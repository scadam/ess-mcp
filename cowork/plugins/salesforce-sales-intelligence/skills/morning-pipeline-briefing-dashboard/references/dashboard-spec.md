# Morning Pipeline Briefing — Dashboard Spec

Loaded on demand by `SKILL.md`. Contains the exact HTML skeleton and the chart computation rules.
Keep the SKILL.md slim; put any rendering detail here.

## HTML Output Template

Use this skeleton verbatim. Substitute every `{{token}}` with a computed value. Do not strip
classes or change the chart structure — SVG dimensions and viewBoxes are tuned for the layout.

```html
<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Morning Pipeline Briefing — {{date}}</title>
<style>
  :root {
    --blue:#00A1E0; --blue-d:#0277A8; --green:#2DA44E; --amber:#D29922; --red:#CF222E;
    --ink:#1F2328; --muted:#656D76; --line:#D0D7DE; --bg:#F4F8FB; --soft:#EAF4FA;
  }
  body { font-family:-apple-system,"Segoe UI",system-ui,sans-serif; color:var(--ink); margin:0; background:var(--bg); }
  .wrap { max-width:1200px; margin:0 auto; padding:24px; }
  h1 { font-size:22px; margin:0 0 4px; }
  .sub { color:var(--muted); margin-bottom:18px; font-size:13px; }
  .kpi-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:14px; }
  .kpi { background:white; border:1px solid var(--line); border-radius:12px; padding:14px 16px; position:relative; }
  .kpi .label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em; }
  .kpi .val { font-size:26px; font-weight:600; margin-top:4px; }
  .kpi .delta { position:absolute; top:14px; right:16px; font-size:11px; font-weight:600; padding:2px 6px; border-radius:6px; }
  .delta.up { background:#DAFBE1; color:var(--green); }
  .delta.down { background:#FFEBE9; color:var(--red); }
  .delta.flat { background:#F0F3F6; color:var(--muted); }
  .kpi.green .val { color:var(--green); }
  .row { display:grid; gap:12px; margin-bottom:14px; }
  .row.r-2 { grid-template-columns:1.4fr 1fr; }
  .row.r-2b { grid-template-columns:1fr 1fr; }
  .card { background:white; border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
  .card h2 { font-size:13px; text-transform:uppercase; letter-spacing:.04em; margin:0 0 10px; color:var(--muted); }
  .card .sub2 { color:var(--muted); font-size:11px; margin-top:-4px; margin-bottom:8px; }
  .funnel { display:flex; flex-direction:column; gap:6px; }
  .funnel .lane { display:grid; grid-template-columns:120px 1fr 90px; align-items:center; gap:8px; font-size:12px; }
  .funnel .lane .name { color:var(--ink); font-weight:500; }
  .funnel .lane .bar { height:22px; background:var(--soft); border-radius:6px; position:relative; overflow:hidden; }
  .funnel .lane .bar > span { display:block; height:100%; background:linear-gradient(90deg,var(--blue),var(--blue-d)); border-radius:6px; }
  .funnel .lane .bar .count { position:absolute; right:8px; top:50%; transform:translateY(-50%); font-size:11px; color:white; font-weight:600; }
  .funnel .lane .val { text-align:right; color:var(--muted); font-variant-numeric:tabular-nums; }
  .donut { display:flex; align-items:center; gap:14px; }
  .donut svg { width:160px; height:160px; flex:0 0 160px; }
  .donut .legend { font-size:12px; }
  .donut .legend .li { display:flex; align-items:center; gap:6px; margin:4px 0; }
  .donut .legend .sw { width:10px; height:10px; border-radius:2px; }
  .donut .center { fill:var(--ink); font-size:14px; font-weight:600; }
  .donut .center-sub { fill:var(--muted); font-size:10px; }
  .gauge { display:flex; flex-direction:column; align-items:center; }
  .gauge svg { width:170px; height:100px; }
  .gauge .label { font-size:11px; color:var(--muted); margin-top:-6px; }
  .gauge .value { font-size:22px; font-weight:600; }
  .sparks { display:grid; grid-template-columns:1fr 1fr 1fr; gap:10px; }
  .spark { border:1px solid var(--line); border-radius:10px; padding:8px 10px; background:white; }
  .spark .t { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
  .spark .v { font-size:18px; font-weight:600; margin:2px 0 4px; }
  .spark svg { width:100%; height:38px; display:block; }
  .treemap { display:flex; gap:4px; height:120px; border-radius:8px; overflow:hidden; }
  .treemap .tile { color:white; padding:8px 10px; display:flex; flex-direction:column; justify-content:flex-end; font-size:12px; min-width:0; }
  .treemap .tile .n { font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .treemap .tile .a { font-size:11px; opacity:.85; }
  .heat { display:grid; grid-template-columns:140px repeat(7,1fr); gap:4px; font-size:11px; }
  .heat .h { color:var(--muted); padding:4px; }
  .heat .lbl { padding:6px 4px; color:var(--ink); }
  .heat .cell { border-radius:4px; height:26px; display:flex; align-items:center; justify-content:center; color:#1F2328; font-weight:600; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:left; padding:6px 8px; border-bottom:1px solid var(--line); vertical-align:middle; }
  th { color:var(--muted); font-weight:500; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  .heatbar { height:6px; border-radius:3px; background:#F0F3F6; overflow:hidden; min-width:60px; }
  .heatbar > span { display:block; height:100%; }
  .heatbar.hot > span { background:var(--red); }
  .heatbar.warm > span { background:var(--amber); }
  .heatbar.ok > span { background:var(--green); }
  .pill { display:inline-block; padding:2px 8px; border-radius:999px; font-size:11px; font-weight:600; }
  .pill.hot { background:#FFEBE9; color:var(--red); }
  .pill.warm { background:#FFF1CF; color:#9A6700; }
  .pill.ok { background:#DAFBE1; color:var(--green); }
  .plan ol { margin:8px 0 0 20px; padding:0; }
  .plan li { padding:4px 0; }
  .spotlight { border-left:4px solid var(--blue); }
  .footer { color:var(--muted); font-size:11px; margin-top:18px; }
</style></head>
<body><div class="wrap">
  <h1>Morning Pipeline Briefing</h1>
  <div class="sub">{{date}} · {{user_name}} · pipeline coverage {{coverage_ratio}}× · WorkIQ context {{workiq_state}}</div>

  <div class="kpi-grid">
    <div class="kpi"><div class="label">Open pipeline</div><div class="val">{{open_pipeline_value}}</div><span class="delta {{open_pipeline_delta_dir}}">{{open_pipeline_delta}}</span></div>
    <div class="kpi green"><div class="label">Commit</div><div class="val">{{commit_value}}</div><span class="delta {{commit_delta_dir}}">{{commit_delta}}</span></div>
    <div class="kpi"><div class="label">Best case</div><div class="val">{{best_case_value}}</div><span class="delta {{best_case_delta_dir}}">{{best_case_delta}}</span></div>
    <div class="kpi"><div class="label">Closed-won period</div><div class="val">{{closed_won_value}}</div><span class="delta {{closed_won_delta_dir}}">{{closed_won_delta}}</span></div>
  </div>

  <div class="row r-2">
    <div class="card">
      <h2>Pipeline by stage</h2>
      <div class="sub2">Bar width = stage value as % of largest stage. Count shown inside.</div>
      <div class="funnel">{{rows_funnel}}</div>
    </div>
    <div class="card">
      <h2>Forecast vs quota</h2>
      <div class="sub2">Closed + Commit + Best case stacked against quota for the period.</div>
      <div class="donut">
        <svg viewBox="0 0 42 42" role="img" aria-label="forecast donut">
          <circle cx="21" cy="21" r="15.9155" fill="none" stroke="#EAF0F5" stroke-width="5"/>
          <circle cx="21" cy="21" r="15.9155" fill="none" stroke="#2DA44E" stroke-width="5" stroke-dasharray="{{donut_closed_pct}} 100" stroke-dashoffset="25"/>
          <circle cx="21" cy="21" r="15.9155" fill="none" stroke="#00A1E0" stroke-width="5" stroke-dasharray="{{donut_commit_pct}} 100" stroke-dashoffset="{{donut_commit_offset}}"/>
          <circle cx="21" cy="21" r="15.9155" fill="none" stroke="#D29922" stroke-width="5" stroke-dasharray="{{donut_best_pct}} 100" stroke-dashoffset="{{donut_best_offset}}"/>
          <text x="21" y="21" text-anchor="middle" class="center">{{donut_attain_pct}}%</text>
          <text x="21" y="26" text-anchor="middle" class="center-sub">of quota</text>
        </svg>
        <div class="legend">
          <div class="li"><span class="sw" style="background:#2DA44E"></span> Closed {{closed_won_value}}</div>
          <div class="li"><span class="sw" style="background:#00A1E0"></span> Commit {{commit_value}}</div>
          <div class="li"><span class="sw" style="background:#D29922"></span> Best case {{best_case_value}}</div>
          <div class="li"><span class="sw" style="background:#EAF0F5"></span> Gap to quota {{gap_to_quota_value}}</div>
        </div>
      </div>
    </div>
  </div>

  <div class="row r-2">
    <div class="card" style="display:flex; flex-direction:column; align-items:center; justify-content:center;">
      <h2 style="align-self:flex-start">Coverage</h2>
      <div class="gauge">
        <svg viewBox="0 0 170 100" role="img" aria-label="coverage gauge">
          <path d="M15 90 A 70 70 0 0 1 155 90" stroke="#EAF0F5" stroke-width="14" fill="none" stroke-linecap="round"/>
          <path d="M15 90 A 70 70 0 0 1 155 90" stroke="{{coverage_color}}" stroke-width="14" fill="none" stroke-linecap="round" stroke-dasharray="{{coverage_arc_len}} 999"/>
          <line x1="85" y1="90" x2="{{coverage_needle_x}}" y2="{{coverage_needle_y}}" stroke="#1F2328" stroke-width="2" stroke-linecap="round"/>
          <circle cx="85" cy="90" r="4" fill="#1F2328"/>
        </svg>
        <div class="value">{{coverage_ratio}}×</div>
        <div class="label">Target ≥ 3.0× · quarter remaining {{quota_remaining_value}}</div>
      </div>
    </div>
    <div class="card">
      <h2>30-day activity</h2>
      <div class="sub2">Daily counts across your open opportunities. {{activity_source}}</div>
      <div class="sparks">
        <div class="spark"><div class="t">Meetings</div><div class="v">{{meetings_30d_total}}</div>
          <svg viewBox="0 0 100 38" preserveAspectRatio="none"><polyline fill="rgba(0,161,224,.12)" stroke="#00A1E0" stroke-width="1.5" points="{{spark_meetings_points}}"/></svg></div>
        <div class="spark"><div class="t">Emails</div><div class="v">{{emails_30d_total}}</div>
          <svg viewBox="0 0 100 38" preserveAspectRatio="none"><polyline fill="rgba(45,164,78,.12)" stroke="#2DA44E" stroke-width="1.5" points="{{spark_emails_points}}"/></svg></div>
        <div class="spark"><div class="t">Calls</div><div class="v">{{calls_30d_total}}</div>
          <svg viewBox="0 0 100 38" preserveAspectRatio="none"><polyline fill="rgba(210,153,34,.12)" stroke="#D29922" stroke-width="1.5" points="{{spark_calls_points}}"/></svg></div>
      </div>
    </div>
  </div>

  <div class="card spotlight" style="margin-bottom:14px;">
    <h2>Spotlight account · {{spotlight_account_name}}</h2>
    <div style="font-size:13px;">{{spotlight_summary}}</div>
    <div style="font-size:12px;color:var(--muted);margin-top:6px;">Why today: {{spotlight_reason}}</div>
  </div>

  <div class="card plan" style="margin-bottom:14px;">
    <h2>Activity plan for today</h2>
    <ol>{{rows_activity_plan}}</ol>
  </div>

  <div class="row r-2b">
    <div class="card">
      <h2>Top accounts by open value</h2>
      <div class="sub2">Tile width is proportional to the account's share of your top-5 open value.</div>
      <div class="treemap">{{rows_treemap}}</div>
    </div>
    <div class="card">
      <h2>Stage-age heatmap</h2>
      <div class="sub2">Each cell is one of your open opps; colour = actual age ÷ expected age in stage.</div>
      <div class="heat">
        <div class="h"></div><div class="h">1</div><div class="h">2</div><div class="h">3</div><div class="h">4</div><div class="h">5</div><div class="h">6</div><div class="h">7</div>
        {{rows_heatmap}}
      </div>
    </div>
  </div>

  <div class="row r-2">
    <div class="card"><h2>Top open opportunities</h2>
      <table><thead><tr><th>Opp</th><th>Account</th><th>Stage</th><th class="num">Amount</th><th>Close</th><th>Heat</th></tr></thead>
      <tbody>{{rows_top_opps}}</tbody></table>
    </div>
    <div class="card"><h2>Today's tasks &amp; meetings</h2>
      <table><thead><tr><th>Time</th><th>What</th><th>Account / Contact</th></tr></thead>
      <tbody>{{rows_today}}</tbody></table>
    </div>
  </div>

  <div class="row r-2">
    <div class="card"><h2>Slipping deals</h2>
      <table><thead><tr><th>Opp</th><th>Account</th><th>Stage age</th><th>Slip</th><th>Last activity</th></tr></thead>
      <tbody>{{rows_slipping}}</tbody></table>
    </div>
    <div class="card"><h2>Fresh leads</h2>
      <table><thead><tr><th>Lead</th><th>Source</th><th class="num">Score</th></tr></thead>
      <tbody>{{rows_leads}}</tbody></table>
    </div>
  </div>

  <div class="footer">Generated by Copilot Cowork · Salesforce MCP{{workiq_footer}} · {{generated_at}}</div>
</div></body></html>
```

## Chart Computation Rules

All charts come from data already gathered. Never invent series. If a series is empty, render the
card with the text "No data" centred and skip the SVG — never emit a chart with placeholder data.

### KPI delta chips

Compare each KPI against the same metric 7 days ago. Emit `{{*_delta}}` (e.g. `+8%`, `-3%`,
`flat`) and `{{*_delta_dir}}` class `up` (good direction), `down`, or `flat` (|Δ| < 1%).

### Pipeline funnel rows

For each entry of `funnel[]` (stage order: Prospect → Qualify → Discover → Propose → Negotiate →
Closed-Won) emit:

```html
<div class="lane">
  <div class="name">Negotiate</div>
  <div class="bar"><span style="width:{{pct_of_max}}%"></span><span class="count">{{count}} opps</span></div>
  <div class="val">{{value_short}}</div>
</div>
```

`pct_of_max = round(stage.value / max(funnel[*].value) * 100)`. Format `value_short` as `$1.2M`
/ `$840K`.

### Forecast donut

Given `closed`, `commit`, `best_case`, `quota` (same currency):

- `total = max(quota, closed + commit + best_case)`
- `donut_closed_pct = round(closed / total * 100, 1)`
- `donut_commit_pct = round(commit / total * 100, 1)`
- `donut_best_pct   = round(best_case / total * 100, 1)`
- `donut_commit_offset = (25 - donut_closed_pct) mod 100`
- `donut_best_offset   = (25 - donut_closed_pct - donut_commit_pct) mod 100`
  (negative → add 100)
- `donut_attain_pct = round((closed + commit) / quota * 100)` — centre label.
- `gap_to_quota_value = format_money(max(0, quota - closed - commit - best_case))`.

### Coverage gauge

- `coverage_ratio = round(open_pipeline / remaining_quota, 1)`.
- `arc_full = 220` (half-circle path length at r=70).
- `coverage_arc_len = round(min(coverage_ratio, 5) / 5 * arc_full, 1)`.
- Needle: `theta = π · (1 - min(coverage_ratio,5)/5)`,
  `coverage_needle_x = round(85 + 60·cos(theta), 1)`,
  `coverage_needle_y = round(90 - 60·sin(theta), 1)`.
- `coverage_color`: `<2.0` → `#CF222E`, `2.0–2.9` → `#D29922`, `≥3.0` → `#2DA44E`.

### Sparklines

For each of `activity_30d.meetings`, `.emails`, `.calls` (30 daily ints, oldest → newest):

- Pad with `0` to length 30. `max_y = max(series) || 1`.
- For `i` in 0..29: `x = round(i * 100/29, 2)`, `y = round(38 - series[i]/max_y * 34, 2)`.
- Emit as `"x1,y1 x2,y2 …"` into `{{spark_*_points}}`. `{{*_30d_total}} = sum(series)`.

### Top accounts treemap

For each of the top 5 accounts (by open value desc):

- `share_x100 = round(account.open_value / sum(top5.open_value) * 100, 2)`.
- Tile colour rotates through: `#0277A8`, `#00A1E0`, `#2DA44E`, `#D29922`, `#6F42C1`.

```html
<div class="tile" style="flex:{{share_x100}} 1 0; background:{{tile_color}}" title="{{account_name}} — {{account_value}}">
  <div class="n">{{account_name}}</div><div class="a">{{account_value_short}}</div>
</div>
```

### Stage-age heatmap

Up to 7 open opps per stage (one row). For each opp `ratio = actual_age / expected_age`
(clip 0..3). Background:

- `≤ 0.8` → `#DAFBE1`
- `0.8–1.2` → `#FFF4D6`
- `1.2–1.8` → `#FFE2B8`
- `> 1.8` → `#FFC9C2`

Cell text = `{actual_age}d`. Row label = stage. Empty trailing cells:
`<div class="cell" style="background:#F5F8FA"></div>`.

```html
<div class="lbl">Negotiate</div>
<div class="cell" style="background:#FFC9C2" title="Acme · 24d (expected 12d)">24d</div>
```

### Slipping deals heat bar

For each `slipping[]` row emit:

```html
<td><div class="heatbar {{slip_class}}"><span style="width:{{slip_pct}}%"></span></div></td>
```

`slip_pct = round(min(slip_ratio, 2.0) / 2.0 * 100)`; `slip_class` = `hot` (≥1.8),
`warm` (1.5–1.8), `ok` (<1.5). Sort by `slip_ratio` desc.

### Activity source disclosure

- Salesforce + WorkIQ → `{{activity_source}} = "Activity from Salesforce + WorkIQ."`
- Salesforce only → `"Activity from Salesforce only."`
- Neither → drop the sparkline card entirely; never fabricate a flat line.
