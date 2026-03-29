
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastmcp import Context

from ..auth import get_bearer_token, TokenValidationError
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
    ctx: Optional[Context] = None,
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
        priority: Filter by priority (1 = Critical ... 5 = Planning).
        assigned_to: Filter by the display name of the assigned user.
        active: Filter by active status (true or false).
        limit: Maximum number of incidents to return (default 10, max 100).
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

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
    ctx: Optional[Context] = None,
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
    token = get_bearer_token(ctx)

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
    ctx: Optional[Context] = None,
) -> dict:
    """Update an existing ServiceNow incident.

    Only the *number* is required -- include only the fields you want to change.
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
    token = get_bearer_token(ctx)

    # Resolve the incident to get sys_id
    raw = await _resolve_incident(number, token, settings.instance_url)
    sys_id = raw.get("sys_id")
    if isinstance(sys_id, dict):
        sys_id = sys_id.get("value", sys_id.get("display_value"))

    # Build PATCH payload -- only include fields that were explicitly provided
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

    # Handle state separately -- accept friendly names
    if state:
        code = _STATE_MAP.get(state.lower().strip(), state)
        payload["state"] = code

    if not payload:
        # Nothing to update -- just return current state + journal
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
    ctx: Optional[Context] = None,
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
    token = get_bearer_token(ctx)

    # Build the payload -- caller_id resolved inside the try block below
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
    ctx: Optional[Context] = None,
) -> Dict:
    """List active ServiceNow tasks assigned to the current user.

    Queries the ServiceNow task table which spans all task-derived tables
    (incidents, changes, problems, etc.).  Returns active tasks ordered by
    most recently updated.

    Args:
        limit: Maximum number of tasks to return (default 50, max 100).
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

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
    ctx: Optional[Context] = None,
) -> Dict:
    """List pending ServiceNow approvals from the sysapproval_approver table.

    Returns approvals in "requested" state, ordered by most recently created.

    Args:
        limit: Maximum number of approvals to return (default 50, max 100).
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

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
    ctx: Optional[Context] = None,
) -> Dict:
    """Get full details of a single ServiceNow approval by its sys_id.

    Returns approver, state, source table, document information, and comments.

    Args:
        sys_id: The sys_id of the approval record.
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

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
    ctx: Optional[Context] = None,
) -> Dict:
    """Approve or reject a ServiceNow approval.

    Updates the approval record state in the sysapproval_approver table.

    Args:
        sys_id: The sys_id of the approval record.
        decision: Either 'approve' or 'reject'.
        comment: Optional comment to attach to the approval decision.
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

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
    ctx: Optional[Context] = None,
) -> Dict:
    """Show the create-incident form widget.

    Returns pre-fill data so the widget can populate the form.  The user
    completes and submits the form inside the widget -- this tool does not
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
    ctx: Optional[Context] = None,
) -> Dict:
    """Fetch an incident and show the update-incident form widget.

    Retrieves the current state of the incident and renders the update form
    pre-populated with existing values.  The user edits fields and clicks
    Submit inside the widget -- this tool does not modify the incident.

    Args:
        number: The incident number to load (e.g. INC0010006).
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

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


async def provider_list_tasks(ctx: Optional[Context] = None) -> List[Dict[str, Any]]:
    """List ServiceNow 'My work' tasks from the task table.

    Spans multiple tables extending ``task`` (impl notes S4).
    Returns raw ServiceNow data for TaskServer normalization.
    """
    try:
        settings = load_servicenow_settings()
    except Exception:  # noqa: BLE001
        LOGGER.debug("servicenow_settings_not_configured")
        return []

    token = get_bearer_token(ctx)
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


async def provider_list_approvals(ctx: Optional[Context] = None) -> List[Dict[str, Any]]:
    """List ServiceNow approvals from sysapproval_approver table.

    Approval updates may fail due to dictionary read-only flags or
    field-level ACLs (impl notes S4).
    """
    try:
        settings = load_servicenow_settings()
    except Exception:  # noqa: BLE001
        LOGGER.debug("servicenow_settings_not_configured")
        return []

    token = get_bearer_token(ctx)
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


async def provider_get_approval_detail(item_id: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Fetch approval detail from sysapproval_approver."""
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

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
    item_id: str, decision: str, comment: str = "", ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """Approve or reject a ServiceNow approval.

    Updates the ``state`` field on ``sysapproval_approver``.
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

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
    ctx: Optional[Context] = None,
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
    intentionally NOT used -- they trigger a slow server-side catalog scan
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
    token = get_bearer_token(ctx)

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
    ctx: Optional[Context] = None,
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
    token = get_bearer_token(ctx)

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
    ctx: Optional[Context] = None,
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
    token = get_bearer_token(ctx)

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
    ctx: Optional[Context] = None,
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
    token = get_bearer_token(ctx)

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
    ctx: Optional[Context] = None,
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
    token = get_bearer_token(ctx)

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


async def tool_get_cart(ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Get the current ServiceNow shopping cart contents.

    Returns all items currently in the user's cart with their quantities,
    prices, and the cart total.
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

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


async def tool_checkout_cart(ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Submit the ServiceNow shopping cart as an order.

    Checks out all items currently in the cart and creates a service request.
    The cart is emptied after successful checkout.
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

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


async def tool_delete_cart(ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Empty the ServiceNow shopping cart.

    Removes all items from the current user's cart.
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

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
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Remove a single item from the ServiceNow shopping cart.

    Uses the cart item ID returned by ``get_cart``.

    Args:
        cart_item_id: ServiceNow cart item ID to remove.
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

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
    ctx: Optional[Context] = None,
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
    token = get_bearer_token(ctx)

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
    ctx: Optional[Context] = None,
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
    token = get_bearer_token(ctx)

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


# ── Change Request fields ────────────────────────────────────────────
_CHANGE_REQUEST_FIELDS = ",".join(
    [
        "sys_id",
        "number",
        "short_description",
        "type",
        "state",
        "risk",
        "impact",
        "category",
        "assignment_group",
        "assigned_to",
        "planned_start_date",
        "planned_end_date",
    ]
)

# ── Knowledge article fields ────────────────────────────────────────
_KB_FIELDS = ",".join(
    [
        "sys_id",
        "number",
        "short_description",
        "text",
        "category",
        "published",
        "author",
    ]
)

# ── Problem record fields ───────────────────────────────────────────
_PROBLEM_FIELDS = ",".join(
    [
        "sys_id",
        "number",
        "short_description",
        "state",
        "priority",
        "category",
        "assigned_to",
    ]
)

# ── CMDB CI fields ──────────────────────────────────────────────────
_CMDB_CI_FIELDS = ",".join(
    [
        "sys_id",
        "name",
        "asset_tag",
        "sys_class_name",
        "category",
        "subcategory",
        "operational_status",
        "assigned_to",
        "support_group",
        "short_description",
    ]
)


async def tool_list_change_requests(
    search_text: Optional[str] = None,
    state: Optional[str] = None,
    risk: Optional[str] = None,
    category: Optional[str] = None,
    assigned_to: Optional[str] = None,
    limit: int = 10,
    ctx: Optional[Context] = None,
) -> Dict:
    """Search and list ServiceNow change requests.

    All filter parameters are optional; when none are provided the most recent
    change requests are returned.

    Args:
        search_text: Free-text search across number, short_description.
        state: Filter by state (e.g. New, Assess, Authorize, Scheduled,
            Implement, Review, Closed, Canceled).
        risk: Filter by risk level (e.g. high, moderate, low).
        category: Filter by category.
        assigned_to: Filter by display name of the assigned user.
        limit: Maximum number of results to return (default 10, max 100).
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

    clauses: List[str] = []
    if search_text:
        clauses.append(
            f"short_descriptionLIKE{search_text}"
            f"^ORnumberLIKE{search_text}"
        )
    if state:
        clauses.append(f"state={state}")
    if risk:
        clauses.append(f"risk={risk}")
    if category:
        clauses.append(f"category={category}")
    if assigned_to:
        clauses.append(f"assigned_to.name={assigned_to}")

    query = "^".join(clauses)
    safe_limit = max(1, min(int(limit), 100))

    params: Dict[str, Any] = {
        "sysparm_limit": safe_limit,
        "sysparm_fields": _CHANGE_REQUEST_FIELDS,
        "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
        "sysparm_orderby": "sys_updated_on",
        "sysparm_orderbydesc": "sys_updated_on",
    }
    if query:
        params["sysparm_query"] = query

    url = f"{settings.instance_url}/api/now/table/change_request"

    LOGGER.info("servicenow_list_change_requests", query=query, limit=safe_limit)

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

    changes = []
    for raw in body.get("result", []):
        changes.append({k: _dv(raw.get(k)) for k in _CHANGE_REQUEST_FIELDS.split(",")})

    return {
        "total_returned": len(changes),
        "change_requests": changes,
    }


async def tool_get_change_request(
    sys_id: str,
    ctx: Optional[Context] = None,
) -> Dict:
    """Retrieve full details of a single ServiceNow change request.

    Args:
        sys_id: The sys_id of the change request.
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

    url = f"{settings.instance_url}/api/now/table/change_request/{sys_id}"
    params: Dict[str, Any] = {
        "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
    }

    LOGGER.info("servicenow_get_change_request", sys_id=sys_id)

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
    record = {k: _dv(raw.get(k)) for k in _CHANGE_REQUEST_FIELDS.split(",")}

    return {
        "change_request": record,
        "link": f"{settings.instance_url}/nav_to.do?uri=change_request.do?sys_id={sys_id}",
    }


async def tool_create_change_request(
    short_description: str,
    type: Optional[str] = None,
    category: Optional[str] = None,
    risk: Optional[str] = None,
    impact: Optional[str] = None,
    assignment_group: Optional[str] = None,
    assigned_to: Optional[str] = None,
    description: Optional[str] = None,
    planned_start_date: Optional[str] = None,
    planned_end_date: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict:
    """Create a new ServiceNow change request.

    Args:
        short_description: Brief summary of the change (required).
        type: Change type – Normal, Standard, or Emergency.
        category: Category for the change.
        risk: Risk level (e.g. high, moderate, low).
        impact: Impact level (1 = High, 2 = Medium, 3 = Low).
        assignment_group: Name of the assignment group.
        assigned_to: Display name of the assignee.
        description: Detailed description of the change.
        planned_start_date: Planned start date/time (ISO 8601 or ServiceNow format).
        planned_end_date: Planned end date/time (ISO 8601 or ServiceNow format).
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

    payload: Dict[str, Any] = {"short_description": short_description}
    _optional: Dict[str, Optional[str]] = {
        "type": type,
        "category": category,
        "risk": risk,
        "impact": impact,
        "assignment_group": assignment_group,
        "assigned_to": assigned_to,
        "description": description,
        "planned_start_date": planned_start_date,
        "planned_end_date": planned_end_date,
    }
    for field, value in _optional.items():
        if value is not None and value != "":
            payload[field] = value

    url = f"{settings.instance_url}/api/now/table/change_request"

    LOGGER.info("servicenow_create_change_request", fields=list(payload.keys()))

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
            if resp.is_error:
                LOGGER.error(
                    "servicenow_create_change_request_http_error",
                    status=resp.status_code,
                    body=resp.text[:1000],
                )
                resp.raise_for_status()
            body = resp.json()
    except Exception as exc:
        LOGGER.error("servicenow_create_change_request_error", error=str(exc), exc_info=True)
        return {"created": False, "error": f"Failed to create change request: {exc}"}

    created = body.get("result", {})

    return {
        "created": True,
        "number": created.get("number"),
        "sys_id": created.get("sys_id"),
        "short_description": created.get("short_description"),
        "type": created.get("type"),
        "state": created.get("state"),
        "risk": created.get("risk"),
        "link": f"{settings.instance_url}/nav_to.do?uri=change_request.do?sys_id={created.get('sys_id')}",
    }


async def tool_search_knowledge(
    search_text: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 10,
    ctx: Optional[Context] = None,
) -> Dict:
    """Search the ServiceNow knowledge base for articles.

    Args:
        search_text: Free-text search across article title and body.
        category: Filter by knowledge category.
        limit: Maximum number of articles to return (default 10, max 100).
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

    clauses: List[str] = []
    if search_text:
        clauses.append(
            f"short_descriptionLIKE{search_text}"
            f"^ORtextLIKE{search_text}"
        )
    if category:
        clauses.append(f"category={category}")
    # Only return published articles by default
    clauses.append("workflow_state=published")

    query = "^".join(clauses)
    safe_limit = max(1, min(int(limit), 100))

    params: Dict[str, Any] = {
        "sysparm_limit": safe_limit,
        "sysparm_fields": _KB_FIELDS,
        "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
        "sysparm_orderby": "sys_updated_on",
        "sysparm_orderbydesc": "sys_updated_on",
    }
    if query:
        params["sysparm_query"] = query

    url = f"{settings.instance_url}/api/now/table/kb_knowledge"

    LOGGER.info("servicenow_search_knowledge", query=query, limit=safe_limit)

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

    articles = []
    for raw in body.get("result", []):
        articles.append({k: _dv(raw.get(k)) for k in _KB_FIELDS.split(",")})

    return {
        "total_returned": len(articles),
        "articles": articles,
    }


async def tool_get_knowledge_article(
    sys_id: str,
    ctx: Optional[Context] = None,
) -> Dict:
    """Retrieve a single knowledge article by its sys_id.

    Args:
        sys_id: The sys_id of the knowledge article.
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

    url = f"{settings.instance_url}/api/now/table/kb_knowledge/{sys_id}"
    params: Dict[str, Any] = {
        "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
    }

    LOGGER.info("servicenow_get_knowledge_article", sys_id=sys_id)

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
    article = {k: _dv(raw.get(k)) for k in _KB_FIELDS.split(",")}

    return {
        "article": article,
        "link": f"{settings.instance_url}/nav_to.do?uri=kb_knowledge.do?sys_id={sys_id}",
    }


async def tool_list_problems(
    search_text: Optional[str] = None,
    state: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    assigned_to: Optional[str] = None,
    limit: int = 10,
    ctx: Optional[Context] = None,
) -> Dict:
    """Search and list ServiceNow problem records.

    All filter parameters are optional; when none are provided the most recent
    problems are returned.

    Args:
        search_text: Free-text search across number and short_description.
        state: Filter by state.
        priority: Filter by priority (1 = Critical ... 5 = Planning).
        category: Filter by category.
        assigned_to: Filter by display name of the assigned user.
        limit: Maximum number of results to return (default 10, max 100).
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

    clauses: List[str] = []
    if search_text:
        clauses.append(
            f"short_descriptionLIKE{search_text}"
            f"^ORnumberLIKE{search_text}"
        )
    if state:
        clauses.append(f"state={state}")
    if priority:
        clauses.append(f"priority={priority}")
    if category:
        clauses.append(f"category={category}")
    if assigned_to:
        clauses.append(f"assigned_to.name={assigned_to}")

    query = "^".join(clauses)
    safe_limit = max(1, min(int(limit), 100))

    params: Dict[str, Any] = {
        "sysparm_limit": safe_limit,
        "sysparm_fields": _PROBLEM_FIELDS,
        "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
        "sysparm_orderby": "sys_updated_on",
        "sysparm_orderbydesc": "sys_updated_on",
    }
    if query:
        params["sysparm_query"] = query

    url = f"{settings.instance_url}/api/now/table/problem"

    LOGGER.info("servicenow_list_problems", query=query, limit=safe_limit)

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

    problems = []
    for raw in body.get("result", []):
        problems.append({k: _dv(raw.get(k)) for k in _PROBLEM_FIELDS.split(",")})

    return {
        "total_returned": len(problems),
        "problems": problems,
    }


async def tool_create_problem(
    short_description: str,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    assignment_group: Optional[str] = None,
    assigned_to: Optional[str] = None,
    description: Optional[str] = None,
    impact: Optional[str] = None,
    urgency: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict:
    """Create a new ServiceNow problem record.

    Args:
        short_description: Brief summary of the problem (required).
        category: Category for the problem.
        priority: Priority level (1 = Critical ... 5 = Planning).
        assignment_group: Name of the assignment group.
        assigned_to: Display name of the assignee.
        description: Detailed description of the problem.
        impact: Impact level (1 = High, 2 = Medium, 3 = Low).
        urgency: Urgency level (1 = High, 2 = Medium, 3 = Low).
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

    payload: Dict[str, Any] = {"short_description": short_description}
    _optional: Dict[str, Optional[str]] = {
        "category": category,
        "priority": priority,
        "assignment_group": assignment_group,
        "assigned_to": assigned_to,
        "description": description,
        "impact": impact,
        "urgency": urgency,
    }
    for field, value in _optional.items():
        if value is not None and value != "":
            payload[field] = value

    url = f"{settings.instance_url}/api/now/table/problem"

    LOGGER.info("servicenow_create_problem", fields=list(payload.keys()))

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
            if resp.is_error:
                LOGGER.error(
                    "servicenow_create_problem_http_error",
                    status=resp.status_code,
                    body=resp.text[:1000],
                )
                resp.raise_for_status()
            body = resp.json()
    except Exception as exc:
        LOGGER.error("servicenow_create_problem_error", error=str(exc), exc_info=True)
        return {"created": False, "error": f"Failed to create problem: {exc}"}

    created = body.get("result", {})

    return {
        "created": True,
        "number": created.get("number"),
        "sys_id": created.get("sys_id"),
        "short_description": created.get("short_description"),
        "state": created.get("state"),
        "priority": created.get("priority"),
        "link": f"{settings.instance_url}/nav_to.do?uri=problem.do?sys_id={created.get('sys_id')}",
    }


async def tool_get_cmdb_ci(
    sys_id: str,
    ctx: Optional[Context] = None,
) -> Dict:
    """Retrieve a CMDB Configuration Item by its sys_id.

    Args:
        sys_id: The sys_id of the configuration item.
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

    url = f"{settings.instance_url}/api/now/table/cmdb_ci/{sys_id}"
    params: Dict[str, Any] = {
        "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
    }

    LOGGER.info("servicenow_get_cmdb_ci", sys_id=sys_id)

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
    ci = {k: _dv(raw.get(k)) for k in _CMDB_CI_FIELDS.split(",")}

    return {
        "ci": ci,
        "link": f"{settings.instance_url}/nav_to.do?uri=cmdb_ci.do?sys_id={sys_id}",
    }


async def tool_list_cmdb_cis(
    search_text: Optional[str] = None,
    sys_class_name: Optional[str] = None,
    category: Optional[str] = None,
    operational_status: Optional[str] = None,
    limit: int = 10,
    ctx: Optional[Context] = None,
) -> Dict:
    """Search CMDB configuration items.

    All filter parameters are optional; when none are provided the most recent
    CIs are returned.

    Args:
        search_text: Free-text search across name and short_description.
        sys_class_name: Filter by CI class (e.g. cmdb_ci_server,
            cmdb_ci_computer, cmdb_ci_vm_instance).
        category: Filter by category.
        operational_status: Filter by operational status (1 = Operational,
            2 = Non-Operational, etc.).
        limit: Maximum number of results to return (default 10, max 100).
    """
    settings = load_servicenow_settings()
    token = get_bearer_token(ctx)

    clauses: List[str] = []
    if search_text:
        clauses.append(
            f"nameLIKE{search_text}"
            f"^ORshort_descriptionLIKE{search_text}"
        )
    if sys_class_name:
        clauses.append(f"sys_class_name={sys_class_name}")
    if category:
        clauses.append(f"category={category}")
    if operational_status:
        clauses.append(f"operational_status={operational_status}")

    query = "^".join(clauses)
    safe_limit = max(1, min(int(limit), 100))

    params: Dict[str, Any] = {
        "sysparm_limit": safe_limit,
        "sysparm_fields": _CMDB_CI_FIELDS,
        "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
        "sysparm_orderby": "name",
    }
    if query:
        params["sysparm_query"] = query

    url = f"{settings.instance_url}/api/now/table/cmdb_ci"

    LOGGER.info("servicenow_list_cmdb_cis", query=query, limit=safe_limit)

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

    cis = []
    for raw in body.get("result", []):
        cis.append({k: _dv(raw.get(k)) for k in _CMDB_CI_FIELDS.split(",")})

    return {
        "total_returned": len(cis),
        "configuration_items": cis,
    }


# ── Service Catalog tool specs (appended after definitions) ──────────
SERVICENOW_TOOL_SPECS.extend(
    [
        {
            "name": "list_catalog_items",
            "summary": (
                "Search and list items from the ServiceNow Service Catalog. "
                "When a search term is provided, uses the Table API with server-side LIKE "
                "filtering on name and short_description -- faster and more complete than "
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


# ── Change Request, Knowledge, Problem, CMDB tool specs ──────────────
SERVICENOW_TOOL_SPECS.extend(
    [
        {
            "name": "list_change_requests",
            "summary": (
                "Search and list ServiceNow change requests. Supports filtering "
                "by free-text search, state, risk level, category, and assigned "
                "user. Returns up to 100 change requests per call."
            ),
            "func": tool_list_change_requests,
            "annotations": {
                "readOnlyHint": True,
            },
        },
        {
            "name": "get_change_request",
            "summary": (
                "Retrieve full details of a single ServiceNow change request "
                "by its sys_id."
            ),
            "func": tool_get_change_request,
            "annotations": {
                "readOnlyHint": True,
            },
        },
        {
            "name": "create_change_request",
            "summary": (
                "Create a new ServiceNow change request. Requires a short "
                "description; optionally set type (Normal, Standard, Emergency), "
                "category, risk, impact, assignment group, and planned dates."
            ),
            "func": tool_create_change_request,
            "annotations": {
                "readOnlyHint": False,
            },
        },
        {
            "name": "search_knowledge",
            "summary": (
                "Search the ServiceNow knowledge base for published articles. "
                "Supports free-text search across article titles and body text, "
                "and optional category filtering."
            ),
            "func": tool_search_knowledge,
            "annotations": {
                "readOnlyHint": True,
            },
        },
        {
            "name": "get_knowledge_article",
            "summary": (
                "Retrieve a single ServiceNow knowledge article by its sys_id. "
                "Returns the full article text, category, author, and publish "
                "status."
            ),
            "func": tool_get_knowledge_article,
            "annotations": {
                "readOnlyHint": True,
            },
        },
        {
            "name": "list_problems",
            "summary": (
                "Search and list ServiceNow problem records. Supports filtering "
                "by free-text search, state, priority, category, and assigned "
                "user. Returns up to 100 problems per call."
            ),
            "func": tool_list_problems,
            "annotations": {
                "readOnlyHint": True,
            },
        },
        {
            "name": "create_problem",
            "summary": (
                "Create a new ServiceNow problem record. Requires a short "
                "description; optionally set category, priority, assignment "
                "group, description, impact, and urgency."
            ),
            "func": tool_create_problem,
            "annotations": {
                "readOnlyHint": False,
            },
        },
        {
            "name": "get_cmdb_ci",
            "summary": (
                "Retrieve a CMDB configuration item by its sys_id. Returns "
                "name, class, category, operational status, and assignment "
                "details."
            ),
            "func": tool_get_cmdb_ci,
            "annotations": {
                "readOnlyHint": True,
            },
        },
        {
            "name": "list_cmdb_cis",
            "summary": (
                "Search CMDB configuration items. Supports free-text search "
                "across name and description, and filtering by CI class, "
                "category, and operational status."
            ),
            "func": tool_list_cmdb_cis,
            "annotations": {
                "readOnlyHint": True,
            },
        },
    ]
)


# ── Manager-focused tool functions ───────────────────────────────────


async def tool_get_team_incidents(
    assigned_to_group: str = "",
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Get a team incident workload dashboard for managers.

    Queries active incidents assigned to the manager's team members,
    summarizing totals by priority, state, and assignee.

    Args:
        assigned_to_group: Optional assignment group name to filter by.
            When empty, returns active incidents across all groups.
    """
    try:
        settings = load_servicenow_settings()
        token = get_bearer_token(ctx)

        query_parts = ["active=true"]
        if assigned_to_group:
            query_parts.append(f"assignment_group.name={assigned_to_group}")
        query_parts.append("ORDERBYDESCsys_updated_on")
        query = "^".join(query_parts)

        url = f"{settings.instance_url}/api/now/table/incident"
        params: Dict[str, Any] = {
            "sysparm_query": query,
            "sysparm_limit": 200,
            "sysparm_fields": _INCIDENT_FIELDS,
            "sysparm_display_value": "all",
            "sysparm_exclude_reference_link": "true",
        }

        LOGGER.info(
            "servicenow_get_team_incidents",
            assigned_to_group=assigned_to_group,
        )

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

        # --- build summary breakdowns ---
        by_priority: Dict[str, int] = {}
        by_state: Dict[str, int] = {}
        by_assignee: Dict[str, int] = {}

        for inc in incidents:
            p = inc.get("priority") or "Unknown"
            by_priority[p] = by_priority.get(p, 0) + 1

            s = inc.get("state") or "Unknown"
            by_state[s] = by_state.get(s, 0) + 1

            a = inc.get("assigned_to") or "Unassigned"
            by_assignee[a] = by_assignee.get(a, 0) + 1

        recent_incidents = incidents[:10]

        return {
            "success": True,
            "total_open": len(incidents),
            "by_priority": by_priority,
            "by_state": by_state,
            "by_assignee": by_assignee,
            "recent_incidents": recent_incidents,
            "_instance_url": settings.instance_url,
        }
    except Exception as exc:
        LOGGER.error("servicenow_get_team_incidents_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_team_approvals(
    limit: int = 100,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Get pending approvals grouped for bulk decision-making.

    Lists all pending approvals (state=requested), groups them by source
    table, and includes approval age for each item.

    Args:
        limit: Maximum number of approvals to return (default 100, max 200).
    """
    try:
        settings = load_servicenow_settings()
        token = get_bearer_token(ctx)

        safe_limit = max(1, min(int(limit), 200))
        url = f"{settings.instance_url}/api/now/table/sysapproval_approver"
        params: Dict[str, Any] = {
            "sysparm_query": "state=requested^ORDERBYDESCsys_created_on",
            "sysparm_limit": safe_limit,
            "sysparm_fields": _APPROVAL_FIELDS,
            "sysparm_display_value": "all",
            "sysparm_exclude_reference_link": "true",
        }

        LOGGER.info("servicenow_get_team_approvals", limit=safe_limit)

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

        now = datetime.now(tz=timezone.utc)

        approvals: List[Dict[str, Any]] = []
        by_source_table: Dict[str, List[Dict[str, Any]]] = {}

        for raw in body.get("result", []):
            sys_id = _dv(raw.get("sys_id"))
            source_table = _dv(raw.get("source_table")) or "unknown"
            created_on_str = _dv(raw.get("sys_created_on")) or ""

            age_hours: Optional[float] = None
            if created_on_str:
                try:
                    created_dt = datetime.strptime(
                        created_on_str, "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=timezone.utc)
                    age_hours = round(
                        (now - created_dt).total_seconds() / 3600, 1
                    )
                except ValueError:
                    pass

            approval = {
                "sys_id": sys_id,
                "state": _dv(raw.get("state")),
                "approver": _dv(raw.get("approver")),
                "source_table": source_table,
                "document_id": _dv(raw.get("document_id")),
                "sys_created_on": created_on_str,
                "age_hours": age_hours,
                "comments": _dv(raw.get("comments")),
                "link": (
                    f"{settings.instance_url}/nav_to.do"
                    f"?uri=sysapproval_approver.do"
                    f"?sys_id={sys_id}"
                ),
            }

            approvals.append(approval)
            by_source_table.setdefault(source_table, []).append(approval)

        return {
            "success": True,
            "total_pending": len(approvals),
            "by_source_table": {
                table: {
                    "count": len(items),
                    "approvals": items,
                }
                for table, items in by_source_table.items()
            },
            "approvals": approvals,
        }
    except Exception as exc:
        LOGGER.error("servicenow_get_team_approvals_error", error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Manager-focused tool specs ───────────────────────────────────────
SERVICENOW_TOOL_SPECS.extend(
    [
        {
            "name": "get_team_incidents",
            "summary": (
                "Team incident workload dashboard for managers. Queries active "
                "incidents assigned to team members, with breakdowns by priority, "
                "state, and assignee. Optionally filter by assignment group name. "
                "Returns the top 10 most recent incidents."
            ),
            "func": tool_get_team_incidents,
            "annotations": {
                "readOnlyHint": True,
            },
            "meta": {
                "openai/outputTemplate": "ui://widget/team-incidents.html",
                "openai/toolInvocation/invoking": "Loading team incidents\u2026",
                "openai/toolInvocation/invoked": "Team incidents ready.",
            },
        },
        {
            "name": "get_team_approvals",
            "summary": (
                "Bulk team approvals view for managers. Lists all pending "
                "approvals (state=requested), grouped by source table type, "
                "with approval age in hours. Returns structured data suitable "
                "for batch approve or reject decisions."
            ),
            "func": tool_get_team_approvals,
            "annotations": {
                "readOnlyHint": True,
            },
        },
    ]
)
