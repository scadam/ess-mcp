"""Print the input parameters the declarative agent plugins declare for the tools the prompts rely on."""

import json
import os
import sys
from pathlib import Path

sys.stdout = open(os.path.join(os.environ["TEMP"], "ap-da-schemas.txt"), "w", encoding="utf-8")
root = Path("declarative_agent/appPackage")
wanted = {
    "workday": ["get_worker", "get_org_chart", "get_direct_reports", "get_team_overview", "get_team_goals", "get_team_performance_summary",
                "get_check_ins", "get_leave_balances", "get_team_calendar", "get_time_off_entries", "prepare_request_leave", "book_leave",
                "get_goals", "get_inbox_tasks"],
    "servicenow": ["search_knowledge", "get_knowledge_article", "list_incidents", "show_create_incident_form", "list_catalog_items",
                   "list_catalog_categories", "get_catalog_item", "list_my_requests", "get_sla_status"],
    "coupa": ["list_it_hardware_orders", "get_category_manager_dashboard", "get_supplier_performance", "get_item_demand",
              "get_servicenow_coupa_flow", "get_invoice_status", "get_po_status", "list_receipts", "reject_invoice", "list_suppliers"],
}
for server, tools in wanted.items():
    plugin = json.loads((root / f"{server}-mcp-plugin.json").read_text(encoding="utf-8"))
    described = {tool["name"]: tool for tool in plugin["runtimes"][0]["spec"]["mcp_tool_description"]["tools"]}
    for name in tools:
        tool = described.get(name)
        if not tool:
            print(f"{server}.{name}: NOT IN PLUGIN")
            continue
        schema = tool.get("inputSchema") or {}
        props = {key: (value.get("type") or [item.get("type") for item in value.get("anyOf", [])]) for key, value in schema.get("properties", {}).items()}
        print(f"{server}.{name}: required={schema.get('required', [])} props={json.dumps(props)}")
        print(f"    {tool.get('description', '')[:300]}")
