---
name: team-performance-review-pack
description: |
  Creates a manager-ready PowerPoint pack for performance reviews and calibration discussions
  using Workday data: per-direct-report goals, recent feedback, learning, check-ins, time-off
  history, and skills profile, plus a team-level summary slide. Use when the user asks for a
  "performance review pack", "calibration prep", "review prep deck", "talent review pack",
  "1:1 review pack" or "performance pack for my team".
license: MIT
compatibility: Copilot Cowork Frontier with the Workday MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: People Manager / HRBP}
cowork.category: People & HR
cowork.icon: PersonStarFilled
---

# Team Performance Review Pack

## What This Skill Does

Generates a PowerPoint pack a people manager can use to prepare for performance reviews,
calibration meetings, or talent reviews. The pack contains a team-level summary slide plus a
one-pager per direct report covering goals, feedback, learning, check-ins, and absences.

## When To Use

- "Build the performance review pack for my team"
- "Calibration prep deck"
- "1:1 review pack"
- "Talent review pack"

Do not use for a daily snapshot (use `morning-people-pulse-dashboard`) or for posting in chat
(use `weekly-team-update-card`).

## Required Connector Tools

- `get_worker`, `get_direct_reports`
- `get_team_goals`
- `get_goals` (per direct report when deeper goal text is needed)
- `get_feedback` (anytime feedback received)
- `get_learning_records`
- `get_check_ins`
- `get_time_off_entries`
- `get_worker_skills`
- `get_development_items`

If the connector is not bound, stop and report.

## Default Workflow

1. Resolve the manager (`get_worker`) and the team (`get_direct_reports`). Confirm scope with the
   user only if the team is unusually large (>15) or they hint at a sub-team.

2. For each direct report, gather:
   - Current goals + status (from `get_team_goals` summary; deepen with `get_goals` for the worker
     when a goal needs more context).
   - Recent anytime feedback received.
   - Learning completed in the period and any overdue items.
   - Last 3 check-ins.
   - Time-off taken in the period (counts only — not reasons).
   - Skills profile.
   - Development plan items.

3. Build the deck. Default review window is the last 6 months unless the user states otherwise.

## Slide Map

| # | Title | Visual | Notes |
|---|---|---|---|
| 1 | Team Performance Review — {{team_name}} | KPI strip: headcount, goals on track %, overdue learning %, check-in cadence | |
| 2 | Goals Overview | Stacked bar by status across team | From `get_team_goals` |
| 3 | Feedback Heatmap | Matrix: who has given/received feedback to whom | From `get_feedback` |
| 4 | Learning & Development | Table: completed vs overdue per report | |
| 5 | Check-in Cadence | Table: last check-in date per report, last topic | |
| 6 | Calibration Snapshot | 3×3 placement grid (manager fills) | Empty slots labelled, instructions in notes |
| 7..N | Direct Report One-Pager | Per-report layout (see below) | One slide per report |
| N+1 | Themes & Actions | Cross-team themes plus owner/action/due | |

### Direct Report One-Pager Layout

Each direct-report slide contains exactly:

- Header: name, role, time in role, manager
- **Goals** (top 3 with status + due)
- **Recent feedback** (top 3 most recent items, source masked to "peer" / "manager" / "stakeholder"
  unless the user has asked for attribution)
- **Learning** (completed in period + any overdue)
- **Check-ins** (last 3 dates, last topic)
- **Time off** in period (working days)
- **Strengths to recognise** (drawn from feedback themes)
- **Development focus** (from `get_development_items`)
- **Manager prompt for the conversation** (one open question)

## Analysis Rules

- Never infer a rating. Only present evidence the manager can use.
- Source-mask feedback authors by default; only attribute if the user explicitly asks.
- Flag a report as "needs attention" when ≥2 of: any overdue goal, any overdue learning, no
  check-in in the last 60 days. Show the flag on the team summary, not on the individual slide.
- Time-off totals are working days only.

## Tone

Manager-coaching. Treat the pack as preparation, not judgement. Use neutral language; let evidence
speak.
