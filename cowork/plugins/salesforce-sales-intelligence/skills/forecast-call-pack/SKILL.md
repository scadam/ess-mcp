---
name: forecast-call-pack
description: |
  Builds the PowerPoint pack for a monthly or quarterly forecast call with the sales VP, covering
  team forecast roll-up by category (commit, best case, pipeline), changes since last submission,
  top deals with confidence, and risk register. Use when the user asks for a "forecast pack",
  "forecast call deck", "monthly forecast deck", "QBR forecast pack", or "VP forecast review".
license: MIT
compatibility: Copilot Cowork Frontier with the Salesforce MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: Sales Manager / Director / RevOps}
cowork.category: Sales
cowork.icon: PresenterFilled
---

# Forecast Call Pack

## What This Skill Does

Produces a forecast-call PowerPoint pack a sales manager can walk into a VP review with: roll-up
by forecast category, changes since the last submission, top deals with confidence narrative, and
a risk register.

## When To Use

- "Build the forecast call pack for this month"
- "VP forecast review deck"
- "QBR forecast pack"

Do not use for weekly pipeline review (`weekly-pipeline-review-deck`) or for a single-account brief
(`account-deep-dive-brief`).

## Required Connector Tools

- `get_forecast`
- `get_team_pipeline_summary`
- `get_team_performance_metrics`
- `list_opportunities` (open in the period + recently closed)
- `get_pipeline_dashboard`
- `get_account_360` (per top deal)
- `get_activity_timeline` (per top deal)
- `list_reports` / `run_report` (when a custom forecast report exists)

## Default Workflow

1. Determine the period (default current quarter).
2. Pull team forecast roll-up by category: Closed, Commit, Best Case, Pipeline, Omitted.
3. Pull last submission's totals (if available via `list_reports`+`run_report`); compute deltas.
4. Identify the top 5 deals contributing to Commit and the top 5 risks (deals slipped, lost in
   period, or moved out of Commit).
5. Build the deck.

## Slide Map

| # | Title | Visual | Notes |
|---|---|---|---|
| 1 | {{team}} Forecast — {{period}} | KPI strip: Closed, Commit, Best Case, Pipeline, Quota gap | |
| 2 | Roll-up by Category | Stacked bar by AE / segment | |
| 3 | Change Since Last Submission | Waterfall: previous → added → removed → moved → current | |
| 4 | Coverage & Linearity | Coverage ratio + week-by-week closed pace | |
| 5..9 | Top Commit Deals | Per-deal one-pager (see layout) | |
| 10 | Risk Register | Table of slipped / regressed / lost deals with mitigation | |
| 11 | Asks for the Business | Specific exec actions needed (not generic "support") | |

### Per Top-Commit Deal Layout

- Opp, account, amount, close, stage, probability, forecast category
- Decision team summary (from `get_account_360`)
- 3 most recent material activities
- Manager confidence narrative (one short paragraph the manager can speak to)
- Risks and required next steps

## Analysis Rules

- "Commit" must reconcile to `get_forecast` Commit total; if it doesn't, stop and surface the
  reconciliation gap as the first slide bullet.
- "Change since last submission" requires a prior snapshot; if unavailable, state on slide 3 that
  delta is not computable and show only current totals.
- Risk register must list named deals only — no "general macro risk".
- Asks for the business must each name an exec, an action, and a date.

## Tone

Forecasting discipline. No optimism without evidence. State assumptions explicitly.
