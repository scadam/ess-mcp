---
name: weekly-delivery-update-card
description: |
  Builds an Adaptive Card 1.5 for posting a weekly engineering-delivery update into a Microsoft
  Teams channel: sprint progress, completed and shipped this week, blockers, ask-of-the-business,
  and what's next. Public-information only. Use when the user asks for a "weekly delivery update
  card", "engineering update card", "ship-it card", or "post our team update to Teams".
license: MIT
compatibility: Copilot Cowork Frontier with the Jira MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: Engineering Manager / Tech Lead}
cowork.category: Engineering
cowork.icon: ChannelArrowLeftFilled
---

# Weekly Delivery Update Card

## What This Skill Does

Produces a single Adaptive Card 1.5 JSON payload — a weekly engineering-delivery update suitable
for posting into a Teams channel. Sprint progress, what shipped this week, current blockers,
ask-of-the-business, and what's next. Designed for public consumption (no individual
performance data).

## When To Use

- "Build the weekly delivery update card"
- "Post our engineering update for the channel"
- "Weekly ship-it card"

Do not use for the daily standup (`daily-standup-brief-dashboard`) or retrospective
(`sprint-health-deck`).

## Required Connector Tools

- `get_team_sprint_health`
- `list_sprints` (active)
- `list_issues` (recently completed = transitioned to Done in last 7 days)
- `list_versions` (any released this week)
- `list_epics` (status of major epics in flight)

## Default Workflow

1. Resolve scope.
2. Pull active sprint health, recently completed issues, any version released this week, and the
   status of major in-flight epics.
3. Filter out anything that names individual performance — keep team-level only.
4. Build the card. Output the **raw JSON** in a fenced ```json``` block plus a one-line preview
   suitable for the Teams notification.

## Adaptive Card Template

```json
{
  "type": "AdaptiveCard",
  "$schema": "https://adaptivecards.io/schemas/adaptive-card.json",
  "version": "1.5",
  "body": [
    {
      "type": "TextBlock",
      "text": "{{team}} — Weekly Delivery Update",
      "weight": "Bolder",
      "size": "Large",
      "wrap": true
    },
    {
      "type": "TextBlock",
      "text": "Week of {{week}} · Sprint {{sprint_name}} ({{sprint_progress_pct}}%)",
      "isSubtle": true,
      "spacing": "None",
      "wrap": true
    },
    {
      "type": "ColumnSet",
      "spacing": "Medium",
      "columns": [
        { "type": "Column", "width": "stretch", "items": [
          { "type": "TextBlock", "text": "Shipped", "weight": "Bolder", "color": "Good" },
          { "type": "TextBlock", "text": "{{shipped_summary}}", "wrap": true, "size": "Small" }
        ]},
        { "type": "Column", "width": "stretch", "items": [
          { "type": "TextBlock", "text": "In progress", "weight": "Bolder", "color": "Accent" },
          { "type": "TextBlock", "text": "{{in_progress_summary}}", "wrap": true, "size": "Small" }
        ]},
        { "type": "Column", "width": "stretch", "items": [
          { "type": "TextBlock", "text": "Blocked", "weight": "Bolder", "color": "Attention" },
          { "type": "TextBlock", "text": "{{blocked_summary}}", "wrap": true, "size": "Small" }
        ]}
      ]
    },
    {
      "type": "TextBlock",
      "text": "Major epics",
      "weight": "Bolder",
      "spacing": "Medium"
    },
    {
      "type": "FactSet",
      "facts": [
        { "title": "{{epic_1}}", "value": "{{epic_1_status}}" },
        { "title": "{{epic_2}}", "value": "{{epic_2_status}}" },
        { "title": "{{epic_3}}", "value": "{{epic_3_status}}" }
      ]
    },
    {
      "type": "TextBlock",
      "text": "Asks for the business",
      "weight": "Bolder",
      "spacing": "Medium"
    },
    {
      "type": "TextBlock",
      "text": "{{asks_markdown}}",
      "wrap": true,
      "size": "Small"
    },
    {
      "type": "TextBlock",
      "text": "Next week",
      "weight": "Bolder",
      "spacing": "Medium"
    },
    {
      "type": "TextBlock",
      "text": "{{next_week_markdown}}",
      "wrap": true,
      "size": "Small"
    }
  ]
}
```

## Content Rules

- "Shipped" = items moved to Done in the last 7 days, summarised at epic / theme level — do NOT
  list every issue.
- "Asks for the business" must each name a person (by role, not name) and a date — no generic
  "more support".
- Never include per-engineer counts on a public channel card.
- If there were no shipped items this week, write "Nothing shipped this week — focus was on {{x}}"
  rather than empty string.

## Tone

Channel-friendly. Brief, factual, no celebratory hype, no apology.
