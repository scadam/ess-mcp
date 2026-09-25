"""Control-room model: a live activity feed and approved capabilities per AI teammate.

Every hired instance is presented as a digital colleague. The host records what
each one is doing (notifications, Teams and email traffic, skills, MCP tool calls,
case steps and issues) in a bounded, operator-only feed, and holds the skills and
MCP servers an operator approved for that instance so the host can enforce them.

Nothing here authenticates anyone: callers pass identifiers they already verified.
Text is scrubbed of credential patterns and clipped before it is retained.
"""

from __future__ import annotations

import copy
import logging
import re
import time
from collections import deque
from collections.abc import Callable, Iterable
from typing import Any

from .conversation_memory import ChatScope, StateTooLargeError, Store, scrub_memory_text

__all__ = [
    "ActivityFeed", "ControlRoomPersistence", "DELEGATED_SERVERS", "PolicyBook", "TEMPLATE_KEY",
    "clip", "tool_phrase",
]

_logger = logging.getLogger("group-functions-autopilot.control-room")

TEMPLATE_KEY = "template"
CATEGORIES = frozenset({
    "notification", "email", "teams-in", "teams-out", "skill", "reasoning", "tool", "case", "issue",
    "lifecycle", "policy",
})
STATUSES = frozenset({"info", "working", "waiting", "ok", "error"})
# Work IQ is reached per instance with the agentic user's delegated token, not at host start.
DELEGATED_SERVERS = ("workiq",)
MAX_EVENTS_PER_INSTANCE = 300
MAX_INSTANCES = 64
_TITLE_LIMIT = 240
_DETAIL_LIMIT = 1500
_OPTIONAL = ("runId", "caseKey", "server", "tool", "who", "callId")
_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")

SERVER_LABELS = {
    "workday": "Workday", "servicenow": "ServiceNow", "coupa": "Coupa", "salesforce": "Salesforce",
    "workiq": "Work IQ", "graph": "Microsoft Graph", "teams": "Teams", "human": "Manager",
    "azure-openai": "Azure OpenAI",
}

# Role presets give a new instance a sensible least-privilege default before an
# operator saves an explicit policy. Match is on the verified instance name.
ROLE_PRESETS: tuple[tuple[str, dict[str, tuple[str, ...]]], ...] = (
    ("compliance", {"skills": ("compliance-case-resolution", "compliance-second-line", "p2p-controls-test"),
                    "servers": ("coupa", "salesforce", "servicenow", "workiq")}),
    ("hr", {"skills": ("hiring-pipeline", "hr-hiring-backlog-clearance", "hr-second-line", "onboarding-audit",
                       "team-review"),
            "servers": ("servicenow", "workday")}),
    ("it", {"skills": ("access-review-panel", "incident-triage", "it-second-line", "manager-approval",
                       "zero-touch-service-desk"),
            "servers": ("coupa", "servicenow", "workday")}),
    ("supply chain", {"skills": ("procurement-month-end-close", "procurement-to-invoice", "requisition-approval-triage",
                                 "supplier-onboarding-panel", "supply-second-line"),
                      "servers": ("coupa", "servicenow")}),
)


def clip(value: Any, limit: int) -> str:
    """Redact credential patterns, then bound the text for display."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    text = scrub_memory_text(text.replace("\r", ""))
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


def _graph_phrase(method: str, target: str) -> str:
    path = target.split("?", 1)[0]
    if path.startswith("/me/messages"):
        return "Read the email in my mailbox"
    if method == "POST" and path == "/chats":
        return "Opened a private Teams chat"
    if method == "POST" and path.endswith("/messages"):
        return "Posted a message in Teams"
    if method == "GET" and re.search(r"/messages/[^/]+$", path):
        return "Read a Teams reply"
    if method == "GET" and path.startswith("/chats/"):
        return "Checked who is in the private chat"
    if path in {"/me", "/me/manager"} or path.startswith("/users/"):
        return "Looked up a directory profile"
    return f"Microsoft Graph {method} {path}"[:120]


def tool_phrase(server: str, tool: str, target: str = "") -> str:
    """Describe an MCP or platform call the way a colleague would."""
    server, tool = str(server or ""), str(tool or "")
    special = {
        ("salesforce", "create_case"): "Opened a Salesforce case",
        ("salesforce", "update_case"): "Updated the Salesforce case",
        ("salesforce", "get_case"): "Read back the Salesforce case",
        ("salesforce", "create_task"): "Logged activity on the Salesforce case",
        ("graph", "read_authenticated_email"): "Read the authenticated email",
        ("teams", "message_to_requester"): "Sent a private Teams message",
        ("teams", "message_from_requester"): "Verified a private Teams reply",
        ("azure-openai", "chat.completions"): "Reasoned over the evidence",
        ("human", "ask_manager"): "Asked the manager for a decision",
    }
    phrase = special.get((server, tool))
    if phrase:
        return phrase
    if server == "graph":
        return _graph_phrase(tool.upper(), target)
    if server == "workiq":
        if tool == "fetch" and "/lists/" in target:
            return "Read an evidence record through Work IQ"
        return f"Work IQ {tool.replace('_', ' ')}"
    label = SERVER_LABELS.get(server, server.title() or "Tool")
    return f"{label}: {tool.replace('_', ' ').replace('.', ' ')}".strip()


class ActivityFeed:
    """Bounded per-instance ring buffers. Newest first; revisions support incremental polls."""

    def __init__(self, *, per_instance: int = MAX_EVENTS_PER_INSTANCE,
                 clock: Callable[[], float] = time.time) -> None:
        self._per_instance = per_instance
        self._clock = clock
        self._buckets: dict[str, deque[dict[str, Any]]] = {}
        self._calls: dict[str, dict[str, Any]] = {}
        self._revision = 0
        self._dirty: set[str] = set()

    @property
    def revision(self) -> int:
        return self._revision

    def _next(self) -> int:
        self._revision += 1
        return self._revision

    def _bucket(self, key: str) -> deque[dict[str, Any]]:
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= MAX_INSTANCES:
                oldest = min(self._buckets, key=lambda name: self._buckets[name][0]["at"] if self._buckets[name] else 0)
                self._forget(oldest)
            bucket = self._buckets[key] = deque(maxlen=self._per_instance)
        return bucket

    def _forget(self, key: str) -> None:
        for event in self._buckets.pop(key, ()):
            self._calls.pop(event.get("callId", ""), None)
        self._dirty.discard(key)

    def record(self, instance: str, category: str, title: Any, *, detail: Any = "", status: str = "info",
               **optional: Any) -> dict[str, Any]:
        key = instance if isinstance(instance, str) and _KEY.fullmatch(instance) else TEMPLATE_KEY
        now = self._clock()
        event: dict[str, Any] = {
            "id": f"{int(now * 1000):x}-{self._revision + 1:x}",
            "rev": self._next(), "at": int(now * 1000), "instance": key,
            "category": category if category in CATEGORIES else "lifecycle",
            "status": status if status in STATUSES else "info",
            "title": clip(title, _TITLE_LIMIT) or "Activity",
            "detail": clip(detail, _DETAIL_LIMIT),
        }
        for name in _OPTIONAL:
            value = optional.get(name)
            if isinstance(value, str) and value:
                event[name] = clip(value, 200)
        bucket = self._bucket(key)
        if len(bucket) == bucket.maxlen:
            dropped = bucket[-1]
            if self._calls.get(dropped.get("callId", "")) is dropped:
                self._calls.pop(dropped["callId"], None)
        bucket.appendleft(event)
        if event.get("callId"):
            self._calls[event["callId"]] = event
        self._dirty.add(key)
        return copy.deepcopy(event)

    def complete_call(self, call_id: str, *, status: str, result: Any = "") -> dict[str, Any] | None:
        event = self._calls.pop(call_id, None)
        if event is None:
            return None
        event["status"] = status if status in STATUSES else "info"
        event["completedAt"] = int(self._clock() * 1000)
        if result:
            event["result"] = clip(result, _DETAIL_LIMIT)
        event["rev"] = self._next()
        self._dirty.add(event["instance"])
        return copy.deepcopy(event)

    def settle_run(self, run_id: str, *, status: str = "error",
                   result: str = "The run ended before this call reported a result.") -> None:
        for call_id, event in tuple(self._calls.items()):
            if event.get("runId") == run_id:
                self.complete_call(call_id, status=status, result=result)

    def events(self, instance: str | None = None, *, after: int = 0, limit: int = 200,
               categories: Iterable[str] | None = None) -> list[dict[str, Any]]:
        wanted = set(categories) if categories else None
        sources = self._buckets.values() if instance is None else [self._buckets.get(instance, deque())]
        items = [event for bucket in sources for event in bucket
                 if event["rev"] > after and (wanted is None or event["category"] in wanted)]
        items.sort(key=lambda event: (event["at"], event["rev"]), reverse=True)
        return copy.deepcopy(items[: max(1, min(int(limit), 500))])

    def keys(self) -> list[str]:
        return list(self._buckets)

    def summary(self, instance: str, *, window_ms: int = 24 * 60 * 60 * 1000) -> dict[str, Any]:
        now = int(self._clock() * 1000)
        bucket = self._buckets.get(instance, deque())
        counts = {"teams": 0, "email": 0, "notification": 0, "tool": 0, "skill": 0, "case": 0, "issue": 0}
        meter = [0] * 12  # Five-minute slots over the last hour, oldest first.
        for event in bucket:
            age = now - event["at"]
            if 0 <= age < 60 * 60 * 1000:
                meter[11 - min(11, age // (5 * 60 * 1000))] += 1
            if age > window_ms:
                continue
            category = event["category"]
            if category in {"teams-in", "teams-out"}:
                counts["teams"] += 1
            elif category in counts:
                counts[category] += 1
            if event["status"] == "error" and category != "issue":
                counts["issue"] += 1
        last = next(iter(bucket), None)
        last_issue = next((event for event in bucket if event["status"] == "error"), None)
        return {
            "counts": counts, "meter": meter, "total": len(bucket),
            "last": copy.deepcopy(last), "lastIssue": copy.deepcopy(last_issue),
        }

    # ── Persistence support ───────────────────────────────────────────
    def take_dirty(self) -> set[str]:
        dirty, self._dirty = self._dirty, set()
        return {key for key in dirty if key in self._buckets}

    def mark_dirty(self, keys: Iterable[str]) -> None:
        self._dirty.update(key for key in keys if key in self._buckets)

    def snapshot(self, instance: str, limit: int | None = None) -> list[dict[str, Any]]:
        events = list(self._buckets.get(instance, ()))
        return copy.deepcopy(events if limit is None else events[:limit])

    def restore(self, instance: str, events: Any) -> int:
        if not isinstance(instance, str) or not _KEY.fullmatch(instance) or type(events) is not list:
            return 0
        known = {event["id"] for event in self._buckets.get(instance, ())}
        restored: list[dict[str, Any]] = []
        for item in events[: self._per_instance]:
            if (type(item) is not dict or type(item.get("id")) is not str or item["id"] in known
                    or type(item.get("at")) is not int or item.get("category") not in CATEGORIES
                    or item.get("status") not in STATUSES or type(item.get("title")) is not str):
                continue
            event = {
                "id": item["id"][:40], "at": item["at"], "instance": instance, "category": item["category"],
                "status": item["status"], "title": clip(item["title"], _TITLE_LIMIT),
                "detail": clip(item.get("detail") if type(item.get("detail")) is str else "", _DETAIL_LIMIT),
            }
            for name in (*_OPTIONAL, "result"):
                if type(item.get(name)) is str and item[name]:
                    event[name] = clip(item[name], _DETAIL_LIMIT if name == "result" else 200)
            if type(item.get("completedAt")) is int:
                event["completedAt"] = item["completedAt"]
            if event["status"] == "working":
                # A call still in flight when the host stopped has no recorded outcome.
                event["status"] = "info"
                event.setdefault("result", "The host restarted before this step reported a result.")
            restored.append(event)
        if not restored:
            return 0
        bucket = self._bucket(instance)
        merged = sorted([*bucket, *restored], key=lambda event: event["at"], reverse=True)[: self._per_instance]
        bucket.clear()
        for event in reversed(merged):
            if "rev" not in event:
                event["rev"] = self._next()
            bucket.appendleft(event)
        return len(restored)


class PolicyBook:
    """Approved skills and MCP servers per instance. Absent means role preset or all."""

    def __init__(self) -> None:
        self._policies: dict[str, dict[str, Any]] = {}

    @staticmethod
    def preset(name: str) -> tuple[str, dict[str, tuple[str, ...]]] | None:
        folded = (name or "").casefold().strip()
        for prefix, preset in ROLE_PRESETS:
            if re.match(rf"{re.escape(prefix)}\b", folded):
                return prefix, preset
        return None

    def effective(self, key: str, name: str, skills: Iterable[str], servers: Iterable[str]) -> dict[str, Any]:
        available_skills, available_servers = sorted(set(skills)), sorted(set(servers))
        record = self._policies.get(key)
        if record is not None:
            return {
                "skills": [slug for slug in record["skills"] if slug in available_skills],
                "servers": [server for server in record["servers"] if server in available_servers],
                "source": "operator", "updatedAt": record.get("updatedAt"), "updatedBy": record.get("updatedBy", ""),
            }
        match = self.preset(name) if key != TEMPLATE_KEY else None
        if match is not None:
            prefix, preset = match
            return {
                "skills": [slug for slug in preset["skills"] if slug in available_skills],
                "servers": [server for server in preset["servers"] if server in available_servers],
                "source": "role-preset", "preset": prefix.upper() if len(prefix) <= 2 else prefix.title(),
            }
        return {"skills": available_skills, "servers": available_servers, "source": "default"}

    def allows(self, key: str, name: str, *, skills: Iterable[str], servers: Iterable[str],
               skill: str | None = None, server: str | None = None) -> bool:
        policy = self.effective(key, name, skills, servers)
        if skill is not None and skill not in policy["skills"]:
            return False
        if server is not None and server not in policy["servers"]:
            return False
        return True

    def set(self, key: str, *, skills: Any, servers: Any, actor: str,
            available_skills: Iterable[str], available_servers: Iterable[str]) -> dict[str, Any]:
        if not isinstance(key, str) or not _KEY.fullmatch(key):
            raise ValueError("A valid instance key is required.")
        known_skills, known_servers = set(available_skills), set(available_servers)
        if (type(skills) is not list or type(servers) is not list or len(skills) > 64 or len(servers) > 16
                or any(type(slug) is not str or slug not in known_skills for slug in skills)
                or any(type(server) is not str or server not in known_servers for server in servers)):
            raise ValueError("Approve only known skills and MCP servers.")
        record = {
            "skills": sorted(set(skills)), "servers": sorted(set(servers)),
            "updatedAt": int(time.time() * 1000), "updatedBy": clip(actor, 200),
        }
        self._policies[key] = record
        return copy.deepcopy(record)

    def reset(self, key: str) -> bool:
        return self._policies.pop(key, None) is not None

    def export(self) -> dict[str, Any]:
        return copy.deepcopy(self._policies)

    def restore(self, data: Any) -> None:
        if type(data) is not dict:
            return
        for key, record in list(data.items())[:MAX_INSTANCES]:
            if (not isinstance(key, str) or not _KEY.fullmatch(key) or type(record) is not dict
                    or type(record.get("skills")) is not list or type(record.get("servers")) is not list):
                continue
            skills = [slug for slug in record["skills"] if type(slug) is str and _SLUG.fullmatch(slug)]
            servers = [server for server in record["servers"] if type(server) is str and _SLUG.fullmatch(server)]
            self._policies[key] = {
                "skills": sorted(set(skills)), "servers": sorted(set(servers)),
                "updatedAt": record.get("updatedAt") if type(record.get("updatedAt")) is int else None,
                "updatedBy": clip(record.get("updatedBy") if type(record.get("updatedBy")) is str else "", 200),
            }


class ControlRoomPersistence:
    """Durable copy of the feed and policies in the conversation store (Blob in Azure)."""

    def __init__(self, store: Store, tenant_id: str, agent_id: str) -> None:
        self._store = store
        self._tenant = tenant_id
        self._agent = agent_id

    def _scope(self, name: str) -> ChatScope:
        return ChatScope(self._tenant, self._agent, "control-room:" + name)

    async def load(self, feed: ActivityFeed, policies: PolicyBook) -> None:
        state = await self._store.read(self._scope("policies"))
        policies.restore(state["tasks"].get("policies", {}).get("byInstance", {}))
        index = await self._store.read(self._scope("index"))
        keys = index["tasks"].get("index", {}).get("keys", [])
        for key in keys[:MAX_INSTANCES] if type(keys) is list else ():
            if isinstance(key, str) and _KEY.fullmatch(key):
                saved = await self._store.read(self._scope("feed:" + key))
                feed.restore(key, saved["tasks"].get("feed", {}).get("events", []))
        feed.take_dirty()

    async def flush(self, feed: ActivityFeed) -> None:
        dirty = feed.take_dirty()
        if not dirty:
            return
        written: set[str] = set()
        try:
            for key in sorted(dirty):
                await self._write_feed(key, feed)
                written.add(key)
            keys = sorted(feed.keys())

            def index(state: dict[str, Any]) -> None:
                state["active"] = True
                state["tasks"]["index"] = {"keys": keys}

            await self._store.update(self._scope("index"), index)
        except Exception:
            feed.mark_dirty(dirty - written)
            raise

    async def _write_feed(self, key: str, feed: ActivityFeed) -> None:
        limit: int | None = None
        for _ in range(4):
            events = feed.snapshot(key, limit)

            def transform(state: dict[str, Any], events: list[dict[str, Any]] = events) -> None:
                state["active"] = True
                state["tasks"]["feed"] = {"events": events}

            try:
                await self._store.update(self._scope("feed:" + key), transform)
                return
            except StateTooLargeError:
                limit = max(20, len(events) // 2)
        _logger.warning("control-room feed could not be persisted within the size bound")

    async def save_policies(self, policies: PolicyBook) -> None:
        data = policies.export()

        def transform(state: dict[str, Any]) -> None:
            state["active"] = True
            state["tasks"]["policies"] = {"byInstance": data}

        await self._store.update(self._scope("policies"), transform)

    async def load_guardrails(self) -> dict[str, Any]:
        state = await self._store.read(self._scope("guardrails"))
        return state["tasks"].get("guardrails") or {}

    async def save_guardrails(self, data: dict[str, Any]) -> None:
        versions = list(data.get("versions") or [])
        while True:
            saved = {**data, "versions": versions}

            def transform(state: dict[str, Any], saved: dict[str, Any] = saved) -> None:
                state["active"] = True
                state["tasks"]["guardrails"] = saved

            try:
                await self._store.update(self._scope("guardrails"), transform)
                return
            except StateTooLargeError:
                if len(versions) <= 1:
                    raise
                versions = versions[len(versions) // 2:]

    async def close(self) -> None:
        await self._store.close()
