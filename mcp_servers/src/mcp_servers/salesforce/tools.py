"""Provides task listing, approval management, and CRUD operations against
the Salesforce REST API using OAuth bearer token passthrough.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastmcp import Context

from ..auth import get_bearer_token
from ..http import create_async_client
from ..logging import get_logger
from ..settings import load_salesforce_settings
import httpx

LOGGER = get_logger(__name__)

_API_VERSION = "v59.0"


def _get_instance_url() -> str:
    """Derive the Salesforce instance URL from settings."""
    settings = load_salesforce_settings()
    domain = settings.domain
    if ".my.salesforce.com" in domain or ".salesforce.com" in domain:
        return f"https://{domain}"
    return f"https://{domain}.my.salesforce.com"


async def _soql_query(query: str, ctx: Optional[Context] = None) -> List[Dict[str, Any]]:
    """Execute a SOQL query and return all records."""
    token = get_bearer_token(ctx)
    instance_url = _get_instance_url()
    url = f"{instance_url}/services/data/{_API_VERSION}/query"

    async with create_async_client() as client:
        resp = await client.get(
            url,
            params={"q": query},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        body = resp.json()

    return body.get("records", [])


async def _salesforce_post(path: str, body: Dict[str, Any], ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Make an authenticated POST request to Salesforce REST API."""
    token = get_bearer_token(ctx)
    instance_url = _get_instance_url()
    url = f"{instance_url}/services/data/{_API_VERSION}{path}"

    async with create_async_client() as client:
        resp = await client.post(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type and resp.content:
            return resp.json()
        return {"success": True}


async def _salesforce_patch(path: str, body: Dict[str, Any], ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Make an authenticated PATCH request to Salesforce REST API."""
    token = get_bearer_token(ctx)
    instance_url = _get_instance_url()
    url = f"{instance_url}/services/data/{_API_VERSION}{path}"

    async with create_async_client() as client:
        resp = await client.patch(
            url,
            json=body,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type and resp.content:
            return resp.json()
        return {"success": True}


async def _salesforce_get(path: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Make an authenticated GET request to Salesforce REST API."""
    token = get_bearer_token(ctx)
    instance_url = _get_instance_url()
    url = f"{instance_url}/services/data/{_API_VERSION}{path}"

    async with create_async_client() as client:
        resp = await client.get(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        resp.raise_for_status()
        return resp.json()


# ── MCP tool functions ──────────────────────────────────────────────


async def tool_list_tasks(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    owner_name: Optional[str] = None,
    limit: int = 20,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List Salesforce tasks.

    Args:
        status: Filter by status (e.g. "Not Started", "In Progress", "Completed").
        priority: Filter by priority (e.g. "High", "Normal", "Low").
        owner_name: Filter by owner name.
        limit: Maximum results (default 20, max 100).
    """
    clauses: List[str] = []
    if status:
        clauses.append(f"Status = '{status}'")
    if priority:
        clauses.append(f"Priority = '{priority}'")
    if owner_name:
        clauses.append(f"Owner.Name = '{owner_name}'")

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    safe_limit = max(1, min(int(limit), 100))

    query = (
        f"SELECT Id, Subject, Status, Priority, Description, ActivityDate, "
        f"CreatedDate, OwnerId, WhoId, WhatId "
        f"FROM Task{where} "
        f"ORDER BY CreatedDate DESC "
        f"LIMIT {safe_limit}"
    )

    LOGGER.info("salesforce_list_tasks", query=query)
    records = await _soql_query(query, ctx)

    return {
        "total": len(records),
        "tasks": records,
    }


async def tool_get_task(task_id: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Get details for a single Salesforce task.

    Args:
        task_id: The Salesforce Task record ID.
    """
    LOGGER.info("salesforce_get_task", task_id=task_id)
    records = await _soql_query(
        f"SELECT Id, Subject, Status, Priority, Description, ActivityDate, "
        f"CreatedDate, OwnerId, WhoId, WhatId, CallType, TaskSubtype "
        f"FROM Task WHERE Id = '{task_id}'"
    , ctx)

    if not records:
        raise ValueError(f"Salesforce Task {task_id} not found")

    return {"task": records[0]}


async def tool_create_task(
    subject: str,
    status: str = "Not Started",
    priority: str = "Normal",
    due_date: Optional[str] = None,
    description: Optional[str] = None,
    what_id: Optional[str] = None,
    who_id: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Create a standalone Salesforce task.

    Args:
        subject: Task subject (required).
        status: Task status (default "Not Started").
        priority: Task priority (default "Normal").
        due_date: Due date in YYYY-MM-DD format.
        description: Additional notes about the task.
        what_id: Related record ID (Account or Opportunity).
        who_id: Related person ID (Contact or Lead).
    """
    payload: Dict[str, Any] = {
        "Subject": subject,
        "Status": status,
        "Priority": priority,
    }
    if due_date:
        payload["ActivityDate"] = due_date
    if description:
        payload["Description"] = description
    if what_id:
        payload["WhatId"] = what_id
    if who_id:
        payload["WhoId"] = who_id

    LOGGER.info("salesforce_create_task", fields=list(payload.keys()))

    try:
        result = await _salesforce_post("/sobjects/Task", payload, ctx)
        task_id = result.get("id", "")
        created: List[Dict[str, Any]] = []
        if task_id:
            try:
                created = await _soql_query(
                    f"SELECT {_TASK_FIELDS} FROM Task WHERE Id = '{_sf(task_id)}'"
                , ctx)
            except Exception:  # noqa: BLE001
                pass
        return {
            "created": True,
            "task": _simplify_task(created[0]) if created else {"id": task_id},
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_create_task_error", error=str(exc))
        return {"created": False, "error": str(exc)}


async def tool_update_task(
    task_id: str,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    description: Optional[str] = None,
    subject: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Update a Salesforce task.

    Args:
        task_id: The Salesforce Task record ID.
        status: New status.
        priority: New priority.
        description: Updated description.
        subject: Updated subject.
    """
    payload: Dict[str, Any] = {}
    if status is not None:
        payload["Status"] = status
    if priority is not None:
        payload["Priority"] = priority
    if description is not None:
        payload["Description"] = description
    if subject is not None:
        payload["Subject"] = subject

    if not payload:
        raise ValueError("No fields provided to update")

    LOGGER.info("salesforce_update_task", task_id=task_id, fields=list(payload.keys()))
    try:
        await _salesforce_patch(f"/sobjects/Task/{task_id}", payload, ctx)

        updated = await _soql_query(
            f"SELECT Id, Subject, Status, Priority, Description, ActivityDate, "
            f"CreatedDate, OwnerId FROM Task WHERE Id = '{task_id}'"
        , ctx)

        return {
            "success": True,
            "task": updated[0] if updated else {},
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_update_task_error", task_id=task_id, error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_list_approvals(
    status: Optional[str] = None,
    limit: int = 20,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List Salesforce approval work items (pending approvals).

    Approval work items are ``ProcessInstanceWorkitem``.
    Approval comments are not the same as Task comments.

    Args:
        status: Filter by process status (e.g. "Pending").
        limit: Maximum results (default 20, max 100).
    """
    clauses = (
        [f"ProcessInstance.Status = '{status}'"]
        if status
        else ["ProcessInstance.Status = 'Pending'"]
    )
    where = f" WHERE {' AND '.join(clauses)}"
    safe_limit = max(1, min(int(limit), 100))

    query = (
        f"SELECT Id, ActorId, ProcessInstanceId, CreatedDate, "
        f"ProcessInstance.TargetObjectId, ProcessInstance.Status, "
        f"ProcessInstance.TargetObject.Name, ProcessInstance.TargetObject.Type "
        f"FROM ProcessInstanceWorkitem{where} "
        f"ORDER BY CreatedDate DESC "
        f"LIMIT {safe_limit}"
    )

    LOGGER.info("salesforce_list_approvals", query=query)
    records = await _soql_query(query, ctx)

    return {
        "total": len(records),
        "approvals": records,
    }


async def tool_approve_reject(
    work_item_id: str,
    action: str,
    comments: str = "",
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Approve or reject a Salesforce approval work item.

    Uses the Process Approvals API.

    Args:
        work_item_id: The ProcessInstanceWorkitem ID.
        action: "Approve" or "Reject".
        comments: Optional comments for the decision.
    """
    if action not in ("Approve", "Reject"):
        raise ValueError(
            f"Invalid action: {action}. Must be 'Approve' or 'Reject'."
        )

    LOGGER.info("salesforce_approve_reject", work_item_id=work_item_id, action=action)

    try:
        body = {
            "requests": [
                {
                    "actionType": action,
                    "contextActorId": "",
                    "contextId": work_item_id,
                    "comments": comments,
                }
            ]
        }

        result = await _salesforce_post("/process/approvals", body, ctx)
        return {
            "success": True,
            "action": action,
            "workItemId": work_item_id,
            "result": result,
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_approve_reject_error", work_item_id=work_item_id, error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Compliance Case tools ────────────────────────────────────────────

# Compliance categories modelled on a banking compliance function.
# These align with the Contoso Compliance SharePoint procedures.
_COMPLIANCE_TYPES = [
    "AML / KYC",
    "Sanctions Screening",
    "Fraud Investigation",
    "Market Abuse / Insider Trading",
    "Data Privacy (GDPR / CCPA)",
    "Regulatory Reporting",
    "Conflicts of Interest",
    "Gifts & Entertainment",
    "Whistleblower Report",
    "Trade Surveillance",
    "Customer Complaint",
    "Policy Breach",
    "Third-Party / Vendor Risk",
    "Operational Risk Event",
    "Other",
]

_CASE_FIELDS = (
    "Id, CaseNumber, Subject, Description, Status, Priority, Origin, Type, "
    "Reason, ContactId, AccountId, OwnerId, CreatedDate, ClosedDate, "
    "IsClosed, IsEscalated"
)

_ACCOUNT_FIELDS = (
    "Id, Name, Industry, Type, AccountNumber, OwnerId, Owner.Name, "
    "Phone, Website, BillingCity, BillingState, BillingCountry, "
    "Description, CreatedDate"
)

_CONTACT_FIELDS = (
    "Id, FirstName, LastName, Name, Email, Phone, Title, Department, "
    "AccountId, Account.Name, OwnerId, CreatedDate"
)

_OPPORTUNITY_FIELDS = (
    "Id, Name, StageName, Amount, Probability, CloseDate, IsClosed, IsWon, "
    "Type, LeadSource, Description, AccountId, Account.Name, OwnerId, Owner.Name, CreatedDate"
)

_EVENT_FIELDS = (
    "Id, Subject, StartDateTime, EndDateTime, Location, Description, "
    "WhatId, WhoId, OwnerId, CreatedDate"
)

_TASK_FIELDS = (
    "Id, Subject, Status, Priority, Description, ActivityDate, "
    "WhatId, WhoId, OwnerId, CreatedDate"
)


def _sf(value: Optional[str]) -> str:
    """Escape a string for safe interpolation into SOQL literals."""
    if value is None:
        return ""
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _soql_in(ids: List[str]) -> str:
    return ", ".join(f"'{_sf(x)}'" for x in ids if x)


def _simplify_account(raw: Dict[str, Any]) -> Dict[str, Any]:
    owner = raw.get("Owner", {}) if isinstance(raw.get("Owner"), dict) else {}
    return {
        "id": raw.get("Id"),
        "name": raw.get("Name"),
        "industry": raw.get("Industry"),
        "type": raw.get("Type"),
        "account_number": raw.get("AccountNumber"),
        "owner_id": raw.get("OwnerId"),
        "owner_name": owner.get("Name"),
        "phone": raw.get("Phone"),
        "website": raw.get("Website"),
        "billing_city": raw.get("BillingCity"),
        "billing_state": raw.get("BillingState"),
        "billing_country": raw.get("BillingCountry"),
        "description": raw.get("Description"),
        "created_date": raw.get("CreatedDate"),
    }


def _simplify_contact(raw: Dict[str, Any]) -> Dict[str, Any]:
    account = raw.get("Account", {}) if isinstance(raw.get("Account"), dict) else {}
    return {
        "id": raw.get("Id"),
        "first_name": raw.get("FirstName"),
        "last_name": raw.get("LastName"),
        "name": raw.get("Name"),
        "email": raw.get("Email"),
        "phone": raw.get("Phone"),
        "title": raw.get("Title"),
        "department": raw.get("Department"),
        "account_id": raw.get("AccountId"),
        "account_name": account.get("Name"),
        "owner_id": raw.get("OwnerId"),
        "created_date": raw.get("CreatedDate"),
    }


def _simplify_opportunity(raw: Dict[str, Any]) -> Dict[str, Any]:
    account = raw.get("Account", {}) if isinstance(raw.get("Account"), dict) else {}
    owner = raw.get("Owner", {}) if isinstance(raw.get("Owner"), dict) else {}
    return {
        "id": raw.get("Id"),
        "name": raw.get("Name"),
        "stage_name": raw.get("StageName"),
        "amount": raw.get("Amount"),
        "probability": raw.get("Probability"),
        "close_date": raw.get("CloseDate"),
        "is_closed": raw.get("IsClosed"),
        "is_won": raw.get("IsWon"),
        "type": raw.get("Type"),
        "lead_source": raw.get("LeadSource"),
        "description": raw.get("Description"),
        "account_id": raw.get("AccountId"),
        "account_name": account.get("Name"),
        "owner_id": raw.get("OwnerId"),
        "owner_name": owner.get("Name"),
        "created_date": raw.get("CreatedDate"),
    }


def _simplify_event(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": raw.get("Id"),
        "subject": raw.get("Subject"),
        "start_datetime": raw.get("StartDateTime"),
        "end_datetime": raw.get("EndDateTime"),
        "location": raw.get("Location"),
        "description": raw.get("Description"),
        "what_id": raw.get("WhatId"),
        "who_id": raw.get("WhoId"),
        "owner_id": raw.get("OwnerId"),
        "created_date": raw.get("CreatedDate"),
    }


def _simplify_task(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": raw.get("Id"),
        "subject": raw.get("Subject"),
        "status": raw.get("Status"),
        "priority": raw.get("Priority"),
        "description": raw.get("Description"),
        "activity_date": raw.get("ActivityDate"),
        "what_id": raw.get("WhatId"),
        "who_id": raw.get("WhoId"),
        "owner_id": raw.get("OwnerId"),
        "created_date": raw.get("CreatedDate"),
    }


def _simplify_case(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a Salesforce Case record for clean output."""
    return {
        "id": raw.get("Id"),
        "case_number": raw.get("CaseNumber"),
        "subject": raw.get("Subject"),
        "description": raw.get("Description"),
        "status": raw.get("Status"),
        "priority": raw.get("Priority"),
        "origin": raw.get("Origin"),
        "type": raw.get("Type"),
        "reason": raw.get("Reason"),
        "contact_id": raw.get("ContactId"),
        "account_id": raw.get("AccountId"),
        "owner_id": raw.get("OwnerId"),
        "created_date": raw.get("CreatedDate"),
        "closed_date": raw.get("ClosedDate"),
        "is_closed": raw.get("IsClosed"),
        "is_escalated": raw.get("IsEscalated"),
    }


async def tool_list_cases(
    status: Optional[str] = None,
    priority: Optional[str] = None,
    case_type: Optional[str] = None,
    search_text: Optional[str] = None,
    limit: int = 20,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List Salesforce compliance cases.

    The Salesforce Case object is used by the Compliance function to track
    regulatory investigations, policy breaches, AML/KYC reviews, fraud
    cases, and other compliance matters.

    Args:
        status: Filter by case status (e.g. "New", "Working", "Escalated", "Closed").
        priority: Filter by priority ("High", "Medium", "Low").
        case_type: Filter by compliance type (e.g. "AML / KYC", "Fraud Investigation").
        search_text: Free-text search across Subject and Description.
        limit: Maximum results (default 20, max 100).
    """
    clauses: List[str] = []
    if status:
        clauses.append(f"Status = '{status}'")
    if priority:
        clauses.append(f"Priority = '{priority}'")
    if case_type:
        clauses.append(f"Type = '{case_type}'")
    if search_text:
        clauses.append(
            f"(Subject LIKE '%{search_text}%' OR Description LIKE '%{search_text}%')"
        )

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    safe_limit = max(1, min(int(limit), 100))

    query = (
        f"SELECT {_CASE_FIELDS} "
        f"FROM Case{where} "
        f"ORDER BY CreatedDate DESC "
        f"LIMIT {safe_limit}"
    )

    LOGGER.info("salesforce_list_cases", query=query)
    records = await _soql_query(query, ctx)

    return {
        "total": len(records),
        "cases": [_simplify_case(r) for r in records],
        "compliance_types": _COMPLIANCE_TYPES,
    }


async def tool_get_case(case_id: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Get full details for a single Salesforce compliance case.

    Args:
        case_id: The Salesforce Case record ID or CaseNumber.
    """
    LOGGER.info("salesforce_get_case", case_id=case_id)

    # Support both Id and CaseNumber
    if case_id.isdigit() or len(case_id) < 15:
        records = await _soql_query(
            f"SELECT {_CASE_FIELDS} FROM Case WHERE CaseNumber = '{case_id}'"
        , ctx)
    else:
        records = await _soql_query(
            f"SELECT {_CASE_FIELDS} FROM Case WHERE Id = '{case_id}'"
        , ctx)

    if not records:
        raise ValueError(f"Salesforce Case {case_id} not found")

    # Also fetch case comments
    sf_case = records[0]
    comments = []
    try:
        comment_records = await _soql_query(
            f"SELECT Id, CommentBody, CreatedDate, CreatedById "
            f"FROM CaseComment WHERE ParentId = '{sf_case['Id']}' "
            f"ORDER BY CreatedDate DESC LIMIT 20"
        , ctx)
        for c in comment_records:
            comments.append({
                "id": c.get("Id"),
                "body": c.get("CommentBody"),
                "created_date": c.get("CreatedDate"),
                "created_by": c.get("CreatedById"),
            })
    except httpx.HTTPStatusError:
        raise
    except Exception:  # noqa: BLE001
        LOGGER.debug("case_comments_fetch_failed")

    return {
        "case": _simplify_case(sf_case),
        "comments": comments,
        "comment_count": len(comments),
    }


async def tool_create_case(
    subject: str,
    compliance_type: str,
    description: Optional[str] = None,
    priority: str = "Medium",
    origin: str = "Copilot",
    contact_name: Optional[str] = None,
    reason: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Create a new Salesforce compliance case.

    Used by employees to raise compliance concerns such as AML/KYC reviews,
    fraud investigations, policy breaches, sanctions screening, data privacy
    issues, conflicts of interest, or whistleblower reports.  The case is
    routed to the Compliance team.

    Args:
        subject: Brief summary of the compliance concern (required).
        compliance_type: The type of compliance matter. Must be one of:
            AML / KYC, Sanctions Screening, Fraud Investigation,
            Market Abuse / Insider Trading, Data Privacy (GDPR / CCPA),
            Regulatory Reporting, Conflicts of Interest,
            Gifts & Entertainment, Whistleblower Report,
            Trade Surveillance, Customer Complaint, Policy Breach,
            Third-Party / Vendor Risk, Operational Risk Event, Other.
        description: Detailed description of the compliance concern.
        priority: High, Medium, or Low (default Medium).
        origin: Channel of origin (default "Copilot").
        contact_name: Name of the person raising the concern.
        reason: Reason for the case.
    """
    payload: Dict[str, Any] = {
        "Subject": subject,
        "Type": compliance_type,
        "Priority": priority,
        "Origin": origin,
        "Status": "New",
    }
    if description:
        payload["Description"] = description
    if reason:
        payload["Reason"] = reason

    LOGGER.info("salesforce_create_case", fields=list(payload.keys()))

    try:
        result = await _salesforce_post("/sobjects/Case", payload, ctx)
        case_id = result.get("id", "")

        # Fetch the created case to return full details including CaseNumber
        created = []
        if case_id:
            try:
                created = await _soql_query(
                    f"SELECT {_CASE_FIELDS} FROM Case WHERE Id = '{case_id}'"
                , ctx)
            except Exception:  # noqa: BLE001
                pass

        return {
            "created": True,
            "case": _simplify_case(created[0]) if created else {"id": case_id},
            "compliance_types": _COMPLIANCE_TYPES,
        }

    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_create_case_error", subject=subject, error=str(exc), exc_info=True)
        return {"created": False, "error": f"Failed to create compliance case: {exc}"}


async def tool_update_case(
    case_id: str,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    description: Optional[str] = None,
    subject: Optional[str] = None,
    compliance_type: Optional[str] = None,
    comment: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Update an existing Salesforce compliance case.

    Provide only the fields you want to change. Use 'comment' to add a
    case comment visible in the case history.

    Args:
        case_id: The Salesforce Case record ID.
        status: New status (New, Working, Escalated, Closed).
        priority: New priority (High, Medium, Low).
        description: Updated description.
        subject: Updated subject.
        compliance_type: Updated compliance type.
        comment: A new case comment to append.
    """
    payload: Dict[str, Any] = {}
    if status is not None:
        payload["Status"] = status
    if priority is not None:
        payload["Priority"] = priority
    if description is not None:
        payload["Description"] = description
    if subject is not None:
        payload["Subject"] = subject
    if compliance_type is not None:
        payload["Type"] = compliance_type

    if not payload and not comment:
        raise ValueError("No fields provided to update")

    try:
        if payload:
            LOGGER.info("salesforce_update_case", case_id=case_id, fields=list(payload.keys()))
            await _salesforce_patch(f"/sobjects/Case/{case_id}", payload, ctx)

        # Add a case comment if provided
        if comment:
            LOGGER.info("salesforce_add_case_comment", case_id=case_id)
            await _salesforce_post(
                "/sobjects/CaseComment",
                {"ParentId": case_id, "CommentBody": comment},
                ctx,
            )

        # Fetch updated case
        updated = await _soql_query(
            f"SELECT {_CASE_FIELDS} FROM Case WHERE Id = '{case_id}'"
        , ctx)

        return {
            "success": True,
            "case": _simplify_case(updated[0]) if updated else {},
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_update_case_error", case_id=case_id, error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Provider functions for TaskServer integration ───────────────────


async def provider_list_tasks(ctx: Optional[Context] = None) -> List[Dict[str, Any]]:
    """List Salesforce tasks for TaskServer normalization."""
    try:
        load_salesforce_settings()
    except Exception:  # noqa: BLE001
        LOGGER.debug("salesforce_settings_not_configured")
        return []

    records = await _soql_query(
        "SELECT Id, Subject, Status, Priority, Description, ActivityDate, "
        "CreatedDate, OwnerId "
        "FROM Task WHERE IsClosed = false "
        "ORDER BY CreatedDate DESC LIMIT 50"
    , ctx)
    # Add browser links for TaskServer widget
    instance_url = _get_instance_url()
    for r in records:
        if r.get("Id"):
            r["link"] = f"{instance_url}/{r['Id']}"
    return records


async def provider_list_cases(ctx: Optional[Context] = None) -> List[Dict[str, Any]]:
    """List open Salesforce compliance cases for TaskServer normalization."""
    try:
        load_salesforce_settings()
    except Exception:  # noqa: BLE001
        LOGGER.debug("salesforce_settings_not_configured")
        return []

    records = await _soql_query(
        f"SELECT {_CASE_FIELDS} "
        f"FROM Case WHERE IsClosed = false "
        f"ORDER BY CreatedDate DESC LIMIT 50"
    , ctx)
    # Add browser links for TaskServer widget
    instance_url = _get_instance_url()
    for r in records:
        if r.get("Id"):
            r["link"] = f"{instance_url}/{r['Id']}"
    return records


async def provider_list_approvals(ctx: Optional[Context] = None) -> List[Dict[str, Any]]:
    """List pending Salesforce approvals for TaskServer normalization."""
    try:
        load_salesforce_settings()
    except Exception:  # noqa: BLE001
        LOGGER.debug("salesforce_settings_not_configured")
        return []

    records = await _soql_query(
        "SELECT Id, ActorId, ProcessInstanceId, CreatedDate, "
        "ProcessInstance.TargetObjectId, ProcessInstance.Status, "
        "ProcessInstance.TargetObject.Name, ProcessInstance.TargetObject.Type "
        "FROM ProcessInstanceWorkitem "
        "WHERE ProcessInstance.Status = 'Pending' "
        "ORDER BY CreatedDate DESC LIMIT 50"
    , ctx)
    # Add browser links (to target object) for TaskServer widget
    instance_url = _get_instance_url()
    for r in records:
        pi = r.get("ProcessInstance", {}) or {}
        target_id = pi.get("TargetObjectId", r.get("Id", ""))
        if target_id:
            r["link"] = f"{instance_url}/{target_id}"
    return records


async def provider_get_approval_detail(item_id: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Fetch approval detail for a ProcessInstanceWorkitem."""
    records = await _soql_query(
        f"SELECT Id, ActorId, ProcessInstanceId, CreatedDate, "
        f"ProcessInstance.TargetObjectId, ProcessInstance.Status, "
        f"ProcessInstance.TargetObject.Name, ProcessInstance.TargetObject.Type "
        f"FROM ProcessInstanceWorkitem WHERE Id = '{item_id}'"
    , ctx)
    if not records:
        raise ValueError(f"Salesforce approval work item {item_id} not found")

    record = records[0]
    process = (
        record.get("ProcessInstance", {})
        if isinstance(record.get("ProcessInstance"), dict)
        else {}
    )
    target = (
        process.get("TargetObject", {})
        if isinstance(process.get("TargetObject"), dict)
        else {}
    )

    return {
        "title": target.get("Name", f"Approval {item_id}"),
        "summary": target.get("Type", ""),
        "status": process.get("Status", ""),
        "workItemId": item_id,
        "processInstanceId": record.get("ProcessInstanceId"),
        "targetObjectId": process.get("TargetObjectId"),
        "createdDate": record.get("CreatedDate"),
        "raw": record,
    }


async def provider_execute_approval(
    item_id: str, decision: str, comment: str = "", ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """Execute an approval decision on a Salesforce work item."""
    action = "Approve" if decision == "approve" else "Reject"
    body = {
        "requests": [
            {
                "actionType": action,
                "contextActorId": "",
                "contextId": item_id,
                "comments": comment,
            }
        ]
    }

    result = await _salesforce_post("/process/approvals", body, ctx)
    return {
        "success": True,
        "decision": decision,
        "workItemId": item_id,
        "result": result,
    }


# ── Form-show helper (GET-pattern, widget submits the POST) ─────────

async def tool_show_compliance_case_form(
    subject: Optional[str] = None,
    compliance_type: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None,
) -> Dict[str, Any]:
    """Show the compliance case creation form widget.

    Returns pre-fill data so the widget can populate the form.  The user
    completes and submits the form inside the widget -- this tool does not
    create the case directly.

    Args:
        subject: Optional pre-fill for the case subject.
        compliance_type: Optional pre-fill for compliance type (e.g. "AML / KYC",
            "Fraud Investigation", "Data Privacy").
        description: Optional detailed description to pre-fill.
        priority: Optional priority pre-fill (High, Medium, Low).
    """
    prefill: Dict[str, Any] = {}
    if subject:
        prefill["subject"] = subject
    if compliance_type:
        prefill["compliance_type"] = compliance_type
    if description:
        prefill["description"] = description
    if priority:
        prefill["priority"] = priority

    return {
        "_widget_hint": "The form is ready. Acknowledge with one short sentence (e.g. 'Here is the compliance case form.').",
        **prefill,
    }


# ── CRM (Accounts / Contacts / Opportunities / Events) ────────────


async def tool_list_accounts(
    search_text: Optional[str] = None,
    industry: Optional[str] = None,
    owner_name: Optional[str] = None,
    limit: int = 25,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List Salesforce accounts for CRM workflows."""
    clauses: List[str] = []
    if search_text:
        s = _sf(search_text)
        clauses.append(f"(Name LIKE '%{s}%' OR AccountNumber LIKE '%{s}%')")
    if industry:
        clauses.append(f"Industry = '{_sf(industry)}'")
    if owner_name:
        clauses.append(f"Owner.Name = '{_sf(owner_name)}'")

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    safe_limit = max(1, min(int(limit), 100))

    query = (
        f"SELECT {_ACCOUNT_FIELDS} "
        f"FROM Account{where} "
        f"ORDER BY Name ASC "
        f"LIMIT {safe_limit}"
    )
    records = await _soql_query(query, ctx)
    return {
        "total": len(records),
        "accounts": [_simplify_account(r) for r in records],
    }


async def tool_list_contacts(
    account_id: Optional[str] = None,
    search_text: Optional[str] = None,
    limit: int = 25,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List Salesforce contacts, optionally scoped to an account."""
    clauses: List[str] = []
    if account_id:
        clauses.append(f"AccountId = '{_sf(account_id)}'")
    if search_text:
        s = _sf(search_text)
        clauses.append(
            f"(Name LIKE '%{s}%' OR Email LIKE '%{s}%' OR Title LIKE '%{s}%')"
        )

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    safe_limit = max(1, min(int(limit), 100))

    query = (
        f"SELECT {_CONTACT_FIELDS} "
        f"FROM Contact{where} "
        f"ORDER BY LastName ASC, FirstName ASC "
        f"LIMIT {safe_limit}"
    )
    records = await _soql_query(query, ctx)
    return {
        "total": len(records),
        "contacts": [_simplify_contact(r) for r in records],
    }


async def tool_create_contact(
    first_name: str,
    last_name: str,
    account_id: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    title: Optional[str] = None,
    department: Optional[str] = None,
    mailing_street: Optional[str] = None,
    mailing_city: Optional[str] = None,
    mailing_state: Optional[str] = None,
    mailing_postal_code: Optional[str] = None,
    mailing_country: Optional[str] = None,
    description: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Create a new Salesforce contact. Optionally link to an account.

    Args:
        first_name: Contact's first name (required).
        last_name: Contact's last name (required).
        account_id: Salesforce Account ID to associate the contact with.
        email: Contact's email address.
        phone: Contact's phone number.
        title: Contact's job title.
        department: Contact's department.
        mailing_street: Mailing street address.
        mailing_city: Mailing city.
        mailing_state: Mailing state/province.
        mailing_postal_code: Mailing postal/ZIP code.
        mailing_country: Mailing country.
        description: Additional notes about the contact.
    """
    payload: Dict[str, Any] = {
        "FirstName": first_name,
        "LastName": last_name,
    }
    if account_id:
        payload["AccountId"] = account_id
    if email:
        payload["Email"] = email
    if phone:
        payload["Phone"] = phone
    if title:
        payload["Title"] = title
    if department:
        payload["Department"] = department
    if mailing_street:
        payload["MailingStreet"] = mailing_street
    if mailing_city:
        payload["MailingCity"] = mailing_city
    if mailing_state:
        payload["MailingState"] = mailing_state
    if mailing_postal_code:
        payload["MailingPostalCode"] = mailing_postal_code
    if mailing_country:
        payload["MailingCountry"] = mailing_country
    if description:
        payload["Description"] = description

    LOGGER.info("salesforce_create_contact", fields=list(payload.keys()))

    try:
        result = await _salesforce_post("/sobjects/Contact", payload, ctx)
        contact_id = result.get("id", "")
        created: List[Dict[str, Any]] = []
        if contact_id:
            try:
                created = await _soql_query(
                    f"SELECT {_CONTACT_FIELDS} FROM Contact WHERE Id = '{_sf(contact_id)}'"
                , ctx)
            except Exception:  # noqa: BLE001
                pass
        return {
            "created": True,
            "contact": _simplify_contact(created[0]) if created else {"id": contact_id},
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_create_contact_error", error=str(exc))
        return {"created": False, "error": str(exc)}


async def tool_update_contact(
    contact_id: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    title: Optional[str] = None,
    department: Optional[str] = None,
    mailing_street: Optional[str] = None,
    mailing_city: Optional[str] = None,
    mailing_state: Optional[str] = None,
    mailing_postal_code: Optional[str] = None,
    mailing_country: Optional[str] = None,
    description: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Update an existing Salesforce contact.

    Args:
        contact_id: The Salesforce Contact record ID (required).
        first_name: Updated first name.
        last_name: Updated last name.
        email: Updated email address.
        phone: Updated phone number.
        title: Updated job title.
        department: Updated department.
        mailing_street: Updated mailing street.
        mailing_city: Updated mailing city.
        mailing_state: Updated mailing state/province.
        mailing_postal_code: Updated mailing postal/ZIP code.
        mailing_country: Updated mailing country.
        description: Updated notes about the contact.
    """
    payload: Dict[str, Any] = {}
    if first_name:
        payload["FirstName"] = first_name
    if last_name:
        payload["LastName"] = last_name
    if email:
        payload["Email"] = email
    if phone:
        payload["Phone"] = phone
    if title:
        payload["Title"] = title
    if department:
        payload["Department"] = department
    if mailing_street:
        payload["MailingStreet"] = mailing_street
    if mailing_city:
        payload["MailingCity"] = mailing_city
    if mailing_state:
        payload["MailingState"] = mailing_state
    if mailing_postal_code:
        payload["MailingPostalCode"] = mailing_postal_code
    if mailing_country:
        payload["MailingCountry"] = mailing_country
    if description:
        payload["Description"] = description

    if not payload:
        return {"success": False, "error": "No fields provided to update."}

    LOGGER.info("salesforce_update_contact", contact_id=contact_id, fields=list(payload.keys()))

    try:
        await _salesforce_patch(f"/sobjects/Contact/{contact_id}", payload, ctx)
        updated: List[Dict[str, Any]] = []
        try:
            updated = await _soql_query(
                f"SELECT {_CONTACT_FIELDS} FROM Contact WHERE Id = '{_sf(contact_id)}'"
            , ctx)
        except Exception:  # noqa: BLE001
            pass
        return {
            "success": True,
            "contact": _simplify_contact(updated[0]) if updated else {"id": contact_id},
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_update_contact_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_activity_timeline(
    record_id: str,
    limit: int = 25,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Get the activity timeline for a Salesforce record (Account, Contact, Opportunity, Lead).

    Returns a combined, chronologically sorted list of tasks, events, and emails
    associated with the record.

    Args:
        record_id: The Salesforce record ID (Account, Contact, Opportunity, or Lead).
        limit: Maximum number of activities to return (default: 25, max: 100).
    """
    LOGGER.info("salesforce_get_activity_timeline", record_id=record_id)
    safe_limit = max(1, min(int(limit), 100))

    try:
        tasks_q = (
            f"SELECT Id, Subject, Status, Priority, ActivityDate, Description, "
            f"Owner.Name, CreatedDate "
            f"FROM Task WHERE WhatId = '{_sf(record_id)}' OR WhoId = '{_sf(record_id)}' "
            f"ORDER BY ActivityDate DESC LIMIT {safe_limit}"
        )
        events_q = (
            f"SELECT Id, Subject, StartDateTime, EndDateTime, Location, Description, "
            f"Owner.Name, CreatedDate "
            f"FROM Event WHERE WhatId = '{_sf(record_id)}' OR WhoId = '{_sf(record_id)}' "
            f"ORDER BY StartDateTime DESC LIMIT {safe_limit}"
        )
        tasks_result, events_result = await asyncio.gather(
            _soql_query(tasks_q, ctx),
            _soql_query(events_q, ctx),
        )

        activities: List[Dict[str, Any]] = []
        for t in tasks_result:
            activities.append({
                "type": "Task",
                "id": t.get("Id"),
                "subject": t.get("Subject"),
                "status": t.get("Status"),
                "priority": t.get("Priority"),
                "date": t.get("ActivityDate"),
                "description": t.get("Description"),
                "owner": (t.get("Owner") or {}).get("Name"),
                "created": t.get("CreatedDate"),
            })
        for e in events_result:
            activities.append({
                "type": "Event",
                "id": e.get("Id"),
                "subject": e.get("Subject"),
                "date": e.get("StartDateTime"),
                "end_date": e.get("EndDateTime"),
                "location": e.get("Location"),
                "description": e.get("Description"),
                "owner": (e.get("Owner") or {}).get("Name"),
                "created": e.get("CreatedDate"),
            })

        activities.sort(key=lambda a: a.get("date") or a.get("created") or "", reverse=True)
        return {
            "success": True,
            "record_id": record_id,
            "activities": activities[:safe_limit],
            "total_tasks": len(tasks_result),
            "total_events": len(events_result),
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_get_activity_timeline_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_list_opportunities(
    account_id: Optional[str] = None,
    stage_name: Optional[str] = None,
    owner_name: Optional[str] = None,
    include_closed: bool = False,
    limit: int = 40,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List Salesforce opportunities for pipeline workflows."""
    clauses: List[str] = []
    if account_id:
        clauses.append(f"AccountId = '{_sf(account_id)}'")
    if stage_name:
        clauses.append(f"StageName = '{_sf(stage_name)}'")
    if owner_name:
        clauses.append(f"Owner.Name = '{_sf(owner_name)}'")
    if not include_closed:
        clauses.append("IsClosed = false")

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    safe_limit = max(1, min(int(limit), 150))

    query = (
        f"SELECT {_OPPORTUNITY_FIELDS} "
        f"FROM Opportunity{where} "
        f"ORDER BY CloseDate ASC, Amount DESC "
        f"LIMIT {safe_limit}"
    )
    records = await _soql_query(query, ctx)
    return {
        "total": len(records),
        "opportunities": [_simplify_opportunity(r) for r in records],
    }


async def tool_get_account_360(
    account_id: Optional[str] = None,
    account_name: Optional[str] = None,
    section_limit: int = 12,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Get a 360-degree account view with contacts, opportunities, activities, cases, and tasks."""
    if not account_id and not account_name:
        raise ValueError("Provide account_id or account_name")

    safe_limit = max(1, min(int(section_limit), 50))

    if account_id:
        account_query = f"SELECT {_ACCOUNT_FIELDS} FROM Account WHERE Id = '{_sf(account_id)}' LIMIT 1"
    else:
        account_query = (
            f"SELECT {_ACCOUNT_FIELDS} "
            f"FROM Account WHERE Name LIKE '%{_sf(account_name or '')}%' "
            f"ORDER BY Name ASC LIMIT 1"
        )

    account_records = await _soql_query(account_query, ctx)
    if not account_records:
        raise ValueError("Salesforce account not found")

    account_raw = account_records[0]
    resolved_account_id = account_raw.get("Id")

    contacts = await _soql_query(
        f"SELECT {_CONTACT_FIELDS} FROM Contact "
        f"WHERE AccountId = '{_sf(resolved_account_id)}' "
        f"ORDER BY LastName ASC, FirstName ASC LIMIT {safe_limit}"
    , ctx)

    opportunities = await _soql_query(
        f"SELECT {_OPPORTUNITY_FIELDS} FROM Opportunity "
        f"WHERE AccountId = '{_sf(resolved_account_id)}' "
        f"ORDER BY CloseDate DESC, Amount DESC LIMIT {safe_limit}"
    , ctx)

    opportunity_ids = [o.get("Id") for o in opportunities if o.get("Id")]
    what_ids = [resolved_account_id, *opportunity_ids]
    in_clause = _soql_in([x for x in what_ids if x])

    events: List[Dict[str, Any]] = []
    tasks: List[Dict[str, Any]] = []
    if in_clause:
        events = await _soql_query(
            f"SELECT {_EVENT_FIELDS} FROM Event "
            f"WHERE WhatId IN ({in_clause}) "
            f"ORDER BY StartDateTime DESC LIMIT {safe_limit}"
        , ctx)
        tasks = await _soql_query(
            f"SELECT {_TASK_FIELDS} FROM Task "
            f"WHERE WhatId IN ({in_clause}) "
            f"ORDER BY CreatedDate DESC LIMIT {safe_limit}"
        , ctx)

    cases = await _soql_query(
        f"SELECT {_CASE_FIELDS} FROM Case "
        f"WHERE AccountId = '{_sf(resolved_account_id)}' "
        f"ORDER BY CreatedDate DESC LIMIT {safe_limit}"
    , ctx)

    open_opps = [o for o in opportunities if not o.get("IsClosed")]
    open_pipeline_amount = sum(float(o.get("Amount") or 0) for o in open_opps)

    instance_url = _get_instance_url()

    return {
        "account": _simplify_account(account_raw),
        "contacts": [_simplify_contact(x) for x in contacts],
        "opportunities": [_simplify_opportunity(x) for x in opportunities],
        "events": [_simplify_event(x) for x in events],
        "tasks": [_simplify_task(x) for x in tasks],
        "cases": [_simplify_case(x) for x in cases],
        "summary": {
            "contacts": len(contacts),
            "opportunities": len(opportunities),
            "open_opportunities": len(open_opps),
            "open_pipeline_amount": open_pipeline_amount,
            "events": len(events),
            "tasks": len(tasks),
            "cases": len(cases),
        },
        "links": {
            "account": f"{instance_url}/{resolved_account_id}",
        },
    }


async def tool_get_pipeline_dashboard(
    owner_name: Optional[str] = None,
    include_closed: bool = False,
    limit: int = 200,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Get a sales pipeline dashboard (funnel/tornado-friendly aggregated view)."""
    clauses: List[str] = []
    if owner_name:
        clauses.append(f"Owner.Name = '{_sf(owner_name)}'")
    if not include_closed:
        clauses.append("IsClosed = false")

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    safe_limit = max(20, min(int(limit), 500))

    query = (
        f"SELECT {_OPPORTUNITY_FIELDS} "
        f"FROM Opportunity{where} "
        f"ORDER BY Amount DESC, CloseDate ASC "
        f"LIMIT {safe_limit}"
    )
    records = await _soql_query(query, ctx)

    stage_rollup: Dict[str, Dict[str, Any]] = {}
    total_amount = 0.0
    total_weighted = 0.0

    for raw in records:
        stage = raw.get("StageName") or "Unknown"
        amount = float(raw.get("Amount") or 0)
        prob = float(raw.get("Probability") or 0)

        total_amount += amount
        total_weighted += amount * (prob / 100.0)

        entry = stage_rollup.setdefault(
            stage,
            {"stage": stage, "count": 0, "amount": 0.0, "weighted_amount": 0.0},
        )
        entry["count"] += 1
        entry["amount"] += amount
        entry["weighted_amount"] += amount * (prob / 100.0)

    stages = sorted(stage_rollup.values(), key=lambda x: x["amount"], reverse=True)

    return {
        "totals": {
            "opportunities": len(records),
            "pipeline_amount": total_amount,
            "weighted_pipeline_amount": total_weighted,
        },
        "stages": stages,
        "opportunities": [_simplify_opportunity(r) for r in records[:50]],
    }


async def tool_show_create_opportunity_form(
    account_id: Optional[str] = None,
    account_name: Optional[str] = None,
    name: Optional[str] = None,
    amount: Optional[float] = None,
    stage_name: Optional[str] = None,
    close_date: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Show a guided create-opportunity form widget with optional prefill."""
    prefill: Dict[str, Any] = {}
    if account_id:
        prefill["account_id"] = account_id
    if account_name:
        prefill["account_name"] = account_name
    if name:
        prefill["name"] = name
    if amount is not None:
        prefill["amount"] = amount
    if stage_name:
        prefill["stage_name"] = stage_name
    if close_date:
        prefill["close_date"] = close_date
    if description:
        prefill["description"] = description

    if account_name and not account_id:
        candidates = await tool_list_accounts(search_text=account_name, limit=5)
        prefill["account_candidates"] = candidates.get("accounts", [])

    return {
        "_widget_hint": "The opportunity form is ready. Acknowledge with one short sentence.",
        **prefill,
    }


async def tool_create_opportunity(
    name: str,
    account_id: str,
    amount: Optional[float] = None,
    stage_name: str = "Prospecting",
    close_date: Optional[str] = None,
    probability: Optional[float] = None,
    description: Optional[str] = None,
    lead_source: Optional[str] = None,
    opportunity_type: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Create a Salesforce opportunity."""
    if not close_date:
        close_date = (datetime.now(timezone.utc).date() + timedelta(days=30)).isoformat()

    payload: Dict[str, Any] = {
        "Name": name,
        "AccountId": account_id,
        "StageName": stage_name,
        "CloseDate": close_date,
    }
    if amount is not None:
        payload["Amount"] = amount
    if probability is not None:
        payload["Probability"] = probability
    if description:
        payload["Description"] = description
    if lead_source:
        payload["LeadSource"] = lead_source
    if opportunity_type:
        payload["Type"] = opportunity_type

    try:
        result = await _salesforce_post("/sobjects/Opportunity", payload, ctx)
        opp_id = result.get("id", "")
        created = await _soql_query(
            f"SELECT {_OPPORTUNITY_FIELDS} FROM Opportunity WHERE Id = '{_sf(opp_id)}'"
        , ctx)
        instance_url = _get_instance_url()
        return {
            "created": True,
            "opportunity": _simplify_opportunity(created[0]) if created else {"id": opp_id},
            "link": f"{instance_url}/{opp_id}" if opp_id else "",
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_create_opportunity_error", error=str(exc))
        return {"created": False, "error": str(exc)}


async def tool_create_opportunity_task(
    opportunity_id: str,
    subject: str,
    due_date: Optional[str] = None,
    priority: str = "Normal",
    status: str = "Not Started",
    description: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Create a Salesforce task linked to an opportunity."""
    payload: Dict[str, Any] = {
        "WhatId": opportunity_id,
        "Subject": subject,
        "Priority": priority,
        "Status": status,
    }
    if due_date:
        payload["ActivityDate"] = due_date
    if description:
        payload["Description"] = description

    try:
        result = await _salesforce_post("/sobjects/Task", payload, ctx)
        task_id = result.get("id", "")
        task_records = await _soql_query(
            f"SELECT {_TASK_FIELDS} FROM Task WHERE Id = '{_sf(task_id)}'"
        , ctx)
        return {
            "created": True,
            "task": _simplify_task(task_records[0]) if task_records else {"id": task_id},
            "opportunity_id": opportunity_id,
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_create_opportunity_task_error", error=str(exc))
        return {"created": False, "error": str(exc)}


async def tool_update_opportunity(
    opportunity_id: str,
    name: Optional[str] = None,
    stage_name: Optional[str] = None,
    amount: Optional[float] = None,
    close_date: Optional[str] = None,
    probability: Optional[float] = None,
    description: Optional[str] = None,
    lead_source: Optional[str] = None,
    opportunity_type: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Update an existing Salesforce opportunity.

    Provide only the fields you want to change.

    Args:
        opportunity_id: The Salesforce Opportunity record ID.
        name: Updated opportunity name.
        stage_name: Updated stage (e.g. "Prospecting", "Closed Won").
        amount: Updated deal amount.
        close_date: Updated close date (ISO 8601, e.g. "2025-12-31").
        probability: Updated win probability (0-100).
        description: Updated description.
        lead_source: Updated lead source.
        opportunity_type: Updated opportunity type.
    """
    payload: Dict[str, Any] = {}
    if name is not None:
        payload["Name"] = name
    if stage_name is not None:
        payload["StageName"] = stage_name
    if amount is not None:
        payload["Amount"] = amount
    if close_date is not None:
        payload["CloseDate"] = close_date
    if probability is not None:
        payload["Probability"] = probability
    if description is not None:
        payload["Description"] = description
    if lead_source is not None:
        payload["LeadSource"] = lead_source
    if opportunity_type is not None:
        payload["Type"] = opportunity_type

    if not payload:
        raise ValueError("No fields provided to update")

    try:
        LOGGER.info("salesforce_update_opportunity", opportunity_id=opportunity_id, fields=list(payload.keys()))
        await _salesforce_patch(f"/sobjects/Opportunity/{opportunity_id}", payload, ctx)

        updated = await _soql_query(
            f"SELECT {_OPPORTUNITY_FIELDS} FROM Opportunity WHERE Id = '{_sf(opportunity_id)}'"
        , ctx)

        return {
            "success": True,
            "opportunity": _simplify_opportunity(updated[0]) if updated else {},
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_update_opportunity_error", opportunity_id=opportunity_id, error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_show_create_event_form(
    subject: Optional[str] = None,
    start_datetime: Optional[str] = None,
    end_datetime: Optional[str] = None,
    opportunity_id: Optional[str] = None,
    account_id: Optional[str] = None,
    contact_id: Optional[str] = None,
    location: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Show a guided create-event form widget with optional prefill."""
    prefill: Dict[str, Any] = {}
    if subject:
        prefill["subject"] = subject
    if start_datetime:
        prefill["start_datetime"] = start_datetime
    if end_datetime:
        prefill["end_datetime"] = end_datetime
    if opportunity_id:
        prefill["opportunity_id"] = opportunity_id
    if account_id:
        prefill["account_id"] = account_id
    if contact_id:
        prefill["contact_id"] = contact_id
    if location:
        prefill["location"] = location
    if description:
        prefill["description"] = description

    return {
        "_widget_hint": "The event form is ready. Acknowledge with one short sentence.",
        **prefill,
    }


async def tool_create_event(
    subject: str,
    start_datetime: str,
    end_datetime: str,
    opportunity_id: Optional[str] = None,
    account_id: Optional[str] = None,
    contact_id: Optional[str] = None,
    location: Optional[str] = None,
    description: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Create a Salesforce event, optionally linked to account/opportunity/contact."""
    payload: Dict[str, Any] = {
        "Subject": subject,
        "StartDateTime": start_datetime,
        "EndDateTime": end_datetime,
    }
    if opportunity_id:
        payload["WhatId"] = opportunity_id
    elif account_id:
        payload["WhatId"] = account_id
    if contact_id:
        payload["WhoId"] = contact_id
    if location:
        payload["Location"] = location
    if description:
        payload["Description"] = description

    try:
        result = await _salesforce_post("/sobjects/Event", payload, ctx)
        event_id = result.get("id", "")
        event_records = await _soql_query(
            f"SELECT {_EVENT_FIELDS} FROM Event WHERE Id = '{_sf(event_id)}'"
        , ctx)
        return {
            "created": True,
            "event": _simplify_event(event_records[0]) if event_records else {"id": event_id},
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_create_event_error", error=str(exc))
        return {"created": False, "error": str(exc)}


async def tool_update_event(
    event_id: str,
    subject: Optional[str] = None,
    start_datetime: Optional[str] = None,
    end_datetime: Optional[str] = None,
    opportunity_id: Optional[str] = None,
    account_id: Optional[str] = None,
    contact_id: Optional[str] = None,
    location: Optional[str] = None,
    description: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Update an existing Salesforce event.

    Provide only the fields you want to change.

    Args:
        event_id: The Salesforce Event record ID.
        subject: Updated event subject.
        start_datetime: Updated start date/time (ISO 8601).
        end_datetime: Updated end date/time (ISO 8601).
        opportunity_id: Link event to this opportunity (sets WhatId).
        account_id: Link event to this account (sets WhatId, ignored if opportunity_id is provided).
        contact_id: Link event to this contact (sets WhoId).
        location: Updated location.
        description: Updated description.
    """
    payload: Dict[str, Any] = {}
    if subject is not None:
        payload["Subject"] = subject
    if start_datetime is not None:
        payload["StartDateTime"] = start_datetime
    if end_datetime is not None:
        payload["EndDateTime"] = end_datetime
    if opportunity_id is not None:
        payload["WhatId"] = opportunity_id
    elif account_id is not None:
        payload["WhatId"] = account_id
    if contact_id is not None:
        payload["WhoId"] = contact_id
    if location is not None:
        payload["Location"] = location
    if description is not None:
        payload["Description"] = description

    if not payload:
        raise ValueError("No fields provided to update")

    try:
        LOGGER.info("salesforce_update_event", event_id=event_id, fields=list(payload.keys()))
        await _salesforce_patch(f"/sobjects/Event/{event_id}", payload, ctx)

        updated = await _soql_query(
            f"SELECT {_EVENT_FIELDS} FROM Event WHERE Id = '{_sf(event_id)}'"
        , ctx)

        return {
            "success": True,
            "event": _simplify_event(updated[0]) if updated else {},
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_update_event_error", event_id=event_id, error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Leads ───────────────────────────────────────────────────────────

_LEAD_FIELDS = (
    "Id, FirstName, LastName, Name, Email, Phone, Company, Status, "
    "LeadSource, Rating, OwnerId, Title, Industry, CreatedDate"
)


def _simplify_lead(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": raw.get("Id"),
        "first_name": raw.get("FirstName"),
        "last_name": raw.get("LastName"),
        "name": raw.get("Name"),
        "email": raw.get("Email"),
        "phone": raw.get("Phone"),
        "company": raw.get("Company"),
        "status": raw.get("Status"),
        "lead_source": raw.get("LeadSource"),
        "rating": raw.get("Rating"),
        "owner_id": raw.get("OwnerId"),
        "title": raw.get("Title"),
        "industry": raw.get("Industry"),
        "created_date": raw.get("CreatedDate"),
    }


async def tool_list_leads(
    status: Optional[str] = None,
    lead_source: Optional[str] = None,
    search_text: Optional[str] = None,
    limit: int = 20,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List or search Salesforce leads.

    Args:
        status: Filter by lead status (e.g. "Open - Not Contacted", "Working - Contacted").
        lead_source: Filter by lead source (e.g. "Web", "Phone Inquiry", "Partner Referral").
        search_text: Free-text search across Name, Email, and Company.
        limit: Maximum results (default 20, max 100).
    """
    clauses: List[str] = ["Status != 'Converted'"]
    if status:
        clauses.append(f"Status = '{_sf(status)}'")
    if lead_source:
        clauses.append(f"LeadSource = '{_sf(lead_source)}'")
    if search_text:
        s = _sf(search_text)
        clauses.append(
            f"(Name LIKE '%{s}%' OR Email LIKE '%{s}%' OR Company LIKE '%{s}%')"
        )

    where = f" WHERE {' AND '.join(clauses)}"
    safe_limit = max(1, min(int(limit), 100))

    query = (
        f"SELECT {_LEAD_FIELDS} "
        f"FROM Lead{where} "
        f"ORDER BY CreatedDate DESC "
        f"LIMIT {safe_limit}"
    )

    LOGGER.info("salesforce_list_leads", query=query)
    records = await _soql_query(query, ctx)

    return {
        "total": len(records),
        "leads": [_simplify_lead(r) for r in records],
    }


async def tool_get_lead(lead_id: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Get details for a single Salesforce lead.

    Args:
        lead_id: The Salesforce Lead record ID.
    """
    LOGGER.info("salesforce_get_lead", lead_id=lead_id)
    records = await _soql_query(
        f"SELECT {_LEAD_FIELDS}, Description, NumberOfEmployees, "
        f"AnnualRevenue, Street, City, State, PostalCode, Country "
        f"FROM Lead WHERE Id = '{_sf(lead_id)}'"
    , ctx)

    if not records:
        raise ValueError(f"Salesforce Lead {lead_id} not found")

    return {"lead": _simplify_lead(records[0])}


async def tool_show_create_lead_form(
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    company: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    title: Optional[str] = None,
    lead_source: Optional[str] = None,
    status: Optional[str] = None,
    description: Optional[str] = None,
) -> Dict[str, Any]:
    """Show the lead creation form widget.

    Returns pre-fill data so the widget can populate the form.  The user
    completes and submits the form inside the widget -- this tool does not
    create the lead directly.

    Args:
        first_name: Optional pre-fill for lead first name.
        last_name: Optional pre-fill for lead last name.
        company: Optional pre-fill for company name.
        email: Optional pre-fill for email address.
        phone: Optional pre-fill for phone number.
        title: Optional pre-fill for job title.
        lead_source: Optional pre-fill for lead source.
        status: Optional pre-fill for lead status.
        description: Optional pre-fill for description.
    """
    prefill: Dict[str, Any] = {}
    if first_name:
        prefill["first_name"] = first_name
    if last_name:
        prefill["last_name"] = last_name
    if company:
        prefill["company"] = company
    if email:
        prefill["email"] = email
    if phone:
        prefill["phone"] = phone
    if title:
        prefill["title"] = title
    if lead_source:
        prefill["lead_source"] = lead_source
    if status:
        prefill["status"] = status
    if description:
        prefill["description"] = description

    return {
        "_widget_hint": "The lead form is ready. Acknowledge with one short sentence.",
        **prefill,
    }


async def tool_create_lead(
    first_name: str,
    last_name: str,
    company: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    title: Optional[str] = None,
    lead_source: Optional[str] = None,
    status: str = "Open - Not Contacted",
    description: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Create a new Salesforce lead.

    Args:
        first_name: Lead's first name (required).
        last_name: Lead's last name (required).
        company: Lead's company name (required).
        email: Lead's email address.
        phone: Lead's phone number.
        title: Lead's job title.
        lead_source: Source of the lead (e.g. "Web", "Phone Inquiry", "Partner Referral").
        status: Lead status (default "Open - Not Contacted").
        description: Additional notes about the lead.
    """
    payload: Dict[str, Any] = {
        "FirstName": first_name,
        "LastName": last_name,
        "Company": company,
        "Status": status,
    }
    if email:
        payload["Email"] = email
    if phone:
        payload["Phone"] = phone
    if title:
        payload["Title"] = title
    if lead_source:
        payload["LeadSource"] = lead_source
    if description:
        payload["Description"] = description

    LOGGER.info("salesforce_create_lead", fields=list(payload.keys()))

    try:
        result = await _salesforce_post("/sobjects/Lead", payload, ctx)
        lead_id = result.get("id", "")
        created: List[Dict[str, Any]] = []
        if lead_id:
            try:
                created = await _soql_query(
                    f"SELECT {_LEAD_FIELDS} FROM Lead WHERE Id = '{_sf(lead_id)}'"
                , ctx)
            except Exception:  # noqa: BLE001
                pass
        return {
            "created": True,
            "lead": _simplify_lead(created[0]) if created else {"id": lead_id},
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_create_lead_error", error=str(exc))
        return {"created": False, "error": str(exc)}


async def tool_update_lead(
    lead_id: str,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    company: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    title: Optional[str] = None,
    lead_source: Optional[str] = None,
    status: Optional[str] = None,
    description: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Update an existing Salesforce lead.

    Provide only the fields you want to change.

    Args:
        lead_id: The Salesforce Lead record ID.
        first_name: Updated first name.
        last_name: Updated last name.
        company: Updated company name.
        email: Updated email address.
        phone: Updated phone number.
        title: Updated job title.
        lead_source: Updated lead source.
        status: Updated lead status.
        description: Updated description.
    """
    payload: Dict[str, Any] = {}
    if first_name is not None:
        payload["FirstName"] = first_name
    if last_name is not None:
        payload["LastName"] = last_name
    if company is not None:
        payload["Company"] = company
    if email is not None:
        payload["Email"] = email
    if phone is not None:
        payload["Phone"] = phone
    if title is not None:
        payload["Title"] = title
    if lead_source is not None:
        payload["LeadSource"] = lead_source
    if status is not None:
        payload["Status"] = status
    if description is not None:
        payload["Description"] = description

    if not payload:
        raise ValueError("No fields provided to update")

    try:
        LOGGER.info("salesforce_update_lead", lead_id=lead_id, fields=list(payload.keys()))
        await _salesforce_patch(f"/sobjects/Lead/{lead_id}", payload, ctx)

        updated = await _soql_query(
            f"SELECT {_LEAD_FIELDS} FROM Lead WHERE Id = '{_sf(lead_id)}'"
        , ctx)

        return {
            "success": True,
            "lead": _simplify_lead(updated[0]) if updated else {},
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_update_lead_error", lead_id=lead_id, error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_convert_lead(
    lead_id: str,
    account_id: Optional[str] = None,
    contact_id: Optional[str] = None,
    opportunity_name: Optional[str] = None,
    do_not_create_opportunity: bool = False,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Convert a Salesforce lead to an account, contact, and optionally an opportunity.

    Args:
        lead_id: The Lead record ID to convert (required).
        account_id: Existing Account ID to merge into (creates new if omitted).
        contact_id: Existing Contact ID to merge into (creates new if omitted).
        opportunity_name: Name for the new opportunity (uses lead name if omitted).
        do_not_create_opportunity: If True, skip opportunity creation.
    """
    LOGGER.info("salesforce_convert_lead", lead_id=lead_id)

    lead_action: Dict[str, Any] = {
        "leadId": lead_id,
        "convertedStatus": "Closed - Converted",
        "doNotCreateOpportunity": do_not_create_opportunity,
    }
    if account_id:
        lead_action["accountId"] = account_id
    if contact_id:
        lead_action["contactId"] = contact_id
    if opportunity_name:
        lead_action["opportunityName"] = opportunity_name

    try:
        body = {"inputs": [lead_action]}
        result = await _salesforce_post("/actions/standard/convertLead", body, ctx)
        return {
            "success": True,
            "lead_id": lead_id,
            "result": result,
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_convert_lead_error", lead_id=lead_id, error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Campaigns ───────────────────────────────────────────────────────

_CAMPAIGN_FIELDS = (
    "Id, Name, Type, Status, StartDate, EndDate, NumberOfLeads, "
    "NumberOfContacts, NumberOfOpportunities, ActualCost, BudgetedCost, "
    "ExpectedRevenue, Description, IsActive, CreatedDate"
)


def _simplify_campaign(raw: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": raw.get("Id"),
        "name": raw.get("Name"),
        "type": raw.get("Type"),
        "status": raw.get("Status"),
        "start_date": raw.get("StartDate"),
        "end_date": raw.get("EndDate"),
        "number_of_leads": raw.get("NumberOfLeads"),
        "number_of_contacts": raw.get("NumberOfContacts"),
        "number_of_opportunities": raw.get("NumberOfOpportunities"),
        "actual_cost": raw.get("ActualCost"),
        "budgeted_cost": raw.get("BudgetedCost"),
        "expected_revenue": raw.get("ExpectedRevenue"),
        "description": raw.get("Description"),
        "is_active": raw.get("IsActive"),
        "created_date": raw.get("CreatedDate"),
    }


async def tool_list_campaigns(
    status: Optional[str] = None,
    campaign_type: Optional[str] = None,
    limit: int = 20,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List Salesforce marketing campaigns.

    Args:
        status: Filter by campaign status (e.g. "Planned", "In Progress", "Completed", "Aborted").
        campaign_type: Filter by campaign type (e.g. "Email", "Webinar", "Conference").
        limit: Maximum results (default 20, max 100).
    """
    clauses: List[str] = []
    if status:
        clauses.append(f"Status = '{_sf(status)}'")
    if campaign_type:
        clauses.append(f"Type = '{_sf(campaign_type)}'")

    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    safe_limit = max(1, min(int(limit), 100))

    query = (
        f"SELECT {_CAMPAIGN_FIELDS} "
        f"FROM Campaign{where} "
        f"ORDER BY StartDate DESC "
        f"LIMIT {safe_limit}"
    )

    LOGGER.info("salesforce_list_campaigns", query=query)
    records = await _soql_query(query, ctx)

    return {
        "total": len(records),
        "campaigns": [_simplify_campaign(r) for r in records],
    }


async def tool_get_campaign(campaign_id: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Get details for a Salesforce campaign including member summary.

    Args:
        campaign_id: The Salesforce Campaign record ID.
    """
    LOGGER.info("salesforce_get_campaign", campaign_id=campaign_id)

    records = await _soql_query(
        f"SELECT {_CAMPAIGN_FIELDS} "
        f"FROM Campaign WHERE Id = '{_sf(campaign_id)}'"
    , ctx)

    if not records:
        raise ValueError(f"Salesforce Campaign {campaign_id} not found")

    members: List[Dict[str, Any]] = []
    try:
        member_records = await _soql_query(
            f"SELECT Id, ContactId, LeadId, Status, FirstRespondedDate, "
            f"CampaignId, Name "
            f"FROM CampaignMember WHERE CampaignId = '{_sf(campaign_id)}' "
            f"ORDER BY CreatedDate DESC LIMIT 50"
        , ctx)
        for m in member_records:
            members.append({
                "id": m.get("Id"),
                "contact_id": m.get("ContactId"),
                "lead_id": m.get("LeadId"),
                "status": m.get("Status"),
                "name": m.get("Name"),
                "first_responded_date": m.get("FirstRespondedDate"),
            })
    except httpx.HTTPStatusError:
        raise
    except Exception:  # noqa: BLE001
        LOGGER.debug("campaign_members_fetch_failed")

    return {
        "campaign": _simplify_campaign(records[0]),
        "members": members,
        "member_count": len(members),
    }


async def tool_add_campaign_member(
    campaign_id: str,
    contact_id: Optional[str] = None,
    lead_id: Optional[str] = None,
    status: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Add a contact or lead to a Salesforce campaign.

    Provide either contact_id or lead_id, but not both.

    Args:
        campaign_id: The Salesforce Campaign record ID (required).
        contact_id: The Salesforce Contact ID to add.
        lead_id: The Salesforce Lead ID to add.
        status: Campaign member status (e.g. "Sent", "Responded").
    """
    if not contact_id and not lead_id:
        raise ValueError("Either contact_id or lead_id must be provided")
    if contact_id and lead_id:
        raise ValueError("Provide either contact_id or lead_id, not both")

    payload: Dict[str, Any] = {
        "CampaignId": campaign_id,
    }
    if contact_id:
        payload["ContactId"] = contact_id
    if lead_id:
        payload["LeadId"] = lead_id
    if status:
        payload["Status"] = status

    LOGGER.info("salesforce_add_campaign_member", fields=list(payload.keys()))

    try:
        result = await _salesforce_post("/sobjects/CampaignMember", payload, ctx)
        member_id = result.get("id", "")
        return {
            "created": True,
            "campaign_member": {"id": member_id, "campaign_id": campaign_id,
                                "contact_id": contact_id, "lead_id": lead_id,
                                "status": status},
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_add_campaign_member_error", error=str(exc))
        return {"created": False, "error": str(exc)}


# ── Quotes ──────────────────────────────────────────────────────────


async def tool_show_create_quote_form(
    name: Optional[str] = None,
    opportunity_id: Optional[str] = None,
    opportunity_name: Optional[str] = None,
    expiration_date: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Show the quote creation form widget.

    Returns pre-fill data so the widget can populate the form.  The user
    completes and submits the form inside the widget -- this tool does not
    create the quote directly.

    If *opportunity_name* is provided without *opportunity_id*, the name is
    included in the prefill so the widget can prompt the user to select the
    correct opportunity.

    Args:
        name: Optional pre-fill for the quote name.
        opportunity_id: Optional opportunity ID to link the quote to.
        opportunity_name: Optional opportunity name for display/lookup.
        expiration_date: Optional pre-fill for expiration date.
        description: Optional pre-fill for description.
        status: Optional pre-fill for quote status.
    """
    prefill: Dict[str, Any] = {}
    if name:
        prefill["name"] = name
    if opportunity_id:
        prefill["opportunity_id"] = opportunity_id
    if opportunity_name:
        prefill["opportunity_name"] = opportunity_name
    if expiration_date:
        prefill["expiration_date"] = expiration_date
    if description:
        prefill["description"] = description
    if status:
        prefill["status"] = status

    return {
        "_widget_hint": "The quote form is ready. Acknowledge with one short sentence.",
        **prefill,
    }


async def tool_create_quote(
    name: str,
    opportunity_id: str,
    expiration_date: Optional[str] = None,
    description: Optional[str] = None,
    status: str = "Draft",
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Create a Salesforce quote linked to an opportunity.

    Args:
        name: Quote name (required).
        opportunity_id: The Opportunity ID to link this quote to (required).
        expiration_date: Quote expiration date (ISO 8601, e.g. "2025-12-31").
        description: Additional description for the quote.
        status: Quote status (default "Draft").
    """
    payload: Dict[str, Any] = {
        "Name": name,
        "OpportunityId": opportunity_id,
        "Status": status,
    }
    if expiration_date:
        payload["ExpirationDate"] = expiration_date
    if description:
        payload["Description"] = description

    LOGGER.info("salesforce_create_quote", fields=list(payload.keys()))

    try:
        result = await _salesforce_post("/sobjects/Quote", payload, ctx)
        quote_id = result.get("id", "")
        created: List[Dict[str, Any]] = []
        if quote_id:
            try:
                created = await _soql_query(
                    f"SELECT Id, Name, OpportunityId, Status, ExpirationDate, "
                    f"Description, CreatedDate "
                    f"FROM Quote WHERE Id = '{_sf(quote_id)}'"
                , ctx)
            except Exception:  # noqa: BLE001
                pass
        return {
            "created": True,
            "quote": created[0] if created else {"id": quote_id},
            "opportunity_id": opportunity_id,
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_create_quote_error", error=str(exc))
        return {"created": False, "error": str(exc)}


async def tool_update_quote(
    quote_id: str,
    name: Optional[str] = None,
    expiration_date: Optional[str] = None,
    description: Optional[str] = None,
    status: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Update an existing Salesforce quote.

    Provide only the fields you want to change.

    Args:
        quote_id: The Salesforce Quote record ID.
        name: Updated quote name.
        expiration_date: Updated expiration date (ISO 8601, e.g. "2025-12-31").
        description: Updated description.
        status: Updated quote status.
    """
    payload: Dict[str, Any] = {}
    if name is not None:
        payload["Name"] = name
    if expiration_date is not None:
        payload["ExpirationDate"] = expiration_date
    if description is not None:
        payload["Description"] = description
    if status is not None:
        payload["Status"] = status

    if not payload:
        raise ValueError("No fields provided to update")

    try:
        LOGGER.info("salesforce_update_quote", quote_id=quote_id, fields=list(payload.keys()))
        await _salesforce_patch(f"/sobjects/Quote/{quote_id}", payload, ctx)

        updated = await _soql_query(
            f"SELECT Id, Name, OpportunityId, Status, ExpirationDate, "
            f"Description, CreatedDate "
            f"FROM Quote WHERE Id = '{_sf(quote_id)}'"
        , ctx)

        return {
            "success": True,
            "quote": updated[0] if updated else {},
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_update_quote_error", quote_id=quote_id, error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Products ────────────────────────────────────────────────────────


async def tool_list_products(
    family: Optional[str] = None,
    search_text: Optional[str] = None,
    limit: int = 25,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List products from the Salesforce product catalog.

    Args:
        family: Filter by product family.
        search_text: Free-text search across Name, ProductCode, and Description.
        limit: Maximum results (default 25, max 100).
    """
    clauses: List[str] = ["IsActive = true"]
    if family:
        clauses.append(f"Family = '{_sf(family)}'")
    if search_text:
        s = _sf(search_text)
        clauses.append(
            f"(Name LIKE '%{s}%' OR ProductCode LIKE '%{s}%' OR Description LIKE '%{s}%')"
        )

    where = f" WHERE {' AND '.join(clauses)}"
    safe_limit = max(1, min(int(limit), 100))

    query = (
        f"SELECT Id, Name, ProductCode, Description, IsActive, Family "
        f"FROM Product2{where} "
        f"ORDER BY Name ASC "
        f"LIMIT {safe_limit}"
    )

    LOGGER.info("salesforce_list_products", query=query)
    records = await _soql_query(query, ctx)

    return {
        "total": len(records),
        "products": [
            {
                "id": r.get("Id"),
                "name": r.get("Name"),
                "product_code": r.get("ProductCode"),
                "description": r.get("Description"),
                "is_active": r.get("IsActive"),
                "family": r.get("Family"),
            }
            for r in records
        ],
    }


# ── Forecasting ─────────────────────────────────────────────────────


async def tool_get_forecast(
    owner_name: Optional[str] = None,
    fiscal_year: Optional[int] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Get a sales forecast / pipeline summary aggregated by stage.

    Uses SOQL aggregate queries on Opportunity grouped by StageName.

    Args:
        owner_name: Filter by opportunity owner name.
        fiscal_year: Filter by fiscal year (e.g. 2025).
    """
    clauses: List[str] = ["IsClosed = false"]
    if owner_name:
        clauses.append(f"Owner.Name = '{_sf(owner_name)}'")
    if fiscal_year:
        clauses.append(f"CALENDAR_YEAR(CloseDate) = {int(fiscal_year)}")

    where = f" WHERE {' AND '.join(clauses)}"

    query = (
        f"SELECT StageName, COUNT(Id) cnt, SUM(Amount) total_amount, "
        f"AVG(Probability) avg_probability "
        f"FROM Opportunity{where} "
        f"GROUP BY StageName "
        f"ORDER BY StageName ASC"
    )

    LOGGER.info("salesforce_get_forecast", query=query)
    records = await _soql_query(query, ctx)

    grand_total = 0.0
    grand_weighted = 0.0
    grand_count = 0
    stages: List[Dict[str, Any]] = []

    for r in records:
        amount = float(r.get("total_amount") or 0)
        prob = float(r.get("avg_probability") or 0)
        count = int(r.get("cnt") or 0)
        grand_total += amount
        grand_weighted += amount * (prob / 100.0)
        grand_count += count
        stages.append({
            "stage": r.get("StageName"),
            "count": count,
            "total_amount": amount,
            "avg_probability": prob,
            "weighted_amount": amount * (prob / 100.0),
        })

    return {
        "totals": {
            "opportunities": grand_count,
            "pipeline_amount": grand_total,
            "weighted_pipeline_amount": grand_weighted,
        },
        "stages": stages,
    }


# ── Reports ─────────────────────────────────────────────────────────


async def tool_list_reports(limit: int = 20, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """List available Salesforce reports.

    Args:
        limit: Maximum results (default 20, max 200).
    """
    LOGGER.info("salesforce_list_reports")
    safe_limit = max(1, min(int(limit), 200))

    result = await _salesforce_get("/analytics/reports", ctx)

    reports: List[Dict[str, Any]] = []
    items: Any = result if isinstance(result, list) else []
    for r in items:
        reports.append({
            "id": r.get("id"),
            "name": r.get("name"),
            "description": r.get("description"),
            "report_format": r.get("reportFormat"),
            "folder_name": r.get("folderName"),
        })
        if len(reports) >= safe_limit:
            break

    return {
        "total": len(reports),
        "reports": reports,
    }


async def tool_run_report(report_id: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Run a Salesforce report and return results.

    Args:
        report_id: The Salesforce Report record ID.
    """
    LOGGER.info("salesforce_run_report", report_id=report_id)

    try:
        result = await _salesforce_get(f"/analytics/reports/{report_id}", ctx)
        report_metadata = result.get("reportMetadata", {})
        fact_map = result.get("factMap", {})
        report_extended = result.get("reportExtendedMetadata", {})

        return {
            "report_id": report_id,
            "name": report_metadata.get("name"),
            "report_format": report_metadata.get("reportFormat"),
            "detail_columns": report_metadata.get("detailColumns", []),
            "fact_map": fact_map,
            "extended_metadata": report_extended,
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("salesforce_run_report_error", report_id=report_id, error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_team_pipeline_summary(
    owner_ids: str = "",
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Get an aggregated pipeline summary grouped by sales rep.

    Useful for sales managers who need a team-level view of pipeline
    with per-rep totals, deal counts, average deal size, and stage breakdowns.

    Args:
        owner_ids: Optional comma-separated Salesforce User IDs to limit to
                   specific reps. If empty, all open pipeline is included.
    """
    clauses: List[str] = ["IsClosed = false"]
    if owner_ids:
        ids = [f"'{_sf(uid.strip())}'" for uid in owner_ids.split(",") if uid.strip()]
        if ids:
            clauses.append(f"OwnerId IN ({','.join(ids)})")

    where = f" WHERE {' AND '.join(clauses)}"

    query = (
        f"SELECT {_OPPORTUNITY_FIELDS} "
        f"FROM Opportunity{where} "
        f"ORDER BY Owner.Name ASC, Amount DESC "
        f"LIMIT 500"
    )

    LOGGER.info("salesforce_get_team_pipeline_summary", query=query)
    records = await _soql_query(query, ctx)

    rep_rollup: Dict[str, Dict[str, Any]] = {}
    team_total_amount = 0.0
    team_total_weighted = 0.0

    for raw in records:
        owner = raw.get("Owner") or {}
        owner_id = raw.get("OwnerId") or "unknown"
        owner_name = owner.get("Name") if isinstance(owner, dict) else str(owner)
        owner_name = owner_name or "Unknown"
        stage = raw.get("StageName") or "Unknown"
        amount = float(raw.get("Amount") or 0)
        prob = float(raw.get("Probability") or 0)

        team_total_amount += amount
        team_total_weighted += amount * (prob / 100.0)

        rep = rep_rollup.setdefault(
            owner_id,
            {
                "owner_id": owner_id,
                "owner_name": owner_name,
                "total_amount": 0.0,
                "weighted_amount": 0.0,
                "count": 0,
                "stages": {},
            },
        )
        rep["total_amount"] += amount
        rep["weighted_amount"] += amount * (prob / 100.0)
        rep["count"] += 1

        stage_entry = rep["stages"].setdefault(
            stage, {"stage": stage, "count": 0, "amount": 0.0}
        )
        stage_entry["count"] += 1
        stage_entry["amount"] += amount

    reps: List[Dict[str, Any]] = []
    for rep in sorted(rep_rollup.values(), key=lambda r: r["total_amount"], reverse=True):
        avg_deal = rep["total_amount"] / rep["count"] if rep["count"] else 0.0
        reps.append({
            "owner_id": rep["owner_id"],
            "owner_name": rep["owner_name"],
            "total_amount": rep["total_amount"],
            "weighted_amount": rep["weighted_amount"],
            "count": rep["count"],
            "avg_deal_size": avg_deal,
            "stages": sorted(
                rep["stages"].values(), key=lambda s: s["amount"], reverse=True
            ),
        })

    return {
        "team_totals": {
            "reps": len(reps),
            "opportunities": len(records),
            "pipeline_amount": team_total_amount,
            "weighted_pipeline_amount": team_total_weighted,
        },
        "reps": reps,
    }


_VALID_PERIODS = {"THIS_QUARTER", "THIS_MONTH", "THIS_YEAR", "LAST_QUARTER"}


async def tool_get_team_performance_metrics(
    period: str = "THIS_QUARTER",
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Get team performance metrics and leaderboard for sales reps.

    Computes per-rep revenue, win rate, and activity counts for the given
    period. Useful for manager-level performance reviews and leaderboards.

    Args:
        period: Date literal for the time window. One of THIS_QUARTER
                (default), THIS_MONTH, THIS_YEAR, or LAST_QUARTER.
    """
    period = period.strip().upper() if period else "THIS_QUARTER"
    if period not in _VALID_PERIODS:
        period = "THIS_QUARTER"

    # -- Closed-Won revenue by owner ----------------------------------------
    won_query = (
        f"SELECT Owner.Name, OwnerId, COUNT(Id) cnt, SUM(Amount) total_amount "
        f"FROM Opportunity "
        f"WHERE IsWon = true AND CloseDate = {period} "
        f"GROUP BY Owner.Name, OwnerId "
        f"ORDER BY SUM(Amount) DESC"
    )

    LOGGER.info("salesforce_team_perf_won", query=won_query)
    won_records = await _soql_query(won_query, ctx)

    # -- Closed-Lost count by owner ------------------------------------------
    lost_query = (
        f"SELECT OwnerId, COUNT(Id) cnt "
        f"FROM Opportunity "
        f"WHERE IsClosed = true AND IsWon = false AND CloseDate = {period} "
        f"GROUP BY OwnerId"
    )

    LOGGER.info("salesforce_team_perf_lost", query=lost_query)
    lost_records = await _soql_query(lost_query, ctx)

    lost_by_owner: Dict[str, int] = {}
    for r in lost_records:
        lost_by_owner[r.get("OwnerId", "")] = int(r.get("cnt") or 0)

    # -- Activity counts (Tasks + Events) ------------------------------------
    task_query = (
        f"SELECT OwnerId, COUNT(Id) cnt "
        f"FROM Task "
        f"WHERE CreatedDate = {period} AND Status = 'Completed' "
        f"GROUP BY OwnerId"
    )
    event_query = (
        f"SELECT OwnerId, COUNT(Id) cnt "
        f"FROM Event "
        f"WHERE CreatedDate = {period} "
        f"GROUP BY OwnerId"
    )

    LOGGER.info("salesforce_team_perf_tasks", query=task_query)
    task_records = await _soql_query(task_query, ctx)
    LOGGER.info("salesforce_team_perf_events", query=event_query)
    event_records = await _soql_query(event_query, ctx)

    tasks_by_owner: Dict[str, int] = {}
    for r in task_records:
        tasks_by_owner[r.get("OwnerId", "")] = int(r.get("cnt") or 0)

    events_by_owner: Dict[str, int] = {}
    for r in event_records:
        events_by_owner[r.get("OwnerId", "")] = int(r.get("cnt") or 0)

    # -- Build per-rep metrics -----------------------------------------------
    team_revenue = 0.0
    team_won = 0
    team_lost = 0
    reps: List[Dict[str, Any]] = []

    for r in won_records:
        owner_id = r.get("OwnerId") or "unknown"
        owner_obj = r.get("Owner") or {}
        owner_name = owner_obj.get("Name") if isinstance(owner_obj, dict) else str(owner_obj)
        owner_name = owner_name or "Unknown"
        revenue = float(r.get("total_amount") or 0)
        won_count = int(r.get("cnt") or 0)
        lost_count = lost_by_owner.get(owner_id, 0)
        total_closed = won_count + lost_count
        win_rate = (won_count / total_closed * 100.0) if total_closed else 0.0

        team_revenue += revenue
        team_won += won_count
        team_lost += lost_count

        reps.append({
            "owner_id": owner_id,
            "owner_name": owner_name,
            "revenue": revenue,
            "deals_won": won_count,
            "deals_lost": lost_count,
            "win_rate": round(win_rate, 1),
            "tasks_completed": tasks_by_owner.get(owner_id, 0),
            "events_logged": events_by_owner.get(owner_id, 0),
        })

    team_total_closed = team_won + team_lost
    team_win_rate = (team_won / team_total_closed * 100.0) if team_total_closed else 0.0

    return {
        "period": period,
        "team_totals": {
            "reps": len(reps),
            "revenue": team_revenue,
            "deals_won": team_won,
            "deals_lost": team_lost,
            "win_rate": round(team_win_rate, 1),
        },
        "reps": reps,
    }


# ── Tool registry ───────────────────────────────────────────────────

SALESFORCE_TOOL_SPECS: list[dict] = [
    {
        "name": "list_tasks",
        "func": tool_list_tasks,
        "summary": (
            "List Salesforce tasks. Optionally filter by status, priority, "
            "or owner name."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_task",
        "func": tool_get_task,
        "summary": (
            "Get full details for a single Salesforce task by ID. "
            "Result is rendered as an interactive widget where the user can "
            "edit and submit updates."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/update-task.html",
            "openai/toolInvocation/invoking": "Loading task\u2026",
            "openai/toolInvocation/invoked": "Task ready.",
        },
    },
    {
        "name": "update_task",
        "func": tool_update_task,
        "summary": (
            "Submit task updates to Salesforce. Widget callback — called automatically "
            "by the task widget after the user clicks Submit. To view or edit a task, "
            "use get_task to load the task widget."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "create_task",
        "func": tool_create_task,
        "summary": "Create a standalone Salesforce task. Optionally link to an account/opportunity (what_id) or contact/lead (who_id).",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_approvals",
        "func": tool_list_approvals,
        "summary": (
            "List Salesforce approval work items (ProcessInstanceWorkitem). "
            "Defaults to pending approvals."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "approve_reject",
        "func": tool_approve_reject,
        "summary": (
            "Approve or reject a Salesforce approval work item."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_cases",
        "func": tool_list_cases,
        "summary": (
            "List Salesforce compliance cases. Used by the Compliance function "
            "to track regulatory investigations, AML/KYC reviews, fraud cases, "
            "policy breaches, sanctions screening, data privacy issues, and "
            "other compliance matters. Supports filtering by status, priority, "
            "compliance type, and free-text search."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_case",
        "func": tool_get_case,
        "summary": (
            "Get full details for a single Salesforce compliance case by ID or "
            "CaseNumber, including case comments / history. Result is rendered as "
            "an interactive widget where the user can edit and submit updates."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/compliance-case.html",
            "openai/toolInvocation/invoking": "Loading compliance case\u2026",
            "openai/toolInvocation/invoked": "Compliance case ready.",
        },
    },
    {
        "name": "show_compliance_case_form",
        "func": tool_show_compliance_case_form,
        "summary": (
            "Create a new compliance case — opens the interactive creation form "
            "for the user to fill in and submit. Use this when the user asks to "
            "raise a compliance concern, create a case, or log a compliance matter. "
            "Pass any known details to pre-fill fields."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/compliance-case.html",
            "openai/toolInvocation/invoking": "Loading compliance case form\u2026",
            "openai/toolInvocation/invoked": "Compliance case form ready.",
        },
    },
    {
        "name": "create_case",
        "func": tool_create_case,
        "summary": (
            "Submit compliance case creation to Salesforce. Widget callback — "
            "called automatically by the compliance case form after the user clicks Submit. "
            "To create a case, use show_compliance_case_form instead."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/compliance-case.html",
            "openai/toolInvocation/invoking": "Raising compliance case\u2026",
            "openai/toolInvocation/invoked": "Compliance case ready.",
        },
    },
    {
        "name": "update_case",
        "func": tool_update_case,
        "summary": (
            "Submit compliance case updates to Salesforce. Widget callback — "
            "called automatically by the case widget after the user clicks Submit. "
            "To view or edit a case, use get_case to load the case widget."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/compliance-case.html",
            "openai/toolInvocation/invoking": "Updating compliance case\u2026",
            "openai/toolInvocation/invoked": "Case updated.",
        },
    },
    {
        "name": "list_accounts",
        "func": tool_list_accounts,
        "summary": (
            "List Salesforce accounts with optional search, industry, and owner filters."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_contacts",
        "func": tool_list_contacts,
        "summary": (
            "List Salesforce contacts, optionally filtered by account or search text."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "create_contact",
        "func": tool_create_contact,
        "summary": "Create a new Salesforce contact. Optionally link to an account.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "update_contact",
        "func": tool_update_contact,
        "summary": "Update an existing Salesforce contact. Provide the contact_id and any fields to change.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_activity_timeline",
        "func": tool_get_activity_timeline,
        "summary": "Get the activity timeline for a Salesforce record (Account, Contact, Opportunity, or Lead) including tasks and events sorted chronologically.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_opportunities",
        "func": tool_list_opportunities,
        "summary": (
            "List Salesforce opportunities for CRM and sales pipeline workflows."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_account_360",
        "func": tool_get_account_360,
        "summary": (
            "Get a 360-degree account view including contacts, opportunities, events, tasks, and cases."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/crm-account-360.html",
            "openai/toolInvocation/invoking": "Loading account 360-degree view\u2026",
            "openai/toolInvocation/invoked": "Account 360-degree view ready.",
        },
    },
    {
        "name": "get_pipeline_dashboard",
        "func": tool_get_pipeline_dashboard,
        "summary": (
            "Build a pipeline dashboard view with stage rollups and opportunity list for funnel/tornado analysis."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/crm-pipeline.html",
            "openai/toolInvocation/invoking": "Loading sales pipeline\u2026",
            "openai/toolInvocation/invoked": "Pipeline ready.",
        },
    },
    {
        "name": "show_create_opportunity_form",
        "func": tool_show_create_opportunity_form,
        "summary": (
            "Create a new opportunity — opens the interactive creation form "
            "for the user to fill in and submit. Use this when the user asks "
            "to create an opportunity or log a new deal. Pass any known details "
            "to pre-fill fields."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/crm-opportunity.html",
            "openai/toolInvocation/invoking": "Opening opportunity form\u2026",
            "openai/toolInvocation/invoked": "Opportunity form ready.",
        },
    },
    {
        "name": "create_opportunity",
        "func": tool_create_opportunity,
        "summary": (
            "Submit opportunity creation to Salesforce. Widget callback — "
            "called automatically by the opportunity form after the user clicks Submit. "
            "To create an opportunity, use show_create_opportunity_form instead."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/crm-opportunity.html",
            "openai/toolInvocation/invoking": "Creating opportunity\u2026",
            "openai/toolInvocation/invoked": "Opportunity created.",
        },
    },
    {
        "name": "create_opportunity_task",
        "func": tool_create_opportunity_task,
        "summary": (
            "Create a Salesforce task linked to an opportunity."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "update_opportunity",
        "func": tool_update_opportunity,
        "summary": (
            "Submit opportunity updates to Salesforce. Widget callback — "
            "called automatically by the opportunity widget after the user clicks Submit."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/crm-opportunity.html",
            "openai/toolInvocation/invoking": "Updating opportunity\u2026",
            "openai/toolInvocation/invoked": "Opportunity updated.",
        },
    },
    {
        "name": "show_create_event_form",
        "func": tool_show_create_event_form,
        "summary": (
            "Create a new event or meeting — opens the interactive creation form "
            "for the user to fill in and submit. Use this when the user asks to "
            "schedule a meeting, create an event, or log a call. Pass any known "
            "details to pre-fill fields."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/crm-event.html",
            "openai/toolInvocation/invoking": "Opening event form\u2026",
            "openai/toolInvocation/invoked": "Event form ready.",
        },
    },
    {
        "name": "create_event",
        "func": tool_create_event,
        "summary": (
            "Submit event creation to Salesforce. Widget callback — "
            "called automatically by the event form after the user clicks Submit. "
            "To create an event, use show_create_event_form instead."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/crm-event.html",
            "openai/toolInvocation/invoking": "Creating event\u2026",
            "openai/toolInvocation/invoked": "Event created.",
        },
    },
    {
        "name": "update_event",
        "func": tool_update_event,
        "summary": (
            "Submit event updates to Salesforce. Widget callback — "
            "called automatically by the event widget after the user clicks Submit."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/crm-event.html",
            "openai/toolInvocation/invoking": "Updating event\u2026",
            "openai/toolInvocation/invoked": "Event updated.",
        },
    },
    {
        "name": "list_leads",
        "func": tool_list_leads,
        "summary": (
            "List or search Salesforce leads. Supports filtering by status, "
            "lead source, and free-text search."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_lead",
        "func": tool_get_lead,
        "summary": (
            "Get full details for a single Salesforce lead by ID."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "show_create_lead_form",
        "func": tool_show_create_lead_form,
        "summary": (
            "Create a new lead — opens the interactive creation form "
            "for the user to fill in and submit. Use this when the user asks "
            "to create a lead or add a new prospect. Pass any known details "
            "to pre-fill fields."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/crm-lead.html",
            "openai/toolInvocation/invoking": "Opening lead form\u2026",
            "openai/toolInvocation/invoked": "Lead form ready.",
        },
    },
    {
        "name": "create_lead",
        "func": tool_create_lead,
        "summary": (
            "Submit lead creation to Salesforce. Widget callback — "
            "called automatically by the lead form after the user clicks Submit. "
            "To create a lead, use show_create_lead_form instead."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/crm-lead.html",
            "openai/toolInvocation/invoking": "Creating lead\u2026",
            "openai/toolInvocation/invoked": "Lead created.",
        },
    },
    {
        "name": "update_lead",
        "func": tool_update_lead,
        "summary": (
            "Submit lead updates to Salesforce. Widget callback — "
            "called automatically by the lead widget after the user clicks Submit."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/crm-lead.html",
            "openai/toolInvocation/invoking": "Updating lead\u2026",
            "openai/toolInvocation/invoked": "Lead updated.",
        },
    },
    {
        "name": "convert_lead",
        "func": tool_convert_lead,
        "summary": (
            "Convert a Salesforce lead to an account, contact, and optionally "
            "an opportunity."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_campaigns",
        "func": tool_list_campaigns,
        "summary": (
            "List Salesforce marketing campaigns with optional status and "
            "type filters."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_campaign",
        "func": tool_get_campaign,
        "summary": (
            "Get details for a Salesforce campaign including campaign members."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "add_campaign_member",
        "func": tool_add_campaign_member,
        "summary": "Add a contact or lead to a Salesforce campaign. Provide either contact_id or lead_id.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "show_create_quote_form",
        "func": tool_show_create_quote_form,
        "summary": (
            "Create a new quote — opens the interactive creation form "
            "for the user to fill in and submit. Use this when the user asks "
            "to create a quote or prepare a quotation. Pass any known details "
            "to pre-fill fields."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/crm-quote.html",
            "openai/toolInvocation/invoking": "Opening quote form\u2026",
            "openai/toolInvocation/invoked": "Quote form ready.",
        },
    },
    {
        "name": "create_quote",
        "func": tool_create_quote,
        "summary": (
            "Submit quote creation to Salesforce. Widget callback — "
            "called automatically by the quote form after the user clicks Submit. "
            "To create a quote, use show_create_quote_form instead."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/crm-quote.html",
            "openai/toolInvocation/invoking": "Creating quote\u2026",
            "openai/toolInvocation/invoked": "Quote created.",
        },
    },
    {
        "name": "update_quote",
        "func": tool_update_quote,
        "summary": (
            "Submit quote updates to Salesforce. Widget callback — "
            "called automatically by the quote widget after the user clicks Submit."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/crm-quote.html",
            "openai/toolInvocation/invoking": "Updating quote\u2026",
            "openai/toolInvocation/invoked": "Quote updated.",
        },
    },
    {
        "name": "list_products",
        "func": tool_list_products,
        "summary": (
            "List active products from the Salesforce product catalog with "
            "optional family and search filters."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_forecast",
        "func": tool_get_forecast,
        "summary": (
            "Get a sales forecast / pipeline summary aggregated by opportunity "
            "stage. Supports owner and fiscal year filters."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_reports",
        "func": tool_list_reports,
        "summary": (
            "List available Salesforce reports."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "run_report",
        "func": tool_run_report,
        "summary": (
            "Run a Salesforce report by ID and return results."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_team_pipeline_summary",
        "func": tool_get_team_pipeline_summary,
        "summary": (
            "Get an aggregated pipeline summary grouped by sales rep with "
            "per-rep totals, deal counts, average deal size, and stage breakdowns."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/team-pipeline.html",
            "openai/toolInvocation/invoking": "Loading team pipeline\u2026",
            "openai/toolInvocation/invoked": "Team pipeline ready.",
        },
    },
    {
        "name": "get_team_performance_metrics",
        "func": tool_get_team_performance_metrics,
        "summary": (
            "Get team performance metrics and leaderboard including revenue, "
            "win rate, and activity counts per sales rep for a given period."
        ),
        "annotations": {"readOnlyHint": True},
    },
]
