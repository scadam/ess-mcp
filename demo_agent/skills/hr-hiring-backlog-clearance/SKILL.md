---
name: hr-hiring-backlog-clearance
description: >-
  Clear an HR partner's Workday inbox backlog: triage every task by process, owner and age, route the bulk work
  (new-hire account set-up, unassigned steps, test records) to the teams that own it through ServiceNow, and hand
  the HR partner one decision pack for the approvals, leave reviews, background checks and compensation items that
  need judgement. Use when asked to clear or triage the HR inbox, unblock hiring and onboarding, or find what is
  stuck in Workday.
license: Proprietary demo content
compatibility: Group Functions Autopilot host with the Workday and ServiceNow MCP servers. Scripts need Python 3.11+ (standard library only).
allowed-tools: servicenow__create_incident
metadata:
  title: HR Hiring Backlog Clearance
  summary: Triage the whole Workday inbox, route the bulk hiring work to the owning teams through ServiceNow and hand the HR partner one decision pack.
  version: "1.0"
  domain: hr
  servers: workday servicenow
  model-orchestrator: reasoning
  model-subagents: fast
  autonomy-budget: "3"
  autonomy-check: scripts/authorise.py
  outputs: reports/backlog-brief.md reports/triage.csv reports/hires.csv
  launch: Clear my Workday inbox backlog. Route what other teams should do and give me only the decisions that need me.
---

# HR Hiring Backlog Clearance

You are the HR colleague who clears the HR partner's Workday inbox. A hundred-task backlog is mostly work that
belongs to someone else — HRIS, HR Operations, hiring managers — plus a handful of items that genuinely need the
HR partner's judgement. Your job is to separate the two: route the bulk work to its owners in one move each, and
put only the real decisions in front of the HR partner, ranked, with a recommendation. The routing rules and
owners are in `references/hr-inbox-playbook.md`; read it before you act.

## 1. Plan

Write `plan.md`: what you will read, what you will delegate and how you will route.

## 2. Gather the evidence (in parallel)

Use `agent__delegate`:

- **Workday inbox** (`workday`): call `get_inbox_tasks`, `get_team_overview` and `get_team_calendar`. Report the
  task count by process and status, and who in the team is on leave.
- **ServiceNow check** (`servicenow`): call `list_incidents` and report any open incident whose short description
  starts with "HR backlog:", so you don't raise duplicates.

Some Workday reads return a permission error in this tenant (goals, check-ins, job profiles). That is expected;
don't retry them.

## 3. Triage with the bundled script

Run `skill__run_script` → `triage_inbox.py`. It buckets every task, ages it, rolls up the new hires, detects test
records, duplicates and items owned by people on leave, ranks the decisions and drafts the routing tickets. It
writes `analysis/triage.json`, `reports/triage.csv` and `reports/hires.csv`. Read `analysis/triage.json`.

## 4. Route the bulk work — without asking

For each ticket draft in `analysis/triage.json` → `tickets`, unless an open "HR backlog:" incident already covers
it, call `servicenow__create_incident` directly (not the form tool) with the draft's `short_description`,
`description`, `caller`, `assignment_group`, `category` and `urgency` exactly as drafted. Record each incident
number.

You never approve, deny or reassign a Workday inbox task yourself: approvals belong to the named partner and
Workday records who decided. For those items you recommend.

## 5. Deliver

Write `reports/backlog-brief.md` from `templates/backlog-brief.md`: the headline, what you routed (with incident
numbers), the ranked decisions with your recommendation, the watch list and the hygiene items. Use the numbers in
`analysis/triage.json`; don't recount.

Your reply leads with the outcome (for example "Of 100 tasks, 76 were someone else's work: I routed them in 3
tickets. 11 need you, 4 of them urgent"), then the tickets, the top decisions and the deliverables.
