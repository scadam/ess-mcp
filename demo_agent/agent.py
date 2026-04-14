"""Minimal agentic loop: FastMCP client + OpenAI tool-calling.

The entire loop is ~12 lines.  Skills are plain-text prompt files in
``skills/`` that tell the LLM what to do with the MCP tools.

Auth note
---------
Each MCP server needs its own Bearer token (Workday, ServiceNow, …).
Tokens are passed via ``ESS_<SERVER>_TOKEN`` env vars and injected as
HTTP headers when connecting.  See ``.env.example`` for the full list.
For production, swap static tokens for a client-credentials or OBO
token provider — the only thing that changes is how you populate the
``headers`` dict below.
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

# ── connect to one MCP server ──────────────────────────────────────


async def connect(name: str, url: str, token: str) -> tuple[Client, list[ChatCompletionToolParam]]:
    """Return a connected ``Client`` and its tools in OpenAI format."""
    transport = StreamableHttpTransport(url, headers={"Authorization": f"Bearer {token}"})
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
) -> str:
    """Run the agentic loop until the LLM produces a final answer."""
    llm = AsyncOpenAI()
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": skill},
        {"role": "user", "content": skill},
    ]

    for _turn in range(int(os.getenv("ESS_MAX_TURNS", "25"))):
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
            try:
                result: Any = await servers[srv].call_tool(
                    tool_name, json.loads(fn.arguments),
                )
            except Exception as exc:
                result = f"Error: {exc}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": str(result)})

    return "Reached turn limit."


# ── CLI entry-point ────────────────────────────────────────────────

SERVER_NAMES = ("workday", "servicenow", "salesforce", "jira")


async def main() -> None:
    load_dotenv()

    # 1. Connect to every configured MCP server
    servers: dict[str, Client] = {}
    all_tools: list[ChatCompletionToolParam] = []
    for name in SERVER_NAMES:
        url = os.getenv(f"ESS_{name.upper()}_MCP_URL", "")
        token = os.getenv(f"ESS_{name.upper()}_TOKEN", "")
        if url and token:
            client, tools = await connect(name, url, token)
            servers[name] = client
            all_tools.extend(tools)
            print(f"  ✅ {name}: {len(tools)} tools")

    if not servers:
        sys.exit("No servers configured — set ESS_<SERVER>_MCP_URL + ESS_<SERVER>_TOKEN")

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
        await run(skill_text, servers, all_tools, model)
    finally:
        for c in servers.values():
            await c.__aexit__(None, None, None)


if __name__ == "__main__":
    asyncio.run(main())
