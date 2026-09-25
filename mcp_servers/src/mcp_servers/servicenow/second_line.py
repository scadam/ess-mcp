"""Second-line ServiceNow tools: the desk's queue sweep, the requester's profile, devices and diagnostics, deskside
tasks, and a host-only account reset for applications whose accounts live in this instance.

Everything uses the Table and Attachment APIs of the configured instance with the server's own credentials.
"""
from __future__ import annotations

import re
import secrets
import string
from typing import Any, Dict, List, Optional

from fastmcp import Context

from ..auth import resolve_servicenow_token
from ..auth.caller import CallerNotTrusted, verify_caller
from ..http import create_async_client
from ..logging import get_logger
from ..settings import load_servicenow_settings

LOGGER = get_logger(__name__)

PRIVILEGED_ROLES = frozenset({"admin", "security_admin", "impersonator", "user_admin", "oauth_admin", "maint"})
_TEXT_TYPES = ("text/", "application/json", "application/xml", "application/csv")
_USER = re.compile(r"[A-Za-z0-9._@'\- ]{2,120}")


def _v(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("display_value", value.get("value"))
    return value


async def _get(path: str, params: Dict[str, Any], ctx: Optional[Context]) -> List[Dict[str, Any]]:
    settings = load_servicenow_settings()
    token = await resolve_servicenow_token(ctx)
    async with create_async_client(timeout=45.0) as client:
        response = await client.get(f"{settings.instance_url}{path}", params=params,
                                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        response.raise_for_status()
        return response.json().get("result", [])


async def _write(method: str, path: str, body: Dict[str, Any], ctx: Optional[Context],
                 params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    settings = load_servicenow_settings()
    token = await resolve_servicenow_token(ctx)
    async with create_async_client(timeout=45.0) as client:
        response = await client.request(method, f"{settings.instance_url}{path}", json=body, params=params or {},
                                        headers={"Authorization": f"Bearer {token}", "Accept": "application/json",
                                                 "Content-Type": "application/json"})
        response.raise_for_status()
        return response.json().get("result", {})


async def _user(who: str, ctx: Optional[Context]) -> Optional[Dict[str, Any]]:
    who = (who or "").strip()
    if not _USER.fullmatch(who):
        return None
    field = "email" if "@" in who else "user_name"
    for query in (f"{field}={who}", f"name={who}"):
        rows = await _get("/api/now/table/sys_user", {
            "sysparm_query": query, "sysparm_limit": 1, "sysparm_display_value": "all",
            "sysparm_exclude_reference_link": "true",
            "sysparm_fields": "sys_id,user_name,name,email,title,department,location,manager,vip,active,locked_out,"
                              "failed_attempts,last_login_time,source,password_needs_reset,phone,mobile_phone"}, ctx)
        if rows:
            return rows[0]
    return None


async def _roles(user_id: str, ctx: Optional[Context]) -> List[str]:
    rows = await _get("/api/now/table/sys_user_has_role", {
        "sysparm_query": f"user={user_id}^state=active", "sysparm_fields": "role.name", "sysparm_limit": 60}, ctx)
    return sorted({str(row.get("role.name") or "") for row in rows if row.get("role.name")})


async def tool_list_queue_changes(queue: str = "", updated_since: str = "", limit: int = 50,
                                  ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Incidents in a support group's queue changed since a UTC watermark, oldest first (the desk's sweep).

    Args:
        queue: Assignment group name (e.g. Autopilot Service Desk).
        updated_since: UTC 'YYYY-MM-DD HH:MM:SS' watermark from the previous sweep; empty for the last 3 days.
        limit: Maximum records (1-100).
    """
    settings = load_servicenow_settings()
    query = "sys_updated_onRELATIVEGT@hour@ago@72^ORDERBYsys_updated_on"
    if queue:
        query = f"assignment_group.name={queue}^" + query
    rows = await _get("/api/now/table/incident", {
        "sysparm_query": query, "sysparm_limit": max(1, min(int(limit), 100)), "sysparm_display_value": "false",
        "sysparm_fields": "sys_id,number,short_description,sys_updated_on,sys_updated_by,sys_mod_count,active,state,"
                          "caller_id.name,caller_id.email,caller_id.user_name"}, ctx)
    integration = (settings.oauth_username or "admin").lower()
    records = []
    for row in rows:
        version = str(row.get("sys_updated_on") or "")
        if updated_since and version <= updated_since:
            continue
        count = str(row.get("sys_mod_count") or "0")
        records.append({
            "id": row.get("sys_id"), "number": row.get("number"), "title": row.get("short_description"),
            "version": version, "new": count == "0", "state": row.get("state"),
            "updated_by_integration": count != "0" and str(row.get("sys_updated_by") or "").lower() == integration,
            "requester": {"name": row.get("caller_id.name") or "", "email": (row.get("caller_id.email") or "").lower(),
                          "userName": row.get("caller_id.user_name") or ""},
            "event_id": f"sn:{row.get('sys_id')}:{count}"})
    return {"records": records, "count": len(records), "queue": queue}


async def tool_get_user_profile(user: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """A ServiceNow user's profile: department, location, manager, VIP flag, lock-out state, last login and roles.

    Args:
        user: Email, user name or full name.
    """
    row = await _user(user, ctx)
    if row is None:
        return {"found": False, "error": f"No ServiceNow user matches {user!r}."}
    roles = await _roles(_v(row.get("sys_id")) or "", ctx)
    profile = {key: _v(row.get(key)) for key in ("user_name", "name", "email", "title", "department", "location",
                                                  "manager", "vip", "active", "locked_out", "failed_attempts",
                                                  "last_login_time", "source", "password_needs_reset")}
    profile["account_type"] = "directory (SSO)" if profile.get("source") else "local account in this instance"
    return {"found": True, "profile": profile, "roles": roles,
            "privileged": bool(PRIVILEGED_ROLES.intersection(roles))}


async def tool_get_user_devices(user: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Hardware assigned to a user with warranty, lifecycle state and the configuration item's technical details,
    plus open incidents already logged against each device.

    Args:
        user: Email, user name or full name.
    """
    row = await _user(user, ctx)
    if row is None:
        return {"found": False, "error": f"No ServiceNow user matches {user!r}."}
    user_id = _v(row.get("sys_id"))
    assets = await _get("/api/now/table/alm_hardware", {
        "sysparm_query": f"assigned_to={user_id}", "sysparm_limit": 20, "sysparm_display_value": "all",
        "sysparm_exclude_reference_link": "true",
        "sysparm_fields": "sys_id,asset_tag,display_name,model,model_category,serial_number,warranty_expiration,"
                          "install_status,substatus,ci,purchase_date,vendor,cost"}, ctx)
    devices = []
    for asset in assets:
        ci = asset.get("ci") or {}
        ci_id = ci.get("value") if isinstance(ci, dict) else ""
        details: Dict[str, Any] = {}
        incidents: List[str] = []
        if ci_id:
            computers = await _get(f"/api/now/table/cmdb_ci_computer/{ci_id}", {
                "sysparm_display_value": "true",
                "sysparm_fields": "name,os,os_version,ram,disk_space,cpu_type,cpu_count,manufacturer,model_id,"
                                  "serial_number,last_discovered,install_status,comments"}, ctx) if ci_id else []
            details = computers if isinstance(computers, dict) else (computers[0] if computers else {})
            open_rows = await _get("/api/now/table/incident", {
                "sysparm_query": f"cmdb_ci={ci_id}^active=true", "sysparm_fields": "number,short_description",
                "sysparm_limit": 10}, ctx)
            incidents = [f"{item.get('number')}: {item.get('short_description')}" for item in open_rows]
        devices.append({
            "asset_tag": _v(asset.get("asset_tag")), "name": _v(asset.get("display_name")),
            "model": _v(asset.get("model")), "category": _v(asset.get("model_category")),
            "serial_number": _v(asset.get("serial_number")), "warranty_expiration": _v(asset.get("warranty_expiration")),
            "state": _v(asset.get("install_status")), "substate": _v(asset.get("substatus")),
            "purchased": _v(asset.get("purchase_date")), "vendor": _v(asset.get("vendor")),
            "configuration_item": details, "open_incidents": incidents})
    return {"found": True, "user": _v(row.get("name")), "devices": devices, "count": len(devices)}


async def _incident_id(number: str, ctx: Optional[Context]) -> str:
    if not re.fullmatch(r"INC\d{7,10}", (number or "").strip()):
        raise ValueError("An incident number such as INC0010001 is required.")
    rows = await _get("/api/now/table/incident", {"sysparm_query": f"number={number.strip()}", "sysparm_limit": 1,
                                                   "sysparm_fields": "sys_id"}, ctx)
    if not rows:
        raise ValueError(f"Incident {number} was not found.")
    return rows[0]["sys_id"]


async def tool_list_incident_attachments(number: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Files attached to an incident, such as diagnostic reports, logs or screenshots.

    Args:
        number: Incident number.
    """
    sys_id = await _incident_id(number, ctx)
    rows = await _get("/api/now/table/sys_attachment", {
        "sysparm_query": f"table_name=incident^table_sys_id={sys_id}^ORDERBYsys_created_on",
        "sysparm_fields": "sys_id,file_name,size_bytes,content_type,sys_created_on,sys_created_by", "sysparm_limit": 20}, ctx)
    return {"number": number, "attachments": [{"id": row.get("sys_id"), "file_name": row.get("file_name"),
                                                "bytes": row.get("size_bytes"), "content_type": row.get("content_type"),
                                                "added": row.get("sys_created_on"), "by": row.get("sys_created_by")}
                                               for row in rows]}


async def tool_read_attachment(attachment_id: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Read a text attachment (diagnostic report, log, CSV or JSON), up to 20,000 characters.

    Args:
        attachment_id: The attachment sys_id from list_incident_attachments.
    """
    if not re.fullmatch(r"[0-9a-f]{32}", attachment_id or ""):
        return {"read": False, "error": "An attachment sys_id is required."}
    settings = load_servicenow_settings()
    token = await resolve_servicenow_token(ctx)
    meta = await _get(f"/api/now/attachment/{attachment_id}", {}, ctx)
    meta = meta if isinstance(meta, dict) else (meta[0] if meta else {})
    content_type = str(meta.get("content_type") or "")
    if not content_type.startswith(_TEXT_TYPES) and not str(meta.get("file_name", "")).endswith((".log", ".txt", ".csv", ".json")):
        return {"read": False, "error": f"{meta.get('file_name')} is {content_type}; only text reports can be read."}
    async with create_async_client(timeout=45.0) as client:
        response = await client.get(f"{settings.instance_url}/api/now/attachment/{attachment_id}/file",
                                    headers={"Authorization": f"Bearer {token}", "Accept": "*/*"})
        response.raise_for_status()
        text = response.content[:400_000].decode("utf-8", errors="replace")
    return {"read": True, "file_name": meta.get("file_name"), "content": text[:20_000],
            "truncated": len(text) > 20_000}


async def tool_create_incident_task(number: str, short_description: str, description: str = "",
                                    assignment_group: str = "", ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Create a task under an incident, e.g. a deskside hardware swap or a vendor warranty claim.

    Args:
        number: Parent incident number.
        short_description: What must be done.
        description: Details, including any appointment or shipping information.
        assignment_group: Group that does the task.
    """
    sys_id = await _incident_id(number, ctx)
    body: Dict[str, Any] = {"incident": sys_id, "short_description": short_description[:160],
                            "description": description[:4000]}
    if assignment_group:
        body["assignment_group"] = assignment_group
    created = await _write("POST", "/api/now/table/incident_task", body, ctx,
                           params={"sysparm_input_display_value": "true"})
    return {"created": bool(created.get("sys_id")), "number": created.get("number"), "incident": number}


def _temporary_password() -> str:
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(12))
    return (secrets.choice(string.ascii_uppercase) + secrets.choice(string.ascii_lowercase) + core
            + secrets.choice(string.digits) + secrets.choice("!#%+=?@"))


def _mask(email: str) -> str:
    name, _, domain = email.partition("@")
    return f"{name[:2]}***@{domain}" if domain else "***"


async def tool_reset_account_password(user_name: str, expected_email: str, application: str, reference: str = "",
                                      ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Reset and unlock the local account of a non-privileged user; the temporary password goes only to the
    account's registered email. Host-only: requires the Autopilot host's managed-identity assertion.

    Args:
        user_name: The account's user name.
        expected_email: The verified requester's email; must be the account's registered email.
        application: The application whose account this is, for the email.
        reference: Case or incident number to note on the ticket.
    """
    try:
        caller = verify_caller(ctx)
    except CallerNotTrusted as exc:
        return {"reset": False, "error": str(exc)}
    row = await _user(user_name, ctx)
    if row is None or _v(row.get("user_name")) != user_name.strip():
        return {"reset": False, "error": f"No account with user name {user_name!r}."}
    email = str(_v(row.get("email")) or "").lower()
    if str(_v(row.get("active"))).lower() not in {"true", "1"}:
        return {"reset": False, "error": "The account is inactive; reactivation needs the account owner's manager."}
    if not email or email != (expected_email or "").strip().lower():
        return {"reset": False, "error": "The account's registered email is not the requester's, so it was not reset."}
    roles = await _roles(_v(row.get("sys_id")) or "", ctx)
    if PRIVILEGED_ROLES.intersection(roles):
        return {"reset": False, "error": "Privileged accounts are reset only through privileged access management."}
    temporary = _temporary_password()
    user_id = _v(row.get("sys_id"))
    await _write("PATCH", f"/api/now/table/sys_user/{user_id}",
                 {"user_password": temporary, "password_needs_reset": "true", "locked_out": "false",
                  "failed_attempts": "0"}, ctx, params={"sysparm_input_display_value": "true"})
    body = (f"<p>Hello {_v(row.get('name'))},</p><p>Your {application} password was reset at your request"
            f"{' (' + reference + ')' if reference else ''}. Your temporary password is:</p>"
            f"<p style=\"font-family:monospace;font-size:16px\">{temporary}</p><p>You must choose a new password when "
            "you next sign in. If you did not ask for this, contact the service desk immediately.</p>")
    mail = await _write("POST", "/api/now/table/sys_email", {
        "type": "send-ready", "recipients": email, "subject": f"Your temporary {application} password",
        "body": body, "content_type": "text/html", "notification_type": "SMTP"}, ctx)
    smtp = await _get("/api/now/table/sys_properties", {"sysparm_query": "name=glide.email.smtp.active",
                                                          "sysparm_fields": "value"}, ctx)
    if reference.startswith("INC"):
        try:
            incident = await _incident_id(reference, ctx)
            await _write("PATCH", f"/api/now/table/incident/{incident}", {"work_notes": (
                f"Password reset and unlock for {user_name} ({application}) by the Autopilot service desk after "
                f"verifying the requester owns the account. Temporary password sent to {_mask(email)}; it must be "
                "changed at first sign-in.")}, ctx)
        except Exception:
            LOGGER.warning("reset_work_note_failed")
    LOGGER.info("account_password_reset", user=user_name, caller=caller, reference=reference)
    return {"reset": True, "unlocked": True, "user_name": user_name, "delivered_to": _mask(email),
            "must_change_at_next_sign_in": True, "email_record": mail.get("sys_id"),
            "outbound_email_enabled": bool(smtp and str(smtp[0].get("value")).lower() == "true")}


_GROUP = re.compile(r"[A-Za-z0-9&()/,.'\- ]{2,80}")
_MEMBER_FIELDS = ("user.sys_id,user.user_name,user.name,user.email,user.title,user.department,user.active,"
                  "user.last_login_time,user.manager,sys_id")


async def _group(name: str, ctx: Optional[Context]) -> Optional[Dict[str, Any]]:
    if not _GROUP.fullmatch((name or "").strip()):
        return None
    rows = await _get("/api/now/table/sys_user_group", {
        "sysparm_query": f"name={name.strip()}", "sysparm_limit": 1, "sysparm_display_value": "true",
        "sysparm_exclude_reference_link": "true", "sysparm_fields": "sys_id,name,description,manager,email,active"}, ctx)
    return rows[0] if rows else None


async def tool_list_group_members(group: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Members of a ServiceNow group with the facts an access review needs: active flag, last login, title,
    department and manager, plus the roles the group grants and the group's owner.

    Args:
        group: Exact group name, e.g. CAB Approval.
    """
    row = await _group(group, ctx)
    if row is None:
        return {"found": False, "error": f"No group named {group!r}."}
    members = await _get("/api/now/table/sys_user_grmember", {
        "sysparm_query": f"group={row['sys_id']}", "sysparm_limit": 200, "sysparm_display_value": "true",
        "sysparm_exclude_reference_link": "true", "sysparm_fields": _MEMBER_FIELDS}, ctx)
    roles = await _get("/api/now/table/sys_group_has_role", {
        "sysparm_query": f"group={row['sys_id']}", "sysparm_fields": "role.name", "sysparm_limit": 50}, ctx)
    return {"found": True, "group": row.get("name"), "owner": row.get("manager"), "description": row.get("description"),
            "grants_roles": sorted({str(item.get("role.name")) for item in roles if item.get("role.name")}),
            "members": [{"user_name": item.get("user.user_name"), "name": item.get("user.name"),
                         "email": item.get("user.email"), "title": item.get("user.title"),
                         "department": item.get("user.department"), "active": item.get("user.active"),
                         "last_login": item.get("user.last_login_time"), "manager": item.get("user.manager")}
                        for item in members],
            "count": len(members)}


async def tool_list_role_holders(role: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Everyone holding a ServiceNow role, directly or through a group, with active flag and last login.

    Args:
        role: Role name, e.g. admin or security_admin.
    """
    if not re.fullmatch(r"[a-z0-9_.]{2,60}", (role or "").strip()):
        return {"found": False, "error": "A role name such as admin is required."}
    rows = await _get("/api/now/table/sys_user_has_role", {
        "sysparm_query": f"role.name={role.strip()}^state=active", "sysparm_limit": 200, "sysparm_display_value": "true",
        "sysparm_exclude_reference_link": "true",
        "sysparm_fields": "user.user_name,user.name,user.email,user.active,user.last_login_time,inherited,granted_by"}, ctx)
    return {"found": True, "role": role, "holders": [
        {"user_name": item.get("user.user_name"), "name": item.get("user.name"), "email": item.get("user.email"),
         "active": item.get("user.active"), "last_login": item.get("user.last_login_time"),
         "via_group": item.get("granted_by") or "", "inherited": item.get("inherited")} for item in rows],
        "count": len(rows)}


async def tool_remove_group_member(group: str, user_name: str, reference: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Remove a user from a group (and so from the roles it grants) after an access review decision.
    Host-only: requires the Autopilot host's managed-identity assertion.

    Args:
        group: Exact group name.
        user_name: The member's user name.
        reference: The review or case reference, recorded on the audit trail.
    """
    try:
        caller = verify_caller(ctx)
    except CallerNotTrusted as exc:
        return {"removed": False, "error": str(exc)}
    row = await _group(group, ctx)
    if row is None or not _USER.fullmatch((user_name or "").strip()):
        return {"removed": False, "error": "A valid group and user name are required."}
    members = await _get("/api/now/table/sys_user_grmember", {
        "sysparm_query": f"group={row['sys_id']}^user.user_name={user_name.strip()}", "sysparm_limit": 1,
        "sysparm_fields": "sys_id"}, ctx)
    if not members:
        return {"removed": False, "error": f"{user_name} is not a member of {group}."}
    settings = load_servicenow_settings()
    token = await resolve_servicenow_token(ctx)
    async with create_async_client(timeout=45.0) as client:
        response = await client.delete(f"{settings.instance_url}/api/now/table/sys_user_grmember/{members[0]['sys_id']}",
                                       headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        response.raise_for_status()
    LOGGER.info("group_member_removed", group=group, user=user_name, caller=caller, reference=reference[:60])
    return {"removed": True, "group": group, "user_name": user_name, "reference": reference[:60]}


SECOND_LINE_SPECS: list[dict] = [
    {"name": "list_group_members", "func": tool_list_group_members, "annotations": {"readOnlyHint": True},
     "summary": "A group's members with active flag, last login, title and manager, the roles it grants and its owner."},
    {"name": "list_role_holders", "func": tool_list_role_holders, "annotations": {"readOnlyHint": True},
     "summary": "Everyone holding a ServiceNow role, directly or through a group, with active flag and last login."},
    {"name": "remove_group_member", "func": tool_remove_group_member,
     "summary": "Host-only: remove a user from a group (and its roles) after an access review decision."},
    {"name": "list_queue_changes", "func": tool_list_queue_changes, "annotations": {"readOnlyHint": True},
     "summary": "Incidents in a support group's queue changed since a UTC watermark, oldest first (reconciliation sweep)."},
    {"name": "get_user_profile", "func": tool_get_user_profile, "annotations": {"readOnlyHint": True},
     "summary": "A user's ServiceNow profile: department, location, manager, VIP, lock-out state, last login, roles."},
    {"name": "get_user_devices", "func": tool_get_user_devices, "annotations": {"readOnlyHint": True},
     "summary": "Hardware assigned to a user: warranty, lifecycle state, technical details and open incidents per device."},
    {"name": "list_incident_attachments", "func": tool_list_incident_attachments, "annotations": {"readOnlyHint": True},
     "summary": "Files attached to an incident, such as diagnostic reports, logs or screenshots."},
    {"name": "read_attachment", "func": tool_read_attachment, "annotations": {"readOnlyHint": True},
     "summary": "Read a text attachment (diagnostic report, log, CSV or JSON), up to 20,000 characters."},
    {"name": "create_incident_task", "func": tool_create_incident_task,
     "summary": "Create a task under an incident, e.g. a deskside hardware swap or a vendor warranty claim."},
    {"name": "reset_account_password", "func": tool_reset_account_password,
     "summary": ("Host-only: reset and unlock a non-privileged local account; the temporary password is emailed to "
                 "the account's registered address only.")},
]
