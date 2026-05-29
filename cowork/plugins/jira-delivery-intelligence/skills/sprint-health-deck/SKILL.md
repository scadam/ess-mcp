---
name: sprint-health-deck
description: |
  Creates a PowerPoint pack for a sprint review or retrospective covering scope changes, burndown,
  velocity vs prior sprints, completed vs committed, blockers timeline, and per-engineer
  contribution, using Jira data. Use when the user asks for a "sprint health deck", "sprint
  review pack", "retrospective deck", "end-of-sprint deck", or "velocity deck".
license: MIT
compatibility: Copilot Cowork Frontier with the Jira MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: Engineering Manager / Scrum Master}
cowork.category: Engineering
cowork.icon: SlidesFilled
---

# Sprint Health Deck

## What This Skill Does

Produces a PowerPoint pack for a sprint review / retrospective: committed vs completed,
burndown, velocity trend across the last N sprints, scope-change timeline, blockers timeline,
and per-engineer contribution. Designed to be evidence-led and not blame-oriented.

## When To Use

- "Build the sprint review deck for the current sprint"
- "Retrospective pack"
- "End-of-sprint deck"

Do not use for daily standup (`daily-standup-brief-dashboard`) or release readiness
(`release-readiness-pack`).

## Required Connector Tools

- `list_sprints`
- `get_sprint`
- `get_team_sprint_health`
- `list_issues` (by sprint)
- `get_team_workload`
- `list_boards`

## Default Workflow

1. Resolve the target sprint (default = most recently closed sprint on the user's primary board).
2. Pull the target sprint plus the previous 5 sprints for trend context.
3. For each, pull `list_issues` to compute committed vs completed, scope additions/removals
   mid-sprint, and per-engineer points completed.
4. Build the deck.

## Slide Map

| # | Title | Visual | Notes |
|---|---|---|---|
| 1 | {{sprint_name}} — Sprint Review | KPI strip: committed, completed, %, scope change | |
| 2 | Burndown | Burndown chart: ideal vs actual | |
| 3 | Velocity Trend | Bar of last 6 sprints (committed vs completed) | |
| 4 | Scope Changes | Timeline: items added/removed mid-sprint with reason | |
| 5 | Blockers Timeline | When blockers appeared, who, time-to-resolve | |
| 6 | Completed Work | Categorised by epic/label/type | |
| 7 | Carried Over | List with reason themes | |
| 8 | Per-Engineer Contribution | Bar per assignee (cycle time + points) | |
| 9 | What Went Well / Watch | Two-column observations supported by data | |
| 10 | Actions for Next Sprint | Owner, action, due | |

## Analysis Rules

- "Velocity" = points or issue count of completed items, consistent across all sprints in the
  trend chart. Do not mix metrics.
- Scope-change reasons must come from the issue history, not be inferred.
- Per-engineer slide is for capacity awareness; never imply ranking or judgement. Order
  alphabetical, not by output.
- "What went well / watch" must each list ≥3 evidence-backed items.

## Tone

Retrospective-friendly. Curious, not punitive. Past tense for outcomes.
