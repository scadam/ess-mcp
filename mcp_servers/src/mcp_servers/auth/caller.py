"""Privileged tools answer only the Autopilot host: an Entra token from its managed identity, sent as X-Autopilot-Caller.

The public demo endpoints stay open for ordinary reads and first-line actions, but account resets and similar
powers need proof of the calling workload. The token's signature, issuer, audience, expiry and application id
are all checked; there is no shared secret.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

import jwt
from fastmcp import Context
from jwt import PyJWKClient

from ..logging import get_logger

LOGGER = get_logger(__name__)


class CallerNotTrusted(PermissionError):
    """The request did not prove it comes from the configured Autopilot host."""


@lru_cache(maxsize=4)
def _jwks(tenant: str) -> PyJWKClient:
    return PyJWKClient(f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys", cache_keys=True,
                       lifespan=3600)


def _header(ctx: Optional[Context]) -> str:
    try:
        request = ctx.request_context.request  # type: ignore[union-attr]
    except (ValueError, AttributeError):
        return ""
    value = (request.headers.get("x-autopilot-caller") if request else "") or ""
    return value.split(" ", 1)[1].strip() if value.lower().startswith("bearer ") else value.strip()


def verify_caller(ctx: Optional[Context]) -> str:
    """Return the trusted caller's application id, or raise CallerNotTrusted."""
    tenant = os.getenv("AUTOPILOT_CALLER_TENANT_ID", "").strip()
    audiences = [value.strip() for value in os.getenv("AUTOPILOT_CALLER_AUDIENCE", "").split(",") if value.strip()]
    app_ids = {value.strip().lower() for value in os.getenv("AUTOPILOT_CALLER_APP_IDS", "").split(",") if value.strip()}
    if not (tenant and audiences and app_ids):
        raise CallerNotTrusted("Privileged tools are disabled: no trusted caller is configured.")
    token = _header(ctx)
    if not token or len(token) > 8192:
        raise CallerNotTrusted("This tool is only available to the Autopilot host.")
    try:
        key = _jwks(tenant).get_signing_key_from_jwt(token)
        claims = jwt.decode(token, key.key, algorithms=["RS256"], audience=audiences,
                            options={"require": ["exp", "iat", "aud", "iss"]}, leeway=60)
    except Exception as exc:
        LOGGER.warning("privileged_caller_rejected", reason=type(exc).__name__)
        raise CallerNotTrusted("This tool is only available to the Autopilot host.") from None
    issuers = {f"https://sts.windows.net/{tenant}/", f"https://login.microsoftonline.com/{tenant}/v2.0"}
    app_id = str(claims.get("appid") or claims.get("azp") or "").lower()
    if claims.get("iss") not in issuers or claims.get("tid", tenant) != tenant or app_id not in app_ids:
        LOGGER.warning("privileged_caller_rejected", reason="identity")
        raise CallerNotTrusted("This tool is only available to the Autopilot host.")
    return app_id
