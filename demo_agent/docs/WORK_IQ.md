# Work IQ production MCP contract

Verified on 2026-09-22 against [the tool reference](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/mcp/tool-reference), [permission reference](https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/permissions), the endpoint's OAuth challenge, and the Caldova Work IQ service principal.

| Setting | Current value |
|---|---|
| Endpoint | https://workiq.svc.cloud.microsoft/mcp |
| Resource application ID | `fdcc1f02-fc51-4226-8753-f668596af7f7` |
| Application ID URI | `api://workiq.svc.cloud.microsoft` |
| Delegated permission | `WorkIQAgent.Ask` |
| SDK scope | `api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask` |
| OAuth protected-resource metadata | https://workiq.svc.cloud.microsoft/.well-known/oauth-protected-resource/mcp |

The live metadata advertises `fdcc1f02-fc51-4226-8753-f668596af7f7/WorkIQAgent.Ask`, the equivalent app-ID-qualified scope. The unqualified scope in [../ToolingManifest.json](../ToolingManifest.json) is paired with the explicit audience for A365 permission provisioning. `workiq` is the local manifest key, not a claim that a new catalog registration exists.

Do not carry forward the retired preview `mcp_TeamsServerV1`, `McpServers.Teams.All`, shared preview audience, or `mcp_graph_chat_*` tools. Old generated configuration belongs to the previous tenant and must not be rerun against Caldova. The new isolated A365 setup must read the current tooling manifest and verify blueprint grants and inheritance after the CLI completes.

## Authentication and policy

- Work IQ uses **delegated user context**, not an app-only token. An agent blueprint registration alone does not establish a signed-in user, consent or license/billing eligibility.
- The SDK adapter defaults to the explicitly configured `OBO` user authorization handler. If an agentic-user handler is selected, verify Work IQ support, tenant consent and that user's eligibility independently; never silently substitute identities.
- Never send the control-plane API token directly to Work IQ. It has a different audience. Use a consented on-behalf-of exchange or a verified SDK user-token exchange.
- Work IQ tenant policy is an additional boundary. Writes are denied by default. Do not change policy, retry a denied operation, or fall back to Graph/email to bypass that denial.
- Normal replies and task reports stay in the originating SDK conversation. The separate cross-chat helper is not automatically invoked by the host and requires explicit effect approval from its caller.

## Tool contract

Discover live tools and argument schemas rather than guessing from preview names. The current reference documents `ask`, `list_agents`, `fetch`, `call_function`, `search_paths`, `get_schema`, `create_entity`, `update_entity`, `delete_entity`, and `do_action`; additional tools such as binary fetch depend on what the live endpoint advertises.

Entity paths are relative resource paths. `jsonBody` is a JSON-encoded **string**, not an object. Entity results contain `statusCode` and `data`, often under MCP `structuredContent`. Never report a mutation as successful merely because the MCP request returned: require a confirmed 2xx entity outcome and expected identifier.

`WorkIQAgent.Ask` can enable both read and write operations. Treat model-selected `ask` and entity mutations as potentially consequential, subject to exact confirmation and server policy. Tenant policy is not weakened by this configuration update.

## Verification status

Public OAuth metadata and the actual Caldova service-principal scope were read successfully. Runtime payload and failure-handling contracts have offline regression tests. No Work IQ tenant permission grant, user-token exchange, live tool invocation or write is implied by those checks; these remain deployment/integration verification steps.