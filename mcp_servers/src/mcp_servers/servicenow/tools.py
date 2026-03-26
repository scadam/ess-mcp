
import json
import re
import time
from typing import Any, Dict, List, Optional

from ..http import create_async_client
from ..logging import get_logger
from ..settings import load_servicenow_settings

LOGGER = get_logger(__name__)

# ── Incident state display mapping ──────────────────────────────────
_STATE_MAP: Dict[str, str] = {
    "new": "1",
    "in_progress": "2",
    "on_hold": "3",
    "resolved": "6",
    "closed": "7",
    "canceled": "8",
}

# Fields returned for each incident (keeps payloads lean)
_INCIDENT_FIELDS = ",".join(
    [
        "sys_id",
        "number",
        "short_description",
        "description",
        "state",
        "priority",
        "urgency",
        "impact",
        "category",
        "subcategory",
        "assigned_to",
        "assignment_group",
        "opened_by",
        "opened_at",
        "resolved_at",
        "closed_at",
        "close_code",
        "close_notes",
        "caller_id",
        "contact_type",
        "active",
        "sys_created_on",
        "sys_updated_on",
    ]
)

# ── Token cache ─────────────────────────────────────────────────────
_token_cache: Dict[str, Any] = {"access_token": None, "expires_at": 0.0}


async def _get_servicenow_token() -> str:
    """Obtain (or reuse) a ServiceNow OAuth access token via client credentials."""
    settings = load_servicenow_settings()

    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 30:
        return _token_cache["access_token"]

    token_url = f"{settings.instance_url}/oauth_token.do"
    data = {
        "grant_type": "client_credentials",
        "client_id": settings.client_id,
        "client_secret": settings.client_secret,
    }

    async with create_async_client() as client:
        resp = await client.post(
            token_url,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        body = resp.json()

    _token_cache["access_token"] = body["access_token"]
    _token_cache["expires_at"] = time.time() + int(body.get("expires_in", 1799))

    LOGGER.info("servicenow_token_acquired")
    return _token_cache["access_token"]


def _build_query(
    *,
    search_text: Optional[str] = None,
    number: Optional[str] = None,
    category: Optional[str] = None,
    state: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
    active: Optional[bool] = None,
) -> str:
    """Convert user-friendly parameters into a ServiceNow encoded query."""
    clauses: List[str] = []

    if number:
        clauses.append(f"number={number}")

    if search_text:
        # Search across short_description and description
        clauses.append(
            f"short_descriptionLIKE{search_text}"
            f"^ORdescriptionLIKE{search_text}"
            f"^ORnumberLIKE{search_text}"
        )

    if category:
        clauses.append(f"category={category}")

    if state:
        code = _STATE_MAP.get(state.lower().strip())
        if code:
            clauses.append(f"state={code}")
        else:
            # Let the caller pass a raw numeric state too
            clauses.append(f"state={state}")

    if priority:
        clauses.append(f"priority={priority}")

    if assigned_to:
        clauses.append(f"assigned_to.name={assigned_to}")

    if active is not None:
        clauses.append(f"active={'true' if active else 'false'}")

    return "^".join(clauses)


def _dv(value: Any) -> Any:
    """Extract display value from ServiceNow ``display_value/value`` dicts."""
    if isinstance(value, dict):
        return value.get("display_value", value.get("value", value))
    return value


def _simplify_incident(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a raw ServiceNow incident into a concise dict.

    When ``sysparm_display_value=all`` every field is returned as
    ``{"display_value": ..., "value": ...}``.  We extract the display
    value for all fields so the caller always gets plain scalars.
    """

    return {
        "sys_id": _dv(raw.get("sys_id")),
        "number": _dv(raw.get("number")),
        "short_description": _dv(raw.get("short_description")),
        "description": _dv(raw.get("description")),
        "state": _dv(raw.get("state")),
        "priority": _dv(raw.get("priority")),
        "urgency": _dv(raw.get("urgency")),
        "impact": _dv(raw.get("impact")),
        "category": _dv(raw.get("category")),
        "subcategory": _dv(raw.get("subcategory")),
        "assigned_to": _dv(raw.get("assigned_to")),
        "assignment_group": _dv(raw.get("assignment_group")),
        "opened_by": _dv(raw.get("opened_by")),
        "opened_at": _dv(raw.get("opened_at")),
        "resolved_at": _dv(raw.get("resolved_at")),
        "closed_at": _dv(raw.get("closed_at")),
        "active": _dv(raw.get("active")),
        "sys_updated_on": _dv(raw.get("sys_updated_on")),
    }


# ── MCP tool functions ──────────────────────────────────────────────

async def tool_list_incidents(
    search_text: Optional[str] = None,
    number: Optional[str] = None,
    category: Optional[str] = None,
    state: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
    active: Optional[bool] = None,
    limit: int = 10,
) -> Dict:
    """Search ServiceNow incidents.

    All filter parameters are optional; when none are provided the most recent
    incidents are returned.

    Args:
        search_text: Free-text search across incident number, short description,
            and description fields.
        number: Exact incident number (e.g. INC0000060).
        category: Filter by category (e.g. inquiry, software, hardware, network).
        state: Filter by state name: new, in_progress, on_hold, resolved, closed,
            or canceled.
        priority: Filter by priority (1 = Critical … 5 = Planning).
        assigned_to: Filter by the display name of the assigned user.
        active: Filter by active status (true or false).
        limit: Maximum number of incidents to return (default 10, max 100).
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    query = _build_query(
        search_text=search_text,
        number=number,
        category=category,
        state=state,
        priority=priority,
        assigned_to=assigned_to,
        active=active,
    )

    safe_limit = max(1, min(int(limit), 100))

    params: Dict[str, Any] = {
        "sysparm_limit": safe_limit,
        "sysparm_fields": _INCIDENT_FIELDS,
        "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
        "sysparm_orderby": "sys_updated_on",
        "sysparm_orderbydesc": "sys_updated_on",
    }
    if query:
        params["sysparm_query"] = query

    url = f"{settings.instance_url}/api/now/table/incident"

    LOGGER.info("servicenow_list_incidents", query=query, limit=safe_limit)

    async with create_async_client() as client:
        resp = await client.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    raw_results = body.get("result", [])
    incidents = [_simplify_incident(r) for r in raw_results]

    payload = {
        "total_returned": len(incidents),
        "incidents": incidents,
        "_instance_url": settings.instance_url,
    }

    return payload


# ── Reverse lookup: state code → friendly name ──────────────────────
_STATE_REVERSE: Dict[str, str] = {v: k for k, v in _STATE_MAP.items()}


# ── Shared: resolve incident number → sys_id ────────────────────────

async def _resolve_incident(
    number: str,
    token: str,
    instance_url: str,
) -> Dict[str, Any]:
    """Fetch a single incident by number. Returns the simplified record.

    Raises ``ValueError`` if the incident is not found.
    """
    params: Dict[str, Any] = {
        "sysparm_query": f"number={number}",
        "sysparm_limit": 1,
        "sysparm_fields": _INCIDENT_FIELDS,
        "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
    }
    url = f"{instance_url}/api/now/table/incident"

    async with create_async_client() as client:
        resp = await client.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    results = body.get("result", [])
    if not results:
        raise ValueError(f"Incident {number} not found.")
    return results[0]


async def _fetch_journal(
    sys_id: str,
    token: str,
    instance_url: str,
    limit: int = 50,
) -> List[Dict[str, str]]:
    """Fetch comment and work-note journal entries for an incident.

    Returns a chronological list of ``{"type", "text", "created_by",
    "created_on"}`` dicts (oldest-first).
    """
    params: Dict[str, Any] = {
        "sysparm_query": (
            f"element_id={sys_id}^name=incident"
            f"^element=comments^ORelement=work_notes"
        ),
        "sysparm_fields": "element,value,sys_created_on,sys_created_by",
        "sysparm_orderby": "sys_created_on",
        "sysparm_limit": limit,
    }
    url = f"{instance_url}/api/now/table/sys_journal_field"

    async with create_async_client() as client:
        resp = await client.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    entries: List[Dict[str, str]] = []
    for raw in body.get("result", []):
        element = raw.get("element", "")
        entries.append({
            "type": "comment" if element == "comments" else "work_note",
            "text": raw.get("value", ""),
            "created_by": raw.get("sys_created_by", ""),
            "created_on": raw.get("sys_created_on", ""),
        })
    return entries


async def _resolve_user(
    name: str,
    token: str,
    instance_url: str,
) -> str:
    """Look up a ServiceNow user by display name and return their sys_id.

    Tries exact match first, then STARTSWITH fallback.  Raises ``ValueError``
    when no match is found so the caller gets a clear error message.
    """
    url = f"{instance_url}/api/now/table/sys_user"
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    for query in (f"name={name}", f"nameLIKE{name}"):
        params: Dict[str, Any] = {
            "sysparm_query": query,
            "sysparm_limit": 1,
            "sysparm_fields": "sys_id,name,email",
        }
        async with create_async_client() as client:
            resp = await client.get(url, params=params, headers=headers)
            if resp.is_error:
                LOGGER.error(
                    "servicenow_user_lookup_http_error",
                    name=name,
                    status=resp.status_code,
                    body=resp.text[:500],
                )
                resp.raise_for_status()
            body = resp.json()
        results = body.get("result", [])
        if results:
            LOGGER.info("servicenow_user_resolved", name=name, query=query, sys_id=results[0]["sys_id"])
            return results[0]["sys_id"]

    LOGGER.warning("servicenow_user_not_found", name=name)
    raise ValueError(
        f"User '{name}' not found in ServiceNow. "
        f"Please enter the caller's exact full name as it appears in ServiceNow."
    )


# ── get_incident ─────────────────────────────────────────────────────

async def tool_get_incident(
    number: str,
) -> dict:
    """Retrieve full details and comment history for a single ServiceNow incident.

    Use this tool after narrowing down the incident (e.g. via list_incidents)
    or when the user provides a known incident number.  The response includes
    the incident record plus all customer-visible comments and internal work
    notes in chronological order.

    Args:
        number: The incident number (e.g. INC0010006).
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    LOGGER.info("servicenow_get_incident", number=number)

    raw = await _resolve_incident(number, token, settings.instance_url)
    incident = _simplify_incident(raw)

    # Extract sys_id (raw value, not display value)
    sys_id = raw.get("sys_id")
    if isinstance(sys_id, dict):
        sys_id = sys_id.get("value", sys_id.get("display_value"))

    journal = await _fetch_journal(sys_id, token, settings.instance_url)

    return {
        "incident": incident,
        "journal": journal,
        "journal_count": len(journal),
        "link": f"{settings.instance_url}/nav_to.do?uri=incident.do?sys_id={sys_id}",
    }


# ── update_incident ──────────────────────────────────────────────────

async def tool_update_incident(
    number: str,
    # ── Self-service fields ──────────────────────────────
    short_description: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    urgency: Optional[str] = None,
    comments: Optional[str] = None,
    state: Optional[str] = None,
    # ── Service-desk fields ──────────────────────────────
    impact: Optional[str] = None,
    assignment_group: Optional[str] = None,
    assigned_to: Optional[str] = None,
    contact_type: Optional[str] = None,
    work_notes: Optional[str] = None,
    service: Optional[str] = None,
    service_offering: Optional[str] = None,
    configuration_item: Optional[str] = None,
    close_code: Optional[str] = None,
    close_notes: Optional[str] = None,
) -> dict:
    """Update an existing ServiceNow incident.

    Only the *number* is required — include only the fields you want to change.
    To add a customer-visible comment use *comments*; for an internal note use
    *work_notes*.  The response returns the updated incident record and its
    full comment/work-note journal so the user can see the conversation history.

    Self-service fields: short_description, description, category, subcategory,
    urgency, comments, state.  Service-desk fields: impact, assignment_group,
    assigned_to, contact_type, work_notes, service, service_offering,
    configuration_item, close_code, close_notes.

    Args:
        number: The incident number to update (e.g. INC0010006).
        short_description: Updated summary of the issue.
        description: Updated detailed explanation.
        category: Updated category.
        subcategory: Updated subcategory.
        urgency: 1 = High, 2 = Medium, 3 = Low.
        comments: A new customer-visible comment to append.
        state: Transition the incident state: new, in_progress, on_hold,
            resolved, closed, or canceled.
        impact: 1 = High, 2 = Medium, 3 = Low.
        assignment_group: Name of the support group.
        assigned_to: Display name of the assignee.
        contact_type: Channel (phone, email, self-service, walk-in).
        work_notes: A new internal work note to append.
        service: Business service affected.
        service_offering: Specific service offering.
        configuration_item: Related configuration item.
        close_code: Closure code (when resolving/closing).
        close_notes: Closure notes (when resolving/closing).
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    # Resolve the incident to get sys_id
    raw = await _resolve_incident(number, token, settings.instance_url)
    sys_id = raw.get("sys_id")
    if isinstance(sys_id, dict):
        sys_id = sys_id.get("value", sys_id.get("display_value"))

    # Build PATCH payload — only include fields that were explicitly provided
    payload: Dict[str, Any] = {}

    _field_map: Dict[str, Optional[str]] = {
        "short_description": short_description,
        "description": description,
        "category": category,
        "subcategory": subcategory,
        "urgency": urgency,
        "impact": impact,
        "comments": comments,
        "work_notes": work_notes,
        "assignment_group": assignment_group,
        "assigned_to": assigned_to,
        "contact_type": contact_type,
        "cmdb_ci": configuration_item,
        "business_service": service,
        "service_offering": service_offering,
        "close_code": close_code,
        "close_notes": close_notes,
    }
    for field, value in _field_map.items():
        if value is not None and value != "":
            payload[field] = value

    # Handle state separately — accept friendly names
    if state:
        code = _STATE_MAP.get(state.lower().strip(), state)
        payload["state"] = code

    if not payload:
        # Nothing to update — just return current state + journal
        incident = _simplify_incident(raw)
        journal = await _fetch_journal(sys_id, token, settings.instance_url)
        return {
            "updated": False,
            "message": "No fields provided to update.",
            "incident": incident,
            "journal": journal,
            "journal_count": len(journal),
            "link": f"{settings.instance_url}/nav_to.do?uri=incident.do?sys_id={sys_id}",
        }

    url = f"{settings.instance_url}/api/now/table/incident/{sys_id}"

    LOGGER.info(
        "servicenow_update_incident",
        number=number,
        sys_id=sys_id,
        fields=list(payload.keys()),
    )

    try:
        async with create_async_client(timeout=60.0) as client:
            resp = await client.patch(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            if not resp.is_success:
                body_text = resp.text[:500]
                LOGGER.error(
                    "servicenow_update_incident_http_error",
                    status_code=resp.status_code,
                    body=body_text,
                )
                return {"updated": False, "error": f"HTTP {resp.status_code}: {body_text}"}
            body = resp.json()
    except Exception as exc:
        LOGGER.error("servicenow_update_incident_error", error=str(exc))
        return {"updated": False, "error": str(exc)}

    updated_raw = body.get("result", {})
    incident = _simplify_incident(updated_raw)

    # Fetch journal *after* the update so the new comment/work_note appears
    journal = await _fetch_journal(sys_id, token, settings.instance_url)

    return {
        "updated": True,
        "number": number,
        "fields_changed": list(payload.keys()),
        "incident": incident,
        "journal": journal,
        "journal_count": len(journal),
        "link": f"{settings.instance_url}/nav_to.do?uri=incident.do?sys_id={sys_id}",
    }


async def tool_create_incident(
    short_description: str,
    caller: str,
    description: Optional[str] = None,
    category: Optional[str] = None,
    subcategory: Optional[str] = None,
    urgency: Optional[str] = None,
    impact: Optional[str] = None,
    comments: Optional[str] = None,
    # ── Service-desk fields (optional expansion) ────────────
    assignment_group: Optional[str] = None,
    assigned_to: Optional[str] = None,
    contact_type: Optional[str] = None,
    service: Optional[str] = None,
    service_offering: Optional[str] = None,
    configuration_item: Optional[str] = None,
) -> Dict:
    """Create a new ServiceNow incident.

    Both *short_description* and *caller* are required.  The *caller* is the
    full display name of the person reporting the issue (e.g. the current
    user); the tool resolves it to a ServiceNow sys_id automatically.

    Self-service fields: short_description, caller, description, category,
    subcategory, urgency, and comments.  Service-desk fields add:
    assignment_group, assigned_to, impact, contact_type, service,
    service_offering, and configuration_item.

    Args:
        short_description: Brief summary of the issue (required).
        caller: Full display name of the person reporting the issue (required).
            The tool looks up the matching ServiceNow user automatically.
        description: Detailed explanation of the issue.
        category: Category such as inquiry, software, hardware, network, database.
        subcategory: Subcategory under the selected category.
        urgency: 1 = High, 2 = Medium, 3 = Low (default 3).
        impact: 1 = High, 2 = Medium, 3 = Low (default 3).
        comments: Initial customer-visible comment.
        assignment_group: Name of the support group to assign.
        assigned_to: Display name of the individual assignee.
        contact_type: How the incident was reported (phone, email, self-service, walk-in).
        service: Business service affected.
        service_offering: Specific service offering.
        configuration_item: Configuration item related to the incident.
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    # Build the payload — caller_id resolved inside the try block below
    payload: Dict[str, Any] = {
        "short_description": short_description,
    }

    _optional: Dict[str, Optional[str]] = {
        "description": description,
        "category": category,
        "subcategory": subcategory,
        "urgency": urgency,
        "impact": impact,
        "comments": comments,
        "assignment_group": assignment_group,
        "assigned_to": assigned_to,
        "contact_type": contact_type,
        "cmdb_ci": configuration_item,   # SN field name
        "business_service": service,      # SN field name
        "service_offering": service_offering,
    }
    for field, value in _optional.items():
        if value is not None and value != "":
            payload[field] = value

    url = f"{settings.instance_url}/api/now/table/incident"

    LOGGER.info("servicenow_create_incident", caller=caller, fields=list(payload.keys()))

    try:
        # Resolve caller display name → sys_user sys_id
        caller_sys_id = await _resolve_user(caller, token, settings.instance_url)
        payload["caller_id"] = caller_sys_id

        async with create_async_client(timeout=60.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            if resp.is_error:
                LOGGER.error(
                    "servicenow_create_incident_http_error",
                    status=resp.status_code,
                    body=resp.text[:1000],
                    caller=caller,
                )
                resp.raise_for_status()
            body = resp.json()

    except ValueError as exc:
        LOGGER.error("servicenow_create_incident_user_error", caller=caller, error=str(exc))
        return {"created": False, "error": str(exc)}
    except Exception as exc:
        LOGGER.error("servicenow_create_incident_error", caller=caller, error=str(exc), exc_info=True)
        return {"created": False, "error": f"Failed to create incident: {exc}"}

    created = body.get("result", {})

    return {
        "created": True,
        "number": created.get("number"),
        "sys_id": created.get("sys_id"),
        "short_description": created.get("short_description"),
        "caller": caller,
        "state": created.get("state"),
        "priority": created.get("priority"),
        "urgency": created.get("urgency"),
        "impact": created.get("impact"),
        "category": created.get("category"),
        "assigned_to": created.get("assigned_to"),
        "assignment_group": created.get("assignment_group"),
        "opened_at": created.get("opened_at"),
        "link": f"{settings.instance_url}/nav_to.do?uri=incident.do?sys_id={created.get('sys_id')}",
    }


# ── Task & Approval MCP tool wrappers ────────────────────────────────


async def tool_list_tasks(
    limit: int = 50,
) -> Dict:
    """List active ServiceNow tasks assigned to the current user.

    Queries the ServiceNow task table which spans all task-derived tables
    (incidents, changes, problems, etc.).  Returns active tasks ordered by
    most recently updated.

    Args:
        limit: Maximum number of tasks to return (default 50, max 100).
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    safe_limit = max(1, min(int(limit), 100))
    url = f"{settings.instance_url}/api/now/table/task"
    params: Dict[str, Any] = {
        "sysparm_query": "active=true^ORDERBYDESCsys_updated_on",
        "sysparm_limit": safe_limit,
        "sysparm_fields": _TASK_FIELDS,
        "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
    }

    LOGGER.info("servicenow_list_tasks", limit=safe_limit)

    async with create_async_client() as client:
        resp = await client.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    tasks = []
    for raw in body.get("result", []):
        tasks.append(
            {
                "sys_id": _dv(raw.get("sys_id")),
                "number": _dv(raw.get("number")),
                "short_description": _dv(raw.get("short_description")),
                "description": _dv(raw.get("description")),
                "state": _dv(raw.get("state")),
                "priority": _dv(raw.get("priority")),
                "assigned_to": _dv(raw.get("assigned_to")),
                "opened_at": _dv(raw.get("opened_at")),
                "sys_created_on": _dv(raw.get("sys_created_on")),
                "link": (
                    f"{settings.instance_url}/nav_to.do"
                    f"?uri=task.do?sys_id={_dv(raw.get('sys_id'))}"
                ),
            }
        )

    return {
        "total_returned": len(tasks),
        "tasks": tasks,
    }


async def tool_list_approvals(
    limit: int = 50,
) -> Dict:
    """List pending ServiceNow approvals from the sysapproval_approver table.

    Returns approvals in "requested" state, ordered by most recently created.

    Args:
        limit: Maximum number of approvals to return (default 50, max 100).
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    safe_limit = max(1, min(int(limit), 100))
    url = f"{settings.instance_url}/api/now/table/sysapproval_approver"
    params: Dict[str, Any] = {
        "sysparm_query": "state=requested^ORDERBYDESCsys_created_on",
        "sysparm_limit": safe_limit,
        "sysparm_fields": _APPROVAL_FIELDS,
        "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
    }

    LOGGER.info("servicenow_list_approvals", limit=safe_limit)

    async with create_async_client() as client:
        resp = await client.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    approvals = []
    for raw in body.get("result", []):
        approvals.append(
            {
                "sys_id": _dv(raw.get("sys_id")),
                "state": _dv(raw.get("state")),
                "approver": _dv(raw.get("approver")),
                "source_table": _dv(raw.get("source_table")),
                "document_id": _dv(raw.get("document_id")),
                "sys_created_on": _dv(raw.get("sys_created_on")),
                "comments": _dv(raw.get("comments")),
                "link": (
                    f"{settings.instance_url}/nav_to.do"
                    f"?uri=sysapproval_approver.do"
                    f"?sys_id={_dv(raw.get('sys_id'))}"
                ),
            }
        )

    return {
        "total_returned": len(approvals),
        "approvals": approvals,
    }


async def tool_get_approval(
    sys_id: str,
) -> Dict:
    """Get full details of a single ServiceNow approval by its sys_id.

    Returns approver, state, source table, document information, and comments.

    Args:
        sys_id: The sys_id of the approval record.
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    LOGGER.info("servicenow_get_approval", sys_id=sys_id)

    url = f"{settings.instance_url}/api/now/table/sysapproval_approver/{sys_id}"
    params: Dict[str, Any] = {
        "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
    }

    async with create_async_client() as client:
        resp = await client.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    raw = body.get("result", {})
    return {
        "sys_id": sys_id,
        "state": _dv(raw.get("state")),
        "approver": _dv(raw.get("approver")),
        "source_table": _dv(raw.get("source_table")),
        "document_id": _dv(raw.get("document_id")),
        "sys_created_on": _dv(raw.get("sys_created_on")),
        "sys_updated_on": _dv(raw.get("sys_updated_on")),
        "comments": _dv(raw.get("comments")),
        "link": (
            f"{settings.instance_url}/nav_to.do"
            f"?uri=sysapproval_approver.do?sys_id={sys_id}"
        ),
    }


async def tool_approve_reject(
    sys_id: str,
    decision: str,
    comment: str = "",
) -> Dict:
    """Approve or reject a ServiceNow approval.

    Updates the approval record state in the sysapproval_approver table.

    Args:
        sys_id: The sys_id of the approval record.
        decision: Either 'approve' or 'reject'.
        comment: Optional comment to attach to the approval decision.
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    if decision not in ("approve", "reject"):
        return {"error": "decision must be 'approve' or 'reject'"}

    state = "approved" if decision == "approve" else "rejected"
    url = f"{settings.instance_url}/api/now/table/sysapproval_approver/{sys_id}"
    payload: Dict[str, Any] = {"state": state}
    if comment:
        payload["comments"] = comment

    LOGGER.info(
        "servicenow_approve_reject",
        sys_id=sys_id,
        decision=decision,
        state=state,
    )

    try:
        async with create_async_client(timeout=60.0) as client:
            resp = await client.patch(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            if not resp.is_success:
                body_text = resp.text[:500]
                LOGGER.error(
                    "servicenow_approve_reject_http_error",
                    status_code=resp.status_code,
                    body=body_text,
                )
                return {"success": False, "error": f"HTTP {resp.status_code}: {body_text}"}
            body = resp.json()
    except Exception as exc:
        LOGGER.error("servicenow_approve_reject_error", error=str(exc))
        return {"success": False, "error": str(exc)}

    updated = body.get("result", {})
    return {
        "success": True,
        "decision": decision,
        "sys_id": sys_id,
        "new_state": _dv(updated.get("state")),
        "link": (
            f"{settings.instance_url}/nav_to.do"
            f"?uri=sysapproval_approver.do?sys_id={sys_id}"
        ),
    }


# ── Form-show helpers (GET-pattern, widget submits the POST) ────────

async def tool_show_create_incident_form(
    short_description: Optional[str] = None,
    caller: Optional[str] = None,
    description: Optional[str] = None,
    category: Optional[str] = None,
    urgency: Optional[str] = None,
    impact: Optional[str] = None,
) -> Dict:
    """Show the create-incident form widget.

    Returns pre-fill data so the widget can populate the form.  The user
    completes and submits the form inside the widget — this tool does not
    create the incident directly.

    Args:
        short_description: Optional pre-fill for the issue summary.
        caller: Optional pre-fill for the caller's display name.
        description: Optional detailed description to pre-fill.
        category: Optional category to pre-select.
        urgency: Optional urgency pre-fill (1=High, 2=Medium, 3=Low).
        impact: Optional impact pre-fill (1=High, 2=Medium, 3=Low).
    """
    prefill: Dict[str, Any] = {}
    if short_description:
        prefill["short_description"] = short_description
    if caller:
        prefill["caller"] = caller
    if description:
        prefill["description"] = description
    if category:
        prefill["category"] = category
    if urgency:
        prefill["urgency"] = urgency
    if impact:
        prefill["impact"] = impact

    return {
        "_widget_hint": "The form is ready. Acknowledge with one short sentence (e.g. 'Here is the incident creation form.').",
        **prefill,
    }


async def tool_show_update_incident_form(
    number: str,
) -> Dict:
    """Fetch an incident and show the update-incident form widget.

    Retrieves the current state of the incident and renders the update form
    pre-populated with existing values.  The user edits fields and clicks
    Submit inside the widget — this tool does not modify the incident.

    Args:
        number: The incident number to load (e.g. INC0010006).
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    LOGGER.info("servicenow_show_update_incident_form", number=number)

    raw = await _resolve_incident(number, token, settings.instance_url)
    incident = _simplify_incident(raw)

    sys_id = raw.get("sys_id")
    if isinstance(sys_id, dict):
        sys_id = sys_id.get("value", sys_id.get("display_value"))

    return {
        "_widget_hint": f"The form for incident {number} is ready. Acknowledge with one short sentence (e.g. 'Here is the update form for incident {number}.').",
        "incident": incident,
        "link": f"{settings.instance_url}/nav_to.do?uri=incident.do?sys_id={sys_id}",
    }


# ── Tool registry (follows Workday pattern) ─────────────────────────

SERVICENOW_TOOL_SPECS: list[dict] = [
    {
        "name": "list_incidents",
        "summary": (
            "Search and list ServiceNow incidents. Supports filtering by free-text "
            "search, incident number, category, state, priority, assigned user, "
            "and active status. Returns up to 100 incidents per call. "
            "Results are rendered as an interactive widget."
        ),
        "func": tool_list_incidents,
        "annotations": {
            "readOnlyHint": True,
        },
        "meta": {
            "openai/outputTemplate": "ui://widget/incident-list.html",
            "openai/toolInvocation/invoking": "Loading incidents\u2026",
            "openai/toolInvocation/invoked": "Incidents ready.",
        },
    },
    {
        "name": "show_create_incident_form",
        "summary": (
            "Show the incident creation form. Pass any known details (short_description, "
            "caller, description, category, urgency, impact) to pre-fill the form. "
            "The widget handles submission."
        ),
        "func": tool_show_create_incident_form,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/create-incident.html",
            "openai/toolInvocation/invoking": "Loading incident form\u2026",
            "openai/toolInvocation/invoked": "Incident form ready.",
        },
    },
    {
        "name": "create_incident",
        "summary": (
            "Create a new ServiceNow incident. Called by the create-incident widget when the user clicks Submit. "
            "Use show_create_incident_form to display the form first."
        ),
        "func": tool_create_incident,
        "annotations": {
            "readOnlyHint": False,
        },
        "meta": {
            "openai/outputTemplate": "ui://widget/create-incident.html",
            "openai/toolInvocation/invoking": "Creating incident\u2026",
            "openai/toolInvocation/invoked": "Incident created.",
        },
    },
    {
        "name": "show_update_incident_form",
        "summary": (
            "Fetch an incident and show the update form. Provide the incident number "
            "(e.g. INC0010006) to load current values into an editable widget. "
            "The widget handles submission."
        ),
        "func": tool_show_update_incident_form,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/update-incident.html",
            "openai/toolInvocation/invoking": "Loading incident for editing\u2026",
            "openai/toolInvocation/invoked": "Update form ready.",
        },
    },
    {
        "name": "get_incident",
        "summary": (
            "Retrieve full details and comment/work-note history for a single "
            "ServiceNow incident by its number (e.g. INC0010006). Use this to "
            "show the user an incident's current state and conversation history."
        ),
        "func": tool_get_incident,
    },
    {
        "name": "update_incident",
        "summary": (
            "Update an existing ServiceNow incident. Called by the update-incident widget when the user clicks Submit. "
            "Use show_update_incident_form first to load the incident."
        ),
        "func": tool_update_incident,
    },
    {
        "name": "list_tasks",
        "summary": (
            "List active ServiceNow tasks. Queries the task table which spans "
            "all task-derived tables (incidents, changes, problems, etc.). "
            "Returns active tasks ordered by most recently updated."
        ),
        "func": tool_list_tasks,
        "annotations": {
            "readOnlyHint": True,
        },
    },
    {
        "name": "list_approvals",
        "summary": (
            "List pending ServiceNow approvals from the sysapproval_approver "
            "table. Returns approvals in 'requested' state, ordered by most "
            "recently created."
        ),
        "func": tool_list_approvals,
        "annotations": {
            "readOnlyHint": True,
        },
    },
    {
        "name": "get_approval",
        "summary": (
            "Get full details of a single ServiceNow approval by its sys_id. "
            "Returns approver, state, source table, document information, "
            "and comments."
        ),
        "func": tool_get_approval,
        "annotations": {
            "readOnlyHint": True,
        },
    },
    {
        "name": "approve_reject",
        "summary": (
            "Approve or reject a ServiceNow approval. Called by the approval-review widget when the user makes a decision."
        ),
        "func": tool_approve_reject,
        "annotations": {
            "readOnlyHint": False,
        },
    },
]


# ── Provider functions for TaskServer integration ───────────────────

# Fields returned for task-table queries
_TASK_FIELDS = ",".join(
    [
        "sys_id",
        "number",
        "short_description",
        "description",
        "state",
        "priority",
        "assigned_to",
        "opened_at",
        "sys_created_on",
        "sys_updated_on",
        "active",
    ]
)

# Fields returned for approval queries
_APPROVAL_FIELDS = ",".join(
    [
        "sys_id",
        "state",
        "approver",
        "source_table",
        "document_id",
        "sys_created_on",
        "sys_updated_on",
        "comments",
    ]
)


async def provider_list_tasks() -> List[Dict[str, Any]]:
    """List ServiceNow 'My work' tasks from the task table.

    Spans multiple tables extending ``task`` (impl notes §4).
    Returns raw ServiceNow data for TaskServer normalization.
    """
    try:
        settings = load_servicenow_settings()
    except Exception:  # noqa: BLE001
        LOGGER.debug("servicenow_settings_not_configured")
        return []

    token = await _get_servicenow_token()
    url = f"{settings.instance_url}/api/now/table/task"
    params: Dict[str, Any] = {
        "sysparm_query": "active=true^ORDERBYDESCsys_updated_on",
        "sysparm_limit": 50,
        "sysparm_fields": _TASK_FIELDS,
        "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
    }

    async with create_async_client() as client:
        resp = await client.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    results = []
    for raw in body.get("result", []):
        results.append(
            {
                "sys_id": _dv(raw.get("sys_id")),
                "number": _dv(raw.get("number")),
                "short_description": _dv(raw.get("short_description")),
                "description": _dv(raw.get("description")),
                "state": _dv(raw.get("state")),
                "priority": _dv(raw.get("priority")),
                "assigned_to": _dv(raw.get("assigned_to")),
                "opened_at": _dv(raw.get("opened_at")),
                "sys_created_on": _dv(raw.get("sys_created_on")),
                "link": (
                    f"{settings.instance_url}/nav_to.do"
                    f"?uri=task.do?sys_id={_dv(raw.get('sys_id'))}"
                ),
            }
        )
    return results


async def provider_list_approvals() -> List[Dict[str, Any]]:
    """List ServiceNow approvals from sysapproval_approver table.

    Approval updates may fail due to dictionary read-only flags or
    field-level ACLs (impl notes §4).
    """
    try:
        settings = load_servicenow_settings()
    except Exception:  # noqa: BLE001
        LOGGER.debug("servicenow_settings_not_configured")
        return []

    token = await _get_servicenow_token()
    url = f"{settings.instance_url}/api/now/table/sysapproval_approver"
    params: Dict[str, Any] = {
        "sysparm_query": "state=requested^ORDERBYDESCsys_created_on",
        "sysparm_limit": 50,
        "sysparm_fields": _APPROVAL_FIELDS,
        "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
    }

    async with create_async_client() as client:
        resp = await client.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    results = []
    for raw in body.get("result", []):
        results.append(
            {
                "sys_id": _dv(raw.get("sys_id")),
                "state": _dv(raw.get("state")),
                "approver": _dv(raw.get("approver")),
                "source_table": _dv(raw.get("source_table")),
                "document_id": _dv(raw.get("document_id")),
                "short_description": _dv(raw.get("document_id")),
                "sys_created_on": _dv(raw.get("sys_created_on")),
                "comments": _dv(raw.get("comments")),
                "link": (
                    f"{settings.instance_url}/nav_to.do"
                    f"?uri=sysapproval_approver.do"
                    f"?sys_id={_dv(raw.get('sys_id'))}"
                ),
            }
        )
    return results


async def provider_get_approval_detail(item_id: str) -> Dict[str, Any]:
    """Fetch approval detail from sysapproval_approver."""
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    url = f"{settings.instance_url}/api/now/table/sysapproval_approver/{item_id}"
    params: Dict[str, Any] = {
        "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
    }

    async with create_async_client() as client:
        resp = await client.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    raw = body.get("result", {})
    return {
        "title": _dv(raw.get("document_id")) or f"Approval {item_id}",
        "summary": _dv(raw.get("comments")) or "",
        "status": _dv(raw.get("state")) or "",
        "approver": _dv(raw.get("approver")),
        "sourceTable": _dv(raw.get("source_table")),
        "documentId": _dv(raw.get("document_id")),
        "sysId": item_id,
        "raw": {k: _dv(v) for k, v in raw.items()},
    }


async def provider_execute_approval(
    item_id: str, decision: str, comment: str = ""
) -> Dict[str, Any]:
    """Approve or reject a ServiceNow approval.

    Updates the ``state`` field on ``sysapproval_approver``.
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    state = "approved" if decision == "approve" else "rejected"
    url = f"{settings.instance_url}/api/now/table/sysapproval_approver/{item_id}"
    payload: Dict[str, Any] = {"state": state}
    if comment:
        payload["comments"] = comment

    LOGGER.info(
        "servicenow_execute_approval",
        item_id=item_id,
        decision=decision,
        state=state,
    )

    async with create_async_client(timeout=60.0) as client:
        resp = await client.patch(
            url,
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    updated = body.get("result", {})
    return {
        "success": True,
        "decision": decision,
        "sysId": item_id,
        "newState": _dv(updated.get("state")),
    }


# ── Service Catalog (sn_sc) ──────────────────────────────────────────


async def tool_list_catalog_items(
    search: Optional[str] = None,
    category_sys_id: Optional[str] = None,
    catalog_sys_id: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """List items from the ServiceNow Service Catalog.

    When *search* is provided the Table API (sc_cat_item) is used with
    server-side LIKE filtering on name and short_description and a minimal
    sysparm_fields projection.  This avoids transferring unused fields and
    lets ServiceNow do the filtering before sending data, which is
    significantly faster than the sn_sc/servicecatalog/items scripted REST
    endpoint + client-side filtering.

    When browsing without a search term the sn_sc/servicecatalog/items
    endpoint is used because it honours catalog/category path parameters.

    The sysparm_search / sysparm_text_search full-text parameters are
    intentionally NOT used — they trigger a slow server-side catalog scan
    that reliably exceeds the 30-second request timeout on large instances.

    Each returned item includes a sys_id that can be passed directly to
    get_catalog_item or order_catalog_item.

    Args:
        search: Free-text search string to filter catalog items by name or
            short description (server-side LIKE, case-insensitive).
        category_sys_id: Filter to a specific category by its sys_id.
        catalog_sys_id: Filter to a specific catalog by its sys_id.
        limit: Maximum items to return (default 20, max 100).
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    safe_limit = max(1, min(int(limit), 100))
    auth_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    LOGGER.info("servicenow_list_catalog_items", search=search, limit=safe_limit)

    if search:
        # ── Fast path: Table API with server-side LIKE filtering ──────
        # nameLIKE / short_descriptionLIKE are server-side, so only
        # matching rows are returned.  sysparm_fields limits the payload
        # to the handful of fields we actually use.
        query_parts = [
            f"nameLIKE{search}",
            f"^ORshort_descriptionLIKE{search}",
            "^active=true",
        ]
        if category_sys_id:
            query_parts.append(f"^category={category_sys_id}")
        if catalog_sys_id:
            query_parts.append(f"^sc_catalogs={catalog_sys_id}")

        params: Dict[str, Any] = {
            "sysparm_query": "".join(query_parts),
            "sysparm_fields": "sys_id,name,short_description,category,price,picture,type",
            "sysparm_limit": safe_limit,
            "sysparm_display_value": "true",
        }

        url = f"{settings.instance_url}/api/now/table/sc_cat_item"

        async with create_async_client() as client:
            resp = await client.get(url, params=params, headers=auth_headers)
            resp.raise_for_status()
            body = resp.json()

        items = []
        for raw in body.get("result", []):
            pic = raw.get("picture", "")
            if pic and not pic.startswith("http"):
                pic = f"{settings.instance_url}/{pic}"
            cat = raw.get("category", "")
            # Table API returns display value as string when sysparm_display_value=true
            if isinstance(cat, dict):
                cat = cat.get("display_value") or cat.get("value") or ""
            items.append(
                {
                    "sys_id": raw.get("sys_id", ""),
                    "name": raw.get("name", ""),
                    "short_description": raw.get("short_description", ""),
                    "category": cat,
                    "price": raw.get("price", ""),
                    "picture": pic,
                    "type": raw.get("type", ""),
                    "link": (
                        f"{settings.instance_url}/nav_to.do"
                        f"?uri=com.glideapp.servicecatalog_cat_item_view.do"
                        f"?v=1&sysparm_id={raw.get('sys_id', '')}"
                    ),
                }
            )

        return {
            "total_returned": len(items),
            "items": items,
        }

    # ── Browse path: catalog API (no search term) ─────────────────────
    params = {
        "sysparm_limit": safe_limit,
    }
    if category_sys_id:
        params["sysparm_category"] = category_sys_id
    if catalog_sys_id:
        params["sysparm_catalog"] = catalog_sys_id

    url = f"{settings.instance_url}/api/sn_sc/servicecatalog/items"

    async with create_async_client() as client:
        resp = await client.get(url, params=params, headers=auth_headers)
        resp.raise_for_status()
        body = resp.json()

    items = []
    for raw in body.get("result", []):
        pic = raw.get("picture", "")
        if pic and not pic.startswith("http"):
            pic = f"{settings.instance_url}/{pic}"
        cat = raw.get("category", "")
        if isinstance(cat, dict):
            cat = cat.get("title", "")
        items.append(
            {
                "sys_id": raw.get("sys_id", ""),
                "name": raw.get("name", ""),
                "short_description": raw.get("short_description", ""),
                "category": cat,
                "catalogs": [
                    c.get("title", "") for c in (raw.get("catalogs") or [])
                    if isinstance(c, dict)
                ],
                "price": raw.get("price", ""),
                "picture": pic,
                "type": raw.get("type", ""),
                "show_quantity": raw.get("show_quantity", False),
                "show_delivery_time": raw.get("show_delivery_time", False),
                "delivery_time": raw.get("delivery_time", ""),
                "link": (
                    f"{settings.instance_url}/nav_to.do"
                    f"?uri=com.glideapp.servicecatalog_cat_item_view.do"
                    f"?v=1&sysparm_id={raw.get('sys_id', '')}"
                ),
            }
        )
        if len(items) >= safe_limit:
            break

    return {
        "total_returned": len(items),
        "items": items,
    }


async def tool_list_catalog_categories(
    catalog_sys_id: Optional[str] = None,
    limit: int = 40,
) -> Dict[str, Any]:
    """List categories in the ServiceNow Service Catalog.

    Use this to help the user browse the catalog structure before listing
    items within a specific category.

    Args:
        catalog_sys_id: Filter to a specific catalog by its sys_id.
            If not provided, returns categories from the default catalog.
        limit: Maximum categories to return (default 40, max 100).
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    safe_limit = max(1, min(int(limit), 100))

    # If no catalog specified, get the default catalog first
    if not catalog_sys_id:
        cat_url = f"{settings.instance_url}/api/sn_sc/servicecatalog/catalogs"
        async with create_async_client() as client:
            resp = await client.get(
                cat_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
            resp.raise_for_status()
            cat_body = resp.json()
        catalogs = cat_body.get("result", [])
        if isinstance(catalogs, dict):
            catalogs = catalogs.get("catalogs", [])
        if not catalogs and isinstance(cat_body.get("catalogs"), list):
            catalogs = cat_body.get("catalogs", [])
        if catalogs:
            raw_catalog_id = catalogs[0].get("sys_id", "")
            if isinstance(raw_catalog_id, dict):
                raw_catalog_id = (
                    raw_catalog_id.get("value")
                    or raw_catalog_id.get("display_value")
                    or ""
                )
            catalog_sys_id = str(raw_catalog_id or "")

    if not catalog_sys_id:
        return {"total_returned": 0, "categories": []}

    # The ServiceNow API requires the catalog sys_id in the URL path:
    # /api/sn_sc/servicecatalog/{catalogId}/categories
    # Using it as a sysparm_catalog query parameter returns a 400.
    url = f"{settings.instance_url}/api/sn_sc/servicecatalog/{catalog_sys_id}/categories"
    params: Dict[str, Any] = {
        "sysparm_limit": safe_limit,
    }

    LOGGER.info("servicenow_list_catalog_categories", catalog=catalog_sys_id)

    async with create_async_client() as client:
        resp = await client.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    categories = []
    raw_categories = body.get("result", [])
    if isinstance(raw_categories, dict):
        raw_categories = raw_categories.get("categories", [])
    if not raw_categories and isinstance(body.get("categories"), list):
        raw_categories = body.get("categories", [])

    for raw in raw_categories:
        category_sys_id = raw.get("sys_id", "")
        if isinstance(category_sys_id, dict):
            category_sys_id = (
                category_sys_id.get("value")
                or category_sys_id.get("display_value")
                or ""
            )
        categories.append(
            {
                "sys_id": category_sys_id,
                "title": raw.get("title") or raw.get("name", ""),
                "description": raw.get("description") or raw.get("short_description", ""),
                "item_count": raw.get("count", raw.get("item_count", 0)),
            }
        )

    return {
        "total_returned": len(categories),
        "categories": categories,
    }


def _validate_sys_id(sys_id: str) -> Optional[Dict[str, Any]]:
    """Return an error dict if *sys_id* is not a valid 32-char hex ServiceNow ID, else None."""
    if not re.fullmatch(r"[0-9a-f]{32}", sys_id.strip(), re.IGNORECASE):
        return {
            "error": (
                f"Invalid sys_id '{sys_id}': ServiceNow sys_ids must be exactly "
                "32 hexadecimal characters. Use the sys_id exactly as returned by "
                "list_catalog_items without adding or removing any characters."
            )
        }
    return None


async def tool_get_catalog_item(
    sys_id: str,
) -> Dict[str, Any]:
    """Get full details of a ServiceNow catalog item including its form.

    Returns the item metadata (name, description, picture, delivery time)
    plus the complete variable/field definitions needed to render the order
    form, including UI policies that control field visibility.

    The widget renders the dynamic form and handles ordering.

    Args:
        sys_id: The sys_id of the catalog item.
    """
    err = _validate_sys_id(sys_id)
    if err:
        return err
    sys_id = sys_id.strip().lower()

    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    url = f"{settings.instance_url}/api/sn_sc/servicecatalog/items/{sys_id}"

    LOGGER.info("servicenow_get_catalog_item", sys_id=sys_id)

    async with create_async_client() as client:
        resp = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    result = body.get("result", {})

    # Build picture URL if present
    picture = result.get("picture", "")
    if picture and not picture.startswith("http"):
        picture = f"{settings.instance_url}/{picture}"

    # Simplify variables for the widget
    variables = []
    for v in result.get("variables", []):
        var_entry: Dict[str, Any] = {
            "id": v.get("id", ""),
            "name": v.get("name", ""),
            "label": v.get("label", ""),
            "type": v.get("type"),
            "friendly_type": v.get("friendly_type", ""),
            "mandatory": v.get("mandatory", False),
            "read_only": v.get("read_only", False),
            "render_label": v.get("render_label", True),
            "value": v.get("value", ""),
            "displayvalue": v.get("displayvalue", ""),
            "help_text": v.get("help_text", ""),
            "max_length": v.get("max_length", 0),
            "order": v.get("order", 0),
            "active": v.get("active", True),
        }
        # Include choices if present
        if v.get("choices"):
            var_entry["choices"] = v["choices"]
        # Include reference info for reference fields (type 8)
        if v.get("reference"):
            var_entry["reference"] = v["reference"]
        if v.get("ref_qual"):
            var_entry["ref_qual"] = v["ref_qual"]
        variables.append(var_entry)

    # UI policies
    ui_policies = result.get("ui_policy", [])

    item_data = {
        "_widget_hint": "The catalog item form is ready. Acknowledge with one short sentence (e.g. \"Here's the order form.\").",
        "sys_id": result.get("sys_id", sys_id),
        "name": result.get("name", ""),
        "short_description": result.get("short_description", ""),
        "description": result.get("description", ""),
        "picture": picture,
        "type": result.get("type", ""),
        "show_quantity": result.get("show_quantity", False),
        "show_delivery_time": result.get("show_delivery_time", False),
        "delivery_time": result.get("delivery_time", ""),
        "show_price": result.get("show_price", False),
        "price": result.get("price", ""),
        "mandatory_attachment": result.get("mandatory_attachment", False),
        "category": result.get("category", {}).get("title", "") if isinstance(result.get("category"), dict) else "",
        "catalogs": [
            c.get("title", "") for c in (result.get("catalogs") or [])
            if isinstance(c, dict)
        ],
        "variables": variables,
        "ui_policy": ui_policies,
        "link": (
            f"{settings.instance_url}/nav_to.do"
            f"?uri=com.glideapp.servicecatalog_cat_item_view.do"
            f"?v=1&sysparm_id={sys_id}"
        ),
        "instance_url": settings.instance_url,
    }

    return item_data


async def tool_order_catalog_item(
    sys_id: str,
    variables: Optional[Dict[str, Any]] = None,
    quantity: int = 1,
) -> Dict[str, Any]:
    """Order a catalog item from the ServiceNow Service Catalog.

    Submits an order request for the specified catalog item.  Variable
    values should be a dict mapping variable names to their selected values.

    Args:
        sys_id: The sys_id of the catalog item to order.
        variables: A dict of variable name → value pairs for the order form fields.
        quantity: Quantity to order (default 1).
    """
    err = _validate_sys_id(sys_id)
    if err:
        return err
    sys_id = sys_id.strip().lower()

    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    url = f"{settings.instance_url}/api/sn_sc/servicecatalog/items/{sys_id}/order_now"

    payload: Dict[str, Any] = {
        "sysparm_quantity": max(1, int(quantity)),
    }
    if variables:
        payload["variables"] = variables

    LOGGER.info(
        "servicenow_order_catalog_item",
        sys_id=sys_id,
        quantity=quantity,
        variable_count=len(variables) if variables else 0,
    )

    try:
        async with create_async_client(timeout=60.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            if not resp.is_success:
                body_text = resp.text[:500]
                LOGGER.error(
                    "servicenow_order_catalog_item_http_error",
                    status_code=resp.status_code,
                    body=body_text,
                )
                return {"success": False, "error": f"HTTP {resp.status_code}: {body_text}"}
            body = resp.json()
    except Exception as exc:
        LOGGER.error("servicenow_order_catalog_item_error", error=str(exc))
        return {"success": False, "error": str(exc)}

    result = body.get("result", {})
    request_number = result.get("request_number", "")
    request_id = result.get("request_id", "")

    return {
        "success": True,
        "request_number": request_number,
        "request_id": request_id,
        "sys_id": sys_id,
        "quantity": quantity,
        "link": (
            f"{settings.instance_url}/nav_to.do"
            f"?uri=sc_request.do?sys_id={request_id}"
        ) if request_id else "",
    }


async def tool_add_to_cart(
    sys_id: str,
    variables: Optional[Dict[str, Any]] = None,
    quantity: int = 1,
) -> Dict[str, Any]:
    """Add a catalog item to the ServiceNow shopping cart.

    Adds the item with the specified variable values and quantity.
    The user can continue browsing and add more items before checking out.

    Args:
        sys_id: The sys_id of the catalog item to add.
        variables: A dict of variable name → value pairs for the form fields.
        quantity: Quantity to add (default 1).
    """
    err = _validate_sys_id(sys_id)
    if err:
        return err
    sys_id = sys_id.strip().lower()

    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    url = f"{settings.instance_url}/api/sn_sc/servicecatalog/items/{sys_id}/add_to_cart"

    payload: Dict[str, Any] = {
        "sysparm_quantity": max(1, int(quantity)),
    }
    if variables:
        payload["variables"] = variables

    LOGGER.info(
        "servicenow_add_to_cart",
        sys_id=sys_id,
        quantity=quantity,
    )

    try:
        async with create_async_client(timeout=60.0) as client:
            resp = await client.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            if not resp.is_success:
                body_text = resp.text[:500]
                LOGGER.error(
                    "servicenow_add_to_cart_http_error",
                    status_code=resp.status_code,
                    body=body_text,
                )
                return {"success": False, "error": f"HTTP {resp.status_code}: {body_text}"}
            body = resp.json()
    except Exception as exc:
        LOGGER.error("servicenow_add_to_cart_error", error=str(exc))
        return {"success": False, "error": str(exc)}

    result = body.get("result", {})
    LOGGER.info("servicenow_add_to_cart_response", result_keys=list(result.keys()) if isinstance(result, dict) else type(result).__name__, result_preview=str(result)[:500])

    # The ServiceNow add_to_cart API may return the full cart or just the cart_item.
    # Normalise: prefer cart_item_id at top level, fall back to nested structures.
    cart_item_id = (
        result.get("cart_item_id")
        or result.get("cart_item", {}).get("cart_item_id", "")
        if isinstance(result, dict) else ""
    )

    return {
        "success": True,
        "cart_item_id": cart_item_id,
        "sys_id": sys_id,
        "quantity": quantity,
        "subtotal": result.get("subtotal", "") if isinstance(result, dict) else "",
    }


async def tool_get_cart() -> Dict[str, Any]:
    """Get the current ServiceNow shopping cart contents.

    Returns all items currently in the user's cart with their quantities,
    prices, and the cart total.
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    url = f"{settings.instance_url}/api/sn_sc/servicecatalog/cart"

    LOGGER.info("servicenow_get_cart")

    async with create_async_client() as client:
        resp = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    result = body.get("result", {})
    LOGGER.info("servicenow_get_cart_response", result_keys=list(result.keys()) if isinstance(result, dict) else type(result).__name__, result_preview=str(result)[:500])
    items = []
    # ServiceNow may return items under "items", "cart_items", or as a top-level list
    raw_items = result.get("items") or result.get("cart_items") or []
    if isinstance(result, list):
        raw_items = result
    for raw in raw_items:
        items.append(
            {
                "cart_item_id": raw.get("cart_item_id", ""),
                "name": raw.get("name", ""),
                "quantity": raw.get("quantity", 1),
                "price": raw.get("price", ""),
                "recurring_price": raw.get("recurring_price", ""),
                "subtotal": raw.get("subtotal", ""),
            }
        )

    return {
        "total_items": len(items),
        "subtotal": result.get("subtotal", ""),
        "items": items,
    }


async def tool_checkout_cart() -> Dict[str, Any]:
    """Submit the ServiceNow shopping cart as an order.

    Checks out all items currently in the cart and creates a service request.
    The cart is emptied after successful checkout.
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    url = f"{settings.instance_url}/api/sn_sc/servicecatalog/cart/submit_order"

    LOGGER.info("servicenow_checkout_cart")

    try:
        async with create_async_client(timeout=60.0) as client:
            resp = await client.post(
                url,
                json={},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            if not resp.is_success:
                body_text = resp.text[:500]
                LOGGER.error(
                    "servicenow_checkout_cart_http_error",
                    status_code=resp.status_code,
                    body=body_text,
                )
                return {"success": False, "error": f"HTTP {resp.status_code}: {body_text}"}
            body = resp.json()
    except Exception as exc:
        LOGGER.error("servicenow_checkout_cart_error", error=str(exc))
        return {"success": False, "error": str(exc)}

    result = body.get("result", {})
    request_number = result.get("request_number", "")
    request_id = result.get("request_id", "")

    return {
        "success": True,
        "request_number": request_number,
        "request_id": request_id,
        "link": (
            f"{settings.instance_url}/nav_to.do"
            f"?uri=sc_request.do?sys_id={request_id}"
        ) if request_id else "",
    }


async def tool_delete_cart() -> Dict[str, Any]:
    """Empty the ServiceNow shopping cart.

    Removes all items from the current user's cart.
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    url = f"{settings.instance_url}/api/sn_sc/servicecatalog/cart"

    LOGGER.info("servicenow_delete_cart")

    try:
        async with create_async_client(timeout=60.0) as client:
            resp = await client.delete(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
            if not resp.is_success:
                body_text = resp.text[:500]
                LOGGER.error(
                    "servicenow_delete_cart_http_error",
                    status_code=resp.status_code,
                    body=body_text,
                )
                return {"success": False, "error": f"HTTP {resp.status_code}: {body_text}"}
    except Exception as exc:
        LOGGER.error("servicenow_delete_cart_error", error=str(exc))
        return {"success": False, "error": str(exc)}

    return {"success": True, "message": "Cart emptied."}


async def tool_remove_cart_item(
    cart_item_id: str,
) -> Dict[str, Any]:
    """Remove a single item from the ServiceNow shopping cart.

    Uses the cart item ID returned by ``get_cart``.

    Args:
        cart_item_id: ServiceNow cart item ID to remove.
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    if not cart_item_id:
        return {"success": False, "error": "cart_item_id is required"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    candidate_urls = [
        f"{settings.instance_url}/api/sn_sc/servicecatalog/cart/{cart_item_id}",
        f"{settings.instance_url}/api/sn_sc/servicecatalog/cart/item/{cart_item_id}",
    ]

    LOGGER.info("servicenow_remove_cart_item", cart_item_id=cart_item_id)

    last_error = ""
    for url in candidate_urls:
        try:
            async with create_async_client(timeout=60.0) as client:
                resp = await client.delete(url, headers=headers)
                if resp.is_success:
                    return {
                        "success": True,
                        "cart_item_id": cart_item_id,
                    }
                last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
        except Exception as exc:
            last_error = str(exc)

    return {
        "success": False,
        "cart_item_id": cart_item_id,
        "error": (
            f"Unable to remove cart item {cart_item_id}. "
            f"Last error: {last_error}"
        ),
    }


async def tool_list_my_requests(
    limit: int = 20,
    state: Optional[str] = None,
) -> Dict[str, Any]:
    """List the current user's ServiceNow service requests and their items.

    Queries sc_request (REQ) and sc_req_item (RITM) for requests opened by
    the authenticated user.  Returns a flat list of requested items (RITMs)
    with their parent request number, catalog item name, current state, and
    key dates.

    Args:
        limit: Maximum number of requested items to return (default 20, max 50).
        state: Optional state filter. One of: open, in_progress, closed_complete,
               closed_incomplete, closed_cancelled.
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    safe_limit = max(1, min(int(limit), 50))

    # ── State code map for sc_req_item ──────────────────────────────
    _RITM_STATE_MAP = {
        "open": "1",
        "in_progress": "2",
        "closed_complete": "3",
        "closed_incomplete": "4",
        "closed_cancelled": "7",
    }

    # Build query – "opened_by=javascript:gs.getUserID()" works in table API
    query_parts = ["opened_by=javascript:gs.getUserID()^ORDERBYDESCsys_created_on"]
    if state:
        code = _RITM_STATE_MAP.get(state.lower().replace(" ", "_"))
        if code:
            query_parts = [query_parts[0].replace("^ORD", f"^state={code}^ORD")]

    ritm_url = f"{settings.instance_url}/api/now/table/sc_req_item"
    params: Dict[str, Any] = {
        "sysparm_limit": safe_limit,
        "sysparm_display_value": "all",
        "sysparm_fields": ",".join([
            "sys_id",
            "number",
            "request",
            "cat_item",
            "short_description",
            "state",
            "stage",
            "quantity",
            "price",
            "sys_created_on",
            "due_date",
            "estimated_delivery",
            "assigned_to",
            "assignment_group",
            "opened_by",
            "active",
        ]),
        "sysparm_query": "^".join(query_parts),
    }

    LOGGER.info("servicenow_list_my_requests", limit=safe_limit, state=state)

    async with create_async_client() as client:
        resp = await client.get(
            ritm_url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    items = []
    for raw in body.get("result", []):
        req_ref = raw.get("request", {})
        req_number = _dv(req_ref) if isinstance(req_ref, dict) else (req_ref or "")
        cat_ref = raw.get("cat_item", {})
        cat_name = _dv(cat_ref) if isinstance(cat_ref, dict) else (cat_ref or "")
        items.append({
            "ritm_number": _dv(raw.get("number")),
            "request_number": req_number,
            "catalog_item": cat_name,
            "short_description": _dv(raw.get("short_description")),
            "state": _dv(raw.get("state")),
            "stage": _dv(raw.get("stage")),
            "quantity": _dv(raw.get("quantity")),
            "price": _dv(raw.get("price")),
            "opened_by": _dv(raw.get("opened_by")),
            "created_on": _dv(raw.get("sys_created_on")),
            "due_date": _dv(raw.get("due_date")),
            "estimated_delivery": _dv(raw.get("estimated_delivery")),
            "assigned_to": _dv(raw.get("assigned_to")),
            "assignment_group": _dv(raw.get("assignment_group")),
        })

    return {
        "total_returned": len(items),
        "requested_items": items,
    }


async def tool_search_reference_values(
    table: str,
    search: str,
    limit: int = 20,
) -> Dict[str, Any]:
    """Search a ServiceNow table for reference field values.

    Used to look up values for reference-type catalog variables where
    choices come from a table (e.g. cmdb_ci, sys_user, etc.).
    Returns matching records with sys_id and display value.

    Args:
        table: The ServiceNow table to search (e.g. cmdb_ci, sys_user).
        search: Search text to match against the table's display field.
        limit: Maximum results to return (default 20, max 50).
    """
    settings = load_servicenow_settings()
    token = await _get_servicenow_token()

    safe_limit = max(1, min(int(limit), 50))

    # Use the display_value endpoint with search
    url = f"{settings.instance_url}/api/now/table/{table}"
    params: Dict[str, Any] = {
        "sysparm_limit": safe_limit,
        "sysparm_fields": "sys_id,name",
        "sysparm_display_value": "true",
        "sysparm_query": f"nameLIKE{search}^ORDERBYname",
    }

    LOGGER.info("servicenow_search_reference", table=table, search=search)

    async with create_async_client() as client:
        resp = await client.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    results = []
    for raw in body.get("result", []):
        results.append(
            {
                "sys_id": raw.get("sys_id", ""),
                "name": raw.get("name", ""),
            }
        )

    return {
        "table": table,
        "total_returned": len(results),
        "results": results,
    }


# ── Service Catalog tool specs (appended after definitions) ──────────
SERVICENOW_TOOL_SPECS.extend(
    [
        {
            "name": "list_catalog_items",
            "summary": (
                "Search and list items from the ServiceNow Service Catalog. "
                "When a search term is provided, uses the Table API with server-side LIKE "
                "filtering on name and short_description — faster and more complete than "
                "a page-then-filter approach. "
                "Supports filtering by category_sys_id or catalog_sys_id. "
                "Each result includes a sys_id that can be passed directly to "
                "get_catalog_item or order_catalog_item without any further lookup. "
                "If zero results are returned, do NOT retry with the same or similar search; "
                "instead call list_catalog_categories to browse by category and pass "
                "category_sys_id here."
            ),
            "func": tool_list_catalog_items,
            "annotations": {
                "readOnlyHint": True,
            },
            "meta": {
                "openai/outputTemplate": "ui://widget/catalog-list.html",
                "openai/toolInvocation/invoking": "Loading catalog items\u2026",
                "openai/toolInvocation/invoked": "Catalog items ready.",
            },
        },
        {
            "name": "list_catalog_categories",
            "summary": (
                "List categories in the ServiceNow Service Catalog. Use this to "
                "help the user explore the catalog structure and find the right "
                "category before listing items."
            ),
            "func": tool_list_catalog_categories,
            "annotations": {
                "readOnlyHint": True,
            },
        },
        {
            "name": "get_catalog_item",
            "summary": (
                "Get full details of a ServiceNow catalog item including its "
                "dynamic order form (variables, choices, UI policies). Renders "
                "an interactive widget where the user can fill in the form, "
                "select a quantity, and order or add to cart."
            ),
            "func": tool_get_catalog_item,
            "annotations": {
                "readOnlyHint": True,
            },
            "meta": {
                "openai/outputTemplate": "ui://widget/catalog-item.html",
                "openai/toolInvocation/invoking": "Loading catalog item\u2026",
                "openai/toolInvocation/invoked": "Catalog item ready.",
            },
        },
        {
            "name": "order_catalog_item",
            "summary": (
                "Submit an order for a ServiceNow catalog item. Called by the catalog-item widget when the user clicks Order Now. "
                "Use get_catalog_item first to display the catalog item."
            ),
            "func": tool_order_catalog_item,
            "annotations": {
                "readOnlyHint": False,
            },
        },
        {
            "name": "add_to_cart",
            "summary": (
                "Add a ServiceNow catalog item to the shopping cart. Called by the catalog-item widget when the user clicks Add to Cart. "
                "Use get_catalog_item first to display the catalog item."
            ),
            "func": tool_add_to_cart,
            "annotations": {
                "readOnlyHint": False,
            },
        },
        {
            "name": "get_cart",
            "summary": (
                "Get the contents of the current ServiceNow shopping cart, "
                "including item names, quantities, prices, and subtotal."
            ),
            "func": tool_get_cart,
            "annotations": {
                "readOnlyHint": True,
            },
            "meta": {
                "openai/outputTemplate": "ui://widget/cart-summary.html",
                "openai/toolInvocation/invoking": "Loading shopping cart\u2026",
                "openai/toolInvocation/invoked": "Shopping cart ready.",
            },
        },
        {
            "name": "checkout_cart",
            "summary": (
                "Submit the ServiceNow shopping cart as an order. Called by the catalog-item widget. "
                "Use get_catalog_item to let the user order via the widget."
            ),
            "func": tool_checkout_cart,
            "annotations": {
                "readOnlyHint": False,
            },
        },
        {
            "name": "delete_cart",
            "summary": (
                "Empty the ServiceNow shopping cart. Called by the catalog-item widget."
            ),
            "func": tool_delete_cart,
            "annotations": {
                "readOnlyHint": False,
            },
        },
        {
            "name": "remove_cart_item",
            "summary": (
                "Remove a single line item from the ServiceNow shopping cart by cart_item_id. "
                "Use get_cart first to discover cart_item_id values."
            ),
            "func": tool_remove_cart_item,
            "annotations": {
                "readOnlyHint": False,
            },
        },
        {
            "name": "list_my_requests",
            "summary": (
                "List the current user's ServiceNow service requests (REQ) and "
                "requested items (RITM) with their catalog item name, state, stage, "
                "quantity, price, and dates. Use this when the user asks what they "
                "have on order, the status of their requests, or wants to track "
                "submitted catalog orders."
            ),
            "func": tool_list_my_requests,
            "annotations": {
                "readOnlyHint": True,
            },
        },
        {
            "name": "search_reference_values",
            "summary": (
                "Search a ServiceNow table for reference field values. Used to "
                "look up values for reference-type catalog variables where choices "
                "come from a table (e.g. cmdb_ci, sys_user). Returns matching "
                "records with sys_id and display value."
            ),
            "func": tool_search_reference_values,
            "annotations": {
                "readOnlyHint": True,
            },
        },
    ]
)
