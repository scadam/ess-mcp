---
name: morning-it-pulse-dashboard
description: |
  Builds a one-page HTML "Morning IT Pulse" dashboard for an IT service-management manager
  or duty officer using live ServiceNow data. Use when the user asks for a "morning IT briefing",
  "start-of-day IT dashboard", "what's broken right now", "IT operations status", "P1/P2 dashboard",
  "SLA breach view", or "today's change calendar".
license: MIT
compatibility: Copilot Cowork Frontier with the ServiceNow MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: IT Service Management lead}
cowork.category: IT Operations
cowork.icon: BoltFilled
---

# Morning IT Pulse Dashboard

## What This Skill Does

Produces an executive-style **HTML dashboard** that an IT Service Management lead, duty manager, or
NOC supervisor can open at the start of the day to see the operational health of the estate at a
glance. Combines live incidents, breached SLAs, the change calendar, top assignment groups, and
pending approvals into one printable page.

This skill is intended to be run on a daily schedule (for example 07:30 local time). The output is
HTML so it renders inline in chat, in a Loop page, or as an email attachment.

## When To Use

Trigger this skill when the user asks for any of:

- "Run my morning IT pulse"
- "Give me the IT operations dashboard"
- "What is broken right now"
- "Show me today's SLA breaches and the change calendar"
- "I'm covering for the duty manager today, brief me"

Do not use this skill for a single-incident triage (use the `list_incidents` / `get_incident` tools
directly) or for retrospective trend analysis (use `weekly-incident-trend-deck` instead).

## Required Connector Tools

If none of the ServiceNow connector tools below are available in the task, stop and tell the user
the package skill loaded but the ServiceNow MCP connector did not bind. Do not fabricate data.

- `list_incidents` — open P1/P2/P3 active incidents
- `get_sla_status` — breached and at-risk SLAs
- `get_team_incidents` — workload by assignee and assignment group
- `get_team_approvals` — pending approvals queue
- `list_change_requests` — changes scheduled today / in-progress
- `list_problems` — open problems
- `list_tasks` — recently updated active tasks (for the activity ticker)

## Default Workflow

1. Resolve "today" in the manager's timezone if the user has stated one; otherwise use UTC and label
   it explicitly in the dashboard footer.

2. Gather data, in this order, in parallel where the host permits:

   - `list_incidents(state="active", priority="1")` then `priority="2"` — count and top 5 each
   - `get_sla_status(breached_only=true)` for the breach list
   - `get_sla_status()` for at-risk percentage
   - `get_team_approvals()` — bucket by source table
   - `list_change_requests(state="scheduled")` and `state="implement"` — today's CAB items
   - `list_problems(state="active")` — count plus top 3 by priority
   - `get_team_incidents()` — workload heatmap

3. Compute simple KPIs:

   - Open P1, Open P2, Total active incidents
   - SLA breach count, % at risk
   - Pending approvals (last 24h vs older than 24h)
   - Active changes today, count by risk
   - Top 5 assignment groups by open incident volume

4. Render the dashboard as a single self-contained HTML document (see template below). Inline all
   CSS, no external assets, no JS frameworks. Use system font stack.

5. End with three to five **"Recommended actions for the next 2 hours"** as plain text bullets above
   the dashboard, so a busy manager can act without scrolling.

## HTML Output Template

The dashboard MUST follow this skeleton. Adjust numbers and rows from live data; never inline
placeholder figures.

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Morning IT Pulse — {{date}}</title>
<style>
  :root { --green:#2DA44E; --amber:#D29922; --red:#CF222E; --ink:#1F2328; --muted:#656D76; --line:#D0D7DE; --bg:#F6F8FA; }
  body { font-family: -apple-system, "Segoe UI", system-ui, sans-serif; color:var(--ink); margin:0; background:var(--bg); }
  .wrap { max-width:1180px; margin:0 auto; padding:24px; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:var(--muted); margin-bottom:18px; font-size:13px; }
  .grid { display:grid; grid-template-columns:repeat(4, 1fr); gap:12px; margin-bottom:18px; }
  .kpi { background:white; border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  .kpi .label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  .kpi .val { font-size:28px; font-weight:600; margin-top:4px; }
  .kpi.red .val { color:var(--red); } .kpi.amber .val { color:var(--amber); } .kpi.green .val { color:var(--green); }
  .row { display:grid; grid-template-columns: 1.4fr 1fr; gap:12px; margin-bottom:14px; }
  .card { background:white; border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.04em; margin:0 0 10px; color:var(--muted); }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-weight:500; }
  .pill { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:600; }
  .pill.p1 { background:#FFEBE9; color:var(--red); }
  .pill.p2 { background:#FFF1CF; color:#9A6700; }
  .pill.ok { background:#DAFBE1; color:var(--green); }
  .footer { color:var(--muted); font-size:11px; margin-top:18px; }
</style></head>
<body><div class="wrap">
  <h1>Morning IT Pulse</h1>
  <div class="sub">{{date}} · {{timezone}} · ServiceNow live data</div>

  <!-- KPI ROW: 4 tiles -->
  <div class="grid">
    <div class="kpi red"><div class="label">Open P1</div><div class="val">{{open_p1}}</div></div>
    <div class="kpi amber"><div class="label">Open P2</div><div class="val">{{open_p2}}</div></div>
    <div class="kpi red"><div class="label">SLA breached</div><div class="val">{{sla_breached}}</div></div>
    <div class="kpi"><div class="label">Pending approvals</div><div class="val">{{pending_approvals}}</div></div>
  </div>

  <div class="row">
    <div class="card"><h2>Top open P1/P2 incidents</h2>
      <table><thead><tr><th>#</th><th>Pri</th><th>Short description</th><th>Assigned to</th><th>Age</th></tr></thead>
      <tbody>{{rows_top_incidents}}</tbody></table>
    </div>
    <div class="card"><h2>Breached SLAs</h2>
      <table><thead><tr><th>Incident</th><th>SLA</th><th>Over by</th></tr></thead>
      <tbody>{{rows_breached_sla}}</tbody></table>
    </div>
  </div>

  <div class="row">
    <div class="card"><h2>Today's change calendar</h2>
      <table><thead><tr><th>CHG</th><th>Risk</th><th>Window</th><th>Owner</th></tr></thead>
      <tbody>{{rows_changes_today}}</tbody></table>
    </div>
    <div class="card"><h2>Workload heatmap</h2>
      <table><thead><tr><th>Assignment group</th><th>Open</th><th>P1</th><th>P2</th></tr></thead>
      <tbody>{{rows_workload}}</tbody></table>
    </div>
  </div>

  <div class="footer">Generated by Copilot Cowork · ServiceNow MCP · {{generated_at}}</div>
</div></body></html>
```

Use semantic colour cues: red KPI tile when value > 0 for P1 or breached SLAs; amber when P2 > 5;
plain otherwise. Do not introduce charts or images — text and tables only so the dashboard prints
cleanly and renders in any host.

## Recommended Actions Block

Above the HTML, output a short markdown section like:

```text
**Top actions for the next 2 hours**
- Page on-call for INC0010234 (P1, 34 min over SLA, no assignment).
- Escalate CHG0030019 — risk High, conflicts with INC0010189 in network segment.
- Re-assign 4 P2 incidents currently sitting unassigned in "Service Desk – EMEA".
```

Generate the actions from the same data; never repeat advice that the data does not support.

## Tone

Keep it short, factual, and unhyperbolic. This is an operational tool for a person who is about to
make decisions, not a marketing artifact. Avoid emoji. Avoid filler like "I hope this helps".
