# 🟪 Copilot Cowork Plugins — MCP Servers + Skills

[← Back to main README](../README.md) · See also: [MCP Servers](mcp-servers.md) · [Demo Agent](demo-agent.md)

**Copilot Cowork** is Microsoft 365 Copilot's pane-of-glass for *building artifacts with your data* — daily dashboards, PowerPoint review decks, Adaptive Card team updates, executive briefs. Cowork plugins combine **Agent Skills** (markdown recipes the agent follows) with **remote MCP connectors** that fetch the data the skills need.

ESS-MCP ships **5 Cowork plugins**, each pairing a fleet of skills with one of the ESS-MCP servers as its remote MCP connector. Every skill is a fully written `SKILL.md` shipped in the plugin package.

| Plugin | Audience | Skills | MCP connector |
|--------|----------|--------|----------------|
| **🟦 Workday People Leader** | People managers & HRBPs | 5 | Workday MCP |
| **🟧 ServiceNow IT Operations** | ITSM leaders, on-call teams | 5 | ServiceNow MCP |
| **🟩 Salesforce Sales Intelligence** | AEs, sales managers, RevOps | 6 | Salesforce MCP (+ WorkIQ) |
| **🟦 Jira Delivery Intelligence** | Engineering managers, scrum masters, POs | 5 | Jira MCP |
| **🟫 Coupa Procurement Intelligence** | Procurement & category managers | 1 | Coupa MCP (mocked) |

All five plugins live under [`cowork/plugins/`](../cowork/plugins). Each plugin folder ships a `manifest.json` (devPreview Teams schema), a packaged `.zip`, the connector configuration, and the `SKILL.md` files.

---

## 🟦 Workday People Leader

<img src="../cowork/plugins/workday-people-leader/color.png" width="64" alt="Workday People Leader icon"/>

📁 [`cowork/plugins/workday-people-leader/`](../cowork/plugins/workday-people-leader) · 📄 [README](../cowork/plugins/workday-people-leader/README.md)

Skills for people managers and HR business partners:

- **Morning People Pulse Dashboard** — daily HTML manager dashboard with PTO, anniversaries, open requisitions
- **Team Performance Review Pack** — PowerPoint with per-direct-report one-pager and feedback source-masking
- **Weekly Team Update Card** — Adaptive Card 1.5 for the team channel using public-only info
- **Headcount & Org Brief** — 9-slide PowerPoint org brief for a skip-level review
- **Learning Compliance Report** — HTML compliance dashboard with per-person completion %

Wired to the **Workday MCP** server (live tenant, not mocks).

**Demo prompt:**
> *"Build a Workday morning people pulse dashboard for my team for today: who's out, anniversaries this week, open requisitions, learning compliance status, and a 'for your standup' markdown summary."*

---

## 🟧 ServiceNow IT Operations

<img src="../cowork/plugins/servicenow-it-operations/color.png" width="64" alt="ServiceNow IT Operations icon"/>

📁 [`cowork/plugins/servicenow-it-operations/`](../cowork/plugins/servicenow-it-operations) · 📄 [README](../cowork/plugins/servicenow-it-operations/README.md)

Skills for IT service-management leaders and on-call teams:

- **Morning IT Pulse Dashboard** — daily HTML dashboard with KPIs, top incidents, breached SLAs, today's changes, workload heatmap
- **Weekly Incident Trend Deck** — 9-slide PowerPoint with WoW trends, MTTR, change failure rate
- **Change Advisory Board Pack** — CAB pack with one-pager per high-risk change
- **Team Workload Card** — Adaptive Card 1.5 for shift handover
- **Knowledge Gap Report** — HTML shift-left report clustering tickets by root `short_description`

Wired to the **ServiceNow MCP** server.

---

## 🟩 Salesforce Sales Intelligence

<img src="../cowork/plugins/salesforce-sales-intelligence/color.png" width="64" alt="Salesforce Sales Intelligence icon"/>

📁 [`cowork/plugins/salesforce-sales-intelligence/`](../cowork/plugins/salesforce-sales-intelligence) · 📄 [README](../cowork/plugins/salesforce-sales-intelligence/README.md)

Skills for account executives, sales managers, and RevOps. Several skills also use **Microsoft 365 WorkIQ** context (recent meetings, emails, Loop pages) when available:

- **Morning Pipeline Briefing Dashboard** — daily HTML dashboard combining Salesforce pipeline + WorkIQ context with a recommended activity plan
- **Weekly Pipeline Review Deck** — PowerPoint for the weekly pipeline / forecast call
- **Account Deep-Dive Brief** — PowerPoint exec brief on a single named account, with WorkIQ relationship signals
- **Forecast Call Pack** — PowerPoint pack for the monthly / quarterly VP forecast review
- **Deal Risk Card** — Adaptive Card 1.5 listing at-risk deals with next-best-actions for posting in Teams
- **Rep Performance Coaching Deck** — PowerPoint 1:1 coaching pack for a single rep, evidence-led

Wired to the **Salesforce MCP** server + WorkIQ.

---

## 🟦 Jira Delivery Intelligence

<img src="../cowork/plugins/jira-delivery-intelligence/color.png" width="64" alt="Jira Delivery Intelligence icon"/>

📁 [`cowork/plugins/jira-delivery-intelligence/`](../cowork/plugins/jira-delivery-intelligence) · 📄 [README](../cowork/plugins/jira-delivery-intelligence/README.md)

Skills for engineering managers, scrum masters, product owners, and tech leads:

- **Daily Standup Brief Dashboard** — daily HTML brief with burndown, in-flight per assignee, blockers, at-risk items, and a "for your standup" markdown summary
- **Sprint Health Deck** — PowerPoint sprint review / retrospective with burndown, velocity trend, scope changes, blockers timeline
- **Release Readiness Pack** — PowerPoint go / no-go pack for a Jira fix-version
- **Weekly Delivery Update Card** — Adaptive Card 1.5 for a Teams channel update (public information only)
- **Backlog Grooming Report** — HTML hygiene report with stale / unestimated / missing-AC items and a recommended grooming shortlist

Wired to the **Jira MCP** server.

---

## 🟫 Coupa Procurement Intelligence

<img src="../cowork/plugins/coupa-procurement-intelligence/color.png" width="64" alt="Coupa Procurement Intelligence icon"/>

📁 [`cowork/plugins/coupa-procurement-intelligence/`](../cowork/plugins/coupa-procurement-intelligence) · 📄 [README](../cowork/plugins/coupa-procurement-intelligence/README.md)

The skill helps procurement teams create executive-ready assets from Coupa data:

- Supplier performance PowerPoint packs
- IT hardware category-manager briefs
- Demand and stock coverage summaries
- ServiceNow → Coupa fulfilment flow walkthroughs
- Procurement risk action plans

Wired to the mock **Coupa MCP** server.

---

## Packaging & Upload

Each plugin folder is packaged as a Teams app `.zip`:

```powershell
cd cowork/plugins/workday-people-leader
Compress-Archive -Path manifest.json, color.png, outline.png, skills `
  -DestinationPath workday-people-leader.zip -Force
```

Then in **Microsoft 365 Admin Center → Manage Apps → Upload custom app**, upload the zip and enable it under **Cowork → Sources & Skills**.

---

[← Back to main README](../README.md)
