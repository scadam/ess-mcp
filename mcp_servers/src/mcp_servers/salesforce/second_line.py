"""Second-line Salesforce tools: case comments for the desk's conversation log and its reconciliation sweep."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Optional

from fastmcp import Context

from ..auth import resolve_salesforce_token
from ..http import create_async_client
from ..logging import get_logger
from .tools import _COMPLIANCE_TYPES, _salesforce_post, _sf, _soql_query

LOGGER = get_logger(__name__)
_CASE_ID = re.compile(r"500[A-Za-z0-9]{12}(?:[A-Za-z0-9]{3})?")
_WATERMARK = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z")
_integration: Dict[str, str] = {}


async def _integration_username(ctx: Optional[Context]) -> str:
    token = await resolve_salesforce_token(ctx)
    if token.instance_url not in _integration:
        async with create_async_client(timeout=30.0) as client:
            response = await client.get(f"{token.instance_url}/services/oauth2/userinfo",
                                        headers={"Authorization": f"Bearer {token.access_token}"})
            name = response.json().get("preferred_username", "") if response.is_success else ""
        _integration[token.instance_url] = str(name).lower()
    return _integration[token.instance_url]


def _iso(value: Any) -> str:
    """Salesforce '2026-09-24T12:00:00.000+0000' as a UTC ISO watermark with Z."""
    text = str(value or "")
    return text.replace("+0000", "Z") if text.endswith("+0000") else text


def _epoch_ms(value: str) -> int:
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except ValueError:
        return 0


async def tool_add_case_comment(case_id: str, body: str, public: bool = False,
                                ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Add a comment to a Salesforce case; public comments are visible to the case contact.

    Args:
        case_id: The 15 or 18 character Case Id.
        body: The comment text.
        public: Publish to the contact (true) or keep internal (false).
    """
    if not _CASE_ID.fullmatch(case_id or ""):
        return {"created": False, "error": "A Salesforce Case Id (starting 500) is required."}
    result = await _salesforce_post("/sobjects/CaseComment", {"ParentId": case_id, "CommentBody": body[:3900],
                                                              "IsPublished": bool(public)}, ctx)
    return {"created": bool(result.get("id")), "id": result.get("id"), "case_id": case_id, "public": bool(public)}


async def tool_list_queue_changes(queue: str = "", updated_since: str = "", limit: int = 50,
                                  ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Compliance cases changed since a UTC watermark, oldest first (the desk's reconciliation sweep).

    Args:
        queue: Owner (queue or user) name to restrict to; empty means every open compliance-type case.
        updated_since: UTC ISO watermark such as 2026-09-24T12:00:00.000Z; empty for the last 3 days.
        limit: Maximum records (1-100).
    """
    clauses = ["Type IN (" + ", ".join(f"'{_sf(value)}'" for value in _COMPLIANCE_TYPES) + ")",
               "Origin != 'Email'"]
    if queue:
        clauses.append(f"Owner.Name = '{_sf(queue)}'")
    if updated_since and _WATERMARK.fullmatch(updated_since):
        clauses.append(f"SystemModstamp > {updated_since}")
    else:
        clauses.append("SystemModstamp = LAST_N_DAYS:3")
    rows = await _soql_query(
        "SELECT Id, CaseNumber, Subject, Status, Type, SystemModstamp, CreatedDate, LastModifiedBy.Username, "
        "SuppliedName, SuppliedEmail, Contact.Name, Contact.Email FROM Case WHERE " + " AND ".join(clauses)
        + f" ORDER BY SystemModstamp ASC LIMIT {max(1, min(int(limit), 100))}", ctx)
    integration = await _integration_username(ctx)
    records = []
    for row in rows:
        version = _iso(row.get("SystemModstamp"))
        created = _iso(row.get("CreatedDate"))
        modified_by = str((row.get("LastModifiedBy") or {}).get("Username") or "").lower()
        contact = row.get("Contact") or {}
        new = abs(_epoch_ms(version) - _epoch_ms(created)) < 3000
        records.append({
            "id": row.get("Id"), "number": row.get("CaseNumber"), "title": row.get("Subject"), "status": row.get("Status"),
            "type": row.get("Type"), "version": version, "new": new,
            "updated_by_integration": not new and bool(integration) and modified_by == integration,
            "requester": {"name": contact.get("Name") or row.get("SuppliedName") or "",
                          "email": (contact.get("Email") or row.get("SuppliedEmail") or "").lower()},
            "event_id": f"sf:{row.get('Id')}:{_epoch_ms(version)}"})
    return {"records": records, "count": len(records), "integration_user": integration}


SECOND_LINE_SPECS: list[dict] = [
    {"name": "add_case_comment", "func": tool_add_case_comment,
     "summary": "Add an internal or public comment to a Salesforce case."},
    {"name": "list_queue_changes", "func": tool_list_queue_changes, "annotations": {"readOnlyHint": True},
     "summary": "Compliance cases changed since a UTC watermark, oldest first (reconciliation sweep)."},
]
