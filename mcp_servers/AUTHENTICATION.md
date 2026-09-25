# Bearer-first authentication

Workday, Salesforce and ServiceNow prefer a nonempty `Authorization: Bearer` token supplied by the MCP caller. The token is passed to that backend and is **never saved in the server's shared fallback cache**. A backend rejection is propagated; the server does not retry a supplied caller token using a more privileged stored account.

Without a bearer token, the server obtains a backend token using its configured credentials. Only these server-owned tokens are cached, with renewal before expiry. Credential values belong in the deployment's secret store and secret references, never the image or checked-in configuration.

| Server | Fallback mechanism | Required configuration |
|---|---|---|
| Workday | `refresh_token` grant; existing integration refresh token, not OAuth client-credentials grant | `WORKDAY_OAUTH_TOKEN_URL`, `WORKDAY_OAUTH_CLIENT_ID`, `WORKDAY_OAUTH_CLIENT_SECRET`, `WORKDAY_OAUTH_REFRESH_TOKEN`; optional default worker ID/search and client auth method |
| Salesforce | `client_credentials` grant, when `SF_AUTH_MODE=auto` (default) | `SALESFORCE_DOMAIN`, `SF_CLIENT_ID`, `SF_CLIENT_SECRET` |
| ServiceNow | Configurable `client_credentials` or `password` grant | `SERVICENOW_INSTANCE_URL`, `SERVICENOW_OAUTH_CLIENT_ID`, `SERVICENOW_OAUTH_CLIENT_SECRET`; set `SERVICENOW_OAUTH_GRANT_TYPE=password` and username/password fields when that is the supported demo flow |

ServiceNow's default token endpoint is the configured instance plus `/oauth_token.do`; `SERVICENOW_OAUTH_TOKEN_URL` can override it with HTTPS. Client authentication supports `client_secret_post` (default) or `client_secret_basic`. `SERVICENOW_OAUTH_SCOPE` is optional. Its server-owned cache is invalidated by credential/configuration changes; a single async lock prevents concurrent renewal storms.

Salesforce retains `oauth_bearer` as an explicitly restrictive option, but the Caldova demo uses `auto`. Even the legacy `client_credentials` mode now respects a supplied bearer token. Workday fallback renewal is serialized as well.

**Demo exposure:** callers who omit a bearer token execute with the stored account's permissions, including any enabled write tools. This is the requested demo behavior, not per-user authorization or a production security boundary. Use appropriately restricted service accounts and protect ingress before broader exposure.

Jira is unchanged: it requires a caller's consented user token. SAP SuccessFactors and Ariba retain their sandbox API-key/demo-fallback behavior, and Coupa remains mocked.

Regression tests: [tests/test_bearer_fallback.py](tests/test_bearer_fallback.py). These tests use fake credentials and mocked HTTP only. Live deployment tests exercise read-only tools with no header, a valid caller bearer, and a deliberately invalid caller bearer; no mutating business operations are used for validation.