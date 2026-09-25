"""Read-only MCP smoke tests. Output contains counts/status only, never tool payloads."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone

import httpx
from dotenv import dotenv_values
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from deployment_support import CATALOG, ROOT, SESSION, SUBSCRIPTION, Vault, audit, az_json, load_server_values
from jira_oauth_callback import user_token

logging.disable(logging.CRITICAL)
READ_TOOLS = {
    "workday": ("get_worker", {}),
    "servicenow": ("list_incidents", {"limit": 1}),
    "salesforce": ("list_tasks", {"limit": 1}),
    "jira": ("list_issues", {"limit": 1}),
    "sap_sf": ("get_employee_profile", {}),
    "ariba": ("list_requisitions", {}),
    "coupa": ("list_requisitions", {}),
}


def docker(*args: str, env=None) -> str:
    result = subprocess.run(["docker", *args], capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=env, timeout=180, check=False)
    if result.returncode:
        raise RuntimeError(f"Docker {args[0]} failed (exit {result.returncode})")
    return result.stdout.strip()


def wait_startup(container: str) -> None:
    follower = subprocess.Popen(["docker", "logs", "--follow", container], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    timer = threading.Timer(90, follower.terminate)
    timer.start()
    ready = False
    try:
        assert follower.stdout is not None
        for line in follower.stdout:
            if "Uvicorn running on" in line:
                ready = True
                break
    finally:
        timer.cancel()
        follower.terminate()
        follower.wait(timeout=10)
    if not ready:
        raise RuntimeError("Container did not emit its startup-ready event")


async def probe(server: str, base: str, token: str = "", functional: bool = False) -> dict:
    report = {"server": server, "health": "unknown", "initialize": False,
              "tools": 0, "resources": 0, "widgetRead": False, "readOnlyCall": "not_run"}
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.get(base + "/healthz")
        if response.status_code != 200 or response.json() != {"status": "ok"}:
            raise RuntimeError(f"Unexpected health response: HTTP {response.status_code}")
    report["health"] = "healthy"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = StreamableHttpTransport(base + f"/{server}/mcp", headers=headers)
    async with Client(transport, timeout=60, init_timeout=30) as client:
        report["initialize"] = True
        tools = await client.list_tools()
        resources = await client.list_resources()
        report["tools"] = len(tools)
        report["resources"] = len(resources)
        if not tools:
            raise RuntimeError("MCP tool discovery returned no tools")
        if resources:
            widget = await client.read_resource(str(resources[0].uri))
            report["widgetRead"] = bool(widget)
        if functional:
            tool_name, arguments = READ_TOOLS[server]
            if tool_name not in {tool.name for tool in tools}:
                raise RuntimeError("Expected read-only test tool missing")
            if server in {"workday", "servicenow", "salesforce", "jira"} and not token:
                report["readOnlyCall"] = "auth_not_available"
            else:
                try:
                    outcome = await client.call_tool(tool_name, arguments, raise_on_error=False)
                    report["readOnlyCall"] = "error" if outcome.is_error else "passed"
                    # Never include business records; classify existing demo fallback separately.
                    report["dataMode"] = {"coupa": "mock", "sap_sf": "sandbox_or_existing_demo_fallback",
                                          "ariba": "sandbox_or_existing_demo_fallback"}.get(server, "live_demo_backend")
                except Exception as exc:
                    report["readOnlyCall"] = "error"
                    report["errorType"] = type(exc).__name__
    return report


def local(image: str) -> None:
    audit("image-local-seven-server-smoke", "started")
    reports = []
    for server, values in load_server_values().items():
        env = dict(os.environ)
        arguments = ["run", "--detach", "--rm", "--cpus", "0.5", "--memory", "1g",
                     "--publish", "127.0.0.1::8080"]
        for key, value in values.items():
            # Discovery does not call backends; local smoke needs no real credentials.
            env[key] = "local-smoke-placeholder" if key in CATALOG[server]["secretEnv"] else value
            arguments.extend(["--env", key])
        arguments.extend([image, server, "--transport", "both", "--host", "0.0.0.0", "--port", "8080"])
        container = docker(*arguments, env=env)
        try:
            wait_startup(container)
            inspection = json.loads(docker("inspect", container))[0]
            port = inspection["NetworkSettings"]["Ports"]["8080/tcp"][0]["HostPort"]
            report = asyncio.run(probe(server, f"http://127.0.0.1:{port}", functional=server == "coupa"))
            report["imageId"] = inspection["Image"]
            reports.append(report)
            print(json.dumps(report), flush=True)
        finally:
            docker("stop", "--time", "5", container)
    payload = {"checkedUtc": datetime.now(timezone.utc).isoformat(), "image": image, "results": reports}
    (SESSION / "image-smoke.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    audit("image-local-seven-server-smoke", "succeeded")


def exchange(url: str, body: dict, auth=None) -> tuple[str, str]:
    if not url.startswith("https://"):
        return "", "unsafe_token_endpoint"
    with httpx.Client(timeout=30) as client:
        response = client.post(url, data=body, auth=auth, headers={"Accept": "application/json"})
    if response.status_code != 200:
        return "", f"oauth_http_{response.status_code}"
    return response.json().get("access_token", ""), "oauth_success"


def backend_token(server: str, vault: Vault) -> tuple[str, str]:
    if server == "jira":
        return user_token(vault), "authorization_code_user_grant"
    if server == "salesforce":
        return exchange("https://microsoft-28a-dev-ed.develop.my.salesforce.com/services/oauth2/token", {
            "grant_type": "client_credentials", "client_id": vault.get("salesforce-client-id"),
            "client_secret": vault.get("salesforce-client-secret")})
    if server == "servicenow":
        body = {"grant_type": "client_credentials", "client_id": vault.get("servicenow-client-id"),
                "client_secret": vault.get("servicenow-client-secret")}
        token, status = exchange("https://dev407392.service-now.com/oauth_token.do", body)
        if token:
            return token, status
        body.update(grant_type="password", username="admin", password=vault.get("servicenow-demo-password"))
        token, status = exchange("https://dev407392.service-now.com/oauth_token.do", body)
        if token:
            return token, "provided_client_password_grant"
        # The supplied auth-code client also permits the password grant in this demo.
        # This is a validation-only token; runtime still receives a client's bearer token.
        body.update(client_id=vault.get("servicenow-auth-code-client-id"),
                    client_secret=vault.get("servicenow-auth-code-client-secret"))
        token, status = exchange("https://dev407392.service-now.com/oauth_token.do", body)
        return token, "auth_code_client_password_grant" if token else status
    if server == "workday":
        values = dotenv_values(ROOT / "demo_agent" / ".env")
        prefix = f"ESS_{server.upper()}"
        url = values.get(prefix + "_OAUTH_TOKEN_URL")
        if url:
            grant = values.get(prefix + "_OAUTH_GRANT_TYPE") or "client_credentials"
            method = values.get(prefix + "_OAUTH_AUTH_METHOD") or "client_secret_post"
            body = {"grant_type": grant}
            for suffix, field in (("SCOPE", "scope"), ("AUDIENCE", "audience"), ("RESOURCE", "resource")):
                value = values.get(prefix + "_OAUTH_" + suffix)
                if value:
                    body[field] = value
            if grant == "refresh_token":
                body["refresh_token"] = values.get(prefix + "_OAUTH_REFRESH_TOKEN") or ""
            client_id = values.get(prefix + "_OAUTH_CLIENT_ID") or ""
            client_secret = values.get(prefix + "_OAUTH_CLIENT_SECRET") or ""
            auth = None
            if method == "client_secret_basic":
                auth = (client_id, client_secret)
            elif method == "client_secret_post":
                body.update(client_id=client_id, client_secret=client_secret)
            elif method != "none":
                return "", "existing_flow_requires_original_agent_identity"
            token, status = exchange(url, body, auth)
            if token:
                return token, status
        static = values.get(prefix + "_TOKEN") or ""
        return static, "existing_local_bearer" if static else "not_configured"
    return "", "not_required_for_demo_mode"


def remote(deployment: str) -> None:
    outputs = az_json("deployment", "sub", "show", "--name", deployment, "--subscription", SUBSCRIPTION)["properties"]["outputs"]
    endpoints = outputs["endpoints"]["value"]
    if len(endpoints) != 7:
        raise RuntimeError("Deployment has not returned all seven endpoints")
    vault = Vault()
    reports = []
    audit("remote-seven-server-smoke", "started")
    try:
        for endpoint in endpoints:
            server = endpoint["cliName"]
            token, auth_status = backend_token(server, vault)
            try:
                report = asyncio.run(probe(server, endpoint["baseUrl"], token, functional=True))
            except Exception as exc:
                report = {"server": server, "health": "unknown", "errorType": type(exc).__name__}
            report.update(mcpUrl=endpoint["mcpUrl"], authStatus=auth_status)
            reports.append(report)
            print(json.dumps(report), flush=True)
    finally:
        vault.close()
    payload = {"checkedUtc": datetime.now(timezone.utc).isoformat(), "deployment": deployment, "results": reports}
    (SESSION / "remote-smoke.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    passed = all(r.get("health") == "healthy" and r.get("initialize") and r.get("tools", 0) for r in reports)
    functional_passed = all(r.get("readOnlyCall") == "passed" for r in reports)
    audit("remote-seven-server-smoke", "all_checks_passed" if passed and functional_passed else "failed")
    if not passed or not functional_passed:
        raise RuntimeError("One or more deployed MCP protocol/backend smoke tests failed; see sanitized report")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["local", "remote"])
    parser.add_argument("--image", default="")
    parser.add_argument("--deployment", default="essmcp-caldova-apps")
    args = parser.parse_args()
    if args.mode == "local":
        local(args.image)
    else:
        remote(args.deployment)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"MCP validation failed: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)