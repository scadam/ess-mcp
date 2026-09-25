"""Durable, fail-closed receipts for one authenticated compliance email.

The caller must verify the SDK notification and map its addressed agentic user
and sender to directory identities before constructing ``CaseIdentity``.  This
module does not authenticate notifications or infer policy from email content.
Every external effect is preceded by a durable claim. A crash or ambiguous
response leaves the claim in an unknown state; it is never replayed blindly.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

from .conversation_memory import ChatScope, Store


_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,127}\Z")
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
_CONFIRM = re.compile(
    r"(?i)yes,? that (?:answers|resolves) my question,? please close (?:the|my) case\.?\Z"
)


def _opaque_id(value: str) -> bool:
    return type(value) is str and 0 < len(value) <= 512 and value.isprintable() and bool(value.strip())


@dataclass(frozen=True)
class CaseIdentity:
    tenant_id: str
    instance_id: str
    manager_id: str
    requester_id: str
    message_id: str
    private_conversation_id: str

    def __post_init__(self) -> None:
        for field in (self.tenant_id, self.instance_id, self.manager_id, self.requester_id):
            if not _GUID.fullmatch(field):
                raise ValueError("Verified tenant and user object IDs are required.")
        if not _opaque_id(self.message_id) or not _opaque_id(self.private_conversation_id):
            raise ValueError("Stable notification and private Teams conversation IDs are required.")

    @property
    def scope(self) -> ChatScope:
        # The notification ID can be untrusted; it never becomes a path segment.
        key = hashlib.sha256(self.message_id.encode("utf-8")).hexdigest()
        return ChatScope(self.tenant_id.lower(), self.instance_id.lower(), f"compliance:{key}")

    def authority(self) -> dict[str, str]:
        return {
            "tenant": self.tenant_id.lower(), "instance": self.instance_id.lower(),
            "manager": self.manager_id.lower(), "requester": self.requester_id.lower(),
            "message": self.message_id, "privateConversation": self.private_conversation_id,
        }


class CaseWorkflow:
    """Store only references and status; external callbacks must enforce their own auth."""

    def __init__(self, store: Store, emit: Callable[[str, dict[str, str]], None] | None = None):
        self.store = store
        self.emit = emit or (lambda _event, _data: None)

    async def _record(self, identity: CaseIdentity) -> dict[str, str] | None:
        record = (await self.store.read(identity.scope))["tasks"].get("case")
        if record is not None and record.get("authority") != identity.authority():
            raise PermissionError("The case does not belong to this requester and instance.")
        return record

    async def _mark_uncertain(self, identity: CaseIdentity, expected: str) -> None:
        def mark(state: dict) -> None:
            record = state["tasks"].get("case")
            if record and record.get("authority") == identity.authority() and record.get("status") == expected:
                record["status"] = "write_outcome_unknown"

        task = asyncio.create_task(self.store.update(identity.scope, mark))
        try:
            await asyncio.shield(task)
        except BaseException:
            # The original write outcome is already uncertain. A storage
            # failure cannot safely restore permission to retry the effect.
            pass

    async def receive(
        self, identity: CaseIdentity, create_case: Callable[[], Awaitable[tuple[str, str]]],
    ) -> dict[str, str]:
        """Claim before creating; duplicate/uncertain notifications never create again."""
        claimed = False

        def claim(state: dict) -> None:
            nonlocal claimed
            claimed = False  # A CAS retry must not retain ownership of a lost claim.
            if "case" not in state["tasks"]:
                state["tasks"]["case"] = {"authority": identity.authority(), "status": "creating"}
                claimed = True

        state = await self.store.update(identity.scope, claim)
        record = state["tasks"]["case"]
        if record.get("authority") != identity.authority():
            raise PermissionError("The case does not belong to this requester and instance.")
        if not claimed:
            return record
        self.emit("case_received", {"status": "creating"})
        try:
            case_id, number = await create_case()
            if type(case_id) is not str or type(number) is not str or not _ID.fullmatch(case_id) or not _ID.fullmatch(number):
                raise ValueError("The case creation result lacks a verified reference.")
        except BaseException:
            # Even a timeout may have created the Salesforce case. Reconciliation
            # by a human or an authoritative query is required, not a retry.
            await self._mark_uncertain(identity, "creating")
            raise

        def complete(state: dict) -> None:
            record = state["tasks"].get("case")
            if record and record.get("authority") == identity.authority() and record["status"] == "creating":
                record.update(status="investigating", caseId=case_id, caseNumber=number)

        result = (await self.store.update(identity.scope, complete))["tasks"]["case"]
        if result.get("caseId") != case_id:
            raise RuntimeError("Case creation receipt could not be committed.")
        self.emit("case_registered", {"status": "investigating", "caseNumber": number})
        return result

    async def answer_delivered(
        self, identity: CaseIdentity, evidence_ids: list[str],
        deliver: Callable[[], Awaitable[str]],
    ) -> dict[str, str]:
        if not evidence_ids or len(evidence_ids) > 32 or any(not _opaque_id(ref) for ref in evidence_ids):
            raise ValueError("Verified evidence references are required before delivering a case answer.")
        claimed = False

        def claim(state: dict) -> None:
            nonlocal claimed
            claimed = False
            record = state["tasks"].get("case")
            if not record or record.get("authority") != identity.authority() or record.get("status") != "investigating":
                return
            record["status"] = "answer_delivery_pending"
            claimed = True

        result = (await self.store.update(identity.scope, claim))["tasks"].get("case")
        if not claimed or not result or result.get("authority") != identity.authority():
            raise PermissionError("Only the verified investigating case can deliver an answer.")
        try:
            message_id = await deliver()
            if not _opaque_id(message_id):
                raise ValueError("An authenticated Teams delivery receipt is required.")
        except BaseException:
            await self._mark_uncertain(identity, "answer_delivery_pending")
            raise

        def complete(state: dict) -> None:
            record = state["tasks"].get("case")
            if record and record.get("authority") == identity.authority() and record.get("status") == "answer_delivery_pending":
                record.update(status="awaiting_confirmation", evidenceIds=list(evidence_ids), answerMessageId=message_id)

        result = (await self.store.update(identity.scope, complete))["tasks"]["case"]
        if result.get("answerMessageId") != message_id:
            raise RuntimeError("The answer delivery receipt could not be committed.")
        self.emit("case_answer_delivered", {"status": "awaiting_confirmation", "caseNumber": result["caseNumber"]})
        return result

    async def close(
        self, identity: CaseIdentity, *, sender_id: str, conversation_id: str, message: str,
        close_case: Callable[[str], Awaitable[None]], read_status: Callable[[str], Awaitable[str]],
    ) -> dict[str, str]:
        """Only an explicit resolution from the bound requester claims closure."""
        if (sender_id.lower() != identity.requester_id.lower()
                or conversation_id != identity.private_conversation_id
                or not isinstance(message, str) or len(message) > 1000
                or not _CONFIRM.fullmatch(message.strip())):
            raise PermissionError("Only an explicit confirmation from the original requester can close this case.")
        claimed = False

        def claim(state: dict) -> None:
            nonlocal claimed
            claimed = False
            record = state["tasks"].get("case")
            if not record or record.get("authority") != identity.authority() or record.get("status") != "awaiting_confirmation":
                return
            record.update(status="closing", confirmation="explicit requester confirmation")
            claimed = True

        result = (await self.store.update(identity.scope, claim))["tasks"].get("case")
        if not result or result.get("authority") != identity.authority():
            raise PermissionError("The case does not belong to this requester and instance.")
        if not claimed:
            return result
        self.emit("case_closing", {"status": "closing", "caseNumber": result["caseNumber"]})
        try:
            await close_case(result["caseId"])
            if (await read_status(result["caseId"])).lower() != "closed":
                raise RuntimeError("Salesforce has not confirmed case closure.")
        except BaseException:
            await self._mark_uncertain(identity, "closing")
            raise

        def complete(state: dict) -> None:
            record = state["tasks"].get("case")
            if record and record.get("authority") == identity.authority() and record.get("status") == "closing":
                record["status"] = "closed"

        final = (await self.store.update(identity.scope, complete))["tasks"]["case"]
        if final.get("status") != "closed":
            raise RuntimeError("Case closure receipt could not be committed.")
        self.emit("case_closed", {"status": "closed", "caseNumber": final["caseNumber"]})
        return final