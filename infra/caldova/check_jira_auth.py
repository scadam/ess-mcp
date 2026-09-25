"""Test supplied Jira OAuth client credentials without logging credentials or records."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import sys

import httpx

from deployment_support import SESSION, Vault, audit, load_server_values
from validate_mcp import probe

MCP_BASE = "https://essmcp-caldova-jira.livelysky-91807d17.eastus2.azurecontainerapps.io"


def classify_oauth_error(payload: dict) -> str:
    code = payload.get("error", "")
    description = str(payload.get("error_description", "")).lower()
    if code in {"unauthorized_client", "unsupported_grant_type"} and "client_credentials" in description:
        return "client_credentials_not_permitted"
    if code in {"invalid_client", "invalid_grant", "unauthorized_client", "unsupported_grant_type", "access_denied", "invalid_scope"}:
        return code
    return "unclassified_oauth_error"


def main() -> None:
    audit("jira-oauth-readonly-check", "started")
    vault = Vault()
    result = {"checkedUtc": datetime.now(timezone.utc).isoformat(), "server": "jira",
              "credentialsStored": True, "grantTested": "client_credentials",
              "backendBaseUrl": load_server_values()["jira"]["JIRA_BASE_URL"], "mcpBaseUrl": MCP_BASE}
    try:
        with httpx.Client(timeout=30) as http:
            response = http.post("https://auth.atlassian.com/oauth/token", json={
                "grant_type": "client_credentials", "audience": "api.atlassian.com",
                "client_id": vault.get("jira-client-id"), "client_secret": vault.get("jira-client-secret"),
            }, headers={"Accept": "application/json"})
            result["tokenEndpointHttp"] = response.status_code
            try:
                payload = response.json()
            except ValueError:
                payload = {}
            token = payload.get("access_token") if response.status_code == 200 else None
            if token:
                result["tokenIssued"] = True
                check = http.get(result["backendBaseUrl"].rstrip("/") + "/rest/api/3/myself",
                                 headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
                result["readOnlyIdentityHttp"] = check.status_code
                try:
                    result["mcp"] = asyncio.run(probe("jira", MCP_BASE, token, True))
                except httpx.HTTPStatusError as exc:
                    result["mcp"] = {"readOnlyCall": "error", "http": exc.response.status_code,
                                     "errorType": "HTTPStatusError"}
                except Exception as exc:
                    result["mcp"] = {"readOnlyCall": "error", "errorType": type(exc).__name__}
            else:
                result["tokenIssued"] = False
                result["oauthError"] = classify_oauth_error(payload)
                # A client ID and secret are not a substitute for a user authorization grant.
                result["nextStep"] = "Complete the app's registered authorization-code flow if this is a Jira 3LO app."
                result["mcp"] = asyncio.run(probe("jira", MCP_BASE))
        (SESSION / "jira-auth-check.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        audit("jira-oauth-readonly-check", "backend_passed" if result.get("mcp", {}).get("readOnlyCall") == "passed" else "backend_authorization_pending")
        print(json.dumps(result))
    finally:
        vault.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Jira auth check failed: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)