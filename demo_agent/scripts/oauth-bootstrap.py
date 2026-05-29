from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from demo_agent.oauth import authorization_request_url, exchange_authorization_code


def _secret_name(server: str) -> str:
    return f"ess-{server.lower()}-oauth-refresh-token"


def _run_az(args: list[str]) -> None:
    completed = subprocess.run(["az", *args], check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        sys.stderr.write(completed.stderr)
        raise SystemExit(completed.returncode)


def _store_containerapp_secret(server: str, token: str, resource_group: str, container_app: str) -> None:
    prefix = f"ESS_{server.upper()}"
    secret_name = _secret_name(server)
    _run_az([
        "containerapp",
        "secret",
        "set",
        "-g",
        resource_group,
        "-n",
        container_app,
        "--secrets",
        f"{secret_name}={token}",
        "-o",
        "none",
    ])
    _run_az([
        "containerapp",
        "update",
        "-g",
        resource_group,
        "-n",
        container_app,
        "--set-env-vars",
        f"{prefix}_OAUTH_GRANT_TYPE=refresh_token",
        f"{prefix}_OAUTH_REFRESH_TOKEN=secretref:{secret_name}",
        "-o",
        "none",
    ])


async def _exchange(args: argparse.Namespace) -> None:
    data: dict[str, Any] = await exchange_authorization_code(args.server, args.code)
    refresh_token = data.get("refresh_token") or data.get("refreshToken")
    if not refresh_token:
        raise SystemExit("The OAuth response did not include a refresh_token. Check the SaaS app grant settings.")
    if args.container_app:
        _store_containerapp_secret(args.server, refresh_token, args.resource_group, args.container_app)
        print(f"Stored {args.server} refresh token in Container Apps secret '{_secret_name(args.server)}'.")
    else:
        print("Authorization succeeded and returned a refresh token.")
        print("Store it in Key Vault or a Container Apps secret; do not put it in .env.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Bootstrap Workday/ServiceNow OAuth without storing access tokens in files.")
    parser.add_argument("server", choices=("workday", "servicenow"))
    parser.add_argument("--env-file", default=str(Path(__file__).resolve().parents[1] / ".env"))
    parser.add_argument("--print-url", action="store_true", help="Print the authorization URL for the SaaS consent step.")
    parser.add_argument("--state", default="", help="OAuth state value. A random value is generated when omitted.")
    parser.add_argument("--code", default="", help="Authorization code returned to the configured redirect URI.")
    parser.add_argument("--resource-group", default="essmcp-rg")
    parser.add_argument("--container-app", default="", help="Container App name where the refresh token should be stored as a secret.")
    args = parser.parse_args()

    load_dotenv(args.env_file)
    if args.print_url:
        state = args.state or uuid.uuid4().hex
        print(authorization_request_url(args.server, state))
        print(f"state={state}")
    if args.code:
        asyncio.run(_exchange(args))
    if not args.print_url and not args.code:
        parser.error("Use --print-url to start auth or --code <code> to exchange the callback code.")


if __name__ == "__main__":
    main()