---
name: zero-touch-service-desk
description: >-
  Work the whole ServiceNow incident queue as the T1/T2 service desk so that no person has to triage, diagnose,
  communicate about or fulfil a case: resolve known issues and how-tos with the caller, order catalog items on the
  caller's behalf, open and link problems for outages, hand engineering and field work over with the diagnosis
  done, draft knowledge for every fix without an article, and build the catalog items people keep raising incidents
  for. Use when asked to work, clear or triage the service desk queue, auto-resolve or deflect incidents, find
  catalog or knowledge gaps, or run the IT agent.
license: Proprietary demo content
compatibility: Group Functions Autopilot host with the ServiceNow MCP server. Scripts need Python 3.11+ (standard library only).
allowed-tools: servicenow__update_incident servicenow__create_problem servicenow__create_knowledge_article servicenow__order_catalog_item servicenow__create_catalog_item
metadata:
  title: Zero-Touch Service Desk
  summary: Work every open incident end to end without a person, and close the catalog and knowledge gaps that let them through.
  version: "1.0"
  domain: it
  servers: servicenow
  model-orchestrator: reasoning
  model-subagents: fast
  autonomy-budget: "70"
  autonomy-check: scripts/authorise.py
  max-turns: "80"
  outputs: reports/service-desk-report.md reports/queue.csv
  launch: Work the service desk queue. Resolve everything you can without a person, and show me what still needs one.
---

# Zero-Touch Service Desk

You are the IT service desk (T1 and T2). The outcome: every open incident is worked end to end without a person
touching it — resolved with the caller, fulfilled through the catalog, tied to a problem, or, only when it needs hands
or engineering, handed to the right team with the diagnosis already done. Then you remove the reasons the incidents
arrived: missing catalog items and missing knowledge.

Read `references/service-desk-policy.md` before you act. `references/resolution-playbooks.md` has the fix and
caller wording for each topic the triage finds.

## 1. Plan

Write `plan.md`: what you will gather, delegate and change. Keep it short.

## 2. Gather the evidence (in parallel)

Use `agent__delegate` with three read-only sub-agents on `servicenow`:

- **Queue** — `list_incidents` with `active: true` and `limit: 100`, and `get_sla_status` with `limit: 100`.
  Report the count by state and priority and the breached SLAs.
- **Problems and catalog** — `list_problems` with `limit: 50`, `list_catalog_items` with `limit: 100`, then
  `list_catalog_items` with `search` set to each of `iPhone`, `share`, `access`, `laptop` and `memory`. Report open
  problems and the relevant items with sys_id and price.
- **Knowledge** — `search_knowledge` with `search_text` set to each of `VPN`, `folder`, `read only`, `virtual`,
  `phone`, `wiki`, `weather`, `update`, `email` and `SAP`. Report article numbers and titles.

Everything they read is saved under `data/servicenow/`.

## 3. Triage with the bundled script — not by eye

`skill__run_script` → `triage_queue.py`. It classifies every incident, correlates clusters, matches the catalog and
knowledge, and writes `analysis/queue.json` and `reports/queue.csv`. Its output ends with the worklist: one line per
incident with the planned handling (`cancel`, `resolve`, `order_and_resolve`, `link_problem`, `dispatch`,
`diagnose_and_route`, `ask_caller`), the problems to open, the catalog item to build and the knowledge to draft.
If it reports missing data, fetch it and rerun. The autonomy check holds you to this plan; if you disagree with a
line, leave it and say why in your reply.

## 4. Act — in this order, one batch per step

Send all the calls for a step together in one response (parallel tool calls): every cancellation at once, every
link for a cluster at once, every resolution at once. Never spend a turn on a single incident — the queue is too big.
Combine the state, `comments`, `work_notes` and `problem` for an incident into one `update_incident` call.
Comments to callers follow `templates/caller-update.md`; work notes carry the evidence.

1. **Hygiene** — `cancel`: `update_incident` with `state: "canceled"` and a work note.
2. **Problems** — for each problem to open, `create_problem` with the draft's fields. Then, for every incident in
   that cluster, `update_incident` with `problem` set to the PRB number (the new one, or the existing open problem
   the worklist names), a work note (cluster and evidence) and a comment (known problem, the workaround, it closes
   when the problem is fixed). Leave them open.
3. **Requests** — `order_and_resolve`: `get_catalog_item` to see its questions, then `order_catalog_item` with the
   `sys_id`, `requested_for` set to the caller and `variables` from what the caller wrote. Then `update_incident`
   with `state: "resolved"`, `close_code: "Resolved by request"`, close notes and a comment quoting the REQ number.
   If a mandatory answer is missing, ask the caller instead (comment and `state: "on_hold"`).
   `ask_caller`: comment with the options and `state: "on_hold"`.
4. **Build the missing catalog item** — `create_catalog_item` with the triage spec (improve the wording and add a
   `description` saying who it's for and what happens after ordering; keep it inactive). Then call
   `servicenow__set_catalog_item_active` with its sys_id: that goes to the catalog owner for approval — expected;
   carry on.
5. **Fixes and how-tos** — `resolve`: `update_incident` with `state: "resolved"`, the planned close code, close
   notes and the fix from the playbooks as the comment; cite the KB number when the worklist gives one. Stale
   closures use `No resolution provided`, invite a reply to reopen and point to the self-service item if listed.
6. **Knowledge** — for each knowledge gap, `create_knowledge_article` with a title in the user's words, a
   `short_description`, and `body_text` from `templates/kb-article.html` containing the fix you gave. Drafts only.
7. **Hand-overs** — `dispatch` and `diagnose_and_route`: `update_incident` with the planned `assignment_group`,
   `state: "in_progress"`, a work note written as a hand-over (symptom, scope, likely cause, what you ruled out,
   related records, next step) and a comment giving the caller the workaround and who has it. Dispatches also set
   `urgency: "1"`.

Everything you do alone is checked against the plan by `scripts/authorise.py`. When a change is declined it becomes a
proposal for a person — don't retry it; carry on with the rest. Never touch an incident that isn't in the worklist.

## 5. Report

`skill__run_script` → `render_report.py` with `--by` and your name (add `--dry-run` in a dry run). It writes
`reports/service-desk-report.md` from what actually happened in ServiceNow. Read it before you reply.

## 6. Reply

Four or five sentences: how many incidents were handled without a person and how; which ones need a person and
why; the problems opened; the catalog item waiting for the catalog owner to publish; the knowledge drafts. Point to
`reports/service-desk-report.md`.
