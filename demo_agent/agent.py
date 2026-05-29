"""Hosted autonomous agent loop using **GitHub Models** + governed MCP.

This demo shows how to build an autonomous agent that:
1. Runs with an Entra Agent Identity / Agent Identity Blueprint
2. Connects to governed Workday and ServiceNow MCP endpoints via FastMCP
3. Sends the discovered tools + a skill prompt to a model via the
   **GitHub Models** inference API
4. Acquires per-system OAuth bearer tokens before calling MCP tools
5. Executes tool calls in a loop until the model produces a final answer

The entire agentic loop is ~15 lines.  Skills are plain-text markdown
prompts in ``skills/`` that tell the model what to do with the MCP tools.

GitHub Models
-------------
Instead of calling the OpenAI API directly, this agent uses the
**GitHub Models** inference endpoint (``https://models.inference.ai.azure.com``).
Authentication is via a **GitHub Personal Access Token** (``GITHUB_TOKEN``).
This means model usage is billed through your **GitHub Copilot** subscription
— no separate OpenAI key is needed.

See the README for full details on how the agent runs and pricing.

MCP auth note
-------------
Each MCP server needs its own Bearer token. In hosted mode, the agent uses its
own Entra Agent Identity to acquire OAuth tokens for Workday and ServiceNow,
then passes those tokens through the governed MCP endpoint. Static
``ESS_<SERVER>_TOKEN`` values remain supported for local development only.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

from .identity import AgentIdentityContext, agent_headers
from .observability import AgentTelemetry, ObservedToolCall, now_ms
from .oauth import EnvOrOAuthTokenProvider, ServerTokenProvider

# ── GitHub Models endpoint ─────────────────────────────────────────

GITHUB_MODELS_URL = "https://models.inference.ai.azure.com"


def _create_llm_client() -> AsyncOpenAI:
    """Create an OpenAI-compatible client pointed at GitHub Models."""
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        sys.exit(
            "GITHUB_TOKEN is required.\n"
            "Create a Personal Access Token at https://github.com/settings/tokens\n"
            "and set it in your .env file."
        )
    return AsyncOpenAI(base_url=GITHUB_MODELS_URL, api_key=token)


# ── connect to one MCP server ──────────────────────────────────────


def mcp_url_for(name: str, context: AgentIdentityContext) -> str:
    """Resolve the MCP URL, preferring the AI Gateway route when configured."""
    direct = os.getenv(f"ESS_{name.upper()}_MCP_URL", "")
    gateway = os.getenv(f"ESS_{name.upper()}_AI_GATEWAY_MCP_URL", "")
    if gateway:
        return gateway
    if context.gateway_base_url:
        return context.gateway_base_url.rstrip("/") + f"/{name}/mcp"
    return direct


async def connect(
    name: str,
    url: str,
    token_provider: ServerTokenProvider,
    context: AgentIdentityContext,
) -> tuple[Client, list[ChatCompletionToolParam]]:
    """Return a connected ``Client`` and its tools in OpenAI format."""
    token = await token_provider.get_token(name)
    headers = {"Authorization": f"Bearer {token}", **agent_headers(context)}
    transport = StreamableHttpTransport(url, headers=headers)
    client = Client(transport, name=name)
    await client.__aenter__()
    tools: list[ChatCompletionToolParam] = [
        {
            "type": "function",
            "function": {
                "name": f"{name}__{t.name}",
                "description": t.description or "",
                "parameters": t.inputSchema or {"type": "object", "properties": {}},  # type: ignore[typeddict-item]
            },
        }
        for t in await client.list_tools()
    ]
    return client, tools


# ── the agentic loop ───────────────────────────────────────────────


async def run(
    skill: str,
    servers: dict[str, Client],
    tools: list[ChatCompletionToolParam],
    model: str,
    context: AgentIdentityContext | None = None,
) -> str:
    """Run the agentic loop until the model produces a final answer."""
    context = context or AgentIdentityContext.from_env()
    telemetry = AgentTelemetry(context)
    llm = _create_llm_client()
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": skill + context.system_prompt_preamble()},
        {"role": "user", "content": "Execute the task described above."},
    ]

    with telemetry.span("agent.run", model=model, tool_count=len(tools)):
        for _turn in range(int(os.getenv("ESS_MAX_TURNS", "25"))):
            with telemetry.span("agent.llm", turn=_turn + 1):
                resp = await llm.chat.completions.create(
                    model=model, messages=messages, tools=tools if tools else None,  # type: ignore[arg-type]
                )
            msg = resp.choices[0].message

            if not msg.tool_calls:                              # final answer
                print(msg.content or "")
                return msg.content or ""

            messages.append(msg)  # type: ignore[arg-type]      # record assistant turn
            for tc in msg.tool_calls:                           # execute each tool call
                fn = tc.function  # type: ignore[union-attr]
                srv, tool_name = fn.name.split("__", 1)
                print(f"  🔧 {srv}/{tool_name}")
                args = json.loads(fn.arguments)
                started_ms = now_ms()
                success = True
                error = ""
                with telemetry.span("agent.tool", server=srv, tool=tool_name):
                    try:
                        result: Any = await servers[srv].call_tool(tool_name, args)
                    except Exception as exc:
                        result = f"Error: {exc}"
                        success = False
                        error = str(exc)
                telemetry.observe_tool_call(
                    ObservedToolCall(
                        call_id=tc.id,
                        server=srv,
                        tool=tool_name,
                        arguments=args,
                        result=result,
                        duration_ms=now_ms() - started_ms,
                        success=success,
                        error=error,
                    )
                )
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})

    return "Reached turn limit."


# ── CLI entry-point ────────────────────────────────────────────────

SERVER_NAMES = ("workday", "servicenow", "coupa")


async def main() -> None:
    load_dotenv()

    # 1. Connect to every configured MCP server
    context = AgentIdentityContext.from_env()
    token_provider = EnvOrOAuthTokenProvider()
    servers: dict[str, Client] = {}
    all_tools: list[ChatCompletionToolParam] = []
    for name in SERVER_NAMES:
        url = mcp_url_for(name, context)
        if url:
            client, tools = await connect(name, url, token_provider, context)
            servers[name] = client
            all_tools.extend(tools)
            print(f"  ✅ {name}: {len(tools)} tools")

    if not servers:
        sys.exit("No servers configured — set ESS_<SERVER>_AI_GATEWAY_MCP_URL or ESS_<SERVER>_MCP_URL")

    # 2. Load the skill prompt
    skill_arg = sys.argv[1] if len(sys.argv) > 1 else None
    if not skill_arg:
        skills_dir = Path(__file__).parent / "skills"
        available = sorted(p.stem for p in skills_dir.glob("*.md"))
        sys.exit(f"Usage: python -m demo_agent.agent <skill>\nAvailable: {', '.join(available)}")

    skill_path = Path(__file__).parent / "skills" / f"{skill_arg}.md"
    if not skill_path.exists():
        sys.exit(f"Skill not found: {skill_path}")
    skill_text = skill_path.read_text()

    # 3. Run the loop
    model = os.getenv("ESS_MODEL", "gpt-4.1")
    print(f"\n🚀 Running skill '{skill_arg}' with {len(all_tools)} tools on {model}\n")
    try:
        await run(skill_text, servers, all_tools, model, context)
    finally:
        for c in servers.values():
            await c.__aexit__(None, None, None)


if __name__ == "__main__":
    asyncio.run(main())
