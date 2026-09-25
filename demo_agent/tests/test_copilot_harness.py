"""The Copilot SDK harness against a scripted stand-in for the SDK client (no runtime, no network)."""

from __future__ import annotations

import asyncio
import contextvars
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from demo_agent.copilot_harness import (
    AgentSpec, CopilotHarness, FinishRun, RunSpec, parse_json_reply, skill_directories,
)

REQUEST = contextvars.ContextVar("request", default="")


def event(kind: str, agent_id: str | None = None, **data: Any) -> Any:
    return SimpleNamespace(type=SimpleNamespace(value=kind), agent_id=agent_id, data=SimpleNamespace(**data))


class FakeSession:
    def __init__(self, client: "FakeClient", config: dict[str, Any]) -> None:
        self.client, self.config = client, config
        self.session_id = config["session_id"]
        self.aborted = asyncio.Event()
        self.disconnected = False

    def emit(self, item: Any) -> None:
        self.config["on_event"](item)

    async def call(self, name: str, call_id: str, args: dict[str, Any], agent_id: str | None = None) -> Any:
        verdict = await self.config["hooks"]["on_pre_tool_use"]({"toolName": name, "toolArgs": args}, {})
        if verdict and verdict.get("permissionDecision") == "deny":
            return verdict
        self.emit(event("tool.execution_start", agent_id, tool_call_id=call_id, tool_name=name, arguments=args))
        tool = next(item for item in self.config["tools"] if item.name == name)
        return await tool.handler(SimpleNamespace(tool_call_id=call_id, arguments=args, session_id=self.session_id))

    async def send_and_wait(self, prompt: str, timeout: float) -> Any:
        return await self.client.script(self, prompt)

    async def abort(self) -> None:
        self.aborted.set()

    async def disconnect(self) -> None:
        self.disconnected = True


class FakeClient:
    def __init__(self, script: Any) -> None:
        self.script = script
        self.sessions: list[FakeSession] = []
        self.deleted: list[str] = []

    async def create_session(self, **config: Any) -> FakeSession:
        session = FakeSession(self, config)
        self.sessions.append(session)
        return session

    async def delete_session(self, session_id: str) -> None:
        self.deleted.append(session_id)


def reply(text: str) -> Any:
    return SimpleNamespace(data=SimpleNamespace(content=text))


class HarnessTests(unittest.IsolatedAsyncioTestCase):
    def spec(self, **overrides: Any) -> tuple[RunSpec, list[tuple[str, dict[str, Any]]], list[tuple]]:
        events: list[tuple[str, dict[str, Any]]] = []
        calls: list[tuple] = []

        async def dispatch(name: str, args: dict[str, Any], call_id: str, agent: str) -> str:
            calls.append((name, call_id, agent, REQUEST.get()))
            await asyncio.sleep(0)
            return json.dumps({"tool": name, "args": args})

        async def sink(kind: str, data: dict[str, Any]) -> None:
            events.append((kind, data))

        values = dict(run_id="run-1", model="gpt-5.4", instructions="Be precise.", prompt="Do the work.",
                      tools=[{"name": "coupa__list_invoices", "description": "List invoices.", "parameters": None}],
                      dispatch=dispatch, events=sink)
        values.update(overrides)
        return RunSpec(**values), events, calls

    async def run_spec(self, client: FakeClient, spec: RunSpec) -> Any:
        harness = CopilotHarness("https://example.openai.azure.com/", token=lambda: asyncio.sleep(0, "token"))
        harness._client = client
        return await harness.run(spec)

    async def test_session_is_empty_mode_shaped_and_each_call_runs_once_in_the_run_context(self) -> None:
        async def script(session: FakeSession, prompt: str) -> Any:
            session.emit(event("assistant.turn_start", model="gpt-5.4"))
            session.emit(event("assistant.usage", model="gpt-5.4", input_tokens=120, output_tokens=8, finish_reason="stop"))
            first, second = await asyncio.gather(session.call("coupa__list_invoices", "c1", {"status": "open"}),
                                                 session.call("coupa__list_invoices", "c1", {"status": "open"}))
            self.assertEqual(first.text_result_for_llm, second.text_result_for_llm)
            return reply("Three invoices are open.")

        client = FakeClient(script)
        spec, events, calls = self.spec()
        REQUEST.set("verified-request")
        result = await self.run_spec(client, spec)
        self.assertEqual((result.content, result.turns, result.finished_early), ("Three invoices are open.", 1, False))
        self.assertEqual(calls, [("coupa__list_invoices", "c1", "", "verified-request")])
        config = client.sessions[0].config
        self.assertEqual(config["available_tools"].to_list(), ["custom:*"])
        self.assertEqual(config["system_message"]["mode"], "customize")
        self.assertEqual(config["provider"]["type"], "azure")
        self.assertEqual(config["provider"]["base_url"], "https://example.openai.azure.com")
        self.assertTrue(all(tool.skip_permission for tool in config["tools"]))
        self.assertIsNone(config["custom_agents"])
        self.assertTrue(client.sessions[0].disconnected)
        self.assertEqual(client.deleted, [config["session_id"]])
        self.assertIn(("turn", {"turn": 1, "model": "gpt-5.4", "agent": ""}), events)
        self.assertIn(("usage", {"model": "gpt-5.4", "agent": "", "input_tokens": 120, "output_tokens": 8,
                                 "finish_reason": "stop", "cached_tokens": 0}), events)

    async def test_sub_agents_are_custom_agents_and_their_calls_are_attributed(self) -> None:
        async def script(session: FakeSession, prompt: str) -> Any:
            session.emit(event("tool.execution_start", None, tool_call_id="t1", tool_name="task",
                               arguments={"agent_type": "coupa-researcher", "prompt": "Read every chain."}))
            session.emit(event("subagent.started", "agent-7", tool_call_id="t1", agent_name="coupa-researcher",
                               agent_display_name="Coupa researcher", model="gpt-5.4-mini"))
            await session.call("coupa__list_invoices", "c9", {}, agent_id="agent-7")
            session.emit(event("subagent.completed", "agent-7", tool_call_id="t1", agent_name="coupa-researcher",
                               agent_display_name="Coupa researcher", model="gpt-5.4-mini", total_tool_calls=1,
                               total_tokens=900))
            session.emit(event("tool.execution_complete", None, tool_call_id="t1", success=True,
                               result=SimpleNamespace(content="7 chains, 2 exceptions.")))
            return reply("Done.")

        agent = AgentSpec(name="coupa-researcher", display_name="Coupa researcher", prompt="Read only.",
                          model="gpt-5.4-mini", tools=["coupa__list_invoices"], reasoning_effort="low")
        lead = AgentSpec(name="colleague", prompt="Own the run.", model="gpt-5.4", skills=["month-end"], infer=False)
        client = FakeClient(script)
        spec, events, calls = self.spec(agents=[agent], lead=lead, skill_directories=["/skills"])
        await self.run_spec(client, spec)
        config = client.sessions[0].config
        self.assertEqual(config["available_tools"].to_list(),
                         ["custom:*", "builtin:task", "builtin:read_agent", "builtin:list_agents"])
        self.assertEqual(config["agent"], "colleague")
        self.assertEqual([item["name"] for item in config["custom_agents"]], ["colleague", "coupa-researcher"])
        self.assertEqual(config["custom_agents"][0]["skills"], ["month-end"])
        self.assertEqual(config["custom_agents"][1]["reasoning_effort"], "low")
        self.assertEqual((config["enable_skills"], config["skill_directories"]), (True, ["/skills"]))
        self.assertEqual(calls[0][2], "Coupa researcher")
        phases = [(data["phase"], data.get("summary")) for kind, data in events if kind == "subagent"]
        self.assertEqual(phases, [("started", None), ("finished", "7 chains, 2 exceptions.")])
        started = next(data for kind, data in events if kind == "subagent")
        self.assertEqual((started["name"], started["model"], started["instructions"]),
                         ("Coupa researcher", "gpt-5.4-mini", "Read every chain."))

    async def test_a_finish_request_aborts_and_returns_its_answer(self) -> None:
        async def dispatch(name: str, args: dict[str, Any], call_id: str, agent: str) -> str:
            raise FinishRun("Waiting for your approval: approve abc123abc123")

        async def script(session: FakeSession, prompt: str) -> Any:
            session.emit(event("assistant.turn_start", model="gpt-5.4"))
            await session.call("coupa__list_invoices", "c1", {})
            await asyncio.wait_for(session.aborted.wait(), 1)
            return None

        client = FakeClient(script)
        spec, _, _ = self.spec(dispatch=dispatch)
        result = await self.run_spec(client, spec)
        self.assertEqual((result.content, result.finished_early), ("Waiting for your approval: approve abc123abc123", True))

    async def test_a_turn_check_stops_the_session_with_its_error(self) -> None:
        class Blocked(PermissionError):
            pass

        async def check(turn: int, model: str, agent: str) -> BaseException | None:
            return Blocked("guardrail model.tokens") if turn == 2 else None

        async def script(session: FakeSession, prompt: str) -> Any:
            session.emit(event("assistant.turn_start", model="gpt-5.4"))
            session.emit(event("assistant.turn_start", model="gpt-5.4"))
            await asyncio.wait_for(session.aborted.wait(), 1)
            return None

        spec, _, _ = self.spec(check_turn=check)
        with self.assertRaises(Blocked):
            await self.run_spec(FakeClient(script), spec)

    async def test_turn_limit_and_unoffered_tools(self) -> None:
        async def refuse(tool: str, args: dict[str, Any], agent: str) -> str | None:
            return "At most 4 sub-agents may run at once."

        async def script(session: FakeSession, prompt: str) -> Any:
            denied = await session.config["hooks"]["on_pre_tool_use"]({"toolName": "bash", "toolArgs": {}}, {})
            self.assertEqual(denied["permissionDecision"], "deny")
            refused = await session.config["hooks"]["on_pre_tool_use"]({"toolName": "task", "toolArgs": {}}, {})
            self.assertEqual(refused["permissionDecisionReason"], "At most 4 sub-agents may run at once.")
            for _ in range(3):
                session.emit(event("assistant.turn_start", model="gpt-5.4"))
            await asyncio.wait_for(session.aborted.wait(), 1)
            return None

        agent = AgentSpec(name="r", prompt="p", model="gpt-5.4-mini", tools=[])
        spec, _, _ = self.spec(max_turns=2, agents=[agent], check_builtin=refuse)
        with self.assertRaisesRegex(RuntimeError, "turn limit"):
            await self.run_spec(FakeClient(script), spec)

    async def test_session_errors_surface_without_upstream_detail(self) -> None:
        async def script(session: FakeSession, prompt: str) -> Any:
            session.emit(event("session.error", message="429 rate limited"))
            raise Exception("Session error: 429 rate limited")

        spec, _, _ = self.spec()
        with self.assertRaisesRegex(RuntimeError, "The Copilot session failed: 429 rate limited"):
            await self.run_spec(FakeClient(script), spec)


class ResumingClient(FakeClient):
    """Writes session state to disk like the runtime, and resumes it."""

    def __init__(self, script: Any, home: Path) -> None:
        super().__init__(script)
        self.home = home
        self.resumed: list[str] = []

    async def create_session(self, **config: Any) -> FakeSession:
        state = self.home / "session-state" / config["session_id"]
        state.mkdir(parents=True, exist_ok=True)
        (state / "events.jsonl").write_text('{"type":"session.start"}\n', encoding="utf-8")
        return await super().create_session(**config)

    async def resume_session(self, session_id: str, **config: Any) -> FakeSession:
        self.resumed.append(session_id)
        return await super().create_session(session_id=session_id, **config)


class DurableSessionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)

    def harness(self, client: FakeClient, vault: Any = None) -> CopilotHarness:
        from demo_agent.copilot_harness import SessionVault

        harness = CopilotHarness("https://example.openai.azure.com", home=str(self.root / "home"),
                                 token=lambda: asyncio.sleep(0, "token"),
                                 vault=vault or SessionVault(local_dir=str(self.root / "vault")))
        harness._client = client
        return harness

    def spec(self, **overrides: Any) -> tuple[RunSpec, list[tuple[str, dict[str, Any]]]]:
        events: list[tuple[str, dict[str, Any]]] = []

        async def sink(kind: str, data: dict[str, Any]) -> None:
            events.append((kind, data))

        async def dispatch(*_args: Any) -> str:
            return "{}"

        values = dict(run_id="run-1", model="gpt-5.4", instructions="Work the case.", prompt="New event.", tools=[],
                      dispatch=dispatch, events=sink, session_id="case-0123456789abcdef")
        values.update(overrides)
        return RunSpec(**values), events

    async def test_a_case_session_is_kept_checkpointed_and_resumed_after_losing_the_disk(self) -> None:
        async def script(session: FakeSession, prompt: str) -> Any:
            session.emit(event("assistant.message_delta", delta_content="Wor"))
            session.emit(event("assistant.message_delta", delta_content="king."))
            return reply("Working.")

        client = ResumingClient(script, self.root / "home")
        harness = self.harness(client)
        spec, events = self.spec()
        first = await harness.run(spec)
        self.assertFalse(first.resumed)
        self.assertEqual(client.deleted, [])  # A durable session is never deleted at the end of a turn.
        self.assertTrue((self.root / "vault" / "copilot-sessions" / "case-0123456789abcdef.tar.gz").is_file())
        self.assertEqual([data["text"] for kind, data in events if kind == "delta"], ["Wor", "king."])
        shutil.rmtree(self.root / "home")  # A new replica: the local disk is gone.
        second = await harness.run(self.spec()[0])
        self.assertTrue(second.resumed)
        self.assertEqual(client.resumed, ["case-0123456789abcdef"])
        self.assertTrue((self.root / "home" / "session-state" / "case-0123456789abcdef" / "events.jsonl").is_file())
        await harness.forget("case-0123456789abcdef")
        self.assertFalse((self.root / "vault" / "copilot-sessions" / "case-0123456789abcdef.tar.gz").exists())

    async def test_the_token_budget_stops_a_runaway_turn(self) -> None:
        async def script(session: FakeSession, prompt: str) -> Any:
            session.emit(event("assistant.usage", model="gpt-5.4", input_tokens=900, output_tokens=200,
                               finish_reason="tool_calls", cache_read_tokens=600))
            await session.aborted.wait()
            raise Exception("aborted")

        spec, _ = self.spec(max_tokens=1000)
        with self.assertRaisesRegex(RuntimeError, "token budget"):
            await self.harness(ResumingClient(script, self.root / "home")).run(spec)

    def test_a_checkpoint_cannot_write_outside_its_session(self) -> None:
        import io
        import tarfile

        from demo_agent.copilot_harness import SessionVault

        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            data = b"x"
            info = tarfile.TarInfo("other-session/events.jsonl")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        with self.assertRaises(ValueError):
            SessionVault.extract(buffer.getvalue(), "case-0123456789abcdef", self.root)
        with self.assertRaises(ValueError):
            SessionVault._name("../escape")


class HelperTests(unittest.TestCase):
    def test_flat_skills_are_staged_as_sdk_skill_folders(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, True)
        (root / "skills" / "folder-skill").mkdir(parents=True)
        (root / "skills" / "folder-skill" / "SKILL.md").write_text("---\nname: folder-skill\n---\nBody", encoding="utf-8")
        (root / "skills" / "flat-skill.md").write_text("---\nname: flat-skill\n---\nFlat body", encoding="utf-8")
        library = {"folder-skill": SimpleNamespace(legacy=False), "flat-skill": SimpleNamespace(legacy=True)}
        roots = skill_directories(root / "skills", library, str(root / "home"))
        self.assertEqual(roots[0], str(root / "skills"))
        self.assertEqual((Path(roots[1]) / "flat-skill" / "SKILL.md").read_text(encoding="utf-8"),
                         "---\nname: flat-skill\n---\nFlat body")

    def test_json_replies_tolerate_fences(self) -> None:
        self.assertEqual(parse_json_reply('```json\n{"mode": "reply", "text": "hi"}\n```'), {"mode": "reply", "text": "hi"})
        with self.assertRaises(ValueError):
            parse_json_reply("no json here")


if __name__ == "__main__":
    unittest.main()
