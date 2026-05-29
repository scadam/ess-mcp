# Agent 365, Entra Agent ID, and AI Gateway Setup

This demo agent is now shaped as a hosted autonomous agent instance for Workday
and ServiceNow. The code can run locally, but the governance surfaces only light
up after the tenant-side Agent ID, Agent 365, Foundry, and gateway resources are
created.

## Target Architecture

```text
Hosted ESS agent instance
  | Entra Agent Identity metadata and token assertions
  v
Workday/ServiceNow OAuth token endpoint
  | bearer token for target SaaS API
  v
Foundry / Agent 365 / APIM AI Gateway MCP endpoint
  | policy, rate limits, logging, tool governance
  v
ESS-MCP Workday and ServiceNow servers
  | bearer-token passthrough
  v
Workday / ServiceNow APIs
```

## 1. Create the Agent Identity Blueprint

Use the Microsoft Entra Agent ID guided setup from Microsoft Learn. Create one
Blueprint for this agent type, for example `ESS Workday ServiceNow Agent`, and
one Agent Identity instance for this hosted demo run.

Required output values for `.env`:

| Environment variable | Source |
| --- | --- |
| `AZURE_TENANT_ID` | Tenant ID |
| `ENTRA_AGENT_BLUEPRINT_CLIENT_ID` | Blueprint application `appId` |
| `ENTRA_AGENT_BLUEPRINT_OBJECT_ID` | Blueprint application object ID |
| `ENTRA_AGENT_BLUEPRINT_PRINCIPAL_ID` | Blueprint principal service principal object ID |
| `ENTRA_AGENT_IDENTITY_OBJECT_ID` | Agent Identity service principal object ID |
| `ENTRA_AGENT_IDENTITY_CLIENT_ID` | Agent Identity client ID, if issued by your tenant/API version |

Important setup details:

- Include the `OData-Version: 4.0` header for Agent ID Graph calls.
- Create the BlueprintPrincipal explicitly; it is not created automatically.
- Configure credentials on the Blueprint, not on individual Agent Identities.
- Set the Blueprint identifier URI to `api://{blueprint-app-id}` and create the
  `access_agent` scope so token acquisition can resolve cleanly.
- Use managed identity federation for Azure-hosted runs and client secret or a
  local AgentID sidecar only for development.

## 2. Register the Hosted Agent in Agent 365 / Foundry

Create or publish the agent in Microsoft Foundry / Agent 365 so the instance is
anchored in the tenant's agent registry and can appear in Microsoft 365 admin
center, Purview, Defender, and the agent map.

Set these values for runtime correlation:

```env
ESS_AGENT_DISPLAY_NAME=ESS Workday ServiceNow Agent
AZURE_FOUNDRY_PROJECT_ENDPOINT=https://<project>.services.ai.azure.com/api/projects/<project>
AZURE_FOUNDRY_AGENT_ID=<foundry-agent-id>
```

Install Agent 365 observability packages when they are available in your Python
environment:

```powershell
pip install microsoft-agents-a365-observability-core opentelemetry-sdk opentelemetry-exporter-otlp
```

The runtime emits OpenTelemetry spans when OpenTelemetry is installed. Set your
tenant collector or Agent 365 ingestion endpoint with:

```env
OTEL_SERVICE_NAME=ess-demo-agent
OTEL_EXPORTER_OTLP_ENDPOINT=https://<otel-collector-or-a365-ingestion-endpoint>
OTEL_EXPORTER_OTLP_HEADERS=Authorization=Bearer <collector-token>
ESS_OBSERVE_TOOL_PAYLOADS=true
ESS_OBSERVE_TOOL_PAYLOAD_MAX_CHARS=0
```

Each Workday and ServiceNow MCP tool invocation emits a dedicated
`agent.tool_call.observed` span/event containing the Agent Identity, Blueprint,
Foundry agent ID, server name, tool name, tool-call ID, full JSON arguments,
full response payload, duration, success/error state, payload sizes, and SHA-256
hashes. `ESS_OBSERVE_TOOL_PAYLOAD_MAX_CHARS=0` means the app does not truncate
the observed payload before export; downstream telemetry systems may still apply
their own storage limits or redaction policies.

## 3. Put MCP Behind the AI Gateway

Preferred runtime configuration:

```env
ESS_AI_GATEWAY_BASE_URL=https://<gateway-host>/ess-mcp
```

The agent resolves:

```text
https://<gateway-host>/ess-mcp/workday/mcp
https://<gateway-host>/ess-mcp/servicenow/mcp
```

Per-server overrides are also supported:

```env
ESS_WORKDAY_AI_GATEWAY_MCP_URL=https://<gateway-host>/ess-mcp/workday/mcp
ESS_SERVICENOW_AI_GATEWAY_MCP_URL=https://<gateway-host>/ess-mcp/servicenow/mcp
```

Use [gateway/apim-mcp-policy.xml](gateway/apim-mcp-policy.xml) as the policy
template for an APIM-backed AI Gateway. Attach policies such as:

- `rate-limit-by-key` keyed by `X-Agent-Identity-Id`
- required agent identity and Blueprint headers
- request/response logging to App Insights or Event Hub
- backend routing to the Workday and ServiceNow MCP container apps
- optional subscription key or managed identity checks for gateway callers

The gateway must forward the `Authorization: Bearer <saas-token>` header to the
ESS-MCP server because ESS-MCP intentionally uses bearer-token passthrough.

## 4. Configure Workday and ServiceNow OAuth

The hosted path uses OAuth instead of static bearer tokens. The agent should
never keep Workday or ServiceNow access tokens in files. Use one of these hosted
patterns instead:

1. App-only confidential client: the agent exchanges a client credential or
  Agent Identity-backed client assertion for a short-lived SaaS access token.
2. Delegated bootstrap: an admin or service account completes authorization code
  consent once, the resulting refresh token is stored in Container Apps secrets
  or Key Vault, and the agent uses `grant_type=refresh_token` to mint fresh
  short-lived access tokens at runtime.
3. Token exchange: Workday or ServiceNow trusts an Entra Agent Identity subject
  token and exchanges it for a SaaS access token.

For OAuth providers that accept a JWT client assertion:

```env
ESS_WORKDAY_OAUTH_AUTH_METHOD=agent_client_assertion
ESS_SERVICENOW_OAUTH_AUTH_METHOD=agent_client_assertion
ENTRA_AGENT_ID_SDK_TOKEN_URL=http://localhost:8911/token
```

For OAuth providers that support token exchange:

```env
ESS_WORKDAY_OAUTH_AUTH_METHOD=token_exchange
ESS_SERVICENOW_OAUTH_AUTH_METHOD=token_exchange
```

For delegated authorization-code bootstrap:

```env
ESS_WORKDAY_OAUTH_GRANT_TYPE=refresh_token
ESS_WORKDAY_OAUTH_REFRESH_TOKEN=<stored as Container Apps secret or Key Vault secret>
ESS_SERVICENOW_OAUTH_GRANT_TYPE=refresh_token
ESS_SERVICENOW_OAUTH_REFRESH_TOKEN=<stored as Container Apps secret or Key Vault secret>
```

Do not store access tokens in `.env`. Static `ESS_WORKDAY_TOKEN` and
`ESS_SERVICENOW_TOKEN` are only emergency local-development fallbacks and should
not be configured on the hosted Container App.

## 5. Run

```powershell
python -m demo_agent.web
```

Open `http://localhost:8091/control-plane` to run Workday/ServiceNow scenarios.

## Verification Checklist

- The Entra admin center shows the Agent Identity Blueprint and Agent Identity.
- Microsoft 365 admin center shows the published/registered agent instance.
- Foundry shows the agent with connected governed MCP tools.
- Gateway logs show requests keyed by `X-Agent-Identity-Id` and
  `X-Agent-Blueprint-Client-Id`.
- Defender/Purview telemetry includes tool-call traces with Workday and
  ServiceNow tool names.
- ESS-MCP receives `Authorization: Bearer <token>` and does not store the token.
## 6. Purview Information Protection + DSPM-for-AI

The agent honours Microsoft Purview sensitivity labels on every MCP tool result and registers itself with Defender XDR Agents and DSPM-for-AI. This is what makes hosted runs visible to compliance officers and the AI Hub.

### 6.1 Runtime behaviour

- Every tool result is passed through demo_agent/purview.py (`PurviewLabelClient` + `LabelPolicy`).
- When the agent's managed identity has been granted `InformationProtectionPolicy.Read.All` on Microsoft Graph, real tenant labels are pulled from `/v1.0/security/informationProtection/sensitivityLabels` and cached for 15 minutes. Otherwise a deterministic heuristic catalogue (Public / Confidential / Highly Confidential) classifies content based on SSN, phone, email, salary, and named keywords.
- The label is then evaluated against `demo_agent/purview-policy.yaml`. The first matching rule wins:
  - `allow`  - content forwarded unchanged.
  - `redact` - regex patterns (SSN/phone/email/salary by default) are replaced with `[REDACTED:<reason>]`.
  - `block`  - the entire payload is replaced with `[BLOCKED BY PURVIEW POLICY: ...]` so the LLM cannot reason over it.
- Telemetry attributes `microsoft.purview.sensitivity_label_id`, `microsoft.purview.sensitivity_label_name`, `microsoft.purview.sensitivity_label_priority`, and `agent.tool_result.policy_applied` are attached to every OTel + Agent 365 span and surfaced as `policy_event` SSE events to the control-plane UI.

### 6.2 Environment switches

```env
# Master switch (default true). Set to false to bypass classification entirely.
PURVIEW_ENABLED=true

# Source of the Microsoft Graph token used to fetch tenant labels.
# 'managed_identity' (default) acquires via DefaultAzureCredential.
# 'none' forces the heuristic catalogue (useful for local dev).
PURVIEW_GRAPH_TOKEN_SOURCE=managed_identity

# Whether to capture user prompts on InvokeAgentScope/InferenceScope (default true).
A365_CAPTURE_PROMPTS=true
```n
### 6.3 Onboarding to DSPM-for-AI / AI Hub

Run the bundled PowerShell script once per tenant - it grants the Graph permission, registers the agent in DSPM-for-AI (`/security/dataSecurityAndGovernance/copilotAndAiApps`), and adds it to the Defender XDR Agents inventory (`/security/aiContent/agents`):

```powershell
./demo_agent/scripts/setup-purview-dspm.ps1 `+
  -TenantId $env:AZURE_TENANT_ID `+
  -AgentManagedIdentityObjectId 92983f30-a70d-4c86-8228-3d0b7f82488f `+
  -AgentClientId 9380b56a-4aa9-46cf-b634-a6e29f536224 `+
  -AgentEndpoint "https://ess-demo-agent.wittysand-460bf1d9.eastus.azurecontainerapps.io" `+
  -BlueprintAppId 3f028e66-44cf-4cee-81ee-03ade7717884
```n
The script is idempotent. Sign in as a user with Compliance Administrator + Application Administrator roles when the Graph consent prompt appears.

### 6.4 Verification

- `GET /api/identity` returns `observability.purview.enabled = true` and `observability.purview.configured = true`.
- Container App logs show JSON entries containing `microsoft.purview.sensitivity_label_id` for every tool call.
- Purview portal -> DSPM for AI -> AI applications: the agent appears within ~20 minutes.
- Defender XDR -> Assets -> Agents: the agent appears with `agentPlatform = AzureContainerApps`.
- Run the bundled `hiring-pipeline` or `incident-triage` skills from Teams; you should see `policy_event` notifications in the control-plane SSE stream when synthetic Confidential or Highly Confidential payloads are emitted.

