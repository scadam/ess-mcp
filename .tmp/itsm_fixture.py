"""Write a trimmed, offline ServiceNow queue fixture (no links or pictures) from the read-only probes."""

import json
import os
from pathlib import Path

probe = json.load(open(os.path.join(os.environ["TEMP"], "ap-itsm-probe.json"), encoding="utf-8"))
reads = probe["reads"]
incidents = json.loads(reads['list_incidents {"active": true, "limit": 100}'])
catalog = json.loads(reads['list_catalog_items {"limit": 100}'])
problems = json.loads(reads["list_problems {}"])
sla = json.loads(reads["get_sla_status {}"])
knowledge = json.loads(reads["search_knowledge {}"])
fixture = {
    "list_incidents": {"total_returned": incidents["total_returned"], "incidents": incidents["incidents"]},
    "list_catalog_items": {"total_returned": catalog["total_returned"], "items": [
        {key: item.get(key) for key in ("sys_id", "name", "short_description", "category", "price", "type")}
        for item in catalog["items"]]},
    "list_problems": {"total_returned": problems["total_returned"], "problems": problems["problems"]},
    "get_sla_status": {key: value for key, value in sla.items() if key != "_instance_url"},
    "search_knowledge": {"total_returned": knowledge.get("total_returned"), "articles": [
        {key: article.get(key) for key in ("number", "short_description", "category", "sys_id")}
        for article in knowledge.get("articles", [])]},
}
Path("demo_agent/tests/fixtures/servicenow_queue.json").write_text(json.dumps(fixture, indent=1), encoding="utf-8")
print({key: len(json.dumps(value)) for key, value in fixture.items()})
print([p["number"] + " " + p["state"] + " " + p["short_description"] for p in problems["problems"]])
