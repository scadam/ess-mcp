"""Write trimmed, offline test fixtures from the read-only probe samples (no URLs, no tenant links)."""

from __future__ import annotations

import json
import os
from pathlib import Path

samples = json.load(open(os.path.join(os.environ["TEMP"], "ap-data-samples.json"), encoding="utf-8"))
print({server: sorted(tools) for server, tools in samples.items()} if isinstance(samples, dict) else type(samples))


def parsed(server: str, tool: str):
    value = samples[server][tool]
    if isinstance(value, dict) and "text" in value:
        value = value["text"]
    return json.loads(value) if isinstance(value, str) else value


out = Path("demo_agent/tests/fixtures")
out.mkdir(parents=True, exist_ok=True)
coupa = {name: parsed("coupa", name) for name in (
    "get_servicenow_coupa_flow", "get_item_demand", "list_suppliers", "list_approvals", "get_category_manager_dashboard")}
(out / "coupa_snapshot.json").write_text(json.dumps(coupa, indent=1), encoding="utf-8")
inbox = parsed("workday", "get_inbox_tasks")
for task in inbox.get("tasks", []):
    task.pop("href", None)
    task.pop("link", None)
(out / "workday_inbox.json").write_text(json.dumps(inbox, indent=1), encoding="utf-8")
demand = coupa["get_item_demand"]["items"]
for item in demand:
    print(item["id"], item["unit-price"], item["supplier-id"], item["lead-time-days"], item["contracted"], item["stock"],
          item["monthly-demand"], item.get("open_quantity"), item["stock_coverage_months"], item["risk"])
for supplier in coupa["list_suppliers"]["results"]:
    print(supplier["id"], supplier["name"], supplier["tier"], supplier["risk"], supplier["preferred"], supplier["contract"],
          supplier.get("metrics"))
for approval in coupa["list_approvals"]["results"]:
    print(approval)
for alert in coupa["get_category_manager_dashboard"].get("alerts", []):
    print(alert)
for flow in coupa["get_servicenow_coupa_flow"]["flows"]:
    order = flow["purchase_order"]
    print(flow["service-now-request"], order["po-number"], order["expected-delivery"], order.get("days-to-delivery"),
          order.get("days-open"), order.get("delivery-risk"), flow["blocked-reason"],
          [(line["item-id"], line["quantity"], line.get("received"), line["unit-price"]) for line in order["lines"]])
