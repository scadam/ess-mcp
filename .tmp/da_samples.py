"""Print compact samples of saved tool results to design the skills around real field names."""

import json
import os
import sys
from pathlib import Path

base = Path(os.environ["TEMP"]) / "da-tests"
sys.stdout = open(Path(os.environ["TEMP"]) / "ap-da-samples.txt", "w", encoding="utf-8")


def clip(value, width=90):
    text = json.dumps(value, default=str)
    return text if len(text) <= width else text[:width] + "…"


def sample(name: str, path: list[str] | None = None, items: int = 2) -> None:
    file = base / f"{name}.json"
    if not file.exists():
        print(f"== {name}: missing")
        return
    data = json.loads(file.read_text(encoding="utf-8"))
    print(f"== {name}")
    for key, value in (data.items() if isinstance(data, dict) else []):
        if isinstance(value, list):
            print(f"  {key}: list[{len(value)}]")
            for entry in value[:items]:
                if isinstance(entry, dict):
                    print("    - " + ", ".join(f"{k}={clip(v, 60)}" for k, v in list(entry.items())[:16]))
                else:
                    print("    - " + clip(entry))
        elif isinstance(value, dict):
            print(f"  {key}: " + ", ".join(f"{k}={clip(v, 70)}" for k, v in list(value.items())[:14]))
        else:
            print(f"  {key}={clip(value)}")


for name in ["workday.get_leave_balances", "workday.get_team_calendar", "workday.get_team_overview",
             "workday.get_team_performance_summary", "workday.get_direct_reports", "workday.get_worker",
             "servicenow.search_knowledge.laptop", "servicenow.search_knowledge.VPN", "servicenow.list_incidents",
             "servicenow.list_my_requests", "servicenow.list_catalog_items.laptop", "coupa.get_supplier_performance",
             "coupa.get_item_demand", "coupa.list_it_hardware_orders", "coupa.get_category_manager_dashboard",
             "coupa.list_receipts", "coupa.get_invoice_status", "coupa.get_po_status"]:
    sample(name)
flows = json.loads((base / "coupa.get_servicenow_coupa_flow.json").read_text(encoding="utf-8"))
print("== coupa.get_servicenow_coupa_flow (first flow)")
first = flows["flows"][0]
for key, value in first.items():
    if isinstance(value, dict):
        print(f"  {key}: " + ", ".join(f"{k}={clip(v, 50)}" for k, v in list(value.items())[:18]))
    elif isinstance(value, list):
        print(f"  {key}: list[{len(value)}] " + (", ".join(f"{k}={clip(v, 40)}" for k, v in list(value[0].items())[:14]) if value and isinstance(value[0], dict) else ""))
    else:
        print(f"  {key}={clip(value)}")
print("  summary: " + clip(flows.get("summary"), 600))
