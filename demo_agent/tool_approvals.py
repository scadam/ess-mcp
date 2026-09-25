"""Durable, requester-only confirmation; no SDK hosting, model, or MCP client.

Main must construct BOTH ChatScope and actor from verified SDK/auth middleware,
never model output, headers supplied by a client, or activity.value. Route only
the current authenticated user's text to decide(), before invoking a planner.
Required actor fields are aadObjectId, tenantId, conversationId; no anonymous,
channel-ID, role, or operator override is accepted. AZURE_TENANT_ID is pinned at
construction. AUTOPILOT_TASK_USER_IDS / AUTOPILOT_OPERATOR_IDS are nonzero UUID
allowlists (comma, semicolon, or whitespace separated); empty lists grant nobody
access. Reconstruct the gate when trusted configuration changes.

Integration deliberately remains outside this module:
* Main's normal tool-validation branch proposes consequential calls. Main still
  owns tool classification, argument schemas, routing, governance and DLP.
* Inject a DISTINCT, single-attempt effect callback, not a normal model run. It
  must raise on upstream errors/ambiguous outcomes, not return an error string.
  In that callback, main may temporarily set its approved-digest ContextVar to
  tool_call_digest(server, tool, args), resetting the token in finally. Bypass
  only the approval branch for that exact target/arguments, never other policy.
  Do not retry, start another planner, or spawn background work in that context.
* clear() is a trusted host operation for forget: it rejects pending approvals
  without erasing execution receipts or touching ordinary conversation memory.

CAS guarantees at most one callback attempt per retained request, NOT exactly
once external effects. A process crash can leave executing indefinitely; reads
never recover/replay it. Failed outcome persistence leaves a non-replayable
executing receipt. Store TTL and bounded receipt retention still apply. SHA-256
detects changed calls, not a malicious writer able to replace both call and hash.
Redaction is heuristic, not a secret classifier. Long approval previews are
explicitly shortened; a host wanting full review must render the stored args.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from .conversation_memory import (
    MAX_CONTENT_CHARS,
    MAX_JSON_DEPTH,
    ChatScope,
    Store,
    scrub_memory_text,
)

__all__ = ["ToolApprovalGate", "tool_call_digest"]

Executor = Callable[[str, str, dict[str, Any], dict[str, Any]], Awaitable[str]]
APPROVAL_TTL_SECONDS = 15 * 60
MAX_RECORDS = 50
MAX_PENDING = 20
MAX_ARGUMENT_BYTES = 16_000
MAX_RESULT_CHARS = 8_000
MAX_MESSAGE_CHARS = 1_800

_SERVERS = frozenset({"workday", "servicenow", "coupa", "salesforce"})
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_TOOL = re.compile(r"[A-Za-z0-9_]{1,64}")
_COMMAND = re.compile(r"(approve|reject) ([0-9a-fA-F]{12})")
_DIGEST = re.compile(r"[0-9a-f]{64}")
_DENIED = "Tool approval requires an authorized, verified user in the configured tenant and this chat."
_NOT_FOUND = "No approval for that ID is available to you in this chat."
_INVALID = "This approval could not be verified. Nothing was run; request a new approval."
_EXPIRED = "This approval has expired. Nothing was run; request a new approval."
_REJECTED = "This approval was rejected. Nothing was run."
_SAVE_FAILED = "I could not confirm that the approval was saved. No tool was run."
_PENDING_PREFIX = "Approval needed for "


def proposal_saved(message: str) -> bool:
    """True only for a stored pending request; every refusal or save failure means nothing awaits approval."""
    return isinstance(message, str) and message.startswith(_PENDING_PREFIX)

# The public scrubber redacts the WHOLE input, then caps its output at 8K.
# Comparing against text[:8K] separates redaction from truncation. For longer
# inputs, also scan for these conservative full-string markers, aligned with
# its patterns: suffix/chunk-only scrubbing can miss a credential or a long
# assignment prefix crossing the 8K boundary. Decoded JSON strings are checked
# too, so JSON-escaped newlines cannot disguise a Bearer/private-key value.
_LONG_CREDENTIAL = re.compile(
    r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?-----"
    r"|\bBearer\s+[^\s\"'`,;<>]+"
    r"|(?<![A-Za-z0-9_.-])(?:eyJ[A-Za-z0-9_-]*|[A-Za-z0-9_-]{16,})"
    r"(?:\.[A-Za-z0-9_-]*){2,4}(?![A-Za-z0-9_.-])"
    r"|(?<![\w.-])[\"']?"
    r"(?:[\w.-]{0,64}(?:password|passwd|pwd|token|secret)[\w.-]{0,64}"
    r"|api[_-]?key|accountkey|private[_-]?key)[\"']?\s*[:=]\s*\S",
    re.IGNORECASE,
)


class _InvalidRequest(ValueError):
    """Only fixed, credential-free messages may be used here."""


def _guid(value: Any) -> str | None:
    if type(value) is not str or _GUID.fullmatch(value) is None:
        return None
    parsed = uuid.UUID(value)
    return str(parsed) if parsed.int else None


def _configured_users() -> frozenset[str]:
    users: set[str] = set()
    for name in ("AUTOPILOT_TASK_USER_IDS", "AUTOPILOT_OPERATOR_IDS"):
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        for part in re.split(r"[,;]", raw):
            if not part.strip():
                raise ValueError("Tool approval allowlists must contain only nonzero UUIDs.")
            for item in part.split():
                identifier = _guid(item)
                if identifier is None:
                    raise ValueError("Tool approval allowlists must contain only nonzero UUIDs.")
                users.add(identifier)
    return frozenset(users)


def _epoch(value: Any) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return value >= 0 and math.isfinite(value)
    except OverflowError:
        return False


def _credential_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    return (
        normalized in {
            "auth", "oauth", "authorization", "proxyauthorization", "authentication",
            "authheader", "authheaders", "cookie", "cookies", "setcookie", "apikey",
            "xapikey", "accountkey", "accesskey", "privatekey", "connectionstring",
            "clientassertion", "sas", "pwd",
        }
        or normalized.endswith("auth")
        or any(part in normalized for part in (
            "authorization", "authentication", "authheader", "token", "password",
            "passwd", "secret", "credential", "apikey", "accountkey", "privatekey", "connectionstring",
        ))
    )


def _has_credentials(text: str) -> bool:
    return (
        scrub_memory_text(text) != text[:MAX_CONTENT_CHARS]
        or (len(text) > MAX_CONTENT_CHARS and _LONG_CREDENTIAL.search(text) is not None)
    )


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _validated_call(server: Any, tool: Any, args: Any) -> tuple[dict[str, Any], str, str]:
    if type(server) is not str or server not in _SERVERS:
        raise _InvalidRequest("Only the configured workday, servicenow, coupa, or salesforce tools can be approved.")
    if type(tool) is not str or _TOOL.fullmatch(tool) is None:
        raise _InvalidRequest("Tool names must contain 1–64 ASCII letters, digits, or underscores.")
    if type(args) is not dict:
        raise _InvalidRequest("Tool arguments must be a plain JSON object.")
    budget = MAX_ARGUMENT_BYTES

    def visit(value: Any, depth: int) -> None:
        nonlocal budget
        if depth > MAX_JSON_DEPTH - 2:
            raise _InvalidRequest("Tool arguments are too deeply nested or cyclic.")
        kind = type(value)
        # A lower bound on JSON size also bounds traversal/allocation before
        # encoding; the exact total UTF-8 byte limit is checked separately.
        budget -= len(value.encode("utf-8")) + 2 if kind is str else 1
        if budget < 0:
            raise _InvalidRequest("Tool arguments exceed the 16000-byte JSON limit.")
        if kind is str:
            if _has_credentials(value):
                raise _InvalidRequest("Credentials are not accepted in tool arguments.")
        elif value is None or kind in (bool, int):
            return
        elif kind is float:
            if not math.isfinite(value):
                raise _InvalidRequest("Tool arguments must contain only finite JSON values.")
        elif kind is list:
            for item in value:
                visit(item, depth + 1)
        elif kind is dict:
            for key, item in value.items():
                if type(key) is not str:
                    raise _InvalidRequest("Tool argument keys must be strings.")
                if _credential_key(key):
                    raise _InvalidRequest("Credentials are not accepted in tool arguments.")
                visit(key, depth + 1)
                visit(item, depth + 1)
        else:
            raise _InvalidRequest("Tool arguments must contain only plain JSON values.")

    try:
        visit(args, 0)
        raw = _json(args)
        if len(raw.encode("utf-8")) > MAX_ARGUMENT_BYTES:
            raise _InvalidRequest("Tool arguments exceed the 16000-byte JSON limit.")
        if _has_credentials(raw):
            raise _InvalidRequest("Credentials are not accepted in tool arguments.")
        snapshot = json.loads(raw)
        canonical = _json({"server": server, "tool": tool, "args": snapshot})
    except _InvalidRequest:
        raise
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError, RuntimeError):
        raise _InvalidRequest("Tool arguments must be bounded, valid JSON.") from None
    return snapshot, hashlib.sha256(canonical.encode("utf-8")).hexdigest(), raw


def tool_call_digest(server: str, tool: str, args: dict[str, Any]) -> str:
    """Validate and SHA-256 hash sorted, compact UTF-8 JSON of {server,tool,args}.

    This is a fingerprint, NOT proof of approval. Only the injected effect
    callback may establish main's temporary approved-digest context.
    """
    return _validated_call(server, tool, args)[1]


def _safe_result(text: str) -> str:
    if type(text) is not str:
        raise TypeError("The tool executor must return text or raise.")
    return scrub_memory_text(text.encode("utf-8", errors="replace").decode("utf-8"))[:MAX_RESULT_CHARS]


def _unknown(request_id: str) -> str:
    return (
        f"Request {request_id} has an unknown outcome and may already have taken effect. "
        "It will not be replayed. Check the source system before requesting another action."
    )


def _status_message(request_id: str, record: dict[str, Any]) -> str:
    status = record.get("status")
    if status == "executing":
        return f"Request {request_id} is executing or may still be running. It will not be replayed."
    if status == "unknown":
        return _unknown(request_id)
    if status == "rejected":
        # Only known notices, never arbitrary persisted rejection/error text.
        reason = record.get("result")
        return reason if reason in (_EXPIRED, _INVALID, _REJECTED) else _REJECTED
    if status == "completed":
        result = record.get("result")
        safe = _safe_result(result) if type(result) is str else "No text result is available."
        message = f"Request {request_id} completed.\n{safe or 'No text result was returned.'}"
        if len(message) > MAX_MESSAGE_CHARS:
            suffix = "\n[Result shortened; the bounded result is saved.]"
            message = message[:MAX_MESSAGE_CHARS - len(suffix)] + suffix
        return message
    return _INVALID


def _approval_message(request_id: str, record: dict[str, Any]) -> str:
    # JSON strings escape control characters; escaping HTML delimiters also
    # prevents a stored tool argument being rendered as a tag/mention.
    preview = _json(record["args"]).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    prefix = f"{_PENDING_PREFIX}{record['server']}.{record['tool']} (request {request_id}).\nArguments (data): "
    suffix = (
        f"\nNothing has run yet. Reply 'yes' to go ahead or 'no' to cancel (with several waiting, use "
        f"'approve {request_id}' or 'reject {request_id}'). Only you can answer, and it expires in 15 minutes."
    )
    available = MAX_MESSAGE_CHARS - len(prefix) - len(suffix)
    if len(preview) > available:
        marker = " … [argument preview shortened]"
        preview = preview[:available - len(marker)] + marker
    return prefix + preview + suffix


async def _settle(task: asyncio.Task[Any]) -> bool:
    """Join a persistence task despite repeated caller cancellation; retrieve errors."""
    cancelled = False
    while True:
        try:
            await asyncio.shield(task)
            return cancelled
        except asyncio.CancelledError:
            cancelled = True
            if task.cancelled():
                return cancelled
        except Exception:
            return cancelled  # Persistence is best effort here; never expose its error.


class ToolApprovalGate:
    def __init__(self, store: Store, execute: Executor, clock: Callable[[], float] = time.time) -> None:
        tenant = _guid(os.environ.get("AZURE_TENANT_ID", "").strip())
        if tenant is None:
            raise ValueError("AZURE_TENANT_ID must be a nonzero tenant UUID for tool approvals.")
        if not isinstance(store, Store) or not callable(execute) or not callable(clock):
            raise ValueError("Tool approvals require a Store, an async executor, and a clock.")
        self.store = store
        self._execute = execute
        self._clock = clock
        self._tenant = tenant
        self._users = _configured_users()

    def _now(self) -> float:
        value = self._clock()
        if not _epoch(value):
            raise ValueError("The approval clock must return a finite nonnegative epoch.")
        return float(value)

    def _scope_allowed(self, scope: ChatScope) -> bool:
        return isinstance(scope, ChatScope) and _guid(scope.tenant_id) == self._tenant

    @staticmethod
    def _storage_scope(scope: ChatScope) -> ChatScope:
        return ChatScope(scope.tenant_id, scope.agent_id, "tool-approvals:" + scope.storage_key)

    def _actor(self, scope: ChatScope, actor: dict[str, Any]) -> dict[str, Any] | None:
        if not self._scope_allowed(scope) or type(actor) is not dict:
            return None
        # Read each authority field once. Only this fresh identity projection is
        # passed to the callback; roles, credentials and model fields are not.
        user = _guid(actor.get("aadObjectId"))
        tenant = _guid(actor.get("tenantId"))
        chat = actor.get("conversationId")
        if user not in self._users or tenant != self._tenant or type(chat) is not str or chat != scope.conversation_id:
            return None
        return {"aadObjectId": user, "tenantId": tenant, "conversationId": chat}

    async def _update(self, scope: ChatScope, transform: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        # A cancelled SQLite to_thread CAS may still commit. Join its shielded
        # operation BEFORE attempting an unknown receipt, or cleanup could race
        # ahead of the claim and leave a late, unobserved executing write.
        write = asyncio.create_task(self.store.update(scope, transform))
        try:
            return await asyncio.shield(write)
        except asyncio.CancelledError:
            await _settle(write)
            raise

    def _validated_request(self, record: dict[str, Any], scope: ChatScope, requester: str) -> dict[str, Any]:
        if record.get("scope") != scope.to_dict() or record.get("requesterId") != requester:
            raise _InvalidRequest(_INVALID)
        at, expires = record.get("at"), record.get("expiresAt")
        if not _epoch(at) or not _epoch(expires) or expires != at + APPROVAL_TTL_SECONDS:
            raise _InvalidRequest(_INVALID)
        now = self._now()
        if now < at or now >= expires:
            raise _InvalidRequest(_EXPIRED)
        if record.get("status") == "pending" and "claimId" in record:
            raise _InvalidRequest(_INVALID)
        args, digest, _ = _validated_call(record.get("server"), record.get("tool"), record.get("args"))
        saved = record.get("digest")
        if type(saved) is not str or _DIGEST.fullmatch(saved) is None or saved != digest:
            raise _InvalidRequest(_INVALID)
        return args

    async def propose(self, scope: ChatScope, actor: dict[str, Any], server: str, tool: str, args: dict[str, Any]) -> str:
        """Save a bounded proposal; never execute. Validation failures are safe text."""
        identity = self._actor(scope, actor)
        if identity is None:
            return _DENIED
        try:
            snapshot, digest, _ = _validated_call(server, tool, args)
        except _InvalidRequest as error:
            return str(error)
        requester = identity["aadObjectId"]
        # All randomness is outside retryable transforms; collisions never
        # overwrite an existing request, including one being pruned below.
        candidates = [uuid.uuid4().hex[:12] for _ in range(5)]
        response = _SAVE_FAILED

        def propose(state: dict[str, Any]) -> None:
            nonlocal response
            response = _SAVE_FAILED  # A failed CAS must not leave a stale success.
            now = self._now()
            tasks = state["tasks"]
            for record in tasks.values():
                if record.get("status") == "pending" and (
                    not _epoch(record.get("expiresAt")) or now >= record["expiresAt"]
                ):
                    record.update(status="rejected", result=_EXPIRED)
            for request_id, record in tasks.items():
                if (record.get("status") == "pending" and record.get("requesterId") == requester
                        and record.get("digest") == digest):
                    try:
                        self._validated_request(record, scope, requester)
                    except _InvalidRequest:
                        record.update(status="rejected", result=_INVALID)
                    else:
                        response = _approval_message(request_id, record)
                        return
            if sum(record.get("status") == "pending" for record in tasks.values()) >= MAX_PENDING:
                response = "This chat already has 20 pending approvals. Reject one or let it expire before requesting another."
                return
            request_id = next((candidate for candidate in candidates if candidate not in tasks), None)
            if request_id is None:
                response = "A unique approval ID could not be allocated. Nothing was run."
                return
            # Also protect executing/unknown receipts; never evict uncertain or
            # in-flight work merely to admit another proposal.
            removable = sorted(
                (key for key, record in tasks.items() if record.get("status") in {"completed", "rejected"}),
                key=lambda key: (tasks[key]["at"] if _epoch(tasks[key].get("at")) else -1, key),
            )
            for key in removable[:max(0, len(tasks) - MAX_RECORDS + 1)]:
                del tasks[key]
            if len(tasks) >= MAX_RECORDS:
                response = "Approval history is full of pending or uncertain actions. Nothing was run; review existing actions first."
                return
            record = {
                "server": server, "tool": tool, "args": snapshot, "digest": digest,
                "requesterId": requester, "scope": scope.to_dict(), "expiresAt": now + APPROVAL_TTL_SECONDS,
                "status": "pending", "at": now, "result": "",
            }
            tasks[request_id] = record
            response = _approval_message(request_id, record)

        try:
            await self._update(self._storage_scope(scope), propose)
        except Exception:
            return _SAVE_FAILED
        return response

    async def _finish(self, scope: ChatScope, request_id: str, claim_id: str, status: str, result: str) -> bool:
        finished = False

        def finish(state: dict[str, Any]) -> None:
            nonlocal finished
            finished = False
            record = state["tasks"].get(request_id)
            if record and record.get("status") == "executing" and record.get("claimId") == claim_id:
                record.update(status=status, result=result)
                finished = True

        await self._update(scope, finish)
        return finished

    async def sole_pending(self, scope: ChatScope, actor: dict[str, Any]) -> str | None:
        """The one live approval waiting on this requester in this chat, if there is exactly one."""
        identity = self._actor(scope, actor)
        if identity is None:
            return None
        state = await self.store.read(self._storage_scope(scope))
        now = self._now()
        waiting = [request_id for request_id, record in state["tasks"].items()
                   if record.get("status") == "pending" and "claimId" not in record
                   and record.get("requesterId") == identity["aadObjectId"] and record.get("scope") == scope.to_dict()
                   and _epoch(record.get("expiresAt")) and now < record["expiresAt"]
                   and _COMMAND.fullmatch(f"approve {request_id}") is not None]
        return waiting[0] if len(waiting) == 1 else None

    async def decide(self, scope: ChatScope, actor: dict[str, Any], text: str) -> str | None:
        """Handle exact lowercase commands and 12 hex digits (hex case is ignored).

        No trimming, fuzzy intent, multiple commands, or approval from another
        requester. The execute callback receives detached args and ONLY the
        current verified aadObjectId/tenantId/conversationId identity projection.
        """
        match = _COMMAND.fullmatch(text) if type(text) is str else None
        if match is None:
            return None
        identity = self._actor(scope, actor)
        if identity is None:
            return _DENIED
        action, request_id = match.group(1), match.group(2).lower()
        requester = identity["aadObjectId"]
        storage_scope = self._storage_scope(scope)
        claim_id = uuid.uuid4().hex
        response = _NOT_FOUND
        claimed = False
        caller = asyncio.current_task()

        def decide(state: dict[str, Any]) -> None:
            nonlocal response, claimed
            response = _NOT_FOUND
            claimed = False  # Reset on EVERY CAS attempt, including a no-op retry.
            record = state["tasks"].get(request_id)
            if not record or record.get("scope") != scope.to_dict() or record.get("requesterId") != requester:
                return
            if record.get("status") != "pending":
                response = _status_message(request_id, record)
                return
            try:
                self._validated_request(record, scope, requester)
            except _InvalidRequest as error:
                reason = _EXPIRED if str(error) == _EXPIRED else _INVALID
                record.update(status="rejected", result=reason)
                response = reason
                return
            if action == "reject":
                record.update(status="rejected", result=_REJECTED)
                response = _REJECTED
            else:
                record.update(status="executing", claimId=claim_id)
                claimed = True

        try:
            if caller is not None and caller.cancelling():
                raise asyncio.CancelledError
            state = await self._update(storage_scope, decide)
            record = state["tasks"].get(request_id)
            # Require BOTH a transition in the successful transform and its
            # committed ownership nonce. Even a repeated nonce cannot replay
            # an already-executing record, nor can a losing CAS retain authority.
            if (action != "approve" or not claimed or not record
                    or record.get("status") != "executing" or record.get("claimId") != claim_id):
                return response
            try:
                # Recheck after the storage await too: the request may have
                # expired while the durable claim was being committed.
                call_args = self._validated_request(record, scope, requester)
            except _InvalidRequest as error:
                reason = _EXPIRED if str(error) == _EXPIRED else _INVALID
                saved = await self._finish(storage_scope, request_id, claim_id, "rejected", reason)
                return reason if saved else _unknown(request_id)
            if caller is not None and caller.cancelling():
                raise asyncio.CancelledError
            result = await self._execute(record["server"], record["tool"], call_args, identity)
            # A callback that swallows CancelledError must not restore delivery
            # authority merely by returning a string after cancellation.
            if caller is not None and caller.cancelling():
                raise asyncio.CancelledError
            safe = _safe_result(result)
            if not await self._finish(storage_scope, request_id, claim_id, "completed", safe):
                return _unknown(request_id)
            return _status_message(request_id, {"status": "completed", "result": safe})
        except BaseException as error:
            # The callback may already have effected the change, even if it
            # failed, timed out or was cancelled. Never make it pending again.
            # Only this invocation's executing claim can be changed; completed
            # receipts and another process's claims cannot be downgraded.
            cancelled = False
            if claimed:
                cleanup = asyncio.create_task(self._finish(
                    storage_scope, request_id, claim_id, "unknown", _unknown(request_id),
                ))
                cancelled = await _settle(cleanup)
            if not isinstance(error, Exception):
                raise
            if cancelled or (caller is not None and caller.cancelling()):
                raise asyncio.CancelledError
            return _unknown(request_id)

    async def clear(self, scope: ChatScope) -> None:
        """Reject only pending approvals; main must authorize the forget action."""
        if not self._scope_allowed(scope):
            raise ValueError("Tool approval clearing requires a scope in the configured tenant.")

        def clear(state: dict[str, Any]) -> None:
            for record in state["tasks"].values():
                if record.get("status") == "pending":
                    record.update(status="rejected", result=_REJECTED)

        await self._update(self._storage_scope(scope), clear)