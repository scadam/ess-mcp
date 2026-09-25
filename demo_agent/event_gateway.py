"""Signed webhooks from systems of record: each is a doorbell that names a record, never trusted content.

ServiceNow (a business rule) and Salesforce (an Apex trigger) sign ``<timestamp>.<body>`` with HMAC-SHA256 using a
per-source secret held in Key Vault. A request older than five minutes, a bad signature or an oversized body is
refused before anything is parsed. The colleague always re-reads the record through its governed tools, so a
payload can at most point it at a real record; loop prevention drops the colleague's own writes.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from typing import Any

from aiohttp import web

from .case_desk import CaseDesk, CaseEvent

_logger = logging.getLogger("group-functions-autopilot.events")

MAX_BODY = 64 * 1024
MAX_SKEW = 300
SOURCES = {"servicenow": "it", "salesforce": "compliance"}


def secret_for(source: str) -> bytes:
    return os.getenv(f"AUTOPILOT_WEBHOOK_SECRET_{source.upper()}", "").encode()


def sign(secret: bytes, timestamp: str, body: bytes) -> str:
    return "v1=" + hmac.new(secret, timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def verify(source: str, headers: Any, body: bytes, *, now: float | None = None) -> None:
    secret = secret_for(source)
    if len(secret) < 32:
        raise web.HTTPServiceUnavailable(text="This event source is not configured.")
    timestamp = headers.get("X-Autopilot-Timestamp", "")
    signature = headers.get("X-Autopilot-Signature", "")
    if not timestamp.isdigit() or abs((now or time.time()) - int(timestamp)) > MAX_SKEW:
        raise web.HTTPUnauthorized(text="The event timestamp is missing or outside the allowed window.")
    if not hmac.compare_digest(sign(secret, timestamp, body), signature):
        raise web.HTTPUnauthorized(text="The event signature is invalid.")


def _text(value: Any, limit: int = 400) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _person(value: Any) -> dict[str, str]:
    value = value if isinstance(value, dict) else {}
    return {"name": _text(value.get("name"), 120), "email": _text(value.get("email"), 200).lower(),
            "systemUserId": _text(value.get("sys_id") or value.get("id"), 80),
            "userName": _text(value.get("user_name") or value.get("username"), 120)}


def servicenow_event(payload: dict[str, Any]) -> CaseEvent | None:
    table = _text(payload.get("table"), 40)
    if table not in {"incident", "sc_req_item"} or not _text(payload.get("sys_id"), 64):
        return None
    integration = os.getenv("AUTOPILOT_SERVICENOW_INTEGRATION_USER", "admin").lower()
    comment = payload.get("comment") if isinstance(payload.get("comment"), dict) else {}
    comment_by = _text(comment.get("by"), 120).lower()
    operation = _text(payload.get("operation"), 20)
    updated_by = _text(payload.get("updated_by"), 120).lower()
    if operation != "insert":
        if comment_by and comment_by == integration:
            return None  # The colleague's own comment echoed back.
        if not comment_by and updated_by == integration:
            return None  # The colleague's own field changes echoed back.
    caller = _person(payload.get("caller"))
    return CaseEvent(
        source="servicenow", kind="created" if operation == "insert" else ("comment" if comment_by else "updated"),
        function="it", system="servicenow", record_id=_text(payload["sys_id"], 64),
        number=_text(payload.get("number"), 40), title=_text(payload.get("short_description"), 240),
        text=_text(comment.get("text"), 3000), actor=caller,
        channel={"kind": "servicenow"}, event_id="sn:" + _text(payload.get("event_id") or payload["sys_id"], 120),
    )


def salesforce_event(payload: dict[str, Any]) -> CaseEvent | None:
    case_id = _text(payload.get("case_id") or payload.get("id"), 18)
    if not case_id.startswith("500"):
        return None
    integration = os.getenv("AUTOPILOT_SALESFORCE_INTEGRATION_USER", "").lower()
    comment = payload.get("comment") if isinstance(payload.get("comment"), dict) else {}
    comment_by = _text(comment.get("by"), 120).lower()
    operation = _text(payload.get("operation"), 20)
    modified_by = _text(payload.get("last_modified_by"), 120).lower()
    if operation != "insert" and integration:
        if comment_by and comment_by == integration:
            return None
        if not comment_by and modified_by == integration:
            return None
    contact = _person(payload.get("contact"))
    if not contact["email"]:
        contact["email"] = _text(payload.get("supplied_email"), 200).lower()
    return CaseEvent(
        source="salesforce", kind="created" if operation == "insert" and not comment_by else ("comment" if comment_by else "updated"),
        function="compliance", system="salesforce", record_id=case_id, number=_text(payload.get("case_number"), 20),
        title=_text(payload.get("subject"), 240), text=_text(comment.get("text"), 3000), actor=contact,
        channel={"kind": "salesforce"}, event_id="sf:" + _text(payload.get("event_id") or case_id, 120),
    )


_NORMALIZERS = {"servicenow": servicenow_event, "salesforce": salesforce_event}


def handler(desk_provider: Any) -> Any:
    async def handle(request: web.Request) -> web.Response:
        source = request.match_info.get("source", "")
        if source not in _NORMALIZERS:
            raise web.HTTPNotFound(text="Unknown event source.")
        if (request.content_length or 0) > MAX_BODY:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY, actual_size=request.content_length or 0)
        body = await request.content.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY, actual_size=len(body))
        verify(source, request.headers, body)
        try:
            payload = json.loads(body)
        except ValueError:
            raise web.HTTPBadRequest(text="A JSON object is required.") from None
        if type(payload) is not dict:
            raise web.HTTPBadRequest(text="A JSON object is required.")
        desk: CaseDesk | None = desk_provider()
        if desk is None:
            raise web.HTTPServiceUnavailable(text="The case desk is not running.")
        event = _NORMALIZERS[source](payload)
        if event is None:
            return web.json_response({"accepted": False, "reason": "not a case event"}, status=202)
        key = await desk.submit(event)
        _logger.info("events.in source=%s kind=%s admitted=%s", source, event.kind, bool(key))
        return web.json_response({"accepted": bool(key), "case": (key or "")[:12]}, status=202)

    return handle
