"""The case desk: second-line work that arrives as events and is worked to closure, without polling.

Systems of record push a small signed event (a doorbell, never trusted content) the moment a case is created
or updated; Agent 365 delivers email, Teams and document @mentions; durable timers wake a case for follow-ups
and SLA checks; and a cheap, model-free reconciliation sweep catches anything a push missed. Each case is one
durable Copilot SDK session that resumes on every event, and the case file here keeps the audit trail, the
waiting state and the next wake-up. Work on a case is strictly serial; different cases run concurrently.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import heapq
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Iterable

from .conversation_memory import ChatScope, Store, scrub_memory_text

_logger = logging.getLogger("group-functions-autopilot.case-desk")

FUNCTIONS = ("it", "hr", "compliance", "supply")
FUNCTION_LABELS = {"it": "IT", "hr": "HR", "compliance": "Compliance", "supply": "Supply chain"}
SOURCES = frozenset({"servicenow", "salesforce", "coupa", "workday", "email", "teams", "document", "timer",
                     "sweep", "operator", "approval", "review"})
OPEN_STATES = frozenset({"new", "working", "waiting", "resolved"})
FINAL_STATES = frozenset({"closed", "escalated", "cancelled"})
WAIT_FOR = frozenset({"requester", "approval", "participants", "vendor", "confirmation", "other"})
DESK_AGENT = "case-desk"
MAX_PENDING = 24
MAX_TIMELINE = 80
MAX_INDEX = 400
MAX_TEXT = 4000
MAX_ERRORS = 3


def _clean(value: Any, limit: int = 300) -> str:
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    text = scrub_memory_text("".join(ch for ch in text if ch.isprintable() or ch in "\n\t")).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def case_key(*parts: str) -> str:
    return hashlib.sha256(json.dumps([str(part) for part in parts], separators=(",", ":")).encode()).hexdigest()[:40]


@dataclass(frozen=True)
class DeskBinding:
    """One function's second-line colleague, from trusted deployment configuration only."""

    function: str
    name: str
    system: str
    skill: str
    instance_app_id: str = ""
    agentic_user_id: str = ""
    manager_id: str = ""
    queue: str = ""
    servers: tuple[str, ...] = ()

    def public(self) -> dict[str, Any]:
        return {"function": self.function, "label": FUNCTION_LABELS.get(self.function, self.function),
                "name": self.name, "system": self.system, "skill": self.skill, "queue": self.queue,
                "instanceAppId": self.instance_app_id, "hasTeamsIdentity": bool(self.agentic_user_id),
                "servers": list(self.servers)}


def load_bindings(raw: str) -> tuple[DeskBinding, ...]:
    """Parse AUTOPILOT_DESK_BINDINGS: a JSON array, one entry per function."""
    if not raw or not raw.strip():
        return ()
    data = json.loads(raw)
    if type(data) is not list or len(data) > len(FUNCTIONS):
        raise ValueError("Desk bindings must be a JSON array with at most one entry per function.")
    allowed = {"function", "name", "system", "skill", "instanceAppId", "agenticUserId", "managerId", "queue",
               "servers"}
    result: list[DeskBinding] = []
    for item in data:
        if type(item) is not dict or not set(item) <= allowed:
            raise ValueError("A desk binding has unsupported fields.")
        function = item.get("function")
        if function not in FUNCTIONS or any(binding.function == function for binding in result):
            raise ValueError("Each desk binding names a distinct supported function.")
        servers = item.get("servers", [])
        if type(servers) is not list or not all(type(server) is str for server in servers):
            raise ValueError("Desk binding servers must be a list of names.")
        values = {key: item.get(key, "") for key in ("name", "system", "skill", "instanceAppId", "agenticUserId",
                                                    "managerId", "queue")}
        if not all(type(value) is str and len(value) <= 120 for value in values.values()):
            raise ValueError("Desk binding values must be short strings.")
        if not values["name"] or not values["system"] or not values["skill"]:
            raise ValueError("Each desk binding needs a name, a system of record and a playbook skill.")
        result.append(DeskBinding(function=function, name=values["name"], system=values["system"],
                                  skill=values["skill"], instance_app_id=values["instanceAppId"].lower(),
                                  agentic_user_id=values["agenticUserId"].lower(),
                                  manager_id=values["managerId"].lower(), queue=values["queue"],
                                  servers=tuple(servers)))
    return tuple(result)


@dataclass
class CaseEvent:
    """A normalized doorbell: which case, what happened, and who; any text is untrusted data."""

    source: str
    kind: str
    function: str = ""
    system: str = ""
    record_id: str = ""
    number: str = ""
    title: str = ""
    text: str = ""
    actor: dict[str, str] = field(default_factory=dict)
    channel: dict[str, str] = field(default_factory=dict)
    event_id: str = ""
    at: float = field(default_factory=time.time)
    case: str = ""  # An explicit case key (timers, approvals, operator events).

    def __post_init__(self) -> None:
        if self.source not in SOURCES:
            raise ValueError("Unsupported case event source.")
        if self.function and self.function not in FUNCTIONS:
            raise ValueError("Unsupported function.")
        self.kind = _clean(self.kind, 40) or "updated"
        self.system = _clean(self.system, 40)
        self.record_id = _clean(self.record_id, 120)
        self.number = _clean(self.number, 60)
        self.title = _clean(self.title, 240)
        self.text = _clean(self.text, MAX_TEXT)
        self.actor = {key: _clean(value, 200) for key, value in (self.actor or {}).items()
                      if key in {"name", "email", "aadObjectId", "systemUserId", "userName", "external"} and value}
        self.channel = {key: _clean(value, 400) for key, value in (self.channel or {}).items()
                        if key in {"kind", "chatId", "messageId", "conversationId", "subject", "document",
                                   "instanceAppId", "skill"} and value}
        self.event_id = _clean(self.event_id, 200) or case_key(self.source, self.kind, self.record_id,
                                                               self.text, str(self.at))

    def aliases(self) -> list[str]:
        names = []
        if self.system and self.record_id:
            names.append(f"{self.system}:{self.record_id}")
        if self.channel.get("kind") == "email" and self.channel.get("conversationId"):
            names.append(f"email:{self.channel['conversationId']}")
        if self.channel.get("kind") == "teams-group" and self.channel.get("chatId"):
            names.append(f"chat:{self.channel['chatId']}")
        return names

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Work = Callable[[dict[str, Any], list[dict[str, Any]]], Awaitable[dict[str, Any]]]
Sweep = Callable[[str], Awaitable[tuple[list[CaseEvent], str]]]


class CaseDesk:
    """Durable cases, a per-case serial inbox, durable timers and reconciliation sweeps."""

    def __init__(self, store: Store, tenant_id: str, bindings: Iterable[DeskBinding], *,
                 max_concurrent: int = 3, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.tenant_id = tenant_id
        self.bindings = {binding.function: binding for binding in bindings}
        self.clock = clock
        self.work: Work | None = None
        self.on_change: Callable[[dict[str, Any]], None] | None = None
        self._slots = asyncio.Semaphore(max_concurrent)
        self._running: set[str] = set()
        self._again: set[str] = set()
        self._tasks: set[asyncio.Task[Any]] = set()
        self._agenda: list[tuple[float, str]] = []
        self._wake = asyncio.Event()
        self._sweeps: list[tuple[str, Sweep, float]] = []
        self._loops: list[asyncio.Task[Any]] = []
        self._closing = False

    # ── storage ──
    def _scope(self, key: str) -> ChatScope:
        return ChatScope(self.tenant_id, DESK_AGENT, "case:" + key)

    @property
    def _index_scope(self) -> ChatScope:
        return ChatScope(self.tenant_id, DESK_AGENT, "index")

    async def get(self, key: str) -> dict[str, Any] | None:
        state = await self.store.read(self._scope(key))
        return state["tasks"].get("case")

    async def update(self, key: str, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        """Apply a synchronous change to a case file; the index row follows."""
        holder: dict[str, Any] = {}

        def transform(state: dict[str, Any]) -> None:
            case = state["tasks"].get("case")
            if case is None:
                raise KeyError("Unknown case.")
            change(case)
            case["updatedAt"] = self.clock()
            state["active"] = case.get("status") in OPEN_STATES
            holder["case"] = json.loads(json.dumps(case))

        await self.store.update(self._scope(key), transform)
        case = holder["case"]
        await self._index(case)
        self._notify(case)
        return case

    async def _index(self, case: dict[str, Any], aliases: Iterable[str] = ()) -> None:
        row = {"function": case["function"], "status": case["status"], "title": case["title"][:160],
               "number": case.get("record", {}).get("number", ""), "system": case.get("record", {}).get("system", ""),
               "requester": case.get("requester", {}).get("name", ""), "updatedAt": case["updatedAt"],
               "createdAt": case["createdAt"], "nextWakeAt": case.get("nextWakeAt") or 0,
               "waiting": (case.get("waiting") or {}).get("for", "")}
        names = list(aliases)

        def transform(state: dict[str, Any]) -> None:
            cases = state["tasks"].setdefault("cases", {})
            cases[case["key"]] = row
            if len(cases) > MAX_INDEX:
                closed = sorted((item["updatedAt"], key) for key, item in cases.items() if item["status"] in FINAL_STATES)
                for _at, key in closed[: len(cases) - MAX_INDEX]:
                    cases.pop(key, None)
            alias = state["tasks"].setdefault("aliases", {})
            for name in names:
                alias[name] = {"key": case["key"]}
            if len(alias) > MAX_INDEX * 3:
                live = set(cases)
                for name in [name for name, item in alias.items() if item["key"] not in live]:
                    alias.pop(name, None)

        await self.store.update(self._index_scope, transform)
        if row["nextWakeAt"] and row["status"] in OPEN_STATES:
            heapq.heappush(self._agenda, (row["nextWakeAt"], case["key"]))
            self._wake.set()

    async def index(self) -> dict[str, Any]:
        return (await self.store.read(self._index_scope))["tasks"]

    async def list_cases(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = (await self.index()).get("cases", {})
        ordered = sorted(rows.items(), key=lambda item: item[1]["updatedAt"], reverse=True)[:limit]
        return [{"key": key, **row} for key, row in ordered]

    def _notify(self, case: dict[str, Any]) -> None:
        if self.on_change is not None:
            try:
                self.on_change(case)
            except Exception:
                _logger.debug("case change projection failed", exc_info=True)

    # ── intake ──
    async def _resolve(self, event: CaseEvent) -> tuple[str, bool]:
        if event.case:
            return event.case, False
        aliases = (await self.index()).get("aliases", {})
        for name in event.aliases():
            if name in aliases:
                return aliases[name]["key"], False
        if event.source in {"timer", "approval", "review"}:
            return "", False
        thread = event.channel.get("conversationId") if event.channel.get("kind") == "email" else ""
        anchor = (f"{event.system}:{event.record_id}" if event.system and event.record_id else
                  f"{event.source}:{thread or event.channel.get('messageId') or event.event_id}")
        return case_key(self.tenant_id, event.function, anchor), True

    def _new_case(self, key: str, event: CaseEvent) -> dict[str, Any]:
        binding = self.bindings[event.function]
        now = self.clock()
        return {
            "key": key, "function": event.function, "status": "new", "title": event.title or event.number or "New case",
            "record": {"system": event.system, "id": event.record_id, "number": event.number} if event.record_id else {},
            "requester": dict(event.actor), "origin": {"source": event.source, "channel": dict(event.channel)},
            "colleague": {"name": binding.name, "instanceAppId": binding.instance_app_id},
            "waiting": None, "nextWakeAt": None, "wakeReason": "", "sessionId": "case-" + key[:32],
            "turns": 0, "tokens": 0, "pending": [], "timeline": [], "review": None, "requesterChat": "",
            "runs": [], "createdAt": now, "updatedAt": now, "closedAt": None,
        }

    async def submit(self, event: CaseEvent) -> str | None:
        """Record an event on its case (creating the case if needed) and schedule the work; None if ignored."""
        if self._closing:
            return None
        key, fresh = await self._resolve(event)
        if not key:
            return None
        if fresh and event.function not in self.bindings:
            _logger.info("case.event ignored: no colleague is bound to function %s", event.function or "unknown")
            return None
        admitted: dict[str, Any] = {}

        def transform(state: dict[str, Any]) -> None:
            if event.event_id in state["seen"]:
                return
            case = state["tasks"].get("case")
            if case is None:
                if not fresh:
                    return
                case = state["tasks"]["case"] = self._new_case(key, event)
            if case["status"] in FINAL_STATES and event.kind not in {"reopen", "created"} and event.source != "operator":
                return  # A closed case ignores late doorbells; a reopen or operator event revives it.
            if case["status"] in FINAL_STATES:
                case["status"], case["closedAt"] = "working", None
            state["seen"].append(event.event_id)
            del state["seen"][:-400]
            case["pending"].append(event.to_dict())
            del case["pending"][:-MAX_PENDING]
            if event.record_id and not case.get("record"):
                case["record"] = {"system": event.system, "id": event.record_id, "number": event.number}
            if not case["requester"] and event.actor and event.source not in {"timer", "review", "approval"}:
                case["requester"] = dict(event.actor)
            case["timeline"].append({"at": event.at, "kind": f"{event.source}.{event.kind}",
                                     "text": _clean(event.text or event.title, 300), "who": event.actor.get("name", "")})
            del case["timeline"][:-MAX_TIMELINE]
            case["updatedAt"] = self.clock()
            state["active"] = True
            admitted["case"] = json.loads(json.dumps(case))

        await self.store.update(self._scope(key), transform)
        case = admitted.get("case")
        if case is None:
            return None
        await self._index(case, event.aliases())
        self._notify(case)
        self.schedule(key)
        return key

    async def alias(self, key: str, *names: str) -> None:
        case = await self.get(key)
        if case is not None:
            await self._index(case, [name for name in names if name])

    # ── the serial worker ──
    def schedule(self, key: str) -> None:
        if key in self._running:
            self._again.add(key)
            return
        self._running.add(key)
        self._track(asyncio.get_running_loop().create_task(self._drain(key)))

    def _track(self, task: asyncio.Task[Any]) -> None:
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _take(self, key: str) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        taken: dict[str, Any] = {}

        def transform(state: dict[str, Any]) -> None:
            case = state["tasks"].get("case")
            if case is None or not case["pending"]:
                return
            taken["events"], case["pending"] = case["pending"], []
            if case["status"] in {"new", "waiting", "resolved"}:
                case["status"] = "working"
            taken["case"] = json.loads(json.dumps(case))

        await self.store.update(self._scope(key), transform)
        return taken.get("case"), taken.get("events", [])

    async def _drain(self, key: str) -> None:
        try:
            while not self._closing:
                async with self._slots:
                    case, events = await self._take(key)
                    if case is None or not events:
                        break
                    await self._index(case)
                    self._notify(case)
                    try:
                        outcome = await self.work(case, events) if self.work is not None else {}
                    except asyncio.CancelledError:
                        raise
                    except Exception as error:
                        _logger.warning("case.turn failed key=%s reason=%s", key[:12], type(error).__name__)
                        outcome = {"error": _clean(str(error) or type(error).__name__, 300)}
                    await self._finish(key, outcome)
        finally:
            self._running.discard(key)
            if key in self._again and not self._closing:
                self._again.discard(key)
                self.schedule(key)

    async def _finish(self, key: str, outcome: dict[str, Any]) -> None:
        def change(case: dict[str, Any]) -> None:
            case["turns"] = case.get("turns", 0) + 1
            case["tokens"] = case.get("tokens", 0) + int(outcome.get("tokens") or 0)
            if outcome.get("runId"):
                case["runs"] = [*case.get("runs", []), outcome["runId"]][-20:]
            summary = _clean(outcome.get("summary") or outcome.get("error") or "", 600)
            if summary:
                case["timeline"].append({"at": self.clock(), "kind": "colleague.turn" if not outcome.get("error")
                                         else "colleague.error", "text": summary, "who": case["colleague"]["name"]})
                del case["timeline"][:-MAX_TIMELINE]
            case["errors"] = case.get("errors", 0) + 1 if outcome.get("error") else 0
            if case["errors"] >= MAX_ERRORS and case["status"] not in FINAL_STATES:
                # Repeated failures stop the retries and hand the case to a person instead of looping.
                case["status"], case["closedAt"] = "escalated", self.clock()
                case["waiting"], case["nextWakeAt"], case["wakeReason"] = None, None, ""
                case["timeline"].append({"at": self.clock(), "kind": "case.escalated", "who": case["colleague"]["name"],
                                         "text": f"Stopped after {MAX_ERRORS} failed turns in a row; needs a person."})
                return
            if case["status"] == "working":
                # A turn that did not set a waiting, resolved or final state still owes the case a next step.
                case["status"] = "waiting"
                case["waiting"] = case.get("waiting") or {"for": "other", "reason": "Next step not yet scheduled",
                                                          "since": self.clock()}
                if not case.get("nextWakeAt"):
                    case["nextWakeAt"] = self.clock() + (600 if outcome.get("error") else 3600)
                    case["wakeReason"] = "Retry after an error" if outcome.get("error") else "Check progress"

        with contextlib.suppress(KeyError):
            await self.update(key, change)

    # ── lifecycle helpers used by the colleague's case tools ──
    async def wait(self, key: str, waiting_for: str, reason: str, follow_up_after: float | None) -> dict[str, Any]:
        if waiting_for not in WAIT_FOR:
            raise ValueError("Unsupported waiting state.")
        now = self.clock()

        def change(case: dict[str, Any]) -> None:
            case["status"] = "waiting"
            previous = case.get("waiting") or {}
            follow_ups = previous.get("followUps", 0) + 1 if previous.get("for") == waiting_for else 0
            case["waiting"] = {"for": waiting_for, "reason": _clean(reason, 300), "since": now, "followUps": follow_ups}
            case["nextWakeAt"] = now + follow_up_after if follow_up_after else None
            case["wakeReason"] = _clean(f"Follow up: {reason}", 300) if follow_up_after else ""

        return await self.update(key, change)

    async def wake_at(self, key: str, at: float, reason: str) -> dict[str, Any]:
        def change(case: dict[str, Any]) -> None:
            case["nextWakeAt"], case["wakeReason"] = at, _clean(reason, 300)

        return await self.update(key, change)

    async def resolve(self, key: str, resolution: str, confirm_within: float | None) -> dict[str, Any]:
        now = self.clock()

        def change(case: dict[str, Any]) -> None:
            case["status"] = "resolved"
            case["resolution"] = _clean(resolution, 1200)
            case["waiting"] = {"for": "confirmation", "reason": "Resolved; waiting for the requester to confirm",
                               "since": now, "followUps": 0}
            case["nextWakeAt"] = now + confirm_within if confirm_within else None
            case["wakeReason"] = "No reply after resolution: close the case" if confirm_within else ""

        return await self.update(key, change)

    async def finish(self, key: str, state: str, note: str) -> dict[str, Any]:
        if state not in FINAL_STATES:
            raise ValueError("Unsupported final state.")
        now = self.clock()

        def change(case: dict[str, Any]) -> None:
            case["status"], case["closedAt"] = state, now
            case["waiting"], case["nextWakeAt"], case["wakeReason"] = None, None, ""
            case["timeline"].append({"at": now, "kind": f"case.{state}", "text": _clean(note, 600),
                                     "who": case["colleague"]["name"]})
            del case["timeline"][:-MAX_TIMELINE]

        return await self.update(key, change)

    # ── timers and sweeps ──
    async def _rebuild_agenda(self) -> None:
        for key, row in (await self.index()).get("cases", {}).items():
            if row.get("nextWakeAt") and row["status"] in OPEN_STATES:
                heapq.heappush(self._agenda, (row["nextWakeAt"], key))

    async def _timer_loop(self) -> None:
        await self._rebuild_agenda()
        while not self._closing:
            self._wake.clear()
            now = self.clock()
            while self._agenda and self._agenda[0][0] <= now:
                due, key = heapq.heappop(self._agenda)
                case = await self.get(key)
                if case is None or case["status"] not in OPEN_STATES or not case.get("nextWakeAt"):
                    continue
                if abs(case["nextWakeAt"] - due) > 1:
                    continue  # Superseded by a newer wake-up.
                reason = case.get("wakeReason") or "Scheduled follow-up"

                def clear(item: dict[str, Any]) -> None:
                    item["nextWakeAt"] = None

                await self.update(key, clear)
                await self.submit(CaseEvent(source="timer", kind="timer", text=reason, case=key,
                                            event_id=f"timer:{key}:{int(due)}"))
            delay = min(max(self._agenda[0][0] - self.clock(), 0.5), 900) if self._agenda else 900
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), delay)

    def add_sweep(self, name: str, sweep: Sweep, interval: float) -> None:
        self._sweeps.append((name, sweep, max(60.0, interval)))

    async def sweep_once(self, name: str, sweep: Sweep) -> int:
        marks = (await self.index()).get("watermarks", {})
        events, mark = await sweep((marks.get(name) or {}).get("value", ""))
        admitted = 0
        for event in events:
            if await self.submit(event):
                admitted += 1
        if mark:
            def transform(state: dict[str, Any]) -> None:
                state["tasks"].setdefault("watermarks", {})[name] = {"value": mark, "at": self.clock()}

            await self.store.update(self._index_scope, transform)
        return admitted

    async def _sweep_loop(self, name: str, sweep: Sweep, interval: float) -> None:
        await asyncio.sleep(min(interval, 30))
        while not self._closing:
            try:
                admitted = await self.sweep_once(name, sweep)
                if admitted:
                    _logger.info("case.sweep %s admitted %d missed event(s)", name, admitted)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                _logger.warning("case.sweep %s failed reason=%s", name, type(error).__name__)
            await asyncio.sleep(interval)

    def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._loops.append(loop.create_task(self._timer_loop()))
        for name, sweep, interval in self._sweeps:
            self._loops.append(loop.create_task(self._sweep_loop(name, sweep, interval)))

    async def resume_pending(self) -> int:
        """After a restart, finish any case that still holds unworked events."""
        count = 0
        for key, row in (await self.index()).get("cases", {}).items():
            if row["status"] in {"new", "working"}:
                case = await self.get(key)
                if case and case.get("pending"):
                    self.schedule(key)
                    count += 1
        return count

    async def close(self) -> None:
        self._closing = True
        self._wake.set()
        for task in [*self._loops, *self._tasks]:
            task.cancel()
        for task in [*self._loops, *self._tasks]:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
