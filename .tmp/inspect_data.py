import collections
import json
import os

data = json.load(open(os.path.join(os.environ["TEMP"], "ap-data-samples.json"), encoding="utf-8"))
tasks = data["workday"]["get_inbox_tasks"]["tasks"]
print("tasks", len(tasks))
for field in ("stepType", "descriptor", "status"):
    print(field, collections.Counter(task.get(field) for task in tasks).most_common(12))
processes = collections.Counter((task.get("overallProcess") or "").split(":")[0] for task in tasks)
print("process", processes.most_common(12))
dues = sorted(task.get("due") or "" for task in tasks)
print("due range", dues[0], dues[-1])
calendar = data["workday"]["get_team_calendar"]
print("team", [(m["name"], len(m.get("timeOff") or [])) for m in calendar["teamMembers"]])
flows = data["coupa"]["get_servicenow_coupa_flow"]["flows"]
for flow in flows:
    print("flow", flow.get("service-now-request"), flow.get("status"), flow.get("blocked-reason"), flow.get("open-value"),
          "receipt" if flow.get("receipt") else "-", "invoice" if flow.get("invoice") else "-",
          sorted(k for k in flow.keys())[:30])
    break
for flow in flows:
    print(" ", flow.get("service-now-request"), flow.get("status"), "|", flow.get("blocked-reason"), "|", flow.get("open-value"),
          "| inv:", (flow.get("invoice") or {}).get("status") if isinstance(flow.get("invoice"), dict) else flow.get("invoice"),
          "| rcpt:", (flow.get("receipt") or {}).get("status") if isinstance(flow.get("receipt"), dict) else flow.get("receipt"))
suppliers = data["coupa"]["list_suppliers"]["results"]
for supplier in suppliers:
    print("supplier", supplier["name"], supplier["tier"], supplier["risk"], supplier.get("contract"), supplier.get("metrics"))
for item in data["coupa"]["get_item_demand"]["items"]:
    print("item", item["id"], item["stock"], item["monthly-demand"], item["lead-time-days"], item["stock_coverage_months"], item["risk"], item.get("open_quantity"))
print("approvals", json.dumps(data["coupa"]["list_approvals"]["results"], indent=0)[:1500])
print("alerts", json.dumps(data["coupa"]["get_category_manager_dashboard"]["alerts"], indent=0)[:1200])
