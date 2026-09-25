"""Offline tests for the Compliance Partner host wiring; no network, SDK or live systems."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from demo_agent.compliance_backend import ComplianceAuthorizationError, LiveComplianceBackend
from demo_agent.compliance_host import ComplianceHost, load_bindings
from demo_agent.compliance_service import ComplianceBinding
from demo_agent.conversation_memory import SQLiteStore

TENANT = "11111111-1111-4111-8111-111111111111"
BLUEPRINT = "22222222-2222-4222-8222-222222222222"
INSTANCE = "33333333-3333-4333-8333-333333333333"
AGENT = "44444444-4444-4444-8444-444444444444"
MANAGER = "55555555-5555-4555-8555-555555555555"
REQUESTER = "66666666-6666-4666-8666-666666666666"
OTHER = "77777777-7777-4777-8777-777777777777"
CONFIG = json.dumps([{
    "name": "Compliance Partner", "instanceAppId": INSTANCE, "agenticUserId": AGENT,
    "managerId": MANAGER, "requesterIds": [REQUESTER], "evidencePaths": [],
}])


class _Connections:
    def get_default_connection(self):  # pragma: no cover - never reached offline
        raise AssertionError("No token exchange in offline tests.")


class ComplianceHostTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.runs: dict[str, dict] = {}
        self.events: list[tuple[str, str, dict]] = []
        self.states: list[tuple[str, str, str]] = []
        self.spawned: list = []

        def ensure_run(run_id, binding, name, title):
            self.runs.setdefault(run_id, {"binding": binding, "name": name, "title": title})

        def spawn(coroutine):
            self.spawned.append(coroutine)
            return None

        self.host = ComplianceHost(
            bindings=load_bindings(CONFIG, TENANT, BLUEPRINT),
            store=SQLiteStore(str(Path(self.temp.name) / "state.db")),
            connection_manager=_Connections(), salesforce_url="https://salesforce.example/salesforce/mcp",
            complete=lambda _instructions, _prompt: None, instance_enabled=lambda _binding: None, ensure_run=ensure_run,
            publish=lambda run_id, kind, data: self.events.append((run_id, kind, data)),
            set_state=lambda run_id, status, text: self.states.append((run_id, status, text)),
            spawn=spawn,
        )

    async def asyncTearDown(self) -> None:
        for coroutine in self.spawned:
            coroutine.close()
        await self.host.close()
        self.temp.cleanup()

    def activity(self, *, sender=REQUESTER, kind="personal", app=INSTANCE, user=AGENT):
        return SimpleNamespace(activity={
            "id": "1790000000001", "recipient": {"agenticAppId": app, "agenticUserId": user},
            "from": {"aadObjectId": sender}, "conversation": {"conversationType": kind, "id": "19:private@unq.gbl.spaces"},
        })

    def test_bindings_take_tenant_and_blueprint_from_host_configuration(self) -> None:
        ((binding, name),) = load_bindings(CONFIG, TENANT, BLUEPRINT)
        self.assertEqual((binding.tenant_id, binding.blueprint_id, name), (TENANT, BLUEPRINT, "Compliance Partner"))
        self.assertEqual(load_bindings("", TENANT, BLUEPRINT), ())
        forged = json.loads(CONFIG)
        forged[0]["tenantId"] = OTHER
        for raw in (json.dumps(forged), json.dumps(json.loads(CONFIG) * 2), "{}"):
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                load_bindings(raw, TENANT, BLUEPRINT)

    def test_only_the_exact_configured_instance_and_agentic_user_match(self) -> None:
        self.assertIsNotNone(self.host.binding_for(self.activity().activity))
        self.assertIsNone(self.host.binding_for(self.activity(app=OTHER).activity))
        self.assertIsNone(self.host.binding_for(self.activity(user=OTHER).activity))
        self.assertIsNone(self.host.binding_for({"recipient": {}}))

    async def test_replies_route_only_for_the_requesters_open_private_case_chat(self) -> None:
        cases = [{"key": "a" * 64, "privateChatId": "19:private@unq.gbl.spaces",
                  "authority": {"instanceAppId": INSTANCE, "requesterId": REQUESTER}}]

        async def list_cases(_tenant, _manager):
            return cases

        self.host.service.list_cases = list_cases
        self.assertFalse(await self.host.try_reply(self.activity(kind="groupChat")))
        self.assertFalse(await self.host.try_reply(self.activity(sender=OTHER)))
        self.assertFalse(await self.host.try_reply(self.activity(app=OTHER)))
        self.assertEqual(self.spawned, [])
        self.assertTrue(await self.host.try_reply(self.activity()))
        self.assertEqual(len(self.spawned), 1)
        cases[0]["privateChatId"] = "19:another@unq.gbl.spaces"
        self.assertFalse(await self.host.try_reply(self.activity()))
        cases[0].update(privateChatId="19:private@unq.gbl.spaces", status="closed", salesforceStatus="Closed")
        self.assertFalse(await self.host.try_reply(self.activity()))  # A closed case hands the chat back.

    async def test_a_rejected_email_is_narrated_without_failing_the_sdk_turn(self) -> None:
        narrated: list[tuple[str, str]] = []

        async def reject(*_args):
            raise ComplianceAuthorizationError("The email sender is not exactly one configured requester.")

        self.host.live.email_from_activity = reject
        self.host._activity = lambda _binding, category, title, **_details: narrated.append((category, title))
        context = SimpleNamespace(activity={
            "recipient": {"agenticAppId": INSTANCE, "agenticUserId": AGENT},
            "from": {"aadObjectId": REQUESTER, "name": "Wonda Howard"}, "entities": [],
        })
        await self.host.on_email(context)
        self.assertEqual(self.spawned, [])
        self.assertEqual(narrated, [("issue", "Couldn't accept an email from Wonda Howard")])

    async def test_demo_case_is_only_for_a_bound_requester_and_uses_the_real_intake(self) -> None:
        for instance, requester in ((OTHER, REQUESTER), (INSTANCE, OTHER)):
            with self.subTest(instance=instance, requester=requester), self.assertRaises(PermissionError):
                await self.host.start_demo_case(instance, requester, "Operator")
        self.assertEqual(self.spawned, [])
        received: list = []

        async def receive_email(binding, email):
            received.append((binding, email))

        self.host.service.receive_email = receive_email
        key = await self.host.start_demo_case(INSTANCE, REQUESTER, "Megan Bowen")
        self.assertEqual(list(self.runs), [ComplianceHost.run_id(key)])
        self.assertEqual(len(self.spawned), 1)
        await self.spawned.pop()
        ((binding, email),) = received
        self.assertEqual((binding.instance_app_id, email.requester_id), (INSTANCE, REQUESTER))
        self.assertTrue(email.subject.startswith("[Demo] ") and email.message_id.startswith("demo-"))

    def test_case_events_project_into_one_operator_run(self) -> None:
        key = "b" * 64
        base = {"tenantId": TENANT, "instanceAppId": INSTANCE, "caseKey": key, "caseNumber": "00001027", "sequence": 1}
        self.host._sink("case_registered", {**base, "status": "investigating"})
        self.host._sink("case_answer_delivered", {**base, "status": "awaiting_confirmation"})
        self.host._sink("case_closure_notice_recorded", {**base, "status": "closed"})
        run_id = ComplianceHost.run_id(key)
        self.assertEqual(list(self.runs), [run_id])
        self.assertEqual([state[1] for state in self.states], ["running", "waiting", "complete"])
        self.assertIn("00001027", self.states[0][2])
        self.assertTrue(any(kind == "result" and "explicit confirmation" in data["content"]
                            for _run, kind, data in self.events))
        self.host._sink("case_registered", {**base, "instanceAppId": OTHER, "status": "investigating"})
        self.assertEqual(len(self.states), 3)

    async def test_salesforce_calls_are_limited_to_the_case_workflow(self) -> None:
        binding = self.host.bindings()[0][0]
        with self.assertRaises(PermissionError):
            await self.host._salesforce_call(binding, "list_accounts", {})

    async def test_email_is_declined_and_narrated_when_the_instance_is_not_approved(self) -> None:
        narrated: list[tuple[str, str]] = []

        def revoked(_binding):
            raise PermissionError("Compliance case work is not approved for this instance.")

        self.host._instance_enabled = revoked
        self.host._activity = lambda _binding, category, title, **_details: narrated.append((category, title))
        context = SimpleNamespace(activity={
            "recipient": {"agenticAppId": INSTANCE, "agenticUserId": AGENT},
            "from": {"aadObjectId": REQUESTER, "name": "Wonda Howard"},
        })
        await self.host.on_email(context)
        self.assertEqual(self.spawned, [])
        self.assertEqual(self.runs, {})
        self.assertEqual(narrated[0][0], "policy")
        self.assertIn("Wonda Howard", narrated[0][1])

    async def test_interactions_are_logged_as_completed_tasks_on_the_bound_case(self) -> None:
        binding = self.host.bindings()[0][0]
        key = "c" * 64
        calls: list[tuple[str, dict]] = []
        narrated: list[tuple[str, str]] = []

        async def salesforce(_binding, tool, args):
            calls.append((tool, args))
            return SimpleNamespace(structuredContent={"created": len(calls) == 1}, isError=False)

        self.host._salesforce_call = salesforce
        self.host._activity = lambda _binding, category, title, **_details: narrated.append((category, title))
        self.host._case_refs[key] = ("500d200003TESAMAA5", "00001070")
        self.host._log_case_task(binding, key, "Teams message to the requester", "password=hunter2 The route is approved.")
        self.host._log_case_task(binding, key, "Teams reply from the requester", "Thanks")
        await asyncio.gather(*self.host._log_tasks)
        self.assertEqual([tool for tool, _ in calls], ["create_task", "create_task"])
        args = calls[0][1]
        self.assertEqual((args["what_id"], args["status"]), ("500d200003TESAMAA5", "Completed"))
        self.assertTrue(args["subject"].startswith("Case #00001070: Teams message"))
        self.assertNotIn("hunter2", args["description"])
        self.assertEqual(narrated, [("issue", "Couldn't log an interaction on the Salesforce case")])


class EmailIntakeTests(unittest.IsolatedAsyncioTestCase):
    """Agent 365 email notifications can omit the directory sender; the mailbox record decides."""

    def setUp(self) -> None:
        self.binding = ComplianceBinding(TENANT, BLUEPRINT, INSTANCE, AGENT, MANAGER, (REQUESTER, OTHER))
        self.backend = LiveComplianceBackend(_Connections(), self._unused, lambda: None, lambda _binding: True)
        self.users = {REQUESTER: {"id": REQUESTER, "mail": "megan@contoso.test", "userPrincipalName": "megan@contoso.test"},
                      OTHER: {"id": OTHER, "mail": "wonda@contoso.test", "userPrincipalName": "wonda@contoso.test"}}
        self.message = {
            "id": "AAMk-immutable", "conversationId": "thread-1", "isDraft": False,
            "receivedDateTime": datetime.now(timezone.utc).isoformat(),
            "from": {"emailAddress": {"address": "Megan@Contoso.test"}},
            "toRecipients": [{"emailAddress": {"address": "agent@contoso.test"}}],
            "subject": "Project Seabrook", "body": {"contentType": "text", "content": "Can we share the pack?"},
        }
        me = {"id": AGENT, "accountEnabled": True, "mail": "agent@contoso.test", "userPrincipalName": "agent@contoso.test"}

        @asynccontextmanager
        async def graph(_binding):
            yield object(), me

        async def graph_get(_binding, _client, path, *, immutable=False):
            return self.message if path.startswith("/me/messages/") else self.users[path.split("/")[2].split("?")[0]]

        self.backend._graph = graph
        self.backend._graph_get = graph_get

    @staticmethod
    async def _unused(*_args):  # pragma: no cover - Salesforce is never called here
        raise AssertionError("No Salesforce call during email intake.")

    def activity(self, sender: dict) -> dict:
        return {"from": sender, "recipient": {"agenticAppId": INSTANCE, "agenticUserId": AGENT, "tenantId": TENANT},
                "entities": [{"type": "emailNotification", "id": "AAMk-notification", "conversationId": "thread-1"}]}

    async def test_mailbox_from_identifies_exactly_one_configured_requester(self) -> None:
        email = await self.backend.email_from_activity(self.binding, self.activity({"id": "", "name": "Megan"}), 3600)
        self.assertEqual((email.requester_id, email.message_id, email.subject), (REQUESTER, "AAMk-immutable", "Project Seabrook"))
        email = await self.backend.email_from_activity(self.binding, self.activity({"id": "megan@contoso.test"}), 3600)
        self.assertEqual(email.requester_id, REQUESTER)

    async def test_unknown_or_contradicting_senders_are_rejected(self) -> None:
        with self.assertRaises(ComplianceAuthorizationError):
            await self.backend.email_from_activity(self.binding, self.activity({"id": "wonda@contoso.test"}), 3600)
        self.message["from"] = {"emailAddress": {"address": "stranger@elsewhere.test"}}
        with self.assertRaises(ComplianceAuthorizationError):
            await self.backend.email_from_activity(self.binding, self.activity({"id": ""}), 3600)


if __name__ == "__main__":
    unittest.main()
