---
name: access-review-panel
description: >-
  Run a user access recertification for privileged ServiceNow groups and roles as a tracked assignment from a
  manager: pull every member with their activity, flag leavers, dormant accounts and segregation-of-duties conflicts
  with a script, convene the group owners in a Teams review chat to confirm keep or remove for each person, chase
  until every decision is in, remove the access they revoke (each removal goes to the manager for approval), and
  report back to the manager with the evidence pack. Use when a manager asks for an access review,
  recertification, user access review (UAR) or entitlement review of ServiceNow.
license: Proprietary demo content
compatibility: Group Functions Autopilot case desk with the ServiceNow MCP server. Scripts need Python 3.11+ (standard library only).
metadata:
  title: Privileged Access Review
  summary: Recertify privileged ServiceNow access with the owners in a Teams review and report the evidence.
  version: "1.0"
  domain: it
  servers: servicenow
  model-orchestrator: standard
  model-subagents: fast
  max-turns: "40"
  mode: assignment
  outputs: reports/access-review.md reports/decisions.csv
  launch: Run the quarterly privileged access review for ServiceNow and report back to me.
---

# Privileged Access Review

A manager has asked you to run a user access review (a quarterly IT general control for the bank's auditors). The
outcome: every privileged membership in scope has a recorded keep or remove decision from its owner, revoked access
is removed, and the manager has an evidence pack an auditor would accept.

Read `references/uar-standard.md` first; it defines scope, the flags, the owners and what evidence must show.

## First turn — build the population

1. Scope from the manager's instruction, else the standard's default groups and roles. For each group call
   `servicenow__list_group_members`; for each role `servicenow__list_role_holders`. Save the results as
   `data/groups.json` (a list of the group results) and `data/roles.json`.
2. `skill__run_script` → `review_pack.py data/groups.json data/roles.json`. It flags leavers (inactive but still a
   member), dormant accounts (no login in 90 days), SoD conflicts and direct privileged grants, and writes
   `reports/decisions.csv` with one row per owner, member and group, and a per-owner summary.
3. `case__start_review` with the owners the script lists (emails in the standard), topic "Q<n> privileged access
   review — ServiceNow", and a brief: what the review is, the deadline (three working days), and each owner's list
   of members with the flags, asking them to reply **keep** or **remove** per person (or "keep all except …").
4. Tell the manager with `case__message_requester` (expects_reply false) that the review is running and when you
   will report back. The review wait is already set.

## Later turns — collect, chase, act

- Each review reply wakes you. Record each decision in `reports/decisions.csv` (re-run the script with
  `--decisions data/decisions.json` after saving decisions as `{"<group>|<user_name>": {"decision": "keep|remove",
  "by": "<owner>", "note": "..."}}`). Acknowledge in the review chat briefly and say who is still outstanding.
- Flagged leavers and dormant accounts need a positive keep with a reason; challenge a bare "keep".
- When the follow-up timer fires with decisions missing, chase the named owners with `case__post_to_review`
  (mention_all) and wait again. After two chases, report the non-response to the manager.
- For every **remove**: `servicenow__remove_group_member` with the review reference. Each removal waits for the
  manager's approval; the approval wakes you.

## Report back

When every decision is in and the removals are done (or rejected), write `reports/access-review.md` (scope, date,
population counts, flags, decisions by owner, removals with approvals, exceptions) and `case__resolve` with a short
summary to the manager: population, how many kept and removed, anything outstanding, where the evidence is.
