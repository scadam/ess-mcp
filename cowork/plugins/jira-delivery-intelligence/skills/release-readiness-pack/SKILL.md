---
name: release-readiness-pack
description: |
  Creates a PowerPoint release-readiness pack for a Jira fix-version: scope summary, completion %
  by epic, open blockers, items at risk of missing the release, dependencies across teams, and
  go/no-go recommendation criteria. Use when the user asks for a "release readiness pack",
  "release deck", "fix-version readiness", "go/no-go deck", or "release status pack".
license: MIT
compatibility: Copilot Cowork Frontier with the Jira MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: Engineering Manager / Release Manager / Product}
cowork.category: Engineering
cowork.icon: RocketFilled
---

# Release Readiness Pack

## What This Skill Does

Produces a PowerPoint go/no-go readiness pack for a single Jira fix-version: scope summary,
completion % by epic, open blockers, items at risk of missing the cut, cross-team dependencies,
and a go/no-go criteria slide that the release manager fills in.

## When To Use

- "Build the release readiness pack for {version}"
- "Go/no-go deck for {fix-version}"
- "Release status pack"

Do not use for sprint-level review (`sprint-health-deck`) or daily standup
(`daily-standup-brief-dashboard`).

## Required Connector Tools

- `list_versions`
- `list_issues` (filtered by `fixVersion`)
- `list_epics`
- `get_team_workload`
- `list_projects`

## Default Workflow

1. Resolve the fix-version (ask the user if multiple are in flight).
2. Pull all issues for that fix-version with full epic + status + assignee.
3. Compute per-epic completion %, open blocker count, items at risk.
4. Identify cross-team dependencies = issues whose `assignee` belongs to a different team/project
   than the version owner, or that link to issues in another project.
5. Build the deck.

## Slide Map

| # | Title | Visual | Notes |
|---|---|---|---|
| 1 | {{version}} — Release Readiness | KPI strip: completion %, days to cut, blockers, at-risk | |
| 2 | Scope Summary | Pie / bar by epic and type | |
| 3 | Completion by Epic | Stacked bar: done / in-progress / not-started per epic | |
| 4 | Open Blockers | Table with owner, age, mitigation | |
| 5 | Items At Risk | Table of issues likely to slip the cut, with reason | |
| 6 | Cross-Team Dependencies | Table: dependency, on whom, status | |
| 7 | Quality Signals | Open bug count, regression count, severity mix | |
| 8 | Go / No-Go Criteria | Empty checklist for release manager (P0 bugs, perf, docs, ops) | |
| 9 | Recommendation | One-paragraph summary + named risks | |

## Analysis Rules

- Completion % = done points / total points, OR done issues / total issues if estimates aren't
  used; state the basis on slide 3.
- "At risk" = open + (no remaining estimate OR remaining estimate > days to cut OR no progress
  in 5 days).
- Cross-team dependencies are listed once, with directionality.
- The recommendation slide must restate the assumption window ("based on data through
  {{generated_at}}").

## Tone

Release-management direct. Make the call surface-able, but the call itself is the human's.
