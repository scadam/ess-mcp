---
name: backlog-grooming-report
description: |
  Builds an HTML backlog-grooming report: stale issues, unestimated items, items missing
  acceptance criteria, oldest items, items with vague titles, and a recommended grooming
  shortlist for the next refinement session. Use when the user asks for a "backlog grooming
  report", "refinement prep", "backlog hygiene report", "grooming dashboard", or "backlog
  health check".
license: MIT
compatibility: Copilot Cowork Frontier with the Jira MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: Product Owner / Scrum Master}
cowork.category: Engineering
cowork.icon: ClipboardTaskListLtrFilled
---

# Backlog Grooming Report

## What This Skill Does

Produces an HTML backlog-hygiene report for a product owner or scrum master to take into the next
refinement session. Highlights stale items, unestimated items, items missing acceptance criteria,
oldest items, and items with vague titles. Recommends a shortlist of 10–15 items to groom next.

## When To Use

- "Run the backlog grooming report"
- "Refinement prep for the next session"
- "Backlog hygiene check"

Do not use for sprint review (`sprint-health-deck`) or release prep (`release-readiness-pack`).

## Required Connector Tools

- `get_backlog`
- `list_issues` (filtered to the backlog)
- `list_epics`
- `list_versions`
- `list_projects`

## Default Workflow

1. Resolve the project / board.
2. Pull the backlog, all in-scope epics and versions.
3. For each item, compute hygiene flags:
   - **stale** = no update in 60 days
   - **unestimated** = no story points / time estimate
   - **no-acceptance** = empty description OR no AC heading detected
   - **vague-title** = title shorter than 5 words OR contains "fix bug", "TBD", "misc"
   - **no-epic** = not linked to an epic
4. Score each item: `flags_count + age_weight`. Higher = needs grooming sooner.
5. Build the report.

## HTML Output Template

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Backlog Grooming Report — {{project}} — {{date}}</title>
<style>
  :root { --blue:#0052CC; --green:#2DA44E; --amber:#D29922; --red:#CF222E; --ink:#1F2328; --muted:#656D76; --line:#D0D7DE; --bg:#F4F8FB; }
  body { font-family:-apple-system,"Segoe UI",system-ui,sans-serif; color:var(--ink); margin:0; background:var(--bg); }
  .wrap { max-width:1180px; margin:0 auto; padding:24px; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:var(--muted); margin-bottom:18px; font-size:13px; }
  .grid { display:grid; grid-template-columns:repeat(5,1fr); gap:12px; margin-bottom:18px; }
  .kpi { background:white; border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  .kpi .label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  .kpi .val { font-size:24px; font-weight:600; margin-top:4px; }
  .kpi.amber .val { color:var(--amber); }
  .kpi.red .val { color:var(--red); }
  .card { background:white; border:1px solid var(--line); border-radius:12px; padding:14px 16px; margin-bottom:14px; }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.04em; margin:0 0 10px; color:var(--muted); }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-weight:500; }
  .flag { display:inline-block; padding:2px 6px; border-radius:6px; font-size:10px; font-weight:600; margin-right:4px; background:#FFF1CF; color:#9A6700; }
  .footer { color:var(--muted); font-size:11px; margin-top:18px; }
</style></head>
<body><div class="wrap">
  <h1>Backlog Grooming Report — {{project}}</h1>
  <div class="sub">{{date}} · {{total_items}} backlog items · {{healthy_pct}}% healthy</div>

  <div class="grid">
    <div class="kpi"><div class="label">Total</div><div class="val">{{total_items}}</div></div>
    <div class="kpi amber"><div class="label">Stale (60d+)</div><div class="val">{{stale_count}}</div></div>
    <div class="kpi amber"><div class="label">Unestimated</div><div class="val">{{unestimated_count}}</div></div>
    <div class="kpi amber"><div class="label">Missing AC</div><div class="val">{{no_ac_count}}</div></div>
    <div class="kpi red"><div class="label">No epic</div><div class="val">{{no_epic_count}}</div></div>
  </div>

  <div class="card"><h2>Recommended grooming shortlist</h2>
    <table><thead><tr><th>Issue</th><th>Title</th><th>Age</th><th>Flags</th><th>Suggested action</th></tr></thead>
    <tbody>{{rows_shortlist}}</tbody></table>
  </div>

  <div class="card"><h2>Stale items (60+ days, top 20)</h2>
    <table><thead><tr><th>Issue</th><th>Title</th><th>Last update</th><th>Owner</th></tr></thead>
    <tbody>{{rows_stale}}</tbody></table>
  </div>

  <div class="card"><h2>Unestimated by epic</h2>
    <table><thead><tr><th>Epic</th><th>Unestimated</th><th>Total</th></tr></thead>
    <tbody>{{rows_unestimated_by_epic}}</tbody></table>
  </div>

  <div class="footer">Generated by Copilot Cowork · Jira MCP · {{generated_at}}</div>
</div></body></html>
```

## Suggested Action Vocabulary

For the "Suggested action" column on the shortlist, use exactly one of:
- **Estimate** — needs sizing
- **Add AC** — write acceptance criteria
- **Reword** — rename a vague title
- **Link to epic**
- **Close as obsolete**
- **Decompose** — too large, split it

## Tone

Practical, not preachy. The report is a checklist for refinement, not a critique of the team.
