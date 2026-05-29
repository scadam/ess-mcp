# 🔧 MCP Servers — The Core

[← Back to main README](../README.md) · See also: [Widget Gallery](widgets.md) · [Azure Deployment](deployment.md) · [Declarative Agent](declarative-agent.md)

ESS-MCP is a suite of [Model Context Protocol](https://modelcontextprotocol.io/) servers that connect AI assistants to enterprise systems. Each server exposes **actionable tools** and **interactive HTML+Skybridge widgets** that let an AI agent read, create, update, and act on behalf of employees and managers.

| Server | Platform | Tools | Widgets | Key actions |
|--------|----------|-------|---------|-------------|
| **Workday** | HR / HCM | 33 | 16 | Book leave, change title, approve/deny inbox tasks, browse learning catalog, give feedback, track goals, create check-ins, view development items, compensation, org charts, **team dashboard**, **team goals** |
| **ServiceNow** | ITSM | 39 | 12 | Create/update incidents & tasks, approve/reject requests, order catalog items, manage change requests, create KB articles, track SLAs, **team incidents** |
| **Salesforce** | CRM | 44 | 9 | Create/update opportunities/leads/contacts/quotes/tasks, approve/reject, convert leads, add campaign members, run reports, activity timeline, **team pipeline** |
| **Jira** | Project Management | 26 | 5 | Create/update issues, transition workflows, log work, move issues to sprints, link issues, manage releases/versions, **team workload** |
| **SAP SuccessFactors** | HR / HCM | 20 | 10 | Employee profiles, leave booking, pay stubs, org charts, personal data changes, employee moves, document management, background checks, employment verification |
| **SAP Ariba** | Procurement | 21 | 12 | Invoice/PO status, receipts, requisitions, catalog search, supplier management, approvals, supplier registration |
| **Coupa** | Procurement | 21 | 12 | Invoice/PO status, receipts, requisitions, catalog search, supplier management, approvals *(fully mocked — no sandbox available)* |

> **204 tools · 76 widgets total.** Servers run individually, in any combination, or all together — locally or on Azure Container Apps.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                            AI Assistant / Client                                │
│                     (ChatGPT, Copilot, Claude, etc.)                            │
└──────────────┬──────────────────────────────────────────────────┬───────────────┘
               │  MCP (SSE / Streamable HTTP)                     │
               ▼                                                  ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          ESS-MCP Gateway (:8080)                                │
│                                                                                 │
│  /workday/mcp  /servicenow/mcp  /salesforce/mcp  /jira/mcp                      │
│  /sap_sf/mcp   /ariba/mcp       /coupa/mcp                                      │
│  /healthz                                                                       │
│                                                                                 │
│  ┌─────────┐ ┌───────────┐ ┌──────────┐ ┌──────┐ ┌───────┐ ┌─────┐ ┌─────┐      │
│  │ Workday │ │ServiceNow │ │Salesforce│ │ Jira │ │SAP SF │ │Ariba│ │Coupa│      │
│  └────┬────┘ └─────┬─────┘ └────┬─────┘ └──┬───┘ └───┬───┘ └──┬──┘ └──┬──┘      │
│       │            │            │          │         │        │       │         │
│       │       ****** Passthrough / Token Exchange       │   (Mocked)      │
└───────┼────────────┼────────────┼──────────┼─────────┼────────┼───────┼─────────┘
        ▼            ▼            ▼          ▼         ▼        ▼       ▼
  Workday API  ServiceNow API Salesforce  Jira API   SAP SF   Ariba  (Local
                              API                    OData   Sandbox  Mock)
```

Each MCP server:

- **Extracts** bearer tokens from incoming requests (OAuth 2.0 passthrough)
- **Exposes** tools for CRUD operations against the target platform
- **Serves** interactive HTML+Skybridge widgets for rich UI rendering
- **Runs** independently or composed behind a shared ASGI gateway

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+**
- **Azure CLI** (only if you want to deploy to Azure)

### Local Development

```bash
git clone https://github.com/scadam/ess-mcp.git
cd ess-mcp/mcp_servers

# Install in development mode
pip install -e ".[dev]"

# Copy and configure environment files
cp env/workday.example.env env/workday.env
cp env/servicenow.example.env env/servicenow.env
cp env/salesforce.example.env env/salesforce.env
cp env/jira.example.env env/jira.env
cp env/sap_sf.example.env env/sap_sf.env
cp env/ariba.example.env env/ariba.env
cp env/coupa.example.env env/coupa.env
# Edit each .env file with your service URLs

# Run a single server (stdio – direct MCP client)
python -m mcp_servers.cli workday --transport stdio

# Run a single server (HTTP)
python -m mcp_servers.cli jira --transport http --port 8080

# Run all servers (HTTP + SSE)
python -m mcp_servers.cli all --transport both --port 8080
```

### Docker (Optional – Local Dev)

```bash
cd mcp_servers
docker build -t ess-mcp .
docker run -p 8080:8080 ess-mcp
```

> Docker is only needed for local container testing. Azure deployment uses ACR remote build — no local Docker installation required.

### Verify

```bash
curl http://localhost:8080/healthz
# → {"status": "ok"}

curl -X POST http://localhost:8080/workday/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

---

## 🔌 Transport Modes

| Mode | Command | Use Case |
|------|---------|----------|
| **stdio** | `--transport stdio` | Direct MCP client integration (single server only) |
| **SSE** | `--transport sse` | Server-Sent Events for streaming |
| **HTTP** | `--transport http` | Streamable HTTP for request/response |
| **Both** | `--transport both` | SSE + HTTP simultaneously (default for container deployment) |

**Endpoints** (when running all servers with `--transport both`):

| Path | Transport |
|------|-----------|
| `/{server}/mcp` | Streamable HTTP |
| `/{server}/sse` | Server-Sent Events |
| `/healthz` | Health check |

---

## 🔐 Authentication Model

ESS-MCP uses **OAuth 2.0 bearer token passthrough** — the MCP server extracts the bearer token from each incoming request's `Authorization` header and forwards it to the target SaaS API. No tokens are stored or validated by the MCP layer.

```
Client → Authorization: ****** → MCP Server → ****** → SaaS API
```

The MCP client is responsible for obtaining a valid bearer token. Per-platform OAuth client setup (Workday, ServiceNow, Salesforce, Jira) lives in **[deployment.md → OAuth Client Setup](deployment.md#oauth-client-setup-per-saas-platform)**.

For **governed** access — with token exchange, Agent Identity assertions, policy, and full observability — front the MCP servers with the Azure API Management AI Gateway as the [Demo Agent](demo-agent.md) does.

---

## 🧰 Per-Server Tool Reference

### Workday – HR / Employee Self-Service

> *Employee profiles, leave management, compensation, org hierarchy, learning, and team calendar.*

| Tool | Type | Description |
|------|------|-------------|
| `get_worker` | 📖 Read | Fetch current worker profile |
| `get_leave_balances` | 📖 Read | View PTO / leave balances |
| `get_direct_reports` | 📖 Read | List direct reports |
| `get_inbox_tasks` | 📖 Read | Fetch pending approval tasks (widget) |
| `get_learning_assignments` | 📖 Read | View learning initiatives (widget) |
| `get_pay_slips` | 📖 Read | Access payroll information |
| `get_time_off_entries` | 📖 Read | Historical time-off records |
| `prepare_request_leave` | 🖼️ Widget | Book time off — interactive leave booking form |
| `book_leave` | ⚙️ Callback | Widget callback: submits leave booking |
| `prepare_change_business_title` | 🖼️ Widget | Change business title — interactive form |
| `change_business_title` | ⚙️ Callback | Widget callback: submits title change |
| `search_learning_content` | 📖 Read | Search the learning library |
| `prepare_learning_search` | 🖼️ Widget | Browse learning — interactive search |
| `get_org_chart` | 📖 Read | Organization hierarchy (widget) |
| `get_team_calendar` | 📖 Read | Team availability calendar (widget) |
| `get_team_overview` | 📖 Read | 👔 Manager team headcount dashboard |
| `get_team_performance_summary` | 📖 Read | 👔 Manager pending reviews & action items |
| `action_inbox_task` | ✏️ Action | Approve or reject an inbox task |
| `get_inbox_task_detail` | 📖 Read | Get detailed info for an inbox task |
| `get_goals` | 📖 Read | Performance goals with status (dashboard) |
| `get_feedback` | 📖 Read | Anytime feedback received from colleagues |
| `give_feedback` | ✏️ Action | Give anytime feedback to a colleague |
| `get_feedback_badges` | 📖 Read | List available feedback badges |
| `get_development_items` | 📖 Read | Individual development plan (widget) |
| `request_feedback_on_self` | ✏️ Action | Request feedback from peers |
| `get_learning_records` | 📖 Read | Learning history with completion & grades |
| `get_check_ins` | 📖 Read | 1:1 check-in records with topics |
| `create_check_in` | ✏️ Create | Create a 1:1 check-in record |
| `get_check_in_topics` | 📖 Read | List check-in topics |
| `get_worker_skills` | 📖 Read | Skills on your Workday profile |
| `get_team_goals` | 📖 Read | 👔 Manager direct reports' goals (widget) |
| `request_feedback_on_worker` | ✏️ Action | 👔 Manager request feedback on a report |
| `prepare_give_feedback` | 🖼️ Widget | Give feedback — 3-step wizard |
| `prepare_create_check_in` | 🖼️ Widget | Create check-in — wizard |

**Widgets:** `worker-profile`, `leave-booking`, `org-chart`, `team-calendar`, `team-dashboard`, `change-business-title`, `learning-assignments`, `learning-search`, `inbox-tasks`, `give-feedback`, `goals-dashboard`, `create-check-in-form`, `development-items`, `team-goals`

**Configuration** (`env/workday.env`):
```env
WORKDAY_BASE_URL=https://your-workday-host.workday.com
WORKDAY_TENANT=your_tenant_name
```

### ServiceNow – IT Service Management

> *Incidents, change requests, problems, service catalog, knowledge base, approvals, and CMDB.*

| Tool | Type | Description |
|------|------|-------------|
| `list_incidents` / `get_incident` | 📖 Read | View and search incidents |
| `show_create_incident_form` | 🖼️ Widget | Create new incident — interactive form |
| `create_incident` | ⚙️ Callback | Widget callback: submits incident |
| `show_update_incident_form` | 🖼️ Widget | Edit an incident — interactive form |
| `update_incident` | ⚙️ Callback | Widget callback: submits update |
| `list_tasks` | 📖 Read | List active tasks |
| `update_task` | ✏️ Update | Update task state, priority, assignment, or notes |
| `list_approvals` / `get_approval` | 📖 Read | View pending approvals |
| `approve_reject` | ⚡ Action | Approve or reject approval request |
| `list_catalog_items` / `list_catalog_categories` | 📖 Read | Browse service catalog |
| `get_catalog_item` | 📖 Read | Get catalog item with order form |
| `order_catalog_item` | ⚙️ Callback | Widget callback: orders item |
| `add_to_cart` / `get_cart` / `checkout_cart` | ⚙️ Cart | Cart flow callbacks |
| `delete_cart` / `remove_cart_item` | 🗑️ Delete | Empty cart or remove items |
| `list_my_requests` | 📖 Read | User's service requests |
| `list_change_requests` / `get_change_request` | 📖 Read | View change requests |
| `show_create_change_req_form` | 🖼️ Widget | Create change request form |
| `create_change_request` | ⚙️ Callback | Widget callback: submits CR |
| `update_change_request` | ✏️ Update | Update change request |
| `search_knowledge` / `get_knowledge_article` | 📖 Read | Search knowledge base |
| `create_knowledge_article` | ✏️ Create | Create new KB article as draft |
| `list_problems` / `show_create_problem_form` / `create_problem` / `update_problem` | 🖼️ + Action | Problem record CRUD |
| `search_reference_values` | 📖 Read | Search table values for dropdowns |
| `get_cmdb_ci` / `list_cmdb_cis` | 📖 Read | CMDB configuration items |
| `get_sla_status` | 📖 Read | SLA compliance — breached, at-risk, compliant |
| `get_team_incidents` | 📖 Read | 👔 Manager team incident dashboard |
| `get_team_approvals` | 📖 Read | 👔 Manager bulk team approvals |

**Widgets:** `incident-list`, `create-incident`, `update-incident`, `approval-review`, `catalog-list`, `catalog-item`, `cart-summary`, `task-list`, `update-task`, `team-incidents`, `create-change-request`, `create-problem`

**Configuration** (`env/servicenow.env`):
```env
SERVICENOW_INSTANCE_URL=https://yourinstance.service-now.com
```

### Salesforce – CRM

> *Accounts, contacts, opportunities, leads, campaigns, pipeline dashboards, and compliance cases.*

| Tool | Type | Description |
|------|------|-------------|
| `list_accounts` / `get_account_360` | 📖 Read | Account lookup and 360° view (contacts, opps, cases, tasks) |
| `list_contacts` / `create_contact` / `update_contact` | 📖 / ✏️ | Contact directory and CRUD |
| `get_activity_timeline` | 📖 Read | Combined task + event timeline for any record |
| `list_opportunities` | 📖 Read | List opportunities/deals |
| `show_create_opportunity_form` / `create_opportunity` / `update_opportunity` | 🖼️ / ⚙️ | Opportunity create/update widgets |
| `create_opportunity_task` | ✏️ Create | Task linked to opportunity |
| `list_leads` / `get_lead` | 📖 Read | Lead management |
| `show_create_lead_form` / `create_lead` / `update_lead` | 🖼️ / ⚙️ | Lead create/update widgets |
| `convert_lead` | ⚡ Action | Convert lead to account/contact/opportunity |
| `list_campaigns` / `get_campaign` / `add_campaign_member` | 📖 / ✏️ | Campaign tracking |
| `get_pipeline_dashboard` | 📖 Read | Pipeline analytics |
| `list_cases` / `get_case` / `show_compliance_case_form` / `create_case` / `update_case` | 🖼️ + Action | Compliance cases |
| `list_tasks` / `get_task` / `create_task` / `update_task` | 📖 / ✏️ / ⚙️ | Task management |
| `list_approvals` / `approve_reject` | 📖 / ⚡ | Approval queue and decisions |
| `show_create_event_form` / `create_event` / `update_event` | 🖼️ / ⚙️ | Event/meeting widgets |
| `show_create_quote_form` / `create_quote` / `update_quote` | 🖼️ / ⚙️ | Quote widgets |
| `list_products` | 📖 Read | Product catalog |
| `get_forecast` | 📖 Read | Sales forecast / pipeline summary |
| `list_reports` / `run_report` | 📖 Read | Run Salesforce reports |
| `get_team_pipeline_summary` | 📖 Read | 👔 Manager team pipeline by rep |
| `get_team_performance_metrics` | 📖 Read | 👔 Manager sales leaderboard and win rates |

**Widgets:** `crm-account-360`, `crm-pipeline`, `crm-opportunity`, `crm-event`, `compliance-case`, `crm-lead`, `crm-quote`, `lead-pipeline`, `team-pipeline`

**Configuration** (`env/salesforce.env`):
```env
SALESFORCE_DOMAIN=yourorg.my.salesforce.com
```

### Jira – Project Management

> *Issues, sprints, boards, epics, comments, and transitions.*

| Tool | Type | Description |
|------|------|-------------|
| `list_issues` / `get_issue` | 📖 Read | Issue queries with JQL or filters |
| `show_create_issue_form` / `create_issue` / `update_issue` | 🖼️ / ⚙️ | Issue create/update widgets |
| `transition_issue` | ⚡ Action | Move issue to new workflow status |
| `add_comment` | ✏️ Create | Comment on an issue |
| `log_work` | ⚡ Action | Log time on an issue |
| `move_issues_to_sprint` | ⚡ Action | Plan issues into sprints |
| `link_issues` | ✏️ Create | Create Blocks / Relates / Duplicate links |
| `show_create_project_form` / `create_project` / `update_project` | 🖼️ / ⚙️ | Project widgets |
| `list_boards` / `get_board` | 📖 Read | Board management |
| `list_sprints` / `get_sprint` | 📖 Read | Sprint tracking |
| `get_backlog` / `list_epics` / `list_versions` / `create_version` / `update_version` | 📖 / ✏️ | Backlog, epics, releases |
| `get_my_issues` / `list_projects` | 📖 Read | My issues and project list |
| `get_team_workload` | 📖 Read | 👔 Manager team workload distribution |
| `get_team_sprint_health` | 📖 Read | 👔 Manager sprint health across boards |

**Widgets:** `jira-issue`, `create-issue-jira`, `create-project`, `sprint-board`, `team-sprint-health`

**Configuration** (`env/jira.env`):
```env
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_PROJECT_KEY=PROJ  # Optional
```

### SAP SuccessFactors – HR

> *Employee profiles, leave management, pay stubs, org charts, personal data changes, employee transfers, document management, background checks, and employment verification.*

**Auth:** Static API key header (`APIKey`) against SAP SuccessFactors sandbox OData APIs.

| Tool | Type | Description |
|------|------|-------------|
| `list_sandbox_entity_sets` / `query_sandbox_entity` | 📖 Read | Generic OData discovery |
| `get_employee_profile` / `get_leave_balances` / `get_time_off_history` | 📖 Read | Profile and time-off |
| `prepare_book_leave` / `book_leave` | 🖼️ / ⚙️ | Leave booking |
| `prepare_change_personal_data` / `change_personal_data` | 🖼️ / ⚙️ | Personal data changes |
| `get_org_chart` / `get_pay_stubs` / `get_pay_stub_detail` | 📖 Read | Org + pay |
| `prepare_move_employee` / `move_employee` / `update_hierarchy` | 🖼️ / ⚙️ / ✏️ | Employee transfers |
| `trigger_background_check` / `get_background_check_status` | ⚡ / 📖 | Background checks |
| `manage_position` / `request_leave_carryover` | ✏️ / ⚡ | Position + carryover |
| `get_employee_documents` | 📖 Read | List documents |
| `generate_employment_verification` / `generate_employment_reference` | ⚡ Action | Employment letters |

**Widgets:** `sf-employee-profile`, `sf-leave-balance`, `sf-time-off-history`, `sf-leave-booking`, `sf-personal-data-form`, `sf-org-chart`, `sf-payslip-list`, `sf-payslip-detail`, `sf-move-employee`, `sf-document-list`

**Configuration** (`env/sap_sf.env`):
```env
SAP_SF_ODATA_URL=https://sandbox.api.sap.com/successfactorsfoundation/odata/v2
SAP_SF_API_KEY=your_api_key
```

### SAP Ariba – Procurement

> *Invoices, purchase orders, receipts, requisitions, catalog items, supplier management, and approvals.*

**Auth:** Static API key header (`apikey`) against SAP Ariba sandbox (`sandbox.api.sap.com`).

| Tool | Type | Description |
|------|------|-------------|
| `get_invoice_status` / `get_po_status` | 📖 Read | Invoice & PO detail |
| `reject_invoice` / `close_purchase_order` | ⚡ Action | Invoice/PO actions |
| `list_receipts` / `prepare_create_receipt` / `create_receipt` | 📖 / 🖼️ / ⚙️ | Goods receipts |
| `list_requisitions` / `prepare_create_requisition` / `create_requisition` / `update_requisition` | 📖 / 🖼️ / ⚙️ / ✏️ | Requisitions |
| `list_catalog_items` / `order_catalog_item` | 📖 / ⚡ | Catalog |
| `list_suppliers` / `get_supplier` / `update_supplier_address` / `update_supplier_bank` / `register_supplier` | 📖 / ✏️ | Supplier management |
| `transfer_purchase_order` | ⚡ Action | Transfer PO to another supplier |
| `list_approvals` / `approve_reject` | 📖 / ⚡ | Approval queue |

**Widgets:** `ariba-invoice-status`, `ariba-po-status`, `ariba-confirm-action`, `ariba-receipt-list`, `ariba-create-receipt`, `ariba-requisition-list`, `ariba-create-requisition`, `ariba-catalog-search`, `ariba-supplier-list`, `ariba-supplier-profile`, `ariba-supplier-registration`, `ariba-approval-list`

**Configuration** (`env/ariba.env`):
```env
ARIBA_API_URL=https://sandbox.api.sap.com/ariba/api
ARIBA_API_KEY=your_api_key
ARIBA_REALM=yourRealm
```

### Coupa – Procurement (Mocked)

> *Invoices, purchase orders, receipts, requisitions, catalog items, supplier management, and approvals. All tools return mocked data — Coupa does not offer a public sandbox.*

**Auth:** None required (all responses are locally mocked).

**Tools (21):** Mirror the Ariba tool set exactly.

**Widgets:** `coupa-invoice-status`, `coupa-po-status`, `coupa-confirm-action`, `coupa-receipt-list`, `coupa-create-receipt`, `coupa-requisition-list`, `coupa-create-requisition`, `coupa-catalog-search`, `coupa-supplier-list`, `coupa-supplier-profile`, `coupa-supplier-registration`, `coupa-approval-list`

**Configuration** (`env/coupa.env`):
```env
COUPA_INSTANCE_URL=https://yourinstance.coupahost.com
COUPA_MOCK=true
```

---

## 🛠️ Development

```bash
cd mcp_servers

pip install -e ".[dev]"

# Run linter
ruff check src/

# Run type checker
mypy src/

# Run tests
pytest
```

### Adding a New MCP Server

1. Create a new directory under `src/mcp_servers/your_service/`
2. Implement `server.py` with a `build_your_service_server()` function
3. Add tools in `tools.py` and widgets in `resources.py`
4. Register the builder in `cli.py` → `SERVER_BUILDERS`
5. Add settings class and loader in `settings.py`
6. Create `env/your_service.example.env`

---

[← Back to main README](../README.md)
