<p align="center">
  <h1 align="center">🏢 ESS-MCP</h1>
  <p align="center">
    <strong>Enterprise Self-Service MCP Servers</strong><br/>
    Modular <a href="https://modelcontextprotocol.io/">Model Context Protocol</a> servers for Workday, ServiceNow, Salesforce, and Jira
  </p>
  <p align="center">
    <a href="#-quick-start"><img src="https://img.shields.io/badge/Quick_Start-blue?style=for-the-badge" alt="Quick Start"/></a>
    <a href="#%EF%B8%8F-azure-deployment"><img src="https://img.shields.io/badge/Deploy_to_Azure-0078D4?style=for-the-badge&logo=microsoftazure&logoColor=white" alt="Deploy to Azure"/></a>
    <a href="#-mcp-servers"><img src="https://img.shields.io/badge/MCP_Servers-4-green?style=for-the-badge" alt="MCP Servers"/></a>
  </p>
</p>

---

## 📖 Overview

**ESS-MCP** is a suite of [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) servers that connect AI assistants to enterprise systems. Each server exposes tools and interactive UI widgets for a specific platform:

| Server | Platform | Tools | Widgets | Use Cases |
|--------|----------|-------|---------|-----------|
| **Workday** | HR / HCM | 17 | 7 | Employee profiles, leave booking, compensation, org charts |
| **ServiceNow** | ITSM | 28 | 10 | Incidents, change requests, service catalog, approvals |
| **Salesforce** | CRM | 28 | 5 | Accounts, opportunities, pipeline, leads, campaigns |
| **Jira** | Project Management | 20 | 4 | Issues, sprints, boards, epics, project tracking |

Servers can be deployed **individually**, in **any combination**, or **all together** — both locally and on Azure Container Apps with a single command.

---

## 🖼️ Widget Screenshots

ESS-MCP includes 23 interactive HTML+Skybridge widgets that render directly in AI assistant UIs.

<table>
  <tr>
    <td align="center"><strong>Workday – Worker Profile</strong></td>
    <td align="center"><strong>Workday – Org Chart</strong></td>
  </tr>
  <tr>
    <td><img src="docs/images/widget-worker-profile.png" width="400" alt="Worker Profile Widget"/></td>
    <td><img src="docs/images/widget-org-chart.png" width="400" alt="Org Chart Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>ServiceNow – Incident List</strong></td>
    <td align="center"><strong>Salesforce – Sales Pipeline</strong></td>
  </tr>
  <tr>
    <td><img src="docs/images/widget-incident-list.png" width="400" alt="Incident List Widget"/></td>
    <td><img src="docs/images/widget-crm-pipeline.png" width="400" alt="CRM Pipeline Widget"/></td>
  </tr>
  <tr>
    <td align="center" colspan="2"><strong>Jira – Issue Detail</strong></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><img src="docs/images/widget-jira-issue.png" width="400" alt="Jira Issue Widget"/></td>
  </tr>
</table>

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      AI Assistant / Client                  │
│               (ChatGPT, Copilot, Claude, etc.)              │
└──────────────┬──────────────────────────────────┬───────────┘
               │  MCP (SSE / Streamable HTTP)     │
               ▼                                  ▼
┌──────────────────────────────────────────────────────────────┐
│                    ESS-MCP Gateway (:8080)                   │
│                                                              │
│  /workday/mcp   /servicenow/mcp  /salesforce/mcp  /jira/mcp │
│  /workday/sse   /servicenow/sse  /salesforce/sse  /jira/sse │
│  /healthz                                                    │
│                                                              │
│  ┌───────────┐ ┌──────────────┐ ┌────────────┐ ┌──────────┐ │
│  │  Workday  │ │  ServiceNow  │ │ Salesforce  │ │   Jira   │ │
│  │  Server   │ │   Server     │ │   Server    │ │  Server  │ │
│  └─────┬─────┘ └──────┬───────┘ └──────┬─────┘ └────┬─────┘ │
│        │ Bearer Token  │ OAuth CC       │ OAuth CC   │ API Key│
└────────┼───────────────┼────────────────┼────────────┼───────┘
         ▼               ▼                ▼            ▼
   Workday API    ServiceNow API   Salesforce API  Jira Cloud API
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
- **Docker** (for containerised deployment)
- **Azure CLI** (for Azure deployment)

### Local Development

```bash
# Clone the repository
git clone https://github.com/scadam/ess-mcp.git
cd ess-mcp/mcp_servers

# Install in development mode
pip install -e ".[dev]"

# Copy and configure environment files
cp env/workday.example.env env/workday.env
cp env/servicenow.example.env env/servicenow.env
cp env/salesforce.example.env env/salesforce.env
cp env/jira.example.env env/jira.env
# Edit each .env file with your credentials

# Run a single server (stdio – for direct MCP client connection)
python -m mcp_servers.cli workday --transport stdio

# Run a single server (HTTP)
python -m mcp_servers.cli jira --transport http --port 8080

# Run all servers (HTTP + SSE)
python -m mcp_servers.cli all --transport both --port 8080
```

### Docker

```bash
cd mcp_servers

# Build the image
docker build -t ess-mcp .

# Run all servers
docker run -p 8080:8080 ess-mcp

# Run specific servers with env vars
docker run -p 8080:8080 \
  -e JIRA_BASE_URL=https://yourorg.atlassian.net \
  -e JIRA_API_TOKEN=your_token \
  ess-mcp python -m mcp_servers.cli jira --transport both --host 0.0.0.0 --port 8080
```

### Verify

```bash
# Health check
curl http://localhost:8080/healthz
# → {"status": "ok"}

# MCP endpoint (Streamable HTTP)
curl -X POST http://localhost:8080/workday/mcp \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"tools/list","id":1}'
```

---

## ☁️ Azure Deployment

Deploy to **Azure Container Apps** with a single command. The script provisions all required infrastructure from scratch — you only need an Azure subscription.

### What Gets Created

| Resource | Purpose |
|----------|---------|
| **Resource Group** | Logical container for all resources |
| **Azure Container Registry** | Hosts the Docker image |
| **Log Analytics Workspace** | Centralised logging and monitoring |
| **Container App Environment** | Managed Kubernetes-based hosting |
| **Container App(s)** | One per selected MCP server |

### Single-Click Deploy

```bash
# Deploy ALL servers (default)
./deploy/deploy.sh

# Deploy a single server
./deploy/deploy.sh --servers workday

# Deploy specific servers
./deploy/deploy.sh --servers workday,jira

# Deploy with custom settings
./deploy/deploy.sh \
  --servers workday,servicenow \
  --location westeurope \
  --name myessmcp \
  --env-file deploy/.env
```

### Deployment Options

| Option | Default | Description |
|--------|---------|-------------|
| `-s, --servers` | `all` | Comma-separated: `workday`, `servicenow`, `salesforce`, `jira`, or `all` |
| `-l, --location` | `eastus` | Azure region |
| `-n, --name` | `essmcp` | Base name for resources (3–16 chars) |
| `-t, --tag` | `latest` | Docker image tag |
| `--cpu` | `0.5` | CPU cores per container |
| `--memory` | `1Gi` | Memory per container |
| `--min-replicas` | `0` | Minimum replica count (0 = scale to zero) |
| `--max-replicas` | `3` | Maximum replica count |
| `-e, --env-file` | — | Path to `.env` file with service credentials |
| `--resource-group` | `{name}-rg` | Use an existing resource group |
| `--subscription` | — | Azure subscription ID or name |
| `--dry-run` | — | Preview what would be deployed |

### Configure Credentials

```bash
# Copy the example environment file
cp deploy/.env.example deploy/.env

# Edit with your service credentials
# Only fill in variables for the servers you're deploying
nano deploy/.env

# Deploy with credentials
./deploy/deploy.sh --servers workday,jira --env-file deploy/.env
```

### Post-Deployment

After deployment, the script prints each server's endpoints:

```
━━━ Deployment Summary ━━━

  workday:
    MCP:    https://essmcp-workday.azurecontainerapps.io/workday/mcp
    SSE:    https://essmcp-workday.azurecontainerapps.io/workday/sse
    Health: https://essmcp-workday.azurecontainerapps.io/healthz

  jira:
    MCP:    https://essmcp-jira.azurecontainerapps.io/jira/mcp
    SSE:    https://essmcp-jira.azurecontainerapps.io/jira/sse
    Health: https://essmcp-jira.azurecontainerapps.io/healthz
```

```bash
# View logs
az containerapp logs show --name essmcp-workday --resource-group essmcp-rg

# Clean up all resources
az group delete --name essmcp-rg --yes --no-wait
```

---

## 🔧 MCP Servers

### Workday – HR / Employee Self-Service

> *Employee profiles, leave management, compensation, org hierarchy, learning, and team calendar.*

**Tools:**

| Tool | Description |
|------|-------------|
| `get_worker` | Fetch current worker profile |
| `get_leave_balances` | View PTO / leave balances |
| `get_direct_reports` | List direct reports |
| `get_inbox_tasks` | Fetch pending approval tasks |
| `get_learning_assignments` | View learning initiatives |
| `get_pay_slips` | Access payroll information |
| `get_time_off_entries` | Historical time-off records |
| `prepare_request_leave` / `book_leave` | Submit leave requests |
| `prepare_change_business_title` / `change_business_title` | Update job title |
| `search_learning_content` | Search the learning library |
| `get_compensation` | Salary and bonus information |
| `get_benefits` | Benefits enrollment and coverage |
| `get_job_history` | Career progression history |
| `get_org_chart` | Organization hierarchy |
| `get_worker_documents` | HR documents |
| `get_team_calendar` | Team availability calendar |

**Widgets:** `worker-profile`, `leave-booking`, `compensation-summary`, `org-chart`, `team-calendar`, `learning-assignments`, `change-business-title`

**Configuration** (`env/workday.env`):
```env
AAD_APP_CLIENT_ID=your_client_id
AAD_APP_TENANT_ID=your_tenant_id
WORKDAY_TOKEN_URL=https://your-workday.com/oauth/token
WORKDAY_WORKERS_API_URL=https://your-workday.com/api/v1/workers
WORKDAY_CLIENT_CREDENTIALS=your_credentials
WORKDAY_CLIENT_SECRET=your_secret
WORKDAY_REFRESH_TOKEN=your_refresh_token
```

---

### ServiceNow – IT Service Management

> *Incidents, change requests, problems, service catalog, knowledge base, approvals, and CMDB.*

**Tools:**

| Tool | Description |
|------|-------------|
| `list_incidents` / `get_incident` | View incidents |
| `create_incident` / `update_incident` | Manage incidents |
| `list_tasks` / `get_task` / `update_task` | Task management |
| `list_approvals` / `approve_reject` | Approval workflows |
| `list_catalog_items` / `order_catalog_item` | Service catalog |
| `add_to_cart` / `get_cart` / `checkout_cart` | Shopping cart |
| `list_change_requests` / `create_change_request` | Change management |
| `search_knowledge` / `get_knowledge_article` | Knowledge base |
| `list_problems` / `create_problem` | Problem management |
| `get_cmdb_ci` / `list_cmdb_cis` | CMDB queries |
| `show_create_incident_form` | Interactive incident form |

**Widgets:** `incident-list`, `create-incident`, `update-incident`, `approval-review`, `catalog-list`, `catalog-item`, `cart-summary`, `create-project`, `task-list`, `update-task`

**Configuration** (`env/servicenow.env`):
```env
SERVICENOW_INSTANCE_URL=https://yourinstance.service-now.com
SERVICENOW_CLIENT_ID=your_client_id
SERVICENOW_CLIENT_SECRET=your_client_secret
```

---

### Salesforce – CRM

> *Accounts, contacts, opportunities, leads, campaigns, pipeline dashboards, and compliance cases.*

**Tools:**

| Tool | Description |
|------|-------------|
| `list_accounts` / `get_account_360` | Account management |
| `list_contacts` | Contact directory |
| `list_opportunities` / `create_opportunity` | Opportunity pipeline |
| `list_leads` / `create_lead` / `convert_lead` | Lead management |
| `list_campaigns` / `get_campaign` | Campaign tracking |
| `get_pipeline_dashboard` | Pipeline analytics |
| `list_cases` / `create_case` | Compliance cases |
| `list_tasks` / `update_task` | Task management |
| `list_approvals` / `approve_reject` | Approval workflows |
| `create_quote` | Quote generation |
| `get_forecast` / `list_reports` | Reporting |

**Widgets:** `crm-account-360`, `crm-opportunity`, `crm-event`, `crm-pipeline`, `compliance-case`

**Configuration** (`env/salesforce.env`):
```env
SALESFORCE_DOMAIN=yourorg.my.salesforce.com
SALESFORCE_CLIENT_ID=your_connected_app_client_id
SALESFORCE_CLIENT_SECRET=your_connected_app_client_secret
```

---

### Jira – Project Management

> *Issues, sprints, boards, epics, comments, and transitions.*

**Tools:**

| Tool | Description |
|------|-------------|
| `list_issues` / `get_issue` | Issue queries |
| `create_issue` / `update_issue` | Issue management |
| `transition_issue` | Workflow transitions |
| `add_comment` | Add comments |
| `create_project` | Project creation |
| `list_boards` / `get_board` | Board management |
| `list_sprints` / `get_sprint` | Sprint tracking |
| `get_backlog` | Backlog views |

**Widgets:** `jira-issue`, `create-issue`, `create-project`

**Configuration** (`env/jira.env`):
```env
JIRA_BASE_URL=https://yourorg.atlassian.net
JIRA_EMAIL=you@example.com
JIRA_API_TOKEN=your_api_token
JIRA_PROJECT_KEY=PROJ  # Optional
```

---

## 🔌 Transport Modes

| Mode | Command | Use Case |
|------|---------|----------|
| **stdio** | `--transport stdio` | Direct MCP client integration (single server only) |
| **SSE** | `--transport sse` | Server-Sent Events for streaming |
| **HTTP** | `--transport http` | Streamable HTTP for request/response |
| **Both** | `--transport both` | SSE + HTTP simultaneously (default for Docker) |

**Endpoints** (when running all servers with `--transport both`):

| Path | Transport |
|------|-----------|
| `/{server}/mcp` | Streamable HTTP |
| `/{server}/sse` | Server-Sent Events |
| `/healthz` | Health check |

---

## 🔐 Authentication

ESS-MCP uses **OAuth 2.0 bearer token passthrough** — the MCP server extracts the bearer token from each incoming request's `Authorization` header and forwards it to the target SaaS API. No tokens are stored or validated by the MCP layer.

```
Client → Authorization: Bearer <token> → MCP Server → Bearer <token> → SaaS API
```

Each backend has its own auth flow:

| Server | Auth Method |
|--------|-------------|
| Workday | OAuth 2.0 refresh token + Microsoft Entra |
| ServiceNow | OAuth 2.0 Client Credentials |
| Salesforce | OAuth 2.0 Client Credentials (Connected App) |
| Jira | API Token (Bearer) |

---

## 🧩 Project Structure

```
ess-mcp/
├── README.md
├── deploy/                         # Azure deployment
│   ├── deploy.sh                   # Single-click deploy script
│   ├── main.bicep                  # Azure Bicep IaC template
│   └── .env.example                # Credential template
├── docs/
│   └── images/                     # Widget screenshots
└── mcp_servers/
    ├── Dockerfile                  # Multi-stage Docker build
    ├── pyproject.toml              # Python project config
    ├── env/                        # Service env templates
    │   ├── workday.example.env
    │   ├── servicenow.example.env
    │   ├── salesforce.example.env
    │   └── jira.example.env
    └── src/mcp_servers/
        ├── cli.py                  # CLI entry point
        ├── settings.py             # Pydantic config loader
        ├── logging.py              # Structured logging
        ├── auth/                   # Bearer token extraction
        ├── http/                   # HTTP client + retry
        ├── workday/                # Workday MCP server
        ├── servicenow/             # ServiceNow MCP server
        ├── salesforce/             # Salesforce MCP server
        ├── jira/                   # Jira MCP server
        └── ui/widget/              # 23 HTML+Skybridge widgets
```

---

## 🛠️ Development

```bash
cd mcp_servers

# Install with dev dependencies
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

## 📄 License

This project is licensed under the [MIT License](LICENSE).
