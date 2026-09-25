"""Offline coordinator tests only; no credentials, SDK, network or live-system proof.

The main agent/host runs these tests. Separate SQLiteStore instances exercise the
actual Store CAS implementation, not an in-memory replacement. Deterministic
barriers cover losing CAS candidates, cross-worker delivery, and cancellation
before/after durable commits. Backend calls are explicit, single-attempt fakes.
"""

from __future__ import annotations

import asyncio
import copy
import gzip
import hashlib
import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any

from demo_agent.compliance_service import (
    MAX_ACTIVITY_RECEIPTS,
    MAX_CASES,
    MAX_STATE_BYTES,
    MAX_TIMELINE_EVENTS,
    MAX_TURNS,
    ComplianceBinding,
    ComplianceService,
    Investigation,
    VerifiedEmail,
)
from demo_agent.conversation_memory import (
    CorruptStateError,
    SQLiteStore,
    StateTooLargeError,
    StoreUnavailableError,
)


# Fictional nonzero directory IDs. Constructing a dataclass does NOT authenticate them.
TENANT = "11111111-1111-4111-8111-111111111111"
BLUEPRINT = "22222222-2222-4222-8222-222222222222"
INSTANCE = "33333333-3333-4333-8333-333333333333"
AGENT = "44444444-4444-4444-8444-444444444444"
MANAGER = "55555555-5555-4555-8555-555555555555"
REQUESTER = "66666666-6666-4666-8666-666666666666"
OTHER = "77777777-7777-4777-8777-777777777777"
BINDING = ComplianceBinding(TENANT, BLUEPRINT, INSTANCE, AGENT, MANAGER, (REQUESTER,), ("demo/approved",))
EMAIL = VerifiedEmail("AAMk-immutable/AQ=", "email-thread-1", REQUESTER, "Seabrook disclosure", "Which approved route applies?")
EVIDENCE = [
    {"id": "approved-policy", "version": "2026-09", "source": "designated-demo-pack"},
    {"id": "uk-recipient-schedule", "version": "3", "title": "Approved UK-only team"},
]
READY = Investigation(
    "Not as originally proposed. The verified UK-only arrangement permits aggregate forecasts, not identity scans.",
    EVIDENCE, [], [], True,
)
QUESTION = Investigation(
    "The NDA covers a UK entity, not necessarily the Singapore affiliate.", EVIDENCE,
    ["Will Singapore analysts download the full pack?"], ["Recipient and data scope need verification."],
)
SECOND_QUESTION = Investigation(
    "The Singapore/full-pack route is not supported by the available approvals.", EVIDENCE,
    ["Can the verified UK-only team work with aggregate forecasts and no identity documents?"],
    ["Verify the alternative against the approved records."],
)


class Gate:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def wait(self) -> None:
        self.entered.set()
        await self.release.wait()


class FakeBackend:
    def __init__(self, results: list[Investigation] | None = None) -> None:
        self.results = list(results or [])
        self.calls: list[tuple[str, Any]] = []
        self.failures: set[str] = set()
        self.invalid: dict[str, Any] = {}
        self.gates: dict[str, Gate] = {}
        self.observer = None
        self.status = "Closed"
        self.next_case = 0
        self.next_message = 0
        self.mutate_investigation_record = False

    def count(self, name: str) -> int:
        return sum(kind == name for kind, _ in self.calls)

    async def step(self, name: str, data: Any) -> None:
        self.calls.append((name, copy.deepcopy(data)))
        if self.observer is not None:
            await self.observer(name, data)
        gate = self.gates.pop(name, None)
        if gate is not None:
            await gate.wait()
        if name in self.failures:
            raise TimeoutError("Remote outcome unknown; password=NEVER-PERSIST-THIS-ERROR")

    async def create_case(self, binding: ComplianceBinding, email: VerifiedEmail, correlation: str) -> dict:
        self.next_case += 1
        result = {"id": f"500{self.next_case:012d}", "number": f"{self.next_case:08d}"}
        await self.step("create", {"binding": binding, "email": email, "correlation": correlation})
        return self.invalid.get("create", result)

    async def ensure_private_chat(self, binding: ComplianceBinding, requester_id: str) -> str:
        await self.step("chat", {"binding": binding, "requester": requester_id})
        return self.invalid.get("chat", f"19:private-{requester_id}@thread.v2")

    async def investigate(self, binding: ComplianceBinding, record: dict, latest_reply: str) -> Investigation:
        result = self.results.pop(0) if self.results else READY
        await self.step("investigate", {"binding": binding, "record": record, "latest_reply": latest_reply})
        if self.mutate_investigation_record:
            record["caseId"] = "MODEL-CHOSEN-CASE"
            record["authority"]["requesterId"] = OTHER
            record["privateChatId"] = "19:unrelated-group@thread.v2"
            record["writes"].clear()
        return copy.deepcopy(self.invalid.get("investigate", result))

    async def send_private(self, binding: ComplianceBinding, requester_id: str, chat_id: str, text: str) -> str:
        self.next_message += 1
        message_id = f"teams-message-{self.next_message}"
        kind = "closed_delivery" if "is closed, confirmed by Salesforce." in text else "delivery"
        await self.step(kind, {"binding": binding, "requester": requester_id, "chat": chat_id, "text": text})
        return self.invalid.get(kind, message_id)

    async def update_case(self, binding: ComplianceBinding, case_id: str, comment: str, close: bool = False) -> None:
        kind = "close" if close else "update"
        await self.step(kind, {"binding": binding, "case_id": case_id, "comment": comment, "close": close})
        return self.invalid.get(kind)

    async def read_case_status(self, binding: ComplianceBinding, case_id: str) -> str:
        await self.step("read", {"binding": binding, "case_id": case_id})
        return self.invalid.get("read", self.status)


class ConversationalBackend(FakeBackend):
    """Adds the optional reply interpreter, courtesy notices and confirmation email."""

    def __init__(self, results: list[Investigation] | None = None, intents: list[str] | None = None) -> None:
        super().__init__(results)
        self.intents = list(intents or [])
        self.notices: list[str] = []

    async def interpret_reply(self, binding: ComplianceBinding, record: dict, text: str) -> str:
        await self.step("interpret", {"status": record["status"], "text": text})
        return self.intents.pop(0) if self.intents else "information"

    async def notify(self, binding: ComplianceBinding, requester_id: str, chat_id: str, text: str) -> None:
        self.notices.append(text)

    async def send_confirmation_email(self, binding: ComplianceBinding, requester_id: str, record: dict,
                                      summary: str) -> None:
        await self.step("email", {"requester": requester_id, "case": record["caseNumber"], "summary": summary})


class Rendezvous:
    def __init__(self) -> None:
        self.count = 0
        self.ready = asyncio.Event()

    async def wait(self) -> None:
        self.count += 1
        if self.count == 2:
            self.ready.set()
        await self.ready.wait()


class CollidingStore(SQLiteStore):
    def __init__(self, path: Path, rendezvous: Rendezvous) -> None:
        super().__init__(path)
        self.rendezvous = rendezvous
        self.cas_calls = 0

    async def _compare_and_swap(self, key: str, version: int | str | None, payload: bytes) -> bool:
        self.cas_calls += 1
        if self.cas_calls == 1:
            await self.rendezvous.wait()
        return await super()._compare_and_swap(key, version, payload)


class InterceptStore(SQLiteStore):
    """Pause/fail one matching CAS, optionally after it has durably committed."""

    def __init__(self, path: Path, predicate, *, after: bool = False, fail: bool = False) -> None:
        super().__init__(path)
        self.predicate = predicate
        self.after = after
        self.fail = fail
        self.gate = Gate()
        self.used = False

    async def _compare_and_swap(self, key: str, version: int | str | None, payload: bytes) -> bool:
        state = json.loads(gzip.decompress(payload))
        records = state["tasks"].get("compliance", {}).get("cases", {})
        match = not self.used and any(self.predicate(record) for record in records.values())
        if not match:
            return await super()._compare_and_swap(key, version, payload)
        self.used = True
        committed = await super()._compare_and_swap(key, version, payload) if self.after else False
        await self.gate.wait()
        if self.fail:
            raise StoreUnavailableError("Injected storage ambiguity.")
        return committed if self.after else await super()._compare_and_swap(key, version, payload)


class RefuseOutcomeStore(SQLiteStore):
    async def _compare_and_swap(self, key: str, version: int | str | None, payload: bytes) -> bool:
        state = json.loads(gzip.decompress(payload))
        for record in state["tasks"].get("compliance", {}).get("cases", {}).values():
            if (record["status"] == "write_outcome_unknown"
                    or record["writes"].get("create", {}).get("status") == "completed"):
                raise StoreUnavailableError("Outcome storage unavailable.")
        return await super()._compare_and_swap(key, version, payload)


class ComplianceBindingTests(unittest.TestCase):
    def test_directory_guids_are_nonzero_normalized_and_immutable(self) -> None:
        for field in ("tenant_id", "blueprint_id", "instance_app_id", "agentic_user_id", "manager_id"):
            for invalid in ("", "not-a-guid", "00000000-0000-0000-0000-000000000000", 1):
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    replace(BINDING, **{field: invalid})
        upper = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
        self.assertEqual(replace(BINDING, tenant_id=upper).tenant_id, upper.lower())
        with self.assertRaises(FrozenInstanceError):
            setattr(BINDING, "manager_id", OTHER)
        for invalid in ((), (REQUESTER, REQUESTER), ("00000000-0000-0000-0000-000000000000",), [REQUESTER]):
            with self.subTest(requesters=invalid), self.assertRaises(ValueError):
                replace(BINDING, requester_ids=invalid)
        with self.assertRaises(ValueError):
            replace(BINDING, evidence_paths=("https://evidence.invalid/file?sig=secret",))


class ComplianceServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "cases.sqlite3"
        self.backend = FakeBackend()
        self.gates: list[Gate] = []
        self.events: list[tuple[str, dict]] = []
        self.service = self.make_service(sink=lambda kind, data: self.events.append((kind, data)))

    async def asyncTearDown(self) -> None:
        # Assertion failures must not strand a shielded CAS behind a test barrier
        # and hang service cleanup. No test relies on wall-clock sleeps.
        for gate in self.gates:
            gate.release.set()

    def new_gate(self) -> Gate:
        gate = Gate()
        self.gates.append(gate)
        return gate

    def make_service(self, *, backend=None, bindings=(BINDING,), store=None, sink=None, path=None) -> ComplianceService:
        store = store or SQLiteStore(path or self.path)
        if isinstance(store, InterceptStore):
            self.gates.append(store.gate)
        self.addAsyncCleanup(store.close)
        service = ComplianceService(store, backend or self.backend, bindings, sink)
        self.addAsyncCleanup(service.close)
        return service

    async def case(self, service=None, binding=BINDING) -> dict:
        records = await (service or self.service).list_cases(binding.tenant_id, binding.manager_id)
        self.assertEqual(len(records), 1)
        return records[0]

    async def reply(self, text: str, activity: str = "activity-1", service=None, record=None) -> bool:
        service = service or self.service
        record = record or await self.case(service)
        return await service.handle_reply(BINDING, REQUESTER, record["privateChatId"], activity, text)

    async def ready(self, service=None) -> dict:
        record = await (service or self.service).receive_email(BINDING, EMAIL)
        self.assertEqual(record["status"], "awaiting_confirmation")
        return record

    async def test_full_two_clarification_turns_then_exact_requester_resolution(self) -> None:
        self.backend.results = [QUESTION, SECOND_QUESTION, READY]
        first = await self.service.receive_email(BINDING, EMAIL)
        number, case_id = first["caseNumber"], first["caseId"]
        self.assertEqual(first["status"], "waiting_for_requester")
        self.assertIsNone(first["resolution"])
        self.assertTrue(await self.reply(f"case #{number}: Singapore analysts would download the full pack.", "turn-1"))
        second = await self.case()
        self.assertEqual(second["status"], "waiting_for_requester")
        self.assertEqual(second["caseId"], case_id)
        peer = self.make_service()  # Restart between clarification turns.
        self.assertTrue(await self.reply(
            f"case #{number}: Use the approved UK-only team and aggregate forecasts, excluding identity documents.",
            "turn-2", peer,
        ))
        answered = await self.case(peer)
        self.assertEqual(answered["generation"], 2)
        self.assertEqual(answered["status"], "awaiting_confirmation")
        self.assertEqual(answered["resolution"]["messageId"], answered["lastDelivery"]["messageId"])
        self.assertEqual(len(answered["replyHistory"]), 2)
        self.assertEqual(len(answered["investigationHistory"]), 3)
        self.assertTrue(await self.reply(f"resolve {number}", "resolve-1", peer))
        closed = await self.case(peer)
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(closed["salesforceStatus"], "Closed")
        self.assertEqual(closed["closureReadback"]["status"], "Closed")
        self.assertEqual(closed["confirmation"]["text"], f"resolve {number}")
        self.assertEqual(closed["confirmation"]["requesterId"], REQUESTER)
        self.assertEqual(closed["confirmation"]["chatId"], first["privateChatId"])
        self.assertIsInstance(closed["confirmation"]["at"], float)
        self.assertEqual([self.backend.count(name) for name in ("create", "chat", "investigate", "update", "delivery", "close", "read", "closed_delivery")],
                         [1, 1, 3, 3, 3, 1, 1, 1])
        closing = next(data for kind, data in self.backend.calls if kind == "close")
        comment = closing["comment"]
        self.assertIn(f"(\"resolve {number}\",", comment)
        self.assertIn("not approval to transfer documents", comment)
        self.assertIn(REQUESTER, comment)
        for item in EVIDENCE:
            self.assertIn(f"- {item['id']} (version {item['version']})", comment)
        self.assertEqual(closing["case_id"], case_id)
        calls = [kind for kind, _ in self.backend.calls]
        self.assertLess(calls.index("close"), calls.index("read"))
        self.assertLess(calls.index("read"), calls.index("closed_delivery"))
        for kind, data in self.backend.calls:
            if kind in {"delivery", "closed_delivery"}:
                self.assertEqual((data["binding"], data["requester"], data["chat"]), (BINDING, REQUESTER, first["privateChatId"]))
                self.assertIn(f"Case #{number}", data["text"])

    async def test_each_external_write_observes_a_durable_unique_claim(self) -> None:
        observed: list[str] = []

        async def observe(name: str, _data: dict) -> None:
            if name in {"investigate", "read"}:
                return
            record = await self.case()
            operation = f"{name}:{record['generation']}" if name in {"update", "delivery"} else name
            write = record["writes"][operation]
            self.assertEqual(write["status"], "claimed")
            self.assertEqual(write["owner"], record["owner"])
            self.assertEqual(len(write["nonce"]), 32)
            self.assertIsNone(write["receipt"])
            self.assertTrue(all(other["status"] == "completed" for key, other in record["writes"].items() if key != operation))
            observed.append(write["nonce"])

        self.backend.observer = observe
        record = await self.ready()
        await self.reply(f"resolve {record['caseNumber']}")
        self.assertEqual(len(observed), 6)
        self.assertEqual(len(set(observed)), 6)
        stored = await self.case()
        self.assertTrue(all(write["status"] == "completed" and write["receipt"] for write in stored["writes"].values()))

    async def test_duplicate_notification_and_activity_survive_restart(self) -> None:
        record = await self.ready()
        expected_key = hashlib.sha256(json.dumps([TENANT, INSTANCE, EMAIL.message_id], separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(record["key"], expected_key)
        peer = self.make_service()
        duplicate = await peer.receive_email(BINDING, replace(EMAIL, subject="Changed notification text cannot create again"))
        self.assertEqual(duplicate["caseId"], record["caseId"])
        self.assertEqual(duplicate["email"]["subject"], EMAIL.subject)
        self.assertEqual(self.backend.count("create"), 1)
        text = f"case #{record['caseNumber']}: Please verify the currently approved version again."
        self.assertTrue(await self.reply(text, "same-activity", peer))
        count = len(self.backend.calls)
        restarted = self.make_service()
        self.assertTrue(await self.reply(text, "same-activity", restarted))
        self.assertEqual(len(self.backend.calls), count)
        await self.reply(f"resolve {record['caseNumber']}", "close-activity", restarted)
        count = len(self.backend.calls)
        self.assertTrue(await self.reply(f"resolve {record['caseNumber']}", "close-activity", peer))
        self.assertTrue(await self.reply(f"resolve {record['caseNumber']}", "another-close-activity", peer))
        self.assertEqual(len(self.backend.calls), count)

    async def test_two_workers_collide_without_stale_claim_ownership(self) -> None:
        rendezvous = Rendezvous()
        left = self.make_service(store=CollidingStore(self.path, rendezvous))
        right = self.make_service(store=CollidingStore(self.path, rendezvous))
        results = await asyncio.wait_for(asyncio.gather(left.receive_email(BINDING, EMAIL), right.receive_email(BINDING, EMAIL)), 15)
        self.assertEqual(self.backend.count("create"), 1)
        self.assertEqual(self.backend.count("delivery"), 1)
        self.assertEqual({result["key"] for result in results}, {(await self.case())["key"]})
        record = await self.case()
        args = (BINDING, REQUESTER, record["privateChatId"], "same-turn", f"case #{record['caseNumber']}: Recheck the policy.")
        self.assertEqual(await asyncio.gather(left.handle_reply(*args), right.handle_reply(*args)), [True, True])
        self.assertEqual(self.backend.count("investigate"), 2)
        args = (BINDING, REQUESTER, record["privateChatId"], "same-resolve", f"resolve {record['caseNumber']}")
        self.assertEqual(await asyncio.gather(left.handle_reply(*args), right.handle_reply(*args)), [True, True])
        self.assertEqual(self.backend.count("close"), 1)
        self.assertEqual(self.backend.count("closed_delivery"), 1)

    async def test_bad_requester_chat_and_unconfigured_binding_have_no_effect(self) -> None:
        record = await self.ready()
        count = len(self.backend.calls)
        for requester, chat in ((OTHER, record["privateChatId"]), (MANAGER, record["privateChatId"]),
                                (REQUESTER, "19:group@thread.v2"), ("not-a-guid", record["privateChatId"])):
            self.assertFalse(await self.service.handle_reply(BINDING, requester, chat, "forged", f"resolve {record['caseNumber']}"))
        with self.assertRaises(PermissionError):
            await self.service.receive_email(BINDING, replace(EMAIL, requester_id=OTHER))
        for field in ("tenant_id", "instance_app_id", "manager_id", "blueprint_id", "agentic_user_id"):
            with self.subTest(field=field), self.assertRaises(PermissionError):
                await self.service.receive_email(replace(BINDING, **{field: OTHER}), EMAIL)
        self.assertEqual(len(self.backend.calls), count)
        self.assertEqual(await self.service.list_cases(TENANT, OTHER), [])
        self.assertEqual(await self.service.list_cases(OTHER, MANAGER), [])

    async def test_manager_and_requester_rebinding_cannot_replay_immutable_email(self) -> None:
        await self.ready()
        for changed in (replace(BINDING, manager_id=OTHER), replace(BINDING, requester_ids=(REQUESTER, OTHER))):
            service = self.make_service(bindings=(changed,))
            with self.assertRaises(PermissionError):
                await service.receive_email(changed, EMAIL)
        self.assertEqual(self.backend.count("create"), 1)
        other = replace(BINDING, instance_app_id=OTHER, manager_id=OTHER, agentic_user_id=OTHER)
        fleet = self.make_service(bindings=(BINDING, other))
        await fleet.receive_email(other, EMAIL)
        own = await fleet.list_cases(TENANT, MANAGER)
        theirs = await fleet.list_cases(TENANT, OTHER)
        self.assertEqual(len(own), 1)
        self.assertEqual(len(theirs), 1)
        self.assertNotEqual(own[0]["key"], theirs[0]["key"])

    async def test_original_requester_cannot_be_replaced_even_if_both_are_allowlisted(self) -> None:
        binding = replace(BINDING, requester_ids=(REQUESTER, OTHER))
        service = self.make_service(bindings=(binding,))
        record = await service.receive_email(binding, EMAIL)
        with self.assertRaises(PermissionError):
            await service.receive_email(binding, replace(EMAIL, requester_id=OTHER))
        self.assertFalse(await service.handle_reply(binding, OTHER, record["privateChatId"], "forged-close", f"resolve {record['caseNumber']}"))
        self.assertEqual(self.backend.count("close"), 0)

    async def test_shared_private_chat_follows_the_latest_case_unless_marked(self) -> None:
        first = await self.ready()
        second = await self.service.receive_email(BINDING, replace(EMAIL, message_id="immutable-second", conversation_id="thread-second"))
        self.assertNotEqual(first["caseId"], second["caseId"])  # Every email is its own Salesforce case.
        self.assertEqual(first["privateChatId"], second["privateChatId"])
        chat = first["privateChatId"]
        count = len(self.backend.calls)
        self.assertFalse(await self.service.handle_reply(BINDING, REQUESTER, chat, "two-markers",
            f"case #{first['caseNumber']}: Also resolve case #{second['caseNumber']}"))
        self.assertFalse(await self.service.handle_reply(BINDING, REQUESTER, chat, "unknown", "case #NOT-MINE: Please close it."))
        self.assertFalse(await self.service.handle_reply(BINDING, REQUESTER, chat, "unknown-close", "resolve NOT-MINE"))
        self.assertEqual(len(self.backend.calls), count)
        self.assertTrue(await self.service.handle_reply(BINDING, REQUESTER, chat, "plain", "Please check the recipients."))
        investigated = [data for kind, data in self.backend.calls if kind == "investigate"][-1]
        self.assertEqual(investigated["record"]["caseId"], second["caseId"])  # The case last messaged about.
        self.assertTrue(await self.service.handle_reply(BINDING, REQUESTER, chat, "chosen", f"case #{first['caseNumber']}: Check the policy version."))
        investigated = [data for kind, data in self.backend.calls if kind == "investigate"][-1]
        self.assertEqual(investigated["record"]["caseId"], first["caseId"])
        self.assertFalse(await self.service.handle_reply(BINDING, REQUESTER, chat, "chosen", f"case #{second['caseNumber']}: Change the target."))
        self.assertTrue(await self.service.handle_reply(BINDING, REQUESTER, chat, "resolve-first", f"resolve {first['caseNumber']}"))
        closing = [data for kind, data in self.backend.calls if kind == "close"]
        self.assertEqual([data["case_id"] for data in closing], [first["caseId"]])

    async def test_no_evidence_versions_blockers_or_unanswered_questions_never_close(self) -> None:
        results = [
            replace(READY, evidence=[]), replace(READY, evidence=[{"id": "policy-without-version"}]),
            replace(READY, blockers=["Mandatory specialist review"]), replace(READY, questions=["Which entity?"]),
            replace(READY, resolution_ready=False), replace(READY, answer=""),
            replace(READY, evidence=[{"id": "policy", "version": "1"}, {"id": "policy", "version": "2"}]),
        ]
        for index, result in enumerate(results):
            with self.subTest(index=index):
                backend = FakeBackend([result])
                service = self.make_service(backend=backend, path=Path(self.directory.name) / f"ungrounded-{index}.sqlite3")
                record = await service.receive_email(BINDING, EMAIL)
                self.assertIsNone(record["resolution"])
                self.assertTrue(await service.handle_reply(BINDING, REQUESTER, record["privateChatId"], "resolve", f"resolve {record['caseNumber']}"))
                self.assertEqual(backend.count("close"), 0)

    async def test_thanks_ooo_disagreement_and_quoted_resolution_never_close(self) -> None:
        record = await self.ready()
        number = record["caseNumber"]
        for index, text in enumerate(("Thanks!", "Out of office until Monday", "I disagree with that answer.",
                                      "Can the Singapore team now receive identity scans?", f"please resolve {number}",
                                      f"resolve {number}\nCan we also change recipients?", f"resolve {number} ",
                                      f"case #{number}: resolve {number}")):
            self.assertTrue(await self.reply(text, f"non-resolution-{index}"))
            self.assertEqual(self.backend.count("close"), 0)
        self.assertEqual(self.backend.count("investigate"), 9)

    async def test_new_material_clears_old_authority_before_reinvestigation(self) -> None:
        record = await self.ready()
        gate = self.new_gate()
        self.backend.gates["investigate"] = gate
        self.backend.results = [SECOND_QUESTION]
        task = asyncio.create_task(self.reply(f"case #{record['caseNumber']}: New recipients now need identity scans.", "new-material"))
        await asyncio.wait_for(gate.entered.wait(), 10)
        pending = await self.case()
        self.assertIsNone(pending["resolution"])
        self.assertIsNone(pending["investigation"])
        self.assertEqual(pending["investigationHistory"][-1]["evidence"], EVIDENCE)
        self.assertTrue(await self.reply(f"resolve {record['caseNumber']}", "premature-resolve", self.make_service()))
        self.assertEqual(self.backend.count("close"), 0)
        gate.release.set()
        self.assertTrue(await task)
        self.assertEqual((await self.case())["status"], "waiting_for_requester")
        self.assertTrue(await self.reply(f"resolve {record['caseNumber']}", "premature-resolve"))
        self.assertEqual(self.backend.count("close"), 0)

    async def test_new_question_during_answer_delivery_cannot_inherit_old_receipt(self) -> None:
        record = await self.ready()
        gate = self.new_gate()
        self.backend.gates["delivery"] = gate
        task = asyncio.create_task(self.reply(f"case #{record['caseNumber']}: Verify the approved UK route.", "older-turn"))
        await asyncio.wait_for(gate.entered.wait(), 10)
        self.backend.results = [SECOND_QUESTION]
        peer = self.make_service()
        self.assertTrue(await self.reply(f"case #{record['caseNumber']}: The proposed recipients changed again.", "newer-turn", peer))
        self.assertTrue(await self.reply(f"resolve {record['caseNumber']}", "racing-resolve", peer))
        self.assertIsNone((await self.case())["resolution"])
        gate.release.set()
        await task
        final = await self.case()
        self.assertEqual(final["generation"], 2)
        self.assertEqual(final["lastDelivery"]["generation"], 2)
        self.assertEqual(final["status"], "waiting_for_requester")
        self.assertEqual(self.backend.count("close"), 0)

    async def test_queued_replies_keep_full_bounded_facts_when_a_turn_is_superseded(self) -> None:
        record = await self.ready()
        gate = self.new_gate()
        self.backend.gates["investigate"] = gate
        first = f"case #{record['caseNumber']}: " + "A" * 250 + " FIRST-FACT"
        second = f"case #{record['caseNumber']}: " + "B" * 250 + " SECOND-FACT"
        third = f"case #{record['caseNumber']}: " + "C" * 250 + " THIRD-FACT"
        task = asyncio.create_task(self.reply(first, "queued-first"))
        await asyncio.wait_for(gate.entered.wait(), 10)
        peer = self.make_service()
        self.assertTrue(await self.reply(second, "queued-second", peer))
        self.assertTrue(await self.reply(third, "queued-third", peer))
        gate.release.set()
        await task
        latest = [data for name, data in self.backend.calls if name == "investigate"][-1]
        self.assertEqual(latest["latest_reply"], third)
        self.assertEqual([reply["text"] for reply in latest["record"]["replyHistory"]], [first, second, third])
        self.assertEqual((await self.case())["lastDelivery"]["generation"], 3)
        self.assertEqual(self.backend.count("delivery"), 2)  # Initial plus newest, never obsolete answers.

    async def test_new_material_during_close_is_visible_not_a_false_resolved_answer(self) -> None:
        record = await self.ready()
        gate = self.new_gate()
        self.backend.gates["close"] = gate
        task = asyncio.create_task(self.reply(f"resolve {record['caseNumber']}", "close-started"))
        await asyncio.wait_for(gate.entered.wait(), 10)
        self.assertTrue(await self.reply(f"case #{record['caseNumber']}: A new material question.", "late-material", self.make_service()))
        gate.release.set()
        await task
        final = await self.case()
        self.assertEqual(final["salesforceStatus"], "Closed")
        self.assertEqual(final["status"], "needs_specialist_review")
        self.assertEqual(self.backend.count("closed_delivery"), 0)
        self.assertTrue(final["pendingReplies"])

    async def test_failed_or_ambiguous_writes_remain_unknown_and_never_replay(self) -> None:
        for name in ("create", "chat", "update", "delivery", "close", "closed_delivery"):
            with self.subTest(operation=name):
                backend = FakeBackend()
                path = Path(self.directory.name) / f"unknown-{name}.sqlite3"
                service = self.make_service(backend=backend, path=path)
                if name in {"close", "closed_delivery"}:
                    record = await service.receive_email(BINDING, EMAIL)
                    backend.failures.add(name)
                    with self.assertRaises(TimeoutError):
                        await service.handle_reply(BINDING, REQUESTER, record["privateChatId"], "resolve", f"resolve {record['caseNumber']}")
                else:
                    backend.failures.add(name)
                    with self.assertRaises(TimeoutError):
                        await service.receive_email(BINDING, EMAIL)
                peer = self.make_service(backend=backend, path=path)
                unknown = await self.case(peer)
                self.assertEqual(unknown["status"], "write_outcome_unknown")
                self.assertTrue(unknown["reconciliationRequired"])
                self.assertIsNone(unknown["resolution"])
                self.assertNotIn("NEVER-PERSIST-THIS-ERROR", json.dumps(unknown))
                before = len(backend.calls)
                await peer.receive_email(BINDING, EMAIL)
                if unknown["privateChatId"]:
                    await peer.handle_reply(BINDING, REQUESTER, unknown["privateChatId"], "retry-resolve", f"resolve {unknown['caseNumber']}")
                    await peer.handle_reply(BINDING, REQUESTER, unknown["privateChatId"], "retry-new", "Investigate again.")
                self.assertEqual(len(backend.calls), before)
                self.assertEqual(backend.count(name), 1)

    async def test_malformed_write_receipts_are_unknown_not_success(self) -> None:
        for index, (name, invalid) in enumerate((("create", {}), ("create", {"id": "chosen", "number": "bad number"}),
                                                ("chat", ""), ("delivery", ""), ("update", {"error": "denied"}))):
            with self.subTest(operation=name, invalid=invalid):
                backend = FakeBackend()
                backend.invalid[name] = invalid
                service = self.make_service(backend=backend, path=Path(self.directory.name) / f"receipt-{index}.sqlite3")
                with self.assertRaises(ValueError):
                    await service.receive_email(BINDING, EMAIL)
                record = await self.case(service)
                self.assertEqual(record["status"], "write_outcome_unknown")
                self.assertIsNone(record["resolution"])
                before = len(backend.calls)
                await service.receive_email(BINDING, EMAIL)
                self.assertEqual(len(backend.calls), before)

    async def test_salesforce_must_read_back_exact_closed(self) -> None:
        for index, status in enumerate(("Working", "closed", "Closed ", "")):
            with self.subTest(status=status):
                backend = FakeBackend()
                backend.status = status
                service = self.make_service(backend=backend, path=Path(self.directory.name) / f"status-{index}.sqlite3")
                record = await service.receive_email(BINDING, EMAIL)
                with self.assertRaises((RuntimeError, ValueError)):
                    await service.handle_reply(BINDING, REQUESTER, record["privateChatId"], "resolve", f"resolve {record['caseNumber']}")
                final = await self.case(service)
                self.assertEqual(final["status"], "write_outcome_unknown")
                self.assertNotEqual(final["salesforceStatus"], "Closed")
                self.assertEqual(backend.count("closed_delivery"), 0)
                self.assertEqual(final["writes"]["close"]["status"], "completed")

    async def test_readback_failure_never_retries_close(self) -> None:
        record = await self.ready()
        self.backend.failures.add("read")
        with self.assertRaises(TimeoutError):
            await self.reply(f"resolve {record['caseNumber']}")
        self.assertTrue(await self.reply(f"resolve {record['caseNumber']}", "resolve-again", self.make_service()))
        self.assertEqual(self.backend.count("close"), 1)
        self.assertEqual(self.backend.count("read"), 1)
        self.assertEqual(self.backend.count("closed_delivery"), 0)

    async def test_emission_failure_never_releases_claim_or_replays_effect(self) -> None:
        def broken_sink(_kind: str, _data: dict) -> None:
            raise RuntimeError("Telemetry unavailable")

        service = self.make_service(sink=broken_sink)
        record = await self.ready(service)
        await self.reply(f"resolve {record['caseNumber']}", service=service)
        before = len(self.backend.calls)
        peer = self.make_service()
        await peer.receive_email(BINDING, EMAIL)
        await self.reply(f"resolve {record['caseNumber']}", "repeat", peer)
        self.assertEqual(len(self.backend.calls), before)
        self.assertEqual((await self.case(peer))["status"], "closed")

    async def test_evidence_projection_scrubbing_and_detached_backend_input(self) -> None:
        self.backend.results = [replace(READY, evidence=[{
            "id": "approved-policy", "version": "v7", "body": "FULL-DOCUMENT-MUST-NOT-PERSIST",
            "content": "PRIVATE-DOCUMENT", "caseId": "MODEL-CASE", "requesterId": OTHER,
            "url": "https://user:password@evidence.invalid/policy?sig=SIGNED-SECRET#fragment",
        }])]
        self.backend.mutate_investigation_record = True
        email = replace(EMAIL, body="Question. Bearer TOP-SECRET password=HUSH https://docs.invalid/file?sig=SAS-SECRET")
        record = await self.service.receive_email(BINDING, email)
        raw = json.dumps(record)
        for secret in ("TOP-SECRET", "HUSH", "SIGNED-SECRET", "SAS-SECRET", "FULL-DOCUMENT-MUST-NOT-PERSIST", "PRIVATE-DOCUMENT", "MODEL-CHOSEN-CASE"):
            self.assertNotIn(secret, raw)
        self.assertEqual(record["investigation"]["evidence"], [{"id": "approved-policy", "version": "v7", "url": "https://evidence.invalid/policy"}])
        self.assertEqual(record["authority"]["requesterId"], REQUESTER)
        self.assertEqual(record["caseId"], "500000000000001")
        self.assertIsNone(record["resolution"])  # Redacted input cannot authorize automatic resolution.
        for kind, data in self.backend.calls:
            if kind == "update":
                self.assertEqual(data["case_id"], "500000000000001")
        view = await self.case()
        view["authority"]["requesterId"] = OTHER
        self.assertEqual((await self.case())["authority"]["requesterId"], REQUESTER)

    async def test_investigation_failure_has_no_identity_fallback_or_delivery(self) -> None:
        self.backend.failures.add("investigate")
        with self.assertRaises(TimeoutError):
            await self.service.receive_email(BINDING, EMAIL)
        record = await self.case()
        self.assertEqual(record["status"], "needs_specialist_review")
        self.assertFalse(record["suspended"])  # A later reply retries rather than stranding the case.
        self.assertIsNone(record["owner"])
        self.assertEqual([kind for kind, _ in self.backend.calls], ["create", "investigate", "investigate"])
        await self.make_service().receive_email(BINDING, EMAIL)
        self.assertEqual(self.backend.count("investigate"), 2)

    async def test_clarify_then_answer_then_natural_confirmation_emails_and_closes(self) -> None:
        backend = ConversationalBackend([QUESTION, READY], intents=["information", "confirm_with_email"])
        service = self.make_service(backend=backend)
        first = await service.receive_email(BINDING, EMAIL)
        self.assertEqual(first["status"], "waiting_for_requester")
        opening = [data["text"] for kind, data in backend.calls if kind == "delivery"][0]
        self.assertIn("I've opened this case", opening)
        self.assertIn("1. Will Singapore analysts download the full pack?", opening)
        self.assertNotIn("Recipient and data scope need verification", opening)  # Internal checks stay internal.
        chat = first["privateChatId"]
        self.assertTrue(await service.handle_reply(BINDING, REQUESTER, chat, "turn-1", "They would download it themselves."))
        self.assertEqual(backend.notices, ["Thanks, let me check that against the records."])
        answer = [data["text"] for kind, data in backend.calls if kind == "delivery"][-1]
        self.assertIn(READY.answer, answer)
        self.assertIn("Does this answer your question?", answer)
        self.assertEqual((await self.case(service))["status"], "awaiting_confirmation")
        self.assertTrue(await service.handle_reply(BINDING, REQUESTER, chat, "turn-2", "Yes, that answers it. Email me please."))
        closed = await self.case(service)
        self.assertEqual((closed["status"], closed["salesforceStatus"], closed["confirmationEmail"]), ("closed", "Closed", "sent"))
        emailed = next(data for kind, data in backend.calls if kind == "email")
        self.assertEqual((emailed["requester"], emailed["case"]), (REQUESTER, first["caseNumber"]))
        self.assertIn(READY.answer, emailed["summary"])
        calls = [kind for kind, _ in backend.calls]
        self.assertLess(calls.index("read"), calls.index("email"))  # Only a verified close is confirmed by email.
        notice = next(data["text"] for kind, data in backend.calls if kind == "closed_delivery")
        self.assertIn("I've emailed you a confirmation", notice)
        comment = next(data for kind, data in backend.calls if kind == "close")["comment"]
        self.assertIn("Confirmation email: requested", comment)

    async def test_small_talk_never_closes_and_declining_email_summarises_in_chat(self) -> None:
        backend = ConversationalBackend(intents=["chat", "confirm_without_email"])
        service = self.make_service(backend=backend)
        record = await service.receive_email(BINDING, EMAIL)
        chat = record["privateChatId"]
        self.assertTrue(await service.handle_reply(BINDING, REQUESTER, chat, "thanks", "Thanks!"))
        self.assertEqual((backend.count("close"), backend.count("investigate")), (0, 1))  # No re-investigation either.
        self.assertIn("still open", backend.notices[-1])
        self.assertEqual((await self.case(service))["status"], "awaiting_confirmation")
        self.assertTrue(await service.handle_reply(BINDING, REQUESTER, chat, "done", "That answers it, no need for an email."))
        closed = await self.case(service)
        self.assertEqual((closed["status"], closed["confirmationEmail"]), ("closed", "declined"))
        self.assertEqual(backend.count("email"), 0)
        notice = next(data["text"] for kind, data in backend.calls if kind == "closed_delivery")
        self.assertIn("Here's a summary for your records", notice)
        self.assertIn(READY.answer, notice)

    async def test_early_confirmation_is_new_material_and_a_failed_email_falls_back_to_chat(self) -> None:
        backend = ConversationalBackend([QUESTION, READY], intents=["confirm_with_email", "confirm_with_email"])
        service = self.make_service(backend=backend)
        first = await service.receive_email(BINDING, EMAIL)
        chat = first["privateChatId"]
        self.assertTrue(await service.handle_reply(BINDING, REQUESTER, chat, "early", "Yes please"))
        self.assertEqual((backend.count("close"), backend.count("investigate")), (0, 2))
        backend.failures.add("email")
        self.assertTrue(await service.handle_reply(BINDING, REQUESTER, chat, "confirm", "Yes, email me"))
        closed = await self.case(service)
        self.assertEqual((closed["status"], closed["confirmationEmail"]), ("closed", "failed"))
        notice = next(data["text"] for kind, data in backend.calls if kind == "closed_delivery")
        self.assertIn("couldn't send the confirmation email", notice)
        self.assertIn(READY.answer, notice)

    async def test_capacity_never_evicts_active_uncertain_or_closed_cases(self) -> None:
        record = await self.ready()
        closed = await self.service.receive_email(BINDING, replace(EMAIL, message_id="closed-capacity-fixture"))
        await self.reply(f"resolve {closed['caseNumber']}", "close-capacity-fixture", record=closed)
        scope = ComplianceService._scope(BINDING)

        def fill(state: dict) -> None:
            cases = state["tasks"]["compliance"]["cases"]
            for index in range(2, MAX_CASES):
                item = copy.deepcopy(record)
                message_id = f"seed-message-{index}"
                key = hashlib.sha256(json.dumps([TENANT, INSTANCE, message_id], separators=(",", ":")).encode()).hexdigest()
                item["key"], item["email"]["messageId"] = key, message_id
                item["caseId"], item["caseNumber"] = f"seed-{index}", f"seed-{index}"
                item["writes"]["create"]["receipt"] = {"id": item["caseId"], "number": item["caseNumber"]}
                item["status"] = ("awaiting_confirmation", "write_outcome_unknown")[index % 2]
                cases[key] = item

        await self.service.store.update(scope, fill)
        before = len(self.backend.calls)
        with self.assertRaisesRegex(RuntimeError, "capacity"):
            await self.service.receive_email(BINDING, replace(EMAIL, message_id="case-101"))
        self.assertEqual(len(await self.service.list_cases(TENANT, MANAGER)), MAX_CASES)
        self.assertEqual(len(self.backend.calls), before)
        await self.service.receive_email(BINDING, EMAIL)  # An admitted duplicate still works at capacity.
        self.assertEqual(len(self.backend.calls), before)

    async def test_timeline_is_bounded_without_pruning_activity_or_write_receipts(self) -> None:
        record = await self.ready()
        for index in range(9):
            await self.reply(f"case #{record['caseNumber']}: Recheck version {index}.", f"turn-{index}")
        final = await self.case()
        self.assertEqual(len(final["timeline"]), MAX_TIMELINE_EVENTS)
        self.assertEqual(len(final["activities"]), 9)
        self.assertEqual(len(final["writes"]), 22)
        self.assertEqual(final["writes"]["create"]["status"], "completed")
        self.assertLess(len(json.dumps(final).encode()), MAX_STATE_BYTES)
        before = len(self.backend.calls)
        await self.reply(f"case #{record['caseNumber']}: Recheck version 0.", "turn-0")
        self.assertEqual(len(self.backend.calls), before)

    async def test_turn_and_activity_capacity_fail_closed_without_erasing_receipts(self) -> None:
        record = await self.ready()
        scope = ComplianceService._scope(BINDING)

        def fill(state: dict) -> None:
            current = state["tasks"]["compliance"]["cases"][record["key"]]
            current["generation"] = MAX_TURNS - 1
            current["activities"] = [hashlib.sha256(f"seen-{index}".encode()).hexdigest() for index in range(MAX_ACTIVITY_RECEIPTS)]

        await self.service.store.update(scope, fill)
        before = len(self.backend.calls)
        self.assertTrue(await self.reply("New material that cannot be admitted.", "over-capacity"))
        final = await self.case()
        self.assertTrue(final["suspended"])
        self.assertIsNone(final["resolution"])
        self.assertEqual(len(final["activities"]), MAX_ACTIVITY_RECEIPTS)
        self.assertEqual(len(self.backend.calls), before)

    async def test_one_megabyte_cap_even_when_store_allows_more(self) -> None:
        generous = SQLiteStore(self.path, max_uncompressed_bytes=2 * MAX_STATE_BYTES)
        service = self.make_service(store=generous)
        record = await self.ready(service)

        def oversized(state: dict) -> None:
            state["tasks"]["compliance"]["cases"][record["key"]]["unexpectedDocument"] = "x" * MAX_STATE_BYTES

        await generous.update(ComplianceService._scope(BINDING), oversized)
        before = len(self.backend.calls)
        with self.assertRaises(StateTooLargeError):
            await service.receive_email(BINDING, EMAIL)
        self.assertEqual(len(self.backend.calls), before)

    async def test_corrupt_case_scope_fails_closed(self) -> None:
        record = await self.ready()

        def corrupt(state: dict) -> None:
            state["tasks"]["compliance"]["cases"][record["key"]]["authority"]["managerId"] = OTHER

        await self.service.store.update(ComplianceService._scope(BINDING), corrupt)
        before = len(self.backend.calls)
        with self.assertRaises(CorruptStateError):
            await self.service.receive_email(BINDING, EMAIL)
        self.assertEqual(len(self.backend.calls), before)

    async def test_persisted_target_cannot_disagree_with_create_or_chat_receipt(self) -> None:
        record = await self.ready()
        for field, replacement in (("caseId", "ANOTHER-CASE"), ("caseNumber", "ANOTHER-NUMBER"), ("privateChatId", "19:other-chat")):
            with self.subTest(field=field):
                def tamper(state: dict) -> None:
                    state["tasks"]["compliance"]["cases"][record["key"]][field] = replacement

                await self.service.store.update(ComplianceService._scope(BINDING), tamper)
                before = len(self.backend.calls)
                with self.assertRaises(CorruptStateError):
                    await self.service.handle_reply(BINDING, REQUESTER, record["privateChatId"], "forged-target", f"resolve {record['caseNumber']}")
                self.assertEqual(len(self.backend.calls), before)

                def restore(state: dict) -> None:
                    state["tasks"]["compliance"]["cases"][record["key"]][field] = record[field]

                await self.service.store.update(ComplianceService._scope(BINDING), restore)

    async def test_dedup_is_explicitly_bounded_by_store_retention(self) -> None:
        clock = [1_800_000_000.0]
        store = SQLiteStore(self.path, ttl_seconds=60, clock=lambda: clock[0])
        service = self.make_service(store=store)
        await self.ready(service)
        self.assertEqual(service.idempotency_window_seconds, 60)
        clock[0] += 61
        self.assertEqual(await service.list_cases(TENANT, MANAGER), [])
        # The HOST must reject this now-stale email; intentionally do not redeliver
        # it and falsely assert infinite deduplication from an expired Store.
        self.assertEqual(self.backend.count("create"), 1)

    async def test_cancelled_claim_is_shielded_and_drained_before_unknown_marker(self) -> None:
        store = InterceptStore(self.path, lambda record: record["writes"].get("create", {}).get("status") == "claimed", after=True)
        service = self.make_service(store=store)
        task = asyncio.create_task(service.receive_email(BINDING, EMAIL))
        await asyncio.wait_for(store.gate.entered.wait(), 10)
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        peer = self.make_service()
        duplicate = await peer.receive_email(BINDING, EMAIL)
        self.assertEqual(duplicate["status"], "write_outcome_unknown")
        self.assertEqual(self.backend.count("create"), 0)
        task.cancel()  # A second cancellation must not abandon the CAS task.
        store.gate.release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        final = await self.case(peer)
        self.assertEqual(final["writes"]["create"]["status"], "unknown")
        await peer.receive_email(BINDING, EMAIL)
        self.assertEqual(self.backend.count("create"), 0)
        self.assertFalse(service._storage)

    async def test_cancelled_completion_preserves_receipt_but_never_continues_effects(self) -> None:
        store = InterceptStore(self.path, lambda record: record["writes"].get("create", {}).get("status") == "completed", after=True)
        service = self.make_service(store=store)
        task = asyncio.create_task(service.receive_email(BINDING, EMAIL))
        await asyncio.wait_for(store.gate.entered.wait(), 10)
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        store.gate.release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        peer = self.make_service()
        record = await peer.receive_email(BINDING, EMAIL)
        self.assertEqual(record["status"], "write_outcome_unknown")
        self.assertEqual(record["writes"]["create"]["status"], "completed")
        self.assertEqual(record["writes"]["create"]["receipt"]["id"], "500000000000001")
        self.assertEqual([kind for kind, _ in self.backend.calls], ["create"])

    async def test_receipt_is_durable_before_registered_state_or_event(self) -> None:
        store = InterceptStore(self.path, lambda record: record["writes"].get("create", {}).get("status") == "completed", after=True)
        events: list[str] = []
        service = self.make_service(store=store, sink=lambda kind, _data: events.append(kind))
        task = asyncio.create_task(service.receive_email(BINDING, EMAIL))
        await asyncio.wait_for(store.gate.entered.wait(), 10)
        record = await self.case(self.make_service())
        self.assertEqual(record["writes"]["create"]["status"], "completed")
        self.assertEqual(record["caseId"], "")
        self.assertEqual(record["status"], "creating")
        self.assertNotIn("case_registered", events)
        self.assertEqual(self.backend.count("chat"), 0)
        store.gate.release.set()
        await task
        self.assertIn("case_registered", events)

    async def test_cancellation_during_delivery_or_close_never_replays(self) -> None:
        for operation in ("delivery", "close"):
            with self.subTest(operation=operation):
                path = Path(self.directory.name) / f"cancel-{operation}.sqlite3"
                backend = FakeBackend()
                service = self.make_service(path=path, backend=backend)
                record = await service.receive_email(BINDING, EMAIL)
                gate = self.new_gate()
                backend.gates[operation] = gate
                text = f"resolve {record['caseNumber']}" if operation == "close" else f"case #{record['caseNumber']}: Verify again."
                task = asyncio.create_task(service.handle_reply(BINDING, REQUESTER, record["privateChatId"], "interrupted", text))
                await asyncio.wait_for(gate.entered.wait(), 10)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                peer = self.make_service(path=path, backend=backend)
                final = await self.case(peer)
                self.assertEqual(final["status"], "write_outcome_unknown")
                self.assertIsNone(final["resolution"])
                before = len(backend.calls)
                await peer.receive_email(BINDING, EMAIL)
                await peer.handle_reply(BINDING, REQUESTER, record["privateChatId"], "interrupted", text)
                await peer.handle_reply(BINDING, REQUESTER, record["privateChatId"], "another-resolve", f"resolve {record['caseNumber']}")
                self.assertEqual(len(backend.calls), before)
                self.assertEqual(backend.count("read"), 0)

    async def test_repeated_cancellation_during_unknown_storage_is_drained(self) -> None:
        store = InterceptStore(self.path, lambda record: record["status"] == "write_outcome_unknown")
        service = self.make_service(store=store)
        external = self.new_gate()
        self.backend.gates["create"] = external
        task = asyncio.create_task(service.receive_email(BINDING, EMAIL))
        await asyncio.wait_for(external.entered.wait(), 10)
        task.cancel()
        await asyncio.wait_for(store.gate.entered.wait(), 10)
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        store.gate.release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual((await self.case())["writes"]["create"]["status"], "unknown")
        await self.make_service().receive_email(BINDING, EMAIL)
        self.assertEqual(self.backend.count("create"), 1)
        self.assertEqual(self.backend.count("chat"), 0)

    async def test_storage_error_after_commit_never_replays_external_write(self) -> None:
        for index, phase in enumerate(("claimed", "completed")):
            with self.subTest(phase=phase):
                path = Path(self.directory.name) / f"storage-{phase}.sqlite3"
                backend = FakeBackend()
                store = InterceptStore(path, lambda record, phase=phase: record["writes"].get("create", {}).get("status") == phase,
                                       after=True, fail=True)
                store.gate.release.set()
                service = self.make_service(store=store, backend=backend)
                with self.assertRaises(StoreUnavailableError):
                    await service.receive_email(BINDING, EMAIL)
                peer = self.make_service(path=path, backend=backend)
                record = await peer.receive_email(BINDING, EMAIL)
                self.assertEqual(record["status"], "write_outcome_unknown")
                self.assertEqual(backend.count("create"), index)
                self.assertEqual(backend.count("chat"), 0)

    async def test_failed_outcome_and_unknown_marker_storage_leave_nonreplayable_claim(self) -> None:
        service = self.make_service(store=RefuseOutcomeStore(self.path))
        with self.assertRaises(StoreUnavailableError):
            await service.receive_email(BINDING, EMAIL)
        peer = self.make_service()
        record = await peer.receive_email(BINDING, EMAIL)
        self.assertEqual(record["writes"]["create"]["status"], "claimed")
        self.assertEqual(record["status"], "write_outcome_unknown")
        self.assertTrue(record["reconciliationRequired"])
        self.assertEqual(self.backend.count("create"), 1)
        self.assertEqual(self.backend.count("chat"), 0)

    async def test_close_cancels_and_drains_without_external_cleanup_or_store_ownership(self) -> None:
        gate = self.new_gate()
        self.backend.gates["create"] = gate

        async def nested_read(_name: str, _data: dict) -> None:
            await self.case()  # A nested public read must not unregister the owning call.

        self.backend.observer = nested_read
        task = asyncio.create_task(self.service.receive_email(BINDING, EMAIL))
        await asyncio.wait_for(gate.entered.wait(), 10)
        await self.service.close()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual([kind for kind, _ in self.backend.calls], ["create"])
        await self.service.close()
        state = await self.service.store.read(ComplianceService._scope(BINDING))
        record = next(iter(state["tasks"]["compliance"]["cases"].values()))
        self.assertEqual(record["writes"]["create"]["status"], "unknown")
        self.assertFalse(self.service._storage)
        with self.assertRaisesRegex(RuntimeError, "closed"):
            await self.service.receive_email(BINDING, EMAIL)


if __name__ == "__main__":
    unittest.main()