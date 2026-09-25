"""Triage a Workday inbox: bucket, age and rank every task, roll up new hires and draft the routing tickets.

Usage: triage_inbox.py [--as-of YYYY-MM-DD] [--for "HR partner name"]
Reads data/workday/get_inbox_tasks*.json (and get_team_overview / get_team_calendar when present) and writes
analysis/triage.json, reports/triage.csv and reports/hires.csv. Standard library only.
"""

from __future__ import annotations

import csv
import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import date

TEST = re.compile(r"\btest(?:ing)?\b|probe|microsoftapp", re.IGNORECASE)
PLACEHOLDER = re.compile(r"(\w+)\s+\1", re.IGNORECASE)  # "admin admin" and similar dummy workers
LISTED = 40
URGENT_LEAVE_DAYS = 14
BUCKETS = {
    "account-setup": ("HRIS team", "ticket", "New-hire Workday account set-up",
                      "Initiation steps only HRIS can complete; the hires' onboarding waits on them."),
    "unassigned": ("HR Operations", "ticket", "Unassigned tasks", "Nobody owns these steps, so they will not move."),
    "test-data": ("HRIS team", "ticket", "Test and probe records",
                  "Integration-test records in the live inbox hide real work and distort SLAs."),
    "compensation": ("HR partner", "decision", "Compensation reviews", "Money waits on it."),
    "approvals": ("HR partner", "decision", "Approvals", "Employment and pay changes wait on the named partner."),
    "background-checks": ("Talent Acquisition", "decision", "Background checks",
                          "A start date cannot be confirmed until the check clears."),
    "leave-reviews": ("HR partner", "decision", "Leave reviews", "Leave cannot be confirmed to the worker."),
    "job-changes": ("HR partner", "decision", "Job and organisation changes", "The change is not effective until reviewed."),
    "mentoring": ("Hiring managers", "nudge", "New-hire mentoring set-up", "Mentors should be in place for day one."),
    "drafts": ("Task owner", "nudge", "Drafts saved for later", "Saved drafts that nobody has come back to."),
    "other": ("HR partner", "review", "Other tasks", "Needs a look."),
}
RANK = {"compensation": 1, "approvals": 1, "background-checks": 2, "leave-reviews": 3, "job-changes": 4}


def load(pattern: str) -> list:
    docs = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="utf-8") as handle:
                docs.append(json.load(handle))
        except (OSError, ValueError):
            print(f"warning: {path} is not JSON; skipped", file=sys.stderr)
    return docs


def parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def bucket_of(task: dict) -> str:
    process = str(task.get("overallProcess") or "")
    descriptor = str(task.get("descriptor") or "")
    if (TEST.search(" ".join((process, str(task.get("subject") or ""), descriptor)))
            or PLACEHOLDER.fullmatch(person(task))):
        return "test-data"
    kind = process.split(":", 1)[0].strip()
    if task.get("status") == "Awaiting Assignment":
        return "unassigned"
    if task.get("status") == "Saved for Later":
        return "drafts"
    if "compensation" in descriptor.lower():
        return "compensation"
    if task.get("stepType") == "Approval":
        return "approvals"
    if kind == "Hire" and descriptor == "Edit Workday Account":
        return "account-setup"
    if descriptor == "Background Check":
        return "background-checks"
    if descriptor == "Manage Mentorship":
        return "mentoring"
    if descriptor == "Review Leave of Absence":
        return "leave-reviews"
    if kind in {"Data Change", "Edit Position", "Move Workers (Staffing)", "Org Design", "Job Requisition"} or descriptor.startswith("Review"):
        return "job-changes"
    return "other"


def person(task: dict) -> str:
    process = str(task.get("overallProcess") or "")
    name = process.split(":", 1)[1] if ":" in process else str(task.get("subject") or "")
    return re.split(r"\s+-\s+|\s+\(", name.strip(), maxsplit=1)[0].strip()


def main(argv: list[str]) -> int:
    today = date.fromisoformat(argv[argv.index("--as-of") + 1]) if "--as-of" in argv else date.today()
    partner = argv[argv.index("--for") + 1] if "--for" in argv else "the HR partner"
    tasks, seen = [], set()
    for doc in load("data/workday/get_inbox_tasks*.json") + load("data/workday/get_team_performance_summary*.json"):
        found = doc.get("tasks") if isinstance(doc, dict) else None
        if found is None and isinstance(doc, dict):
            found = (doc.get("inboxSummary") or {}).get("tasks")
        for task in found or []:
            if isinstance(task, dict) and task.get("id") not in seen:
                seen.add(task.get("id"))
                tasks.append(task)
    if not tasks:
        print("No Workday inbox tasks in the workspace: call workday get_inbox_tasks first, then rerun.")
        return 2
    on_leave = set()
    for doc in load("data/workday/get_team_overview*.json") + load("data/workday/get_team_calendar*.json"):
        for member in (doc.get("teamMembers") if isinstance(doc, dict) else None) or []:
            name = str(member.get("name") or "")
            if "(on leave)" in name.lower():
                on_leave.add(name.split("(")[0].strip().lower())

    rows, buckets = [], defaultdict(list)
    duplicates = Counter((task.get("overallProcess"), task.get("descriptor"), task.get("subject")) for task in tasks)
    for task in tasks:
        name = bucket_of(task)
        assigned, due = parse_date(task.get("assigned")), parse_date(task.get("due"))
        waiting = (today - assigned).days if assigned else None
        overdue = (today - due).days if due and due < today else 0
        who = person(task)
        leave_flag = "(on leave)" in json.dumps(task).lower() or who.lower() in on_leave or \
            str(task.get("initiator") or "").lower() in on_leave
        row = {"id": task.get("id"), "bucket": name, "owner": BUCKETS[name][0], "handling": BUCKETS[name][1],
               "process": task.get("overallProcess"), "step": task.get("descriptor"), "status": task.get("status"),
               "person": who, "initiator": task.get("initiator"), "assigned": str(assigned or ""), "due": str(due or ""),
               "waiting_days": waiting, "overdue_days": overdue, "on_leave": leave_flag,
               "duplicate": duplicates[(task.get("overallProcess"), task.get("descriptor"), task.get("subject"))] > 1}
        rows.append(row)
        buckets[name].append(row)

    hires = defaultdict(list)
    for row in rows:
        if str(row["process"] or "").startswith("Hire") and row["bucket"] != "test-data":
            hires[row["person"]].append(row)
    hire_rows = sorted(({"hire": name, "open_steps": len(items), "steps": sorted({item["step"] for item in items}),
                         "oldest_assigned": min((item["assigned"] for item in items if item["assigned"]), default=""),
                         "max_overdue_days": max(item["overdue_days"] for item in items)}
                        for name, items in hires.items()), key=lambda item: (-item["open_steps"], item["oldest_assigned"]))

    decisions = []
    for name, rank in RANK.items():
        for row in buckets.get(name, []):
            urgent = rank <= 2 or (name == "leave-reviews" and (row["waiting_days"] or 0) > URGENT_LEAVE_DAYS)
            advice = {
                "compensation": "Check the change against the approved range before the requisition moves to offer.",
                "approvals": f"Open it in Workday and approve or send back; it has waited {row['waiting_days']} days.",
                "background-checks": "Chase the screening provider and hold the start date until the check clears.",
                "leave-reviews": "Review the request so the worker has an answer; confirm cover if the leave is long.",
                "job-changes": "Review and complete, or send back with a reason if the change is no longer wanted.",
            }[name]
            if row["on_leave"]:
                advice += " The worker or initiator is on leave: consider reassigning."
            decisions.append({**row, "rank": rank, "urgent": urgent, "why": BUCKETS[name][3], "recommendation": advice})
    decisions.sort(key=lambda item: (item["rank"], -(item["waiting_days"] or 0)))

    def ticket(name: str, urgency: str, what: str) -> dict:
        items = buckets[name]
        oldest = min((item["assigned"] for item in items if item["assigned"]), default="unknown")
        overdue = sum(1 for item in items if item["overdue_days"] > 0)
        return {"bucket": name, "tasks": len(items), "caller": "System Administrator", "category": "inquiry",
                "urgency": urgency, "assignment_group": "Service Desk",
                "short_description": f"HR backlog: {what}",
                "description": (f"{BUCKETS[name][3]} {len(items)} tasks in {partner}'s Workday inbox; oldest assigned "
                                f"{oldest}; {overdue} past their due date.\n\n"
                                + "\n".join(f"- {item['person']}: {item['step']} ({item['status']}, assigned {item['assigned'] or 'n/a'})"
                                            for item in items[:LISTED])
                                + (f"\n- … and {len(items) - LISTED} more" if len(items) > LISTED else "")
                                + "\n\nRaised by the HR colleague (Group Functions Autopilot) for the HR partner. "
                                  "Full task list: reports/triage.csv in the run.")}

    tickets = []
    if buckets.get("account-setup"):
        count = len({item["person"] for item in buckets["account-setup"]})
        tickets.append(ticket("account-setup", "2", f"complete Workday account set-up for {count} new hires"))
    if buckets.get("unassigned"):
        tickets.append(ticket("unassigned", "2", f"route {len(buckets['unassigned'])} unassigned Workday inbox tasks"))
    if buckets.get("test-data"):
        tickets.append(ticket("test-data", "3", f"remove {len(buckets['test-data'])} test and probe records from the live Workday inbox"))

    routed = sum(len(buckets[item["bucket"]]) for item in tickets)
    summary = {
        "as_of": today.isoformat(), "total": len(rows), "routed_by_ticket": routed,
        "decisions": len(decisions), "urgent_decisions": sum(1 for item in decisions if item["urgent"]),
        "nudges": sum(len(buckets[name]) for name in ("mentoring", "drafts")),
        "overdue": sum(1 for row in rows if row["overdue_days"] > 0),
        "oldest_overdue_days": max((row["overdue_days"] for row in rows), default=0),
        "new_hires": len(hire_rows), "duplicates": sum(1 for row in rows if row["duplicate"]),
        "on_leave_items": sum(1 for row in rows if row["on_leave"]),
    }
    result = {
        "summary": summary,
        "buckets": {name: {"count": len(items), "owner": BUCKETS[name][0], "handling": BUCKETS[name][1],
                           "title": BUCKETS[name][2], "why": BUCKETS[name][3],
                           "overdue": sum(1 for item in items if item["overdue_days"] > 0),
                           "oldest_assigned": min((item["assigned"] for item in items if item["assigned"]), default="")}
                    for name, items in sorted(buckets.items(), key=lambda pair: -len(pair[1]))},
        "decisions": decisions, "tickets": tickets, "hires": hire_rows[:80],
        "watch": {"multi_step_hires": [item for item in hire_rows if item["open_steps"] > 1][:20],
                  "on_leave": [row for row in rows if row["on_leave"]][:20]},
    }
    os.makedirs("analysis", exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    with open("analysis/triage.json", "w", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2)
    with open("reports/triage.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        fields = ["id", "bucket", "owner", "handling", "process", "step", "status", "person", "assigned", "due",
                  "waiting_days", "overdue_days", "on_leave", "duplicate"]
        writer.writerow(fields)
        writer.writerows([[row[field] for field in fields] for row in rows])
    with open("reports/hires.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["hire", "open steps", "steps", "oldest assigned", "max overdue days"])
        writer.writerows([[item["hire"], item["open_steps"], "; ".join(item["steps"]), item["oldest_assigned"],
                           item["max_overdue_days"]] for item in hire_rows])
    print(f"As of {today}: {summary['total']} tasks. {routed} route to other teams in {len(tickets)} tickets; "
          f"{summary['decisions']} decisions ({summary['urgent_decisions']} urgent); {summary['nudges']} nudges; "
          f"{summary['overdue']} overdue (oldest {summary['oldest_overdue_days']} days).")
    for name, info in result["buckets"].items():
        print(f"- {info['title']}: {info['count']} -> {info['owner']} ({info['handling']})")
    print("Wrote analysis/triage.json, reports/triage.csv and reports/hires.csv.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
