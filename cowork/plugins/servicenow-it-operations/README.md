# ServiceNow IT Operations for Copilot Cowork

This Cowork plugin packages five IT-operations Agent Skills and one remote MCP connector for the ServiceNow MCP demo server in this repository.

## Contents

```text
servicenow-it-operations/
├── manifest.json
├── color.png
├── outline.png
└── skills/
    ├── morning-it-pulse-dashboard/SKILL.md
    ├── weekly-incident-trend-deck/SKILL.md
    ├── change-advisory-board-pack/SKILL.md
    ├── team-workload-card/SKILL.md
    └── knowledge-gap-report/SKILL.md
```

## What It Does

Skills for IT service-management leaders and on-call teams:

- **Morning IT Pulse Dashboard** — daily HTML dashboard with KPIs, top incidents, breached SLAs, today's changes, workload heatmap.
- **Weekly Incident Trend Deck** — 9-slide PowerPoint with WoW trends, MTTR, change failure rate.
- **Change Advisory Board Pack** — CAB pack with one-pager per high-risk change.
- **Team Workload Card** — Adaptive Card 1.5 for shift handover.
- **Knowledge Gap Report** — HTML shift-left report clustering tickets by root short_description.

## Connector

```text
https://essmcp-servicenow.wittysand-460bf1d9.eastus.azurecontainerapps.io/servicenow/mcp
```

Authentication: `OAuthPluginVault` using the same reference id as the declarative agent's ServiceNow MCP plugin. The MCP server is wired to a real ServiceNow tenant — not mock data.

## Demo Prompt

```text
Build the morning IT pulse dashboard for the platform operations team using ServiceNow data: open P1/P2 counts, breached SLAs, today's changes, and a workload heatmap by assignee.
```

## Package

```powershell
Compress-Archive -Path manifest.json, color.png, outline.png, skills -DestinationPath servicenow-it-operations.zip -Force
```

Upload the zip in Microsoft 365 Admin Center > Manage Apps > Upload custom app, then enable it in Cowork Sources & Skills.
