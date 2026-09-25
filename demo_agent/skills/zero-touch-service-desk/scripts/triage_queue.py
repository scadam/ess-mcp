"""Triage the ServiceNow incident queue: classify, cluster and plan a zero-touch resolution for every incident.

Usage: triage_queue.py [--as-of YYYY-MM-DD] [--numbers INC1,INC2] [--stale-days 180]
Reads data/servicenow/ (list_incidents, get_team_incidents, list_problems, list_catalog_items, search_knowledge,
get_sla_status) and writes analysis/queue.json and reports/queue.csv. Standard library only.
"""

from __future__ import annotations

import csv
import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import date, datetime

# (kind, topic, pattern) — first match wins, so specific rules precede generic ones. test/howto read the subject only.
RULES = [
    ("test", "test-record", r"\batf\b|assessment\s*:|\btest\d*\b"),
    ("howto", "how-to", r"^how (do|can|to)\b|\bhow do i\b"),
    ("dispatch", "facilities", r"\bleak|\bwater\b|\bflood|\bfire\b|\bsmoke\b|burning|power cut"),
    ("outage", "sap", r"\bsap\b"),
    ("outage", "email", r"\be-?mail\b|\bexchange\b|mail server|\boutlook\b"),
    ("outage", "network", r"wireless|wi-?fi|network storage|network file|\bnetwork\b.*\b(down|unavailable)\b"),
    ("request", "file-share-access", r"shared folder|common drive|file share|team drive|shared drive"),
    ("request", "database-access", r"access to .*\b(db|database)\b"),
    ("request", "mobile-device", r"\biphone\b|replacement phone|new phone|mobile device"),
    ("request", "laptop-memory", r"\b(memory|ram)\b.*\blaptop\b|\blaptop\b.*\b(memory|ram)\b"),
    ("request", "new-service", r"request for a new service"),
    ("known_fix", "software-removal", r"remove .*(hotfix|update|patch)|uninstall"),
    ("known_fix", "vpn-client", r"\bvpn\b"),
    ("known_fix", "desk-phone", r"desk phone|telephone"),
    ("known_fix", "read-only-file", r"read[ -]only"),
    ("known_fix", "virtualization", r"virtual machine|\bvm\b|64-bit"),
    ("known_fix", "weather", r"\bweather\b"),
    ("known_fix", "wiki-posting", r"\bwiki\b"),
    ("t2", "enhancement", r"\bconfigure\b|add (additional |more )?fields|customi[sz]e|remove a few buttons"),
    ("t2", "web-defect", r"javascript|website|web page"),
    ("outage", "service-down", r"\bis down\b|\boutage\b|server is down|\bunavailable\b"),
    ("t2", "app-access", r"can.?t (access|log)|cannot access|unable to access|not accessible|\blogin\b"),
    ("t2", "performance", r"performance|\bslow\b"),
]
TOPICS = {  # Knowledge search words, the resolver group, and the problem/KB wording.
    "sap": {"words": ["sap"], "group": "Software", "title": "SAP applications unavailable or degraded"},
    "email": {"words": ["email", "exchange", "mail server", "outlook"], "group": "Software", "title": "Email service outage and degradation"},
    "network": {"words": ["wireless", "wifi", "network storage", "file share"], "group": "Network", "title": "Wireless and network storage outage"},
    "service-down": {"words": ["down"], "group": "Hardware", "title": "Application server down"},
    "file-share-access": {"words": ["share", "shared drive", "folder"], "group": "Service Desk", "title": "Shared drive access"},
    "database-access": {"words": ["database"], "group": "Database", "title": "Database access"},
    "mobile-device": {"words": ["iphone", "phone"], "group": "Hardware", "title": "Mobile device replacement"},
    "laptop-memory": {"words": ["memory", "ram"], "group": "Hardware", "title": "Laptop memory upgrade"},
    "new-service": {"words": ["service"], "group": "Service Desk", "title": "New service request"},
    "how-to": {"words": ["sub-folder", "subfolder", "folder"], "group": "Service Desk", "title": "Create a sub-folder in Outlook"},
    "software-removal": {"words": ["uninstall", "roll back", "hotfix"], "group": "Software", "title": "Remove a Windows update or hotfix"},
    "vpn-client": {"words": ["vpn"], "group": "Network", "title": "VPN client fails after a software update"},
    "desk-phone": {"words": ["phone"], "group": "Hardware", "title": "Desk phone not working"},
    "read-only-file": {"words": ["read only", "read-only"], "group": "Service Desk", "title": "Office file opens read-only"},
    "virtualization": {"words": ["virtual", "vm"], "group": "Software", "title": "64-bit virtual machine will not start"},
    "weather": {"words": ["weather"], "group": "Service Desk", "title": "Weather report not showing"},
    "wiki-posting": {"words": ["wiki"], "group": "Software", "title": "Cannot post to the wiki"},
    "enhancement": {"words": [], "group": "Software", "title": "Enhancement request"},
    "web-defect": {"words": ["javascript", "website"], "group": "Software", "title": "Corporate website defect"},
    "app-access": {"words": ["access", "login", "password"], "group": "Software", "title": "Application access problems"},
    "performance": {"words": ["performance", "slow"], "group": "Software", "title": "Application performance problems"},
    "facilities": {"words": ["leak", "water"], "group": "Hardware", "title": "Physical damage to equipment"},
    "test-record": {"words": [], "group": "", "title": "Automated test records"},
}
CATALOG = {  # Dedicated item words, fallback items that can fulfil today, and the item to build when missing.
    "mobile-device": {"match": ["iphone"], "fallback": [], "build": None},
    "file-share-access": {"match": ["file share", "shared drive", "shared folder", "drive access"],
                          "fallback": ["group modifications", "temporary group membership"],
                          "build": {"name": "Shared drive access", "category": "Application and Account Access",
                                    "fulfillment_group": "Service Desk", "short_description": "Request read or read/write access to a shared drive or team folder",
                                    "variables": [
                                        {"name": "share_path", "question": "Which shared drive or folder? (for example \\\\fs01\\finance)", "type": "single_line", "mandatory": True},
                                        {"name": "access_level", "question": "Access needed", "type": "select", "choices": ["Read", "Read/write"], "mandatory": True},
                                        {"name": "business_reason", "question": "Why do you need access?", "type": "multi_line", "mandatory": True},
                                        {"name": "end_date", "question": "Access needed until (leave blank if permanent)", "type": "date"}]}},
    "database-access": {"match": ["database access", "db access"], "fallback": ["temporary group membership"],
                        "build": {"name": "Database access request", "category": "Application and Account Access",
                                  "fulfillment_group": "Database", "short_description": "Request read or write access to a business database",
                                  "variables": [
                                      {"name": "database", "question": "Which database or report?", "type": "single_line", "mandatory": True},
                                      {"name": "access_level", "question": "Access needed", "type": "select", "choices": ["Read", "Write"], "mandatory": True},
                                      {"name": "business_reason", "question": "Why do you need access?", "type": "multi_line", "mandatory": True}]}},
    "laptop-memory": {"match": ["memory upgrade", "ram upgrade"], "fallback": [],
                      "build": {"name": "Laptop memory upgrade", "category": "Hardware", "fulfillment_group": "Hardware",
                                "short_description": "Request a memory (RAM) upgrade for your laptop",
                                "variables": [
                                    {"name": "asset_tag", "question": "Laptop asset tag", "type": "single_line", "mandatory": True},
                                    {"name": "current_memory", "question": "Current memory", "type": "select", "choices": ["8 GB", "16 GB", "32 GB"], "mandatory": True},
                                    {"name": "business_reason", "question": "What are you running that needs more memory?", "type": "multi_line", "mandatory": True}]}},
}
BUILD_THRESHOLD = 2
ORDER_LIMIT = 1500.0
CLOSE_CODES = {"howto": "Solution provided", "known_fix": "Workaround provided", "request": "Resolved by request"}
SOLUTION_TOPICS = {"virtualization", "weather"}  # The answer is the fix, not a workaround.
GENERIC = {"with", "from", "your", "that", "this", "after", "will", "does", "working", "cannot", "issue", "issues",
           "problem", "problems", "request", "access", "application", "applications", "service", "questions"}
STOPWORDS = {"the", "and", "for", "can", "not", "with", "from", "my", "is", "to", "of", "in", "on", "a", "an", "i",
             "unable", "cannot", "cant", "having", "issue", "issues", "problem", "problems", "today", "again"}


def significant(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", str(text or "").lower()) if len(word) > 1 and word not in STOPWORDS}


def keywords(*texts: str, extra: list[str] | None = None) -> list[str]:
    words = {word for text in texts for word in re.findall(r"[a-z][a-z-]{3,}", text.lower()) if word not in GENERIC}
    return sorted(words | set(extra or []))


def load(pattern: str) -> list:
    docs = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="utf-8") as handle:
                docs.append(json.load(handle))
        except (OSError, ValueError):
            print(f"warning: {path} is not JSON; skipped", file=sys.stderr)
    return docs


def records(docs: list, *keys: str) -> list[dict]:
    return [item for doc in docs if isinstance(doc, dict) for key in keys
            if isinstance(doc.get(key), list) for item in doc[key] if isinstance(item, dict)]


def parse_day(value) -> date | None:
    try:
        return datetime.fromisoformat(str(value)[:19]).date()
    except ValueError:
        return None


def price(value) -> float:
    try:
        return float(re.sub(r"[^0-9.]", "", str(value or "")) or 0)
    except ValueError:
        return 0.0


def classify(incident: dict) -> tuple[str, str]:
    text = f"{incident.get('short_description') or ''} {incident.get('description') or ''}".lower()
    subject = str(incident.get("short_description") or "").lower().strip()
    for kind, topic, pattern in RULES:
        if re.search(pattern, subject if kind in {"test", "howto"} else text):
            return kind, topic
    return "t2", "general"


def main(argv: list[str]) -> int:
    today = date.fromisoformat(argv[argv.index("--as-of") + 1]) if "--as-of" in argv else date.today()
    stale_days = int(argv[argv.index("--stale-days") + 1]) if "--stale-days" in argv else 180
    only = set(argv[argv.index("--numbers") + 1].split(",")) if "--numbers" in argv else None
    incidents: dict[str, dict] = {}
    for item in records(load("data/servicenow/list_incidents*.json") + load("data/servicenow/get_team_incidents*.json"), "incidents"):
        if item.get("number") and str(item.get("active", "true")).lower() != "false" and item.get("state") not in {"Resolved", "Closed", "Canceled"}:
            incidents.setdefault(item["number"], item)
    if only:
        incidents = {number: item for number, item in incidents.items() if number in only}
    if not incidents:
        print("No active incidents in the workspace: call servicenow list_incidents (active, limit 100) first, then rerun.")
        return 2
    problems = records(load("data/servicenow/list_problems*.json"), "problems")
    catalog = {item["sys_id"]: item for item in records(load("data/servicenow/list_catalog_items*.json"), "items") if item.get("sys_id")}
    articles = {item.get("number"): item for item in records(load("data/servicenow/search_knowledge*.json"), "articles") if item.get("number")}
    breached = {item.get("task") for item in records(load("data/servicenow/get_sla_status*.json"), "sla_records") if item.get("has_breached")}

    def knowledge(topic: str) -> list[dict]:
        words = TOPICS.get(topic, {}).get("words", [])
        return [{"number": number, "title": " ".join(str(item.get("short_description") or "").split())}
                for number, item in articles.items()
                if words and any(word in str(item.get("short_description") or "").lower() for word in words)][:3]

    def catalog_match(topic: str) -> tuple[dict | None, bool]:
        rule = CATALOG.get(topic)
        if not rule:
            return None, False
        def found(words: list[str]) -> list[dict]:
            return sorted((item for item in catalog.values()
                           if any(word in f"{item.get('name', '')} {item.get('short_description', '')}".lower() for word in words)),
                          key=lambda item: (price(item.get("price")) or 0, item.get("name", "")))
        exact = found(rule["match"])
        if exact:
            return exact[0], True
        fallback = found(rule["fallback"])
        return (fallback[0] if fallback else None), False

    plans, clusters = [], defaultdict(list)
    for number, incident in sorted(incidents.items()):
        kind, topic = classify(incident)
        opened, updated = parse_day(incident.get("opened_at")), parse_day(incident.get("sys_updated_on"))
        stale = bool(updated and (today - updated).days > stale_days)
        plan: dict = {"number": number, "short_description": " ".join(str(incident.get("short_description") or "").split()),
                      "kind": kind, "topic": topic, "state": incident.get("state"), "priority": incident.get("priority"),
                      "opened_by": incident.get("opened_by") or "", "assignment_group": incident.get("assignment_group") or "",
                      "age_days": (today - opened).days if opened else None, "stale": stale,
                      "sla_breached": number in breached, "knowledge": knowledge(topic), "notes": []}
        group = incident.get("assignment_group") or TOPICS.get(topic, {}).get("group", "Service Desk")
        dedicated = False
        if kind == "test":
            plan["action"] = {"do": "cancel", "state": "canceled",
                              "work_notes": "Automated test (ATF) record in the live queue; cancelled during queue hygiene."}
        elif kind == "dispatch":
            plan["action"] = {"do": "dispatch", "assignment_group": group, "urgency": "1",
                              "why": "Physical fault: needs an on-site engineer now."}
        elif kind == "outage":
            clusters[topic].append(number)
            plan["action"] = {"do": "link_problem", "cluster": topic}
        elif kind == "request":
            item, dedicated = catalog_match(topic)
            if item and dedicated and price(item.get("price")) <= ORDER_LIMIT:
                plan["action"] = {"do": "order_and_resolve", "close_code": CLOSE_CODES["request"],
                                  "catalog_item": {"sys_id": item["sys_id"], "name": item.get("name"), "price": item.get("price")},
                                  "requested_for": plan["opened_by"]}
            elif item:
                plan["action"] = {"do": "order_and_resolve", "close_code": CLOSE_CODES["request"],
                                  "catalog_item": {"sys_id": item["sys_id"], "name": item.get("name"), "price": item.get("price")},
                                  "requested_for": plan["opened_by"], "interim": True}
                plan["notes"].append(f"No dedicated catalog item; {item.get('name')} fulfils it today.")
            elif topic == "new-service":
                plan["action"] = {"do": "ask_caller", "state": "on_hold",
                                  "why": "The request doesn't say which service is needed."}
            else:
                plan["action"] = {"do": "dispatch", "assignment_group": group, "why": "No catalog item fulfils this yet."}
            if topic in CATALOG and not dedicated:
                clusters["gap:" + topic].append(number)
        elif kind in {"howto", "known_fix"}:
            plan["action"] = {"do": "resolve", "close_code": CLOSE_CODES["howto" if topic in SOLUTION_TOPICS else kind],
                              "cite": [article["number"] for article in plan["knowledge"]] or None}
            if not plan["knowledge"]:
                clusters["kb:" + topic].append(number)
        else:
            plan["action"] = {"do": "diagnose_and_route", "assignment_group": group,
                              "why": "Needs an engineer: diagnose, give the caller a workaround and hand over complete diagnostics."}
            if topic == "web-defect":
                clusters[topic].append(number)
                plan["action"] = {"do": "link_problem", "cluster": topic}
        if stale and plan["action"]["do"] in {"diagnose_and_route", "dispatch", "order_and_resolve", "ask_caller"}:
            days = (today - updated).days
            plan["action"] = {"do": "resolve", "close_code": "No resolution provided", "stale_days": days,
                              "self_service": (plan["action"].get("catalog_item") or {}).get("name") if dedicated else None}
            plan["notes"].append(f"No update for {days} days: close with a reopen invitation rather than spend engineering time.")
        plans.append(plan)

    open_problems = [problem for problem in problems if problem.get("state") not in {"Closed", "Resolved", "Canceled"}]
    problem_plans = []
    for topic, numbers in sorted(clusters.items()):
        if topic.startswith(("gap:", "kb:")):
            continue
        words = TOPICS.get(topic, {}).get("words", [])
        existing = next((problem for problem in open_problems
                         if any(word in str(problem.get("short_description") or "").lower() for word in words)), None)
        if len(numbers) < 2 and topic != "web-defect":
            for plan in plans:
                if plan["number"] in numbers:
                    plan["action"] = {"do": "diagnose_and_route", "assignment_group": plan["assignment_group"] or TOPICS[topic]["group"],
                                      "why": "Single report of a service fault: confirm scope and hand over diagnostics."}
            continue
        problem_plans.append({
            "cluster": topic, "incidents": numbers, "existing_problem": (existing or {}).get("number"),
            "keywords": sorted(set(words) | {topic}),
            "draft": None if existing else {
                "short_description": f"{TOPICS[topic]['title']} ({len(numbers)} incident{'s' if len(numbers) != 1 else ''})",
                "category": "Software" if TOPICS[topic]["group"] == "Software" else TOPICS[topic]["group"],
                "priority": "1" if len(numbers) >= 3 else "2", "impact": "1" if len(numbers) >= 3 else "2",
                "urgency": "1" if len(numbers) >= 3 else "2", "assignment_group": TOPICS[topic]["group"],
                "description": "Related incidents: " + ", ".join(numbers) + ". Raised by the service desk agent from the queue triage."}})
    # A lone fault that an open problem already describes is linked to it, not handed to an engineer.
    for plan in plans:
        if plan["action"]["do"] != "diagnose_and_route":
            continue
        words = significant(plan["short_description"])
        for problem in open_problems:
            shared = words & significant(problem.get("short_description"))
            if len(shared) >= 2 and len(shared) >= 0.6 * len(significant(problem.get("short_description"))):
                cluster = f"known-{problem['number']}"
                plan["action"] = {"do": "link_problem", "cluster": cluster}
                plan["notes"].append(f"{problem['number']} ({problem.get('state')}) already covers this fault.")
                problem_plans.append({"cluster": cluster, "incidents": [plan["number"]], "existing_problem": problem["number"],
                                      "keywords": sorted(shared), "draft": None})
                break
    kb_gaps = [{"topic": key[3:], "incidents": numbers, "title": TOPICS.get(key[3:], {}).get("title", key[3:]),
                "keywords": keywords(TOPICS.get(key[3:], {}).get("title", ""), extra=TOPICS.get(key[3:], {}).get("words"))}
               for key, numbers in sorted(clusters.items()) if key.startswith("kb:")]
    catalog_gaps = []
    for key, numbers in sorted(clusters.items()):
        if not key.startswith("gap:"):
            continue
        topic = key[4:]
        spec = CATALOG[topic]["build"]
        build = bool(spec) and len(numbers) >= BUILD_THRESHOLD
        catalog_gaps.append({"topic": topic, "incidents": numbers, "build": build, "spec": spec,
                             "keywords": keywords((spec or {}).get("name", ""), extra=CATALOG[topic]["match"]),
                             "why": (f"{len(numbers)} {'person' if len(numbers) == 1 else 'people'} raised incidents to ask for "
                                     "this; a catalog item lets the next person self-serve without a ticket.")})
        for plan in plans:
            if build and plan["number"] in numbers and plan["action"].get("close_code") == "No resolution provided":
                plan["action"]["self_service"] = f"{spec['name']} (new catalog item)"
    counts = defaultdict(int)
    for plan in plans:
        counts[plan["action"]["do"]] += 1
    zero_touch = counts["cancel"] + counts["resolve"] + counts["order_and_resolve"] + counts["link_problem"] + counts["ask_caller"]
    summary = {"as_of": today.isoformat(), "incidents": len(plans), "by_action": dict(counts),
               "problems_to_open": sum(1 for item in problem_plans if item["draft"]), "kb_drafts": len(kb_gaps),
               "catalog_items_to_build": sum(1 for item in catalog_gaps if item["build"]),
               "needs_engineer_or_field": counts["dispatch"] + counts["diagnose_and_route"],
               "handled_without_a_person": zero_touch, "sla_breached": sum(1 for plan in plans if plan["sla_breached"]),
               "stale": sum(1 for plan in plans if plan["stale"])}
    os.makedirs("analysis", exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    with open("analysis/queue.json", "w", encoding="utf-8") as handle:
        json.dump({"summary": summary, "incidents": plans, "problems": problem_plans, "kb_gaps": kb_gaps,
                   "catalog_gaps": catalog_gaps}, handle, separators=(",", ":"))
    with open("reports/queue.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["number", "short description", "kind", "topic", "action", "priority", "state", "age days",
                         "stale", "sla breached", "knowledge", "notes"])
        for plan in plans:
            writer.writerow([plan["number"], plan["short_description"], plan["kind"], plan["topic"], plan["action"]["do"],
                             plan["priority"], plan["state"], plan["age_days"], plan["stale"], plan["sla_breached"],
                             "; ".join(item["number"] for item in plan["knowledge"]), " ".join(plan["notes"])])
    print(f"As of {today}: {len(plans)} active incidents. Plan: " + ", ".join(f"{count} {name}" for name, count in sorted(counts.items())) + ".")
    items_to_build = summary["catalog_items_to_build"]
    print(f"{zero_touch} can be handled without a person; {summary['needs_engineer_or_field']} need an engineer or field visit "
          f"(with full diagnostics). {summary['problems_to_open']} problems to open, {len(kb_gaps)} knowledge drafts, "
          f"{items_to_build} catalog item{'' if items_to_build == 1 else 's'} to build.")
    for item in problem_plans:
        if item["existing_problem"]:
            print(f"- problem {item['cluster']}: link {', '.join(item['incidents'])} to existing {item['existing_problem']}")
        else:
            print(f"- problem {item['cluster']} to open: {json.dumps(item['draft'], ensure_ascii=False)}")
    for item in catalog_gaps:
        if item["build"]:
            print(f"- catalog gap {item['topic']} ({', '.join(item['incidents'])}): build {json.dumps(item['spec'], ensure_ascii=False)}")
        else:
            print(f"- catalog gap {item['topic']} ({', '.join(item['incidents'])}): suggest only")
    for item in kb_gaps:
        print(f"- knowledge gap {item['topic']} ({', '.join(item['incidents'])}): draft \"{item['title']}\"")
    print("Worklist:")
    for plan in plans:
        action = plan["action"]
        detail = {"cancel": "test record",
                  "resolve": f"{action.get('close_code')}" + (f", stale {action['stale_days']} days" if action.get("stale_days") else "")
                             + (f", point to {action['self_service']}" if action.get("self_service") else "")
                             + (f", cite {', '.join(action['cite'])}" if action.get("cite") else ""),
                  "order_and_resolve": f"{(action.get('catalog_item') or {}).get('name')} "
                                       f"{(action.get('catalog_item') or {}).get('sys_id')} ({(action.get('catalog_item') or {}).get('price') or 'no charge'}) "
                                       f"for {action.get('requested_for')}",
                  "link_problem": f"{action.get('cluster')} problem",
                  "dispatch": f"{action.get('assignment_group')}" + (", urgency 1" if action.get("urgency") else ""),
                  "diagnose_and_route": f"{action.get('assignment_group')}",
                  "ask_caller": "on hold, awaiting caller"}.get(action["do"], "")
        print(f"{plan['number']} {action['do']} [{plan['topic']}] {detail} | {plan['short_description'][:70]}"
              + (f" | by {plan['opened_by']}" if plan["opened_by"] else ""))
    print("Wrote analysis/queue.json and reports/queue.csv.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
