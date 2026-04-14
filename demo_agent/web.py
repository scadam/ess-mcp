"""Web UI for the ESS-MCP demo agent.

Streams tool-call progress to the browser via Server-Sent Events (SSE).
Run with:  python -m demo_agent.web
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from aiohttp import web
from dotenv import load_dotenv
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

STATIC_DIR = Path(__file__).parent / "static"
SKILLS_DIR = Path(__file__).parent / "skills"
SERVER_NAMES = ("workday", "servicenow", "salesforce", "jira")

# ── MCP connections (module-level, populated on startup) ───────────

_servers: dict[str, Client] = {}
_all_tools: list[ChatCompletionToolParam] = []


async def connect(name: str, url: str, token: str) -> tuple[Client, list[ChatCompletionToolParam]]:
    """Return a connected Client and its tools in OpenAI format."""
    transport = StreamableHttpTransport(url, headers={"Authorization": f"Bearer {token}"})
    client = Client(transport, name=name)
    await client.__aenter__()
    tools: list[ChatCompletionToolParam] = [
        {
            "type": "function",
            "function": {
                "name": f"{name}__{t.name}",
                "description": t.description or "",
                "parameters": t.inputSchema or {"type": "object", "properties": {}},
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
        skills.append({"name": p.stem, "prompt": p.read_text()})
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


async def handle_run(request: web.Request) -> web.StreamResponse:
    """Run the agentic loop, streaming progress as SSE."""
    body = await request.json()
    prompt = body.get("prompt", "").strip()
    if not prompt:
        return web.json_response({"error": "prompt is required"}, status=400)

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
    llm = AsyncOpenAI()

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": "Execute the task described above."},
    ]

    stats = {
        "model": model,
        "turns": 0,
        "tool_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "start_time": time.time(),
    }

    await send_event("status", {"message": f"Starting with {len(_all_tools)} tools on {model}"})

    try:
        for turn in range(max_turns):
            stats["turns"] = turn + 1
            completion = await llm.chat.completions.create(
                model=model,
                messages=messages,
                tools=_all_tools if _all_tools else None,
            )
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

                await send_event("tool_call", {
                    "id": tc.id,
                    "server": srv,
                    "tool": tool_name,
                    "arguments": args,
                    "index": stats["tool_calls"],
                })

                try:
                    result: Any = await _servers[srv].call_tool(tool_name, args)
                    result_str = str(result)
                except Exception as exc:
                    result_str = f"Error: {exc}"

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

    except Exception:
        await send_event("error", {"message": "An internal error occurred while running the agent."})
        await send_event("done", {})

    return resp


# ── Static file serving ────────────────────────────────────────────


async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


# ── App setup ──────────────────────────────────────────────────────


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/skills", handle_skills)
    app.router.add_get("/api/servers", handle_servers)
    app.router.add_post("/api/run", handle_run)
    return app


async def init_mcp() -> None:
    """Connect to all configured MCP servers."""
    load_dotenv()
    for name in SERVER_NAMES:
        url = os.getenv(f"ESS_{name.upper()}_MCP_URL", "")
        token = os.getenv(f"ESS_{name.upper()}_TOKEN", "")
        if url and token:
            client, tools = await connect(name, url, token)
            _servers[name] = client
            _all_tools.extend(tools)
            print(f"  ✅ {name}: {len(tools)} tools")

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
