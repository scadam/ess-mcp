# Jira Delivery Intelligence for Copilot Cowork

This Cowork plugin packages five engineering-delivery Agent Skills and one remote MCP connector for the Jira MCP server in this repository.

## Contents

```text
jira-delivery-intelligence/
├── manifest.json
├── color.png
├── outline.png
└── skills/
    ├── daily-standup-brief-dashboard/SKILL.md
    ├── sprint-health-deck/SKILL.md
    ├── release-readiness-pack/SKILL.md
    ├── weekly-delivery-update-card/SKILL.md
    └── backlog-grooming-report/SKILL.md
```

## What It Does

Skills for engineering managers, scrum masters, product owners and tech leads:

- **Daily Standup Brief Dashboard** — daily HTML brief with burndown, in-flight per assignee, blockers, at-risk items, and a "for your standup" markdown summary.
- **Sprint Health Deck** — PowerPoint sprint review / retrospective with burndown, velocity trend, scope changes, blockers timeline.
- **Release Readiness Pack** — PowerPoint go/no-go pack for a Jira fix-version.
- **Weekly Delivery Update Card** — Adaptive Card 1.5 for a Teams channel update (public information only).
- **Backlog Grooming Report** — HTML hygiene report with stale / unestimated / missing-AC items and a recommended grooming shortlist.

## Connector

```text
https://essmcp-caldova-jira.livelysky-91807d17.eastus2.azurecontainerapps.io/jira/mcp
```

> **This MCP server uses the real Jira demo site.** Authentication is set to `OAuthPluginVault`. Before uploading, replace the existing `REPLACE_WITH_JIRA_OAUTH_REFERENCE_ID` placeholder in [manifest.json](manifest.json) with an actual new-tenant OAuth registration reference. Jira's verified flow is interactive authorization-code consent initially, followed by refresh-token renewal; client credentials alone did not grant site access. The deployment test's read-only consent is not a Copilot connection registration. See [../../AUTHENTICATION.md](../../AUTHENTICATION.md).

## Demo Prompt

```text
Run my daily standup brief for the active sprint. Show burndown vs ideal, who is working on what today, blockers, items at risk of slipping, and overnight changes. Also give me a markdown "for your standup" summary at the top.
```

## Package

```powershell
Compress-Archive -Path manifest.json, color.png, outline.png, skills -DestinationPath jira-delivery-intelligence.zip -Force
```

Upload the zip in Microsoft 365 Admin Center > Manage Apps > Upload custom app, then enable it in Cowork Sources & Skills.
