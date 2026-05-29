# Demo Agent - Hosted Agent 365 + ESS-MCP

This demo is now a Workday and ServiceNow focused autonomous agent designed to
run as a hosted agent instance with:

- Microsoft Entra Agent ID and an Agent Identity Blueprint
- Agent 365 / Foundry metadata for registry, map, Purview, and Defender views
- AI Gateway routing for governed MCP tool access
- OAuth token acquisition for Workday and ServiceNow bearer-token passthrough
- OpenTelemetry spans/events for full MCP tool-call observation

The old four-system static-token demo path has been narrowed intentionally.
Salesforce and Jira are no longer connected by `demo_agent`.

## Runtime Flow

```text
Skill prompt
  -> GitHub Models or Azure OpenAI
  -> tool call: workday__* or servicenow__*
  -> OAuth token provider
  -> AI Gateway MCP endpoint
  -> ESS-MCP Workday/ServiceNow server
  -> SaaS API
```

The ESS-MCP server still uses bearer-token passthrough. The important change is
that this demo agent can now acquire those bearer tokens at runtime instead of
requiring fixed `ESS_<SERVER>_TOKEN` values.

## Setup

1. Create the Entra Agent Identity Blueprint and Agent Identity instance.
2. Register or publish the hosted agent in Agent 365 / Foundry.
3. Put the Workday and ServiceNow MCP endpoints behind the AI Gateway.
4. Configure Workday and ServiceNow OAuth clients to trust the hosted agent's
   identity assertion or token exchange flow.
5. Copy `.env.example` to `.env` and fill in the values.

Detailed setup notes are in [AGENT365_SETUP.md](AGENT365_SETUP.md). The APIM
policy template for the MCP gateway is in
[gateway/apim-mcp-policy.xml](gateway/apim-mcp-policy.xml).

## Run the Web UI

```powershell
python -m demo_agent.web
```

Open:

- `http://localhost:8091/` for the simple run UI
- `http://localhost:8091/control-plane` for the operations dashboard

## Run the CLI

```powershell
python -m demo_agent.agent team-review
```

Available skills:

| Skill | Focus |
| --- | --- |
| `team-review` | Workday people signals plus ServiceNow health and approvals |
| `incident-triage` | ServiceNow incident/SLA triage with Workday availability context |
| `onboarding-audit` | Workday onboarding and ServiceNow provisioning readiness |
| `sprint-readiness` | Workday capacity and ServiceNow operational blockers |
| `hiring-pipeline` | Workday hiring context and ServiceNow provisioning |
| `cross-system-overview` | Employee self-service view across Workday and ServiceNow |

## Token Modes

Preferred hosted modes:

- `agent_client_assertion` - the agent gets an Agent Identity-backed JWT from
  the Entra AgentID SDK sidecar and uses it as an OAuth client assertion.
- `token_exchange` - the agent gets an Agent Identity-backed subject token and
  exchanges it with the Workday or ServiceNow OAuth endpoint.

Emergency local development fallback only:

- `ESS_WORKDAY_TOKEN`
- `ESS_SERVICENOW_TOKEN`

Do not configure static access tokens on the hosted Container App. For a hosted
demo, use `agent_client_assertion`, `token_exchange`, or the authorization-code
bootstrap flow that stores refresh tokens in Container Apps secrets or Key Vault.

## Key Environment Variables

| Variable | Purpose |
| --- | --- |
| `ENTRA_AGENT_BLUEPRINT_CLIENT_ID` | Agent Identity Blueprint app ID |
| `ENTRA_AGENT_IDENTITY_OBJECT_ID` | Per-instance Agent Identity service principal ID |
| `ENTRA_AGENT_ID_SDK_TOKEN_URL` | Microsoft Entra SDK for AgentID sidecar/token broker endpoint |
| `AZURE_FOUNDRY_PROJECT_ENDPOINT` | Foundry project used for hosted agent correlation |
| `AZURE_FOUNDRY_AGENT_ID` | Foundry agent ID for registry/telemetry correlation |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Agent 365/tenant collector endpoint for exported spans |
| `ESS_OBSERVE_TOOL_PAYLOADS` | Emits full tool arguments and responses when `true` |
| `ESS_OBSERVE_TOOL_PAYLOAD_MAX_CHARS` | `0` means the app does not truncate observed payloads |
| `ESS_AI_GATEWAY_BASE_URL` | Base URL for governed Workday/ServiceNow MCP routes |
| `ESS_WORKDAY_OAUTH_*` | Workday OAuth token acquisition settings |
| `ESS_SERVICENOW_OAUTH_*` | ServiceNow OAuth token acquisition settings |

See [.env.example](.env.example) for the complete template.

To bootstrap an authorization-code flow without putting access tokens in files:

```powershell
python demo_agent/scripts/oauth-bootstrap.py servicenow --print-url
python demo_agent/scripts/oauth-bootstrap.py servicenow --code <callback-code> --container-app ess-demo-agent
```

Repeat for `workday` after the Workday OAuth client and redirect URI are
configured.

## Verification

Before using this as a hosted demo, confirm:

- Entra admin center shows the Blueprint and Agent Identity.
- Microsoft 365 admin center shows the agent in the registry.
- Foundry shows the agent and connected governed MCP tools.
- AI Gateway logs include `X-Agent-Identity-Id` and
  `X-Agent-Blueprint-Client-Id`.
- Defender/Purview traces include model calls and Workday/ServiceNow tool calls.
- Each tool call has an `agent.tool_call.observed` span/event with server, tool,
  call ID, full arguments, full response, duration, success/error, payload sizes,
  payload hashes, Agent Identity, Blueprint, and Foundry agent metadata.