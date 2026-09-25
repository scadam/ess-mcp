"""Prefer the caller's bearer token; mint/cache only server-owned fallback tokens."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import math
import time
from typing import Optional
from urllib.parse import urlsplit

import httpx
from fastmcp import Context

from ..settings import ServiceNowSettings, load_servicenow_settings
from .entra import TokenValidationError, get_bearer_token


@dataclass
class _CachedToken:
    access_token: str = field(repr=False)
    refresh_at: float
    configuration_key: str


_token_cache: Optional[_CachedToken] = None
_token_lock = asyncio.Lock()


def _configuration_key(settings: ServiceNowSettings) -> str:
    # A configuration change must never reuse a token from the previous account.
    values = [settings.instance_url, settings.oauth_token_url, settings.oauth_client_id,
              settings.oauth_client_secret, settings.oauth_grant_type, settings.oauth_auth_method,
              settings.oauth_scope, settings.oauth_username, settings.oauth_password]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


async def _mint_token(settings: ServiceNowSettings, key: str) -> _CachedToken:
    token_url = settings.oauth_token_url or settings.instance_url.rstrip("/") + "/oauth_token.do"
    parsed = urlsplit(token_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RuntimeError("ServiceNow OAuth token endpoint must be an HTTPS URL without embedded credentials or query parameters")
    if not settings.oauth_client_id or not settings.oauth_client_secret:
        raise TokenValidationError("ServiceNow fallback requires SERVICENOW_OAUTH_CLIENT_ID and SERVICENOW_OAUTH_CLIENT_SECRET")

    body = {"grant_type": settings.oauth_grant_type}
    if settings.oauth_grant_type == "password":
        if not settings.oauth_username or not settings.oauth_password:
            raise TokenValidationError("ServiceNow password grant requires configured username and password")
        body.update(username=settings.oauth_username, password=settings.oauth_password)
    elif settings.oauth_grant_type != "client_credentials":
        raise RuntimeError("Unsupported ServiceNow fallback grant; use client_credentials or password")
    if settings.oauth_scope:
        body["scope"] = settings.oauth_scope
    auth = None
    if settings.oauth_auth_method == "client_secret_basic":
        auth = httpx.BasicAuth(settings.oauth_client_id, settings.oauth_client_secret)
    elif settings.oauth_auth_method == "client_secret_post":
        body.update(client_id=settings.oauth_client_id, client_secret=settings.oauth_client_secret)
    else:
        raise RuntimeError("Unsupported ServiceNow OAuth client authentication method")

    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        response = await client.post(token_url, data=body, auth=auth, headers={"Accept": "application/json"})
    # Preserve HTTP auth failures for MCP error propagation. Never log the body.
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("ServiceNow token response did not contain a usable access_token")
    if str(payload.get("token_type", "Bearer")).lower() != "bearer":
        raise RuntimeError("ServiceNow token response did not contain a bearer token")
    try:
        lifetime = float(payload.get("expires_in", 1800))
    except (TypeError, ValueError):
        raise RuntimeError("ServiceNow token response has invalid expires_in") from None
    if not math.isfinite(lifetime) or lifetime <= 0:
        raise RuntimeError("ServiceNow token response has invalid expires_in")
    # Short-lived tokens must not immediately expire because of a fixed skew.
    margin = min(60, lifetime / 10)
    return _CachedToken(token, time.monotonic() + lifetime - margin, key)


async def resolve_servicenow_token(ctx: Optional[Context] = None) -> str:
    """Never cache a caller token or retry a rejected caller as the service account."""
    try:
        return get_bearer_token(ctx)
    except TokenValidationError:
        pass
    settings = load_servicenow_settings()
    key = _configuration_key(settings)
    global _token_cache
    async with _token_lock:
        if _token_cache and _token_cache.configuration_key == key and time.monotonic() < _token_cache.refresh_at:
            return _token_cache.access_token
        # Failed refreshes do not leave an old-account token eligible for reuse.
        _token_cache = None
        _token_cache = await _mint_token(settings, key)
        return _token_cache.access_token


def reset_servicenow_token_cache() -> None:
    """Clear only server-owned fallback state (for tests or explicit invalidation)."""
    global _token_cache
    _token_cache = None