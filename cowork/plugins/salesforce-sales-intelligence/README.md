# Salesforce Sales Intelligence for Copilot Cowork

This Cowork plugin packages six sales Agent Skills and one remote MCP connector for the Salesforce MCP demo server in this repository. Several skills also use Microsoft 365 WorkIQ context (recent meetings, emails, Loop pages) when available.

## Contents

```text
salesforce-sales-intelligence/
├── manifest.json
├── color.png
├── outline.png
└── skills/
    ├── morning-pipeline-briefing-dashboard/SKILL.md
    ├── weekly-pipeline-review-deck/SKILL.md
    ├── account-deep-dive-brief/SKILL.md
    ├── forecast-call-pack/SKILL.md
    ├── deal-risk-card/SKILL.md
    └── rep-performance-coaching-deck/SKILL.md
```

## What It Does

Skills for account executives, sales managers and RevOps:

- **Morning Pipeline Briefing Dashboard** — daily HTML dashboard combining Salesforce pipeline + WorkIQ context with a recommended activity plan for today.
- **Weekly Pipeline Review Deck** — PowerPoint for the weekly pipeline / forecast call.
- **Account Deep-Dive Brief** — PowerPoint exec brief on a single named account, with WorkIQ relationship signals.
- **Forecast Call Pack** — PowerPoint pack for the monthly / quarterly VP forecast review.
- **Deal Risk Card** — Adaptive Card 1.5 listing at-risk deals with next-best-actions for posting in Teams.
- **Rep Performance Coaching Deck** — PowerPoint 1:1 coaching pack for a single rep, evidence-led.

## Connector

```text
https://essmcp-caldova-salesforce.livelysky-91807d17.eastus2.azurecontainerapps.io/salesforce/mcp
```

> **This MCP server uses the real Salesforce demo org.** The manifest declares `None`; the server runs in `auto` mode and acquires a token using its Key Vault-backed client credentials when no bearer is supplied. A supplied bearer token takes precedence, including when it is rejected by Salesforce. Both no-header and valid-bearer reads were verified. No-header calls run with the stored account's permissions. See [../../AUTHENTICATION.md](../../AUTHENTICATION.md).

## Demo Prompt

```text
Run my morning pipeline briefing for today using Salesforce. Combine pipeline by stage, today's tasks and meetings, slipping deals, and the spotlight account. Use WorkIQ context to tell me which accounts I should prioritise based on today's calendar and recent customer emails.
```

## Package

```powershell
Compress-Archive -Path manifest.json, color.png, outline.png, skills -DestinationPath salesforce-sales-intelligence.zip -Force
```

Upload the zip in Microsoft 365 Admin Center > Manage Apps > Upload custom app, then enable it in Cowork Sources & Skills.
