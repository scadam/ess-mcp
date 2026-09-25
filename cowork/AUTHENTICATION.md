# Caldova MCP endpoints and authentication

Verified on 2026-09-22 after the requested bearer-first update. All seven servers passed health, MCP initialization, tools/resources discovery, widget reads, and a representative read-only tool call. **Workday, Salesforce, and ServiceNow additionally passed live calls with no Authorization header, with a valid caller token, and with an invalid caller token.** No-header calls return data using stored-account OAuth; invalid supplied tokens return 401 rather than switching identities.

## Verified flows and current runtime behavior

| Server | How the successful test acquired access | What the deployed MCP server does | Client-credentials-only/no-token data access? |
|---|---|---|---|
| Jira | Initial interactive user authorization-code consent (`read:jira-work read:jira-user offline_access`), then verified refresh-token rotation | Requires caller's Jira user bearer token; uses Atlassian's OAuth API gateway | No. An app-only token was issued but had no site access. |
| Workday | Server-side **refresh-token** grant with stored client authentication | Caller bearer first; otherwise renews a server token using Key Vault-backed credentials and resolves the configured default worker | **No-header data access works.** This is a refresh-token grant, not a `client_credentials` grant. |
| Salesforce | Server-side **client-credentials grant** | `SF_AUTH_MODE=auto`; caller bearer first, otherwise cached server-token acquisition using Key Vault-backed client credentials | **No-header data access works.** |
| ServiceNow | Stored OAuth client plus demo username/password using its enabled **password grant**; dedicated client-credentials application still returned 401 | Caller bearer first; otherwise server-side cached OAuth acquisition. Resolver supports both configured grant types | **No-header data access works** using the verified password grant. This is not a claim that the dedicated client-credentials flow works. |
| SAP SuccessFactors | Existing sandbox API key | Uses configured API key; existing demo fallback remains | Not an OAuth client-credentials flow. Sandbox/fallback result, not proof of a live enterprise tenant. |
| SAP Ariba | Existing sandbox API key | Uses configured API key; existing demo fallback remains | Not an OAuth client-credentials flow. |
| Coupa | None | Existing mock data | No credentials required; explicitly mocked. |

An authorization-code **flow belongs to the client/identity provider**. The MCP server accepts the resulting bearer token; it does not perform an interactive exchange just because a header was passed. Workday, Salesforce, and ServiceNow can use valid access tokens acquired through a suitably configured authorization-code connection, but those interactive flows were not all exercised during deployment. Jira needs initial consent, not a new interactive login for every tool call; renewal can use its refresh token until revoked/expired.

The verified read-only Jira grant does not authorize all 26 tools: write/admin tools need the appropriate OAuth scopes and Jira permissions. No mutating backend tests were run for any server.

## Plugin configuration

- Cowork and declarative-agent Workday, Salesforce, and ServiceNow declare `None` to use the requested server-side fallback without an interactive sign-in. No-token read-only execution is verified, not just tool discovery. Clients that do send a valid bearer token retain caller-specific access.
- Cowork Jira uses `OAuthPluginVault` but still has its existing registration placeholder. Register a real connection in Caldova and use that reference; a validation token in Azure Key Vault does not create a Microsoft 365 OAuth connection.
- ServiceNow's old-tenant OAuth reference was removed from the fallback-mode plugin definitions. An optional per-user OAuth connection would need its own real new-tenant registration, not the old reference.
- The declarative-agent Jira plugin still declares `None`; it needs client-side OAuth configuration before use. Jira has no server-account fallback and is unchanged by the three-server update.
- SAP SuccessFactors/Ariba use sandbox-key/demo behavior and Coupa is mocked, so their existing `None` client declarations do not represent OAuth client-credentials flows.
- URL changes do **not** change the agent action list, Graph connector, application IDs, versions, registrations, or already installed Microsoft 365 packages.

No OAuth reference IDs or credentials were invented. **Demo exposure:** no-header requests to Workday, Salesforce, and ServiceNow execute with the stored account's permissions, including any enabled write tools. The fallback is not a per-user authorization boundary. No mutating tools were used during verification; protect ingress and restrict stored-account privileges before broader use.

## Canonical new Streamable HTTP endpoints

| Server | Endpoint |
|---|---|
| Workday | https://essmcp-caldova-workday.livelysky-91807d17.eastus2.azurecontainerapps.io/workday/mcp |
| ServiceNow | https://essmcp-caldova-servicenow.livelysky-91807d17.eastus2.azurecontainerapps.io/servicenow/mcp |
| Salesforce | https://essmcp-caldova-salesforce.livelysky-91807d17.eastus2.azurecontainerapps.io/salesforce/mcp |
| Jira | https://essmcp-caldova-jira.livelysky-91807d17.eastus2.azurecontainerapps.io/jira/mcp |
| SAP SuccessFactors | https://essmcp-caldova-sap-sf.livelysky-91807d17.eastus2.azurecontainerapps.io/sap_sf/mcp |
| Ariba | https://essmcp-caldova-ariba.livelysky-91807d17.eastus2.azurecontainerapps.io/ariba/mcp |
| Coupa | https://essmcp-caldova-coupa.livelysky-91807d17.eastus2.azurecontainerapps.io/coupa/mcp |