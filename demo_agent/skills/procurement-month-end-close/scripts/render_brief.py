"""Render reports/month-end-brief.md from the analysis files and analysis/actions.json.

Usage: render_brief.py [--by "Supply Chain Agent"]
Fills templates/month-end-brief.md from analysis/exceptions.json, analysis/replenishment.json and the optional
analysis/actions.json that the colleague writes after acting. Standard library only.
"""

from __future__ import annotations

import json
import os
import sys


def read(path: str, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def gbp(value) -> str:
    return f"£{float(value or 0):,.2f}"


def table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "_None._"
    clean = [[str(cell).replace("|", "/").replace("\n", " ") for cell in row] for row in rows]
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)] + ["| " + " | ".join(row) + " |" for row in clean])


def main(argv: list[str]) -> int:
    by = argv[argv.index("--by") + 1] if "--by" in argv else "the procurement colleague"
    analysis = read("analysis/exceptions.json", None)
    if analysis is None:
        print("analysis/exceptions.json is missing: run p2p_exceptions.py first.")
        return 2
    replenishment = read("analysis/replenishment.json", {"items": []})
    actions = read("analysis/actions.json", [])
    actions = actions if isinstance(actions, list) else []
    summary, exceptions = analysis["summary"], analysis["exceptions"]
    done = [item for item in actions if isinstance(item, dict) and item.get("outcome") == "done"]
    proposed = [item for item in actions if isinstance(item, dict) and item.get("outcome") == "proposed"]
    decisions = [item for item in exceptions if item["action"]["type"] == "decision"]
    headline = (f"{summary['clean_chains']} of {summary['chains']} request-to-pay chains are clean. "
                f"{summary['exceptions']} exceptions ({summary['by_severity']['high']} high); "
                f"{gbp(summary['exposure'])} was billed ahead of receipt. "
                f"{len(done)} actions taken, {len(proposed)} proposed for approval and {len(decisions)} decisions need an owner.")
    action_rows = [[item.get("action", ""), item.get("record", ""), item.get("outcome", ""), item.get("reference", "")]
                   for item in actions if isinstance(item, dict)]
    decision_rows = [[item["action"].get("owner", ""), item["action"]["summary"], item["finding"]] for item in decisions]
    decision_rows += [[row.get("owner", ""), f"Approve requisition: {row['name']} x {row['quantity']} ({gbp(row['value'])})", row.get("why", "")]
                      for row in replenishment.get("items", []) if row.get("mode") == "approval"]
    chain_rows = [[chain["request"], chain["requester"], chain["supplier"], chain["po"], chain["po_status"],
                   gbp(chain["ordered"]), gbp(chain["received"]), gbp(chain["invoiced"]), chain["state"]]
                  for chain in analysis["chains"]]
    exception_rows = [[item["id"], item["severity"], item["check"].replace("_", " "), item.get("po") or "",
                       item["finding"], item["action"]["type"]] for item in exceptions]
    reorder_rows = [[row["item"], row["name"], row["cover_days"], row["reorder_below_days"], row.get("quantity", ""),
                     row.get("supplier", ""), gbp(row.get("value")), row.get("mode", "")]
                    for row in replenishment.get("items", []) if row.get("status") == "reorder"]
    observations = [[item["id"], item["check"].replace("_", " "), item["finding"]] for item in exceptions
                    if item["check"] in {"approval_bypass", "sod_self_receipt", "invoice_over_receipt", "paid_ahead_of_receipt"}]
    with open(os.path.join(os.environ.get("SKILL_DIR", "."), "templates", "month-end-brief.md"), encoding="utf-8") as handle:
        template = handle.read()
    values = {
        "as_of": analysis["as_of"], "by": by, "headline": headline,
        "actions": table(["Action", "Record", "Outcome", "Reference"], action_rows),
        "decisions": table(["Owner", "Decision", "Why"], decision_rows),
        "chains": table(["Request", "Requester", "Supplier", "PO", "PO status", "Ordered", "Received", "Invoiced", "State"], chain_rows),
        "exceptions": table(["ID", "Severity", "Check", "PO", "Finding", "Handling"], exception_rows),
        "replenishment": table(["Item", "Name", "Cover (days)", "Reorder below", "Qty", "Source", "Value", "Handling"], reorder_rows),
        "observations": table(["ID", "Control", "Finding"], observations),
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", str(value))
    os.makedirs("reports", exist_ok=True)
    with open("reports/month-end-brief.md", "w", encoding="utf-8") as handle:
        handle.write(template)
    print(headline)
    print("Wrote reports/month-end-brief.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
