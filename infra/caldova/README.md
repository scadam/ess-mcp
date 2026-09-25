# Caldova MCP deployment

Isolated deployment of the seven existing ESS MCP servers. It does not alter the original tenant, existing declarative-agent environment, or separate hosted demo agent.

## Target

- Tenant: `17371818-07cb-47f2-9ca3-18f96f0125d7` (Caldova74201480.onmicrosoft.com).
- Subscription: `54b04cf7-73f7-4ea0-aa82-b15694ea8033` (ME-Caldova74201480-scadam-1).
- Resource group: `essmcp-caldova-rg`, East US.
- **Compute: East US 2.** The initial East US environment failed with `ManagedEnvironmentCapacityHeavyUsageError`. The successful replacement is `cae-essmcp-caldova-f61b2`. Supporting resources remain in East US. The failed East US environment is retained for transparent, manual cleanup.
- Registry: `cressmcpcaldovaf61b.azurecr.io` (Basic, admin and anonymous access disabled).
- Vault: `kv-essmcp-caldova-f61b` (RBAC, soft delete and purge protection).
- Logging: `log-essmcp-caldova-f61b`, 30-day retention; Azure Monitor diagnostics, no workspace keys.
- Identity: `id-essmcp-caldova-f61b`, with resource-scoped `AcrPull` and `Key Vault Secrets User`.

The estimated light-demo cost is approximately **US$97/month**, before tax, egress, registry builds/excess storage, and external-service licenses. Seven warm replicas cost more than scale-to-zero; a continuously active workload is approximately US$280/month using the retail rates checked on 2026-09-22. Rates do not imply remaining subscription credits.

## Deployed MCP endpoints

Deployment `essmcp-caldova-fallback` succeeded on 2026-09-22. All seven cloud endpoints passed health, initialization, tool/resource discovery, widget reads and representative read-only calls: **224 tools total**. Workday, Salesforce, and ServiceNow also passed the no-header/valid-bearer/invalid-bearer contract tests.

| MCP server | Tools | Streamable HTTP endpoint | Backend check |
|---|---:|---|---|
| Workday | 46 | [Connect](https://essmcp-caldova-workday.livelysky-91807d17.eastus2.azurecontainerapps.io/workday/mcp) | Read-only call passed against existing demo backend |
| ServiceNow | 39 | [Connect](https://essmcp-caldova-servicenow.livelysky-91807d17.eastus2.azurecontainerapps.io/servicenow/mcp) | Read-only incident call passed; flow caveat below |
| Salesforce | 44 | [Connect](https://essmcp-caldova-salesforce.livelysky-91807d17.eastus2.azurecontainerapps.io/salesforce/mcp) | Read-only task call passed with supplied client credentials |
| Jira | 26 | [Connect](https://essmcp-caldova-jira.livelysky-91807d17.eastus2.azurecontainerapps.io/jira/mcp) | User consent, token renewal and authenticated issue search verified |
| SAP SuccessFactors | 22 | [Connect](https://essmcp-caldova-sap-sf.livelysky-91807d17.eastus2.azurecontainerapps.io/sap_sf/mcp) | Read-only call passed with existing sandbox/demo-fallback behavior |
| Ariba | 21 | [Connect](https://essmcp-caldova-ariba.livelysky-91807d17.eastus2.azurecontainerapps.io/ariba/mcp) | Read-only call passed with existing sandbox/demo-fallback behavior |
| Coupa | 26 | [Connect](https://essmcp-caldova-coupa.livelysky-91807d17.eastus2.azurecontainerapps.io/coupa/mcp) | Read-only mock call passed |

[Open the resource group in Azure](https://portal.azure.com/#@17371818-07cb-47f2-9ca3-18f96f0125d7/resource/subscriptions/54b04cf7-73f7-4ea0-aa82-b15694ea8033/resourceGroups/essmcp-caldova-rg/overview).

## Files

- [main.bicep](main.bicep): subscription-scope foundation and conditional applications, with hard target guards.
- [main.parameters.json](main.parameters.json): non-secret, isolated target configuration.
- [server-catalog.json](server-catalog.json): accepted settings and credential classifications per server.
- [Dockerfile](Dockerfile) and [.dockerignore](.dockerignore): source-only image, non-root runtime, no env files.
- [constraints.txt](constraints.txt): known local dependency versions, preventing an unreviewed FastMCP major upgrade.
- [deployment_support.py](deployment_support.py): safe build staging, in-memory credential seeding, and secret-reference-only runtime parameters.
- [validate_mcp.py](validate_mcp.py): seven-server local/live read-only smoke tests; outputs only status/counts, not tokens or records.
- [verify_fallback.py](verify_fallback.py): live tests of no-header fallback, valid bearer precedence, and invalid bearer rejection for the three updated servers.

## Deployment sequence

1. Use an isolated Azure CLI profile and interactive sign-in. Never send the tenant admin password through chat or scripts.
2. Compile and validate the foundation. Preview with `what-if` before applying it; `deployApps=false` creates no placeholder apps.
3. Stage the build using the helper's `stage` operation. Only source, manifests, constraints, and the scoped Docker build files are staged. Never use the old env-copying Dockerfile or repository root as build context.
4. Build/publish to the new registry with Entra authentication. The first local build could not negotiate TLS to the Python package host; ACR remote build succeeded without disabling TLS verification.
5. Pull and smoke-test the **same immutable digest** locally with the planned 0.5 CPU/1 GiB limits. Each server must pass health, MCP initialization, tools/resources listing, and a widget read.
6. Seed existing SAP/Ariba keys and supplied Salesforce/ServiceNow credentials into the new vault. `seed-fallbacks` copies the verified Workday integration credential set from local configuration and verifies all fallback vault values. Credentials never enter images, source or ARM parameters.
7. Use the helper's `parameters` operation to generate ignored runtime parameters containing the digest and seven configurations. `--preserve-other-images` updates Workday/Salesforce/ServiceNow while keeping the other four existing images; all credentials are vault references.
8. Validate and preview the application stage with **both** base and runtime parameter files, then apply it. Always keep `deployApps=true`, the real immutable image, and the full seven-server configuration on later application redeployments.
9. Verify every cloud revision and live HTTPS/MCP endpoint. Record authenticated backend verification separately from MCP hosting health.

Deployment command examples, measured results, and safe runtime parameters are in the local ignored session linked below. Do not commit that directory.

## Authentication and preserved behavior

| Server | Runtime authentication / data mode |
|---|---|
| Workday | Incoming bearer first; otherwise server-side refresh-token grant using vault-backed client credentials/refresh token and configured default worker. |
| ServiceNow | Incoming bearer first; otherwise server-side OAuth password grant using the verified stored client and demo account. The resolver also supports client_credentials when configured with a working client. |
| Salesforce | Incoming bearer first (`SF_AUTH_MODE=auto`); otherwise server-side client-credentials grant using vault-backed credentials. |
| Jira | Incoming Jira user bearer token; same Jira site, through the required OAuth gateway `https://api.atlassian.com/ex/jira/86d2487a-0a7c-477e-b827-f0b1b2c5a950`. Original tenant configuration is unchanged. |
| SAP SuccessFactors | Existing sandbox API key via vault reference and existing demo fallback behavior. |
| Ariba | Existing sandbox API key via vault reference and existing demo fallback behavior. |
| Coupa | Existing mock mode, not a live Coupa integration. |

The ServiceNow authorization-code redirect remains `https://teams.microsoft.com/api/platform/v1.0/oAuthRedirect`. Connection registrations and M365 app IDs from the old tenant are not portable: optional user-specific Copilot OAuth connections, publishing the declarative agent, and Agent 365 tool registration are separate operations. Local plugin URLs and ServiceNow's fallback-mode auth were updated; original Azure tenant deployments and local backend environment files remain unchanged.

ServiceNow's supplied dedicated client-credentials application returned HTTP 401. The separately supplied OAuth application issued tokens through the password grant; this is now the explicitly requested server fallback. No ServiceNow OAuth app, policy or password was changed. Workday uses a refresh-token grant, not client_credentials. A rejected incoming bearer remains a backend error and does not switch identities.

**Requested demo exposure:** calls without a bearer run as the stored account, including any enabled write tools. Keep service privileges restricted and protect ingress before production/broader use. Jira is unchanged. The three updated apps use digest `sha256:84765596d4567a193bd776d0796fb6eaf62515ecdff6805cc9aed5a9985cec51`; the other four retain `sha256:0a3c8d848c70b000e7ffc5d106c0c85c8c39b7ea2f83d48bd5e6ef1719213ccc`.

Jira credentials supplied later were stored as `jira-client-id`, `jira-client-secret`, `jira-demo-username`, and `jira-demo-password` in the new vault, not injected into the public MCP application. The app is the existing **Copilot** OAuth app, app ID `9a2a3755-c789-45e0-836b-dc27b91edb45`. A client-credentials token alone had zero accessible Jira sites. After the user completed MFA, an authorization-code grant with `read:jira-work read:jira-user offline_access` successfully authorized the existing site and passed identity/issue-search checks. The existing registered Teams callback was not modified.

The access/rotating-refresh pair is stored atomically in the `jira-user-oauth` vault secret. [jira_oauth_callback.py](jira_oauth_callback.py) contains the one-use state-validated callback receiver and token refresh helper. Run one local validation client at a time to avoid concurrent refresh rotations. This is not a public-server service-account fallback: MCP clients still supply their own valid bearer token. The read-only validation grant does not authorize write/admin tools; those require the client's appropriate OAuth scopes and Jira permissions. No write operations were tested.

The new Jira deployment uses the documented `api.atlassian.com/ex/jira/{cloudId}` route. Its previous site web hostname returned 401 for OAuth tokens. Only `JIRA_BASE_URL` changed, not the underlying Jira site, image, or original tenant's environment files. The original [check_jira_auth.py](check_jira_auth.py) is retained as a diagnostic of the **client-credentials** flow; use [validate_mcp.py](validate_mcp.py) for the working consented-user flow.

Single replicas retain in-memory MCP sessions while running. Sessions and mocked mutations reset on restart; this is not a production HA deployment. Legacy SSE transport is exposed by the existing application, but deployment verification targets Streamable HTTP.

## Local execution evidence

- [Deployment session](../../.copilot-azure/sessions/f61b6075-b781-474c-8014-215acf111dd1/context.json)
- [Deployment result](../../.copilot-azure/sessions/f61b6075-b781-474c-8014-215acf111dd1/deploy-result.json)
- [Exact-image smoke tests](../../.copilot-azure/sessions/f61b6075-b781-474c-8014-215acf111dd1/image-smoke.json)
- [Runtime parameters](../../.copilot-azure/sessions/f61b6075-b781-474c-8014-215acf111dd1/runtime.parameters.json)

These are local ignored files, not portable source artifacts. Infrastructure uses the latest stable resource API versions advertised by the target providers. The local Bicep type cache lacks Key Vault `2026-05-15` metadata, producing two `BCP081` warnings; actual Azure ARM validation succeeded. A generic scanner also incorrectly rejected `enablePurgeProtection=true` and assumed a specific Dockerfile filename; both original scanner failures and evidence-backed exceptions are retained in the session. Security settings were not weakened to satisfy those checks.