"""Scoped deployment helpers. Never emit credentials or business-record payloads."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
INFRA = ROOT / "infra" / "caldova"
SESSION = ROOT / ".copilot-azure" / "sessions" / "f61b6075-b781-474c-8014-215acf111dd1"
SUBSCRIPTION = "54b04cf7-73f7-4ea0-aa82-b15694ea8033"
TENANT = "17371818-07cb-47f2-9ca3-18f96f0125d7"
VAULT = "https://kv-essmcp-caldova-f61b.vault.azure.net"
REGISTRY = "cressmcpcaldovaf61b.azurecr.io"
PROFILE = Path(os.environ["LOCALAPPDATA"]) / "ess-mcp" / "azure-caldova74201480"
CATALOG = json.loads((INFRA / "server-catalog.json").read_text(encoding="utf-8"))
FALLBACK_SECRET_BINDINGS = {
    "workday": {"WORKDAY_OAUTH_CLIENT_ID": "workday-oauth-client-id", "WORKDAY_OAUTH_CLIENT_SECRET": "workday-oauth-client-secret", "WORKDAY_OAUTH_REFRESH_TOKEN": "workday-oauth-refresh-token"},
    "salesforce": {"SF_CLIENT_ID": "salesforce-client-id", "SF_CLIENT_SECRET": "salesforce-client-secret"},
    "servicenow": {"SERVICENOW_OAUTH_CLIENT_ID": "servicenow-auth-code-client-id", "SERVICENOW_OAUTH_CLIENT_SECRET": "servicenow-auth-code-client-secret", "SERVICENOW_OAUTH_PASSWORD": "servicenow-demo-password"},
}


def audit(operation: str, status: str) -> None:
    record = {"utc": datetime.now(timezone.utc).isoformat(), "operation": operation, "status": status}
    with (SESSION / "deploy-audit.log").open("a", encoding="utf-8") as target:
        target.write(json.dumps(record) + "\n")


def az_json(*arguments: str):
    env = dict(os.environ, AZURE_CONFIG_DIR=str(PROFILE))
    az = shutil.which("az")
    if not az:
        raise RuntimeError("Azure CLI is unavailable")
    result = subprocess.run([az, *arguments, "--output", "json", "--only-show-errors"],
                            env=env, capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode:
        # CLI errors can contain request payloads; never forward stderr.
        raise RuntimeError(f"Azure CLI operation failed with exit {result.returncode}")
    return json.loads(result.stdout)


def guard_target() -> None:
    account = az_json("account", "show")
    if account["id"] != SUBSCRIPTION or account["tenantId"] != TENANT:
        raise RuntimeError("Tenant/subscription mismatch; operation blocked")


def stage() -> None:
    """Copy only application source/manifests into a fresh temporary build context."""
    target = Path(tempfile.mkdtemp(prefix="essmcp-caldova-build-"))
    source = ROOT / "mcp_servers"
    for filename in ("pyproject.toml", "README.md"):
        shutil.copy2(source / filename, target / filename)
    for filename in ("Dockerfile", ".dockerignore", "constraints.txt"):
        shutil.copy2(INFRA / filename, target / filename)
    shutil.copytree(source / "src", target / "src", ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", "*.pyo", ".env*", "*.env", "*.pem", "*.key", "*.pfx", "*.p12", "*.log"))
    for item in target.rglob("*"):
        if item.is_symlink():
            raise RuntimeError("Build context cannot contain symlinks")
        if item.is_file() and (item.suffix.lower() in {".env", ".pem", ".key", ".pfx", ".p12"}
                               or item.name.startswith(".env")):
            raise RuntimeError("Build context contains a prohibited file")
    audit("stage-secret-free-context", "succeeded")
    print(target)


def load_server_values() -> dict[str, dict[str, str]]:
    result = {}
    for server, catalog in CATALOG.items():
        env_path = ROOT / "mcp_servers" / "env" / f"{server}.env"
        values = {key: value for key, value in dotenv_values(env_path).items() if value is not None}
        allowed = set(catalog["plainEnv"] + catalog["secretEnv"])
        result[server] = {key: value for key, value in values.items() if key in allowed and value}
    result["servicenow"]["SERVICENOW_INSTANCE_URL"] = "https://dev407392.service-now.com"
    result["servicenow"].update(SERVICENOW_OAUTH_TOKEN_URL="https://dev407392.service-now.com/oauth_token.do",
                               SERVICENOW_OAUTH_GRANT_TYPE="password", SERVICENOW_OAUTH_AUTH_METHOD="client_secret_post",
                               SERVICENOW_OAUTH_USERNAME="admin")
    result["salesforce"]["SALESFORCE_DOMAIN"] = "microsoft-28a-dev-ed.develop.my.salesforce.com"
    result["salesforce"]["SF_AUTH_MODE"] = "auto"
    # Only Key Vault references supply fallback credentials, never stale local SaaS secrets.
    for server, bindings in FALLBACK_SECRET_BINDINGS.items():
        for key in bindings:
            result[server].pop(key, None)
    # Verified Jira 3LO tokens use Atlassian's API gateway, not the site's web hostname.
    # This changes only the new-tenant deployment; original env files are not modified.
    result["jira"]["JIRA_BASE_URL"] = "https://api.atlassian.com/ex/jira/86d2487a-0a7c-477e-b827-f0b1b2c5a950"
    return result


class Vault:
    def __init__(self):
        guard_target()
        token = az_json("account", "get-access-token", "--resource", "https://vault.azure.net",
                        "--subscription", SUBSCRIPTION)["accessToken"]
        self.client = httpx.Client(timeout=30, headers={"Authorization": f"Bearer {token}"})

    def close(self):
        self.client.close()

    def get(self, name: str) -> str:
        response = self.client.get(f"{VAULT}/secrets/{name}", params={"api-version": "7.4"})
        if response.status_code != 200:
            raise RuntimeError(f"Key Vault read {name} failed: HTTP {response.status_code}")
        return response.json()["value"]

    def put(self, name: str, value: str) -> None:
        if not re.fullmatch(r"[a-z0-9-]+", name) or not value:
            raise ValueError("Invalid secret name or empty value")
        existing = self.client.get(f"{VAULT}/secrets/{name}", params={"api-version": "7.4"})
        if existing.status_code == 200 and existing.json()["value"] == value:
            return
        if existing.status_code not in (200, 404):
            raise RuntimeError(f"Key Vault precheck {name} failed: HTTP {existing.status_code}")
        response = self.client.put(f"{VAULT}/secrets/{name}", params={"api-version": "7.4"},
                                   json={"value": value, "attributes": {"enabled": True}})
        if response.status_code != 200:
            raise RuntimeError(f"Key Vault write {name} failed: HTTP {response.status_code}")


SUPPLIED_SECRET_ENV = {
    "salesforce-client-id": "CALDOVA_SF_CLIENT_ID",
    "salesforce-client-secret": "CALDOVA_SF_CLIENT_SECRET",
    "salesforce-security-token": "CALDOVA_SF_SECURITY_TOKEN",
    "servicenow-client-id": "CALDOVA_SN_CLIENT_ID",
    "servicenow-client-secret": "CALDOVA_SN_CLIENT_SECRET",
    "servicenow-auth-code-client-id": "CALDOVA_SN_AUTH_CLIENT_ID",
    "servicenow-auth-code-client-secret": "CALDOVA_SN_AUTH_CLIENT_SECRET",
    "servicenow-demo-password": "CALDOVA_SN_PASSWORD",
}


def seed_jira() -> None:
    """Add separately supplied Jira credentials without requiring other secrets again."""
    values = {"jira-client-id": os.environ.get("CALDOVA_JIRA_CLIENT_ID", ""),
              "jira-client-secret": os.environ.get("CALDOVA_JIRA_CLIENT_SECRET", "")}
    if not all(values.values()):
        raise RuntimeError("Both Jira credentials must be supplied in process environment")
    if os.environ.get("CALDOVA_JIRA_USERNAME") and os.environ.get("CALDOVA_JIRA_PASSWORD"):
        values["jira-demo-username"] = os.environ["CALDOVA_JIRA_USERNAME"]
        values["jira-demo-password"] = os.environ["CALDOVA_JIRA_PASSWORD"]
    audit("seed-jira-oauth-credentials", "started")
    vault = Vault()
    try:
        for name, value in values.items():
            vault.put(name, value)
            if vault.get(name) != value:
                raise RuntimeError(f"Secret verification mismatch: {name}")
        audit("seed-jira-oauth-credentials", "succeeded")
        print(json.dumps({"secretNames": list(values), "verified": True, "valuesPrinted": False}))
    finally:
        vault.close()


def seed() -> None:
    audit("seed-new-vault", "started")
    values = load_server_values()
    supplied = {name: os.environ.get(variable, "") for name, variable in SUPPLIED_SECRET_ENV.items()}
    if not all(supplied.values()):
        raise RuntimeError("Missing supplied credentials in process environment; no values written")
    vault = Vault()
    try:
        names = []
        for server, settings in values.items():
            for key in CATALOG[server]["secretEnv"]:
                if settings.get(key):
                    name = key.lower().replace("_", "-")
                    vault.put(name, settings[key])
                    names.append(name)
        for name, value in supplied.items():
            vault.put(name, value)
            names.append(name)
        # Verify actual values in memory; only names/counts may be emitted.
        for name in names:
            if not vault.get(name):
                raise RuntimeError("A seeded secret is empty")
        audit("seed-new-vault", "succeeded")
        print(json.dumps({"seededCount": len(names), "secretNames": names, "valuesPrinted": False}))
    finally:
        vault.close()


def seed_fallbacks() -> None:
    """Copy the previously verified Workday credential set; reuse supplied SF/SN vault values."""
    original = dotenv_values(ROOT / "demo_agent" / ".env", interpolate=False)
    values = {target: original.get(f"ESS_WORKDAY_OAUTH_{field}") or ""
              for field, target in [("CLIENT_ID", "workday-oauth-client-id"),
                                    ("CLIENT_SECRET", "workday-oauth-client-secret"),
                                    ("REFRESH_TOKEN", "workday-oauth-refresh-token")]}
    if not all(values.values()):
        raise RuntimeError("The verified local Workday OAuth credential set is incomplete")
    audit("seed-bearer-first-fallbacks", "started")
    vault = Vault()
    try:
        for name, value in values.items():
            vault.put(name, value)
            if vault.get(name) != value:
                raise RuntimeError(f"Vault verification failed: {name}")
        names = {name for bindings in FALLBACK_SECRET_BINDINGS.values() for name in bindings.values()}
        for name in names:
            if not vault.get(name):
                raise RuntimeError(f"Required fallback secret is empty: {name}")
        audit("seed-bearer-first-fallbacks", "succeeded")
        print(json.dumps({"verifiedSecretNames": sorted(names), "valuesPrinted": False}))
    finally:
        vault.close()


def parameters(image: str, preserve_other_images: bool = False) -> None:
    if not re.fullmatch(re.escape(REGISTRY) + r"/[a-z0-9/_-]+@sha256:[a-f0-9]{64}", image):
        raise ValueError("Use a digest-pinned image from the new registry")
    configs = []
    existing = {}
    if preserve_other_images:
        prior = json.loads((SESSION / "runtime.parameters.json").read_text(encoding="utf-8"))["parameters"]
        existing = {server["cliName"]: server.get("image", prior["containerImage"]["value"])
                    for server in prior["serverConfigs"]["value"]}
    vault = Vault()
    try:
        for server, values in load_server_values().items():
            catalog = CATALOG[server]
            config = {"name": catalog["name"], "cliName": server, "env": [], "secrets": []}
            if preserve_other_images and server not in FALLBACK_SECRET_BINDINGS:
                config["image"] = existing[server]
            for key, value in values.items():
                if key in catalog["secretEnv"]:
                    name = key.lower().replace("_", "-")
                    if vault.get(name) != value:
                        raise RuntimeError(f"Secret verification mismatch: {name}")
                    config["env"].append({"name": key, "secretRef": name})
                    config["secrets"].append({"name": name, "keyVaultUrl": f"{VAULT}/secrets/{name}"})
                else:
                    config["env"].append({"name": key, "value": value})
            for key, name in FALLBACK_SECRET_BINDINGS.get(server, {}).items():
                if not vault.get(name):
                    raise RuntimeError(f"Required fallback secret is empty: {name}")
                config["env"].append({"name": key, "secretRef": name})
                config["secrets"].append({"name": name, "keyVaultUrl": f"{VAULT}/secrets/{name}"})
            configured = {entry["name"] for entry in config["env"]}
            for key in catalog["requiredEnv"]:
                if key not in configured:
                    raise RuntimeError(f"Missing required configuration: {key}")
            configs.append(config)
    finally:
        vault.close()
    payload = {"$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
               "contentVersion": "1.0.0.0", "parameters": {"deployApps": {"value": True},
               "containerImage": {"value": image}, "serverConfigs": {"value": configs}}}
    path = SESSION / "runtime.parameters.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    audit("prepare-reference-only-runtime-parameters", "succeeded")
    print(json.dumps({"path": str(path), "serverCount": len(configs), "containsSecretValues": False}))


def evidence(deployment_name: str = "essmcp-caldova-apps") -> None:
    """Collect allowlisted deployment metadata; exclude template parameters and secrets."""
    guard_target()
    audit("collect-final-deployment-evidence", "started")
    deployment = az_json("deployment", "sub", "show", "--name", deployment_name,
                         "--subscription", SUBSCRIPTION, "--query",
                         "{state:properties.provisioningState,outputs:properties.outputs}")
    endpoints = deployment["outputs"]["endpoints"]["value"]
    root_operations = az_json("deployment", "operation", "sub", "list", "--name", deployment_name,
                              "--subscription", SUBSCRIPTION)
    resource_results = []
    nested_names = []
    for operation in root_operations:
        properties = operation["properties"]
        target = properties.get("targetResource") or {}
        if target.get("resourceType") == "Microsoft.Resources/deployments" and "/resourceGroups/" in target.get("id", ""):
            name = target["id"].rsplit("/", 1)[-1]
            nested_names.append(name)
            children = az_json("deployment", "operation", "group", "list", "--name", name,
                               "--resource-group", "essmcp-caldova-rg", "--subscription", SUBSCRIPTION)
            for child in children:
                item = child["properties"]
                resource = item.get("targetResource") or {}
                if resource.get("id"):
                    resource_results.append({"resourceId": resource["id"], "type": resource.get("resourceType", ""),
                                             "status": "succeeded" if item.get("provisioningState") == "Succeeded" else "failed"})
        elif target.get("resourceType") == "Microsoft.Resources/resourceGroups":
            resource_results.append({"resourceId": target["id"], "type": target["resourceType"],
                                     "status": "succeeded" if properties.get("provisioningState") == "Succeeded" else "failed"})
    apps = []
    runtime = json.loads((SESSION / "runtime.parameters.json").read_text(encoding="utf-8"))["parameters"]
    expected_image = runtime["containerImage"]["value"]
    expected_images = {server["name"]: server.get("image", expected_image) for server in runtime["serverConfigs"]["value"]}
    for endpoint in endpoints:
        app = az_json("rest", "--method", "get", "--url",
                      "https://management.azure.com" + endpoint["resourceId"] + "?api-version=2026-01-01",
                      "--query", "{id:id,name:name,location:location,state:properties.provisioningState,running:properties.runningStatus,ready:properties.latestReadyRevisionName,image:properties.template.containers[0].image,identity:identity.type,min:properties.template.scale.minReplicas,max:properties.template.scale.maxReplicas}")
        if app["state"] != "Succeeded" or app["running"] != "Running" or app["image"] != expected_images[app["name"]] or not app["ready"]:
            raise RuntimeError("A deployed app does not match its validated configuration")
        apps.append(app)
    if len(apps) != 7 or any(item["status"] != "succeeded" for item in resource_results):
        raise RuntimeError("Final deployment operation evidence is incomplete or failed")
    snapshot = {"checkedUtc": datetime.now(timezone.utc).isoformat(), "deployment": deployment_name,
                "state": deployment["state"], "endpoints": endpoints, "apps": apps,
                "nestedDeploymentNames": nested_names, "resourceResults": resource_results}
    (SESSION / "deployment-evidence.json").write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
    audit("collect-final-deployment-evidence", "succeeded")
    print(json.dumps({"state": snapshot["state"], "verifiedApps": len(apps), "successfulResourceOperations": len(resource_results),
                      "checkedUtc": snapshot["checkedUtc"], "image": expected_image}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["stage", "seed", "seed-jira", "seed-fallbacks", "parameters", "evidence"])
    parser.add_argument("--image")
    parser.add_argument("--deployment", default="essmcp-caldova-apps")
    parser.add_argument("--preserve-other-images", action="store_true")
    args = parser.parse_args()
    if args.operation == "stage":
        stage()
    elif args.operation == "seed":
        seed()
    elif args.operation == "seed-jira":
        seed_jira()
    elif args.operation == "seed-fallbacks":
        seed_fallbacks()
    elif args.operation == "evidence":
        evidence(args.deployment)
    else:
        parameters(args.image or "", args.preserve_other_images)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not expose HTTP request/response bodies or an exception traceback.
        if isinstance(exc, (RuntimeError, ValueError)):
            print(str(exc), file=sys.stderr)
        else:
            print(f"Deployment support failed: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)