"""Offline unittest/SQLite checks; every external effect is a fake.

No SDK, network, credentials, subprocesses or wall-clock sleeps are needed.
Separate Store instances and event barriers force real CAS conflicts and the
claim/persistence cancellation windows; clocks and environment are test-local.
"""

from __future__ import annotations

import asyncio
import copy
import gzip
import hashlib
import json
import os
import re
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

from demo_agent.conversation_memory import ChatScope, SQLiteStore, StoreUnavailableError, scrub_memory_text
from demo_agent.tool_approvals import ToolApprovalGate, tool_call_digest


TENANT = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT = "22222222-2222-4222-8222-222222222222"
USER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OPERATOR = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
OUTSIDER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
NIL = "00000000-0000-0000-0000-000000000000"
ENV = {
    "AZURE_TENANT_ID": TENANT,
    "AUTOPILOT_TASK_USER_IDS": USER,
    "AUTOPILOT_OPERATOR_IDS": OPERATOR,
}


class Clock:
    def __init__(self) -> None:
        self.value = 1_800_000_000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def actor(scope: ChatScope, user: str = USER) -> dict[str, Any]:
    # Only stands in for main's verified identity construction, not JWT tests.
    return {"aadObjectId": user, "tenantId": scope.tenant_id, "conversationId": scope.conversation_id}


def approval_scope(scope: ChatScope) -> ChatScope:
    return ChatScope(scope.tenant_id, scope.agent_id, "tool-approvals:" + scope.storage_key)


def request_id(message: str) -> str:
    match = re.search(r"'approve ([0-9a-f]{12})'", message)
    if match is None:
        raise AssertionError("Expected an approval message, not: " + message)
    return match.group(1)


class FakeExecutor:
    def __init__(self, *, blocked: bool = False, error: BaseException | None = None,
                 result: Any = "The requested change was applied.", suppress_cancel: bool = False) -> None:
        self.calls: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.error = error
        self.result = result
        self.suppress_cancel = suppress_cancel
        if not blocked:
            self.release.set()

    async def __call__(self, server: str, tool: str, args: dict[str, Any], identity: dict[str, Any]) -> str:
        self.calls.append((server, tool, copy.deepcopy(args), copy.deepcopy(identity)))
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            if not self.suppress_cancel:
                raise
        if self.error is not None:
            raise self.error
        return self.result


class Rendezvous:
    def __init__(self) -> None:
        self.arrivals = 0
        self.ready = asyncio.Event()

    async def wait(self) -> None:
        self.arrivals += 1
        if self.arrivals == 2:
            self.ready.set()
        await self.ready.wait()


class CollidingStore(SQLiteStore):
    """Hold the first CAS until both stores have read the same version."""

    def __init__(self, path: Path, rendezvous: Rendezvous, **options: Any) -> None:
        super().__init__(path, **options)
        self.rendezvous = rendezvous
        self.cas_calls = 0

    async def _compare_and_swap(self, key: str, version: int | str | None, payload: bytes) -> bool:
        self.cas_calls += 1
        if self.cas_calls == 1:
            await self.rendezvous.wait()
        return await super()._compare_and_swap(key, version, payload)


class PausingStore(SQLiteStore):
    """A selected durable write is paused before or after its real SQLite CAS."""

    def __init__(self, path: Path, *, status: str = "executing", after_commit: bool = False,
                 **options: Any) -> None:
        super().__init__(path, **options)
        self.status = status
        self.after_commit = after_commit
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.paused = False

    async def _compare_and_swap(self, key: str, version: int | str | None, payload: bytes) -> bool:
        # Inspect the already-validated candidate without editing SQLite rows.
        state = json.loads(gzip.decompress(payload))
        pause = not self.paused and any(record.get("status") == self.status for record in state["tasks"].values())
        if pause:
            self.paused = True
        if pause and not self.after_commit:
            self.entered.set()
            await self.release.wait()
        committed = await super()._compare_and_swap(key, version, payload)
        if pause and self.after_commit:
            self.entered.set()
            await self.release.wait()
        return committed


class FailingStore(SQLiteStore):
    """Simulate both a lost write acknowledgement and an outcome-store outage."""

    def __init__(self, path: Path, *, commit_then_fail: bool = False, fail_outcomes: bool = False,
                 **options: Any) -> None:
        super().__init__(path, **options)
        self.commit_then_fail = commit_then_fail
        self.fail_outcomes = fail_outcomes

    async def _compare_and_swap(self, key: str, version: int | str | None, payload: bytes) -> bool:
        records = json.loads(gzip.decompress(payload))["tasks"].values()
        statuses = {record.get("status") for record in records}
        if self.fail_outcomes and statuses.intersection({"completed", "unknown"}):
            raise StoreUnavailableError("password=fictional-storage-diagnostic")
        committed = await super()._compare_and_swap(key, version, payload)
        if self.commit_then_fail and committed and "executing" in statuses:
            self.commit_then_fail = False
            raise StoreUnavailableError("token=fictional-lost-acknowledgement")
        return committed


class ApprovalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        environment = patch.dict(os.environ, ENV, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "approvals.sqlite3"
        self.clock = Clock()
        self.scope = ChatScope(TENANT, "28:autopilot", "chat-a")
        self.store = self.new_store()
        self.executor = FakeExecutor()
        self.gate = ToolApprovalGate(self.store, self.executor, self.clock)

    def new_store(self, cls: type[SQLiteStore] = SQLiteStore, **options: Any) -> SQLiteStore:
        store = cls(self.path, clock=self.clock, **options)
        self.addAsyncCleanup(store.close)
        return store

    def track(self, awaitable: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(awaitable)

        async def cleanup() -> None:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

        self.addAsyncCleanup(cleanup)
        return task

    async def propose(self, *, gate: ToolApprovalGate | None = None, user: str = USER,
                      args: dict[str, Any] | None = None, scope: ChatScope | None = None) -> str:
        target = scope or self.scope
        return await (gate or self.gate).propose(
            target, actor(target, user), "servicenow", "update_incident",
            {"number": "INC001", "state": "resolved"} if args is None else args,
        )

    async def records(self, scope: ChatScope | None = None) -> dict[str, Any]:
        return (await self.store.read(approval_scope(scope or self.scope)))["tasks"]

    async def decide(self, identifier: str, *, command: str = "approve", user: str = USER,
                     gate: ToolApprovalGate | None = None) -> str | None:
        return await (gate or self.gate).decide(self.scope, actor(self.scope, user), f"{command} {identifier}")

    async def test_propose_is_durable_purpose_scoped_and_never_executes(self) -> None:
        message = await self.propose()
        identifier = request_id(message)
        record = (await self.records())[identifier]
        self.assertEqual(self.executor.calls, [])
        self.assertEqual(record["status"], "pending")
        self.assertEqual(record["requesterId"], USER)
        self.assertEqual(record["scope"], self.scope.to_dict())
        self.assertEqual(record["expiresAt"], self.clock() + 900)
        self.assertEqual(record["at"], self.clock())
        self.assertEqual(record["result"], "")
        self.assertNotIn("actor", record)
        self.assertNotIn("claimId", record)
        self.assertLessEqual(len(message), 1800)
        original = await self.store.read(self.scope)
        self.assertEqual(original["tasks"], {})
        self.assertEqual(original["recent"], [])
        reopened = self.new_store()
        self.assertEqual((await reopened.read(approval_scope(self.scope)))["tasks"][identifier], record)

    async def test_digest_is_canonical_and_includes_exact_target(self) -> None:
        args = {"z": [True, 1, None], "a": {"second": 2, "first": "café"}}
        canonical = json.dumps({"server": "coupa", "tool": "create_order", "args": args},
                               sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        digest = tool_call_digest("coupa", "create_order", args)
        self.assertEqual(digest, hashlib.sha256(canonical.encode("utf-8")).hexdigest())
        self.assertEqual(digest, tool_call_digest("coupa", "create_order", {"a": args["a"], "z": args["z"]}))
        for server, tool, changed in (
            ("salesforce", "create_order", args), ("coupa", "delete_order", args),
            ("coupa", "create_order", {"z": [1, 1, None], "a": args["a"]}),
        ):
            self.assertNotEqual(digest, tool_call_digest(server, tool, changed))

    async def test_pending_dedup_does_not_extend_expiry_or_merge_requesters(self) -> None:
        message = await self.propose(args={"b": 2, "a": 1})
        identifier = request_id(message)
        before = (await self.records())[identifier]
        self.clock.advance(60)
        self.assertEqual(message, await self.propose(args={"a": 1, "b": 2}))
        self.assertEqual(before, (await self.records())[identifier])
        other = request_id(await self.propose(user=OPERATOR, args={"a": 1, "b": 2}))
        self.assertNotEqual(other, identifier)
        self.assertEqual(len(await self.records()), 2)
        self.assertIn("available to you", str(await self.decide(identifier, user=OPERATOR)))
        self.assertEqual((await self.records())[identifier]["status"], "pending")
        await self.decide(other, user=OPERATOR)
        self.assertEqual(self.executor.calls[0][3]["aadObjectId"], OPERATOR)

    async def test_same_requester_only_even_an_operator_cannot_reject_another(self) -> None:
        identifier = request_id(await self.propose())
        for command in ("approve", "reject"):
            for user in (OPERATOR, OUTSIDER):
                response = await self.decide(identifier, user=user, command=command)
                self.assertNotIn("INC001", str(response))
        self.assertEqual((await self.records())[identifier]["status"], "pending")
        self.assertEqual(self.executor.calls, [])

    async def test_wrong_chat_agent_tenant_and_actor_mismatch_fail_closed(self) -> None:
        identifier = request_id(await self.propose())
        scopes = (
            ChatScope(TENANT, self.scope.agent_id, "chat-b"),
            ChatScope(TENANT, "28:other-agent", self.scope.conversation_id),
            ChatScope(OTHER_TENANT, self.scope.agent_id, self.scope.conversation_id),
        )
        for scope in scopes:
            for identity in (actor(scope), actor(self.scope)):
                for command in ("approve", "reject"):
                    await self.gate.decide(scope, identity, f"{command} {identifier}")
        for field, value in (("tenantId", OTHER_TENANT), ("conversationId", "chat-b")):
            identity = actor(self.scope)
            identity[field] = value
            self.assertIn("verified user", await self.gate.propose(self.scope, identity, "coupa", "create", {}))
        self.assertEqual((await self.records())[identifier]["status"], "pending")
        self.assertEqual(self.executor.calls, [])
        with self.assertRaises(ValueError):
            await self.gate.clear(scopes[-1])

    async def test_no_placeholder_identity_or_model_authority_fallback(self) -> None:
        identifier = request_id(await self.propose())
        identities: list[dict[str, Any]] = []
        for field in ("aadObjectId", "tenantId", "conversationId"):
            identity = actor(self.scope)
            del identity[field]
            identities.append(identity)
        for value in (None, "", "anonymous", "control-plane", NIL, "someone@example.invalid", USER.replace("-", "")):
            identity = actor(self.scope)
            identity["aadObjectId"] = value
            identity.update(id=USER, roles=["operator"], authenticated=True)
            identities.append(identity)
        identities.append({**actor(self.scope, OUTSIDER), "roles": ["operator"], "approved": True})
        for identity in identities:
            with self.subTest(identity=identity):
                self.assertIn("verified user", await self.gate.propose(
                    self.scope, identity, "coupa", "create_order", {"requesterId": USER, "approved": True},
                ))
                self.assertIn("verified user", str(await self.gate.decide(self.scope, identity, "approve " + identifier)))
        self.assertEqual(len(await self.records()), 1)
        self.assertEqual(self.executor.calls, [])

    async def test_configuration_uuid_parsing_empty_lists_and_revocation(self) -> None:
        for name in ("AZURE_TENANT_ID", "AUTOPILOT_TASK_USER_IDS", "AUTOPILOT_OPERATOR_IDS"):
            invalid_values = ("anonymous", NIL, "not-a-guid", USER + ",", "{" + USER + "}")
            for invalid in invalid_values:
                with self.subTest(name=name, invalid=invalid), patch.dict(os.environ, {name: invalid}), self.assertRaises(ValueError):
                    ToolApprovalGate(self.store, self.executor, self.clock)
        with patch.dict(os.environ, {"AZURE_TENANT_ID": ""}), self.assertRaises(ValueError):
            ToolApprovalGate(self.store, self.executor, self.clock)
        with patch.dict(os.environ, {"AUTOPILOT_TASK_USER_IDS": " " + USER.upper() + "; " + OPERATOR + " " + USER,
                                     "AUTOPILOT_OPERATOR_IDS": ""}):
            allowed = ToolApprovalGate(self.store, self.executor, self.clock)
        identifier = request_id(await self.propose(gate=allowed))
        with patch.dict(os.environ, {"AUTOPILOT_TASK_USER_IDS": "", "AUTOPILOT_OPERATOR_IDS": ""}):
            revoked = ToolApprovalGate(self.store, self.executor, self.clock)
        self.assertIn("verified user", str(await self.decide(identifier, gate=revoked)))
        self.assertIn("verified user", await self.propose(gate=revoked, user=OPERATOR))
        self.assertEqual(self.executor.calls, [])

    async def test_commands_are_exact_not_fuzzy_or_model_style(self) -> None:
        identifier = request_id(await self.propose())
        texts = (
            "yes", "approve", "APPROVE " + identifier, "Approve " + identifier,
            " approve " + identifier, "approve " + identifier + " ", "approve " + identifier + "\n",
            "approve\t" + identifier, "approve  " + identifier, "please approve " + identifier,
            "approve " + identifier + ".", "approve " + identifier[:-1], "approve " + identifier + "0",
            "approve " + identifier + "\nreject " + identifier, "approve gggggggggggg",
            "`approve " + identifier + "`", "reject " + identifier + " because no", "",
        )
        for text in texts:
            with self.subTest(text=text):
                self.assertIsNone(await self.gate.decide(self.scope, actor(self.scope), text))
        self.assertEqual(self.executor.calls, [])
        await self.decide(identifier.upper())
        self.assertEqual(len(self.executor.calls), 1)

    async def test_expiry_at_exact_boundary_rejects_and_new_request_gets_new_id(self) -> None:
        identifier = request_id(await self.propose())
        self.clock.advance(900)
        self.assertIn("expired", str(await self.decide(identifier)))
        self.assertEqual((await self.records())[identifier]["status"], "rejected")
        new_identifier = request_id(await self.propose())
        self.assertNotEqual(identifier, new_identifier)
        self.assertEqual(self.executor.calls, [])

    async def test_claim_that_expires_during_storage_await_does_not_execute(self) -> None:
        identifier = request_id(await self.propose())
        store = PausingStore(self.path, after_commit=True, clock=self.clock)
        self.addAsyncCleanup(store.close)
        gate = ToolApprovalGate(store, self.executor, self.clock)
        decision = self.track(self.decide(identifier, gate=gate))
        try:
            await asyncio.wait_for(store.entered.wait(), 5)
            self.clock.advance(900)
        finally:
            store.release.set()
        self.assertIn("expired", str(await asyncio.wait_for(decision, 5)))
        self.assertEqual(self.executor.calls, [])
        self.assertEqual((await self.records())[identifier]["status"], "rejected")

    async def test_reject_is_durable_and_duplicate_decisions_never_execute(self) -> None:
        identifier = request_id(await self.propose())
        self.assertIn("rejected", str(await self.decide(identifier, command="reject")))
        for command in ("approve", "reject"):
            self.assertIn("rejected", str(await self.decide(identifier, command=command)))
        self.assertEqual(self.executor.calls, [])

    async def test_caller_mutation_cannot_change_args_or_identity_during_claim(self) -> None:
        args = {"record": {"state": "resolved"}, "count": 1}
        identifier = request_id(await self.propose(args=args))
        args["record"]["state"] = "deleted"
        store = PausingStore(self.path, clock=self.clock)
        self.addAsyncCleanup(store.close)
        gate = ToolApprovalGate(store, self.executor, self.clock)
        identity = {**actor(self.scope), "roles": ["operator"], "token": "not-for-storage", "runId": "untrusted-extra"}
        decision = self.track(gate.decide(self.scope, identity, "approve " + identifier))
        try:
            await asyncio.wait_for(store.entered.wait(), 5)
            identity["aadObjectId"] = OUTSIDER
            identity["conversationId"] = "chat-b"
        finally:
            store.release.set()
        await asyncio.wait_for(decision, 5)
        self.assertEqual(self.executor.calls[0][2], {"record": {"state": "resolved"}, "count": 1})
        self.assertEqual(self.executor.calls[0][3], actor(self.scope))
        self.assertNotIn("not-for-storage", json.dumps(await self.records()))

    async def test_mutated_digest_args_target_scope_and_requester_fail_closed(self) -> None:
        mutations = (
            ("args", {"state": "deleted"}), ("digest", "0" * 64), ("server", "coupa"),
            ("tool", "delete_incident"), ("scope", ChatScope(TENANT, "other", "chat-a").to_dict()),
            ("requesterId", OPERATOR), ("expiresAt", self.clock() + 901), ("at", True),
            ("claimId", uuid.uuid4().hex),
        )
        for index, (field, value) in enumerate(mutations):
            identifier = request_id(await self.propose(args={"case": index}))

            def mutate(state: dict[str, Any]) -> None:
                state["tasks"][identifier][field] = value

            await self.store.update(approval_scope(self.scope), mutate)
            await self.decide(identifier)
        self.assertEqual(self.executor.calls, [])

    async def test_credential_keys_values_boundaries_and_json_escapes_are_rejected(self) -> None:
        credentials: list[dict[str, Any]] = [
            {"Authorization": None}, {"nested": [{"aUtH-ToKeN": {}}]}, {"x_api_key": []},
            {"x-authorization": None}, {"serviceAuth": {}}, {"vendorApiKey": ""},
            {"auth": "Basic fictional"}, {"private-key": ""}, {"clientSecret": False},
            {"note": "Bearer fictional-credential"}, {"note": "Bearer\nfictional-credential"},
            {"note": "password=fictional-value"}, {"note": "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ4In0.signature"},
            {"note": "-----BEGIN PRIVATE KEY-----\nfictional\n-----END PRIVATE KEY-----"},
            {"note": "x" * 9000 + " password=fictional-after-cap"},
            {"note": "x" * 7900 + " Bearer " + "z" * 2000},
            {"note": "x" * 7900 + " password=" + " " * 200 + "fictional-boundary"},
        ]
        for args in credentials:
            with self.subTest(args_size=len(json.dumps(args))):
                message = await self.propose(args=args)
                self.assertIn("Credentials", message)
                self.assertNotIn("fictional", message)
        self.assertEqual(await self.records(), {})
        self.assertEqual(self.executor.calls, [])

    async def test_safe_long_args_size_checks_are_separate_from_redaction(self) -> None:
        # Exactly 16,000 UTF-8 bytes, including JSON keys, braces and quotes.
        args = {"note": "x" * 15_989}
        self.assertEqual(len(json.dumps(args, separators=(",", ":")).encode("utf-8")), 16000)
        message = await self.propose(args=args)
        identifier = request_id(message)
        self.assertLessEqual(len(message), 1800)
        self.assertIn("preview shortened", message)
        self.assertEqual((await self.records())[identifier]["args"], args)
        for invalid in ({"note": "x" * 15_990}, {"a": "x" * 9000, "b": "y" * 9000}, {"note": "é" * 8000}):
            self.assertIn("16000-byte", await self.propose(args=invalid))
        self.assertEqual(len(await self.records()), 1)

    async def test_non_json_values_and_arbitrary_servers_or_tool_names_are_rejected(self) -> None:
        cycle: dict[str, Any] = {}
        cycle["cycle"] = cycle
        # Deliberately violate the public annotation to exercise runtime checks.
        invalid_args: list[Any] = [
            {"x": float("nan")}, {"x": float("inf")}, {"x": (1, 2)}, {1: "not-string-key"},
            {"x": object()}, {"x": "\ud800"}, cycle, [], "not an object",
        ]
        for args in invalid_args:
            message = await self.propose(args=args)
            self.assertNotIn("'approve ", message)
        for server in ("https://example.invalid/mcp", "human", "workday/../coupa", "WORKDAY", ""):
            self.assertNotIn("'approve ", await self.gate.propose(self.scope, actor(self.scope), server, "create", {}))
        for tool in ("create-order", "../create", "x" * 65, "create\n", "créate", "", "https://host"):
            self.assertNotIn("'approve ", await self.gate.propose(self.scope, actor(self.scope), "coupa", tool, {}))
        self.assertEqual(await self.records(), {})
        self.assertEqual(self.executor.calls, [])
        for server in ("workday", "servicenow", "coupa", "salesforce"):
            request_id(await self.gate.propose(self.scope, actor(self.scope), server, "A_" + "1" * 62, {}))

    async def test_completion_is_persisted_before_delivery_and_duplicates_never_execute(self) -> None:
        identifier = request_id(await self.propose())
        self.executor.result = "Applied. password=fictional-result " + "z" * 9000
        first = await self.decide(identifier)
        record = (await self.records())[identifier]
        self.assertEqual(record["status"], "completed")
        self.assertEqual(record["result"], scrub_memory_text(self.executor.result))
        self.assertEqual(len(record["result"]), 8000)
        self.assertNotIn("fictional-result", str(first))
        self.assertLessEqual(len(str(first)), 1800)
        self.assertIn("Result shortened", str(first))
        reopened_gate = ToolApprovalGate(self.new_store(), self.executor, self.clock)
        self.clock.advance(901)
        self.assertEqual(await self.decide(identifier, gate=reopened_gate), first)
        self.assertEqual(await self.decide(identifier, gate=reopened_gate, command="reject"), first)
        self.assertEqual(len(self.executor.calls), 1)

    async def test_failures_are_unknown_and_never_retried_or_leaked(self) -> None:
        for error in (RuntimeError("password=fictional-error"), TimeoutError("token=fictional-timeout")):
            executor = FakeExecutor(error=error)
            gate = ToolApprovalGate(self.store, executor, self.clock)
            identifier = request_id(await self.propose(gate=gate, args={"case": type(error).__name__}))
            response = await self.decide(identifier, gate=gate)
            self.assertIn("unknown outcome", str(response))
            self.assertIn("may already have taken effect", str(response))
            self.assertNotIn("fictional", str(response))
            self.assertEqual((await self.records())[identifier]["status"], "unknown")
            reopened = ToolApprovalGate(self.new_store(), executor, self.clock)
            for command in ("approve", "reject"):
                self.assertEqual(await self.decide(identifier, gate=reopened, command=command), response)
            self.assertEqual(len(executor.calls), 1)
        self.assertNotIn("fictional", json.dumps(await self.records()))

    async def test_invalid_callback_result_is_unknown_not_a_fake_success(self) -> None:
        executor = FakeExecutor(result={"status": "success"})
        gate = ToolApprovalGate(self.store, executor, self.clock)
        identifier = request_id(await self.propose(gate=gate))
        self.assertIn("unknown outcome", str(await self.decide(identifier, gate=gate)))
        self.assertEqual((await self.records())[identifier]["status"], "unknown")
        await self.decide(identifier, gate=gate)
        self.assertEqual(len(executor.calls), 1)

    async def test_executing_is_visible_before_effect_and_cross_process_duplicates_do_not_replay(self) -> None:
        executor = FakeExecutor(blocked=True)
        gate = ToolApprovalGate(self.store, executor, self.clock)
        identifier = request_id(await self.propose(gate=gate))
        decision = self.track(self.decide(identifier, gate=gate))
        try:
            await asyncio.wait_for(executor.started.wait(), 5)
            self.assertEqual((await self.records())[identifier]["status"], "executing")
            other_gate = ToolApprovalGate(self.new_store(), self.executor, self.clock)
            for command in ("approve", "reject"):
                response = await self.decide(identifier, gate=other_gate, command=command)
                self.assertIn("may still be running", str(response))
            self.assertEqual(self.executor.calls, [])
        finally:
            executor.release.set()
        await asyncio.wait_for(decision, 5)
        self.assertEqual(len(executor.calls), 1)

    async def test_real_colliding_cas_approvals_execute_exactly_one_callback(self) -> None:
        identifier = request_id(await self.propose())
        rendezvous = Rendezvous()
        left = CollidingStore(self.path, rendezvous, clock=self.clock)
        right = CollidingStore(self.path, rendezvous, clock=self.clock)
        self.addAsyncCleanup(left.close)
        self.addAsyncCleanup(right.close)
        gates = [ToolApprovalGate(store, self.executor, self.clock) for store in (left, right)]
        responses = await asyncio.wait_for(asyncio.gather(*(self.decide(identifier, gate=gate) for gate in gates)), 15)
        self.assertEqual(rendezvous.arrivals, 2)
        self.assertGreaterEqual(left.cas_calls + right.cas_calls, 3)
        self.assertTrue(all(response is not None for response in responses))
        self.assertEqual(len(self.executor.calls), 1)
        self.assertEqual((await self.records())[identifier]["status"], "completed")

    async def test_repeated_claim_nonce_cannot_replay_an_executing_record(self) -> None:
        executor = FakeExecutor(blocked=True)
        gate = ToolApprovalGate(self.store, executor, self.clock)
        identifier = request_id(await self.propose(gate=gate))
        fixed = uuid.UUID("abcdef01-2345-4678-8123-0123456789ab")
        with patch("demo_agent.tool_approvals.uuid.uuid4", return_value=fixed):
            decision = self.track(self.decide(identifier, gate=gate))
            try:
                await asyncio.wait_for(executor.started.wait(), 5)
                response = await asyncio.wait_for(self.decide(identifier, gate=gate), 5)
                self.assertIn("may still be running", str(response))
                self.assertEqual(len(executor.calls), 1)
            finally:
                executor.release.set()
            await asyncio.wait_for(decision, 5)

    async def test_colliding_clear_and_approval_serialize_without_erasing_receipts(self) -> None:
        identifier = request_id(await self.propose())
        rendezvous = Rendezvous()
        stores = [CollidingStore(self.path, rendezvous, clock=self.clock) for _ in range(2)]
        for store in stores:
            self.addAsyncCleanup(store.close)
        approve_gate, clear_gate = [ToolApprovalGate(store, self.executor, self.clock) for store in stores]
        await asyncio.wait_for(asyncio.gather(
            self.decide(identifier, gate=approve_gate), clear_gate.clear(self.scope),
        ), 15)
        record = (await self.records())[identifier]
        self.assertIn(record["status"], {"completed", "rejected"})
        self.assertEqual(len(self.executor.calls), int(record["status"] == "completed"))
        await self.decide(identifier)
        self.assertEqual(len(self.executor.calls), int(record["status"] == "completed"))

    async def test_real_colliding_proposals_return_same_request_and_preserve_both_users(self) -> None:
        for users in ((USER, USER), (USER, OPERATOR)):
            rendezvous = Rendezvous()
            stores = [CollidingStore(self.path, rendezvous, clock=self.clock) for _ in range(2)]
            for store in stores:
                self.addAsyncCleanup(store.close)
            gates = [ToolApprovalGate(store, self.executor, self.clock) for store in stores]
            messages = await asyncio.wait_for(asyncio.gather(*(
                self.propose(gate=gate, user=user, args={"case": list(users)}) for gate, user in zip(gates, users)
            )), 15)
            identifiers = [request_id(message) for message in messages]
            self.assertEqual(identifiers[0] == identifiers[1], users[0] == users[1])
            self.assertEqual(rendezvous.arrivals, 2)
        self.assertEqual(len(await self.records()), 3)
        self.assertEqual(self.executor.calls, [])

    async def test_cancellation_during_effect_is_unknown_before_cancel_propagates(self) -> None:
        executor = FakeExecutor(blocked=True)
        gate = ToolApprovalGate(self.store, executor, self.clock)
        identifier = request_id(await self.propose(gate=gate))
        decision = self.track(self.decide(identifier, gate=gate))
        await asyncio.wait_for(executor.started.wait(), 5)
        decision.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(decision, 5)
        self.assertEqual((await self.records())[identifier]["status"], "unknown")
        await self.decide(identifier, gate=gate)
        self.assertEqual(len(executor.calls), 1)

    async def test_callback_suppressing_cancellation_cannot_report_completion(self) -> None:
        executor = FakeExecutor(blocked=True, suppress_cancel=True)
        gate = ToolApprovalGate(self.store, executor, self.clock)
        identifier = request_id(await self.propose(gate=gate))
        decision = self.track(self.decide(identifier, gate=gate))
        await asyncio.wait_for(executor.started.wait(), 5)
        decision.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(decision, 5)
        self.assertEqual((await self.records())[identifier]["status"], "unknown")
        await self.decide(identifier, gate=gate)
        self.assertEqual(len(executor.calls), 1)

    async def test_cancellation_before_claim_ack_joins_write_then_marks_unknown(self) -> None:
        for after_commit in (False, True):
            identifier = request_id(await self.propose(args={"afterCommit": after_commit}))
            store = PausingStore(self.path, after_commit=after_commit, clock=self.clock)
            self.addAsyncCleanup(store.close)
            gate = ToolApprovalGate(store, self.executor, self.clock)
            decision = self.track(self.decide(identifier, gate=gate))
            try:
                await asyncio.wait_for(store.entered.wait(), 5)
                decision.cancel()
            finally:
                store.release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(decision, 5)
            self.assertEqual((await self.records())[identifier]["status"], "unknown")
        self.assertEqual(self.executor.calls, [])

    async def test_repeated_cancellation_does_not_abandon_unknown_persistence(self) -> None:
        executor = FakeExecutor(blocked=True)
        store = PausingStore(self.path, status="unknown", clock=self.clock)
        self.addAsyncCleanup(store.close)
        gate = ToolApprovalGate(store, executor, self.clock)
        identifier = request_id(await self.propose(gate=gate))
        decision = self.track(self.decide(identifier, gate=gate))
        try:
            await asyncio.wait_for(executor.started.wait(), 5)
            decision.cancel()
            await asyncio.wait_for(store.entered.wait(), 5)
            decision.cancel()
        finally:
            store.release.set()
            executor.release.set()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(decision, 5)
        self.assertEqual((await self.records())[identifier]["status"], "unknown")

    async def test_cancellation_during_completed_commit_never_downgrades_saved_success(self) -> None:
        identifier = request_id(await self.propose())
        store = PausingStore(self.path, status="completed", after_commit=True, clock=self.clock)
        self.addAsyncCleanup(store.close)
        gate = ToolApprovalGate(store, self.executor, self.clock)
        decision = self.track(self.decide(identifier, gate=gate))
        try:
            await asyncio.wait_for(store.entered.wait(), 5)
            decision.cancel()
        finally:
            store.release.set()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(decision, 5)
        self.assertEqual((await self.records())[identifier]["status"], "completed")
        await self.decide(identifier, gate=gate)
        self.assertEqual(len(self.executor.calls), 1)

    async def test_base_exception_is_persisted_unknown_and_reraised(self) -> None:
        class StopEffect(BaseException):
            pass

        executor = FakeExecutor(error=StopEffect("private diagnostic"))
        gate = ToolApprovalGate(self.store, executor, self.clock)
        identifier = request_id(await self.propose(gate=gate))
        with self.assertRaises(StopEffect):
            await self.decide(identifier, gate=gate)
        self.assertEqual((await self.records())[identifier]["status"], "unknown")
        self.assertNotIn("private diagnostic", json.dumps(await self.records()))

    async def test_ambiguous_claim_commit_never_dispatches(self) -> None:
        identifier = request_id(await self.propose())
        store = self.new_store(FailingStore, commit_then_fail=True)
        gate = ToolApprovalGate(store, self.executor, self.clock)
        response = await self.decide(identifier, gate=gate)
        self.assertIn("unknown outcome", str(response))
        self.assertNotIn("fictional", str(response))
        self.assertEqual((await self.records())[identifier]["status"], "unknown")
        await self.decide(identifier, gate=gate)
        self.assertEqual(self.executor.calls, [])

    async def test_outcome_store_failure_keeps_executing_and_never_leaks_success_or_retries(self) -> None:
        identifier = request_id(await self.propose())
        store = self.new_store(FailingStore, fail_outcomes=True)
        gate = ToolApprovalGate(store, self.executor, self.clock)
        response = await self.decide(identifier, gate=gate)
        self.assertIn("unknown outcome", str(response))
        self.assertNotIn("fictional", str(response))
        self.assertNotIn("applied", str(response))
        self.assertEqual((await self.records())[identifier]["status"], "executing")
        reopened = ToolApprovalGate(self.new_store(), self.executor, self.clock)
        self.assertIn("may still be running", str(await self.decide(identifier, gate=reopened)))
        self.assertEqual(len(self.executor.calls), 1)

    async def test_clear_and_conversation_forget_preserve_execution_receipts(self) -> None:
        completed = request_id(await self.propose(args={"case": "completed"}))
        await self.decide(completed)
        failing = FakeExecutor(error=RuntimeError("fictional"))
        failed_gate = ToolApprovalGate(self.store, failing, self.clock)
        unknown = request_id(await self.propose(gate=failed_gate, args={"case": "unknown"}))
        await self.decide(unknown, gate=failed_gate)
        pending = request_id(await self.propose(args={"case": "pending"}))
        executor = FakeExecutor(blocked=True)
        gate = ToolApprovalGate(self.store, executor, self.clock)
        executing = request_id(await self.propose(gate=gate, args={"case": "executing"}))
        decision = self.track(self.decide(executing, gate=gate))
        try:
            await asyncio.wait_for(executor.started.wait(), 5)
            before = await self.records()
            await self.gate.clear(self.scope)
            after = await self.records()
            self.assertEqual(after[pending]["status"], "rejected")
            for identifier in (completed, unknown, executing):
                self.assertEqual(after[identifier], before[identifier])
            await self.store.update(self.scope, lambda state: state["tasks"].clear())
            self.assertEqual(await self.records(), after)
            await self.decide(pending)
        finally:
            executor.release.set()
        await asyncio.wait_for(decision, 5)
        self.assertEqual((await self.records())[executing]["status"], "completed")

    async def test_pending_limit_dedup_at_capacity_and_expiration_releases_slots(self) -> None:
        identifiers = [request_id(await self.propose(args={"case": index})) for index in range(20)]
        self.assertIn("20 pending", await self.propose(args={"case": 20}))
        self.assertEqual(request_id(await self.propose(args={"case": 0})), identifiers[0])
        self.assertEqual(len(await self.records()), 20)
        self.clock.advance(900)
        request_id(await self.propose(args={"case": 20}))
        records = await self.records()
        self.assertEqual(sum(record["status"] == "pending" for record in records.values()), 1)
        self.assertTrue(all(records[identifier]["status"] == "rejected" for identifier in identifiers))

    async def test_cas_also_serializes_the_pending_capacity_limit(self) -> None:
        for index in range(19):
            request_id(await self.propose(args={"case": index}))
        rendezvous = Rendezvous()
        stores = [CollidingStore(self.path, rendezvous, clock=self.clock) for _ in range(2)]
        for store in stores:
            self.addAsyncCleanup(store.close)
        gates = [ToolApprovalGate(store, self.executor, self.clock) for store in stores]
        messages = await asyncio.wait_for(asyncio.gather(*(
            self.propose(gate=gate, args={"new": index}) for index, gate in enumerate(gates)
        )), 15)
        self.assertEqual(sum("20 pending" in message for message in messages), 1)
        self.assertEqual(len(await self.records()), 20)
        self.assertEqual(self.executor.calls, [])

    async def test_history_cap_preserves_pending_executing_unknown_and_prunes_oldest_terminal(self) -> None:
        template_id = request_id(await self.propose())
        template = (await self.records())[template_id]

        def fill(state: dict[str, Any]) -> None:
            state["tasks"].clear()
            for index in range(50):
                record = copy.deepcopy(template)
                status = "pending" if index < 19 else "executing" if index == 19 else "unknown" if index == 20 else "completed"
                record.update(status=status, at=self.clock() - 50 + index,
                              expiresAt=self.clock() - 50 + index + 900)
                state["tasks"][f"{index:012x}"] = record

        await self.store.update(approval_scope(self.scope), fill)
        request_id(await self.propose(args={"new": True}))
        records = await self.records()
        self.assertEqual(len(records), 50)
        self.assertNotIn(f"{21:012x}", records)
        self.assertTrue(all(f"{index:012x}" in records for index in range(21)))
        self.assertEqual(sum(record["status"] == "pending" for record in records.values()), 20)

    async def test_full_uncertain_history_refuses_new_work_instead_of_erasing_receipts(self) -> None:
        identifier = request_id(await self.propose())
        template = (await self.records())[identifier]

        def fill(state: dict[str, Any]) -> None:
            state["tasks"].clear()
            for index in range(50):
                record = copy.deepcopy(template)
                record["status"] = "executing" if index % 2 else "unknown"
                state["tasks"][f"{index:012x}"] = record

        await self.store.update(approval_scope(self.scope), fill)
        before = await self.records()
        self.assertIn("history is full", await self.propose(args={"new": True}))
        self.assertEqual(await self.records(), before)

    async def test_random_id_collision_cannot_replace_an_existing_request(self) -> None:
        fixed = uuid.UUID("abcdef01-2345-4678-8123-0123456789ab")
        with patch("demo_agent.tool_approvals.uuid.uuid4", return_value=fixed):
            identifier = request_id(await self.propose(args={"case": 1}))
            before = await self.records()
            message = await self.propose(args={"case": 2})
        self.assertEqual(identifier, fixed.hex[:12])
        self.assertIn("unique approval ID", message)
        self.assertEqual(await self.records(), before)


if __name__ == "__main__":
    unittest.main()