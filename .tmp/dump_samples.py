"""Dump full read-only results for a few tools so skill designs match real data shapes."""

import asyncio
import json
import os
import sys

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

BASE = "https://essmcp-caldova-{host}.livelysky-91807d17.eastus2.azurecontainerapps.io/{path}/mcp"
CALLS = {
    "coupa": [("list_requisitions", {}), ("list_approvals", {}), ("list_receipts", {}), ("list_suppliers", {}),
              ("get_supplier_performance", {}), ("list_it_hardware_orders", {}), ("get_item_demand", {}),
              ("get_servicenow_coupa_flow", {}), ("get_category_manager_dashboard", {}),
              ("get_po_status", {"po_number": "SUP-4101"}), ("get_invoice_status", {"invoice_number": "SUP-4101"})],
    "servicenow": [("list_approvals", {"limit": 5}), ("get_team_approvals", {}), ("list_my_requests", {}),
                   ("get_sla_status", {}), ("list_catalog_items", {"limit": 5})],
    "workday": [("get_inbox_tasks", {}), ("get_org_chart", {}), ("get_team_overview", {}),
                ("get_team_performance_summary", {}), ("get_learning_assignments", {}), ("get_team_calendar", {})],
    "salesforce": [("list_cases", {}), ("list_accounts", {"limit": 5})],
}
HOSTS = {"coupa": ("coupa", "coupa"), "servicenow": ("servicenow", "servicenow"),
         "workday": ("workday", "workday"), "salesforce": ("salesforce", "salesforce")}


async def dump(server: str) -> dict:
    host, path = HOSTS[server]
    out = {}
    for name, args in CALLS[server]:
        try:
            async with Client(StreamableHttpTransport(BASE.format(host=host, path=path)), timeout=45) as client:
                result = await asyncio.wait_for(client.call_tool_mcp(name, args), 40)
                structured = getattr(result, "structuredContent", None)
                text = json.dumps(structured, default=str) if structured is not None else "\n".join(
                    getattr(part, "text", "") or "" for part in (result.content or []))
                try:
                    out[name] = json.loads(text)
                except ValueError:
                    out[name] = text
        except Exception as exc:  # noqa: BLE001
            out[name] = f"{type(exc).__name__}: {str(exc)[:160]}"
    return out


async def main() -> None:
    servers = sys.argv[1:] or list(CALLS)
    results = dict(zip(servers, await asyncio.gather(*(dump(name) for name in servers))))
    path = os.path.join(os.environ.get("TEMP", "."), "ap-data-samples.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(results, handle, indent=1, default=str)
    print(path)


asyncio.run(main())
