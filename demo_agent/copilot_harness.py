"""The agent harness: every run is a GitHub Copilot SDK session on BYOK Azure OpenAI (managed identity).

The SDK runs the agent loop: planning, tool calls, sub-agents, skills and context compaction. The host only
supplies what a session may use (tools, skills, sub-agent definitions) and hooks, so every step still passes
the host's approvals and guardrails before anything happens.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import io
import json
import logging
import os
import re
import shutil
import tarfile
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

_logger = logging.getLogger("group-functions-autopilot.harness")

TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"
# Isolated SDK built-ins (no host filesystem, shell or network) that run custom sub-agents.
SUBAGENT_BUILTINS = ("task", "read_agent", "list_agents")
_SECTIONS = {"identity": {"action": "remove"}, "guidelines": {"action": "remove"},
             "code_change_rules": {"action": "remove"}, "environment_context": {"action": "remove"}}
IDENTITY = ("You are Group Functions Autopilot, an AI teammate for business operations work across enterprise "
            "systems. You are not a coding assistant and have no repository or shell: you work only through the "
            "tools, skills and sub-agents you are given.")
_TURN_LIMIT = "The task reached its turn limit without a final answer."
_TOKEN_LIMIT = "The task reached its token budget without a final answer."
_SESSION_ID = re.compile(r"[a-z0-9][a-z0-9-]{7,79}")
MAX_ARCHIVE_BYTES = 32_000_000

EventSink = Callable[[str, dict[str, Any]], Awaitable[None]]
Dispatch = Callable[[str, dict[str, Any], str, str], Awaitable[str]]
Check = Callable[..., Awaitable[BaseException | None]]


class FinishRun(Exception):
    """Raised by a tool to end the run now with this answer, e.g. a change that now waits for a person."""

    def __init__(self, answer: str) -> None:
        super().__init__(answer)
        self.answer = answer


@dataclass
class AgentSpec:
    """A Copilot SDK custom agent: the run's lead colleague or a sub-agent it can delegate to."""

    name: str
    prompt: str
    model: str
    tools: list[str] | None = None
    display_name: str = ""
    description: str = ""
    reasoning_effort: str | None = None
    skills: list[str] = field(default_factory=list)
    infer: bool = True

    def config(self) -> dict[str, Any]:
        config: dict[str, Any] = {"name": self.name, "display_name": self.display_name or self.name,
                                  "description": self.description, "prompt": self.prompt, "tools": self.tools,
                                  "model": self.model, "infer": self.infer}
        if self.reasoning_effort:
            config["reasoning_effort"] = self.reasoning_effort
        if self.skills:
            config["skills"] = list(self.skills)
        return config


@dataclass
class RunSpec:
    run_id: str
    model: str
    instructions: str
    prompt: str
    tools: list[dict[str, Any]]
    dispatch: Dispatch
    events: EventSink
    reasoning_effort: str | None = None
    identity: str = IDENTITY
    lead: AgentSpec | None = None
    agents: list[AgentSpec] = field(default_factory=list)
    skill_directories: list[str] = field(default_factory=list)
    max_turns: int = 30
    timeout: float = 1800.0
    check_turn: Check | None = None  # (turn, model, agent) -> an error that stops the run
    check_message: Check | None = None  # (model, agent, tool names, content chars) -> an error that stops the run
    check_builtin: Check | None = None  # (tool, args, agent) -> an error that refuses the call
    session_id: str = ""  # A durable conversation (a case or a chat) resumes this Copilot session.
    streaming: bool = False
    max_tokens: int = 0  # Input plus output tokens across the lead and sub-agents; 0 means no budget.
    tool_search_threshold: int = 0  # Above this many tools the SDK defers schemas behind its tool search.


@dataclass
class RunResult:
    content: str
    turns: int
    finished_early: bool = False
    resumed: bool = False
    tokens: int = 0


class SessionVault:
    """Checkpoints Copilot session state (session-state/<id>) as a tarball so a durable session survives restarts."""

    def __init__(self, account_url: str = "", container: str = "", *, local_dir: str = "") -> None:
        self.account_url = account_url
        self.container = container
        self.local_dir = local_dir
        self._container: Any = None
        self._credential: Any = None

    @classmethod
    def from_env(cls) -> "SessionVault | None":
        account = os.getenv("AUTOPILOT_STORAGE_ACCOUNT_URL", "")
        if account:
            return cls(account, os.getenv("AUTOPILOT_STORAGE_CONTAINER", "autopilot-state"))
        local = os.getenv("AUTOPILOT_SESSION_VAULT_PATH", "")
        return cls(local_dir=local) if local else None

    @staticmethod
    def _name(session_id: str) -> str:
        if _SESSION_ID.fullmatch(session_id) is None:
            raise ValueError("Durable session ids are lowercase letters, digits and dashes.")
        return f"copilot-sessions/{session_id}.tar.gz"

    async def _blobs(self) -> Any:
        if self._container is None:
            from azure.identity.aio import ManagedIdentityCredential
            from azure.storage.blob.aio import ContainerClient

            self._credential = ManagedIdentityCredential(client_id=os.getenv("AZURE_CLIENT_ID") or None)
            self._container = ContainerClient(self.account_url, self.container, credential=self._credential,
                                              logging_enable=False)
        return self._container

    async def save(self, session_id: str, state_dir: Path) -> int:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            archive.add(state_dir, arcname=session_id, filter=lambda item: None if item.name.endswith(".lock") else item)
        data = buffer.getvalue()
        if len(data) > MAX_ARCHIVE_BYTES:
            raise ValueError("The session state is too large to checkpoint.")
        name = self._name(session_id)
        if self.account_url:
            await (await self._blobs()).upload_blob(name, data, overwrite=True)
        else:
            target = Path(self.local_dir) / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return len(data)

    async def load(self, session_id: str) -> bytes | None:
        name = self._name(session_id)
        if not self.account_url:
            path = Path(self.local_dir) / name
            return path.read_bytes() if path.is_file() else None
        from azure.core.exceptions import ResourceNotFoundError

        try:
            download = await (await self._blobs()).download_blob(name)
            return await download.readall()
        except ResourceNotFoundError:
            return None

    async def delete(self, session_id: str) -> None:
        name = self._name(session_id)
        if not self.account_url:
            with contextlib.suppress(FileNotFoundError):
                (Path(self.local_dir) / name).unlink()
            return
        from azure.core.exceptions import ResourceNotFoundError

        with contextlib.suppress(ResourceNotFoundError):
            await (await self._blobs()).delete_blob(name)

    @staticmethod
    def extract(data: bytes, session_id: str, state_root: Path) -> None:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            members = archive.getmembers()
            if any(not (member.name == session_id or member.name.startswith(session_id + "/")) for member in members):
                raise ValueError("The session checkpoint holds files outside its own session.")
            archive.extractall(state_root, members=members, filter="data")

    async def close(self) -> None:
        container, self._container = self._container, None
        if container is not None:
            with contextlib.suppress(Exception):
                await container.close()
        credential, self._credential = self._credential, None
        if credential is not None:
            with contextlib.suppress(Exception):
                await credential.close()


def skill_directories(skills_dir: Path, library: Mapping[str, Any], home: str) -> list[str]:
    """SDK skill roots: folder skills load in place; flat <name>.md skills are staged as <name>/SKILL.md."""
    staged = Path(home) / "skills"
    shutil.rmtree(staged, ignore_errors=True)
    for name, package in library.items():
        if getattr(package, "legacy", False):
            target = staged / name
            target.mkdir(parents=True, exist_ok=True)
            (target / "SKILL.md").write_text((skills_dir / f"{name}.md").read_text(encoding="utf-8"), encoding="utf-8")
    return [str(skills_dir), *([str(staged)] if staged.is_dir() else [])]


def parse_json_reply(text: str) -> Any:
    """The first JSON object in a model reply, tolerating a code fence around it."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("The reply contains no JSON object.")
    return json.loads(text[start:end + 1])


def system_message(instructions: str, identity: str = IDENTITY) -> dict[str, Any]:
    """Keep the SDK's safety and tool-use sections; swap its identity for the teammate's and drop coding rules."""
    return {"mode": "customize", "content": instructions,
            "sections": {**_SECTIONS, "preamble": {"action": "replace", "content": identity}}}


class CopilotHarness:
    """One Copilot runtime per host process (mode "empty": only what the host registers is available)."""

    def __init__(self, endpoint: str, *, home: str | None = None, api_version: str = "",
                 token: Callable[[], Awaitable[str]] | None = None, vault: SessionVault | None = None) -> None:
        self.endpoint = (endpoint or "").rstrip("/")
        self.home = home or os.path.join(tempfile.gettempdir(), "autopilot-copilot")
        self.api_version = api_version
        self.vault = vault
        self._token = token
        self._credential: Any = None
        self._client: Any = None
        self._lock: asyncio.Lock | None = None
        self._session_locks: dict[str, asyncio.Lock] = {}

    @classmethod
    def from_env(cls) -> "CopilotHarness":
        return cls(os.getenv("AZURE_OPENAI_ENDPOINT", ""), home=os.getenv("AUTOPILOT_COPILOT_HOME") or None,
                   api_version=os.getenv("AUTOPILOT_AZURE_API_VERSION", ""), vault=SessionVault.from_env())

    @property
    def configured(self) -> bool:
        return bool(self.endpoint)

    async def _bearer(self, _args: Any = None) -> str:
        if self._token is None:
            from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider

            self._credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
            self._token = get_bearer_token_provider(self._credential, TOKEN_SCOPE)
        return await self._token()

    def provider(self) -> dict[str, Any]:
        provider: dict[str, Any] = {"type": "azure", "base_url": self.endpoint, "bearer_token_provider": self._bearer}
        if self.api_version:
            provider["azure"] = {"api_version": self.api_version}
        return provider

    async def client(self) -> Any:
        if not self.configured:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT is not configured, so the Copilot harness has no model provider.")
        self._lock = self._lock or asyncio.Lock()
        async with self._lock:
            if self._client is None:
                from copilot import CopilotClient

                client = CopilotClient(mode="empty", base_directory=self.home, log_level="warning",
                                       session_idle_timeout_seconds=3600)
                await client.start()
                self._client = client
            return self._client

    async def stop(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            with contextlib.suppress(Exception):
                await client.stop()
        credential, self._credential = self._credential, None
        if credential is not None:
            with contextlib.suppress(Exception):
                await credential.close()
            self._token = None
        if self.vault is not None:
            await self.vault.close()

    def state_dir(self, session_id: str) -> Path:
        return Path(self.home) / "session-state" / session_id

    async def _restore(self, session_id: str) -> bool:
        """True when the session's state is on local disk, restoring its checkpoint first if needed."""
        if self.state_dir(session_id).is_dir():
            return True
        if self.vault is None:
            return False
        try:
            data = await self.vault.load(session_id)
            if data is None:
                return False
            SessionVault.extract(data, session_id, self.state_dir(session_id).parent)
            return self.state_dir(session_id).is_dir()
        except Exception as error:  # A lost checkpoint starts a fresh session; the case file still has the history.
            _logger.warning("Copilot session checkpoint restore failed (%s)", type(error).__name__)
            return False

    async def _checkpoint(self, session_id: str) -> None:
        if self.vault is None or not self.state_dir(session_id).is_dir():
            return
        try:
            await self.vault.save(session_id, self.state_dir(session_id))
        except Exception as error:
            _logger.warning("Copilot session checkpoint failed (%s)", type(error).__name__)

    async def forget(self, session_id: str) -> None:
        """Delete a durable session everywhere, e.g. when its case closes."""
        if _SESSION_ID.fullmatch(session_id or "") is None:
            return
        if self._client is not None:
            with contextlib.suppress(Exception):
                await self._client.delete_session(session_id)
        shutil.rmtree(self.state_dir(session_id), ignore_errors=True)
        if self.vault is not None:
            with contextlib.suppress(Exception):
                await self.vault.delete(session_id)

    async def run(self, spec: RunSpec) -> RunResult:
        if not spec.session_id:
            return await _SessionRun(spec).execute(await self.client(), self.provider())
        if _SESSION_ID.fullmatch(spec.session_id) is None:
            raise ValueError("Durable session ids are lowercase letters, digits and dashes.")
        lock = self._session_locks.setdefault(spec.session_id, asyncio.Lock())
        async with lock:  # One turn at a time per durable conversation.
            resume = await self._restore(spec.session_id)
            try:
                return await _SessionRun(spec, resume=resume).execute(await self.client(), self.provider())
            finally:
                await self._checkpoint(spec.session_id)

    async def complete(self, instructions: str, prompt: str, *, model: str, reasoning_effort: str | None = None,
                       timeout: float = 40.0) -> str:
        """One tool-free answer from a short-lived session (the conversation planner and summaries)."""
        client = await self.client()
        from copilot import ToolSet

        session = await client.create_session(
            session_id=f"answer-{uuid.uuid4().hex}", model=model, reasoning_effort=reasoning_effort,
            provider=self.provider(), available_tools=ToolSet(), infinite_sessions={"enabled": False},
            system_message=system_message(instructions), on_permission_request=_refuse,
        )
        try:
            reply = await session.send_and_wait(prompt, timeout=timeout)
        finally:
            await _close(client, session)
        return (reply.data.content or "") if reply is not None else ""


def _refuse(request: Any, _invocation: Any) -> Any:
    from copilot.session import PermissionDecisionReject

    _logger.warning("Refused an unexpected Copilot permission request (%s)", type(request).__name__)
    return PermissionDecisionReject(feedback="Only the tools this run was given may be used.")


async def _close(client: Any, session: Any, *, keep: bool = False) -> None:
    with contextlib.suppress(Exception):
        await session.disconnect()
    if not keep:
        with contextlib.suppress(Exception):
            await client.delete_session(session.session_id)


class _SessionRun:
    """One run's Copilot session: registers the tools, translates SDK events and enforces the stop rules."""

    def __init__(self, spec: RunSpec, *, resume: bool = False) -> None:
        self.spec = spec
        self.resume = resume
        self.tokens = 0
        self.loop = asyncio.get_running_loop()
        self.context = contextvars.copy_context()  # Handlers run in the run's context (scope, run, actor).
        self.turns = 0
        self.agents: dict[str, str] = {}  # SDK agent id -> sub-agent display name
        self.agent_turns: dict[str, int] = {}
        self.call_agent: dict[str, str] = {}  # tool call id -> the agent that made it
        self.calls: dict[str, asyncio.Task[str]] = {}
        self.delegations: dict[str, dict[str, Any]] = {}  # "task" tool call id -> sub-agent entry
        self.skills: set[str] = set()
        self.content = ""
        self.error = ""
        self.stopped: BaseException | None = None
        self.finished: str | None = None
        self.session: Any = None
        self.queue: asyncio.Queue[tuple[str, dict[str, Any]] | None] = asyncio.Queue()
        self.allowed = {tool["name"] for tool in spec.tools} | (set(SUBAGENT_BUILTINS) if spec.agents else set())
        self.models = {agent.display_name or agent.name: agent.model for agent in spec.agents}

    def _spawn(self, coroutine: Awaitable[Any]) -> asyncio.Task[Any]:
        return self.loop.create_task(coroutine, context=self.context.copy())  # type: ignore[arg-type]

    def _emit(self, kind: str, data: dict[str, Any]) -> None:
        self.queue.put_nowait((kind, data))

    async def _pump(self) -> None:
        while (item := await self.queue.get()) is not None:
            try:
                await self.spec.events(*item)
            except Exception:
                _logger.debug("Run event projection failed", exc_info=True)

    def _halt(self, error: BaseException) -> None:
        if self.stopped is None and self.finished is None:
            self.stopped = error
            if self.session is not None:
                self._spawn(self.session.abort())

    async def _check(self, check: Check, *args: Any) -> None:
        try:
            error = await check(*args)
        except Exception as failure:  # A check that cannot decide stops the run (fail closed).
            error = failure
        if error is not None:
            self._halt(error)

    # ── tools ──
    def _handler(self, name: str) -> Callable[[Any], Awaitable[Any]]:
        async def handle(invocation: Any) -> Any:
            from copilot import ToolResult

            call_id = invocation.tool_call_id or uuid.uuid4().hex
            task = self.calls.get(call_id)
            if task is None:  # The SDK can deliver one sub-agent call twice; it runs once.
                args = invocation.arguments if isinstance(invocation.arguments, dict) else {}
                task = self.calls[call_id] = self._spawn(
                    self.spec.dispatch(name, args, call_id, self.call_agent.get(call_id, "")))
            try:
                text = await asyncio.shield(task)
            except FinishRun as finish:
                if self.finished is None and self.stopped is None:
                    self.finished = finish.answer
                    self._spawn(self.session.abort())
                return ToolResult(text_result_for_llm="The run is complete.", result_type="success")
            except asyncio.CancelledError:
                raise
            except Exception as error:  # Lost authority or an unrecoverable host failure ends the run.
                self._halt(error)
                return ToolResult(text_result_for_llm="The run was stopped.", result_type="failure",
                                  error="The run was stopped.")
            return ToolResult(text_result_for_llm=text, result_type="success")
        return handle

    async def _pre_tool(self, hook: dict[str, Any], _invocation: Any) -> dict[str, Any] | None:
        name = hook.get("toolName") or ""
        if name not in self.allowed:
            return {"permissionDecision": "deny", "permissionDecisionReason": "That tool is not offered in this run."}
        if self.stopped is not None or self.finished is not None:
            return {"permissionDecision": "deny", "permissionDecisionReason": "The run is stopping."}
        if name in SUBAGENT_BUILTINS and self.spec.check_builtin is not None:
            args = hook.get("toolArgs") if isinstance(hook.get("toolArgs"), dict) else {}
            refusal = await self._spawn(self.spec.check_builtin(name, args, ""))
            if refusal is not None:
                return {"permissionDecision": "deny", "permissionDecisionReason": str(refusal)[:600]}
        return None

    # ── events ──
    def _delegation(self, call_id: str) -> dict[str, Any]:
        if call_id not in self.delegations:
            self.delegations[call_id] = {"index": len(self.delegations)}
        return self.delegations[call_id]

    def on_event(self, event: Any) -> None:
        try:
            self._translate(event)
        except Exception:
            _logger.debug("Copilot event translation failed", exc_info=True)

    def _translate(self, event: Any) -> None:
        kind = getattr(event.type, "value", str(event.type))
        data = event.data
        agent_id = getattr(event, "agent_id", None) or ""
        agent = self.agents.get(agent_id, "sub-agent") if agent_id else ""
        if kind == "subagent.started":
            name = data.agent_display_name or data.agent_name or "Sub-agent"
            if agent_id:
                self.agents[agent_id] = name
            entry = self._delegation(data.tool_call_id)
            entry.update(name=name, model=data.model or "")
            self._emit("subagent", {**entry, "phase": "started"})
        elif kind in {"subagent.completed", "subagent.failed"}:
            entry = self._delegation(data.tool_call_id)
            entry.setdefault("name", agent)
            entry.update(model=data.model or entry.get("model", ""), tool_calls=data.total_tool_calls or 0,
                         tokens=data.total_tokens or 0)
            if kind == "subagent.failed":
                self._emit("subagent", {**entry, "phase": "failed", "summary": str(data.error or "")[:600]})
                entry["done"] = True
        elif kind == "tool.execution_start":
            self.call_agent[data.tool_call_id] = agent
            if data.tool_name == "task":
                args = data.arguments if isinstance(data.arguments, dict) else {}
                instructions = next((str(args[key]) for key in ("prompt", "description") if args.get(key)), "")
                self._delegation(data.tool_call_id)["instructions"] = instructions[:600]
        elif kind == "tool.execution_complete":
            entry = self.delegations.get(data.tool_call_id)
            if entry is not None and not entry.get("done"):
                summary = (getattr(data.result, "content", "") or "") if data.result is not None else ""
                entry["done"] = True
                self._emit("subagent", {**entry, "phase": "finished" if data.success else "failed",
                                        "summary": summary[:600]})
        elif kind == "assistant.turn_start":
            model = data.model or (self.models.get(agent, "") if agent_id else self.spec.model)
            if agent_id:
                turn = self.agent_turns[agent_id] = self.agent_turns.get(agent_id, 0) + 1
            else:
                self.turns += 1
                turn = self.turns
                if self.turns > self.spec.max_turns:
                    self._halt(RuntimeError(_TURN_LIMIT))
            self._emit("turn", {"turn": turn, "model": model, "agent": agent})
            if self.spec.check_turn is not None:
                self._spawn(self._check(self.spec.check_turn, turn, model or self.spec.model, agent))
        elif kind == "assistant.usage":
            self.tokens += (data.input_tokens or 0) + (data.output_tokens or 0)
            self._emit("usage", {"model": data.model or "", "agent": agent, "input_tokens": data.input_tokens or 0,
                                 "output_tokens": data.output_tokens or 0, "finish_reason": data.finish_reason or "",
                                 "cached_tokens": getattr(data, "cache_read_tokens", 0) or 0})
            if self.spec.max_tokens and self.tokens > self.spec.max_tokens:
                self._halt(RuntimeError(_TOKEN_LIMIT))
        elif kind == "assistant.message_delta" and not agent_id and getattr(data, "delta_content", ""):
            self._emit("delta", {"text": data.delta_content})
        elif kind == "assistant.message":
            names = [request.name for request in data.tool_requests or ()]
            if not agent_id:
                self.content = data.content or ""
            if self.spec.check_message is not None:
                self._spawn(self._check(self.spec.check_message, data.model or self.spec.model, agent, names,
                                        len(data.content or "")))
        elif kind == "assistant.intent" and data.intent:
            self._emit("intent", {"text": data.intent, "agent": agent})
        elif kind == "skill.invoked" and data.name not in self.skills:
            self.skills.add(data.name)
            self._emit("skill", {"name": data.name, "agent": agent})
        elif kind == "session.compaction_complete" and data.success:
            self._emit("compaction", {"before": data.pre_compaction_tokens or 0, "after": data.post_compaction_tokens or 0})
        elif kind == "session.error":
            self.error = str(data.message or "")[:300]

    # ── the run ──
    async def execute(self, client: Any, provider: dict[str, Any]) -> RunResult:
        from copilot import Tool, ToolSet

        spec = self.spec
        tools = [Tool(name=tool["name"], description=tool.get("description") or tool["name"],
                      parameters=tool.get("parameters") or {"type": "object", "properties": {}},
                      handler=self._handler(tool["name"]), skip_permission=True) for tool in spec.tools]
        available = ToolSet().add_custom("*")
        if spec.agents:
            available.add_builtin(list(SUBAGENT_BUILTINS))
        agents = [agent.config() for agent in ([spec.lead] if spec.lead else []) + spec.agents]
        config: dict[str, Any] = dict(
            model=spec.model, reasoning_effort=spec.reasoning_effort, provider=provider, tools=tools,
            available_tools=available, system_message=system_message(spec.instructions, spec.identity),
            custom_agents=agents or None, agent=spec.lead.name if spec.lead else None,
            enable_skills=bool(spec.skill_directories) or None, skill_directories=spec.skill_directories or None,
            hooks={"on_pre_tool_use": self._pre_tool}, on_permission_request=_refuse, on_event=self.on_event,
            streaming=spec.streaming or None,
        )
        if spec.tool_search_threshold:
            config["tool_search"] = {"enabled": True, "defer_threshold": spec.tool_search_threshold}
        pump = self._spawn(self._pump())
        try:
            if spec.session_id and self.resume:
                self.session = await client.resume_session(spec.session_id, **config)
            else:
                self.session = await client.create_session(
                    session_id=spec.session_id or f"{spec.run_id}-{uuid.uuid4().hex[:8]}", **config)
            try:
                reply = await self.session.send_and_wait(spec.prompt, timeout=spec.timeout)
            except asyncio.TimeoutError:
                self._halt(TimeoutError("The run exceeded its time limit."))
                reply = None
            except Exception as error:
                if self.stopped is None and self.finished is None:
                    raise RuntimeError(f"The Copilot session failed: {self.error or str(error)[:300]}") from None
                reply = None
            if self.finished is not None:
                return RunResult(self.finished, self.turns, finished_early=True, resumed=self.resume, tokens=self.tokens)
            if self.stopped is not None:
                raise self.stopped
            content = (reply.data.content or "") if reply is not None else self.content
            if not content.strip():
                raise RuntimeError("The model returned no final answer.")
            return RunResult(content, self.turns, resumed=self.resume, tokens=self.tokens)
        except BaseException:
            if self.session is not None:
                with contextlib.suppress(Exception):
                    await self.session.abort()
            raise
        finally:
            for task in self.calls.values():
                task.cancel()
            if self.session is not None:
                await _close(client, self.session, keep=bool(spec.session_id))
            self.queue.put_nowait(None)
            with contextlib.suppress(Exception):
                await asyncio.wait_for(pump, 5)
