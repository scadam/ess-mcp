"""Control-room model contracts: bounded feed, host-enforced approvals, durable copy."""

from __future__ import annotations

import unittest

from demo_agent.control_room import (
    TEMPLATE_KEY, ActivityFeed, ControlRoomPersistence, PolicyBook, tool_phrase,
)
from demo_agent.conversation_memory import Store, _Record

TENANT = "11111111-1111-4111-8111-111111111111"
AGENT = "33333333-3333-4333-8333-333333333333"
INSTANCE = "44444444-4444-4444-8444-444444444444"
SKILLS = ("compliance-case-resolution", "incident-triage", "team-review")
SERVERS = ("workday", "servicenow", "coupa", "salesforce", "workiq")


class MemoryStore(Store):
    def __init__(self) -> None:
        super().__init__()
        self.records: dict[str, _Record] = {}

    async def _read_record(self, key: str) -> _Record | None:
        return self.records.get(key)

    async def _compare_and_swap(self, key: str, version: int | str | None, payload: bytes) -> bool:
        record = self.records.get(key)
        if (record.version if record else None) != version:
            return False
        self.records[key] = _Record(int(version or 0) + 1, payload)
        return True


class Clock:
    def __init__(self, now: float = 1_800_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


class ActivityFeedTests(unittest.TestCase):
    def test_records_newest_first_and_polls_incrementally_by_revision(self) -> None:
        clock = Clock()
        feed = ActivityFeed(clock=clock)
        first = feed.record(INSTANCE, "email", "Received an email", detail="Body")
        clock.now += 1
        second = feed.record(INSTANCE, "teams-out", "Replied in Teams")
        self.assertEqual([event["id"] for event in feed.events(INSTANCE)], [second["id"], first["id"]])
        self.assertEqual([event["id"] for event in feed.events(INSTANCE, after=first["rev"])], [second["id"]])
        self.assertEqual(feed.events(INSTANCE, after=feed.revision), [])
        self.assertEqual(feed.events(INSTANCE, categories=["email"])[0]["title"], "Received an email")

    def test_tool_call_completes_in_place_with_a_new_revision(self) -> None:
        feed = ActivityFeed(clock=Clock())
        call = feed.record(INSTANCE, "tool", "Opened a Salesforce case", status="working", callId="run-1:c1", runId="run-1")
        seen = feed.revision
        completed = feed.complete_call("run-1:c1", status="ok", result='{"created": true}')
        self.assertEqual(completed["id"], call["id"])
        self.assertEqual(completed["status"], "ok")
        self.assertGreater(completed["rev"], seen)
        self.assertEqual([event["id"] for event in feed.events(INSTANCE, after=seen)], [call["id"]])
        self.assertIsNone(feed.complete_call("run-1:c1", status="ok"))

    def test_settling_a_run_marks_only_its_unfinished_calls(self) -> None:
        feed = ActivityFeed(clock=Clock())
        feed.record(INSTANCE, "tool", "Call A", status="working", callId="run-1:a", runId="run-1")
        feed.record(INSTANCE, "tool", "Call B", status="working", callId="run-2:b", runId="run-2")
        feed.settle_run("run-1")
        statuses = {event["title"]: event["status"] for event in feed.events(INSTANCE)}
        self.assertEqual(statuses, {"Call A": "error", "Call B": "working"})

    def test_text_is_scrubbed_and_bounded_and_unknown_values_are_normalized(self) -> None:
        feed = ActivityFeed(clock=Clock())
        event = feed.record("not a key!", "made-up", "x" * 500, detail="password=hunter2 " + "y" * 3000, status="odd")
        self.assertEqual(event["instance"], TEMPLATE_KEY)
        self.assertEqual((event["category"], event["status"]), ("lifecycle", "info"))
        self.assertLessEqual(len(event["title"]), 240)
        self.assertLessEqual(len(event["detail"]), 1500)
        self.assertNotIn("hunter2", event["detail"])

    def test_ring_buffer_is_bounded_per_instance(self) -> None:
        feed = ActivityFeed(per_instance=5, clock=Clock())
        for index in range(12):
            feed.record(INSTANCE, "tool", f"Call {index}", status="working", callId=f"c{index}")
        titles = [event["title"] for event in feed.events(INSTANCE)]
        self.assertEqual(titles, [f"Call {index}" for index in range(11, 6, -1)])
        self.assertIsNone(feed.complete_call("c0", status="ok"))

    def test_summary_counts_the_day_and_meters_the_hour(self) -> None:
        clock = Clock()
        feed = ActivityFeed(clock=clock)
        feed.record(INSTANCE, "teams-in", "Message in")
        feed.record(INSTANCE, "teams-out", "Message out")
        feed.record(INSTANCE, "tool", "Failed call", status="error")
        clock.now += 30 * 60
        feed.record(INSTANCE, "email", "Email")
        summary = feed.summary(INSTANCE)
        self.assertEqual(summary["counts"]["teams"], 2)
        self.assertEqual(summary["counts"]["email"], 1)
        self.assertEqual(summary["counts"]["issue"], 1)
        self.assertEqual(sum(summary["meter"]), 4)
        self.assertEqual(summary["meter"][-1], 1)
        self.assertEqual(summary["lastIssue"]["title"], "Failed call")
        self.assertEqual(summary["last"]["title"], "Email")

    def test_restore_rejects_malformed_items_and_marks_inflight_calls_unknown(self) -> None:
        feed = ActivityFeed(clock=Clock())
        restored = feed.restore(INSTANCE, [
            {"id": "a", "at": 5, "category": "tool", "status": "working", "title": "Interrupted call"},
            {"id": "b", "at": 4, "category": "not-real", "status": "ok", "title": "Bad"},
            "junk",
        ])
        self.assertEqual(restored, 1)
        event = feed.events(INSTANCE)[0]
        self.assertEqual(event["status"], "info")
        self.assertIn("restarted", event["result"])


class PolicyBookTests(unittest.TestCase):
    def test_default_approves_everything_and_template_ignores_role_presets(self) -> None:
        book = PolicyBook()
        policy = book.effective(INSTANCE, "Finance Helper", SKILLS, SERVERS)
        self.assertEqual((policy["skills"], policy["servers"], policy["source"]), (sorted(SKILLS), sorted(SERVERS), "default"))
        self.assertEqual(book.effective(TEMPLATE_KEY, "Compliance Partner", SKILLS, SERVERS)["source"], "default")

    def test_compliance_partner_role_preset_is_least_privilege(self) -> None:
        policy = PolicyBook().effective(INSTANCE, "Compliance Partner", SKILLS, SERVERS)
        self.assertEqual(policy["skills"], ["compliance-case-resolution"])
        self.assertEqual(policy["servers"], ["coupa", "salesforce", "servicenow", "workiq"])
        self.assertEqual(policy["source"], "role-preset")
        hr = PolicyBook().effective(INSTANCE, "HR Agent", (*SKILLS, "hr-hiring-backlog-clearance"), SERVERS)
        self.assertEqual((hr["skills"], hr["servers"]), (["hr-hiring-backlog-clearance", "team-review"], ["servicenow", "workday"]))
        it = PolicyBook().effective(INSTANCE, "IT Agent", (*SKILLS, "zero-touch-service-desk"), SERVERS)
        self.assertEqual((it["skills"], it["servers"], it["preset"]),
                         (["incident-triage", "zero-touch-service-desk"], ["coupa", "servicenow", "workday"], "IT"))
        self.assertEqual(PolicyBook().effective(INSTANCE, "Italy Helper", SKILLS, SERVERS)["source"], "default")

    def test_operator_policy_is_validated_enforced_and_resettable(self) -> None:
        book = PolicyBook()
        with self.assertRaises(ValueError):
            book.set(INSTANCE, skills=["unknown-skill"], servers=[], actor="op", available_skills=SKILLS, available_servers=SERVERS)
        with self.assertRaises(ValueError):
            book.set(INSTANCE, skills="team-review", servers=[], actor="op", available_skills=SKILLS, available_servers=SERVERS)
        book.set(INSTANCE, skills=["team-review"], servers=["workday"], actor="Operator (id)",
                 available_skills=SKILLS, available_servers=SERVERS)
        common = {"skills": SKILLS, "servers": SERVERS}
        self.assertTrue(book.allows(INSTANCE, "Compliance Partner", skill="team-review", **common))
        self.assertFalse(book.allows(INSTANCE, "Compliance Partner", skill="compliance-case-resolution", **common))
        self.assertFalse(book.allows(INSTANCE, "Compliance Partner", server="salesforce", **common))
        self.assertEqual(book.effective(INSTANCE, "Compliance Partner", SKILLS, SERVERS)["source"], "operator")
        self.assertTrue(book.reset(INSTANCE))
        self.assertEqual(book.effective(INSTANCE, "Compliance Partner", SKILLS, SERVERS)["source"], "role-preset")

    def test_restore_ignores_malformed_records(self) -> None:
        book = PolicyBook()
        book.restore({INSTANCE: {"skills": ["team-review", 7, "../x"], "servers": ["workday"]}, "bad key!": {}})
        policy = book.effective(INSTANCE, "Anyone", SKILLS, SERVERS)
        self.assertEqual((policy["skills"], policy["servers"]), (["team-review"], ["workday"]))


class PhraseTests(unittest.TestCase):
    def test_calls_are_described_in_plain_language(self) -> None:
        self.assertEqual(tool_phrase("salesforce", "create_case"), "Opened a Salesforce case")
        self.assertEqual(tool_phrase("graph", "POST", "/chats"), "Opened a private Teams chat")
        self.assertEqual(tool_phrase("graph", "POST", "/chats/19:abc/messages"), "Posted a message in Teams")
        self.assertEqual(tool_phrase("workiq", "fetch", "/sites/x/lists/y/items/1"), "Read an evidence record through Work IQ")
        self.assertEqual(tool_phrase("servicenow", "list_incidents"), "ServiceNow: list incidents")


class PersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_feed_and_policies_survive_a_restart(self) -> None:
        store = MemoryStore()
        feed, book = ActivityFeed(clock=Clock()), PolicyBook()
        feed.record(INSTANCE, "email", "Received an email")
        feed.record(TEMPLATE_KEY, "lifecycle", "Came online")
        book.set(INSTANCE, skills=["team-review"], servers=["workday"], actor="op",
                 available_skills=SKILLS, available_servers=SERVERS)
        persistence = ControlRoomPersistence(store, TENANT, AGENT)
        await persistence.flush(feed)
        await persistence.save_policies(book)
        self.assertEqual(feed.take_dirty(), set())

        restored_feed, restored_book = ActivityFeed(clock=Clock()), PolicyBook()
        await ControlRoomPersistence(store, TENANT, AGENT).load(restored_feed, restored_book)
        self.assertEqual([event["title"] for event in restored_feed.events(INSTANCE)], ["Received an email"])
        self.assertEqual([event["title"] for event in restored_feed.events(TEMPLATE_KEY)], ["Came online"])
        self.assertEqual(restored_book.effective(INSTANCE, "x", SKILLS, SERVERS)["skills"], ["team-review"])
        self.assertEqual(restored_feed.take_dirty(), set())

    async def test_failed_flush_keeps_instances_dirty_for_retry(self) -> None:
        class Failing(MemoryStore):
            async def _compare_and_swap(self, key: str, version: int | str | None, payload: bytes) -> bool:
                raise OSError("offline")

        feed = ActivityFeed(clock=Clock())
        feed.record(INSTANCE, "email", "Received an email")
        with self.assertRaises(OSError):
            await ControlRoomPersistence(Failing(), TENANT, AGENT).flush(feed)
        self.assertEqual(feed.take_dirty(), {INSTANCE})


if __name__ == "__main__":
    unittest.main()
