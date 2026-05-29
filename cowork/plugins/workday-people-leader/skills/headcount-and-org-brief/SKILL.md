---
name: headcount-and-org-brief
description: |
  Creates a PowerPoint headcount and organization brief for a skip-level review or HRBP sync,
  using Workday data: team structure (org chart), headcount mix by role/level/location, span of
  control, recent moves, and key talent indicators. Use when the user asks for an "org brief",
  "headcount deck", "skip-level pack", "org structure deck", "people deck for my skip-level",
  or "team profile pack".
license: MIT
compatibility: Copilot Cowork Frontier with the Workday MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: People Manager / Skip-level / HRBP}
cowork.category: People & HR
cowork.icon: OrganizationFilled
---

# Headcount & Org Brief

## What This Skill Does

Produces a PowerPoint pack that gives a senior leader a clean, evidence-based view of a team or
sub-org: org chart, headcount mix, span of control, key milestones, and talent indicators. Useful
for skip-level meetings, HRBP syncs, and quarterly people reviews.

## When To Use

- "Build my org brief for the skip-level"
- "Create the headcount deck for my org"
- "Quarterly people review pack"
- "Show me the structure of {{team}} as a deck"

Do not use for performance review prep (use `team-performance-review-pack`) or a quick channel
post (use `weekly-team-update-card`).

## Required Connector Tools

- `get_worker`, `get_direct_reports`
- `get_org_chart`
- `get_team_overview`
- `get_team_calendar`
- `get_worker_skills` (per direct report when building skills mix)
- `get_team_goals` (for the strategic alignment slide)

If the connector is not bound, stop and report.

## Default Workflow

1. Resolve the leader and the org by `get_worker` + `get_org_chart`. Establish the depth
   (default: leader + 2 levels).
2. Gather:
   - Headcount totals by level, role family, and (if available) location.
   - Span of control per manager in the org.
   - Time in role distribution.
   - Recent joiners and recent leavers in the period (default 90 days).
   - Skills mix snapshot.
   - Top 5 team goals.
3. Build the deck.

## Slide Map

| # | Title | Visual | Notes |
|---|---|---|---|
| 1 | {{org_name}} — Org Brief | KPI strip: headcount, manager:IC ratio, recent joiners, open roles (if known) | |
| 2 | Org Structure | Tree (text-based) leader → managers → ICs (counts) | From `get_org_chart` |
| 3 | Headcount Mix | Tables by role family, by level, by location | From `get_team_overview` |
| 4 | Span of Control | Bar list: each manager and their direct count | Highlight outliers (>9, <3) |
| 5 | Tenure & Time-in-role | Buckets: <6m, 6–12m, 1–2y, 2–5y, 5y+ | |
| 6 | Recent Movement | Table: joiners, role changes, leavers in the window | |
| 7 | Skills Snapshot | Top skills present in the org and notable gaps | |
| 8 | Strategic Alignment | Top 5 team goals + owner + status | From `get_team_goals` |
| 9 | Discussion Prompts | Three open questions for the skip-level | |

## Analysis Rules

- Span of control flags: ≤2 may indicate fragmented management; ≥10 may indicate stretched
  management. State both as "for discussion", not "as risks".
- Joiners/leavers: counts only, no names of leavers unless the manager has explicitly asked.
- Skills gaps: derived from team goals. Tag a skill as a gap only when it is required by ≥2 active
  team goals AND fewer than 20% of the team list it on `get_worker_skills`.
- Always show the data window on slide 1 footnote.

## Tone

Senior-leader appropriate, factual, neutral. Avoid HR jargon. Avoid emoji.
