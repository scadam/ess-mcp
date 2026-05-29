---
name: morning-pipeline-briefing-dashboard
description: |
  Builds a visually rich HTML "Morning Pipeline Briefing" dashboard for an account executive or
  sales manager, combining live Salesforce data with Microsoft 365 WorkIQ context (recent
  meetings, email, Loop). Includes inline SVG charts — a pipeline funnel, forecast vs quota
  donut, coverage gauge, 30-day activity sparklines, stage-age heatmap, and top-account treemap —
  alongside today's tasks and meetings, top accounts to focus, deals slipping, and a recommended
  activity plan. Designed to be scheduled daily. Use when the user asks for a "morning pipeline
  briefing", "today's plan", "AE morning brief", "what should I work on today", "pipeline
  dashboard", or "daily sales briefing".
license: MIT
compatibility: Copilot Cowork Frontier with the Salesforce MCP connector. Uses built-in WorkIQ context where available.
metadata: {author: ESS MCP Demo, version: "1.1.0", demo-audience: AE / Sales Manager}
cowork.category: Sales
cowork.icon: ChartMultipleFilled
---

# Morning Pipeline Briefing Dashboard

## What This Skill Does

Produces a one-page **HTML dashboard** for an account executive or front-line sales manager to
read at the start of the day. Combines live Salesforce pipeline + activity data with Microsoft 365
WorkIQ context (recent meetings, emails to/from key contacts, Loop pages) to recommend an
**activity plan for today**. Designed to be scheduled (07:30 daily) and rendered inline in chat,
in Loop, or as an emailed snapshot.

The dashboard is deliberately **chart-forward** — the manager should be able to read pipeline
shape, forecast confidence, momentum, and stage-age risk without scanning a table. Every chart is
inline SVG or pure CSS (no JS, no external assets) so it renders identically in chat surfaces,
Loop, and email.

## When To Use

- "Run my morning pipeline briefing"
- "Brief me before my day starts"
- "What should I work on today"
- "Daily sales briefing for today"
- "AE morning dashboard"

Do not use this for a weekly forecast review (use `weekly-pipeline-review-deck`), monthly forecast
call (`forecast-call-pack`), or a single-account brief (`account-deep-dive-brief`).

## Required Connector Tools

- `get_pipeline_dashboard` — current pipeline snapshot
- `list_opportunities` — open opportunities, sortable by close date / amount / stage age
- `list_tasks` — today's tasks for the user
- `get_team_pipeline_summary` — only when the user is a manager
- `get_activity_timeline` — per top account, recent activity
- `get_account_360` — for the spotlight account
- `list_leads` — top leads to follow up
- `get_forecast` — current period forecast for context

If none are available, stop and report the connector binding issue. Never invent pipeline numbers.

## Optional WorkIQ Context

When the host environment exposes WorkIQ / Microsoft Graph context for the current user, also
pull (in priority order):

- Today's calendar events whose attendees match contacts on top accounts.
- Most recent emails (last 3 days) involving key contacts on at-risk opportunities.
- Loop pages and shared docs referenced in recent meetings on top accounts.

Use this WorkIQ context to **explain** prioritisation decisions in the activity plan ("Acme moved
up because you have a 14:00 with their CFO and they replied to your proposal yesterday"). Never
quote private email content verbatim — paraphrase as a context cue only.

## Default Workflow

1. Resolve the user (AE or manager) from the host. Default timezone UTC unless stated.
2. In parallel:
   - `get_pipeline_dashboard()` — totals by stage, coverage ratio.
   - `list_opportunities(state="open")` — pull open opps, sort by stage age desc.
   - `list_tasks(date="today")` — today's tasks.
   - `get_forecast()` — period commit, best case, closed, quota.
   - `list_leads(status="new", recent=true)` — fresh leads.
3. Identify **top 5 focus accounts** for today by combining:
   - Largest open opp value.
   - Stage age past expected.
   - WorkIQ signal: a meeting today with that account, or an email reply in last 48h.
4. For each top focus account, call `get_activity_timeline` to surface the most recent material
   activity (last call, last meeting outcome, last email).
5. Pick **one spotlight account** = the one with the best combination of open value and active
   WorkIQ signal. Call `get_account_360` for richer context.
6. Build a recommended **activity plan for today**: 5–7 specific actions, each tied to an account,
   contact, or opportunity (no generic advice). Include time-blocks if today's calendar is known.
7. **Compute chart series** before rendering (see `references/dashboard-spec.md` for formulas):
   - `funnel[]` — one entry per active stage: `{stage, value, count, expected_age, actual_age}`.
   - `forecast` — `{quota, closed, commit, best_case}` derived from `get_forecast()`.
   - `coverage_ratio` — open pipeline ÷ remaining quota.
   - `activity_30d` — 30-day daily counts for meetings, emails, calls (best-effort from
     `get_activity_timeline` aggregated across the user's open opps, or from WorkIQ if richer).
   - `top_accounts[]` — top 5 by open value, with each account's open value as a share of the top 5
     total (for the treemap).
   - `slipping[]` — opps where `actual_age` > 1.5 × `expected_age` for the current stage, with a
     `slip_ratio` 0–1 used to size the inline heat bar.
8. Render the HTML using the skeleton in `references/dashboard-spec.md`. Charts are inline SVG /
   CSS — never embed external images or scripts. Substitute every `{{token}}` with a computed
   value; do not strip classes or change chart structure (SVG dimensions are tuned for the layout).

## Dashboard Layout (Reference)

The full HTML skeleton + chart computation formulas live in
[`references/dashboard-spec.md`](references/dashboard-spec.md). At a glance:

- **KPI strip** (4 tiles) with 7-day delta chips: Open pipeline, Commit, Best case, Closed-won.
- **Hero row**: Pipeline funnel (horizontal stage bars) + Forecast-vs-quota donut.
- **Momentum row**: Coverage gauge (semi-circular SVG, red/amber/green by ratio) + 30-day
  meetings / emails / calls sparklines.
- **Spotlight account** card (full width) + **Activity plan** card (full width).
- **Insight row**: Top-5 accounts treemap + Stage-age heatmap (cells coloured by
  actual ÷ expected age).
- **Detail row**: Top open opportunities table + today's tasks & meetings.
- **Detail row**: Slipping deals table (with inline slip-risk heat bar) + Fresh leads.

## Activity Plan Rules

- 5–7 items maximum.
- Every item must reference a specific opportunity, contact, account or task ID.
- Pair each item with a short rationale ("stage age 22 days vs 12 expected", "CFO replied
  yesterday", "demo today at 14:00").
- Order by what is time-bound first (meetings/calls), then by deal value × heat.
- Never recommend a generic action like "review pipeline" — replace with the concrete next call,
  email, or update.

## Heat Calculation

For the "Heat" column on top opps:

- **hot** — close date ≤ 14 days AND (stage = Negotiate or Propose) AND any activity in last 7 days.
- **warm** — open value > median open value of the user's pipeline AND last activity in last 14 days.
- **ok** — otherwise.

## WorkIQ Disclosure

When WorkIQ context is used, the dashboard footer reads "with WorkIQ context"; when it isn't,
it reads "Salesforce-only". Never silently downgrade — be transparent in the footer.

## Tone

Sales-rep practical. First-person where natural ("Your top deal…"). No hype. No emoji.
