---
name: account-deep-dive-brief
description: |
  Creates a PowerPoint executive brief for a single named account combining Salesforce CRM data
  (opportunities, contacts, cases, recent activity) with Microsoft 365 WorkIQ context
  (recent meetings, emails, Loop pages) — designed for an AE walking into a major customer
  meeting or for an executive sponsor briefing. Use when the user asks for an "account brief",
  "account deep dive", "exec brief on {account}", "customer 360 deck", or "prep me for {account}".
license: MIT
compatibility: Copilot Cowork Frontier with the Salesforce MCP connector. Uses built-in WorkIQ context where available.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: AE / Account Director / Exec Sponsor}
cowork.category: Sales
cowork.icon: BuildingMultipleFilled
---

# Account Deep-Dive Brief

## What This Skill Does

Produces a PowerPoint executive brief on a single named account: relationship history, decision
team, open and won opportunities, support case posture, recent activity from Salesforce and
WorkIQ, and a recommended meeting agenda. Designed for an AE preparing for a customer visit or an
executive sponsor walking into a sponsor call.

## When To Use

- "Build me an account brief on {account}"
- "Prep me for my meeting with {account}"
- "Customer 360 deck for {account}"
- "Exec brief on {account}"

Do not use for the morning daily briefing (`morning-pipeline-briefing-dashboard`) or the weekly
review (`weekly-pipeline-review-deck`).

## Required Connector Tools

- `list_accounts` (resolve the account if name is fuzzy)
- `get_account_360` — primary
- `list_opportunities` — open + closed for this account
- `list_contacts` — decision team
- `list_cases` — support / compliance cases
- `get_activity_timeline`
- `list_campaigns` — campaigns the account is in
- `list_leads` — leads tied to the account
- `get_pipeline_dashboard` — only for context if the AE owns multiple

## Optional WorkIQ Context

When available:
- Last 30 days of meetings whose attendees include any account contact.
- Last 30 days of emails to/from any account contact (paraphrased themes only, never verbatim).
- Loop pages or shared documents referenced in those meetings.

Use WorkIQ to surface relationship signals ("the CTO has been on every meeting since March",
"replies have shifted from buyer to procurement") and as input for the recommended agenda.

## Default Workflow

1. Resolve the account name with `list_accounts`. If multiple match, ask the user which.
2. Pull `get_account_360`, `list_opportunities`, `list_contacts`, `list_cases`,
   `get_activity_timeline`.
3. Pull WorkIQ relationship signal if available.
4. Synthesise:
   - Relationship summary (years as customer, current ARR if available, exec sponsor).
   - Decision team with role and engagement level.
   - Open opps (priority list with stage, amount, close, next step).
   - Won/lost history in last 12 months.
   - Support case posture: open, recently closed, severity mix.
   - Themes from recent activity and WorkIQ.
5. Build the deck.

## Slide Map

| # | Title | Visual | Notes |
|---|---|---|---|
| 1 | {{account_name}} — Account Brief | Cover with logo placeholder, ARR / industry / region / sponsor | |
| 2 | Relationship Summary | Timeline of major events (won deals, exec changes, escalations) | |
| 3 | Decision Team | Table: name, role, engagement, last touch | |
| 4 | Pipeline & Opportunities | Pipeline waterfall + table of open opps | |
| 5 | Recent Activity | Combined Salesforce + WorkIQ activity, themed | |
| 6 | Support & Cases | Open cases, severity, themes | |
| 7 | Strategic Themes | 3–5 themes Cowork has identified across data | |
| 8 | Risks & Open Questions | Items the team needs answers to | |
| 9 | Recommended Agenda | Suggested agenda for the upcoming meeting | |
| 10 | Next 30 Days | Owner, action, due | |

## Analysis Rules

- Engagement level for a contact = derived from activity counts in last 90 days:
  high (≥6), medium (3–5), low (1–2), cold (0). State the basis on slide 3.
- Themes must be supported by ≥2 evidence items. Cite the source ("from 4 meetings in March",
  "from 2 cases on rate-limit topic").
- Never paraphrase a single private email such that the wording is recoverable. Use thematic
  language only.
- If WorkIQ context is unavailable, mark slide 5 as "Salesforce activity only" in the footer.

## Tone

Executive briefing. Specific, evidence-backed, neutral. Don't oversell internal optimism.
