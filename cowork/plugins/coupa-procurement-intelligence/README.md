# Coupa Procurement Intelligence for Copilot Cowork

This Cowork plugin packages one procurement-focused Agent Skill and one remote MCP connector for the Coupa MCP demo server in this repository.

## Contents

```text
coupa-procurement-intelligence/
├── manifest.json
├── color.png
├── outline.png
└── skills/
    └── supplier-performance-brief/
        ├── SKILL.md
        └── references/
            ├── demo-scenarios.md
            └── slide-patterns.md
```

## What It Does

The skill helps procurement teams create executive-ready assets from Coupa data, especially:

- Supplier performance PowerPoint packs
- IT hardware category manager briefs
- Demand and stock coverage summaries
- ServiceNow-to-Coupa fulfilment flow walkthroughs
- Procurement risk action plans

The connector points to the mock Coupa MCP server:

```text
https://essmcp-coupa.wittysand-460bf1d9.eastus.azurecontainerapps.io/coupa/mcp
```

Authentication is set to `None` because this demo MCP server uses mock data and no auth.

## Demo Prompt

```text
Create a PowerPoint supplier performance pack for IT hardware procurement using Coupa data. Focus on open order value, on-time delivery, supplier risk, delivery exceptions, and recommended actions for the procurement leadership team.
```

## Package

From this folder, create the upload package with PowerShell:

```powershell
Compress-Archive -Path manifest.json, color.png, outline.png, skills -DestinationPath coupa-procurement-intelligence.zip -Force
```

Upload the zip in Microsoft 365 Admin Center > Manage Apps > Upload custom app, then enable it in Cowork Sources & Skills.
