"""Shared Workday helper functions."""
from __future__ import annotations
import base64
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import quote
from ..http import create_async_client
from ..logging import get_logger
from ..settings import WorkdaySettings, load_workday_settings
from .config import DEFAULT_ENDPOINTS, WorkdayApiEndpoints

LOGGER = get_logger(__name__)


def _require(value: Optional[str], name: str) -> str:
    if not value:
        raise ValueError(f"Missing required configuration value: {name}")
    return value


def _parse_worker_id_from_token(token: str) -> Optional[str]:
    """Try to extract worker/employee ID from JWT token claims (no validation).

    Returns the first matching claim: preferred_username, upn, sub.
    Returns None if token is not a JWT or has no useful claims.
    """
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        padding = 4 - len(parts[1]) % 4
        padded = parts[1] + "=" * padding
        payload_bytes = base64.urlsafe_b64decode(padded)
        payload = json.loads(payload_bytes)
        # Try common claim names for worker/employee identifier
        for key in ("preferred_username", "upn", "unique_name"):
            val = payload.get(key)
            if val:
                # Strip domain if present
                return val.split("@")[0] if "@" in str(val) else str(val)
        for key in ("EmployeeId", "employeeId", "employee_id", "extension_EmployeeId"):
            if key in payload and payload[key]:
                return str(payload[key])
        sub = payload.get("sub")
        if sub:
            return str(sub)
    except Exception as exc:
        LOGGER.debug("jwt_parse_failed", error=str(exc))
    return None


async def search_worker_in_workday(
    access_token: str,
    worker_id: str,
    endpoints: WorkdayApiEndpoints = DEFAULT_ENDPOINTS,
) -> Dict[str, Any]:
    settings: WorkdaySettings = load_workday_settings()
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


async def build_worker_context_from_bearer(token: str) -> WorkerContext:
    """Build worker context using the incoming OAuth 2.0 bearer token.

    The token is used directly as the Workday API access token.
    Worker ID is extracted from JWT claims (no validation) and then
    resolved via the Workday workers API.
    """
    worker_id = _parse_worker_id_from_token(token)
    if not worker_id:
        raise ValueError(
            "Cannot determine worker ID from token. "
            "Ensure your OAuth token contains preferred_username, upn, or employeeId claims."
        )
    LOGGER.info("resolving_workday_worker", worker_id=worker_id)
    worker_data = await search_worker_in_workday(token, worker_id)
    workday_id = worker_data.get("id", worker_id)
    return WorkerContext(
        payload={},
        worker_id=worker_id,
        workday_id=workday_id,
        workday_access_token=token,
        worker_data=worker_data,
    )

