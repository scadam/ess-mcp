"""Render reports/service-desk-report.md from analysis/queue.json and the ServiceNow results saved during the run.

Usage: render_report.py [--by "IT Agent"] [--dry-run]
Outcomes come from the saved results of update_incident, create_problem, create_knowledge_article,
order_catalog_item and create_catalog_item, so the report shows what actually happened. Standard library only.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys

STATES = {"1": "New", "2": "In Progress", "3": "On Hold", "6": "Resolved", "7": "Closed", "8": "Canceled"}
LABELS = {"cancel": "Cancel test record", "resolve": "Resolve", "order_and_resolve": "Order and resolve",
          "link_problem": "Link to problem", "dispatch": "Dispatch", "diagnose_and_route": "Diagnose and route",
          "ask_caller": "Ask the caller"}


def read(path: str, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def results(tool: str) -> list[dict]:
    docs = [read(path, None) for path in sorted(glob.glob(f"data/servicenow/{tool}*.json"))]
    return [doc for doc in docs if isinstance(doc, dict) and doc.get("status") not in {"not_run", "requires_approval"}]


def field(record: dict, name: str) -> str:
    value = record.get(name)
    if isinstance(value, dict):
        value = value.get("display_value") or value.get("value")
    return " ".join(str(value or "").split())


def table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "_None._"
    clean = [[str(cell).replace("|", "/").replace("\n", " ") for cell in row] for row in rows]
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)] + ["| " + " | ".join(row) + " |" for row in clean])


def plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def best(items: list[dict], value: str) -> dict | None:
    """The item whose keywords the text hits most often (first wins a tie), as in authorise.py."""
    value, score, chosen = value.lower(), 0, None
    for item in items:
        count = sum(1 for word in item.get("keywords", [])
                    if word and re.search(rf"(?<![a-z]){re.escape(word.lower())}", value))
        if count > score:
            score, chosen = count, item
    return chosen


def main(argv: list[str]) -> int:
    by = argv[argv.index("--by") + 1] if "--by" in argv else "the service desk colleague"
    dry = "--dry-run" in argv
    queue = read("analysis/queue.json", None)
    if queue is None:
        print("analysis/queue.json is missing: run triage_queue.py first.")
        return 2
    summary, plans = queue["summary"], queue["incidents"]
    updates: dict[str, dict] = {}
    final = {"6", "7", "8", "Resolved", "Closed", "Canceled"}
    for doc in results("update_incident"):
        if doc.get("updated") and doc.get("number"):
            number = str(doc["number"]).upper()
            rank = field(doc.get("incident") or {}, "state") in final
            if number not in updates or rank >= (field(updates[number].get("incident") or {}, "state") in final):
                updates[number] = doc
    problems = [doc for doc in results("create_problem") if doc.get("created") and doc.get("number")]
    articles = [doc["article"] for doc in results("create_knowledge_article") if doc.get("success") and isinstance(doc.get("article"), dict)]
    orders = [doc for doc in results("order_catalog_item") if doc.get("success") and doc.get("request_number")]
    items = [doc for doc in results("create_catalog_item") if doc.get("success") and doc.get("sys_id")]

    cluster_problem: dict[str, str] = {item["cluster"]: item.get("existing_problem") or "" for item in queue.get("problems", [])}
    drafts = [item for item in queue.get("problems", []) if item.get("draft")]
    for doc in problems:
        cluster = best(drafts, str(doc.get("short_description") or ""))
        if cluster is not None:
            cluster_problem[cluster["cluster"]] = doc["number"]

    rows, handled, engineer, untouched = [], 0, 0, 0
    for plan in plans:
        action = plan["action"]
        update = updates.get(plan["number"])
        if dry:
            outcome = "Planned (dry run)"
        elif update is None:
            outcome = "Not done"
            untouched += 1
        else:
            incident = update.get("incident") or {}
            state = field(incident, "state")
            state = STATES.get(state, state) or "Updated"
            outcome = state + (f" ({action['close_code']})" if action.get("close_code") and state in {"Resolved", "Closed"} else "")
            if action["do"] == "link_problem" and cluster_problem.get(action.get("cluster", "")):
                outcome += f", linked to {cluster_problem[action['cluster']]}"
            if action["do"] in {"dispatch", "diagnose_and_route"}:
                engineer += 1
            else:
                handled += 1
        detail = (action.get("catalog_item") or {}).get("name") or action.get("assignment_group") or action.get("close_code") or ""
        rows.append([plan["number"], plan["short_description"], plan["kind"].replace("_", " "),
                     LABELS.get(action["do"], action["do"]), detail, outcome])

    if dry:
        headline = (f"Dry run, nothing changed. Of {summary['incidents']} active incidents, {summary['handled_without_a_person']} "
                    f"can be handled without a person and {summary['needs_engineer_or_field']} need an engineer or field visit. "
                    f"The plan opens {plural(summary['problems_to_open'], 'problem')}, drafts "
                    f"{plural(summary['kb_drafts'], 'knowledge article')} and builds "
                    f"{plural(summary['catalog_items_to_build'], 'catalog item')}.")
    else:
        headline = (f"Worked {summary['incidents'] - untouched} of {summary['incidents']} active incidents: {handled} handled "
                    f"without a person, {engineer} handed to an engineer or field team with full diagnostics"
                    + (f", {untouched} not reached" if untouched else "") + f". Opened {plural(len(problems), 'problem')}, "
                    f"drafted {plural(len(articles), 'knowledge article')}, raised {plural(len(orders), 'request')} and "
                    f"built {plural(len(items), 'catalog item')}.")
    problem_rows = [[item["cluster"], cluster_problem.get(item["cluster"]) or ("to open" if dry else "not opened"),
                     len(item["incidents"]), ", ".join(item["incidents"])] for item in queue.get("problems", [])]
    builds = [gap for gap in queue.get("catalog_gaps", []) if gap.get("build")]
    built_for = {id(best(builds, str(doc.get("name") or ""))) for doc in items}
    catalog_rows = []
    for gap in queue.get("catalog_gaps", []):
        built = gap["build"] and id(gap) in built_for
        state = ("built, inactive; publishing waits for approval" if built else ("to build" if dry and gap["build"] else
                 "not built" if gap["build"] else "suggested (one request so far)"))
        catalog_rows.append([(gap.get("spec") or {}).get("name", gap["topic"]), state, len(gap["incidents"]), ", ".join(gap["incidents"])])
    drafted: dict[int, str] = {}
    for article in articles:
        gap = best(queue.get("kb_gaps", []), str(article.get("title") or ""))
        if gap is not None:
            drafted.setdefault(id(gap), str(article.get("number") or ""))
    kb_rows = [[gap["title"], ", ".join(gap["incidents"]), drafted.get(id(gap)) or ("to draft" if dry else "not drafted")]
               for gap in queue.get("kb_gaps", [])]
    by_item: dict[str, list[dict]] = {}
    for plan in plans:
        item = plan["action"].get("catalog_item")
        if item:
            by_item.setdefault(str(item.get("sys_id") or "").lower(), []).append(plan)
    order_rows = []
    for doc in orders:
        planned = by_item.get(str(doc.get("sys_id") or "").lower(), [])
        order_rows.append([doc.get("request_number"), ", ".join(plan["number"] for plan in planned),
                           ", ".join(sorted({plan["opened_by"] for plan in planned})),
                           planned[0]["action"]["catalog_item"].get("name", "") if planned else ""])
    people = [[plan["number"], plan["short_description"], plan["action"].get("assignment_group", ""), plan["action"].get("why", "")]
              for plan in plans if plan["action"]["do"] in {"dispatch", "diagnose_and_route"}]
    with open(os.path.join(os.environ.get("SKILL_DIR", "."), "templates", "service-desk-report.md"), encoding="utf-8") as handle:
        template = handle.read()
    values = {
        "as_of": summary["as_of"], "by": by, "headline": headline,
        "incidents": table(["Incident", "Summary", "Kind", "Handling", "Detail", "Outcome"], rows),
        "problems": table(["Cluster", "Problem", "Incidents", "Numbers"], problem_rows),
        "catalog": table(["Catalog item", "Status", "Requests", "From"], catalog_rows),
        "knowledge": table(["Article", "Incidents", "Draft"], kb_rows),
        "orders": table(["Request", "Incident", "For", "Item"], order_rows),
        "people": table(["Incident", "Summary", "Group", "Why a person is needed"], people),
        "sla": f"{summary['sla_breached']} of the active incidents had breached SLA before this run; {summary['stale']} had no update for over 180 days.",
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", str(value))
    template = re.sub(r"\n{3,}", "\n\n", template)
    os.makedirs("reports", exist_ok=True)
    with open("reports/service-desk-report.md", "w", encoding="utf-8") as handle:
        handle.write(template)
    print(headline)
    print("Wrote reports/service-desk-report.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
