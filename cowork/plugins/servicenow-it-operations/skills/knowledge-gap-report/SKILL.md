---
name: knowledge-gap-report
description: |
  Generates an HTML report identifying repeat ServiceNow incidents that are NOT yet covered by a
  knowledge base article, ranked by reduction opportunity. Use when the user asks for a "knowledge
  gap report", "self-service opportunity analysis", "deflection candidates", "shift-left report",
  or "where should we write KB articles next".
license: MIT
compatibility: Copilot Cowork Frontier with the ServiceNow MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: Knowledge Manager / Service Desk Lead}
cowork.category: IT Operations
cowork.icon: BookOpenFilled
---

# Knowledge Gap Report

## What This Skill Does

Builds a shift-left analysis: which clusters of repeat incidents currently have **no published KB
article** the agent could have used, and which would deliver the largest deflection if a KB were
written. Renders as a printable HTML report.

## When To Use

- "Run the knowledge gap report"
- "Where are our self-service opportunities?"
- "Which incidents should become KB articles?"
- "Build the shift-left analysis for last 30 days"

## Required Connector Tools

- `list_incidents` (last 30 days, paged)
- `search_knowledge` (per cluster keyword)
- `get_knowledge_article` (only when needed for verification)

## Default Workflow

1. Window: last 30 days unless the user specifies otherwise.
2. Pull active and recently-closed incidents.
3. Cluster incidents by short_description root (after stripping ticket numbers, hostnames, and
   stop-words). Treat any cluster with ≥ 5 incidents as a candidate.
4. For each candidate cluster, run `search_knowledge` with the cluster keywords. If zero published
   articles match, mark the cluster as a **gap**.
5. For each gap, score = `incident_count × avg_resolution_minutes / 60`. Higher is more valuable.
6. Render HTML report with the structure below. Top 10 gaps as cards, full table below.

## HTML Output Template

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Knowledge Gap Report — {{date}}</title>
<style>
  body { font-family:-apple-system,"Segoe UI",system-ui,sans-serif; color:#1F2328; margin:0; background:#F6F8FA; }
  .wrap { max-width:1100px; margin:0 auto; padding:24px; }
  h1 { margin:0 0 4px; font-size:22px; }
  .sub { color:#656D76; font-size:13px; margin-bottom:18px; }
  .gap-grid { display:grid; grid-template-columns:repeat(2,1fr); gap:12px; margin-bottom:20px; }
  .gap { background:white; border:1px solid #D0D7DE; border-left:4px solid #62D84E; border-radius:10px; padding:14px 16px; }
  .gap h3 { margin:0 0 6px; font-size:15px; }
  .gap .meta { color:#656D76; font-size:12px; margin-bottom:8px; }
  .gap .why { font-size:13px; }
  table { width:100%; border-collapse:collapse; font-size:13px; background:white; border:1px solid #D0D7DE; border-radius:10px; overflow:hidden; }
  th, td { text-align:left; padding:8px 10px; border-bottom:1px solid #D0D7DE; }
  th { background:#F6F8FA; color:#656D76; font-weight:500; }
  .score { font-weight:600; }
</style></head>
<body><div class="wrap">
  <h1>Knowledge Gap Report</h1>
  <div class="sub">{{from}} → {{to}} · {{total_incidents}} incidents reviewed · {{cluster_count}} clusters · {{gap_count}} gaps</div>

  <h2 style="font-size:14px;text-transform:uppercase;color:#656D76;letter-spacing:.04em;">Top deflection opportunities</h2>
  <div class="gap-grid">
    {{cards_top_gaps}}
  </div>

  <h2 style="font-size:14px;text-transform:uppercase;color:#656D76;letter-spacing:.04em;">All gaps</h2>
  <table><thead><tr>
    <th>Cluster</th><th>Incidents</th><th>Avg resolve (min)</th><th>Top assignment group</th><th class="score">Score</th>
  </tr></thead><tbody>{{rows_all_gaps}}</tbody></table>
</div></body></html>
```

Each card uses this snippet for `cards_top_gaps`:

```html
<div class="gap">
  <h3>{{cluster_title}}</h3>
  <div class="meta">{{incident_count}} incidents · avg {{avg_resolve_min}} min · top group {{top_group}}</div>
  <div class="why">Sample incidents: {{sample_inc_numbers}}. Suggested KB title: <em>{{suggested_kb_title}}</em>.</div>
</div>
```

## Analysis Rules

- A cluster qualifies only with ≥ 5 incidents in the window.
- "No KB" means `search_knowledge` returned zero published articles whose title or topic overlaps
  with the cluster keywords.
- Suggested KB title must be a how-to phrase ("How to reset…", "Resolve … on Windows 11"), not a
  rephrasing of the incident text.
- Never include incident numbers or sensitive descriptions verbatim where free-text PII could
  appear; quote only the cluster keywords.

## Tone

Analytical, knowledge-management voice. Frame outputs as opportunities, not failings.
