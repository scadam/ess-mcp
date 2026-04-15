"""Web UI for the ESS-MCP demo agent.

Streams tool-call progress to the browser via Server-Sent Events (SSE).
Supports **Azure OpenAI** (managed identity) or **GitHub Models** (PAT).
Run with:  python -m demo_agent.web
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from aiohttp import web

# Suppress noisy background SSE tracebacks from fastmcp/mcp internals.
# These are keep-alive connection failures (logger.exception at ERROR level),
# not user-facing errors.  Set to CRITICAL to hide them entirely.
for _noisy in ("mcp.client.streamable_http", "httpcore", "httpx"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)
from dotenv import load_dotenv
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from openai import AsyncAzureOpenAI, AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

STATIC_DIR = Path(__file__).parent / "static"
SKILLS_DIR = Path(__file__).parent / "skills"
SERVER_NAMES = ("workday", "servicenow", "salesforce", "jira")

# Token budget constants (GitHub Models free-tier limit)
# Only enforced when using GitHub Models; Azure OpenAI has 128K context.
MAX_REQUEST_TOKENS = 8000
COMPLETION_RESERVE = 600

# ── LLM backend ────────────────────────────────────────────────────

GITHUB_MODELS_URL = "https://models.inference.ai.azure.com"

# Resolved once at startup
_use_azure_openai = False


def _create_llm_client() -> AsyncOpenAI:
    """Create an OpenAI-compatible client.

    Priority:
      1. AZURE_OPENAI_ENDPOINT → Azure OpenAI with DefaultAzureCredential
      2. GITHUB_TOKEN          → GitHub Models (8 000-token cap)
    """
    global _use_azure_openai

    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    if azure_endpoint:
        from azure.identity import AzureCliCredential, get_bearer_token_provider

        credential = AzureCliCredential()
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        _use_azure_openai = True
        print(f"  🔑 Using Azure OpenAI at {azure_endpoint} (managed identity)")
        return AsyncAzureOpenAI(
            azure_endpoint=azure_endpoint,
            azure_ad_token_provider=token_provider,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-03-01-preview"),
            max_retries=3,
        )

    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        sys.exit(
            "Either AZURE_OPENAI_ENDPOINT or GITHUB_TOKEN is required.\n"
            "  • Azure OpenAI: set AZURE_OPENAI_ENDPOINT (uses managed identity)\n"
            "  • GitHub Models: set GITHUB_TOKEN (8 000-token limit)\n"
        )
    print("  🔑 Using GitHub Models (8 000-token cap)")
    return AsyncOpenAI(base_url=GITHUB_MODELS_URL, api_key=token)


# ── MCP connections (module-level, populated on startup) ───────────

_servers: dict[str, Client] = {}
_server_configs: dict[str, tuple[str, str]] = {}  # name → (url, token) for reconnect
_all_tools: list[ChatCompletionToolParam] = []


def _estimate_tokens(obj: Any) -> int:
    """Rough token estimate: ~4 chars per token for JSON-serialised content."""
    return len(json.dumps(obj, default=str)) // 4


def _trim_messages(
    messages: list[ChatCompletionMessageParam],
    tool_tokens: int,
) -> list[ChatCompletionMessageParam]:
    """Prune / compress messages so total request fits in MAX_REQUEST_TOKENS.

    Skipped entirely when using Azure OpenAI (128K context).

    Strategy (applied in order until the budget fits):
      1. Truncate tool-result messages to 300 chars
      2. Drop complete assistant+tool groups from the middle
    """
    if _use_azure_openai:
        return messages  # 128K context — no trimming needed

    budget = MAX_REQUEST_TOKENS - tool_tokens - COMPLETION_RESERVE

    if _estimate_tokens(messages) <= budget:
        return messages

    # Pass 1 – compress tool results
    msgs = []
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "tool":
            content = m.get("content", "")
            if isinstance(content, str) and len(content) > 300:
                m = {**m, "content": content[:300] + "…(trimmed)"}
        msgs.append(m)

    if _estimate_tokens(msgs) <= budget:
        return msgs

    # Pass 2 – keep system + user (first 2) and the last complete
    # assistant→tool group.  We walk backwards to find a safe cut point
    # (never orphan tool messages from their assistant message).
    keep_tail = []
    i = len(msgs) - 1
    while i >= 2:
        m = msgs[i]
        keep_tail.insert(0, m)
        # If we just added an assistant message, that's a complete group
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        if role == "assistant":
            break
        i -= 1
    msgs = msgs[:2] + keep_tail

    return msgs


def _slim_schema(schema: dict | None) -> dict:
    """Strip verbose descriptions from parameter schemas to save tokens."""
    if not schema:
        return {"type": "object", "properties": {}}
    out: dict = {"type": schema.get("type", "object")}
    props = schema.get("properties", {})
    out["properties"] = {
        k: {kk: vv for kk, vv in v.items() if kk != "description"}
        for k, v in props.items()
    }
    req = schema.get("required")
    if req:
        out["required"] = req
    return out


def _resilient_httpx_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
    **_kwargs: object,
) -> httpx.AsyncClient:
    """httpx client with transport-level retries for flaky ACA shared-IP TLS."""
    transport = httpx.AsyncHTTPTransport(retries=3)
    kw: dict[str, object] = {"transport": transport, "follow_redirects": True}
    kw["timeout"] = timeout or httpx.Timeout(30.0, read=300.0)
    if headers:
        kw["headers"] = headers
    if auth:
        kw["auth"] = auth
    return httpx.AsyncClient(**kw)


async def connect(name: str, url: str, token: str) -> tuple[Client, list[ChatCompletionToolParam]]:
    """Return a connected Client and its tools in OpenAI format."""
    transport = StreamableHttpTransport(
        url,
        headers={"Authorization": f"Bearer {token}"},
        httpx_client_factory=_resilient_httpx_factory,
    )
    client = Client(transport, name=name)
    await client.__aenter__()
    tools: list[ChatCompletionToolParam] = [
        {
            "type": "function",
            "function": {
                "name": f"{name}__{t.name}",
                "description": (t.description or "")[:100],
                "parameters": _slim_schema(t.inputSchema),
            },
        }
        for t in await client.list_tools()
    ]
    return client, tools


# ── API routes ─────────────────────────────────────────────────────


async def handle_skills(request: web.Request) -> web.Response:
    """Return the list of available skills with their content."""
    skills = []
    for p in sorted(SKILLS_DIR.glob("*.md")):
        skills.append({"name": p.stem, "prompt": p.read_text(encoding="utf-8")})
    return web.json_response(skills)


async def handle_servers(request: web.Request) -> web.Response:
    """Return connected server names and tool counts."""
    info = []
    for name, client in _servers.items():
        tool_count = sum(
            1 for t in _all_tools if t["function"]["name"].startswith(f"{name}__")
        )
        info.append({"name": name, "tools": tool_count})
    return web.json_response(info)


async def _reconnect(name: str) -> None:
    """Reconnect a dropped MCP client using stored config."""
    url, token = _server_configs[name]
    try:
        await _servers[name].__aexit__(None, None, None)
    except Exception:
        pass
    transport = StreamableHttpTransport(
        url,
        headers={"Authorization": f"Bearer {token}"},
        httpx_client_factory=_resilient_httpx_factory,
    )
    client = Client(transport, name=name)
    await asyncio.wait_for(client.__aenter__(), timeout=45)
    _servers[name] = client
    print(f"  🔄 {name}: reconnected")


async def _call_tool_safe(srv: str, tool_name: str, args: dict) -> str:
    """Call an MCP tool with timeout and auto-reconnect on disconnection."""
    for attempt in range(2):
        try:
            result: Any = await asyncio.wait_for(
                _servers[srv].call_tool(tool_name, args), timeout=60
            )
            # Extract just the text content; str() triplicates data
            if hasattr(result, "content") and result.content:
                parts = [c.text for c in result.content if hasattr(c, "text")]
                return "\n".join(parts) if parts else str(result)
            return str(result)
        except asyncio.TimeoutError:
            print(f"  ⚠ {srv}__{tool_name}: timed out (60s)")
            return "Error: tool call timed out after 60s"
        except Exception as exc:
            if attempt == 0 and "not connected" in str(exc).lower():
                print(f"  ⚠ {srv}: disconnected — reconnecting…")
                try:
                    await _reconnect(srv)
                    continue  # retry the tool call
                except Exception as re_exc:
                    return f"Error: reconnect failed: {re_exc}"
            return f"Error: {exc}"
    return "Error: tool call failed after retry"


async def handle_run(request: web.Request) -> web.StreamResponse:
    """Run the agentic loop, streaming progress as SSE."""
    body = await request.json()
    prompt = body.get("prompt", "").strip()
    server_filter = body.get("servers")  # optional list of server names
    print(f"▶ /api/run  prompt={prompt[:80]}…" if len(prompt) > 80 else f"▶ /api/run  prompt={prompt}")
    if not prompt:
        return web.json_response({"error": "prompt is required"}, status=400)

    # Filter tools to requested servers (avoids exceeding token limits)
    if server_filter:
        allowed = set(server_filter)
        tools = [t for t in _all_tools if t["function"]["name"].split("__")[0] in allowed]
    else:
        tools = list(_all_tools)

    resp = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await resp.prepare(request)

    async def send_event(event: str, data: dict) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        await resp.write(payload.encode())

    model = os.getenv("ESS_MODEL", "gpt-4.1")
    max_turns = int(os.getenv("ESS_MAX_TURNS", "25"))
    llm = _create_llm_client()

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": "Execute the task described above."},
    ]

    # Track which servers were actually called (for progressive pruning on GitHub Models)
    used_servers: set[str] = set()

    stats = {
        "model": model,
        "turns": 0,
        "tool_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "start_time": time.time(),
    }

    backend = "Azure OpenAI" if _use_azure_openai else "GitHub Models"
    await send_event("status", {"message": f"Starting with {len(tools)} tools on {model} ({backend})"})

    try:
        for turn in range(max_turns):
            stats["turns"] = turn + 1

            # ── Progressive tool pruning (GitHub Models only) ──
            if not _use_azure_openai and turn > 0 and used_servers:
                tools = [t for t in tools if t["function"]["name"].split("__")[0] in used_servers]

            # ── Token budget: trim messages (GitHub Models only) ──
            tool_tokens = _estimate_tokens(tools)
            messages = _trim_messages(messages, tool_tokens)

            print(f"  ↳ turn {turn+1}: calling {model} with {len(messages)} msgs, {len(tools)} tools (~{tool_tokens + _estimate_tokens(messages)} tok)")
            try:
                completion = await llm.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=tools if tools else None,
                )
            except Exception as api_err:
                err_str = str(api_err)
                if not _use_azure_openai and ("413" in err_str or "tokens_limit_reached" in err_str):
                    # GitHub Models: too many tools — reduce to mentioned servers
                    mentioned = [s for s in _servers if s in prompt.lower()]
                    if mentioned and len(mentioned) < len(_servers):
                        allowed = set(mentioned)
                        tools = [t for t in tools if t["function"]["name"].split("__")[0] in allowed]
                        tool_tokens = _estimate_tokens(tools)
                        messages = _trim_messages(messages, tool_tokens)
                        print(f"  ↳ 413 hit — retrying with {len(tools)} tools (servers: {mentioned})")
                        await send_event("status", {"message": f"Too many tools — retrying with {', '.join(mentioned)} ({len(tools)} tools)"})
                        completion = await llm.chat.completions.create(
                            model=model,
                            messages=messages,
                            tools=tools if tools else None,
                        )
                    else:
                        raise
                else:
                    raise
            print(f"  ↳ turn {turn+1}: got response (finish_reason={completion.choices[0].finish_reason})")
            msg = completion.choices[0].message

            # Accumulate token usage
            if completion.usage:
                stats["prompt_tokens"] += completion.usage.prompt_tokens
                stats["completion_tokens"] += completion.usage.completion_tokens
                stats["total_tokens"] += completion.usage.total_tokens

            if not msg.tool_calls:
                # Final answer
                stats["duration"] = round(time.time() - stats["start_time"], 2)
                await send_event("result", {"content": msg.content or ""})
                await send_event("stats", stats)
                await send_event("done", {})
                return resp

            messages.append(msg)  # type: ignore[arg-type]

            for tc in msg.tool_calls:
                fn = tc.function
                srv, tool_name = fn.name.split("__", 1)
                args = json.loads(fn.arguments)
                stats["tool_calls"] += 1
                used_servers.add(srv)

                await send_event("tool_call", {
                    "id": tc.id,
                    "server": srv,
                    "tool": tool_name,
                    "arguments": args,
                    "index": stats["tool_calls"],
                })

                result_str = await _call_tool_safe(srv, tool_name, args)

                # Cap result length (generous on Azure OpenAI, tight on GitHub Models)
                max_result = 4000 if _use_azure_openai else 800
                if len(result_str) > max_result:
                    result_str = result_str[:max_result] + "…(truncated)"

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

                await send_event("tool_result", {
                    "id": tc.id,
                    "server": srv,
                    "tool": tool_name,
                    "result": result_str[:4000],  # cap for SSE
                })

        # Reached turn limit
        stats["duration"] = round(time.time() - stats["start_time"], 2)
        await send_event("result", {"content": "⚠️ Reached maximum turn limit."})
        await send_event("stats", stats)
        await send_event("done", {})

    except Exception as exc:
        import traceback
        traceback.print_exc()
        await send_event("error", {"message": f"Agent error: {exc}"})
        await send_event("done", {})

    return resp


# ── Static file serving ────────────────────────────────────────────


async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_control_plane(request: web.Request) -> web.FileResponse:
    """Serve the control plane UI."""
    return web.FileResponse(STATIC_DIR / "control-plane.html")


# ── App setup ──────────────────────────────────────────────────────


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/control-plane", handle_control_plane)
    app.router.add_get("/api/skills", handle_skills)
    app.router.add_get("/api/servers", handle_servers)
    app.router.add_post("/api/run", handle_run)
    return app


async def _connect_with_retry(name: str, url: str, token: str, retries: int = 3, timeout: int = 20) -> None:
    """Try to connect to an MCP server with retries.

    The httpx transport already retries connection-level errors (retries=3),
    so each attempt here is already quite resilient.  The outer retry handles
    higher-level failures (session negotiation, timeouts).
    """
    for attempt in range(1, retries + 1):
        try:
            client, tools = await asyncio.wait_for(connect(name, url, token), timeout=timeout)
            _servers[name] = client
            _all_tools.extend(tools)
            print(f"  ✅ {name}: {len(tools)} tools")
            return
        except asyncio.TimeoutError:
            print(f"  ⏳ {name}: attempt {attempt}/{retries} timed out ({timeout}s)")
        except Exception as exc:
            print(f"  ⏳ {name}: attempt {attempt}/{retries} failed ({exc})")
        if attempt < retries:
            await asyncio.sleep(3)
    print(f"  ❌ {name}: gave up after {retries} attempts")


async def init_mcp() -> None:
    """Connect to MCP servers sequentially (same-IP TLS contention with parallel)."""
    load_dotenv()
    for name in SERVER_NAMES:
        url = os.getenv(f"ESS_{name.upper()}_MCP_URL", "")
        token = os.getenv(f"ESS_{name.upper()}_TOKEN", "")
        if url and token:
            _server_configs[name] = (url, token)
            await _connect_with_retry(name, url, token)

    if not _servers:
        print("⚠️  No MCP servers configured — will run in demo-only mode")
        print("   Set ESS_<SERVER>_MCP_URL + ESS_<SERVER>_TOKEN in .env")


async def cleanup_mcp(app: web.Application) -> None:
    for c in _servers.values():
        await c.__aexit__(None, None, None)


def main() -> None:
    port = int(os.getenv("ESS_WEB_PORT", "8091"))
    app = create_app()
    app.on_cleanup.append(cleanup_mcp)

    async def start():
        await init_mcp()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", port)
        await site.start()
        print()
        url = f"http://localhost:{port}"
        inner_w = max(len("ESS-MCP Demo Agent — Web UI"), len(f"→ {url}"), len("Press Ctrl+C to stop")) + 6

        def pad(s: str) -> str:
            return s + " " * (inner_w - len(s))
        print(f"  ╭{'─' * inner_w}╮")
        print(f"  │{' ' * inner_w}│")
        print(f"  │{pad('   ESS-MCP Demo Agent — Web UI')}│")
        print(f"  │{' ' * inner_w}│")
        print(f"  │{pad(f'   → {url}')}│")
        print(f"  │{' ' * inner_w}│")
        print(f"  │{pad('   Press Ctrl+C to stop')}│")
        print(f"  │{' ' * inner_w}│")
        print(f"  ╰{'─' * inner_w}╯")
        print()
        # Keep running
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await runner.cleanup()

    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
