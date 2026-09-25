"""Print input schemas and descriptions of selected write tools (listing only; nothing is invoked)."""

from __future__ import annotations

import asyncio
import json
import os

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

BASE = "https://essmcp-caldova-{host}.livelysky-91807d17.eastus2.azurecontainerapps.io/{path}/mcp"
WANTED = {
    "coupa": {"create_requisition", "approve_reject", "reject_invoice", "create_receipt", "update_requisition",
              "get_servicenow_coupa_flow", "get_item_demand", "list_suppliers", "get_supplier_performance",
              "list_approvals", "list_catalog_items", "order_catalog_item"},
    "servicenow": {"create_incident", "update_task", "approve_reject", "list_approvals", "get_team_approvals"},
    "salesforce": {"create_case", "create_task", "update_case", "list_cases"},
    "workday": {"action_inbox_task", "get_inbox_tasks", "get_inbox_task_detail"},
}


async def main() -> None:
    out = {}
    for server, names in WANTED.items():
        client = Client(StreamableHttpTransport(BASE.format(host=server, path=server)))
        async with client:
            tools = await client.list_tools()
            out[server] = {tool.name: {"description": tool.description, "schema": tool.inputSchema}
                           for tool in tools if tool.name in names}
            out[server]["_all"] = sorted(tool.name for tool in tools)
    path = os.path.join(os.environ["TEMP"], "ap-write-schemas.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=1)
    print(path)


asyncio.run(main())
