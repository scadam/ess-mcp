"""Salesforce authentication: bearer passthrough with client-credentials fallback.

Default behaviour (``SF_AUTH_MODE=auto``):
  * If the inbound request carries ``Authorization: Bearer <token>``, that
    token is forwarded to Salesforce (OAuth pass-through, same as before).
  * Otherwise the server mints an access token via the Salesforce OAuth 2.0
    Client Credentials flow using ``SF_CLIENT_ID`` / ``SF_CLIENT_SECRET``.

Other modes:
    * ``client_credentials`` – allow client-credentials fallback; caller bearer wins.
  * ``oauth_bearer``       – require a bearer token; no fallback.

The minted token is cached process-wide and refreshed on expiry.

Implementation mirrors the L2Q reference (``l2q.auth.salesforce``).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx
from fastmcp import Context

from ..logging import get_logger
from ..settings import SalesforceSettings, load_salesforce_settings
from .entra import TokenValidationError

LOGGER = get_logger(__name__)


@dataclass
class SalesforceToken:
    access_token: str
    instance_url: str
    token_type: str = "Bearer"
    issued_at: float = field(default_factory=time.time)
    expires_in: int = 7200  # Salesforce default access-token lifetime

    def is_expired(self, buffer_seconds: int = 120) -> bool:
        return time.time() >= self.issued_at + self.expires_in - buffer_seconds


_token_cache: Optional[SalesforceToken] = None
_token_lock: asyncio.Lock = asyncio.Lock()


def _instance_url_from_domain(domain: str) -> str:
    if domain.startswith("http://") or domain.startswith("https://"):
        return domain.rstrip("/")
    if ".my.salesforce.com" in domain or ".salesforce.com" in domain:
        return f"https://{domain}"
    return f"https://{domain}.my.salesforce.com"


def _bearer_from_context(ctx: Optional[Context]) -> Optional[str]:
    """Return the bearer token from the inbound Authorization header, if any."""
    if ctx is None:
        return None
    try:
        request = ctx.request_context.request  # type: ignore[union-attr]
    except (ValueError, AttributeError):
        return None
    if request is None:
        return None
    auth_header = request.headers.get("authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    return token or None


async def _mint_client_credentials_token(settings: SalesforceSettings) -> SalesforceToken:
    if not settings.client_id or not settings.client_secret:
        raise TokenValidationError(
            "Salesforce client credentials not configured: set SF_CLIENT_ID and "
            "SF_CLIENT_SECRET (or send Authorization: Bearer <token>)."
        )
    instance_url = _instance_url_from_domain(settings.domain)
    token_url = f"{instance_url}/services/oauth2/token"
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
    }
    LOGGER.info("salesforce_token_request", url=token_url, mode="client_credentials")
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            token_url, data=data, headers={"Accept": "application/json"}
        )
    if response.status_code != 200:
        LOGGER.error(
            "salesforce_token_request_failed",
            status=response.status_code,
        )
        # Surface as an auth error so the 401-passthrough middleware can
        # rewrite the HTTP status appropriately.
        response.raise_for_status()
    payload = response.json()
    issued_raw = payload.get("issued_at")
    try:
        issued_at = float(issued_raw) / 1000 if issued_raw else time.time()
    except (TypeError, ValueError):
        issued_at = time.time()
    return SalesforceToken(
        access_token=payload["access_token"],
        instance_url=payload.get("instance_url", instance_url),
        token_type=payload.get("token_type", "Bearer"),
        issued_at=issued_at,
    )


async def _get_cached_client_credentials_token(settings: SalesforceSettings) -> SalesforceToken:
    global _token_cache
    async with _token_lock:
        if _token_cache and not _token_cache.is_expired():
            return _token_cache
        token = await _mint_client_credentials_token(settings)
        _token_cache = token
        return token


async def resolve_salesforce_token(ctx: Optional[Context]) -> SalesforceToken:
    """Return a usable Salesforce access token + instance URL for this request.

    Resolution order depends on ``SF_AUTH_MODE``:
      * ``auto``               – bearer (if present), else client_credentials.
      * ``oauth_bearer``       – require a bearer header.
    * ``client_credentials`` – bearer (if present), else client credentials.
    """
    settings = load_salesforce_settings()
    mode = (settings.auth_mode or "auto").lower()

    bearer = _bearer_from_context(ctx)

    # A supplied caller identity always wins, even when fallback is configured.
    # Backend rejection must propagate rather than retry as the service account.
    if bearer:
        LOGGER.debug("salesforce_auth_using_bearer")
        return SalesforceToken(
            access_token=bearer,
            instance_url=_instance_url_from_domain(settings.domain),
        )

    if mode == "oauth_bearer":
        raise TokenValidationError(
            "Authorization: Bearer <token> header is required"
        )

    if mode not in {"auto", "client_credentials"}:
        raise RuntimeError("Unsupported Salesforce authentication mode")
    LOGGER.debug("salesforce_auth_using_client_credentials_fallback")
    return await _get_cached_client_credentials_token(settings)


def reset_salesforce_token_cache() -> None:
    """Clear the cached client-credentials token (useful for tests)."""
    global _token_cache
    _token_cache = None
