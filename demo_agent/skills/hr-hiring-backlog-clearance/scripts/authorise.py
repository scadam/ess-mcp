"""Deterministic policy check run by the host before any pre-approved action; prints {"allow", "reason"}.

Input on stdin: {"action": {"server", "tool", "args"}, "used": [earlier pre-approved actions]}.
Only the routing tickets drafted by triage_inbox.py may be raised without approval, once each, at most three.
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
    if (server, tool) != ("servicenow", "create_incident"):
        return verdict(False, "Only the HR backlog routing tickets are pre-approved for this skill.")
    try:
        with open("analysis/triage.json", encoding="utf-8") as handle:
            drafts = json.load(handle).get("tickets") or []
    except (OSError, ValueError):
        return verdict(False, "Run triage_inbox.py first: tickets must come from the triage.")
    subject = str(args.get("short_description") or "")
    draft = next((item for item in drafts if item.get("short_description") == subject), None)
    if draft is None:
        return verdict(False, "The ticket does not match a routing ticket drafted by the triage.")
    raised = [item for item in used if item.get("action") == "servicenow.create_incident"]
    if any((item.get("args") or {}).get("short_description") == subject for item in raised):
        return verdict(False, "That routing ticket has already been raised in this run.")
    if len(raised) >= 3:
        return verdict(False, "At most three routing tickets per run.")
    return verdict(True, f"Routing ticket for {draft.get('tasks')} {draft.get('bucket')} tasks drafted by the triage.")


if __name__ == "__main__":
    sys.exit(main())
