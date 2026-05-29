---
name: weekly-pipeline-review-deck
description: |
  Creates a PowerPoint pack for the weekly pipeline / forecast review covering pipeline coverage,
  stage movement week-over-week, deals won and lost, deals slipped, and top deal one-pagers, using
  Salesforce data. Use when the user asks for a "weekly pipeline review", "weekly forecast deck",
  "pipeline review pack", "QBR-lite", or "pipeline call deck".
license: MIT
compatibility: Copilot Cowork Frontier with the Salesforce MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: Sales Manager / RevOps}
cowork.category: Sales
cowork.icon: SlidesFilled
---

# Weekly Pipeline Review Deck

## What This Skill Does

Produces a 10-slide PowerPoint pack for the weekly pipeline review meeting. Compares this week to
last week on pipeline coverage and stage movement, calls out deals won/lost/slipped, and includes
a one-pager for each of the top deals expected to close in the period.

## When To Use

- "Build the weekly pipeline review deck"
- "Pack for the Friday pipeline call"
- "Weekly forecast deck"

Do not use for a daily snapshot (`morning-pipeline-briefing-dashboard`), the monthly forecast call
(`forecast-call-pack`), or a single account (`account-deep-dive-brief`).

## Required Connector Tools

- `get_pipeline_dashboard`
- `list_opportunities` (open + recently closed)
- `get_team_pipeline_summary`
- `get_team_performance_metrics`
- `get_forecast`
- `get_account_360` (per top deal)
- `get_activity_timeline` (per top deal)

If the connector is not bound, stop and report.

## Default Workflow

1. Set window: this week vs last week. The "period" for forecast is the current quarter.
2. Pull pipeline dashboard, opps (open and won/lost in the last 7 days), team summary, forecast.
3. Compute:
   - Pipeline value by stage, coverage ratio = open pipeline / quota gap.
   - Stage movement WoW: new opps added, advanced, regressed, slipped close date, lost.
   - Top 5 deals expected to close this period (by amount × probability).
4. For each top deal, pull `get_account_360` and `get_activity_timeline` for the per-deal slide.
5. Build the deck.

## Slide Map

| # | Title | Visual | Notes |
|---|---|---|---|
| 1 | Pipeline Review — Week of {{week}} | KPI strip: open pipeline, coverage, commit, period delta | |
| 2 | Pipeline By Stage | Funnel + WoW deltas | |
| 3 | Coverage vs Quota | Bar: coverage ratio with target line | |
| 4 | Movement This Week | Table: added / advanced / regressed / slipped / lost | |
| 5 | Won This Week | Table: opp, account, amount, close date | |
| 6 | Lost & At-Risk | Table with reason, who, next action | |
| 7..N | Top Deal One-Pager | Per-deal slide (see layout) | One per top 5 deals |
| N+1 | Team Performance | From `get_team_performance_metrics` (if manager) | |
| N+2 | Actions for the Week | Owner, action, due | |

### Top Deal One-Pager

For each of the top 5 deals:

- **Opp**: name, account, amount, close date, stage, probability
- **Decision team** — buyer, champion, blocker (from `get_account_360`)
- **Recent activity** (top 3 from `get_activity_timeline`)
- **Risks & open questions**
- **Next 3 actions** (each with owner and due date)

## Analysis Rules

- Coverage ratio target should be the team's stated benchmark; if not known, state assumption
  (e.g. "3× target") on slide 3.
- Highlight any deal that has slipped its close date more than once in the period.
- Lost-reason analysis must group by reason, not speculate from notes.
- "At risk" = stage age > 1.5× median for that stage.

## Tone

Sales-management direct. Past-tense for outcomes, present for current state, imperative for
actions. No hedging.
