---
name: change-advisory-board-pack
description: |
  Creates the PowerPoint pack for a Change Advisory Board (CAB) meeting from ServiceNow change
  request data, including upcoming changes by risk, conflicts, freeze-window violations, recent
  failed changes, and per-change one-pagers for high-risk items. Use when the user asks for a
  "CAB pack", "change advisory board deck", "weekly CAB review", "change calendar pack" or
  "ECAB pack".
license: MIT
compatibility: Copilot Cowork Frontier with the ServiceNow MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: Change Manager / CAB Chair}
cowork.category: IT Operations
cowork.icon: CalendarLtr
---

# Change Advisory Board Pack

## What This Skill Does

Produces a CAB-ready PowerPoint pack covering the upcoming change window plus a retrospective on
the previous window. Every high-risk change gets a dedicated one-pager. Designed for the CAB chair
to walk through with limited prep.

## When To Use

- "Build the CAB pack for this week"
- "Create the change advisory deck"
- "Prep me for ECAB"
- "Show me what's going through CAB and which ones are risky"

Do not use this skill for a single-change deep dive (call `get_change_request` directly) or for
incident reviews (use `weekly-incident-trend-deck`).

## Required Connector Tools

- `list_change_requests` (state: scheduled, implement, review)
- `get_change_request` (per high-risk change)
- `list_incidents` (to flag changes touching CIs with active incidents)
- `get_cmdb_ci`, `list_cmdb_cis` (for CI-conflict detection)
- `list_approvals`, `get_approval` (pending change approvals)

If none of these are available, stop and report the connector binding issue.

## Default Workflow

1. Determine the **CAB window**: by default, the next 7 calendar days. Confirm with the user only
   if they have hinted otherwise.

2. Pull all changes intersecting the window. Bucket by risk (High / Moderate / Low) and by state.

3. For every High-risk change AND any Moderate-risk change with an unapproved state, fetch the full
   detail with `get_change_request` and identify:
   - Affected CI and any active incidents on that CI.
   - Conflicts with another scheduled change in the same window touching the same CI.
   - Pending approval status.
   - Backout plan presence.

4. Pull the previous 7-day window of implemented changes; flag any with state "failed" or that
   triggered an incident within 24 hours of the implementation window.

5. Build the deck.

## Slide Map

| # | Title | Visual | Notes |
|---|---|---|---|
| 1 | CAB — Window {{from}} → {{to}} | KPI strip (count by risk, pending approvals, conflicts) | |
| 2 | Change Calendar | Timeline / Gantt-style table by day | Highlight conflicts in red |
| 3 | Pending Approvals | Table: CHG #, requester, age, assignee | Sort by age |
| 4 | High-Risk Changes — Summary | Table: CHG #, owner, CI, conflict?, backout? | One row per High |
| 5..N | High-Risk Change One-Pager | Title, scope, CI, risk, conflict, approval, backout, recommendation | One slide per High-risk change |
| N+1 | Conflicts & Freeze Violations | Table grouping changes by CI with overlap window | |
| N+2 | Last Week — Implemented & Failed | Table: implemented count, failed count, failure RCAs needed | |
| N+3 | CAB Decisions | Table for chair to mark Approve / Defer / Reject inline | |

## Analysis Rules

- A change is **conflicted** when another change in the same window targets the same CI or a CI in
  the same business application.
- A change with no backout plan and risk ≥ Moderate is automatically a CAB discussion item.
- A High-risk change without all approvals 24h before the start window is a CAB discussion item.
- A previously-failed change being retried gets its own callout slide.

## Per-Change One-Pager Format

For every high-risk change, produce a slide with these fields exactly:

- **Change**: CHG number and short description
- **Owner / Assignment group**
- **Window**: planned start → planned end
- **Affected CI(s)** and business service
- **Risk** and rationale
- **Conflicts**: list other CHG numbers or "None"
- **Approvals**: list of approvers and state
- **Backout plan**: present / missing
- **Recommendation for CAB**: Approve / Approve-with-conditions / Defer / Reject — and why

## Tone

Direct, change-management formal. No filler. CAB chairs read these standing up.
