"""Offline stdlib tests for conversation memory; no Azure SDK/network required.

These tests intentionally exercise separate SQLite connections/store instances,
including deterministically colliding CAS writes. Azure construction/factory
tests do not initialize clients; Azure wire-contract tests use stdlib fakes,
never real SDK clients, acquired tokens, or network calls.
"""

from __future__ import annotations

import asyncio
import copy
import gzip
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

from demo_agent.conversation_memory import (
    DEFAULT_MAX_COMPRESSED_BYTES,
    DEFAULT_TTL_SECONDS,
    MAX_CONTENT_CHARS,
    MAX_ID_CHARS,
    MAX_JSON_DEPTH,
    MAX_RECENT_MESSAGES,
    MAX_SEEN_IDS,
    AzureBlobStore,
    ChatScope,
    ConcurrentUpdateError,
    CorruptStateError,
    SQLiteStore,
    StateTooLargeError,
    StoreClosedError,
    StoreConfigurationError,
    StoreUnavailableError,
    append_exchange,
    claim_activity,
    create_conversation_store,
    mark_welcomed,
    scrub_memory_text,
)


class Clock:
    def __init__(self) -> None:
        self.value = 1_800_000_000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class Rendezvous:
    """Release exactly two initial CAS attempts after both have read a snapshot."""

    def __init__(self) -> None:
        self.arrivals = 0
        self.ready = asyncio.Event()

    async def wait(self) -> None:
        self.arrivals += 1
        if self.arrivals == 2:
            self.ready.set()
        await self.ready.wait()


class CollidingStore(SQLiteStore):
    def __init__(self, path: Path, rendezvous: Rendezvous, **options: Any) -> None:
        super().__init__(path, **options)
        self.rendezvous = rendezvous
        self.cas_calls = 0

    async def _compare_and_swap(self, key: str, version: int | str | None, payload: bytes) -> bool:
        self.cas_calls += 1
        if self.cas_calls == 1:
            await self.rendezvous.wait()
        return await super()._compare_and_swap(key, version, payload)


class NeverWinningStore(SQLiteStore):
    def __init__(self, path: Path, **options: Any) -> None:
        super().__init__(path, **options)
        self.cas_calls = 0

    async def _compare_and_swap(self, key: str, version: int | str | None, payload: bytes) -> bool:
        self.cas_calls += 1
        return False


class ConversationMemoryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "chosen" / "memory.sqlite3"
        self.clock = Clock()
        self.scope = ChatScope("tenant", "agent", "conversation")
        self.store = self.new_store()

    def new_store(self, **options: Any) -> SQLiteStore:
        store = SQLiteStore(self.path, clock=self.clock, **options)
        self.addAsyncCleanup(store.close)
        return store

    def colliding_pair(self) -> tuple[CollidingStore, CollidingStore]:
        rendezvous = Rendezvous()
        stores = tuple(CollidingStore(self.path, rendezvous, clock=self.clock) for _ in range(2))
        for store in stores:
            self.addAsyncCleanup(store.close)
        return stores[0], stores[1]

    async def raw_row(self) -> tuple[int, bytes] | None:
        def read() -> tuple[int, bytes] | None:
            with closing(sqlite3.connect(self.path)) as connection:
                return connection.execute(
                    "SELECT version, payload FROM conversation_memory WHERE storage_key = ?",
                    (self.scope.storage_key,),
                ).fetchone()

        return await asyncio.to_thread(read)

    async def replace_payload(self, payload: bytes) -> None:
        def write() -> None:
            with closing(sqlite3.connect(self.path)) as connection, connection:
                connection.execute(
                    "UPDATE conversation_memory SET payload = ? WHERE storage_key = ?",
                    (payload, self.scope.storage_key),
                )

        await asyncio.to_thread(write)

    async def test_operator_reset_deletes_everything_except_kept_scopes(self) -> None:
        kept = ChatScope("tenant", "agent", "control-room:policies")
        for scope in (self.scope, kept, ChatScope("tenant", "agent", "other")):
            await self.store.update(scope, lambda state: state.update(active=True))
        self.assertEqual(await self.store.clear_all(keep=(kept,)), 2)
        self.assertFalse((await self.store.read(self.scope))["active"])
        self.assertTrue((await self.store.read(kept))["active"])
        self.assertEqual(await self.store.clear_all(keep=(kept,)), 0)

    @staticmethod
    def encoded(state: dict[str, Any]) -> bytes:
        return gzip.compress(json.dumps(state, ensure_ascii=False).encode("utf-8"), mtime=0)

    async def seed(self) -> dict[str, Any]:
        def transform(state: dict[str, Any]) -> None:
            state["summary"] = "# Durable memory\n\n- Preserve the draft."
            state["tasks"]["draft-1"] = {"status": "draft", "steps": ["review", "approve"]}

        return await self.store.update(self.scope, transform)

    async def test_missing_state_is_fresh_detached_and_inactive(self) -> None:
        self.assertFalse(self.path.exists())  # Constructor performs no I/O.
        state = await self.store.read(self.scope)
        self.assertEqual(
            state,
            {"schemaVersion": 1, "scope": self.scope.to_dict(), "summary": "", "recent": [],
             "seen": [], "tasks": {}, "welcomed": False, "active": False,
             "updatedAt": self.clock()},
        )
        state["tasks"]["not-saved"] = {"status": "draft"}
        state["scope"]["tenantId"] = "not-saved"
        self.assertEqual((await self.store.read(self.scope))["tasks"], {})
        self.assertEqual((await self.store.read(self.scope))["scope"], self.scope.to_dict())
        self.assertIsNone(await self.raw_row())

    async def test_tenant_agent_and_conversation_are_all_isolated(self) -> None:
        scopes = [
            self.scope, ChatScope("other", "agent", "conversation"),
            ChatScope("tenant", "other", "conversation"), ChatScope("tenant", "agent", "other"),
        ]
        for index, scope in enumerate(scopes):
            def transform(state: dict[str, Any], text: str = str(index)) -> None:
                state["summary"] = text

            await self.store.update(scope, transform)
        reopened = self.new_store()
        for index, scope in enumerate(scopes):
            self.assertEqual((await reopened.read(scope))["summary"], str(index))

    async def test_gzip_json_roundtrip_preserves_markdown_and_draft(self) -> None:
        initial = await self.seed()
        await self.store.close()
        reopened = self.new_store()
        self.assertEqual(await reopened.read(self.scope), initial)
        row = await self.raw_row()
        self.assertIsNotNone(row)
        assert row is not None
        self.assertEqual(row[0], 1)
        self.assertTrue(row[1].startswith(b"\x1f\x8b"))
        self.assertEqual(json.loads(gzip.decompress(row[1])), initial)

    async def test_two_instances_retry_colliding_creates_without_losing_tasks(self) -> None:
        left, right = self.colliding_pair()

        def first(state: dict[str, Any]) -> None:
            state["tasks"]["left"] = {"status": "draft"}

        def second(state: dict[str, Any]) -> None:
            state["tasks"]["right"] = {"status": "draft"}

        await asyncio.wait_for(
            asyncio.gather(left.update(self.scope, first), right.update(self.scope, second)), 15
        )
        self.assertEqual(set((await self.store.read(self.scope))["tasks"]), {"left", "right"})
        self.assertEqual(left.cas_calls + right.cas_calls, 3)
        row = await self.raw_row()
        assert row is not None
        self.assertEqual(row[0], 2)

    async def test_two_instances_retry_colliding_existing_versions(self) -> None:
        await self.seed()
        left, right = self.colliding_pair()

        def increment(state: dict[str, Any]) -> None:
            record = state["tasks"].setdefault("counter", {"count": 0})
            record["count"] += 1

        await asyncio.wait_for(
            asyncio.gather(left.update(self.scope, increment), right.update(self.scope, increment)), 15
        )
        state = await self.store.read(self.scope)
        self.assertEqual(state["tasks"]["counter"]["count"], 2)
        self.assertEqual(state["tasks"]["draft-1"]["status"], "draft")
        row = await self.raw_row()
        assert row is not None
        self.assertEqual(row[0], 3)

    async def test_cas_budget_is_at_most_five_attempts(self) -> None:
        store = NeverWinningStore(self.path, clock=self.clock, max_attempts=5)
        self.addAsyncCleanup(store.close)

        def transform(state: dict[str, Any]) -> None:
            state["active"] = True

        with self.assertRaises(ConcurrentUpdateError):
            await store.update(self.scope, transform)
        self.assertEqual(store.cas_calls, 5)
        self.assertIsNone(await self.raw_row())

    async def test_claim_is_atomic_across_instances_and_survives_reopen(self) -> None:
        left, right = self.colliding_pair()
        results = await asyncio.wait_for(
            asyncio.gather(claim_activity(left, self.scope, "activity"),
                           claim_activity(right, self.scope, "activity")), 15
        )
        self.assertEqual(sorted(results), [False, True])
        self.assertFalse(await claim_activity(self.new_store(), self.scope, "activity"))
        self.assertEqual((await self.store.read(self.scope))["seen"], ["activity"])
        self.assertTrue(await claim_activity(self.store, ChatScope("other", "agent", "conversation"), "activity"))

    async def test_welcome_is_atomic_and_not_repeated(self) -> None:
        left, right = self.colliding_pair()
        results = await asyncio.wait_for(
            asyncio.gather(mark_welcomed(left, self.scope), mark_welcomed(right, self.scope)), 15
        )
        self.assertEqual(sorted(results), [False, True])
        self.assertFalse(await mark_welcomed(self.new_store(), self.scope))
        self.assertFalse((await self.store.read(self.scope))["active"])

    async def test_bounded_receipts_evict_oldest_not_duplicate_attempts(self) -> None:
        def fill(state: dict[str, Any]) -> None:
            state["seen"] = [f"activity-{index}" for index in range(MAX_SEEN_IDS)]

        await self.store.update(self.scope, fill)
        self.assertFalse(await claim_activity(self.store, self.scope, "activity-0"))
        self.assertTrue(await claim_activity(self.store, self.scope, "new"))
        seen = (await self.store.read(self.scope))["seen"]
        self.assertEqual(len(seen), MAX_SEEN_IDS)
        self.assertEqual(seen[0], "activity-1")
        self.assertEqual(seen[-1], "new")
        self.assertTrue(await claim_activity(self.new_store(), self.scope, "activity-0"))

    async def test_claim_then_append_retains_exchange_and_deduplicates_recent(self) -> None:
        initial = await self.seed()
        self.assertTrue(await claim_activity(self.store, self.scope, "activity"))
        state = await append_exchange(
            self.store, self.scope, "activity", "user", "password=fictional-password",
            "Bearer fictional-token", summary="## Plan\n\n- token=fictional-secret",
        )
        self.assertEqual(len(state["recent"]), 2)
        self.assertEqual(state["recent"][0]["role"], "user")
        self.assertEqual(state["recent"][1]["senderId"], self.scope.agent_id)
        self.assertEqual(state["recent"][0]["at"], self.clock())
        self.assertEqual(state["seen"], ["activity"])
        self.assertEqual(state["tasks"], initial["tasks"])
        self.assertNotIn("fictional", json.dumps(state))
        duplicate = await append_exchange(
            self.store, self.scope, "activity", "user", "replay", "replay", summary="stale summary"
        )
        self.assertEqual(duplicate, state)

    async def test_append_keeps_last_sixteen_messages_and_optional_summary(self) -> None:
        for index in range(10):
            await append_exchange(
                self.store, self.scope, f"activity-{index}", "user", f"question {index}",
                f"answer {index}", summary="# Persistent summary" if index == 0 else None,
            )
        state = await self.store.read(self.scope)
        self.assertEqual(len(state["recent"]), MAX_RECENT_MESSAGES)
        self.assertEqual(state["recent"][0]["activityId"], "activity-2")
        self.assertEqual(state["recent"][-1]["content"], "answer 9")
        self.assertEqual(state["summary"], "# Persistent summary")
        self.assertEqual(len(state["seen"]), 10)
        state = await append_exchange(self.store, self.scope, "clear", "user", "", "", summary="")
        self.assertEqual(state["summary"], "")

    async def test_append_caps_all_text_at_eight_thousand_characters(self) -> None:
        state = await append_exchange(
            self.store, self.scope, "activity", "user", "u" * 9000, "a" * 9000, "s" * 9000
        )
        self.assertEqual(len(state["summary"]), MAX_CONTENT_CHARS)
        self.assertTrue(all(len(message["content"]) == MAX_CONTENT_CHARS for message in state["recent"]))

    async def test_expiry_returns_empty_state_but_updates_original_version(self) -> None:
        store = self.new_store(ttl_seconds=60, max_attempts=1)
        await append_exchange(store, self.scope, "old", "user", "old", "old", summary="old")
        await mark_welcomed(store, self.scope)
        before = await self.raw_row()
        assert before is not None
        self.clock.advance(60)
        fresh = await store.read(self.scope)
        self.assertEqual(fresh["summary"], "")
        self.assertEqual(fresh["recent"], [])
        self.assertEqual(fresh["seen"], [])
        self.assertFalse(fresh["welcomed"])
        self.assertEqual(fresh["updatedAt"], self.clock())
        self.assertEqual(await self.raw_row(), before)  # Expiry is not a delete.
        self.assertTrue(await claim_activity(store, self.scope, "old"))
        after = await self.raw_row()
        assert after is not None
        self.assertEqual(after[0], before[0] + 1)

    async def test_concurrent_updates_after_expiry_keep_both_mutations(self) -> None:
        await self.seed()
        self.clock.advance(DEFAULT_TTL_SECONDS)
        left, right = self.colliding_pair()

        def first(state: dict[str, Any]) -> None:
            state["tasks"]["new-left"] = {"status": "draft"}

        def second(state: dict[str, Any]) -> None:
            state["tasks"]["new-right"] = {"status": "draft"}

        await asyncio.wait_for(
            asyncio.gather(left.update(self.scope, first), right.update(self.scope, second)), 15
        )
        state = await self.store.read(self.scope)
        self.assertEqual(set(state["tasks"]), {"new-left", "new-right"})

    async def test_reads_duplicates_and_noops_do_not_renew_ttl(self) -> None:
        await claim_activity(self.store, self.scope, "activity")
        await mark_welcomed(self.store, self.scope)
        before = await self.raw_row()
        self.clock.advance(10)
        await self.store.read(self.scope)
        await self.store.update(self.scope, lambda state: None)
        self.assertFalse(await claim_activity(self.store, self.scope, "activity"))
        self.assertFalse(await mark_welcomed(self.store, self.scope))
        self.assertEqual(await self.raw_row(), before)

    async def test_expired_corruption_is_not_silently_forgotten(self) -> None:
        await self.seed()
        await self.replace_payload(b"broken")
        self.clock.advance(DEFAULT_TTL_SECONDS + 1)
        with self.assertRaises(CorruptStateError):
            await self.store.read(self.scope)
        with self.assertRaises(CorruptStateError):
            await claim_activity(self.store, self.scope, "new")

    async def test_wrong_identity_and_schema_fail_closed(self) -> None:
        state = await self.seed()
        variants = []
        for key in ("tenantId", "agentId", "conversationId"):
            wrong = copy.deepcopy(state)
            wrong["scope"][key] = "wrong"
            variants.append(wrong)
        for schema in (2, True, "1"):
            wrong = copy.deepcopy(state)
            wrong["schemaVersion"] = schema
            variants.append(wrong)
        missing = copy.deepcopy(state)
        del missing["tasks"]
        variants.append(missing)
        extra = copy.deepcopy(state)
        extra["unknown"] = "unsupported"
        variants.append(extra)
        for wrong in variants:
            with self.subTest(state=wrong):
                await self.replace_payload(self.encoded(wrong))
                before = await self.raw_row()
                with self.assertRaises(CorruptStateError):
                    await self.store.read(self.scope)
                with self.assertRaises(CorruptStateError):
                    await self.store.update(self.scope, lambda value: value.update(summary="reset"))
                self.assertEqual(await self.raw_row(), before)

    async def test_corrupt_gzip_json_and_duplicate_properties_fail_closed(self) -> None:
        state = await self.seed()
        valid = self.encoded(state)
        bad_crc = bytearray(valid)
        bad_crc[-8] ^= 1
        raw = json.dumps(state)
        duplicate = raw[:-1] + ', "schemaVersion": 1}'
        variants = [
            b"", b"not gzip", valid[:-4], valid + b"trailing", valid + valid,
            bytes(bad_crc), gzip.compress(b"not JSON"), gzip.compress(b"\xff"),
            gzip.compress(duplicate.encode()), gzip.compress(b"[]"),
        ]
        for index, payload in enumerate(variants):
            with self.subTest(case=index):
                await self.replace_payload(payload)
                with self.assertRaises(CorruptStateError):
                    await self.store.read(self.scope)

    async def test_invalid_field_types_and_nonfinite_numbers_fail_closed(self) -> None:
        original = await self.seed()
        variants = [
            ("welcomed", 1), ("active", None), ("updatedAt", True), ("updatedAt", float("nan")),
            ("updatedAt", -1), ("tasks", []), ("tasks", {"bad": "not a record"}),
            ("seen", ["duplicate", "duplicate"]), ("seen", [None]), ("summary", 17),
            ("recent", [{"role": "user", "content": "missing fields"}]),
        ]
        for field, value in variants:
            with self.subTest(field=field, value=value):
                state = copy.deepcopy(original)
                state[field] = value
                await self.replace_payload(self.encoded(state))
                with self.assertRaises(CorruptStateError):
                    await self.store.read(self.scope)

    async def test_invalid_transform_does_not_replace_valid_state(self) -> None:
        await self.seed()
        before = await self.raw_row()

        def wrong_identity(state: dict[str, Any]) -> None:
            state["scope"]["tenantId"] = "wrong"

        def cyclic_task(state: dict[str, Any]) -> None:
            task: dict[str, Any] = {}
            task["self"] = task
            state["tasks"]["cycle"] = task

        def non_json_task(state: dict[str, Any]) -> None:
            state["tasks"]["bad"] = {"tuple": (1, 2)}

        def fails(state: dict[str, Any]) -> None:
            state["summary"] = "never committed"
            raise ValueError("test transform failure")

        for transform in (wrong_identity, cyclic_task, non_json_task):
            with self.assertRaises(CorruptStateError):
                await self.store.update(self.scope, transform)
        with self.assertRaises(ValueError):
            await self.store.update(self.scope, fails)
        self.assertEqual(await self.raw_row(), before)

    async def test_transform_must_be_synchronous_and_return_none(self) -> None:
        async def not_synchronous(state: dict[str, Any]) -> None:
            state["active"] = True

        with self.assertRaises(TypeError):
            await self.store.update(self.scope, not_synchronous)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            await self.store.update(self.scope, lambda state: {"active": True})  # type: ignore[arg-type]
        self.assertIsNone(await self.raw_row())

    async def test_retained_transform_references_do_not_mutate_committed_result(self) -> None:
        retained = []

        def transform(state: dict[str, Any]) -> None:
            state["tasks"]["draft"] = {"status": "draft"}
            retained.append(state)

        result = await self.store.update(self.scope, transform)
        retained[0]["tasks"]["draft"]["status"] = "changed outside update"
        self.assertEqual(result["tasks"]["draft"]["status"], "draft")
        self.assertEqual((await self.store.read(self.scope))["tasks"]["draft"]["status"], "draft")

    async def test_json_type_changes_are_not_mistaken_for_noops(self) -> None:
        await self.store.update(self.scope, lambda state: state["tasks"].update(item={"value": 1}))
        before = await self.raw_row()
        assert before is not None

        def change_type(state: dict[str, Any]) -> None:
            state["tasks"]["item"]["value"] = True

        result = await self.store.update(self.scope, change_type)
        self.assertIs(result["tasks"]["item"]["value"], True)
        self.assertIs((await self.store.read(self.scope))["tasks"]["item"]["value"], True)
        after = await self.raw_row()
        assert after is not None
        self.assertEqual(after[0], before[0] + 1)

    async def test_field_bounds_reject_oversized_direct_updates(self) -> None:
        await self.seed()
        before = await self.raw_row()
        changes = [
            {"summary": "x" * (MAX_CONTENT_CHARS + 1)},
            {"seen": [str(index) for index in range(MAX_SEEN_IDS + 1)]},
            {"recent": [
                {"role": "user", "content": "x", "senderId": "user", "activityId": str(index), "at": self.clock()}
                for index in range(MAX_RECENT_MESSAGES + 1)
            ]},
        ]
        for change in changes:
            with self.assertRaises(StateTooLargeError):
                await self.store.update(self.scope, lambda state: state.update(change))
        self.assertEqual(await self.raw_row(), before)

    async def test_compressed_and_uncompressed_write_limits(self) -> None:
        store = self.new_store(max_uncompressed_bytes=512)
        with self.assertRaises(StateTooLargeError):
            await store.update(self.scope, lambda state: state.update(summary="x" * 600))
        self.assertIsNone(await self.raw_row())
        store = self.new_store(max_compressed_bytes=16)
        with self.assertRaises(StateTooLargeError):
            await store.update(self.scope, lambda state: state.update(summary="new"))
        self.assertIsNone(await self.raw_row())

    async def test_document_byte_limit_applies_to_combined_fields_and_utf8(self) -> None:
        store = self.new_store(max_uncompressed_bytes=700)

        def multiple_small_fields(state: dict[str, Any]) -> None:
            state["tasks"] = {"one": {"note": "a" * 300}, "two": {"note": "b" * 300}}

        with self.assertRaises(StateTooLargeError):
            await store.update(self.scope, multiple_small_fields)
        store = self.new_store(max_uncompressed_bytes=400)
        with self.assertRaises(StateTooLargeError):
            await store.update(self.scope, lambda state: state.update(summary="\U0001f642" * 200))
        self.assertIsNone(await self.raw_row())

    async def test_oversized_stored_payload_and_gzip_bomb_fail_closed(self) -> None:
        state = await self.seed()
        await self.replace_payload(b"x" * (DEFAULT_MAX_COMPRESSED_BYTES + 1))
        with self.assertRaises(StateTooLargeError):
            await self.store.read(self.scope)
        state["tasks"]["bomb"] = {"text": "x" * 20_000}
        await self.replace_payload(self.encoded(state))
        store = self.new_store(max_uncompressed_bytes=4096)
        with self.assertRaises(StateTooLargeError):
            await store.read(self.scope)

    async def test_deep_task_json_is_rejected(self) -> None:
        state = await self.seed()
        nested: dict[str, Any] = {}
        for _ in range(MAX_JSON_DEPTH + 2):
            nested = {"nested": nested}
        state["tasks"]["deep"] = nested
        await self.replace_payload(self.encoded(state))
        with self.assertRaises(CorruptStateError):
            await self.store.read(self.scope)

    async def test_traversal_ids_are_hashed_not_used_as_paths(self) -> None:
        scope = ChatScope("../../tenant", "C:\\agent\\..\\other", "../../conversation?x=1")
        await claim_activity(self.store, scope, "../activity")
        expected = hashlib.sha256(json.dumps(
            [scope.tenant_id, scope.agent_id, scope.conversation_id],
            ensure_ascii=False, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        self.assertEqual(scope.storage_key, expected)
        self.assertRegex(scope.storage_key, r"\A[0-9a-f]{64}\Z")

        def keys() -> list[str]:
            with closing(sqlite3.connect(self.path)) as connection:
                return [row[0] for row in connection.execute("SELECT storage_key FROM conversation_memory")]

        self.assertEqual(await asyncio.to_thread(keys), [scope.storage_key])
        self.assertEqual((await self.store.read(scope))["scope"], scope.to_dict())
        self.assertEqual(list(Path(self.directory.name).iterdir()), [self.path.parent])

    async def test_unavailable_sqlite_never_falls_back_to_empty_state(self) -> None:
        with patch.object(self.store, "_read_sync", side_effect=sqlite3.OperationalError("unavailable")):
            with self.assertRaises(StoreUnavailableError):
                await self.store.read(self.scope)

    async def test_close_is_async_idempotent_and_prevents_further_operations(self) -> None:
        await self.store.aclose()
        await self.store.close()
        with self.assertRaises(StoreClosedError):
            await self.store.read(self.scope)
        with self.assertRaises(StoreClosedError):
            await claim_activity(self.store, self.scope, "new")
        other = self.new_store()
        async with other:
            await other.read(self.scope)
        with self.assertRaises(StoreClosedError):
            await other.read(self.scope)

    async def test_factory_production_without_blob_fails_even_with_local_path(self) -> None:
        for environment in ("production", " PRODUCTION "):
            with patch.dict(os.environ, {
                "AUTOPILOT_ENVIRONMENT": environment,
                "AUTOPILOT_STATE_PATH": str(self.path),
            }, clear=True):
                with self.assertRaises(StoreConfigurationError):
                    create_conversation_store()
        self.assertFalse(self.path.exists())

    async def test_factory_default_is_user_cache_and_constructor_is_lazy(self) -> None:
        with patch.dict(os.environ, {
            "LOCALAPPDATA": self.directory.name, "XDG_CACHE_HOME": self.directory.name,
            "AUTOPILOT_STATE_TTL_SECONDS": "120",
        }, clear=True):
            store = create_conversation_store()
        self.addAsyncCleanup(store.close)
        self.assertIsInstance(store, SQLiteStore)
        assert isinstance(store, SQLiteStore)
        self.assertEqual(store.path, Path(self.directory.name) / "ess-mcp" / "autopilot" / "conversation-memory.sqlite3")
        self.assertEqual(store.ttl_seconds, 120)
        self.assertFalse(store.path.exists())

    async def test_factory_uses_explicit_local_path(self) -> None:
        with patch.dict(os.environ, {"AUTOPILOT_STATE_PATH": str(self.path)}, clear=True):
            store = create_conversation_store()
        self.addAsyncCleanup(store.close)
        self.assertIsInstance(store, SQLiteStore)
        assert isinstance(store, SQLiteStore)
        self.assertEqual(store.path, self.path)
        self.assertEqual(store.ttl_seconds, DEFAULT_TTL_SECONDS)

    async def test_factory_azure_is_lazy_and_never_falls_back(self) -> None:
        with patch.dict(os.environ, {
            "AUTOPILOT_ENVIRONMENT": "production",
            "AUTOPILOT_STORAGE_ACCOUNT_URL": "https://account123.blob.core.windows.net",
            "AUTOPILOT_STATE_PATH": str(self.path),
        }, clear=True):
            store = create_conversation_store()
        self.addAsyncCleanup(store.close)
        self.assertIsInstance(store, AzureBlobStore)
        assert isinstance(store, AzureBlobStore)
        self.assertEqual(store.container, "autopilot-state")
        self.assertIsNone(store._credential)
        self.assertIsNone(store._service)
        self.assertFalse(self.path.exists())
        with patch.dict(os.environ, {
            "AUTOPILOT_STORAGE_ACCOUNT_URL": "https://arbitrary.example",
            "AUTOPILOT_STATE_PATH": str(self.path),
        }, clear=True):
            with self.assertRaises(StoreConfigurationError):
                create_conversation_store()


class FakeHttpResponseError(Exception):
    def __init__(self, status_code: int, error_code: str) -> None:
        super().__init__("Fictional SDK failure; never a live service response.")
        self.status_code = status_code
        self.error_code = error_code


class FakeResourceNotFoundError(FakeHttpResponseError):
    pass


class AzureContractTests(unittest.IsolatedAsyncioTestCase):
    """Dependency-free tests for request bounds, ETags, conflicts and cleanup."""

    async def asyncSetUp(self) -> None:
        self.clock = Clock()
        self.scope = ChatScope("tenant", "agent", "chat")
        self.credential = SimpleNamespace(close=AsyncMock())
        self.blob = SimpleNamespace(download_blob=AsyncMock(), upload_blob=AsyncMock())
        self.container = SimpleNamespace(get_blob_client=Mock(return_value=self.blob))
        self.service = SimpleNamespace(
            get_container_client=Mock(return_value=self.container), close=AsyncMock()
        )
        self.make_credential = Mock(return_value=self.credential)
        self.make_service = Mock(return_value=self.service)
        self.if_not_modified = object()
        modules = {
            name: ModuleType(name) for name in (
                "azure", "azure.core", "azure.core.exceptions", "azure.identity", "azure.identity.aio",
                "azure.storage", "azure.storage.blob", "azure.storage.blob.aio",
            )
        }
        for name, module in modules.items():
            setattr(module, "__path__", [])
            if "." in name:
                parent, child = name.rsplit(".", 1)
                setattr(modules[parent], child, module)
        setattr(modules["azure.identity.aio"], "ManagedIdentityCredential", self.make_credential)
        setattr(modules["azure.storage.blob.aio"], "BlobServiceClient", self.make_service)
        setattr(modules["azure.storage.blob"], "ContentSettings", SimpleNamespace)
        setattr(modules["azure.core"], "MatchConditions", SimpleNamespace(IfNotModified=self.if_not_modified))
        setattr(modules["azure.core.exceptions"], "HttpResponseError", FakeHttpResponseError)
        setattr(modules["azure.core.exceptions"], "ResourceNotFoundError", FakeResourceNotFoundError)
        module_patch = patch.dict(sys.modules, modules)
        module_patch.start()
        self.addCleanup(module_patch.stop)
        self.store = AzureBlobStore("https://account123.blob.core.windows.net", clock=self.clock)
        self.addAsyncCleanup(self.store.close)
        self.state = {
            "schemaVersion": 1, "scope": self.scope.to_dict(), "summary": "# Memory", "recent": [],
            "seen": [], "tasks": {}, "welcomed": False, "active": False, "updatedAt": self.clock(),
        }

    def download(self, state: dict[str, Any] | None = None, *, etag: Any = '"version-7"') -> Any:
        payload = ConversationMemoryTests.encoded(self.state if state is None else state)
        return SimpleNamespace(properties=SimpleNamespace(etag=etag), readall=AsyncMock(return_value=payload))

    async def test_operator_reset_deletes_only_this_stores_state_blobs(self) -> None:
        kept = ChatScope("tenant", "agent", "control-room:policies")
        names = [f"{self.scope.storage_key}.json.gz", f"{kept.storage_key}.json.gz", "unrelated/readme.txt"]

        async def list_blobs(**_kwargs: Any) -> Any:
            for name in names:
                yield SimpleNamespace(name=name)

        self.container.list_blobs = list_blobs
        self.container.delete_blob = AsyncMock()
        self.assertEqual(await self.store.clear_all(keep=(kept,)), 1)
        self.container.delete_blob.assert_awaited_once_with(f"{self.scope.storage_key}.json.gz", logging_enable=False)

    async def test_explicit_managed_identity_etag_and_bounded_range_request(self) -> None:
        self.make_credential.assert_not_called()
        self.blob.download_blob.return_value = self.download()
        with patch.dict(os.environ, {"AZURE_CLIENT_ID": "uami-client-id"}):
            result = await self.store.update(self.scope, lambda state: state.update(active=True))
        self.assertTrue(result["active"])
        self.make_credential.assert_called_once_with(client_id="uami-client-id")
        self.assertIs(self.make_service.call_args.kwargs["credential"], self.credential)
        self.assertEqual(self.make_service.call_args.kwargs["retry_total"], 0)
        self.service.get_container_client.assert_called_once_with("autopilot-state")
        self.assertEqual(self.container.get_blob_client.call_args.args[0], f"{self.scope.storage_key}.json.gz")
        request = self.blob.download_blob.call_args.kwargs
        self.assertEqual(request["offset"], 0)
        self.assertEqual(request["length"], DEFAULT_MAX_COMPRESSED_BYTES + 1)
        upload = self.blob.upload_blob.call_args
        self.assertTrue(upload.kwargs["overwrite"])
        self.assertEqual(upload.kwargs["etag"], '"version-7"')
        self.assertIs(upload.kwargs["match_condition"], self.if_not_modified)
        self.assertEqual(upload.kwargs["content_settings"].content_type, "application/gzip")
        self.assertFalse(upload.kwargs["logging_enable"])
        self.assertEqual(json.loads(gzip.decompress(upload.args[0])), result)

    async def test_create_collision_retries_with_winners_etag_and_state(self) -> None:
        winner = copy.deepcopy(self.state)
        winner["tasks"]["existing-draft"] = {"status": "draft"}
        self.blob.download_blob.side_effect = [
            FakeResourceNotFoundError(404, "BlobNotFound"), self.download(winner),
        ]
        self.blob.upload_blob.side_effect = [FakeHttpResponseError(409, "BlobAlreadyExists"), None]
        result = await self.store.update(self.scope, lambda state: state.update(active=True))
        first, second = self.blob.upload_blob.call_args_list
        self.assertFalse(first.kwargs["overwrite"])
        self.assertNotIn("etag", first.kwargs)
        self.assertEqual(second.kwargs["etag"], '"version-7"')
        self.assertEqual(result["tasks"], winner["tasks"])

    async def test_only_missing_blob_is_empty_not_missing_container_or_denied_access(self) -> None:
        self.blob.download_blob.side_effect = FakeResourceNotFoundError(404, "BlobNotFound")
        self.assertEqual((await self.store.read(self.scope))["summary"], "")
        for error in (
            FakeResourceNotFoundError(404, "ContainerNotFound"),
            FakeHttpResponseError(403, "AuthorizationPermissionMismatch"),
            OSError("fictional transport failure"),
        ):
            self.blob.download_blob.side_effect = error
            with self.assertRaises(StoreUnavailableError):
                await self.store.read(self.scope)
        self.blob.upload_blob.assert_not_awaited()

    async def test_etag_conflicts_stop_at_five_and_other_failures_do_not_retry(self) -> None:
        self.blob.download_blob.return_value = self.download()
        self.blob.upload_blob.side_effect = FakeHttpResponseError(412, "ConditionNotMet")
        with self.assertRaises(ConcurrentUpdateError):
            await self.store.update(self.scope, lambda state: state.update(active=True))
        self.assertEqual(self.blob.upload_blob.await_count, 5)
        for error in (
            FakeHttpResponseError(412, "LeaseIdMismatchWithBlobOperation"),
            FakeHttpResponseError(403, "AuthorizationPermissionMismatch"),
            OSError("fictional ambiguous write response"),
        ):
            before = self.blob.upload_blob.await_count
            self.blob.upload_blob.side_effect = error
            with self.assertRaises(StoreUnavailableError):
                await self.store.update(self.scope, lambda state: state.update(active=True))
            self.assertEqual(self.blob.upload_blob.await_count, before + 1)

    async def test_expired_blob_still_uses_existing_etag(self) -> None:
        self.state["updatedAt"] = self.clock() - DEFAULT_TTL_SECONDS
        self.state["seen"] = ["old"]
        self.blob.download_blob.return_value = self.download()
        self.assertTrue(await claim_activity(self.store, self.scope, "old"))
        self.assertEqual(self.blob.upload_blob.call_args.kwargs["etag"], '"version-7"')
        persisted = json.loads(gzip.decompress(self.blob.upload_blob.call_args.args[0]))
        self.assertEqual(persisted["summary"], "")
        self.assertEqual(persisted["seen"], ["old"])

    async def test_missing_etag_and_oversize_blob_fail_closed(self) -> None:
        self.blob.download_blob.return_value = self.download(etag=None)
        with self.assertRaises(CorruptStateError):
            await self.store.read(self.scope)
        download = self.download()
        download.readall.return_value = b"x" * (DEFAULT_MAX_COMPRESSED_BYTES + 1)
        self.blob.download_blob.return_value = download
        with self.assertRaises(StateTooLargeError):
            await self.store.read(self.scope)

    async def test_both_async_resources_close_even_when_service_close_fails(self) -> None:
        self.blob.download_blob.return_value = self.download()
        await self.store.read(self.scope)
        self.service.close.side_effect = OSError("fictional close failure")
        with self.assertRaises(StoreUnavailableError):
            await self.store.close()
        self.service.close.assert_awaited_once()
        self.credential.close.assert_awaited_once()
        await self.store.close()
        with self.assertRaises(StoreClosedError):
            await self.store.read(self.scope)

    async def test_initialization_failure_closes_created_credential(self) -> None:
        self.make_service.side_effect = ValueError("fictional SDK initialization failure")
        with self.assertRaises(StoreUnavailableError):
            await self.store.read(self.scope)
        self.credential.close.assert_awaited_once()
        self.assertIsNone(self.store._service)


class ValidationAndRedactionTests(unittest.TestCase):
    def test_scope_is_frozen_validated_and_array_encoding_is_unambiguous(self) -> None:
        scope = ChatScope("tenant", "agent", "chat")
        with self.assertRaises(FrozenInstanceError):
            setattr(scope, "tenant_id", "changed")
        for value in ("", " ", "a\n", "a\x00", "\ud800", "x" * (MAX_ID_CHARS + 1), None, 123):
            for index in range(3):
                identifiers: list[Any] = ["tenant", "agent", "chat"]
                identifiers[index] = value
                with self.subTest(value=repr(value), index=index):
                    with self.assertRaises(ValueError):
                        ChatScope(*identifiers)
        self.assertNotEqual(ChatScope("ab", "c", "d").storage_key, ChatScope("a", "bc", "d").storage_key)
        self.assertEqual(scope.storage_key, ChatScope("tenant", "agent", "chat").storage_key)

    def test_azure_rejects_noncanonical_urls_credentials_sas_and_paths(self) -> None:
        for url in (
            "http://account123.blob.core.windows.net", "https://account123.blob.core.windows.net/",
            "https://user:password@account123.blob.core.windows.net",
            "https://account123.blob.core.windows.net?sig=fictional", "https://account123.blob.core.windows.net#fragment",
            "https://account123.blob.core.windows.net/container", "https://account123.blob.core.windows.net:443",
            "https://account123.blob.core.windows.net.evil.example", "https://ACCOUNT123.blob.core.windows.net",
            "DefaultEndpointsProtocol=https;AccountName=account123;AccountKey=fictional", "https://127.0.0.1",
        ):
            with self.subTest(url=url), self.assertRaises(StoreConfigurationError):
                AzureBlobStore(url)
        for container in ("ab", "Uppercase", "a--b", "-abc", "abc-", "a/b", "$root", "a" * 64):
            with self.subTest(container=container), self.assertRaises(StoreConfigurationError):
                AzureBlobStore("https://account123.blob.core.windows.net", container)

    def test_relative_paths_and_invalid_bounds_are_rejected(self) -> None:
        for path in ("relative.sqlite3", ":memory:", ""):
            with self.assertRaises(StoreConfigurationError):
                SQLiteStore(path)
        for options in (
            {"ttl_seconds": 0}, {"ttl_seconds": -1}, {"ttl_seconds": float("inf")},
            {"ttl_seconds": float("nan")}, {"ttl_seconds": True}, {"max_attempts": 0},
            {"max_attempts": 6}, {"max_attempts": True}, {"max_compressed_bytes": 0},
            {"max_uncompressed_bytes": -1}, {"max_compressed_bytes": 1.5},
        ):
            with self.subTest(options=options), self.assertRaises(StoreConfigurationError):
                SQLiteStore(Path.home() / "unused-memory.sqlite3", **options)

    def test_redacts_bearer_jwt_and_private_keys(self) -> None:
        jwt = "eyJhbGciOiJub25lIn0.eyJzdWIiOiJmaWN0aW9uYWwifQ.signature"
        text = (
            "# Notes\nAuthorization: bEaReR fictional-bearer\nJWT: " + jwt + "\n"
            "-----BEGIN RSA PRIVATE KEY-----\nfictional-key-material\n-----END RSA PRIVATE KEY-----\n"
            "- Keep this Markdown."
        )
        result = scrub_memory_text(text)
        for secret in ("fictional-bearer", jwt, "fictional-key-material", "BEGIN RSA"):
            self.assertNotIn(secret, result)
        self.assertIn("# Notes", result)
        self.assertIn("- Keep this Markdown.", result)
        self.assertIn("Bearer [REDACTED]", result)
        self.assertNotIn("material", scrub_memory_text("-----BEGIN PRIVATE KEY-----\nmaterial"))

    def test_redacts_assignment_variants_and_unterminated_quotes(self) -> None:
        for text, secret in (
            ("password=fictional-password", "fictional-password"),
            ("PASSWORD: 'fictional password with spaces'", "fictional password"),
            ('{"access_token": "fictional-token"}', "fictional-token"),
            ('clientSecret="fictional-secret"', "fictional-secret"),
            ("refreshToken: fictional-refresh", "fictional-refresh"),
            ("secret = fictional-value; harmless=true", "fictional-value"),
            ("api_key=fictional-api", "fictional-api"),
            ("AccountKey=fictional-account", "fictional-account"),
            ("private_key: fictional-private", "fictional-private"),
            ('password="fictional unterminated value', "fictional"),
            ("token=Bearer fictional-bearer", "fictional-bearer"),
            ("password=`fictional-inline-code`", "fictional-inline-code"),
        ):
            with self.subTest(text=text):
                redacted = scrub_memory_text(text)
                self.assertNotIn(secret, redacted)
                self.assertIn("[REDACTED]", redacted)

    def test_redaction_is_idempotent_for_existing_placeholders(self) -> None:
        text = 'password=[REDACTED]; token="[REDACTED]"; secret=`[REDACTED]`\nBearer [REDACTED]'
        self.assertEqual(scrub_memory_text(text), text)
        once = scrub_memory_text("password=fictional-value")
        self.assertEqual(scrub_memory_text(once), once)

    def test_redacts_before_truncating_and_preserves_normal_markdown(self) -> None:
        text = "n" * 7950 + "\npassword=" + "fictional-value" * 1000
        redacted = scrub_memory_text(text)
        self.assertLessEqual(len(redacted), MAX_CONTENT_CHARS)
        self.assertNotIn("fictional-value", redacted)
        markdown = "## Group functions\n\n- **Draft** remains pending human review.\n"
        self.assertEqual(scrub_memory_text(markdown), markdown)
        self.assertEqual(len(scrub_memory_text("x" * 10_000)), MAX_CONTENT_CHARS)
        with self.assertRaises(TypeError):
            scrub_memory_text(None)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()