# Workday People Leader for Copilot Cowork

This Cowork plugin packages five people-leader Agent Skills and one remote MCP connector for the Workday MCP demo server in this repository.

## Contents

```text
workday-people-leader/
├── manifest.json
├── color.png
├── outline.png
└── skills/
    ├── morning-people-pulse-dashboard/SKILL.md
    ├── team-performance-review-pack/SKILL.md
    ├── weekly-team-update-card/SKILL.md
    ├── headcount-and-org-brief/SKILL.md
    └── learning-compliance-report/SKILL.md
```

## What It Does

Skills for people managers and HR business partners:

- **Morning People Pulse Dashboard** — daily HTML manager dashboard with PTO, anniversaries, open requisitions.
- **Team Performance Review Pack** — PowerPoint with per-direct-report one-pager, with feedback source-masking.
- **Weekly Team Update Card** — Adaptive Card 1.5 for the team channel using public-only info.
- **Headcount & Org Brief** — 9-slide PowerPoint org brief for a skip-level review.
- **Learning Compliance Report** — HTML compliance dashboard with per-person completion %.

## Connector

```text
https://essmcp-caldova-workday.livelysky-91807d17.eastus2.azurecontainerapps.io/workday/mcp
```

> This server uses the real Workday demo tenant. With `None` client authentication, the MCP server obtains a token using its Key Vault-backed refresh-token credentials. A supplied bearer token takes precedence; rejected caller tokens are not retried as the stored account. No-header and valid-bearer reads were both verified. No-header calls use the configured default worker and stored account's permissions. See [../../AUTHENTICATION.md](../../AUTHENTICATION.md).

## Demo Prompt

```text
Build a Workday morning people pulse dashboard for my team for today: who's out, anniversaries this week, open requisitions, learning compliance status, and a "for your standup" markdown summary.
```

## Package

```powershell
Compress-Archive -Path manifest.json, color.png, outline.png, skills -DestinationPath workday-people-leader.zip -Force
```

Upload the zip in Microsoft 365 Admin Center > Manage Apps > Upload custom app, then enable it in Cowork Sources & Skills.
