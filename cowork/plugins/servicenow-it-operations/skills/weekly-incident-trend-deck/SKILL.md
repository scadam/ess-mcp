---
name: weekly-incident-trend-deck
description: |
  Creates a weekly IT leadership PowerPoint deck reviewing incident volume, MTTR, SLA compliance,
  category mix, change failure rate and top contributing assignment groups using ServiceNow data.
  Use when the user asks for a "weekly incident review", "IT ops weekly", "service management
  steering pack", "incident trend deck", or "PowerPoint for the IT leadership weekly".
license: MIT
compatibility: Copilot Cowork Frontier with the ServiceNow MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: IT Director / Head of Service Management}
cowork.category: IT Operations
cowork.icon: SlidesFilled
---

# Weekly Incident Trend Deck

## What This Skill Does

Produces a 9-slide PowerPoint pack for the weekly IT service management review. The deck compares
the last 7 days against the previous 7 days, calls out trend reversals, and ends with prioritised
actions for the IT leadership team.

## When To Use

Trigger this skill when the user asks for any of:

- "Build the weekly IT operations deck"
- "Create the incident trend PowerPoint"
- "Pack for the IT steering call"
- "Make the service management weekly"

Do not use for a daily snapshot (use `morning-it-pulse-dashboard`) or for change-only reviews
(use `change-advisory-board-pack`).

## Required Connector Tools

- `list_incidents` (with state and priority filters, paged)
- `get_sla_status`
- `list_problems`
- `list_change_requests` (state filters: implemented, failed, scheduled)
- `get_team_incidents`
- `search_knowledge` (to identify articles created this week)

If none are available, stop and report the connector binding issue. Do not invent figures.

## Default Workflow

1. Set the **review window**: last 7 days vs previous 7 days, in UTC unless the user specifies a
   timezone. State the window explicitly on slide 1.

2. Pull the data:
   - All active and recently closed incidents in the window.
   - SLA breach counts and percentages.
   - Open and recently-resolved problems.
   - Implemented and failed changes in the window.
   - Top assignment groups by inbound volume and by MTTR.
   - New KB articles created in the window.

3. Compute, per priority:
   - Inbound count, resolved count, mean time to resolve (MTTR), SLA breach rate.
   - Delta vs previous 7-day window, with up/down arrow indicator.

4. Identify **storylines** the deck must address:
   - Any priority where MTTR worsened by >15% week-over-week.
   - Any assignment group accounting for >25% of all P1/P2.
   - Any change failure rate above 5%.
   - Any repeat incident category (≥3 incidents on the same short_description root).

5. Generate the deck following the slide map below. If Cowork can create the PowerPoint directly,
   do so. Otherwise output a slide-by-slide markdown plan with title, bullets, suggested visual,
   speaker notes, and source tools.

## Slide Map

| # | Title | Visual | Source tools |
|---|---|---|---|
| 1 | IT Operations — Week of {{week}} | Title with summary KPI strip (P1, P2, MTTR, breach %) | All |
| 2 | Volume & Trend | Bar chart: inbound vs resolved by priority, week-over-week | `list_incidents`, `get_sla_status` |
| 3 | SLA Compliance | Stacked bar: breached / at-risk / met by priority | `get_sla_status` |
| 4 | MTTR by Priority | Bar chart with WoW delta arrows | `list_incidents` |
| 5 | Top Assignment Groups | Horizontal bar: open volume + MTTR | `get_team_incidents` |
| 6 | Repeat / Problem-driven Incidents | Table linking incident clusters to open problems | `list_problems`, `list_incidents` |
| 7 | Change Performance | Implemented vs failed; failed-change post-mortems | `list_change_requests` |
| 8 | Knowledge Coverage | New KB articles vs incidents that should have triggered new KB | `search_knowledge` |
| 9 | Actions for IT Leadership | Owner, action, due date, success measure | All |

For each slide produce: title, 3–5 bullets, suggested visual, speaker notes (one short paragraph
written for the IT director), and the list of source tools used.

## Analysis Rules

- A trend is "material" only if it moves >10% week-over-week AND the absolute count is non-trivial
  (P1 ≥ 1, P2 ≥ 5, others ≥ 10).
- Always pair an MTTR claim with the count it is averaged over.
- Never average across priorities for the headline MTTR figure.
- A change failure rate above 5% is automatically a leadership-level item.
- "Repeat incident" means three or more incidents in the window with substantially similar short
  descriptions or the same configuration_item.

## Tone

Service-management professional. Past-tense for what happened, present-tense for what's true now,
imperative for actions. No hedging.
