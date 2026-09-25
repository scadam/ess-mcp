"""Live read-only checks for missing, valid and rejected Authorization bearer tokens."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys

import httpx

from deployment_support import SESSION, Vault, audit
from validate_mcp import backend_token

TOOLS = {"workday": ("get_worker", {}), "salesforce": ("list_tasks", {"limit": 1}),
         "servicenow": ("list_incidents", {"limit": 1})}


def rpc_payload(response: httpx.Response) -> dict:
    if "text/event-stream" in response.headers.get("content-type", ""):
        for line in response.text.splitlines():
            if line.startswith("data:"):
                result = json.loads(line[5:].strip())
                if "result" in result or "error" in result:
                    return result
        raise RuntimeError("Missing MCP RPC response")
    return response.json()


def call(server: str, token: str | None) -> dict:
    headers = {"Accept": "application/json, text/event-stream"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request_count = 0
    def check_header(request: httpx.Request) -> None:
        nonlocal request_count
        request_count += 1
        if token is None:
            assert "authorization" not in request.headers, "Unexpected Authorization header"
        else:
            assert request.headers.get("authorization") == f"Bearer {token}", "Caller token changed"

    endpoint = f"https://essmcp-caldova-{server}.livelysky-91807d17.eastus2.azurecontainerapps.io/{server}/mcp"
    with httpx.Client(timeout=60, follow_redirects=False, auth=None, headers=headers,
                      event_hooks={"request": [check_header]}) as client:
        initialized = client.post(endpoint, json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "fallback-verification", "version": "1.0"}}})
        init = rpc_payload(initialized)
        if initialized.status_code != 200 or "result" not in init:
            raise RuntimeError("MCP initialize failed")
        session = initialized.headers.get("mcp-session-id")
        if session:
            client.headers["mcp-session-id"] = session
        client.headers["mcp-protocol-version"] = init["result"]["protocolVersion"]
        notified = client.post(endpoint, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        if notified.status_code not in (200, 202, 204):
            raise RuntimeError("MCP initialized notification failed")
        tool, arguments = TOOLS[server]
        response = client.post(endpoint, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": tool, "arguments": arguments}})
        result = rpc_payload(response)
        text = json.dumps(result).lower()
        failed = bool(response.status_code >= 400 or result.get("error") or result.get("result", {}).get("isError"))
        auth_rejected = response.status_code in (401, 403) or (failed and any(
            marker in text for marker in ("401 unauthorized", "403 forbidden", "invalid_session_id", "invalid token")))
        # Include only statuses; never include tool data, request headers, or tokens.
        return {"http": response.status_code, "toolSucceeded": not failed, "authRejected": auth_rejected,
                "requestCount": request_count, "authorizationHeaderPresent": token is not None}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", choices=list(TOOLS), action="append")
    args = parser.parse_args()
    reports = []
    audit("bearer-first-live-verification", "started")
    vault = Vault()
    try:
        for server in args.server or list(TOOLS):
            token, auth_source = backend_token(server, vault)
            if not token:
                raise RuntimeError(f"Cannot obtain caller token for {server}")
            report = {"server": server, "noHeader": call(server, None),
                      "validBearer": call(server, token),
                      "invalidBearer": call(server, "intentionally-invalid-bearer-precedence-test"),
                      "validBearerSource": auth_source}
            report["passed"] = (report["noHeader"]["toolSucceeded"] and report["validBearer"]["toolSucceeded"]
                                and not report["invalidBearer"]["toolSucceeded"] and report["invalidBearer"]["authRejected"])
            reports.append(report)
            print(json.dumps(report), flush=True)
    finally:
        vault.close()
    payload = {"checkedUtc": datetime.now(timezone.utc).isoformat(), "results": reports,
               "passed": all(report["passed"] for report in reports)}
    (SESSION / "bearer-fallback-smoke.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    audit("bearer-first-live-verification", "passed" if payload["passed"] else "failed")
    if not payload["passed"]:
        raise RuntimeError("Bearer/fallback contract did not pass all live checks")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Fallback verification failed: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)