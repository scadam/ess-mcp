# ☁️ Deployment & OAuth Setup

[← Back to main README](../README.md) · See also: [MCP Servers](mcp-servers.md) · [Declarative Agent](declarative-agent.md)

This page covers two things:

1. **Deploying ESS-MCP servers to Azure Container Apps** with a single command
2. **Registering OAuth 2.0 clients** in each SaaS platform so AI assistants (e.g. Microsoft 365 Copilot) can obtain bearer tokens on behalf of users

---

## ☁️ Azure Deployment

Deploy to **Azure Container Apps** with a single command. The script provisions all required infrastructure from scratch and uses **ACR remote build** — no local Docker installation required. You only need an Azure subscription and the Azure CLI.

### What Gets Created

| Resource | Purpose |
|----------|---------|
| **Resource Group** | Logical container for all resources |
| **Azure Container Registry** | Builds and hosts the container image (remote build — no local Docker needed) |
| **Log Analytics Workspace** | Centralised logging and monitoring |
| **Container App Environment** | Managed Kubernetes-based hosting |
| **Container App(s)** | One per selected MCP server |

### Single-Click Deploy

```bash
# Deploy ALL servers (default)
./deploy.sh

# Deploy a single server
./deploy.sh --servers workday

# Deploy specific servers
./deploy.sh --servers workday,jira

# Deploy with custom settings
./deploy.sh \
  --servers workday,servicenow \
  --location westeurope \
  --name myessmcp \
  --env-file deploy/.env
```

### Deployment Options

| Option | Default | Description |
|--------|---------|-------------|
| `-s, --servers` | `all` | Comma-separated: `workday`, `servicenow`, `salesforce`, `jira`, `sap_sf`, `ariba`, `coupa`, or `all` |
| `-l, --location` | `eastus` | Azure region |
| `-n, --name` | `essmcp` | Base name for resources (3–16 chars) |
| `-t, --tag` | `latest` | Container image tag |
| `--cpu` | `0.5` | CPU cores per container |
| `--memory` | `1Gi` | Memory per container |
| `--min-replicas` | `0` | Minimum replica count (0 = scale to zero) |
| `--max-replicas` | `3` | Maximum replica count |
| `-e, --env-file` | — | Path to `.env` file with service configuration |
| `--resource-group` | `{name}-rg` | Use an existing resource group |
| `--subscription` | — | Azure subscription ID or name |
| `--dry-run` | — | Preview what would be deployed |

### Configure Environment

```bash
cp deploy/.env.example deploy/.env
# Edit with your service URLs. Only fill in variables for the servers you're deploying.
./deploy.sh --servers workday,jira --env-file deploy/.env
```

### Post-Deployment

After deployment, the script prints each server's endpoints:

```
━━━ Deployment Summary ━━━

  workday:
    MCP:    https://essmcp-workday.azurecontainerapps.io/workday/mcp
    SSE:    https://essmcp-workday.azurecontainerapps.io/workday/sse
    Health: https://essmcp-workday.azurecontainerapps.io/healthz
```

```bash
# View logs
az containerapp logs show --name essmcp-workday --resource-group essmcp-rg

# Clean up all resources
az group delete --name essmcp-rg --yes --no-wait
```

---

## 🔐 OAuth Client Setup per SaaS Platform

ESS-MCP uses **OAuth 2.0 bearer token passthrough** — the MCP server forwards the bearer token from incoming requests directly to the target SaaS API. Each SaaS platform requires an OAuth 2.0 client registration so the AI assistant can obtain those tokens on behalf of users.

Below are step-by-step guides for creating OAuth clients with the **Authorization Code flow** for each platform.

<details>
<summary><strong>Workday – OAuth 2.0 Client (Authorization Code Grant)</strong></summary>

Workday uses **API Clients for Integrations** registered through the Workday tenant.

1. **Sign in** to your Workday tenant as a Security Administrator.
2. Navigate to **Register API Client for Integrations** (search in the Workday search bar).
3. Fill in the registration form:
   - **Client Name:** `ESS-MCP Copilot`
   - **Grant Type:** **Authorization Code Grant**
   - **Access Token Type:** `Bearer`
   - **Redirect URI:** e.g. `https://teams.microsoft.com/api/platform/v1.0/oAuthRedirect`
   - **Scope:** `Staffing`, `Time Off and Leave`, `Compensation`, `Learning`, `Tenant Non-Configurable`
4. Click **OK** to register. **Copy the Client ID and Client Secret** — the secret is only shown once.
5. Navigate to **View API Clients** to verify your registration.
6. **Create an Integration System User (ISU)** and assign it to a security group with the required domain permissions.
7. **Configure Authentication Policy** — add a rule to allow OAuth 2.0 authentication for your ISU.

**Token Endpoints:**
```
Authorization: https://your-tenant.workday.com/authorize
Token:         https://your-tenant.workday.com/token
```

</details>

<details>
<summary><strong>ServiceNow – OAuth 2.0 Application Registry</strong></summary>

ServiceNow uses the **Application Registry** to create OAuth clients.

1. **Sign in** to your ServiceNow instance as an admin.
2. Navigate to **System OAuth → Application Registry**.
3. Click **New** → **Create an OAuth API endpoint for external clients**.
4. Fill in the form:
   - **Name:** `ESS-MCP Copilot`
   - **Client Secret:** Click **Generate** — copy immediately.
   - **Redirect URL:** `https://teams.microsoft.com/api/platform/v1.0/oAuthRedirect`
   - **Token Lifespan:** `1800` seconds
   - **Refresh Token Lifespan:** `8640000` seconds
   - **Active:** ✅
5. Click **Submit**.
6. Optional: enable scopes under **System OAuth → OAuth Scopes**.

**Token Endpoints:**
```
Authorization: https://yourinstance.service-now.com/oauth_auth.do
Token:         https://yourinstance.service-now.com/oauth_token.do
```

</details>

<details>
<summary><strong>Salesforce – Connected App (OAuth 2.0)</strong></summary>

Salesforce uses **Connected Apps** for OAuth 2.0 integration.

1. **Sign in** to Salesforce as a System Administrator.
2. Navigate to **Setup → Apps → App Manager**.
3. Click **New Connected App**.
4. Under **API (Enable OAuth Settings)**:
   - **Callback URL:** `https://teams.microsoft.com/api/platform/v1.0/oAuthRedirect`
   - **Selected OAuth Scopes:** `Full access (full)`, `Perform requests at any time (refresh_token, offline_access)`
   - ✅ Require Secret for Web Server Flow
   - ✅ Require Secret for Refresh Token Flow
   - ✅ Enable Authorization Code and Credentials Flow
5. **Save**, wait 2–10 minutes, then **Manage Consumer Details** to copy Consumer Key and Consumer Secret.

**Token Endpoints:**
```
Authorization: https://login.salesforce.com/services/oauth2/authorize
Token:         https://login.salesforce.com/services/oauth2/token
```
For sandboxes use `test.salesforce.com`.

</details>

<details>
<summary><strong>Jira Cloud – OAuth 2.0 App (3LO)</strong></summary>

Jira Cloud uses the **Atlassian Developer Console** for OAuth 2.0 (3-legged OAuth).

1. Go to [developer.atlassian.com/console/myapps](https://developer.atlassian.com/console/myapps/).
2. **Create** → **OAuth 2.0 integration** → name it `ESS-MCP Copilot`.
3. **Authorization** → Add OAuth 2.0 (3LO) with callback `https://teams.microsoft.com/api/platform/v1.0/oAuthRedirect`.
4. **Permissions** → add: `read:jira-work`, `write:jira-work`, `read:jira-user`, `manage:jira-project`, `manage:jira-configuration`.
5. **Settings** to find your **Client ID** and **Secret**.

**Token Endpoints:**
```
Authorization: https://auth.atlassian.com/authorize
Token:         https://auth.atlassian.com/oauth/token
```

**Important:** Jira Cloud OAuth 2.0 tokens require a `cloud_id` for API calls:
```
GET https://api.atlassian.com/oauth/token/accessible-resources
→ Returns cloud IDs for authorized sites
API Base: https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/
```

</details>

<details>
<summary><strong>SAP SuccessFactors / SAP Ariba — API Key headers</strong></summary>

The bundled SAP SuccessFactors and SAP Ariba servers target the public SAP sandbox (`sandbox.api.sap.com`) using a static API key header rather than OAuth. For production SAP tenants, use Workday-style OAuth or your SAP Cloud Identity Authentication setup and pass the bearer token in via the normal MCP authorization header.

</details>

> Once OAuth clients exist on each SaaS platform, register them in **Teams Developer Center** as described in **[declarative-agent.md → Registering OAuth in Teams Developer Center](declarative-agent.md#registering-oauth-in-teams-developer-center)**.

---

[← Back to main README](../README.md)
