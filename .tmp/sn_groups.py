"""Read-only: look up ServiceNow group names to route skill tickets (no writes)."""

import asyncio
import json
import os

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

URL = "https://essmcp-caldova-servicenow.livelysky-91807d17.eastus2.azurecontainerapps.io/servicenow/mcp"


async def main() -> None:
    out = {}
    async with Client(StreamableHttpTransport(URL)) as client:
        for search in ("HR", "Procure", "Service Desk", "Hardware", "Help"):
            result = await client.call_tool("search_reference_values", {"table": "sys_user_group", "search": search, "limit": 20})
            text = "\n".join(getattr(part, "text", "") for part in result.content)
            try:
                data = json.loads(text)
                out[search] = [item.get("display_value") or item.get("name") for item in data.get("results", data.get("values", []))]
            except ValueError:
                out[search] = text[:300]
        result = await client.call_tool("list_incidents", {"search_text": "HR backlog", "limit": 5})
        out["hr-backlog-incidents"] = "\n".join(getattr(part, "text", "") for part in result.content)[:600]
    with open(os.path.join(os.environ["TEMP"], "ap-sn-groups.json"), "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=1)


asyncio.run(main())
