"""Durable, narrowly scoped compliance coordination; no live adapters or host.

Host contract
-------------
Construct bindings from VERIFIED directory relationships, not notification fields
or model output. Authenticate notifications/Teams activities, resolve the real
sender, verify the addressed instance, and enforce notification freshness BEFORE
calling this service. ``VerifiedEmail.message_id`` must be the immutable mailbox
message ID, not a notification/subscription ID. The host MUST reject email and
activity replays older than ``idempotency_window_seconds`` using authoritative
timestamps. Store inactivity TTL still applies: this is NOT infinite deduplication.
Use the email's original received time, not a fresh notification delivery time.
Keep the retention configuration stable across workers/restarts.

The injected backend independently enforces identity, governance, evidence access,
DLP and private-chat membership on EVERY call. Investigation is read-only and its
``resolution_ready`` must represent verified evidence/control checks, not merely
a model's opinion. No generic approval gate, identity fallback, or SDK is imported.
Adapters must make single attempts, propagate ambiguous outcomes as exceptions,
and must not launch detached writes. ``send_private`` accepts plain text; adapters
must escape any HTML/mentions and return the actual delivery message ID. A receipt
certifies delivery of the supplied answer: partial/policy-filtered sends must raise.

Persistence and recovery
------------------------
One CAS document per tenant/instance contains the manager-pinned index AND cases,
avoiding an index/case dual-write gap. Changing a retained directory binding fails
closed; migration/reconciliation is an explicit host/operator responsibility.
Case keys are SHA-256 of compact JSON [tenant, instance, immutable message ID].
All 100 admitted cases (including closed/uncertain ones) remain until Store TTL;
admission fails instead of evicting. Activity/write receipts are not timeline
entries and are never pruned to make room. Additional turn/receipt/size bounds
stop automatic progress. Timelines retain their latest 50 entries; total stored
JSON is limited to 1 MiB, even with a more permissive Store.

A durable, unique owner serializes progress. Every external write has a separate
claim nonce BEFORE invocation and a completion receipt committed BEFORE business
state/events. Claims are never leased, stolen, or retried. A lost process may
leave a claim or owner forever until retention expiry; reconcile, don't replay.
Storage errors and cancellation can follow a commit. Every CAS is shielded AND
drained before cancellation cleanup, which performs storage work only.

``handle_reply`` returns True for a recognized, scoped case, including duplicates
and rejected/blocked resolution commands; False means unauthorized/unroutable.
A plain reply continues the requester's most recently contacted open case in that
chat; ``case #NUMBER: ...`` picks another. A case closes on the exact command
``resolve NUMBER`` or, when the backend offers ``interpret_reply``, on a confirmed
answer, and only while ``_can_resolve`` holds; thanks and small talk never close.
The recorded confirmation time is server receipt time (UTC epoch), not an inferred
source timestamp. A command received before answer delivery is consumed but denied.
New material invalidates earlier authority atomically and queues behind an owner.
Closure linearizes at its write claim: material arriving afterwards cannot undo an
already attempted Salesforce write, so it requires visible specialist follow-up.

Backend/storage exceptions propagate after best-effort unknown-state persistence;
read the case index for the durable outcome. Scrubbing is heuristic, not a DLP
classifier. Only compact text and allowlisted versioned evidence references are
retained, never evidence document bodies. The optional synchronous event sink is
``event_sink(kind, data)``; it receives scoped metadata AFTER durable timeline
updates and is best effort, not an exactly-once event bus.

``close`` cancels/drains this service's active calls/CAS tasks, never starts or
replays external work, and does NOT close the borrowed Store/backend. The host
owns those resources and authentication for ``list_cases`` manager queries.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from .conversation_memory import (
    ChatScope,
    CorruptStateError,
    StateTooLargeError,
    Store,
    scrub_memory_text,
)

__all__ = [
    "ComplianceBinding", "VerifiedEmail", "Investigation", "ComplianceBackend",
    "ComplianceService",
]

MAX_CASES = 100
MAX_TIMELINE_EVENTS = 50
MAX_STATE_BYTES = 1024 * 1024
MAX_TURNS = 32
MAX_ACTIVITY_RECEIPTS = 128
MAX_PENDING_REPLIES = 8
MAX_INVESTIGATION_HISTORY = 4
MAX_EVIDENCE = 16
MAX_INPUT_CHARS = 65_536
_TASK = "compliance"
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_NONCE = re.compile(r"[0-9a-f]{32}")
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_RESOLVE = re.compile(r"(?i:resolve) ([A-Za-z0-9][A-Za-z0-9_-]{0,63})", re.ASCII)
_MARKER = re.compile(r"(?i:case) #([A-Za-z0-9][A-Za-z0-9_-]{0,63})(?:: ?| |$)")
_CASE_MENTION = re.compile(r"\bcase #([A-Za-z0-9][A-Za-z0-9_-]{0,63})", re.IGNORECASE | re.ASCII)
_WRITE = re.compile(r"create|chat|close|closed_delivery|(?:update|delivery):[0-9]{1,2}")
_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_STATUSES = frozenset({
    "received", "creating", "investigating", "opening_private_chat", "updating_case",
    "delivering_answer", "waiting_for_requester", "awaiting_confirmation", "closing",
    "verifying_close", "closed", "notifying_closure", "needs_specialist_review",
    "write_outcome_unknown",
})
_PENDING_STATUS = {
    "create": "creating", "chat": "opening_private_chat", "close": "closing",
    "closed_delivery": "notifying_closure", "update": "updating_case",
    "delivery": "delivering_answer",
}
_INTENTS = frozenset({"information", "confirm_with_email", "confirm_without_email", "chat"})
_CONFIRM = frozenset({"confirm_with_email", "confirm_without_email"})


def _guid(value: Any) -> str:
    if type(value) is not str or _GUID.fullmatch(value) is None:
        raise ValueError("Verified nonzero directory GUIDs are required.")
    parsed = uuid.UUID(value)
    if not parsed.int:
        raise ValueError("Verified nonzero directory GUIDs are required.")
    return str(parsed)


def _opaque(value: Any, limit: int = 512) -> str:
    if (type(value) is not str or not 0 < len(value) <= limit
            or not value.strip() or not value.isprintable()
            or scrub_memory_text(value) != value):
        raise ValueError("A bounded, credential-free opaque reference is required.")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError("References must contain valid Unicode.") from None
    return value


def _plain(value: Any) -> str:
    if type(value) is not str or len(value) > MAX_INPUT_CHARS:
        raise ValueError("Text must be a bounded plain string.")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise ValueError("Text must contain valid Unicode.") from None
    return value


def _safe_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            return "[unsafe link]"
        # Remove credentials, signed query strings and fragments, including SAS.
        host = parts.netloc.rsplit("@", 1)[-1]
        return urlunsplit((parts.scheme.lower(), host, parts.path, "", ""))
    except ValueError:
        return "[unsafe link]"


def _compact(value: Any, limit: int) -> str:
    text = _CONTROL.sub("", _plain(value))
    text = _URL.sub(lambda match: _safe_url(match.group()), text)
    return scrub_memory_text(text)[:limit]


def _hash(*parts: str) -> str:
    raw = json.dumps(parts, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class ComplianceBinding:
    tenant_id: str
    blueprint_id: str
    instance_app_id: str
    agentic_user_id: str
    manager_id: str
    requester_ids: tuple[str, ...]
    evidence_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("tenant_id", "blueprint_id", "instance_app_id", "agentic_user_id", "manager_id"):
            object.__setattr__(self, name, _guid(getattr(self, name)))
        if type(self.requester_ids) is not tuple or not 0 < len(self.requester_ids) <= 100:
            raise ValueError("A nonempty bounded tuple of verified requesters is required.")
        users = tuple(_guid(value) for value in self.requester_ids)
        if len(set(users)) != len(users):
            raise ValueError("Requester directory IDs must be unique.")
        object.__setattr__(self, "requester_ids", users)
        if type(self.evidence_paths) is not tuple or len(self.evidence_paths) > 32:
            raise ValueError("Evidence paths must be a bounded tuple.")
        for path in self.evidence_paths:
            if _compact(_opaque(path), 512) != path:
                raise ValueError("Evidence paths must not contain credentials or signed URLs.")


@dataclass(frozen=True)
class VerifiedEmail:
    message_id: str
    conversation_id: str
    requester_id: str
    subject: str
    body: str

    def __post_init__(self) -> None:
        _opaque(self.message_id)
        _opaque(self.conversation_id)
        object.__setattr__(self, "requester_id", _guid(self.requester_id))
        _plain(self.subject)
        _plain(self.body)


@dataclass(frozen=True)
class Investigation:
    """Backend-verified findings, not model-supplied permission.

    Evidence entries require nonblank string ``id`` and ``version``. Optional
    ``source``, ``title``, ``url`` and ``date`` are compacted; all other keys are
    discarded. Superseded findings remain context only, never closure authority.
    """

    answer: str
    evidence: list[dict]
    questions: list[str]
    blockers: list[str]
    resolution_ready: bool = False


class ComplianceBackend(Protocol):
    """Trusted, single-attempt adapters; authorization remains their responsibility.

    Optional: ``interpret_reply`` (routes a reply), ``notify`` (courtesy chat message)
    and ``send_confirmation_email``; all are best effort and never closure authority.
    """

    async def create_case(
        self, binding: ComplianceBinding, email: VerifiedEmail, correlation: str,
    ) -> dict: ...

    async def ensure_private_chat(self, binding: ComplianceBinding, requester_id: str) -> str: ...

    async def investigate(
        self, binding: ComplianceBinding, record: dict, latest_reply: str,
    ) -> Investigation: ...

    async def send_private(
        self, binding: ComplianceBinding, requester_id: str, chat_id: str, text: str,
    ) -> str: ...

    async def update_case(
        self, binding: ComplianceBinding, case_id: str, comment: str, close: bool = False,
    ) -> None: ...

    async def read_case_status(self, binding: ComplianceBinding, case_id: str) -> str: ...


def _authority(binding: ComplianceBinding, requester: str) -> dict:
    return {
        "tenantId": binding.tenant_id, "blueprintId": binding.blueprint_id,
        "instanceAppId": binding.instance_app_id, "agenticUserId": binding.agentic_user_id,
        "managerId": binding.manager_id, "requesterId": requester,
    }


def _binding_data(binding: ComplianceBinding) -> dict:
    data = _authority(binding, "")
    del data["requesterId"]
    return {**data, "requesterIds": list(binding.requester_ids), "evidencePaths": list(binding.evidence_paths)}


def _investigation(value: Investigation, generation: int, input_complete: bool) -> dict:
    """Only id/version plus optional source/title/url/date survive evidence projection."""
    if type(value) is not Investigation or type(value.resolution_ready) is not bool:
        raise ValueError("The investigator must return the typed evidence contract.")
    if any(type(items) is not list for items in (value.evidence, value.questions, value.blockers)):
        raise ValueError("Investigation collections must be plain lists.")
    if len(value.evidence) > 256 or len(value.questions) > 64 or len(value.blockers) > 64:
        raise ValueError("The investigation exceeds its input bounds.")
    answer = _compact(value.answer, 3000)
    questions = [_compact(item, 400) for item in value.questions[:4] if _plain(item).strip()]
    blockers = [_compact(item, 300) for item in value.blockers[:8] if _plain(item).strip()]
    incomplete = (
        answer != value.answer or not input_complete or len(value.evidence) > MAX_EVIDENCE
        or len(value.questions) > 4 or len(value.blockers) > 8
        or any(_compact(item, 400) != item for item in value.questions[:4])
        or any(_compact(item, 300) != item for item in value.blockers[:8])
    )
    evidence: list[dict] = []
    versions: dict[str, str] = {}
    for item in value.evidence[:MAX_EVIDENCE]:
        if type(item) is not dict:
            incomplete = True
            continue
        try:
            reference = {"id": _opaque(item.get("id"), 160), "version": _opaque(item.get("version"), 80)}
            if any(_compact(part, 512) != part for part in reference.values()):
                raise ValueError("Unsafe evidence reference.")
        except ValueError:
            incomplete = True
            continue
        previous = versions.get(reference["id"])
        if previous is not None:
            if previous != reference["version"]:
                incomplete = True
            continue
        versions[reference["id"]] = reference["version"]
        for name, limit in (("source", 80), ("title", 160), ("url", 512), ("date", 64)):
            if name in item and type(item[name]) is str:
                projected = _compact(item[name], limit)
                if name == "url":
                    projected = _safe_url(projected)
                    if projected == "[unsafe link]":
                        continue
                reference[name] = projected
        evidence.append(reference)
    if incomplete:
        blockers.append("Input or evidence was incomplete, conflicting, shortened or redacted; verified review is required.")
    if not evidence:
        blockers.append("No verified versioned evidence is available.")
    if not answer.strip():
        blockers.append("A complete grounded answer is not available.")
    return {
        "generation": generation, "answer": answer, "evidence": evidence,
        "questions": questions, "blockers": blockers,
        "resolutionReady": value.resolution_ready and bool(evidence) and bool(answer.strip())
        and not questions and not blockers,
    }


async def _drain(task: asyncio.Task[Any]) -> bool:
    """Retrieve completion/errors even through repeated cancellation of the caller."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except BaseException:
            break
    try:
        task.result()
    except BaseException:
        pass
    return cancelled


class _OwnershipLost(RuntimeError):
    pass


class ComplianceService:
    def __init__(
        self, store: Store, backend: ComplianceBackend, bindings: tuple[ComplianceBinding, ...],
        event_sink: Callable[[str, dict], None] | None = None,
    ) -> None:
        if not isinstance(store, Store) or type(bindings) is not tuple or len(bindings) > 100:
            raise ValueError("A Store and bounded tuple of verified bindings are required.")
        if event_sink is not None and (
            not callable(event_sink) or inspect.iscoroutinefunction(event_sink)
            or inspect.iscoroutinefunction(getattr(event_sink, "__call__", None))
        ):
            raise ValueError("The event sink must be synchronous.")
        self.store = store
        self.backend = backend
        self.idempotency_window_seconds = store.ttl_seconds
        self._bindings: dict[tuple[str, str], ComplianceBinding] = {}
        for binding in bindings:
            if type(binding) is not ComplianceBinding:
                raise ValueError("Only verified ComplianceBinding objects are accepted.")
            key = (binding.tenant_id, binding.instance_app_id)
            if key in self._bindings:
                raise ValueError("Each tenant/instance may have only one directory binding.")
            self._bindings[key] = binding
        self._sink = event_sink
        self._closed = False
        self._active: dict[asyncio.Task[Any], int] = {}
        self._storage: set[asyncio.Task[Any]] = set()

    @staticmethod
    def _scope(binding: ComplianceBinding) -> ChatScope:
        # Pin the manager INSIDE this stable instance scope. A manager change must
        # not create a second index capable of replaying an old immutable email.
        return ChatScope(binding.tenant_id, binding.instance_app_id, "compliance-service:v1")

    def _binding(self, supplied: ComplianceBinding) -> ComplianceBinding:
        if type(supplied) is not ComplianceBinding:
            raise PermissionError("The verified directory binding is not configured.")
        binding = self._bindings.get((supplied.tenant_id, supplied.instance_app_id))
        if binding != supplied:
            raise PermissionError("The verified directory binding is not configured.")
        return binding

    def _enter(self) -> asyncio.Task[Any]:
        if self._closed:
            raise RuntimeError("The compliance service is closed.")
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("An async caller is required.")
        self._active[task] = self._active.get(task, 0) + 1
        return task

    def _leave(self, task: asyncio.Task[Any]) -> None:
        depth = self._active[task] - 1
        if depth:
            self._active[task] = depth
        else:
            del self._active[task]

    def _running(self) -> None:
        task = asyncio.current_task()
        if self._closed or (task is not None and task.cancelling()):
            raise asyncio.CancelledError

    def _bounds(self, state: dict) -> None:
        raw = json.dumps(state, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        # Reserve a little space for Store's own updatedAt serialization.
        if len(raw) > min(MAX_STATE_BYTES, self.store.max_uncompressed_bytes) - 512:
            raise StateTooLargeError("The compliance index reached its bounded JSON capacity.")

    def _index(self, state: dict, binding: ComplianceBinding) -> dict | None:
        self._bounds(state)
        index = state["tasks"].get(_TASK)
        if index is None:
            if state["tasks"]:
                raise CorruptStateError("Unsupported compliance index.")
            return None
        if (type(index) is not dict or set(index) != {"version", "binding", "cases"}
                or type(index["version"]) is not int or index["version"] != 1):
            raise CorruptStateError("Unsupported compliance index.")
        if index["binding"] != _binding_data(binding):
            raise PermissionError("The retained index has a different directory/manager binding.")
        cases = index["cases"]
        if type(cases) is not dict or len(cases) > MAX_CASES:
            raise CorruptStateError("Invalid compliance case index.")
        try:
            for key, record in cases.items():
                if type(record) is not dict or type(key) is not str or _DIGEST.fullmatch(key) is None:
                    raise ValueError
                requester = record["authority"]["requesterId"]
                if (requester not in binding.requester_ids or record["authority"] != _authority(binding, requester)
                        or record["key"] != key
                        or key != _hash(binding.tenant_id, binding.instance_app_id, _opaque(record["email"]["messageId"]))):
                    raise ValueError
                _opaque(record["email"]["conversationId"])
                if (record["status"] not in _STATUSES or type(record["suspended"]) is not bool
                    or type(record["inputComplete"]) is not bool
                        or type(record["generation"]) is not int or not 0 <= record["generation"] < MAX_TURNS
                        or (record["owner"] is not None and _NONCE.fullmatch(record["owner"]) is None)):
                    raise ValueError
                activities, pending, timeline, writes = (
                    record["activities"], record["pendingReplies"], record["timeline"], record["writes"],
                )
                if (type(activities) is not list or len(activities) > MAX_ACTIVITY_RECEIPTS
                        or len(set(activities)) != len(activities)
                        or any(type(item) is not str or _DIGEST.fullmatch(item) is None for item in activities)
                        or type(pending) is not list or len(pending) > MAX_PENDING_REPLIES
                        or type(timeline) is not list or len(timeline) > MAX_TIMELINE_EVENTS
                        or type(writes) is not dict or len(writes) > 2 * MAX_TURNS + 4
                        or type(record["replyHistory"]) is not list or len(record["replyHistory"]) >= MAX_TURNS
                        or type(record["investigationHistory"]) is not list
                        or len(record["investigationHistory"]) > MAX_INVESTIGATION_HISTORY):
                    raise ValueError
                for name, write in writes.items():
                    if (type(name) is not str or _WRITE.fullmatch(name) is None or type(write) is not dict
                            or _NONCE.fullmatch(write["nonce"]) is None
                            or _NONCE.fullmatch(write["owner"]) is None
                            or write["status"] not in {"claimed", "completed", "unknown"}
                            or (write["status"] == "completed" and type(write["receipt"]) is not dict)):
                        raise ValueError
                    if ":" in name and int(name.split(":", 1)[1]) > record["generation"]:
                        raise ValueError
                self._validate_targets(record)
        except (KeyError, TypeError, ValueError):
            raise CorruptStateError("Invalid or mismatched compliance case state.") from None
        return index

    @staticmethod
    def _validate_targets(record: dict) -> None:
        """Resource selectors must agree with their durable backend receipts.

        This detects inconsistent state, not a malicious writer able to forge
        both metadata and receipts. Store access and backend auth remain required.
        """
        writes = record["writes"]
        case_id, number, chat_id = record["caseId"], record["caseNumber"], record["privateChatId"]
        if any(type(value) is not str for value in (case_id, number, chat_id)) or bool(case_id) != bool(number):
            raise ValueError
        if case_id:
            created = writes.get("create", {})
            if (created.get("status") != "completed" or created.get("receipt") != {"id": case_id, "number": number}
                    or _REFERENCE.fullmatch(case_id) is None or _REFERENCE.fullmatch(number) is None):
                raise ValueError
        elif any(name != "create" for name in writes):
            raise ValueError
        if chat_id:
            chat = writes.get("chat", {})
            if chat.get("status") != "completed" or chat.get("receipt") != {"chatId": _opaque(chat_id)}:
                raise ValueError
        elif any(name.startswith("delivery:") or name in {"close", "closed_delivery"} for name in writes):
            raise ValueError
        if record["salesforceStatus"] not in {"", "Closed"}:
            raise ValueError
        if record["status"] == "closed" and record["salesforceStatus"] != "Closed":
            raise ValueError
        if record["salesforceStatus"] == "Closed":
            close, readback = writes.get("close", {}), record["closureReadback"]
            if (close.get("status") != "completed" or type(readback) is not dict
                    or readback.get("status") != "Closed"):
                raise ValueError

    async def _persist(self, scope: ChatScope, transform: Callable[[dict], None]) -> dict:
        write = asyncio.create_task(self.store.update(scope, transform))
        self._storage.add(write)
        try:
            return await asyncio.shield(write)
        except asyncio.CancelledError:
            await _drain(write)
            raise
        finally:
            self._storage.discard(write)

    def _event(self, record: dict, kind: str, at: float, events: list, text: str = "") -> None:
        record["sequence"] += 1
        event = {"sequence": record["sequence"], "kind": kind, "at": at, "status": record["status"]}
        if text:
            event["text"] = _compact(text, 240)
        record["timeline"] = (record["timeline"] + [event])[-MAX_TIMELINE_EVENTS:]
        record["updatedAt"] = at
        events.append((kind, {
            **record["authority"], "caseKey": record["key"], "caseNumber": record["caseNumber"],
            "sequence": event["sequence"], "at": at, "status": record["status"],
        }))

    async def _change(
        self, binding: ComplianceBinding, transform: Callable[[dict, list], None], *, create: bool = False,
    ) -> dict:
        events: list[tuple[str, dict]] = []

        def change(state: dict) -> None:
            events.clear()  # A losing CAS candidate must not emit or retain ownership.
            index = self._index(state, binding)
            if index is None:
                if not create:
                    raise _OwnershipLost("The retained case index is unavailable.")
                index = {"version": 1, "binding": _binding_data(binding), "cases": {}}
                state["tasks"][_TASK] = index
            transform(index, events)
            self._bounds(state)

        state = await self._persist(self._scope(binding), change)
        if self._sink is not None:
            for kind, data in events:
                try:
                    result = self._sink(kind, copy.deepcopy(data))
                    if inspect.iscoroutine(result):
                        result.close()  # Never turn a misconfigured sink into detached work.
                except Exception:
                    pass  # Durable receipts/state, not a notification, control progress.
        return state["tasks"][_TASK]

    async def _edit(
        self, binding: ComplianceBinding, key: str, owner: str,
        transform: Callable[[dict], bool], event: str = "",
    ) -> dict:
        at = self.store._now()

        def edit(index: dict, events: list) -> None:
            record = index["cases"].get(key)
            if record is None or record["owner"] != owner:
                raise _OwnershipLost("Case ownership is unavailable; no effect may be retried.")
            if transform(record):
                record["updatedAt"] = at
                if event:
                    self._event(record, event, at, events)

        return (await self._change(binding, edit))["cases"][key]

    async def _record(self, binding: ComplianceBinding, key: str) -> dict:
        index = self._index(await self.store.read(self._scope(binding)), binding)
        if index is None or key not in index["cases"]:
            raise _OwnershipLost("The retained case is unavailable.")
        return index["cases"][key]

    @staticmethod
    def _view(record: dict) -> dict:
        result = copy.deepcopy(record)
        uncertain = any(write["status"] in {"claimed", "unknown"} for write in record["writes"].values())
        result["inFlightOrInterrupted"] = record["owner"] is not None
        result["reconciliationRequired"] = uncertain or record["status"] == "write_outcome_unknown"
        if uncertain:
            result["pendingStatus"] = result["status"]
            result["status"] = "write_outcome_unknown"
        return result

    async def _abort(self, binding: ComplianceBinding, key: str, owner: str) -> None:
        def unknown(record: dict) -> bool:
            for write in record["writes"].values():
                if write["status"] == "claimed" and write["owner"] == owner:
                    write["status"] = "unknown"
            record.update(status="write_outcome_unknown", suspended=True, resolution=None,
                          lastOutcome="Operation interrupted; reconcile receipts before any further action.")
            return True

        try:
            await self._edit(binding, key, owner, unknown, "case_outcome_unknown")
        except (Exception, asyncio.CancelledError):
            # _persist has drained even if cancellation recurs. The original
            # durable owner/claim still blocks replay if this marker cannot save.
            pass

    async def _write(
        self, binding: ComplianceBinding, key: str, owner: str, name: str,
        invoke: Callable[[], Awaitable[Any]], receipt: Callable[[Any], dict],
        generation: int | None = None,
    ) -> dict | None:
        nonce, at = uuid.uuid4().hex, self.store._now()

        def claim(record: dict) -> bool:
            if record["suspended"] or (generation is not None and record["generation"] != generation):
                return False
            if name in record["writes"] or any(
                item["status"] != "completed" for item in record["writes"].values()
            ):
                raise _OwnershipLost("A retained write claim must never be replayed.")
            record["writes"][name] = {
                "nonce": nonce, "owner": owner, "status": "claimed", "at": at, "receipt": None,
            }
            record["status"] = _PENDING_STATUS[name.split(":", 1)[0]]
            return True

        record = await self._edit(binding, key, owner, claim)
        if record["writes"].get(name, {}).get("nonce") != nonce:
            return None
        self._running()
        proof = receipt(await invoke())
        completed_at = self.store._now()

        def complete(current: dict) -> bool:
            write = current["writes"].get(name)
            if (not write or write["owner"] != owner or write["nonce"] != nonce
                    or write["status"] != "claimed"):
                raise _OwnershipLost("The external write receipt lost its unique claim.")
            write.update(status="completed", receipt=copy.deepcopy(proof), completedAt=completed_at)
            return True

        # This CAS deliberately does NOT advance the workflow or emit an event.
        await self._edit(binding, key, owner, complete)
        return proof

    @staticmethod
    def _created(value: Any) -> dict:
        if (type(value) is not dict or type(value.get("id")) is not str
                or type(value.get("number")) is not str
                or _REFERENCE.fullmatch(value["id"]) is None
                or _REFERENCE.fullmatch(value["number"]) is None):
            raise ValueError("Salesforce did not return a verified case reference.")
        return {"id": value["id"], "number": value["number"]}

    @staticmethod
    def _ack(value: Any) -> dict:
        if value is not None:
            raise ValueError("Case updates must return None on success or raise.")
        return {"acknowledged": True}

    async def receive_email(self, binding: ComplianceBinding, email: VerifiedEmail) -> dict:
        task = self._enter()
        key, owner = "", uuid.uuid4().hex
        try:
            binding = self._binding(binding)
            if type(email) is not VerifiedEmail or email.requester_id not in binding.requester_ids:
                raise PermissionError("The authenticated requester is not bound to this instance.")
            key = _hash(binding.tenant_id, binding.instance_app_id, email.message_id)
            at = self.store._now()
            subject, body = _compact(email.subject, 256), _compact(email.body, 2000)

            def admit(index: dict, events: list) -> None:
                existing = index["cases"].get(key)
                if existing is not None:
                    if (existing["authority"] != _authority(binding, email.requester_id)
                            or existing["email"]["conversationId"] != email.conversation_id):
                        raise PermissionError("The immutable email is bound to a different sender/conversation.")
                    return
                if len(index["cases"]) >= MAX_CASES:
                    raise RuntimeError("Compliance case capacity reached; no retained cases were evicted.")
                record = {
                    "key": key, "authority": _authority(binding, email.requester_id),
                    "email": {"messageId": email.message_id, "conversationId": email.conversation_id,
                              "subject": subject, "body": body},
                    "createdAt": at, "updatedAt": at, "status": "received", "owner": owner,
                    "caseId": "", "caseNumber": "", "privateChatId": "", "generation": 0,
                    "inputComplete": subject == email.subject and body == email.body,
                    "suspended": False, "activities": [], "writes": {}, "sequence": 0, "timeline": [],
                    "pendingReplies": [{"generation": 0, "text": "", "at": at, "activityKey": ""}],
                    "replyHistory": [], "investigationHistory": [],
                    "work": None, "latestReply": None, "investigation": None, "resolution": None,
                    "confirmation": None, "lastDelivery": None, "closureReadback": None,
                    "salesforceStatus": "", "lastOutcome": "Email admitted.",
                }
                index["cases"][key] = record
                self._event(record, "case_received", at, events)

            record = (await self._change(binding, admit, create=True))["cases"][key]
            if record["owner"] == owner:
                await self._drive(binding, key, owner, email)
                record = await self._record(binding, key)
            return self._view(record)
        except BaseException:
            if key:
                await self._abort(binding, key, owner)
            raise
        finally:
            self._leave(task)

    async def _register(self, binding: ComplianceBinding, key: str, owner: str, email: VerifiedEmail) -> None:
        proof = await self._write(binding, key, owner, "create",
                                  lambda: self.backend.create_case(binding, email, key), self._created)
        if proof is None:
            raise _OwnershipLost("Case registration was interrupted before its claim.")
        at = self.store._now()

        def registered(index: dict, events: list) -> None:
            record = index["cases"][key]
            if record["owner"] != owner or record["writes"]["create"]["receipt"] != proof:
                raise _OwnershipLost("Case registration receipt is unavailable.")
            collision = any(
                other_key != key and (other["caseId"] == proof["id"] or other["caseNumber"] == proof["number"])
                for other_key, other in index["cases"].items()
            )
            record.update(caseId=proof["id"], caseNumber=proof["number"],
                          status="write_outcome_unknown" if collision else "investigating", suspended=collision)
            self._event(record, "case_reference_collision" if collision else "case_registered", at, events)

        record = (await self._change(binding, registered))["cases"][key]
        if record["suspended"]:
            raise RuntimeError("Salesforce returned a conflicting case reference; reconciliation is required.")

    async def _take_work(self, binding: ComplianceBinding, key: str, owner: str) -> dict:
        def take(record: dict) -> bool:
            if record["suspended"] or record["salesforceStatus"] == "Closed" or not record["pendingReplies"]:
                record.update(owner=None, work=None)
            else:
                work = record["pendingReplies"].pop(0)
                record.update(work=work, latestReply=work if work["text"] else None,
                              status="investigating", resolution=None)
            return True

        return await self._edit(binding, key, owner, take)

    @staticmethod
    def _comment(record: dict, *, close: bool = False) -> str:
        """A readable Salesforce case note; the durable machine record stays in the case store."""
        result = record["investigation"] or {}
        parts: list[str] = []
        if close:
            confirmation = record["confirmation"]
            when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(confirmation["at"]))
            email = "requested" if confirmation.get("email") else "not requested"
            parts.append(f"Resolved. The original requester confirmed in the private Teams chat "
                         f"(\"{confirmation['text']}\", {when}). Confirmation email: {email}.\n"
                         "This records that the compliance question is resolved; it is not approval to transfer documents.")
        else:
            parts.append(f"Investigation update (round {record['generation']}).")
        latest = record["latestReply"]
        if type(latest) is dict and latest.get("text"):
            parts.append(f"Latest requester message: {latest['text']}")
        if result.get("answer"):
            parts.append(f"Answer: {result['answer']}")
        for heading, name in (("Questions for the requester", "questions"), ("Unresolved", "blockers")):
            if result.get(name):
                parts.append(heading + ":\n" + "\n".join(f"- {item}" for item in result[name]))
        if result.get("evidence"):
            parts.append("Evidence:\n" + "\n".join(
                f"- {item['id']} (version {item['version']})" + (f": {item['title']}" if item.get("title") else "")
                for item in result["evidence"]))
        parts.append(f"Requester {record['authority']['requesterId']} | Autopilot reference {record['key'][:12]}")
        text = "\n\n".join(parts)
        # Salesforce CaseComment bodies hold at most 4,000 characters.
        return text if len(text) <= 3900 else text[:3880] + "\n[shortened]"

    @staticmethod
    def _message(record: dict) -> str:
        result, number = record["investigation"], record["caseNumber"]
        subject = record["email"]["subject"]
        parts = [f"Case #{number} · {subject}" if subject else f"Case #{number}"]
        answer = result["answer"].strip()
        if result["resolutionReady"]:
            parts += [answer, "Does this answer your question? If it does, would you like me to email you a "
                              "confirmation of the outcome before I close the case?"]
        elif result["questions"]:
            first = record["generation"] == 0
            opening = ("Thanks for your email. I've opened this case and I'm checking it against our records."
                       if first else "Thanks, that helps.")
            parts.append(f"{opening} {answer}" if answer else opening)
            ask = ("To make sure I give you the right answer, could you tell me:" if first
                   else "One more thing before I can answer:" if len(result["questions"]) == 1
                   else "A couple more things before I can answer:")
            parts.append(ask + "\n" + "\n".join(
                f"{index}. {item}" for index, item in enumerate(result["questions"], 1)))
        else:
            reasons = "\n".join(f"- {item}" for item in result["blockers"]) or "- The records don't support a definitive answer yet."
            parts += [answer, "I can't give you a definitive answer yet:\n" + reasons,
                      "I've kept the case open and flagged it for a compliance specialist, who will follow up with you."]
        text = "\n\n".join(part for part in parts if part)
        if len(text) > 8000:
            # A ready answer with the specified evidence/text bounds fits in 8K.
            if result["resolutionReady"]:
                raise StateTooLargeError("A complete resolution answer does not fit the delivery bound.")
            text = text[:7800] + "\n[Shortened; the full details are on the case.]"
        return text

    @staticmethod
    def _summary(record: dict) -> str:
        """The resolved outcome in plain text, for the requester's confirmation email."""
        result, confirmation = record["investigation"] or {}, record["confirmation"] or {}
        when = time.strftime("%d %b %Y %H:%M UTC", time.gmtime(confirmation.get("at") or 0))
        return "\n\n".join([
            f"Case #{record['caseNumber']}: {record['email']['subject']}",
            "Outcome:\n" + (result.get("answer") or ""),
            f"You confirmed in Teams on {when} that this answers your question, so I've closed the case in Salesforce.",
            "This confirms advice on your question. It is not approval to share anything beyond what is described above.",
        ])

    @staticmethod
    def _closing_message(record: dict, wants_email: bool, emailed: bool) -> str:
        closed = f"Case #{record['caseNumber']} is closed, confirmed by Salesforce."
        if emailed:
            return f"{closed} I've emailed you a confirmation of the outcome for your records. Thanks for checking before sharing!"
        lead = ("I couldn't send the confirmation email, so here's a summary for your records:" if wants_email
                else "Here's a summary for your records:")
        answer = (record["investigation"] or {}).get("answer") or ""
        return f"{lead}\n\n{answer}\n\n{closed} Thanks for checking before sharing!"

    @staticmethod
    def _status_notice(record: dict) -> str:
        number, result = record["caseNumber"], record["investigation"] or {}
        if record["salesforceStatus"] == "Closed":
            return f"Case #{number} is already closed. If something has changed, email me and I'll open a new case."
        if record["status"] == "awaiting_confirmation":
            return (f"Case #{number} is still open. Does my answer above resolve your question? If it does, would you "
                    "like me to email you a confirmation before I close it?")
        if record["status"] == "waiting_for_requester" and result.get("questions"):
            questions = "\n".join(f"{index}. {item}" for index, item in enumerate(result["questions"], 1))
            return f"No problem. To finish case #{number} I still need:\n{questions}"
        if record["status"] == "needs_specialist_review":
            return f"Case #{number} is with a compliance specialist for review; I'll update you here."
        return f"I'm still working on case #{number} and will reply here shortly."

    async def _notice(self, binding: ComplianceBinding, record: dict, text: str) -> None:
        """Best-effort courtesy message: never a claimed write, receipt or closure authority."""
        notify = getattr(self.backend, "notify", None)
        if notify is None or not record["privateChatId"]:
            return
        self._running()
        try:
            await notify(binding, record["authority"]["requesterId"], record["privateChatId"], text)
        except Exception:
            pass

    async def _investigate(self, binding: ComplianceBinding, record: dict, text: str) -> Investigation:
        """Investigation is read-only, so one transient failure is retried; authorization failures are not."""
        try:
            return await self.backend.investigate(binding, copy.deepcopy(record), text)
        except PermissionError:
            raise
        except Exception:
            self._running()
            return await self.backend.investigate(binding, copy.deepcopy(record), text)

    async def _drive(
        self, binding: ComplianceBinding, key: str, owner: str, email: VerifiedEmail | None = None,
    ) -> None:
        if email is not None:
            await self._register(binding, key, owner, email)
        while True:
            self._running()
            record = await self._take_work(binding, key, owner)
            if record["owner"] != owner:
                return
            work = record["work"]
            generation = work["generation"]
            if generation != record["generation"]:
                # Full bounded text remains in replyHistory for the next read-only
                # investigation. Don't silently discard facts or send old answers.
                continue
            await self._edit(binding, key, owner, lambda _record: True, "case_investigation_started")
            self._running()
            try:
                result = _investigation(
                    await self._investigate(binding, record, work["text"]),
                    generation, record["inputComplete"],
                )
            except Exception:
                def blocked(current: dict) -> bool:
                    current.update(status="needs_specialist_review", owner=None, resolution=None,
                                   lastOutcome="The records could not be checked; the next reply retries the investigation.")
                    return True

                current = await self._edit(binding, key, owner, blocked, "case_investigation_blocked")
                await self._notice(binding, current, f"Sorry, I couldn't check the records for case "
                                   f"#{current['caseNumber']} just now, so I haven't changed my answer. "
                                   "Reply here and I'll try again.")
                raise

            def investigated(current: dict) -> bool:
                if current["generation"] != generation or current["suspended"]:
                    return False
                current["investigation"] = copy.deepcopy(result)
                current["investigationHistory"] = (
                    current["investigationHistory"] + [copy.deepcopy(result)]
                )[-MAX_INVESTIGATION_HISTORY:]
                return True

            record = await self._edit(binding, key, owner, investigated, "case_investigated")
            if record["generation"] != generation or record["suspended"]:
                continue
            requester = record["authority"]["requesterId"]
            if not record["privateChatId"]:
                proof = await self._write(binding, key, owner, "chat",
                    lambda: self.backend.ensure_private_chat(binding, requester),
                    lambda value: {"chatId": _opaque(value)}, generation)
                if proof is None:
                    continue

                def chat_ready(current: dict) -> bool:
                    current["privateChatId"] = proof["chatId"]
                    return True

                record = await self._edit(binding, key, owner, chat_ready, "case_private_chat_ready")
            comment = self._comment(record)
            proof = await self._write(binding, key, owner, f"update:{generation}",
                lambda: self.backend.update_case(binding, record["caseId"], comment, close=False),
                self._ack, generation)
            if proof is None:
                continue
            await self._edit(binding, key, owner, lambda _record: True, "case_updated")
            text = self._message(record)
            proof = await self._write(binding, key, owner, f"delivery:{generation}",
                lambda: self.backend.send_private(binding, requester, record["privateChatId"], text),
                lambda value: {"messageId": _opaque(value)}, generation)
            if proof is None:
                continue

            def delivered(current: dict) -> bool:
                write = current["writes"][f"delivery:{generation}"]
                current["lastDelivery"] = {
                    "generation": generation, "messageId": proof["messageId"], "at": write["completedAt"],
                }
                if current["generation"] != generation or current["suspended"]:
                    current["resolution"] = None
                    return True
                current["resolution"] = {
                    "generation": generation, "messageId": proof["messageId"], "deliveryNonce": write["nonce"],
                } if result["resolutionReady"] else None
                current["status"] = (
                    "awaiting_confirmation" if current["resolution"] else
                    "waiting_for_requester" if result["questions"] else "needs_specialist_review"
                )
                current["lastOutcome"] = "Answer delivery has a verified message receipt."
                return True

            await self._edit(binding, key, owner, delivered, "case_answer_delivered")

    @staticmethod
    def _can_resolve(record: dict, received_at: float) -> bool:
        generation, result, authority = record["generation"], record["investigation"], record["resolution"]
        if (record["owner"] is not None or record["suspended"] or record["pendingReplies"]
                or record["status"] != "awaiting_confirmation" or record["salesforceStatus"] == "Closed"
                or type(result) is not dict or type(authority) is not dict or not record["inputComplete"]):
            return False
        write = record["writes"].get(f"delivery:{generation}", {})
        return (
            result.get("generation") == generation and result.get("resolutionReady") is True
            and bool(result.get("answer", "").strip()) and bool(result.get("evidence"))
            and all(type(ref) is dict and ref.get("id") and ref.get("version") for ref in result["evidence"])
            and not result.get("blockers") and not result.get("questions")
            and authority.get("generation") == generation and write.get("status") == "completed"
            and write.get("nonce") == authority.get("deliveryNonce")
            and write.get("receipt", {}).get("messageId") == authority.get("messageId")
            and bool(authority.get("messageId")) and received_at >= write["completedAt"]
            and all(item["status"] == "completed" for item in record["writes"].values())
        )

    @staticmethod
    def _last_contact(record: dict) -> float:
        delivery = record["lastDelivery"]
        at = delivery.get("at") if type(delivery) is dict else None
        return at if type(at) in (int, float) else record["createdAt"]

    @classmethod
    def _target(cls, index: dict, requester_id: str, chat_id: str, number: str | None, text: str) -> dict | None:
        candidates = [record for record in index["cases"].values()
                      if record["authority"]["requesterId"] == requester_id and record["privateChatId"] == chat_id]
        if number is not None:
            candidates = [record for record in candidates if record["caseNumber"] == number]
        elif text.lower().startswith(("case #", "resolve ")):
            if len(candidates) != 1:
                return None
        elif len(candidates) > 1:
            # A plain reply continues the open case the requester was most recently messaged about.
            candidates = sorted((record for record in candidates if record["salesforceStatus"] != "Closed"),
                                key=cls._last_contact)[-1:]
        return candidates[0] if len(candidates) == 1 else None

    async def _intent(
        self, binding: ComplianceBinding, requester_id: str, chat_id: str, number: str | None, text: str,
        command: bool,
    ) -> tuple[str, str]:
        """Model-read routing for a free-text reply, pinned to the case it was read against."""
        interpret = getattr(self.backend, "interpret_reply", None)
        if command or interpret is None:
            return "information", ""
        index = self._index(await self.store.read(self._scope(binding)), binding)
        record = self._target(index, requester_id, chat_id, number, text) if index is not None else None
        if record is None:
            return "information", ""
        self._running()
        try:
            intent = await interpret(binding, self._view(record), text)
        except Exception:
            return "information", record["key"]
        return (intent if intent in _INTENTS else "information"), record["key"]

    async def handle_reply(
        self, binding: ComplianceBinding, requester_id: str, chat_id: str, activity_id: str, text: str,
    ) -> bool:
        task = self._enter()
        key, owner = "", uuid.uuid4().hex
        try:
            binding = self._binding(binding)
            try:
                requester_id = _guid(requester_id)
                _opaque(chat_id)
                _opaque(activity_id)
                _plain(text)
            except ValueError:
                return False
            if requester_id not in binding.requester_ids or not text.strip():
                return False
            received_at = self.store._now()
            activity_key = _hash(binding.tenant_id, binding.instance_app_id, requester_id, chat_id, activity_id)
            resolve, marker = _RESOLVE.fullmatch(text), _MARKER.match(text)
            if len(set(_CASE_MENTION.findall(text))) > 1:
                return False
            number = resolve.group(1) if resolve else marker.group(1) if marker else None
            safe_text = _compact(text, 2000)
            intent, intent_key = await self._intent(binding, requester_id, chat_id, number, text, bool(resolve))
            handled, action = False, ""

            def accept(index: dict, events: list) -> None:
                nonlocal key, handled, action
                key, handled, action = "", False, ""  # Reset all CAS-candidate decisions.
                record = self._target(index, requester_id, chat_id, number, text)
                if record is None:
                    return
                key = record["key"]
                # An activity cannot be replayed against another case by changing its marker.
                previous = [item for item in index["cases"].values() if activity_key in item["activities"]]
                if previous:
                    handled = len(previous) == 1 and previous[0]["key"] == key
                    return
                handled = True
                if len(record["activities"]) >= MAX_ACTIVITY_RECEIPTS:
                    record.update(suspended=True, resolution=None, lastOutcome="Activity receipt capacity reached.")
                    if record["status"] != "write_outcome_unknown":
                        record["status"] = "needs_specialist_review"
                    self._event(record, "case_capacity_blocked", received_at, events)
                    return
                record["activities"].append(activity_key)
                understood = intent if intent_key == key else "information"
                if resolve and not self._can_resolve(record, received_at):
                    self._event(record, "case_resolution_rejected", received_at, events)
                    return
                if resolve or (understood in _CONFIRM and self._can_resolve(record, received_at)):
                    record.update(owner=owner, status="closing", confirmation={
                        "text": text, "at": received_at, "requesterId": requester_id, "chatId": chat_id,
                        "activityId": activity_id, "activityKey": activity_key,
                        "generation": record["generation"], "answerMessageId": record["resolution"]["messageId"],
                        "email": understood == "confirm_with_email",
                    })
                    action = "close"
                    self._event(record, "case_resolution_requested", received_at, events)
                    return
                if understood == "chat":
                    self._event(record, "case_chat_received", received_at, events, safe_text)
                    action = "notice"
                    return
                # Everything else is material, never implicit approval.
                record["resolution"] = None
                record["investigation"] = None
                record["inputComplete"] = record["inputComplete"] and safe_text == text
                if (record["generation"] >= MAX_TURNS - 1
                        or len(record["pendingReplies"]) >= MAX_PENDING_REPLIES):
                    record.update(suspended=True, lastOutcome="Clarification capacity reached; specialist review required.")
                elif not record["suspended"]:
                    record["generation"] += 1
                    reply = {
                        "generation": record["generation"], "text": safe_text,
                        "at": received_at, "activityKey": activity_key,
                    }
                    record["pendingReplies"].append(reply)
                    record["replyHistory"].append(copy.deepcopy(reply))
                if record["salesforceStatus"] == "Closed":
                    record.update(suspended=True, lastOutcome="New material after closure requires specialist follow-up.")
                if record["suspended"]:
                    if record["status"] != "write_outcome_unknown":
                        record["status"] = "needs_specialist_review"
                else:
                    record["status"] = "investigating"
                    if record["owner"] is None:
                        record["owner"], action = owner, "investigate"
                self._event(record, "case_reply_received", received_at, events, safe_text)

            try:
                index = await self._change(binding, accept)
            except _OwnershipLost:
                return False
            if key and action == "notice":
                await self._notice(binding, index["cases"][key], self._status_notice(index["cases"][key]))
            elif key and index["cases"][key]["owner"] == owner:
                if action == "close":
                    await self._close_case(binding, key, owner)
                elif action == "investigate":
                    await self._notice(binding, index["cases"][key], "Thanks, let me check that against the records.")
                    await self._drive(binding, key, owner)
            return handled
        except BaseException:
            if key:
                await self._abort(binding, key, owner)
            raise
        finally:
            self._leave(task)

    async def _close_case(self, binding: ComplianceBinding, key: str, owner: str) -> None:
        record = await self._record(binding, key)
        if record["owner"] != owner or not record["confirmation"]:
            raise _OwnershipLost("Only the explicit requester confirmation owns closure.")
        generation = record["confirmation"]["generation"]
        comment = self._comment(record, close=True)
        proof = await self._write(binding, key, owner, "close",
            lambda: self.backend.update_case(binding, record["caseId"], comment, close=True), self._ack, generation)
        if proof is None:
            await self._drive(binding, key, owner)  # Material won the CAS before closure's claim.
            return

        def verifying(current: dict) -> bool:
            current["status"] = "verifying_close"
            return True

        await self._edit(binding, key, owner, verifying, "case_close_acknowledged")
        self._running()
        status = _opaque(await self.backend.read_case_status(binding, record["caseId"]), 128)
        at = self.store._now()

        def readback(current: dict) -> bool:
            current["closureReadback"] = {"status": status, "at": at}
            return True

        await self._edit(binding, key, owner, readback)
        if status != "Closed":
            raise RuntimeError("Salesforce has not confirmed the exact Closed status.")

        def closed(current: dict) -> bool:
            current.update(salesforceStatus="Closed", closedAt=at, resolution=None)
            if current["generation"] != generation or current["pendingReplies"] or current["suspended"]:
                current.update(status="needs_specialist_review", suspended=True, owner=None,
                               lastOutcome="Salesforce closed, but new material requires specialist follow-up.")
            else:
                current.update(status="closed", lastOutcome="Salesforce closure confirmed by readback.")
            return True

        record = await self._edit(binding, key, owner, closed, "case_close_readback")
        if record["owner"] != owner:
            return
        wants_email = bool(record["confirmation"].get("email"))
        emailed = wants_email and await self._email_confirmation(binding, record)
        text = self._closing_message(record, wants_email, emailed)
        proof = await self._write(binding, key, owner, "closed_delivery",
            lambda: self.backend.send_private(binding, record["authority"]["requesterId"], record["privateChatId"], text),
            lambda value: {"messageId": _opaque(value)}, generation)

        def notified(current: dict) -> bool:
            if proof is not None:
                current["closureMessageId"] = proof["messageId"]
            current["confirmationEmail"] = "sent" if emailed else "failed" if wants_email else "declined"
            current["owner"] = None
            if current["generation"] == generation and not current["suspended"] and proof is not None:
                current["status"] = "closed"
            else:
                current.update(status="needs_specialist_review", suspended=True)
            return True

        await self._edit(binding, key, owner, notified, "case_closure_notice_recorded")

    async def _email_confirmation(self, binding: ComplianceBinding, record: dict) -> bool:
        """Best effort after a verified close; a failure falls back to a summary in the chat."""
        send = getattr(self.backend, "send_confirmation_email", None)
        if send is None:
            return False
        self._running()
        try:
            await send(binding, record["authority"]["requesterId"], self._view(record), self._summary(record))
        except Exception:
            return False
        return True

    async def list_cases(self, tenant_id: str, manager_id: str) -> list[dict]:
        """Detached manager-scoped records; the host authenticates both query IDs."""
        task = self._enter()
        try:
            tenant_id, manager_id = _guid(tenant_id), _guid(manager_id)
            cases = []
            for binding in self._bindings.values():
                if binding.tenant_id == tenant_id and binding.manager_id == manager_id:
                    index = self._index(await self.store.read(self._scope(binding)), binding)
                    if index is not None:
                        cases.extend(self._view(record) for record in index["cases"].values())
            return sorted(cases, key=lambda record: (record["createdAt"], record["key"]), reverse=True)
        finally:
            self._leave(task)

    async def close(self) -> None:
        self._closed = True
        current = asyncio.current_task()
        active = [task for task in self._active if task is not current]
        for task in active:
            task.cancel()
        cancelled = False
        for task in active:
            cancelled = await _drain(task) or cancelled
        for task in tuple(self._storage):
            cancelled = await _drain(task) or cancelled
        if cancelled and current is not None and current.cancelling():
            raise asyncio.CancelledError