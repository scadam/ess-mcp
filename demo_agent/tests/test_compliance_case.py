"""Offline safety tests; these are not evidence of A365/Salesforce/Teams delivery."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from demo_agent.compliance_case import CaseIdentity, CaseWorkflow
from demo_agent.conversation_memory import SQLiteStore


TENANT = "17371818-07cb-47f2-9ca3-18f96f0125d7"
INSTANCE = "d9602248-c060-44f2-8db3-f4af2a1965b2"
MANAGER = "3ef6fe2c-3605-4f77-aeff-fb9e084e3a0d"
REQUESTER = "e4c4a045-8a73-4aad-af66-ab7f8add8b38"


class ComplianceCaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / "state.sqlite3"
        self.store = SQLiteStore(self.path)
        self.addAsyncCleanup(self.store.close)
        self.identity = CaseIdentity(TENANT, INSTANCE, MANAGER, REQUESTER, "AAMk.../AQ=", "19:private@thread.v2")
        self.events = []
        self.workflow = CaseWorkflow(self.store, lambda kind, data: self.events.append((kind, data)))

    async def test_duplicate_notification_creates_once_even_with_two_workers(self):
        calls = 0
        async def create():
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return "500000000000001", "00000001"
        a, b = await asyncio.gather(self.workflow.receive(self.identity, create),
                                    self.workflow.receive(self.identity, create))
        self.assertEqual(calls, 1)
        self.assertTrue({a["status"], b["status"]} <= {"creating", "investigating"})
        self.assertEqual((await self.workflow.receive(self.identity, create))["caseId"], "500000000000001")
        self.assertEqual(calls, 1)

    async def test_unknown_create_is_not_replayed_after_restart(self):
        calls = 0
        async def unknown():
            nonlocal calls
            calls += 1
            raise TimeoutError("Salesforce may have committed")
        with self.assertRaises(TimeoutError):
            await self.workflow.receive(self.identity, unknown)
        other = SQLiteStore(self.path)
        self.addAsyncCleanup(other.close)
        record = await CaseWorkflow(other).receive(self.identity, unknown)
        self.assertEqual(record["status"], "write_outcome_unknown")
        self.assertEqual(calls, 1)

    async def test_cross_instance_and_requester_cannot_take_over_case(self):
        await self.workflow.receive(self.identity, lambda: asyncio.sleep(0, result=("500000000000001", "00000001")))
        impostor = CaseIdentity(TENANT, INSTANCE, MANAGER, MANAGER, self.identity.message_id, self.identity.private_conversation_id)
        with self.assertRaises(PermissionError):
            await self.workflow.receive(impostor, lambda: asyncio.sleep(0, result=("500000000000002", "00000002")))
        other_instance = CaseIdentity(TENANT, MANAGER, MANAGER, REQUESTER, self.identity.message_id, self.identity.private_conversation_id)
        self.assertIsNone(await self.workflow._record(other_instance))

    async def test_closure_requires_evidence_and_original_requester_in_private_chat(self):
        await self.workflow.receive(self.identity, lambda: asyncio.sleep(0, result=("500000000000001", "00000001")))
        with self.assertRaises(ValueError):
            await self.workflow.answer_delivered(self.identity, [], lambda: asyncio.sleep(0, result="teams-message"))
        await self.workflow.answer_delivered(self.identity, ["policy-version:2026-09", "supplier/UK-team"],
                                             lambda: asyncio.sleep(0, result="teams-message"))
        calls = 0
        async def close(case_id):
            nonlocal calls
            calls += 1
            self.assertEqual(case_id, "500000000000001")
        async def read_status(_case_id):
            return "Closed"
        async def attempt(sender, chat, message):
            return await self.workflow.close(self.identity, sender_id=sender, conversation_id=chat,
                                             message=message, close_case=close, read_status=read_status)
        for sender, chat, text in ((MANAGER, self.identity.private_conversation_id, "Yes, that answers my question, please close the case"),
                                   (REQUESTER, "19:group@thread.v2", "Yes, that answers my question, please close the case"),
                                   (REQUESTER, self.identity.private_conversation_id, "Thanks!"),
                                   (REQUESTER, self.identity.private_conversation_id,
                                    "Yes, that answers my question, but can we also send the scans? Please close the case.")):
            with self.assertRaises(PermissionError):
                await attempt(sender, chat, text)
        self.assertEqual(calls, 0)
        result = await attempt(REQUESTER, self.identity.private_conversation_id,
                               "Yes, that answers my question, please close the case.")
        self.assertEqual(result["status"], "closed")
        await attempt(REQUESTER, self.identity.private_conversation_id,
                      "Yes, that answers my question, please close the case.")
        self.assertEqual(calls, 1)
        self.assertIn("case_closed", [name for name, _ in self.events])

    async def test_ambiguous_close_never_claims_closed_or_retries(self):
        await self.workflow.receive(self.identity, lambda: asyncio.sleep(0, result=("500000000000001", "00000001")))
        await self.workflow.answer_delivered(self.identity, ["nda-version-3"],
                             lambda: asyncio.sleep(0, result="teams-message"))
        calls = 0
        async def uncertain(_case_id):
            nonlocal calls
            calls += 1
            raise TimeoutError("unknown outcome")
        kwargs = dict(sender_id=REQUESTER, conversation_id=self.identity.private_conversation_id,
                      message="Yes, that resolves my question, please close my case.", close_case=uncertain,
                      read_status=lambda _id: asyncio.sleep(0, result="Closed"))
        with self.assertRaises(TimeoutError):
            await self.workflow.close(self.identity, **kwargs)
        self.assertEqual((await self.workflow.close(self.identity, **kwargs))["status"], "write_outcome_unknown")
        self.assertEqual(calls, 1)

    async def test_unverified_delivery_never_unlocks_closure(self):
        await self.workflow.receive(self.identity, lambda: asyncio.sleep(0, result=("500000000000001", "00000001")))
        with self.assertRaises(ValueError):
            await self.workflow.answer_delivered(self.identity, ["nda-version-3"],
                                                 lambda: asyncio.sleep(0, result=""))
        self.assertEqual((await self.workflow._record(self.identity))["status"], "write_outcome_unknown")
        async def unexpected(_case_id):
            self.fail("Unverified Teams answer must never close a Salesforce case")
        result = await self.workflow.close(
            self.identity, sender_id=REQUESTER, conversation_id=self.identity.private_conversation_id,
            message="Yes, that answers my question, please close the case.", close_case=unexpected,
            read_status=lambda _id: asyncio.sleep(0, result="Closed"),
        )
        self.assertEqual(result["status"], "write_outcome_unknown")