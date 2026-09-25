"""Deterministic policy check run by the host before any pre-approved action; prints {"allow", "reason"}.

Input on stdin: {"action": {"server", "tool", "args"}, "used": [earlier pre-approved actions]}.
A case may be opened without approval only for a finding in analysis/controls.json that meets the case threshold,
matches its draft's type and priority, and has no case yet.
"""

from __future__ import annotations

import json
import sys


def verdict(allow: bool, reason: str) -> int:
    print(json.dumps({"allow": allow, "reason": reason}))
    return 0


def main() -> int:
    try:
        request = json.load(sys.stdin)
        action = request["action"]
        server, tool, args = action["server"], action["tool"], action.get("args") or {}
        used = request.get("used") or []
    except (ValueError, KeyError, TypeError):
        return verdict(False, "The action could not be read.")
    if (server, tool) != ("salesforce", "create_case"):
        return verdict(False, "Only compliance cases for tested findings are pre-approved for this skill.")
    try:
        with open("analysis/controls.json", encoding="utf-8") as handle:
            findings = json.load(handle).get("findings") or []
    except (OSError, ValueError):
        return verdict(False, "Run controls_test.py first: cases must come from the test results.")
    subject = str(args.get("subject") or "")
    item = next((entry for entry in findings if subject.startswith(f"[{entry.get('id')}]")), None)
    if item is None:
        return verdict(False, "The case subject must start with the [finding ID] of a tested finding.")
    case = item.get("case") or {}
    draft = case.get("draft") or {}
    if not case.get("required"):
        return verdict(False, f"{item['id']} is below the case threshold: it stays in the workpaper.")
    if case.get("existing"):
        return verdict(False, f"{item['id']} already has case {case['existing']}.")
    if any(str((entry.get("args") or {}).get("subject", "")).startswith(f"[{item['id']}]") for entry in used):
        return verdict(False, f"A case for {item['id']} was already opened in this run.")
    if args.get("compliance_type") != draft.get("compliance_type"):
        return verdict(False, f"{item['id']} is a {draft.get('compliance_type')} case.")
    if str(args.get("priority") or "Medium") != draft.get("priority"):
        return verdict(False, f"{item['id']} has {draft.get('priority')} priority under the framework.")
    return verdict(True, f"{item['id']}: {item['severity']} finding, exposure £{item['exposure']:,.2f}.")


if __name__ == "__main__":
    sys.exit(main())
