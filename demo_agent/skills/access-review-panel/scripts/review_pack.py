"""Build the access review pack: flags per member, decisions table per owner, and outstanding decisions.

Usage: review_pack.py <groups json> [<roles json>] [--decisions <decisions json>]
groups json: a list of servicenow__list_group_members results; roles json: a list of list_role_holders results.
Writes reports/decisions.csv and analysis/review.json, prints the summary. Standard library only.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

OWNERS = {"admin": "Elvia Atkins", "security_admin": "Kadji Bell", "CAB Approval": "Kadji Bell",
          "Change Management": "Elvia Atkins", "Database": "Kenvin Sturis"}
SOD = [("Change Management", "CAB Approval")]
DORMANT_DAYS = 90


def _load(path: str) -> list:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data if isinstance(data, list) else [data]


def _dormant(last_login: str | None, now: datetime) -> bool:
    if not last_login:
        return True
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
        try:
            when = datetime.strptime(str(last_login)[:19], fmt).replace(tzinfo=timezone.utc)
            return now - when > timedelta(days=DORMANT_DAYS)
        except ValueError:
            continue
    return False


def build(groups: list, roles: list, decisions: dict) -> dict:
    now = datetime.now(timezone.utc)
    rows, memberships = [], {}
    entries = [(item.get("group"), "group", item.get("members") or []) for item in groups if item.get("found", True)]
    entries += [(item.get("role"), "role", item.get("holders") or []) for item in roles if item.get("found", True)]
    for name, kind, people in entries:
        for person in people:
            user = str(person.get("user_name") or "")
            memberships.setdefault(user, set()).add(name)
            flags = []
            if str(person.get("active")).lower() in {"false", "0"}:
                flags.append("leaver")
            if _dormant(person.get("last_login"), now):
                flags.append("dormant")
            if kind == "role" and not person.get("via_group"):
                flags.append("direct privileged grant")
            key = f"{name}|{user}"
            decision = decisions.get(key, {})
            rows.append({"owner": OWNERS.get(name, "Platform owner"), "scope": f"{kind}: {name}", "user_name": user,
                         "name": person.get("name") or "", "email": person.get("email") or "",
                         "last_login": person.get("last_login") or "never", "flags": ", ".join(flags),
                         "decision": decision.get("decision", ""), "decided_by": decision.get("by", ""),
                         "note": decision.get("note", ""), "key": key})
    for user, held in memberships.items():
        for left, right in SOD:
            if left in held and right in held:
                for row in rows:
                    if row["user_name"] == user and row["scope"] in {f"group: {left}", f"group: {right}"}:
                        row["flags"] = ", ".join(filter(None, [row["flags"], f"SoD conflict ({left} + {right})"]))
    Path("reports").mkdir(exist_ok=True)
    with Path("reports/decisions.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["owner"])
        writer.writeheader()
        writer.writerows(rows)
    owners: dict = {}
    for row in rows:
        entry = owners.setdefault(row["owner"], {"members": 0, "flagged": 0, "outstanding": [], "remove": 0, "keep": 0})
        entry["members"] += 1
        entry["flagged"] += bool(row["flags"])
        if row["decision"] in ("keep", "remove"):
            entry[row["decision"]] += 1
        else:
            entry["outstanding"].append(f"{row['name'] or row['user_name']} ({row['scope']})")
    return {"population": len(rows), "flagged": sum(1 for row in rows if row["flags"]),
            "owners": owners, "complete": all(not item["outstanding"] for item in owners.values()),
            "flagged_rows": [{k: row[k] for k in ("owner", "scope", "user_name", "name", "flags")}
                             for row in rows if row["flags"]][:60],
            "removals": [row["key"] for row in rows if row["decision"] == "remove"]}


def main() -> None:
    args = sys.argv[1:]
    decisions: dict = {}
    if "--decisions" in args:
        index = args.index("--decisions")
        decisions = json.loads(Path(args[index + 1]).read_text(encoding="utf-8"))
        args = args[:index] + args[index + 2:]
    if not args:
        print("usage: review_pack.py <groups json> [<roles json>] [--decisions <decisions json>]")
        sys.exit(2)
    groups = _load(args[0])
    roles = _load(args[1]) if len(args) > 1 else []
    result = build(groups, roles, decisions)
    Path("analysis").mkdir(exist_ok=True)
    Path("analysis/review.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
