---
name: morning-people-pulse-dashboard
description: |
  Builds a one-page HTML "Morning People Pulse" dashboard for a people manager using live Workday
  data: who is out today, pending Workday inbox tasks, learning overdue, goals at risk, and team
  calendar for the next two weeks. Use when the user asks for a "morning people pulse",
  "manager start-of-day briefing", "what does my team look like today", "Workday inbox snapshot",
  or "team out today".
license: MIT
compatibility: Copilot Cowork Frontier with the Workday MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: People Manager / Team Lead}
cowork.category: People & HR
cowork.icon: PersonClock
---

# Morning People Pulse Dashboard

## What This Skill Does

Produces an at-a-glance HTML dashboard a people manager can open at the start of the day to see
the state of their team — absences today, Workday inbox load, learning compliance gaps, and goals
that need attention. Designed to be scheduled (e.g. 07:30 daily) and rendered inline, in Loop, or
as an emailed snapshot.

## When To Use

- "Run my morning people pulse"
- "What does my team look like today"
- "Brief me before standup"
- "Manager dashboard for today"

Do not use for performance review prep (use `team-performance-review-pack`) or for a Teams chat
post (use `weekly-team-update-card`).

## Required Connector Tools

- `get_worker` — current worker (the manager)
- `get_direct_reports` — team roster
- `get_team_calendar` — who is out today / this week
- `get_team_overview` — headcount, role mix, key dates
- `get_team_performance_summary` — pending inbox + absence overview
- `get_inbox_tasks` — manager's own pending tasks
- `get_team_goals` — team goal status
- `get_learning_records` — learning compliance lookups (per direct report)

If none are available, stop and report the connector binding issue. Never invent team data.

## Default Workflow

1. Call `get_worker` and `get_direct_reports` to establish team context. State the manager and team
   name on the dashboard header.
2. In parallel, pull `get_team_calendar`, `get_team_overview`, `get_team_performance_summary`,
   `get_inbox_tasks`, and `get_team_goals`.
3. Compute KPIs:
   - Out today (count + names).
   - Out this week (count, peak day).
   - Manager inbox tasks: pending count, oldest age in days.
   - Goals at risk: goals with status "At Risk" or "Overdue".
   - Learning overdue: count of direct reports with overdue required learning.
4. Render the HTML dashboard following the template below.
5. Above the HTML, output 3–5 markdown bullets titled **"For your standup"** — one specific item
   per bullet (a name + an action), never generic advice.

## HTML Output Template

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>People Pulse — {{date}}</title>
<style>
  :root { --orange:#F38B00; --green:#2DA44E; --amber:#D29922; --red:#CF222E; --ink:#1F2328; --muted:#656D76; --line:#D0D7DE; --bg:#FBFAF7; }
  body { font-family:-apple-system,"Segoe UI",system-ui,sans-serif; color:var(--ink); margin:0; background:var(--bg); }
  .wrap { max-width:1180px; margin:0 auto; padding:24px; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:var(--muted); margin-bottom:18px; font-size:13px; }
  .grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:18px; }
  .kpi { background:white; border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  .kpi .label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  .kpi .val { font-size:28px; font-weight:600; margin-top:4px; }
  .kpi.amber .val { color:var(--amber); } .kpi.red .val { color:var(--red); }
  .row { display:grid; grid-template-columns:1.3fr 1fr; gap:12px; margin-bottom:14px; }
  .card { background:white; border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.04em; margin:0 0 10px; color:var(--muted); }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-weight:500; }
  .pill { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:600; }
  .pill.ok { background:#DAFBE1; color:var(--green); }
  .pill.risk { background:#FFF1CF; color:#9A6700; }
  .pill.over { background:#FFEBE9; color:var(--red); }
  .footer { color:var(--muted); font-size:11px; margin-top:18px; }
</style></head>
<body><div class="wrap">
  <h1>People Pulse — {{team_name}}</h1>
  <div class="sub">{{date}} · manager: {{manager_name}} · {{headcount}} reports</div>

  <div class="grid">
    <div class="kpi"><div class="label">Out today</div><div class="val">{{out_today}}</div></div>
    <div class="kpi amber"><div class="label">Out this week</div><div class="val">{{out_this_week}}</div></div>
    <div class="kpi amber"><div class="label">Inbox tasks</div><div class="val">{{inbox_pending}}</div></div>
    <div class="kpi red"><div class="label">Learning overdue</div><div class="val">{{learning_overdue}}</div></div>
  </div>

  <div class="row">
    <div class="card"><h2>Out today &amp; this week</h2>
      <table><thead><tr><th>Name</th><th>Type</th><th>From</th><th>To</th></tr></thead>
      <tbody>{{rows_calendar}}</tbody></table>
    </div>
    <div class="card"><h2>Inbox needs your attention</h2>
      <table><thead><tr><th>Task</th><th>Subject</th><th>Age</th></tr></thead>
      <tbody>{{rows_inbox}}</tbody></table>
    </div>
  </div>

  <div class="row">
    <div class="card"><h2>Goals at risk</h2>
      <table><thead><tr><th>Owner</th><th>Goal</th><th>Status</th><th>Due</th></tr></thead>
      <tbody>{{rows_goals_risk}}</tbody></table>
    </div>
    <div class="card"><h2>Learning compliance</h2>
      <table><thead><tr><th>Owner</th><th>Course</th><th>Due</th></tr></thead>
      <tbody>{{rows_learning_overdue}}</tbody></table>
    </div>
  </div>

  <div class="footer">Generated by Copilot Cowork · Workday MCP · {{generated_at}}</div>
</div></body></html>
```

## Rules

- Show "out today" only when at least one report is on time off intersecting today's date in the
  manager's stated timezone (default UTC).
- "Goals at risk" = explicit Workday status `At Risk` OR `Overdue`. Never infer from due dates
  alone.
- "Learning overdue" = any required learning whose due date is past today.
- Never include sensitive notes from inbox task descriptions; show only subject and short type.

## Tone

Operational and warm, not corporate-formal. This is a manager's at-a-glance tool.
