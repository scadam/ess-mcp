import json
import os

data = json.load(open(os.path.join(os.environ["TEMP"], "ap-itsm-probe.json"), encoding="utf-8"))
lines = []
for name, item in sorted(data["schemas"].items()):
    props = item["schema"].get("properties", {})
    fields = ", ".join(f"{key}{'*' if key in item['schema'].get('required', []) else ''}" for key in props)
    lines.append(f"## {name}: {fields}\n   {item['description'][:300]}")
reads = data["reads"]
incidents = json.loads(reads['list_incidents {"active": true, "limit": 100}'])
lines.append(f"\nincidents keys={sorted(incidents)} n={len(incidents.get('incidents', []))}")
for inc in incidents.get("incidents", [])[:80]:
    lines.append(" | ".join(str(inc.get(k, ""))[:60] for k in ("number", "state", "priority", "category", "short_description", "caller", "assignment_group", "assigned_to", "cmdb_ci", "opened_at")))
team = json.loads(reads["get_team_incidents {}"])
lines.append(f"\nteam keys={sorted(team)}")
lines.append(json.dumps({k: v for k, v in team.items() if not isinstance(v, list)}, default=str)[:800])
catalog = json.loads(reads['list_catalog_items {"limit": 100}'])
lines.append(f"\ncatalog keys={sorted(catalog)} n={len(catalog.get('items', []))}")
for item in catalog.get("items", []):
    lines.append(" | ".join(str(item.get(k, ""))[:50] for k in ("name", "category", "type", "price", "short_description")))
lines.append("\ncategories: " + reads["list_catalog_categories {}"][:300])
knowledge = json.loads(reads["search_knowledge {}"])
lines.append(f"\nknowledge keys={sorted(knowledge)}")
for article in (knowledge.get("articles") or knowledge.get("results") or [])[:60]:
    lines.append(" | ".join(str(article.get(k, ""))[:70] for k in ("number", "short_description", "kb_knowledge_base", "category", "workflow_state")))
for key in ("get_sla_status {}", "list_problems {}", "list_cmdb_cis {}", "list_change_requests {}"):
    lines.append(f"\n{key}: {reads[key][:1500]}")
with open(os.path.join(os.environ["TEMP"], "ap-itsm-summary.txt"), "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines))
