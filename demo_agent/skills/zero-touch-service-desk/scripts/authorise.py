"""Deterministic policy check run by the host before any pre-approved service desk action; prints {"allow", "reason"}.

Input on stdin: {"action": {"server", "tool", "args"}, "used": [earlier pre-approved actions]}.
Every change must match the plan in analysis/queue.json (written by triage_queue.py). Anything it cannot verify
is declined, and the host turns the action into a proposal that waits for a person.
"""

from __future__ import annotations

import json
import re
import sys

CLOSE_CODES = {"Solution provided", "Workaround provided", "Resolved by request", "Resolved by problem",
               "No resolution provided", "Resolved by caller", "User error", "Duplicate", "Known error"}
OPEN_STATES = {"", "in_progress", "on_hold"}
MAX_UPDATES_PER_INCIDENT = 3
MIN_KB_BODY = 200


def verdict(allow: bool, reason: str) -> int:
    print(json.dumps({"allow": allow, "reason": reason}))
    return 0


def text(value) -> str:
    return " ".join(str(value or "").split())


def hits(words: list[str], value: str) -> int:
    value = value.lower()
    return sum(1 for word in words if word and re.search(rf"(?<![a-z]){re.escape(word.lower())}", value))


def best(items: list[dict], value: str) -> dict | None:
    """The item whose keywords the text hits most often (first wins a tie); None when nothing matches."""
    score, chosen = 0, None
    for item in items:
        count = hits(item.get("keywords", []), value)
        if count > score:
            score, chosen = count, item
    return chosen


def earlier(used: list, tool: str) -> list[dict]:
    return [item.get("args") or {} for item in used
            if isinstance(item, dict) and item.get("action") == f"servicenow.{tool}"]


def main() -> int:
    try:
        request = json.load(sys.stdin)
        action = request["action"]
        server, tool, args = action["server"], action["tool"], action.get("args") or {}
        used = request.get("used") or []
    except (ValueError, KeyError, TypeError):
        return verdict(False, "The action could not be read.")
    try:
        with open("analysis/queue.json", encoding="utf-8") as handle:
            queue = json.load(handle)
    except (OSError, ValueError):
        return verdict(False, "There is no queue triage yet: run triage_queue.py before changing anything.")
    if server != "servicenow":
        return verdict(False, "The service desk colleague only changes ServiceNow.")
    plans = {plan["number"]: plan for plan in queue.get("incidents", []) if plan.get("number")}
    drafts = [item for item in queue.get("problems", []) if item.get("draft")]
    kb_gaps = queue.get("kb_gaps", [])
    builds = [item for item in queue.get("catalog_gaps", []) if item.get("build")]

    if tool == "update_incident":
        number = text(args.get("number")).upper()
        plan = plans.get(number)
        if plan is None:
            return verdict(False, f"{number or 'That incident'} is not in the triaged queue.")
        done = sum(1 for item in earlier(used, "update_incident") if text(item.get("number")).upper() == number)
        if done >= MAX_UPDATES_PER_INCIDENT:
            return verdict(False, f"{number} has already been updated {done} times in this run.")
        planned = plan["action"]
        state = text(args.get("state")).lower().replace(" ", "_")
        if (args.get("urgency") or args.get("impact")) and planned["do"] != "dispatch":
            return verdict(False, f"Only field dispatches change urgency or impact; {number} is planned as {planned['do']}.")
        if state in {"resolved", "closed"}:
            if planned["do"] not in {"resolve", "order_and_resolve"}:
                return verdict(False, f"{number} is planned as {planned['do'].replace('_', ' ')}, not a resolution.")
            if not (text(args.get("close_code")) and text(args.get("close_notes")) and text(args.get("comments"))):
                return verdict(False, "A resolution needs a close code, close notes and a comment to the caller.")
            if text(args.get("close_code")) not in CLOSE_CODES:
                return verdict(False, f"{text(args.get('close_code'))!r} is not a standard close code.")
            if planned.get("stale_days") and text(args.get("close_code")) != "No resolution provided":
                return verdict(False, f"{number} is a stale closure: use close code 'No resolution provided'.")
            if planned["do"] == "order_and_resolve":
                item = planned.get("catalog_item") or {}
                ordered = [order for order in earlier(used, "order_catalog_item")
                           if text(order.get("sys_id")).lower() == text(item.get("sys_id")).lower()
                           and text(order.get("requested_for")).lower() == text(plan.get("opened_by")).lower()]
                if not ordered:
                    return verdict(False, f"Order {item.get('name')} for {plan.get('opened_by')} before resolving {number}.")
            return verdict(True, f"{number}: planned {planned['do'].replace('_', ' ')} with close code {text(args.get('close_code'))}.")
        if state == "canceled":
            if planned["do"] != "cancel":
                return verdict(False, f"Only automated test records are cancelled; {number} is a real request.")
            return verdict(True, f"{number} is an automated test record.")
        if state not in OPEN_STATES:
            return verdict(False, f"The service desk colleague doesn't move incidents to {state!r}.")
        if args.get("problem"):
            problem = text(args.get("problem")).upper()
            cluster = next((item for item in queue.get("problems", []) if number in item.get("incidents", [])), None)
            if cluster is None or planned["do"] != "link_problem":
                return verdict(False, f"{number} is not part of a triaged problem cluster.")
            created = [item for item in earlier(used, "create_problem")
                       if best(drafts, text(item.get("short_description"))) is cluster]
            if problem != text(cluster.get("existing_problem")).upper() and not created:
                return verdict(False, f"Open or reuse the {cluster['cluster']} problem before linking {number} to {problem}.")
            return verdict(True, f"{number} belongs to the {cluster['cluster']} cluster ({len(cluster['incidents'])} incidents).")
        if not (text(args.get("comments")) or text(args.get("work_notes"))):
            return verdict(False, "Every update needs a comment to the caller or a work note.")
        return verdict(True, f"{number}: planned {planned['do'].replace('_', ' ')}.")

    if tool == "create_problem":
        cluster = best(drafts, text(args.get("short_description")))
        if cluster is None:
            return verdict(False, "No triaged incident cluster needs a new problem for that description.")
        if any(best(drafts, text(item.get("short_description"))) is cluster for item in earlier(used, "create_problem")):
            return verdict(False, f"A problem for the {cluster['cluster']} cluster was already opened in this run.")
        return verdict(True, f"{len(cluster['incidents'])} open incidents share the {cluster['cluster']} fault and no open problem covers it.")

    if tool == "create_knowledge_article":
        gap = best(kb_gaps, text(args.get("title")))
        if gap is None:
            return verdict(False, "That article does not fill a knowledge gap found in the queue.")
        if len(text(args.get("body_text"))) < MIN_KB_BODY:
            return verdict(False, f"The article body is too thin to help anyone: write at least {MIN_KB_BODY} characters.")
        if any(best(kb_gaps, text(item.get("title"))) is gap for item in earlier(used, "create_knowledge_article")):
            return verdict(False, f"A draft for {gap['title']} was already written in this run.")
        return verdict(True, f"Draft article for {gap['title']} ({', '.join(gap['incidents'])}); drafts need a knowledge owner to publish.")

    if tool == "order_catalog_item":
        sys_id, person = text(args.get("sys_id")).lower(), text(args.get("requested_for"))
        if not person:
            return verdict(False, "Order on the caller's behalf: requested_for must be the person who raised the incident.")
        if int(args.get("quantity") or 1) != 1:
            return verdict(False, "Incident fulfilment orders one item.")
        planned = [plan for plan in plans.values() if plan["action"]["do"] == "order_and_resolve"
                   and text((plan["action"].get("catalog_item") or {}).get("sys_id")).lower() == sys_id
                   and text(plan.get("opened_by")).lower() == person.lower()]
        if not planned:
            return verdict(False, "No triaged incident needs that catalog item for that person.")
        already = [order for order in earlier(used, "order_catalog_item")
                   if text(order.get("sys_id")).lower() == sys_id and text(order.get("requested_for")).lower() == person.lower()]
        if len(already) >= len(planned):
            return verdict(False, f"{person} already has that item on order from this run.")
        item = planned[0]["action"]["catalog_item"]
        return verdict(True, f"{planned[0]['number']}: {item.get('name')} ({item.get('price') or 'no charge'}) for {person}.")

    if tool == "create_catalog_item":
        if args.get("active") not in (None, False, "false"):
            return verdict(False, "New catalog items start inactive: publishing needs the catalog owner's approval.")
        name = text(args.get("name"))
        gap = best(builds, name)
        if gap is None:
            return verdict(False, f"No catalog gap with enough demand matches {name!r}.")
        if any(best(builds, text(item.get("name"))) is gap for item in earlier(used, "create_catalog_item")):
            return verdict(False, f"The {gap['topic']} catalog item was already built in this run.")
        variables = args.get("variables") or []
        if not isinstance(variables, list) or not variables:
            return verdict(False, "A catalog item needs order-form questions so it can be fulfilled without a follow-up.")
        return verdict(True, f"{len(gap['incidents'])} incidents asked for this ({', '.join(gap['incidents'])}); built inactive.")

    return verdict(False, f"{tool.replace('_', ' ')} is outside the service desk colleague's authority.")


if __name__ == "__main__":
    sys.exit(main())
