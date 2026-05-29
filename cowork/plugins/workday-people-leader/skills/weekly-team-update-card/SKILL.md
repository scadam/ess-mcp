---
name: weekly-team-update-card
description: |
  Builds an Adaptive Card for Microsoft Teams summarising the week ahead for a manager's team:
  who is out, key milestones (anniversaries, role starts), team goals progress, and learning
  status. Use when the user asks for a "weekly team update card", "Monday team card",
  "team Teams update", "post my weekly to the team channel" or "team week-ahead card".
license: MIT
compatibility: Copilot Cowork Frontier with the Workday MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: People Manager}
cowork.category: People & HR
cowork.icon: CalendarWorkWeek
---

# Weekly Team Update Card

## What This Skill Does

Produces a single Adaptive Card 1.5 JSON payload a people manager can post to their team's
Microsoft Teams channel each Monday. Summarises the week ahead: who is out and when, anniversaries
or new joiners this week, headline goal progress, and any required learning due this week.

## When To Use

- "Post my weekly team update card"
- "Monday team card for the channel"
- "Build the week-ahead card for my team"

Do not use this for executive review (use `team-performance-review-pack`) or a daily manager view
(use `morning-people-pulse-dashboard`).

## Required Connector Tools

- `get_worker`, `get_direct_reports`
- `get_team_calendar`
- `get_team_overview`
- `get_team_goals`
- `get_learning_assignments` (per report when checking due-this-week status)

If the connector is not bound, stop and report.

## Default Workflow

1. Resolve manager and team.
2. Compute the week window: Monday → Sunday in the manager's stated timezone (default UTC).
3. Pull the calendar, overview and goals.
4. Determine "this week" milestones from `get_team_overview` data: anniversaries, new starts,
   role changes within the window.
5. Compute headline goal progress: % of team goals on track vs at risk.
6. Build the Adaptive Card payload. Output the **raw JSON** in a fenced ```json``` block plus a
   one-line preview suitable for the Teams notification.

## Adaptive Card Template

```json
{
  "type": "AdaptiveCard",
  "$schema": "https://adaptivecards.io/schemas/adaptive-card.json",
  "version": "1.5",
  "body": [
    {
      "type": "TextBlock",
      "text": "{{team_name}} — Week of {{week_start}}",
      "weight": "Bolder",
      "size": "Large",
      "wrap": true
    },
    {
      "type": "TextBlock",
      "text": "Posted by {{manager_name}}",
      "isSubtle": true,
      "spacing": "None",
      "wrap": true
    },
    {
      "type": "ColumnSet",
      "spacing": "Medium",
      "columns": [
        { "type": "Column", "width": "stretch", "items": [
          { "type": "TextBlock", "text": "Out this week", "isSubtle": true, "size": "Small" },
          { "type": "TextBlock", "text": "{{out_count}}", "size": "ExtraLarge", "weight": "Bolder" }
        ]},
        { "type": "Column", "width": "stretch", "items": [
          { "type": "TextBlock", "text": "Goals on track", "isSubtle": true, "size": "Small" },
          { "type": "TextBlock", "text": "{{goals_on_track_pct}}%", "size": "ExtraLarge", "weight": "Bolder", "color": "Good" }
        ]},
        { "type": "Column", "width": "stretch", "items": [
          { "type": "TextBlock", "text": "Learning due this week", "isSubtle": true, "size": "Small" },
          { "type": "TextBlock", "text": "{{learning_due_count}}", "size": "ExtraLarge", "weight": "Bolder", "color": "Warning" }
        ]}
      ]
    },
    {
      "type": "TextBlock",
      "text": "Out of office",
      "weight": "Bolder",
      "spacing": "Medium",
      "wrap": true
    },
    {
      "type": "FactSet",
      "facts": [
        { "title": "{{name_1}}", "value": "{{type_1}} · {{from_1}}–{{to_1}}" }
      ]
    },
    {
      "type": "TextBlock",
      "text": "Milestones",
      "weight": "Bolder",
      "spacing": "Medium",
      "wrap": true
    },
    {
      "type": "TextBlock",
      "text": "{{milestones_markdown}}",
      "wrap": true
    },
    {
      "type": "TextBlock",
      "text": "Manager focus",
      "weight": "Bolder",
      "spacing": "Medium",
      "wrap": true
    },
    {
      "type": "TextBlock",
      "text": "{{focus_markdown}}",
      "wrap": true
    }
  ]
}
```

Repeat the OOO `FactSet` row for up to 8 entries. The `milestones_markdown` is a short bulleted
list ("- Anniv: 5y for Priya — Mon", "- Start: Karl joins as SE — Wed"). The `focus_markdown` is
1–3 manager-facing items the team should know about (no individual performance data).

## Rules

- Never include private feedback, ratings, leave reasons, or salary information in this card —
  it is a public team channel artifact.
- Anniversaries and new starts are public and OK to include.
- If `goals_on_track_pct` cannot be computed cleanly, omit that column rather than guess.
- Keep the card short enough to fit without scroll on desktop Teams (~600px).

## Tone

Inclusive, present-tense, no exclamation marks, no emoji unless the user explicitly asks.
