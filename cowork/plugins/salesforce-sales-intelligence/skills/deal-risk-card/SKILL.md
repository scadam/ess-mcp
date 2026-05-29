---
name: deal-risk-card
description: |
  Builds an Adaptive Card for Microsoft Teams listing at-risk and slipping opportunities for a
  rep or team, each with a recommended next-best-action. Designed to be posted into a sales
  channel daily or weekly. Use when the user asks for a "deal risk card", "at-risk deals card",
  "slipping deals card", "post my risk deals to Teams", or "next-best-action card".
license: MIT
compatibility: Copilot Cowork Frontier with the Salesforce MCP connector in this package.
metadata: {author: ESS MCP Demo, version: "1.0.0", demo-audience: AE / Sales Manager}
cowork.category: Sales
cowork.icon: WarningFilled
---

# Deal Risk Card

## What This Skill Does

Produces a single Adaptive Card 1.5 JSON payload listing the user's top at-risk and slipping
opportunities, each with a one-line **recommended next-best-action** drawn from the activity
timeline. Designed for posting into a sales Teams channel each day or as the lead-in to a 1:1.

## When To Use

- "Build the deal risk card"
- "Show me my slipping deals as a Teams card"
- "Post a next-best-action card to the channel"

Do not use for a full HTML dashboard (use `morning-pipeline-briefing-dashboard`) or executive
review (`forecast-call-pack`).

## Required Connector Tools

- `list_opportunities` — open
- `get_pipeline_dashboard`
- `get_activity_timeline` — per at-risk deal
- `get_account_360` — only when a deal is added to the spotlight section

## Default Workflow

1. Resolve the user / team scope. Default = the current user; use `get_team_pipeline_summary` if
   the user is a manager and asked for the team view.
2. Pull open opps and pipeline dashboard.
3. Identify at-risk opps using:
   - Stage age > 1.5× median for that stage, OR
   - Close date slipped at least once in the last 30 days, OR
   - No activity in the last 14 days, OR
   - Forecast category = Best Case but close date is within 14 days.
4. Rank by amount × heat-weight; take top 6.
5. For each, fetch `get_activity_timeline` and derive a single concrete next-best-action
   (specific contact, specific channel, specific question).
6. Build the Adaptive Card. Output the **raw JSON** in a fenced ```json``` block plus a one-line
   preview suitable for the Teams notification.

## Adaptive Card Template

```json
{
  "type": "AdaptiveCard",
  "$schema": "https://adaptivecards.io/schemas/adaptive-card.json",
  "version": "1.5",
  "body": [
    {
      "type": "TextBlock",
      "text": "Deals at risk — {{scope}}",
      "weight": "Bolder",
      "size": "Large",
      "wrap": true
    },
    {
      "type": "TextBlock",
      "text": "{{date}} · {{count}} deals · ${{at_risk_value}} at stake",
      "isSubtle": true,
      "spacing": "None",
      "wrap": true
    },
    {
      "type": "Container",
      "spacing": "Medium",
      "items": [
        {
          "type": "ColumnSet",
          "columns": [
            { "type": "Column", "width": "stretch", "items": [
              { "type": "TextBlock", "text": "{{opp_1}}", "weight": "Bolder", "wrap": true },
              { "type": "TextBlock", "text": "{{account_1}} · {{stage_1}} · ${{amount_1}} · close {{close_1}}", "isSubtle": true, "size": "Small", "wrap": true },
              { "type": "TextBlock", "text": "Why at risk: {{risk_1}}", "wrap": true, "size": "Small" },
              { "type": "TextBlock", "text": "Next best action: {{nba_1}}", "wrap": true, "weight": "Bolder", "color": "Accent" }
            ]},
            { "type": "Column", "width": "auto", "items": [
              { "type": "TextBlock", "text": "{{heat_1}}", "weight": "Bolder", "color": "Attention" }
            ]}
          ]
        },
        { "type": "TextBlock", "text": "—", "isSubtle": true, "horizontalAlignment": "Center" }
      ]
    }
  ]
}
```

Repeat the inner `Container` block (with `_2`, `_3`, …) for up to 6 deals. The outer card height
should comfortably fit on a Teams desktop screen without scroll.

## Next-Best-Action Rules

The NBA must be specific:
- A named contact ("Re-engage Priya Shah, the CFO")
- A channel ("send WhatsApp", "book 15-min Teams call", "in-person at trade show next week")
- A question or ask ("ask about budget cycle alignment for Q2")

If the activity timeline is empty for a deal, NBA = "kick off a contact-restart sequence with the
last known champion: {{name}}" and explain in the risk line.

## Heat Labels

- 🔴 → use text "high"
- 🟠 → use text "medium"
- 🟡 → use text "watch"

(Use the words, not emoji, in the card.)

## Tone

Direct. The point of the card is to drive action by the end of the day.
