---
name: team-workload-card
description: |
  Builds an Adaptive Card snapshot of an IT team's workload — open incidents per assignee,
  pending approvals, and SLA risk — designed to be posted into a Microsoft Teams channel as a
  daily or shift-handover update. Use when the user asks for a "workload card", "shift handover",
  "team status card", or "post a team snapshot to Teams".
license: MIT
compatibility: Copilot Cowork Frontier with the ServiceNow MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: Service Desk / IT Ops Team Lead}
cowork.category: IT Operations
cowork.icon: PeopleTeamFilled
---

# Team Workload Card

## What This Skill Does

Produces a single **Adaptive Card 1.5** JSON payload summarising the live workload of an IT team
(by default the user's assignment group). Suitable for posting into a Teams channel at the start of
each shift or each day. The card includes per-assignee counts, breached / at-risk SLA totals,
pending approvals, and a "next 3 hours" focus list.

## When To Use

- "Post the team workload card"
- "Adaptive card for shift handover"
- "Snapshot the EMEA service desk for Teams"
- "Build the team status card I can drop in chat"

Do not use this for a full HTML dashboard (use `morning-it-pulse-dashboard`) or for executive
review (use `weekly-incident-trend-deck`).

## Required Connector Tools

- `get_team_incidents` (with optional `assignment_group` argument)
- `get_team_approvals`
- `get_sla_status`

If none of these are available, stop and report the connector binding issue.

## Default Workflow

1. Resolve the assignment group: the user's stated team if provided, otherwise call
   `get_team_incidents()` without filter and use the group with the highest open volume.

2. Pull workload, approvals, SLA in parallel.

3. Compute:
   - Open incidents per assignee (top 8 by volume).
   - Total open by priority.
   - SLA: breached count, at-risk count.
   - Pending approvals queue depth and age buckets.

4. Build the Adaptive Card payload using the template below. Output the **raw JSON** in a fenced
   code block labelled `json` so the user can paste it into a Teams workflow / Power Automate /
   Copilot Studio adaptive-card sender.

5. Above the card, include a one-line summary suitable for the Teams notification preview, e.g.:
   *"EMEA Service Desk: 3 P1 open, 2 SLAs breached, 14 incidents across 6 engineers."*

## Adaptive Card Template

```json
{
  "type": "AdaptiveCard",
  "$schema": "https://adaptivecards.io/schemas/adaptive-card.json",
  "version": "1.5",
  "body": [
    {
      "type": "TextBlock",
      "text": "{{group_name}} — Workload Snapshot",
      "weight": "Bolder",
      "size": "Large",
      "wrap": true
    },
    {
      "type": "TextBlock",
      "text": "{{date}} · live from ServiceNow",
      "isSubtle": true,
      "spacing": "None",
      "wrap": true
    },
    {
      "type": "ColumnSet",
      "spacing": "Medium",
      "columns": [
        { "type": "Column", "width": "stretch", "items": [
          { "type": "TextBlock", "text": "Open P1", "isSubtle": true, "size": "Small" },
          { "type": "TextBlock", "text": "{{open_p1}}", "size": "ExtraLarge", "weight": "Bolder", "color": "Attention" }
        ]},
        { "type": "Column", "width": "stretch", "items": [
          { "type": "TextBlock", "text": "Open P2", "isSubtle": true, "size": "Small" },
          { "type": "TextBlock", "text": "{{open_p2}}", "size": "ExtraLarge", "weight": "Bolder", "color": "Warning" }
        ]},
        { "type": "Column", "width": "stretch", "items": [
          { "type": "TextBlock", "text": "SLA breached", "isSubtle": true, "size": "Small" },
          { "type": "TextBlock", "text": "{{sla_breached}}", "size": "ExtraLarge", "weight": "Bolder", "color": "Attention" }
        ]},
        { "type": "Column", "width": "stretch", "items": [
          { "type": "TextBlock", "text": "Approvals", "isSubtle": true, "size": "Small" },
          { "type": "TextBlock", "text": "{{approvals_pending}}", "size": "ExtraLarge", "weight": "Bolder" }
        ]}
      ]
    },
    {
      "type": "TextBlock",
      "text": "Per assignee",
      "weight": "Bolder",
      "spacing": "Medium",
      "wrap": true
    },
    {
      "type": "FactSet",
      "facts": [
        { "title": "{{assignee_1}}", "value": "{{a1_open}} open · {{a1_p1p2}} P1/P2 · {{a1_sla_risk}} SLA risk" }
      ]
    },
    {
      "type": "TextBlock",
      "text": "Focus next 3 hours",
      "weight": "Bolder",
      "spacing": "Medium",
      "wrap": true
    },
    {
      "type": "TextBlock",
      "text": "{{focus_bullets_markdown}}",
      "wrap": true
    }
  ],
  "actions": [
    {
      "type": "Action.OpenUrl",
      "title": "Open in ServiceNow",
      "url": "{{servicenow_group_url}}"
    }
  ]
}
```

Repeat the `FactSet` row for up to 8 assignees, sorted by open count descending.

## Rules

- Use `color: Attention` for any non-zero P1 or breached SLA value, `Warning` for P2, default
  otherwise.
- The "Focus next 3 hours" markdown must contain at most 5 bullets, each tied to a specific
  incident number, approval id, or SLA breach. No vague advice.
- If `servicenow_group_url` is not derivable, omit the action element entirely; do not output a
  fake URL.

## Tone

Operational and short. Numbers first, words second.
