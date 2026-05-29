---
name: rep-performance-coaching-deck
description: |
  Creates a manager 1:1 coaching PowerPoint pack for a single rep, using Salesforce data on
  pipeline contribution, stage conversion, activity volume, and recent deal outcomes. Use when
  the user asks for a "rep coaching pack", "1:1 deck for {rep}", "performance pack for my rep",
  "coaching deck", or "sales rep scorecard deck".
license: MIT
compatibility: Copilot Cowork Frontier with the Salesforce MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: Sales Manager}
cowork.category: Sales
cowork.icon: PersonChatFilled
---

# Rep Performance Coaching Deck

## What This Skill Does

Produces a PowerPoint pack a sales manager can use in a 1:1 coaching conversation with a single
rep: pipeline contribution, stage conversion vs team median, activity volume, recent wins and
losses with patterns, and a coaching-prompt slide. Designed to be evidence-led, not punitive.

## When To Use

- "Build a 1:1 coaching deck for {rep}"
- "Sales rep scorecard for {rep}"
- "Performance pack for my rep before our 1:1"

Do not use for executive review of the team (`weekly-pipeline-review-deck`,
`forecast-call-pack`) or single-account context (`account-deep-dive-brief`).

## Required Connector Tools

- `get_team_performance_metrics`
- `get_team_pipeline_summary`
- `list_opportunities` — for the rep, open + closed in last 90 days
- `list_tasks` — rep's activity volume
- `get_activity_timeline` — sample deal review
- `list_leads` — lead conversion

## Default Workflow

1. Resolve the rep (ask the user if not specified).
2. Pull rep-scoped pipeline + activity + closed deals (last 90 days).
3. Pull team-level metrics from `get_team_performance_metrics` for benchmarking.
4. Compute, for the rep:
   - Pipeline contribution: % of team open pipeline owned.
   - Stage conversion: rate per stage transition vs team median.
   - Activity volume: tasks/calls/meetings per week vs team median.
   - Win rate, average deal cycle, average deal size — all vs team median.
   - Lead-to-opp conversion.
5. Identify 3 patterns (positive or negative) supported by data, never anecdote.
6. Build the deck.

## Slide Map

| # | Title | Visual | Notes |
|---|---|---|---|
| 1 | {{rep_name}} — Coaching Prep | KPI strip: pipeline owned, win rate, cycle, activity | |
| 2 | Pipeline Contribution | Bar: rep vs team median across stages | |
| 3 | Stage Conversion | Per-stage conversion rate, with team median line | |
| 4 | Activity Volume | Weekly tasks / meetings / calls trend | |
| 5 | Recent Wins | Table: last 5 wins, amount, cycle, key activity | |
| 6 | Recent Losses | Table: last 5 losses with reason themes | |
| 7 | Patterns | 3 evidence-backed observations (strengths + opportunities) | |
| 8 | Sample Deal Walk-through | One open deal with `get_activity_timeline` | |
| 9 | Coaching Prompts | 3 open questions for the 1:1 | |
| 10 | Agreed Actions | Empty rows for the manager to fill during the 1:1 | |

## Analysis Rules

- Always benchmark against team median, never team max — fair and stable.
- A pattern must be supported by ≥3 data points and span at least 30 days.
- Loss reasons grouped from `Closed Lost` reason field, not inferred.
- Activity volume must be normalised by working days in the period.
- Never present a single bad week as a "trend".

## Tone

Manager-coaching. Evidence-led, growth-oriented, not judgemental. Frame the patterns slide as
"what the data shows" before "what to do".
