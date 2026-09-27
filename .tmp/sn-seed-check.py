"""Call read-only tools on the live ServiceNow MCP server to confirm the crash-scene seed data."""
import asyncio
import json

from fastmcp import Client

URL = "https://essmcp-caldova-servicenow.livelysky-91807d17.eastus2.azurecontainerapps.io/servicenow/mcp"


def _data(result):
    data = getattr(result, "structured_content", None) or getattr(result, "data", None)
    if data is None:
        data = json.loads(result.content[0].text)
    return data


async def main() -> None:
    async with Client(URL) as client:
        names = sorted(tool.name for tool in await client.list_tools())
        print("problem/knowledge/catalog/device tools:",
              [n for n in names if any(k in n for k in ("problem", "knowledge", "kb", "catalog", "device", "asset", "reference"))])
        users = _data(await client.call_tool("search_reference_values", {"table": "sys_user", "search": "Aadi", "limit": 5}))
        print("sys_user 'Aadi':", json.dumps(users)[:300])
        groups = _data(await client.call_tool("search_reference_values",
                                              {"table": "sys_user_group", "search": "Autopilot", "limit": 5}))
        print("groups 'Autopilot':", json.dumps(groups)[:300])
        checks = [("get_user_devices", {"user": "Aadi Kapoor"}),
                  ("list_problems", {"search_text": "MEMORY_MANAGEMENT"}),
                  ("search_knowledge", {"search_text": "out of memory"}),
                  ("list_catalog_items", {"search": "graphics driver rollback"})]
        for name, args in checks:
            try:
                print(name, "->", json.dumps(_data(await client.call_tool(name, args)))[:420])
            except Exception as error:  # Argument names differ per tool; report and continue.
                print(name, "failed:", str(error)[:200])


asyncio.run(main())
