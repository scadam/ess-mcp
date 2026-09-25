"""Read-only ServiceNow credential diagnostics; no credentials or records are emitted."""
import asyncio
import json

import httpx

from deployment_support import Vault, SESSION
from validate_mcp import probe


def main():
    vault = Vault()
    reports = []
    usable_token = ""
    successful_flow = ""
    try:
        password = vault.get("servicenow-demo-password")
        pairs = [
            ("provided-client-credentials", vault.get("servicenow-client-id"), vault.get("servicenow-client-secret")),
            ("provided-authorization-code-client", vault.get("servicenow-auth-code-client-id"), vault.get("servicenow-auth-code-client-secret")),
        ]
        with httpx.Client(timeout=30) as http:
            basic = http.get("https://dev407392.service-now.com/api/now/table/incident",
                             params={"sysparm_limit": 1, "sysparm_fields": "sys_id"},
                             auth=("admin", password), headers={"Accept": "application/json"})
            reports.append({"check": "basic-api-credentials", "http": basic.status_code})
            for label, client_id, client_secret in pairs:
                for grant in ("client_credentials", "password"):
                    body = {"grant_type": grant, "client_id": client_id, "client_secret": client_secret}
                    if grant == "password":
                        body.update(username="admin", password=password)
                    response = http.post("https://dev407392.service-now.com/oauth_token.do", data=body)
                    try:
                        data = response.json()
                    except ValueError:
                        data = {}
                    error = data.get("error")
                    safe_error = error if error in {"invalid_client", "invalid_grant", "unsupported_grant_type", "access_denied", "server_error"} else "unclassified"
                    item = {"client": label, "grant": grant, "http": response.status_code}
                    if response.status_code != 200:
                        item["error"] = safe_error
                    reports.append(item)
                    if response.status_code == 200 and data.get("access_token"):
                        usable_token = data["access_token"]
                        successful_flow = f"{label}/{grant}"
                        break
                if usable_token:
                    break
        result = {"servicenow": reports, "successfulFlow": successful_flow or None}
        if usable_token:
            result["mcp"] = asyncio.run(probe("servicenow", "https://essmcp-caldova-servicenow.livelysky-91807d17.eastus2.azurecontainerapps.io", usable_token, True))
        (SESSION / "servicenow-auth-check.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))
    finally:
        vault.close()


if __name__ == "__main__":
    main()