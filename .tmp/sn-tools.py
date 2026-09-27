"""Print the live ServiceNow MCP tool names (read-only)."""
import asyncio

from fastmcp import Client

URL = "https://essmcp-caldova-servicenow.livelysky-91807d17.eastus2.azurecontainerapps.io/servicenow/mcp"


async def main() -> None:
    async with Client(URL) as client:
        print(" ".join(sorted(tool.name for tool in await client.list_tools())))


asyncio.run(main())
