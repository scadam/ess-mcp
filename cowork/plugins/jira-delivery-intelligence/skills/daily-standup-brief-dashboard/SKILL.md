---
name: daily-standup-brief-dashboard
description: |
  Builds a daily HTML "Standup Brief" dashboard for an engineering manager or scrum master:
  what each team member is working on today, blockers, sprint burndown, items at risk of slipping
  the sprint, and a "for your standup" markdown summary above the dashboard. Designed to be
  scheduled before the daily standup. Use when the user asks for a "standup brief", "daily
  delivery brief", "team standup dashboard", "scrum standup pack", or "what's my team doing
  today".
license: MIT
compatibility: Copilot Cowork Frontier with the Jira MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: Engineering Manager / Scrum Master}
cowork.category: Engineering
cowork.icon: TaskListSquareLtrFilled
---

# Daily Standup Brief Dashboard

## What This Skill Does

Produces a one-page HTML dashboard for the daily standup, plus a "For your standup" markdown
block above it that the manager can read aloud. Shows current sprint burndown, today's in-flight
work per assignee, blockers, items at risk of slipping the sprint, and overnight changes.

## When To Use

- "Run my standup brief"
- "Daily standup dashboard for my team"
- "What is the team working on today"
- "Pre-standup briefing"

Do not use for sprint retrospective (`sprint-health-deck`) or release prep
(`release-readiness-pack`).

## Required Connector Tools

- `get_team_sprint_health`
- `get_team_workload`
- `list_sprints` (active)
- `list_issues` (by sprint, by status)
- `get_my_issues` (only when scoped to the user)
- `get_backlog` (for context on spillover risk)

If the connector is not bound, stop and report it. Never fabricate sprint metrics.

## Default Workflow

1. Resolve scope (team / project / board). Default = the active sprint on the user's primary board.
2. Pull `list_sprints(state="active")`, `get_team_sprint_health`, `get_team_workload`.
3. Pull `list_issues` for the active sprint, grouped by status.
4. Identify:
   - **Blockers** = issues with the `Blocked` flag or `Blocked` status, or with the label
     `blocked` / `impediment`.
   - **At risk** = open issues with remaining estimate > days left in sprint, or no progress in 2
     business days.
   - **Overnight changes** = issues whose status changed since the previous standup window.
5. Build the markdown block (see template) + the HTML dashboard.

## Markdown Block (above the dashboard)

```markdown
**For your standup — {{date}} · Sprint {{sprint_name}} · day {{day_n}} of {{sprint_len}}**

- Burndown: {{remaining_points}} pts remaining vs {{ideal_remaining}} ideal ({{burndown_state}}).
- Blockers: {{blocker_count}} — {{blockers_inline}}
- At risk of slipping: {{at_risk_count}} — {{at_risk_inline}}
- Overnight changes: {{overnight_count}} (see dashboard).
- Suggested standup order: {{assignee_order}}.
```

The "Suggested standup order" prioritises (1) anyone with a blocker, (2) anyone owning an at-risk
item, then (3) the rest in alphabetical order.

## HTML Output Template

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Standup Brief — {{date}} — {{team}}</title>
<style>
  :root { --blue:#0052CC; --green:#2DA44E; --amber:#D29922; --red:#CF222E; --ink:#1F2328; --muted:#656D76; --line:#D0D7DE; --bg:#F4F8FB; }
  body { font-family:-apple-system,"Segoe UI",system-ui,sans-serif; color:var(--ink); margin:0; background:var(--bg); }
  .wrap { max-width:1180px; margin:0 auto; padding:24px; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:var(--muted); margin-bottom:18px; font-size:13px; }
  .grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:18px; }
  .kpi { background:white; border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  .kpi .label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  .kpi .val { font-size:26px; font-weight:600; margin-top:4px; }
  .kpi.red .val { color:var(--red); }
  .kpi.amber .val { color:var(--amber); }
  .kpi.green .val { color:var(--green); }
  .row { display:grid; grid-template-columns:1fr 1fr; gap:12px; margin-bottom:14px; }
  .card { background:white; border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.04em; margin:0 0 10px; color:var(--muted); }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-weight:500; }
  .pill { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:600; }
  .pill.blocker { background:#FFEBE9; color:var(--red); }
  .pill.risk { background:#FFF1CF; color:#9A6700; }
  .pill.ok { background:#DAFBE1; color:var(--green); }
  .footer { color:var(--muted); font-size:11px; margin-top:18px; }
</style></head>
<body><div class="wrap">
  <h1>Standup Brief — {{team}}</h1>
  <div class="sub">{{date}} · Sprint {{sprint_name}} · day {{day_n}} of {{sprint_len}} · burndown {{burndown_state}}</div>

  <div class="grid">
    <div class="kpi"><div class="label">Remaining points</div><div class="val">{{remaining_points}}</div></div>
    <div class="kpi {{burndown_class}}"><div class="label">Ideal remaining</div><div class="val">{{ideal_remaining}}</div></div>
    <div class="kpi red"><div class="label">Blockers</div><div class="val">{{blocker_count}}</div></div>
    <div class="kpi amber"><div class="label">At risk</div><div class="val">{{at_risk_count}}</div></div>
  </div>

  <div class="row">
    <div class="card"><h2>In flight today, by assignee</h2>
      <table><thead><tr><th>Assignee</th><th>Issue</th><th>Status</th><th>Pts</th></tr></thead>
      <tbody>{{rows_in_flight}}</tbody></table>
    </div>
    <div class="card"><h2>Blockers &amp; at-risk</h2>
      <table><thead><tr><th>Issue</th><th>Owner</th><th>Why</th><th>State</th></tr></thead>
      <tbody>{{rows_blockers_risk}}</tbody></table>
    </div>
  </div>

  <div class="row">
    <div class="card"><h2>Overnight changes</h2>
      <table><thead><tr><th>Issue</th><th>From</th><th>To</th><th>By</th></tr></thead>
      <tbody>{{rows_overnight}}</tbody></table>
    </div>
    <div class="card"><h2>Spillover risk</h2>
      <table><thead><tr><th>Issue</th><th>Remaining</th><th>Days left</th><th>Recommendation</th></tr></thead>
      <tbody>{{rows_spillover}}</tbody></table>
    </div>
  </div>

  <div class="footer">Generated by Copilot Cowork · Jira MCP · {{generated_at}}</div>
</div></body></html>
```

## Analysis Rules

- "Burndown state" = on-track (within 10% of ideal), behind (10–25% behind), or critical (>25%).
- Spillover recommendation must be one of: "swarm", "descope", "split", "carry-over OK".
- Never list an issue as a blocker unless an explicit blocker indicator is present in the data —
  do not infer from comments.

## Tone

Operational. Short labels. Manager should be able to read the markdown block in 30 seconds.
