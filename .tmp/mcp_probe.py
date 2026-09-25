"""Read-only probe through the deployed MCP servers (no local credentials): who Workday 'me' is, and team data."""
import asyncio
import json
import sys

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

BASE = "https://essmcp-caldova-{name}.livelysky-91807d17.eastus2.azurecontainerapps.io/{name}/mcp"


async def call(name: str, tool: str, args: dict | None = None) -> None:
    async with Client(StreamableHttpTransport(BASE.format(name=name)), timeout=90) as client:
        result = await client.call_tool_mcp(tool, args or {})
        text = "".join(getattr(part, "text", "") for part in result.content or [])
        print(f"== {name}.{tool} isError={result.isError}")
        print(text[:2500])


async def main() -> None:
    calls = [("workday", "get_worker"), ("workday", "get_direct_reports"), ("workday", "get_leave_balances"),
             ("workday", "get_inbox_tasks")]
    for name, tool in calls:
        try:
            await call(name, tool)
        except Exception as error:
            print(f"== {name}.{tool} failed: {type(error).__name__}: {str(error)[:300]}")


asyncio.run(main())
