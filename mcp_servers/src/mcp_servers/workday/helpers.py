"""Shared Workday helper functions ported from the Azure Functions project."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import quote

from ..auth import EntraTokenValidator, WorkdayTokenProvider
from ..http import create_async_client
from ..logging import get_logger
from ..settings import GraphSettings, WorkdayOAuthSettings, load_graph_settings, load_workday_oauth_settings
from .config import DEFAULT_ENDPOINTS, WorkdayApiEndpoints

LOGGER = get_logger(__name__)


def _require(value: Optional[str], name: str) -> str:
    if not value:
        raise ValueError(f"Missing required configuration value: {name}")
    return value


async def get_workday_access_token() -> str:
    provider = WorkdayTokenProvider()
    token = await provider.get_access_token()
    return token.access_token


async def get_graph_access_token(settings: Optional[GraphSettings] = None) -> str:
    cfg = settings or load_graph_settings()
    token_url = f"https://login.microsoftonline.com/{cfg.tenant_id}/oauth2/v2.0/token"
    data = {
        "client_id": cfg.client_id,
        "client_secret": cfg.client_secret,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }
    async with create_async_client() as client:
        response = await client.post(token_url, data=data)
        response.raise_for_status()
        payload = response.json()
    return payload["access_token"]


async def get_employee_id_from_graph(user_identifier: str) -> str:
    graph_token = await get_graph_access_token()
    encoded_identifier = quote(user_identifier, safe="@")
    url = f"https://graph.microsoft.com/v1.0/users/{encoded_identifier}"
    params = {"$select": "employeeId,userPrincipalName,id"}
    async with create_async_client() as client:
        response = await client.get(url, params=params, headers={"Authorization": f"Bearer {graph_token}"})
        response.raise_for_status()
        user_data = response.json()
    employee_id = user_data.get("employeeId")
    if employee_id:
        return employee_id
    upn = user_data.get("userPrincipalName")
    if upn:
        return upn.split("@")[0]
    raise ValueError("Unable to determine employee ID from Microsoft Graph")


async def extract_worker_id_from_token(token: str, payload: Dict[str, Any]) -> str:
    LOGGER.info("extracting_worker_id", claims=list(payload.keys()))
    username = payload.get("preferred_username") or payload.get("upn") or payload.get("unique_name")

    if username:
        try:
            return await get_employee_id_from_graph(username)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("graph_lookup_failed", identifier=username, error=str(exc))

    if "oid" in payload and payload["oid"]:
        try:
            return await get_employee_id_from_graph(str(payload["oid"]))
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("graph_lookup_failed", identifier=payload["oid"], error=str(exc))

    for key in ("EmployeeId", "employeeId", "employee_id", "extension_EmployeeId"):
        if key in payload and payload[key]:
            return str(payload[key])

    if username:
        return username.split("@")[0]

    raise ValueError("Worker ID could not be determined from token")


async def search_worker_in_workday(
    access_token: str,
    worker_id: str,
    endpoints: WorkdayApiEndpoints = DEFAULT_ENDPOINTS,
) -> Dict[str, Any]:
    settings: WorkdayOAuthSettings = load_workday_oauth_settings()
    base_url = (settings.workers_api_url or endpoints.full_url(endpoints.workers_path)).rstrip("/")
    search_url = f"{base_url}?search='{worker_id}'"
    async with create_async_client() as client:
        response = await client.get(search_url, headers={"Authorization": f"Bearer {access_token}"})
        response.raise_for_status()
        data = response.json()
    records = data.get("data", [])
    if not records:
        raise LookupError(f"No worker found with ID {worker_id}")
    return records[0]


@dataclass
class WorkerContext:
    payload: Dict[str, Any]
    worker_id: str
    workday_id: str
    workday_access_token: str
    worker_data: Dict[str, Any]


async def build_worker_context_anonymous(employee_id: str) -> WorkerContext:
    """Build worker context using a pre-configured employee ID without authentication."""
    LOGGER.info("building_anonymous_worker_context", employee_id=employee_id)
    access_token = await get_workday_access_token()
    worker_data = await search_worker_in_workday(access_token, employee_id)
    workday_id = worker_data.get("id", employee_id)
    return WorkerContext(
        payload={},  # No auth token payload in anonymous mode
        worker_id=employee_id,
        workday_id=workday_id,
        workday_access_token=access_token,
        worker_data=worker_data,
    )


async def build_worker_context(token: str, validator: Optional[EntraTokenValidator] = None) -> WorkerContext:
    validator = validator or EntraTokenValidator()
    payload = await validator.validate(token)
    worker_id = await extract_worker_id_from_token(token, payload)
    access_token = await get_workday_access_token()
    worker_data = await search_worker_in_workday(access_token, worker_id)
    workday_id = worker_data.get("id", worker_id)
    return WorkerContext(
        payload=payload,
        worker_id=worker_id,
        workday_id=workday_id,
        workday_access_token=access_token,
        worker_data=worker_data,
    )
