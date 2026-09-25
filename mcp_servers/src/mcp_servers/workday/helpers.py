"""Shared Workday helper functions."""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, Dict

from ..http import create_async_client
from ..logging import get_logger
from ..settings import load_workday_settings
from .config import get_endpoints

LOGGER = get_logger(__name__)


@dataclass
class WorkerContext:
    payload: Dict[str, Any]
    worker_id: str
    workday_id: str
    workday_access_token: str
    worker_data: Dict[str, Any]


@dataclass
class CachedToken:
    access_token: str
    expires_at: float

    def valid(self) -> bool:
        return bool(self.access_token) and time.time() < self.expires_at - 60


_TOKEN_CACHE: dict[str, CachedToken] = {}
_TOKEN_LOCK = asyncio.Lock()


def _setting_or_env(setting_value: str, *env_names: str) -> str:
    if setting_value:
        return setting_value
    for env_name in env_names:
        value = os.getenv(env_name, "")
        if value:
            return value
    return ""


async def get_workday_fallback_access_token() -> str:
    """Serialize fallback renewal; inbound caller tokens never use this cache."""
    async with _TOKEN_LOCK:
        return await _get_workday_fallback_access_token()


async def _get_workday_fallback_access_token() -> str:
    """Acquire a server-side Workday token with the stored refresh-token flow."""
    settings = load_workday_settings()
    token_url = _setting_or_env(settings.oauth_token_url, "ESS_WORKDAY_OAUTH_TOKEN_URL")
    if not token_url:
        raise RuntimeError("No Workday OAuth token URL configured for fallback access")

    cached = _TOKEN_CACHE.get("workday")
    if cached and cached.valid():
        return cached.access_token

    client_id = _setting_or_env(settings.oauth_client_id, "ESS_WORKDAY_OAUTH_CLIENT_ID")
    client_secret = _setting_or_env(settings.oauth_client_secret, "ESS_WORKDAY_OAUTH_CLIENT_SECRET")
    refresh_token = _setting_or_env(settings.oauth_refresh_token, "ESS_WORKDAY_OAUTH_REFRESH_TOKEN")
    grant_type = _setting_or_env(settings.oauth_grant_type, "ESS_WORKDAY_OAUTH_GRANT_TYPE")
    if not grant_type:
        grant_type = "refresh_token"
    if grant_type != "refresh_token":
        raise RuntimeError("Workday fallback only supports grant_type=refresh_token")
    auth_method = _setting_or_env(settings.oauth_auth_method, "ESS_WORKDAY_OAUTH_AUTH_METHOD") or "client_secret_post"

    body: dict[str, str] = {"grant_type": grant_type}
    headers = {"Accept": "application/json"}
    scope = _setting_or_env(settings.oauth_scope, "ESS_WORKDAY_OAUTH_SCOPE")
    audience = _setting_or_env(settings.oauth_audience, "ESS_WORKDAY_OAUTH_AUDIENCE")
    resource = _setting_or_env(settings.oauth_resource, "ESS_WORKDAY_OAUTH_RESOURCE")
    if scope:
        body["scope"] = scope
    if audience:
        body["audience"] = audience
    if resource:
        body["resource"] = resource
    if not refresh_token:
        raise RuntimeError("Workday refresh-token fallback is configured, but no refresh token is available")
    body["refresh_token"] = refresh_token

    auth: tuple[str, str] | None = None
    if auth_method == "client_secret_basic":
        auth = (client_id, client_secret)
    elif auth_method == "client_secret_post":
        body["client_id"] = client_id
        body["client_secret"] = client_secret
    elif auth_method == "none":
        pass
    else:
        raise RuntimeError(f"Unsupported Workday OAuth auth method: {auth_method}")

    async with create_async_client() as client:
        if auth is not None:
            response = await client.post(token_url, data=body, headers=headers, auth=auth)
        else:
            response = await client.post(token_url, data=body, headers=headers)
        response.raise_for_status()
        data = response.json()

    access_token = data.get("access_token") or data.get("accessToken")
    if not access_token:
        raise RuntimeError("Workday OAuth endpoint did not return access_token")
    expires_in = int(data.get("expires_in") or data.get("expiresIn") or 1800)
    _TOKEN_CACHE["workday"] = CachedToken(access_token=access_token, expires_at=time.time() + expires_in)
    LOGGER.info("workday_fallback_token_acquired", grant_type=grant_type)
    return access_token


async def _fetch_worker_from_staffing(token: str, workday_id: str, seed_data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    endpoints = get_endpoints()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    staffing_url = endpoints.full_url(
        "/ccx/api/staffing/v4/{tenant}/workers/{workday_id}",
        workday_id=workday_id,
    )
    LOGGER.info("enriching_worker_from_staffing", url=staffing_url)
    async with create_async_client() as client:
        staffing_resp = await client.get(staffing_url, headers=headers)
        if staffing_resp.is_success:
            worker_data = staffing_resp.json()
            for key, value in (seed_data or {}).items():
                worker_data.setdefault(key, value)
            LOGGER.info("enriched_worker_from_staffing", keys=list(worker_data.keys()))
            return worker_data

    LOGGER.warning(
        "staffing_enrichment_failed",
        status=staffing_resp.status_code,
        fallback="using seed worker data",
    )
    return seed_data or {"id": workday_id, "workerId": workday_id}


async def build_worker_context_from_bearer(token: str) -> WorkerContext:
    """Build worker context using /workers/me then enriching via the staffing API."""
    endpoints = get_endpoints()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Step 1: Get the workday_id from /workers/me
    me_url = endpoints.full_url("/ccx/api/common/v1/{tenant}/workers/me")
    LOGGER.info("resolving_worker_via_me", url=me_url)
    async with create_async_client() as client:
        response = await client.get(me_url, headers=headers)
        response.raise_for_status()
        me_data = response.json()

    workday_id = me_data.get("id", "")
    LOGGER.info("resolved_worker_via_me", workday_id=workday_id)

    worker_data = await _fetch_worker_from_staffing(token, workday_id, me_data)

    worker_id = worker_data.get("workerId", workday_id)
    return WorkerContext(
        payload={},
        worker_id=worker_id,
        workday_id=workday_id,
        workday_access_token=token,
        worker_data=worker_data,
    )


async def build_worker_context_from_fallback() -> WorkerContext:
    """Build worker context for no-auth MCP calls using configured service credentials."""
    settings = load_workday_settings()
    token = await get_workday_fallback_access_token()
    workday_id = _setting_or_env(settings.default_worker_id, "ESS_WORKDAY_DEFAULT_WORKER_ID")
    worker_data: Dict[str, Any] = {}

    if workday_id:
        LOGGER.info("resolving_worker_via_configured_id", workday_id=workday_id)
        worker_data = await _fetch_worker_from_staffing(token, workday_id)
    else:
        search = _setting_or_env(settings.default_worker_search, "ESS_WORKDAY_DEFAULT_WORKER_SEARCH")
        if search:
            endpoints = get_endpoints()
            headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            search_url = endpoints.full_url("/ccx/api/absenceManagement/v1/{tenant}/workers")
            LOGGER.info("resolving_worker_via_search", search=search)
            async with create_async_client() as client:
                response = await client.get(search_url, params={"search": search}, headers=headers)
                response.raise_for_status()
                data = response.json()
            matches = data.get("data") if isinstance(data, dict) else data
            if not isinstance(matches, list) or not matches:
                raise RuntimeError(f"No Workday worker matched WORKDAY_DEFAULT_WORKER_SEARCH={search!r}")
            worker_data = matches[0]
            workday_id = worker_data.get("id") or worker_data.get("workerId") or ""
            if workday_id:
                worker_data = await _fetch_worker_from_staffing(token, workday_id, worker_data)
        else:
            LOGGER.info("resolving_fallback_worker_via_me")
            return await build_worker_context_from_bearer(token)

    worker_id = worker_data.get("workerId", workday_id)
    return WorkerContext(
        payload={},
        worker_id=worker_id,
        workday_id=workday_id,
        workday_access_token=token,
        worker_data=worker_data,
    )

