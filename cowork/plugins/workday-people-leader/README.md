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
https://essmcp-workday.wittysand-460bf1d9.eastus.azurecontainerapps.io/workday/mcp
```

> This MCP server is wired to a real Workday tenant — not mock data. Authentication is currently set to `None` for the demo gateway; tighten the auth before broader rollout.

## Demo Prompt

```text
Build a Workday morning people pulse dashboard for my team for today: who's out, anniversaries this week, open requisitions, learning compliance status, and a "for your standup" markdown summary.
```

## Package

```powershell
Compress-Archive -Path manifest.json, color.png, outline.png, skills -DestinationPath workday-people-leader.zip -Force
```

Upload the zip in Microsoft 365 Admin Center > Manage Apps > Upload custom app, then enable it in Cowork Sources & Skills.
