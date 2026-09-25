# Group Functions Autopilot

## Manifests and artwork

The current [A365 manifest](manifest/manifest.json) and
[Teams manifest](appPackage/manifest.json) use Group Functions Autopilot branding
and the [new compass icon](static/autopilot-icon.svg). See the
[branding and publication guide](docs/AUTOPILOT_BRANDING.md) for exact paths,
icon dimensions and the final packaging order. The expired tenant's local
credentials and packages have been removed; its cloud resources were not touched.

## Compliance Partner demonstration

The revised [Compliance Partner scenario](docs/COMPLIANCE_PARTNER_DEMO.md) is a
cross-border client-data disclosure investigation for a syndicated refinancing,
not a simple policy lookup. The [case-resolution skill](skills/compliance-case-resolution.md)
defines evidence gathering, private requester clarification and confirmed
Salesforce closure. Scenario and skill definitions are not live deployment proof;
the document lists the notification, identity and end-to-end acceptance gates.

This Python host combines conversation-scoped memory, approved tool work and an
authenticated control plane. Its intended hosted integrations include:

- Microsoft Entra Agent ID and an Agent Identity Blueprint
- Agent 365 / Foundry metadata for registry, map, Purview, and Defender views
- AI Gateway routing for governed MCP tool access
- OAuth token acquisition for Workday and ServiceNow bearer-token passthrough
- OpenTelemetry spans/events for full MCP tool-call observation

The web host supports Workday, ServiceNow, Salesforce and Coupa MCP connections.
The compliance workflow requires separately verified Agent 365 email delivery,
Work IQ evidence and private Teams communication; do not infer live capability
from a skill document or offline test.

## Runtime Flow

```text
Skill prompt
  -> GitHub Models or Azure OpenAI
  -> approved Workday, ServiceNow, Salesforce or Coupa tool call
  -> OAuth token provider
  -> AI Gateway MCP endpoint
  -> configured Caldova MCP server
  -> SaaS API
```

The MCP server still uses bearer-token passthrough. The important change is
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

## Skills

Every run is a GitHub Copilot SDK session hosted by `demo_agent.web`; there is no separate CLI loop.
Skills include:

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
python demo_agent/scripts/oauth-bootstrap.py servicenow --code <callback-code> --container-app <verified-current-container-app>
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