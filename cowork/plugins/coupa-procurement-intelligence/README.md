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
https://essmcp-caldova-coupa.livelysky-91807d17.eastus2.azurecontainerapps.io/coupa/mcp
```

Authentication is set to `None` because this demo MCP server uses mock data and no auth.

## Demo Prompt

```text
Create a PowerPoint supplier performance pack for IT hardware procurement using Coupa data. Focus on open order value, on-time delivery, supplier risk, delivery exceptions, and recommended actions for the procurement leadership team.
```

## Package

Use ATK provisioning with the `caldova` environment in [m365agents.yml](m365agents.yml). It rebuilds the current manifest, includes every declared skill, and validates [build/appPackage.caldova.zip](build/appPackage.caldova.zip).

Microsoft 365 rejects nested ZIP files inside skill folders. [../../prepare_atk_package.ps1](../../prepare_atk_package.ps1) removes those entries from the generated upload only; both original skill archives remain untouched. Do not recursively archive the unfiltered skill directory for upload.

Publish the verified ZIP using ATK's explicit `--package-file` option. The tested CLI otherwise rebuilds an unfiltered package without running the custom lifecycle filter. Publication submits the app to [Teams Admin Center](https://admin.teams.microsoft.com/policies/manage-apps) for approval. After approval, enable it in Cowork Sources & Skills.
