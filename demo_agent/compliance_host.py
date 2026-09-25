"""Host wiring for the Compliance Partner case workflow.

An SDK-authenticated Agent 365 email notification becomes one Salesforce case;
the requester's private Teams replies continue it; and every durable case step
and tool call is projected into the control-plane run ledger. Bindings come only
from trusted deployment configuration (``AUTOPILOT_COMPLIANCE_BINDINGS``), never
from notification fields or model output.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from .compliance_backend import (
    ComplianceAuthorizationError, ComplianceBackendError, LiveComplianceBackend, _field, _guid,
)
from .compliance_service import ComplianceBinding, ComplianceService, VerifiedEmail, _hash
from .conversation_memory import Store, scrub_memory_text

__all__ = ["BINDINGS_ENV", "ComplianceHost", "load_bindings"]

_logger = logging.getLogger("group-functions-autopilot.compliance")
BINDINGS_ENV = "AUTOPILOT_COMPLIANCE_BINDINGS"
TEAMS_CHANNEL_ENV = "AUTOPILOT_COMPLIANCE_TEAMS_CHANNEL"
MAX_EMAIL_AGE_SECONDS = 7 * 24 * 60 * 60
DEMO_SUBJECT = "[Demo] Project Seabrook — can we share the diligence pack with the Singapore advisory team today?"
DEMO_BODY = (
    "We are finalising Northbridge Renewables' refinancing. Our external adviser wants the diligence pack for its "
    "Singapore team before tomorrow's lender call. The supplier dashboard is green and we have an NDA, but I am not "
    "sure whether those cover this team. The pack includes revised forecasts and some KYC documents. Can you establish "
    "what we can share, with whom, and what needs changing? The files are in the internal Seabrook deal workspace."
)
MAX_REPLY_AGE_SECONDS = 24 * 60 * 60
# create_task is used only by the host to log interactions on the bound case.
_SALESFORCE_TOOLS = frozenset({"create_case", "update_case", "get_case", "create_task"})
_BINDING_KEYS = frozenset({"name", "instanceAppId", "agenticUserId", "managerId", "requesterIds", "evidencePaths"})
_CURRENT_CASE: contextvars.ContextVar[str] = contextvars.ContextVar("compliance_case", default="")
# Tool events observed before the authenticated email yields its case key.
_PENDING: contextvars.ContextVar[list | None] = contextvars.ContextVar("compliance_pending", default=None)
_OPEN = frozenset({"received", "creating", "investigating", "opening_private_chat", "updating_case",
                   "delivering_answer", "waiting_for_requester", "awaiting_confirmation", "closing",
                   "verifying_close", "notifying_closure"})
_WAITING = {"waiting_for_requester": "Waiting for the requester's reply in Teams",
            "awaiting_confirmation": "Answer delivered; waiting for the requester to confirm resolution",
            "needs_specialist_review": "Needs specialist review; the case stays open"}
_STEPS = {
    "case_received": "Email received and authenticated; registering the case",
    "case_registered": "Salesforce case #{number} created",
    "case_reference_collision": "Salesforce returned a conflicting case reference; reconciliation required",
    "case_investigation_started": "Investigating against the approved evidence library",
    "case_investigation_blocked": "The records couldn't be checked; the next reply retries",
    "case_investigated": "Evidence investigation complete",
    "case_private_chat_ready": "Private Teams chat with the requester is ready",
    "case_updated": "Salesforce case #{number} updated with the findings",
    "case_answer_delivered": "Answer delivered to the requester in Teams",
    "case_reply_received": "Requester replied in Teams",
    "case_chat_received": "Requester messaged in Teams; status shared",
    "case_resolution_rejected": "Resolution command received but the case is not ready to close",
    "case_resolution_requested": "Requester confirmed the answer resolves the question; closing the case",
    "case_close_acknowledged": "Salesforce acknowledged the close; verifying",
    "case_close_readback": "Salesforce readback confirms the case status",
    "case_closure_notice_recorded": "Closure confirmed to the requester in Teams",
    "case_capacity_blocked": "Case reached its bounded capacity; specialist review required",
    "case_outcome_unknown": "An operation outcome is unknown; reconciliation required",
}


def load_bindings(raw: str, tenant_id: str, blueprint_id: str) -> tuple[tuple[ComplianceBinding, str], ...]:
    """Parse deployment JSON; tenant and blueprint always come from host configuration."""
    if not raw or not raw.strip():
        return ()
    data = json.loads(raw)
    if type(data) is not list or len(data) > 20:
        raise ValueError(f"{BINDINGS_ENV} must be a JSON array of at most 20 bindings.")
    result: list[tuple[ComplianceBinding, str]] = []
    for item in data:
        if type(item) is not dict or not set(item) <= _BINDING_KEYS:
            raise ValueError(f"{BINDINGS_ENV} contains an unsupported binding.")
        requesters = item.get("requesterIds")
        paths = item.get("evidencePaths", [])
        if type(requesters) is not list or type(paths) is not list:
            raise ValueError(f"{BINDINGS_ENV} requester and evidence lists must be arrays.")
        name = item.get("name", "Compliance Partner")
        if type(name) is not str or not 0 < len(name.strip()) <= 80:
            raise ValueError(f"{BINDINGS_ENV} binding names must be short nonblank text.")
        binding = ComplianceBinding(
            tenant_id=tenant_id, blueprint_id=blueprint_id,
            instance_app_id=item.get("instanceAppId"), agentic_user_id=item.get("agenticUserId"),
            manager_id=item.get("managerId"), requester_ids=tuple(requesters), evidence_paths=tuple(paths),
        )
        result.append((binding, name.strip()))
    if len({(binding.tenant_id, binding.instance_app_id) for binding, _ in result}) != len(result):
        raise ValueError(f"{BINDINGS_ENV} lists an instance more than once.")
    return tuple(result)


def _single_attempt_client(headers: dict[str, str] | None = None, timeout: httpx.Timeout | None = None,
                           auth: httpx.Auth | None = None, **_kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=headers, timeout=timeout or httpx.Timeout(30, read=90), auth=auth,
                             follow_redirects=False, transport=httpx.AsyncHTTPTransport(retries=0))


def _preview(value: Any, limit: int = 600) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def _reason(exc: BaseException) -> str:
    """Only the backend's deliberately payload-free messages are logged verbatim."""
    if isinstance(exc, (ComplianceBackendError, ComplianceAuthorizationError)):
        return f"{type(exc).__name__}: {exc}"
    return type(exc).__name__


class _ObservedBackend:
    """Delegates to the live backend, narrating each interaction and logging it on the case."""

    def __init__(self, host: "ComplianceHost", live: LiveComplianceBackend) -> None:
        self._host = host
        self._live = live

    async def create_case(self, binding: ComplianceBinding, email: Any, correlation: str) -> dict:
        case = await self._live.create_case(binding, email, correlation)
        self._host._case_refs[correlation] = (case["id"], case["number"])
        name = self._host._name_of(email.requester_id)
        colleague = self._host._bindings[(binding.tenant_id, binding.instance_app_id)][1]
        self._host._log_case_task(binding, correlation, f"Email received: {email.subject}",
                                  f"From {name}. Registered by {colleague}, an AI teammate.\n\n{email.body}")
        return case

    async def interpret_reply(self, binding: ComplianceBinding, record: dict, text: str) -> str:
        return await self._live.interpret_reply(binding, record, text)

    async def notify(self, binding: ComplianceBinding, requester_id: str, chat_id: str, text: str) -> None:
        name = self._host._name_of(requester_id)
        try:
            await self._live.notify(binding, requester_id, chat_id, text)
        except Exception as exc:
            self._host._narrate(binding, "issue", f"Couldn't send {name} a status message in Teams",
                                detail=_reason(exc), status="error", who=name)
            raise
        self._host._tool(binding, "teams", "message_to_requester", {"chat": "private"}, text, True)
        self._host._narrate(binding, "teams-out", f"Messaged {name} privately in Teams", detail=text, status="ok",
                            who=name)

    async def send_confirmation_email(self, binding: ComplianceBinding, requester_id: str, record: dict,
                                      summary: str) -> None:
        name = self._host._name_of(requester_id)
        try:
            await self._live.send_confirmation_email(binding, requester_id, record, summary)
        except Exception as exc:
            self._host._narrate(binding, "issue", f"Couldn't email {name} the case confirmation",
                                detail=f"{_reason(exc)} The summary goes to Teams instead.", status="error", who=name)
            raise
        self._host._narrate(binding, "email", f"Emailed {name} a confirmation of the outcome", detail=summary,
                            status="ok", who=name)
        self._host._log_case_task(binding, _CURRENT_CASE.get(), "Confirmation email to the requester", summary)

    async def ensure_private_chat(self, binding: ComplianceBinding, requester_id: str) -> str:
        return await self._live.ensure_private_chat(binding, requester_id)

    async def investigate(self, binding: ComplianceBinding, record: dict, latest_reply: str) -> Any:
        return await self._live.investigate(binding, record, latest_reply)

    async def send_private(self, binding: ComplianceBinding, requester_id: str, chat_id: str, text: str) -> str:
        message_id = await self._live.send_private(binding, requester_id, chat_id, text)
        self._host._tool(binding, "teams", "message_to_requester", {"chat": "private"}, text, True)
        name = self._host._name_of(requester_id)
        self._host._narrate(binding, "teams-out", f"Messaged {name} privately in Teams", detail=text, status="ok",
                            who=name)
        self._host._log_case_task(binding, _CURRENT_CASE.get(), "Teams message to the requester", text)
        return message_id

    async def update_case(self, binding: ComplianceBinding, case_id: str, comment: str, close: bool = False) -> None:
        await self._live.update_case(binding, case_id, comment, close=close)
        if close:
            self._host._log_case_task(binding, _CURRENT_CASE.get(), "Resolved: the requester confirmed in Teams", comment)

    async def read_case_status(self, binding: ComplianceBinding, case_id: str) -> str:
        return await self._live.read_case_status(binding, case_id)


class ComplianceHost:
    def __init__(
        self, *, bindings: tuple[tuple[ComplianceBinding, str], ...], store: Store, connection_manager: Any,
        salesforce_url: str, complete: Callable[[str, str], Any], instance_enabled: Callable[[ComplianceBinding], None],
        ensure_run: Callable[[str, ComplianceBinding, str, str], None],
        publish: Callable[[str, str, dict[str, Any]], None],
        set_state: Callable[[str, str, str], None],
        spawn: Callable[[Any], asyncio.Task[Any]],
        headers: Callable[[], dict[str, str]] | None = None,
        teams_channel: str | None = None,
        activity: Callable[..., None] | None = None,
    ) -> None:
        if not bindings or not salesforce_url.startswith("https://"):
            raise ValueError("Compliance bindings and an HTTPS Salesforce MCP URL are required.")
        self._bindings = {(binding.tenant_id, binding.instance_app_id): (binding, name) for binding, name in bindings}
        self._salesforce_url = salesforce_url
        self._instance_enabled = instance_enabled
        self._ensure_run = ensure_run
        self._publish = publish
        self._set_state = set_state
        self._spawn = spawn
        self._headers = headers or (lambda: {})
        self._activity = activity
        self._titles: dict[str, str] = {}
        self._case_bindings: dict[str, ComplianceBinding] = {}
        self._case_refs: dict[str, tuple[str, str]] = {}
        self._names: dict[str, str] = {}
        self._log_tasks: set[asyncio.Task[Any]] = set()
        self.live = LiveComplianceBackend(connection_manager, self._salesforce_call, complete, self._guard,
                                          observer=self._observe,
                                          teams_channel=teams_channel or os.getenv(TEAMS_CHANNEL_ENV, "graph"))
        self.service = ComplianceService(store, _ObservedBackend(self, self.live),
                                         tuple(binding for binding, _ in bindings), event_sink=self._sink)
        self.store = store

    # ── Trusted configuration ────────────────────────────────────────────
    def _guard(self, binding: ComplianceBinding) -> bool:
        configured = self._bindings.get((binding.tenant_id, binding.instance_app_id))
        if configured is None or configured[0] != binding:
            raise PermissionError("The compliance binding is not configured.")
        self._instance_enabled(binding)
        return True

    def binding_for(self, activity: Any) -> tuple[ComplianceBinding, str] | None:
        """Match the SDK recipient to exactly one configured instance and agentic user."""
        recipient = _field(activity, "recipient")
        try:
            app_id = _guid(_field(recipient, "agenticAppId", "agentic_app_id"))
            user_id = _guid(_field(recipient, "agenticUserId", "agentic_user_id"))
        except PermissionError:
            return None
        for binding, name in self._bindings.values():
            if binding.instance_app_id == app_id and binding.agentic_user_id == user_id:
                return binding, name
        return None

    def bindings(self) -> list[tuple[ComplianceBinding, str]]:
        return list(self._bindings.values())

    # ── Control-plane projection ─────────────────────────────────────────
    @staticmethod
    def run_id(case_key: str) -> str:
        return "case-" + case_key[:32]

    def _run_for(self, binding: ComplianceBinding, case_key: str) -> str:
        run_id = self.run_id(case_key)
        name = self._bindings[(binding.tenant_id, binding.instance_app_id)][1]
        self._case_bindings[case_key] = binding
        self._ensure_run(run_id, binding, name, self._titles.get(case_key, f"{name}: compliance case"))
        return run_id

    def _sink(self, kind: str, data: dict[str, Any]) -> None:
        key = data.get("caseKey") or ""
        if not key:
            return
        _CURRENT_CASE.set(key)
        binding = self._bindings.get((data.get("tenantId"), data.get("instanceAppId")))
        if binding is None:
            return
        run_id = self._run_for(binding[0], key)
        number = data.get("caseNumber") or ""
        text = _STEPS.get(kind, kind.replace("_", " ")).format(number=number or "pending")
        status = data.get("status") or ""
        self._publish(run_id, "agent_event", {
            "event": "compliance." + kind, "timestamp": time.time(),
            "attributes": {"caseNumber": number, "status": status, "sequence": data.get("sequence")},
        })
        if status == "closed" and kind in {"case_close_readback", "case_closure_notice_recorded"}:
            self._publish(run_id, "result", {"content": (
                f"Case #{number} closed after the requester's explicit confirmation; Salesforce readback confirms Closed.")})
            self._set_state(run_id, "complete", text)
        elif status == "write_outcome_unknown":
            self._set_state(run_id, "error", text)
        elif status in _WAITING:
            self._set_state(run_id, "waiting", _WAITING[status] if kind != "case_answer_delivered" else text + "; " + _WAITING[status].lower())
        else:
            self._set_state(run_id, "running", text)

    def _tool(self, binding: ComplianceBinding, server: str, tool: str, arguments: dict[str, Any],
              result: Any, succeeded: bool) -> None:
        call_id = f"{server}-{uuid.uuid4().hex[:12]}"
        events = [
            ("tool_call", {"id": call_id, "server": server, "tool": tool, "arguments": arguments}),
            ("tool_result", {"id": call_id, "server": server, "tool": tool,
                             "result": _preview(result) if succeeded else "Failed or outcome unknown."}),
        ]
        key = _CURRENT_CASE.get()
        if not key:
            pending = _PENDING.get()
            if pending is not None and len(pending) < 64:
                pending.extend(events)
            return
        run_id = self._run_for(binding, key)
        for event_type, data in events:
            self._publish(run_id, event_type, data)

    def _observe(self, system: str, operation: str, target: str, succeeded: bool) -> None:
        key = _CURRENT_CASE.get()
        binding = self._case_bindings.get(key) if key else None
        if binding is None and _PENDING.get() is not None:
            binding = next(iter(self._bindings.values()))[0]  # Buffered until the case binding is known.
        if binding is not None:
            self._tool(binding, system, operation, {"target": target}, "OK" if succeeded else "", succeeded)

    # ── Control-room narration and Salesforce activity history ─────────────
    def _narrate(self, binding: ComplianceBinding, category: str, title: str, **details: Any) -> None:
        if self._activity is None:
            return
        key = _CURRENT_CASE.get()
        if key:
            details.setdefault("runId", self.run_id(key))
            details.setdefault("caseKey", key[:32])
        try:
            self._activity(binding, category, title, **details)
        except Exception:
            _logger.debug("compliance narration failed", exc_info=True)

    def _name_of(self, requester_id: str) -> str:
        return self._names.get(requester_id, "the requester")

    def _remember_name(self, activity: Any) -> str:
        sender = _field(activity, "from_property", "from")
        name = _field(sender, "name")
        try:
            requester = _guid(_field(sender, "aad_object_id", "aadObjectId"))
        except PermissionError:
            return name if isinstance(name, str) and name else "the requester"
        if isinstance(name, str) and 0 < len(name) <= 120 and name.isprintable():
            self._names[requester] = name
        return self._name_of(requester)

    def _log_case_task(self, binding: ComplianceBinding, key: str, subject: str, description: str) -> None:
        """Best-effort Activity History entry on the bound case; never delays or alters the case workflow."""
        if not key:
            return
        try:
            task = asyncio.get_running_loop().create_task(self._write_case_task(binding, key, subject, description))
        except RuntimeError:
            return
        self._log_tasks.add(task)
        task.add_done_callback(self._log_tasks.discard)

    async def _case_reference(self, binding: ComplianceBinding, key: str) -> tuple[str, str] | None:
        reference = self._case_refs.get(key)
        if reference is None:
            for case in await self.service.list_cases(binding.tenant_id, binding.manager_id):
                if case.get("key") == key and case.get("caseId") and case.get("caseNumber"):
                    reference = self._case_refs[key] = (case["caseId"], case["caseNumber"])
                    break
        return reference

    async def _write_case_task(self, binding: ComplianceBinding, key: str, subject: str, description: str) -> None:
        try:
            self._guard(binding)
        except PermissionError:
            return  # Isolated or no longer approved: log nothing further on the case.
        try:
            reference = await self._case_reference(binding, key)
            if reference is None:
                return
            case_id, number = reference
            result = await self._salesforce_call(binding, "create_task", {
                "subject": _preview(f"Case #{number}: {subject}", 250), "status": "Completed", "priority": "Normal",
                "due_date": time.strftime("%Y-%m-%d", time.gmtime()), "what_id": case_id,
                "description": _preview(scrub_memory_text(description or ""), 3900),
            })
            structured = _field(result, "structuredContent", "structured_content")
            if _field(result, "isError", "is_error") or type(structured) is not dict or structured.get("created") is not True:
                raise ComplianceBackendError("Salesforce did not confirm the activity entry; it was not retried.")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.warning("compliance.activity log skipped reason=%s", _reason(exc))
            self._narrate(binding, "issue", "Couldn't log an interaction on the Salesforce case",
                          detail=f"{subject}. {_reason(exc)}", status="error")

    # ── Salesforce (single attempt, narrow tool set) ─────────────────────
    async def _salesforce_call(self, binding: ComplianceBinding, tool: str, args: dict) -> Any:
        if tool not in _SALESFORCE_TOOLS:
            raise PermissionError("The Salesforce tool is outside the compliance workflow.")
        transport = StreamableHttpTransport(self._salesforce_url, headers=self._headers(),
                                            httpx_client_factory=_single_attempt_client)
        try:
            async with Client(transport, name="compliance-salesforce", timeout=60, init_timeout=30) as client:
                result = await client.call_tool_mcp(tool, args)
        except BaseException:
            self._tool(binding, "salesforce", tool, args, "", False)
            raise
        structured = _field(result, "structuredContent", "structured_content")
        self._tool(binding, "salesforce", tool, args, structured if structured is not None else "completed",
                   not _field(result, "isError", "is_error"))
        return result

    # ── SDK entry points ─────────────────────────────────────────────────
    async def on_email(self, context: Any) -> None:
        activity = context.activity
        match = self.binding_for(activity)
        if match is None:
            _logger.warning("compliance.email ignored: not addressed to a configured instance")
            return
        binding, name = match
        requester_name = self._remember_name(activity)
        try:
            self._guard(binding)
        except PermissionError as exc:
            _logger.warning("compliance.email declined by host policy")
            self._narrate(binding, "policy", f"Declined an email from {requester_name}: compliance work isn't approved for me",
                          detail=str(exc), status="error", who=requester_name)
            return
        pending: list = []
        pending_token = _PENDING.set(pending)
        try:
            email = await self.live.email_from_activity(binding, activity, MAX_EMAIL_AGE_SECONDS)
        except Exception as exc:
            sender = _field(activity, "from_property", "from")
            _logger.warning("compliance.email rejected reason=%s sender_aad=%s entities=%d", _reason(exc),
                            bool(_field(sender, "aad_object_id", "aadObjectId")), len(_field(activity, "entities") or []))
            self._narrate(binding, "issue", f"Couldn't accept an email from {requester_name}",
                          detail=f"{_reason(exc)} No case was created.", status="error", who=requester_name)
            return  # Handled: a failed SDK turn would only make the platform redeliver it.
        finally:
            _PENDING.reset(pending_token)
        key = _hash(binding.tenant_id, binding.instance_app_id, email.message_id)
        self._titles.setdefault(key, f"{name}: {email.subject[:120]}")
        token = _CURRENT_CASE.set(key)
        try:
            run_id = self._run_for(binding, key)
            self._narrate(binding, "email", f"Received an email from {requester_name}: “{email.subject}”",
                          detail=email.body, status="info", who=requester_name)
            for event_type, data in pending:
                self._publish(run_id, event_type, data)
            self._tool(binding, "graph", "read_authenticated_email", {"subject": email.subject},
                       email.body, True)
        finally:
            _CURRENT_CASE.reset(token)

        async def admit() -> None:
            _CURRENT_CASE.set(key)
            try:
                await self.service.receive_email(binding, email)
            except Exception as exc:
                _logger.warning("compliance.case stopped reason=%s", _reason(exc))
                self._narrate(binding, "issue", "The compliance case stopped", detail=_reason(exc), status="error")

        self._spawn(admit())

    async def start_demo_case(self, instance_app_id: str, requester_id: str, operator_name: str) -> str:
        """Operator-started demo: the signed-in operator is the requester, so no one else is impersonated."""
        requester = _guid(requester_id)
        match = next(((binding, name) for binding, name in self._bindings.values()
                      if binding.instance_app_id == _guid(instance_app_id)), None)
        if match is None:
            raise PermissionError("This colleague isn't configured for compliance cases.")
        binding, name = match
        if requester not in binding.requester_ids:
            raise PermissionError("You aren't a registered requester for this colleague, so no demo case was opened.")
        self._guard(binding)
        if isinstance(operator_name, str) and 0 < len(operator_name) <= 120 and operator_name.isprintable():
            self._names[requester] = operator_name
        requester_name = self._name_of(requester)
        reference = f"demo-{uuid.uuid4().hex}"
        email = VerifiedEmail(message_id=reference, conversation_id=reference, requester_id=requester,
                              subject=DEMO_SUBJECT, body=DEMO_BODY)
        key = _hash(binding.tenant_id, binding.instance_app_id, email.message_id)
        self._titles.setdefault(key, f"{name}: {email.subject[:120]}")
        token = _CURRENT_CASE.set(key)
        try:
            self._run_for(binding, key)
            self._narrate(binding, "skill", f"Started a demo compliance case for {requester_name}",
                          detail=("Launched from the control plane. It follows the same path as an emailed request: "
                                  f"a Salesforce case, evidence checks and a private Teams chat.\n\n{email.subject}"),
                          status="info", who=requester_name)
        finally:
            _CURRENT_CASE.reset(token)

        async def admit() -> None:
            _CURRENT_CASE.set(key)
            try:
                await self.service.receive_email(binding, email)
            except Exception as exc:
                _logger.warning("compliance.demo stopped reason=%s", _reason(exc))
                self._narrate(binding, "issue", "The demo compliance case stopped", detail=_reason(exc), status="error")

        self._spawn(admit())
        return key

    async def _open_case_chat(self, binding: ComplianceBinding, requester: str, chat_id: str) -> str | None:
        """The requester's most recently contacted open case in this chat; closed cases hand back to chat."""
        cases = [case for case in await self.service.list_cases(binding.tenant_id, binding.manager_id)
                 if case["authority"]["instanceAppId"] == binding.instance_app_id
                 and case["authority"]["requesterId"] == requester and case["privateChatId"] == chat_id
                 and case.get("salesforceStatus") != "Closed" and case.get("status") != "closed"]
        if not cases:
            return None
        return max(cases, key=lambda case: (case.get("lastDelivery") or {}).get("at") or case.get("createdAt") or 0)["key"]

    async def try_reply(self, context: Any) -> bool:
        """Consume a requester's private-chat message for an existing case; False means normal chat."""
        activity = context.activity
        match = self.binding_for(activity)
        if match is None:
            return False
        binding, _name = match
        sender = _field(activity, "from_property", "from")
        conversation = _field(activity, "conversation")
        kind = _field(conversation, "conversation_type", "conversationType")
        try:
            requester = _guid(_field(sender, "aad_object_id", "aadObjectId"))
        except PermissionError:
            return False
        chat_id, activity_id = _field(conversation, "id"), _field(activity, "id")
        if (getattr(kind, "value", kind) != "personal" or requester not in binding.requester_ids
                or type(chat_id) is not str or type(activity_id) is not str):
            return False
        key = await self._open_case_chat(binding, requester, chat_id)
        if key is None:
            _logger.info("compliance.reply not a case chat teams_thread=%s", chat_id.startswith("19:"))
            return False
        requester_name = self._remember_name(activity)

        async def continue_case() -> None:
            _CURRENT_CASE.set(key)
            try:
                text = await self.live.verify_reply(binding, requester, chat_id, activity_id, MAX_REPLY_AGE_SECONDS)
                self._tool(binding, "teams", "message_from_requester", {"chat": "private"}, text, True)
                self._narrate(binding, "teams-in", f"{requester_name} replied in our private chat", detail=text,
                              status="info", who=requester_name)
                self._log_case_task(binding, key, "Teams reply from the requester", text)
                await self.service.handle_reply(binding, requester, chat_id, activity_id, text.strip())
            except Exception as exc:
                _logger.warning("compliance.reply stopped reason=%s", _reason(exc))
                self._narrate(binding, "issue", f"Couldn't continue the case from {requester_name}'s reply",
                              detail=_reason(exc), status="error", who=requester_name)

        self._spawn(continue_case())
        return True

    async def list_cases(self) -> list[dict[str, Any]]:
        cases: list[dict[str, Any]] = []
        managers = {(binding.tenant_id, binding.manager_id) for binding, _ in self._bindings.values()}
        for tenant_id, manager_id in sorted(managers):
            cases.extend(await self.service.list_cases(tenant_id, manager_id))
        return cases

    async def close(self) -> None:
        pending = tuple(self._log_tasks)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        try:
            await self.service.close()
        finally:
            await self.store.close()
