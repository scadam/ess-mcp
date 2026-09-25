"""List the live ServiceNow MCP tools and show the new catalog/problem-link schema bits (no business data)."""

import asyncio
import json

from fastmcp import Client

URL = "https://essmcp-caldova-servicenow.livelysky-91807d17.eastus2.azurecontainerapps.io/servicenow/mcp"


async def main() -> None:
    async with Client(URL, timeout=60) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
    print("tools", len(tools))
    for name in ("create_catalog_item", "set_catalog_item_active", "order_catalog_item", "update_incident"):
        tool = tools.get(name)
        props = sorted((tool.inputSchema or {}).get("properties", {})) if tool else None
        print(name, "present" if tool else "MISSING", json.dumps(props))


asyncio.run(main())
