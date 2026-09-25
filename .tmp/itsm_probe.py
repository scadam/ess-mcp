"""Read-only probe for the ITSM skill: ServiceNow write-tool schemas plus a sample of queue, knowledge and catalog data."""

import asyncio
import json
import os

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

URL = "https://essmcp-caldova-servicenow.livelysky-91807d17.eastus2.azurecontainerapps.io/servicenow/mcp"
SCHEMAS = {"update_incident", "create_problem", "update_problem", "create_knowledge_article", "order_catalog_item",
           "get_catalog_item", "create_change_request", "list_incidents", "get_team_incidents", "search_knowledge",
           "list_catalog_items", "list_catalog_categories", "list_problems", "get_incident", "list_cmdb_cis",
           "get_sla_status", "list_change_requests"}
READS = [
    ("list_incidents", {"active": True, "limit": 100}),
    ("get_team_incidents", {}),
    ("get_sla_status", {}),
    ("list_problems", {}),
    ("list_catalog_categories", {}),
    ("list_catalog_items", {"limit": 100}),
    ("search_knowledge", {"query": "password"}),
    ("search_knowledge", {"query": "email"}),
    ("search_knowledge", {"query": "VPN"}),
    ("list_cmdb_cis", {}),
    ("list_change_requests", {}),
]


def text(result) -> str:
    return "\n".join(getattr(part, "text", "") or "" for part in (getattr(result, "content", None) or []))


async def main() -> None:
    out = {"schemas": {}, "reads": {}}
    async with Client(StreamableHttpTransport(URL)) as client:
        for tool in await client.list_tools():
            if tool.name in SCHEMAS:
                out["schemas"][tool.name] = {"description": tool.description[:400], "schema": tool.inputSchema}
    for name, args in READS:
        try:
            async with Client(StreamableHttpTransport(URL)) as client:
                schema = out["schemas"].get(name, {}).get("schema", {})
                allowed = set((schema.get("properties") or {}))
                call_args = {key: value for key, value in args.items() if key in allowed}
                result = await client.call_tool(name, call_args)
                out["reads"][f"{name} {json.dumps(call_args)}"] = text(result)
        except Exception as error:  # noqa: BLE001
            out["reads"][f"{name} {json.dumps(args)}"] = f"ERROR {type(error).__name__}: {str(error)[:200]}"
    with open(os.path.join(os.environ["TEMP"], "ap-itsm-probe.json"), "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=1)
    print({key: len(value) for key, value in out["reads"].items()})


asyncio.run(main())
