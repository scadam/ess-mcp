"""Analytics for the digital workforce: what the work costs, how much there is, how well it goes, and how much
self-service takes off the desk.

Everything is derived from what the host itself observed (runs, cases, approvals, the self-service articles and
catalog items the colleagues created) plus two outside sources: Azure Cost Management for the fixed daily cost of the
infrastructure, and ServiceNow for demand and self-service use. Facts are kept per UTC day in the state store, so they
survive restarts and control-room resets.

Costs are in US dollars:

- AI: GitHub Copilot SDK AI credits at $0.01. The SDK's own figure for a model call when it reports one; otherwise
  the call's tokens priced at GitHub's published per-model rates (which is how AI credits are counted).
- Work IQ: Copilot Credits at $0.01 for each Work IQ call, at a configurable number of credits per call. Microsoft
  bills Work IQ by variable usage, so the rate is an estimate to calibrate from the Microsoft 365 admin center.
- Infrastructure: the fixed daily cost of the host's Azure resource group from Azure Cost Management (the average of
  the last complete days, without the model-token meters, which the AI credits already cost), spread over the
  interactions in the period.
- People in the loop: minutes per approval, escalation and review reply at a loaded hourly rate.
"""

from __future__ import annotations

import asyncio
import calendar
import contextlib
import datetime as _dt
import json
import logging
import math
import re
import time
from typing import Any, Callable, Iterable

import httpx

from .conversation_memory import ChatScope, Store

_logger = logging.getLogger("group-functions-autopilot.analytics")

DAY = 86400.0
USD_PER_CREDIT = 0.01  # GitHub AI credits and Microsoft Copilot Credits are both one cent.
NANO_AIU_PER_CREDIT = 1e9
RETENTION_DAYS = 95
PERIODS = (1, 7, 30, 90)
FUNCTIONS = ("it", "hr", "compliance", "supply")
FUNCTION_LABELS = {"it": "IT", "hr": "HR", "compliance": "Compliance", "supply": "Supply chain", "platform": "Platform"}
FINAL = frozenset({"closed", "escalated", "cancelled"})
MAX_DAY_RUNS = 1000
MAX_DAY_CASES = 400
_AGENT = "analytics"

# GitHub Copilot per-token prices in USD per million tokens (docs.github.com, "Models and pricing for GitHub
# Copilot"): (input, cached input, output), with a second tier above a request's long-context threshold.
MODEL_PRICES: dict[str, tuple[tuple[float, float, float], int, tuple[float, float, float] | None]] = {
    "gpt-5.4-mini": ((0.75, 0.075, 4.50), 0, None),
    "gpt-5.4-nano": ((0.20, 0.02, 1.25), 0, None),
    "gpt-5.4": ((2.50, 0.25, 15.00), 272_000, (5.00, 0.50, 22.50)),
    "gpt-5.5": ((5.00, 0.50, 30.00), 272_000, (10.00, 1.00, 45.00)),
    "gpt-5-mini": ((0.25, 0.025, 2.00), 0, None),
    "gpt-5.3-codex": ((1.75, 0.175, 14.00), 0, None),
}
FALLBACK_MODEL = "gpt-5.4"

DEFAULT_SETTINGS: dict[str, Any] = {
    "workIqCreditsPerCall": 1.0,
    "baselineCostPerCase": 40.0,
    "baselineByFunction": {},
    "humanHandleMinutes": 30.0,
    "peopleHourlyUsd": 50.0,
    "approvalMinutes": 3.0,
    "escalationMinutes": 30.0,
    "reviewReplyMinutes": 5.0,
    "dailyInfraUsd": None,
}
_BOUNDS = {"workIqCreditsPerCall": 1000, "baselineCostPerCase": 100_000, "humanHandleMinutes": 1440,
           "peopleHourlyUsd": 10_000, "approvalMinutes": 600, "escalationMinutes": 1440, "reviewReplyMinutes": 600,
           "dailyInfraUsd": 1_000_000}

CHANNEL_LABELS = {
    "teams-chat": "Teams chat", "servicenow": "ServiceNow ticket", "salesforce": "Salesforce case",
    "coupa": "Coupa exception", "workday": "Workday", "email": "Email", "document": "Word comment",
    "teams": "Teams request", "operator": "Control plane", "control-plane": "Control plane",
    "instance-launch": "Control plane", "compliance": "Compliance email", "review": "Review chat",
}
_MODEL_METERS = ("foundry models", "cognitive services", "openai", "azure ai")
_STOP = frozenset("a an and are as at be by can do for from has have how i in is it my of on or our please the "
                  "this to we what when with you your me need needs re fw fwd not no new request help issue case "
                  "comment word about after before get got still just also into up out any all some".split())


def _num(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else 0.0


def day_key(at: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(at))


def model_key(name: str) -> str | None:
    """The price-list entry for a model or deployment name (longest match first), or None when it isn't listed."""
    text = re.sub(r"[\s_]+", "-", str(name or "").strip().lower())
    for key in sorted(MODEL_PRICES, key=len, reverse=True):
        if text == key or text.startswith(key + "-"):
            return key
    return None


def price_call(model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0,
               nano_aiu: float | None = None) -> tuple[float, bool]:
    """AI credits for one model call, and whether GitHub's price list (or the SDK itself) covered it."""
    if nano_aiu is not None and nano_aiu >= 0:
        return nano_aiu / NANO_AIU_PER_CREDIT, True
    key = model_key(model)
    rates, threshold, long_rates = MODEL_PRICES[key or FALLBACK_MODEL]
    tokens_in, tokens_out = max(int(input_tokens or 0), 0), max(int(output_tokens or 0), 0)
    if threshold and long_rates and tokens_in > threshold:
        rates = long_rates
    cached = min(max(int(cached_tokens or 0), 0), tokens_in)
    usd = ((tokens_in - cached) * rates[0] + cached * rates[1] + tokens_out * rates[2]) / 1_000_000
    return usd / USD_PER_CREDIT, key is not None


def clean_settings(raw: Any) -> dict[str, Any]:
    """Operator-editable assumptions, validated; unknown keys are refused rather than ignored."""
    if type(raw) is not dict:
        raise ValueError("Settings must be an object.")
    unknown = set(raw) - set(DEFAULT_SETTINGS)
    if unknown:
        raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}.")
    result = dict(DEFAULT_SETTINGS)
    for key, value in raw.items():
        if key == "baselineByFunction":
            if type(value) is not dict or not set(value) <= set(FUNCTIONS):
                raise ValueError("baselineByFunction maps it, hr, compliance or supply to a cost.")
            result[key] = {name: _bounded(key, cost, 100_000) for name, cost in value.items() if cost is not None}
        elif key == "dailyInfraUsd" and value is None:
            result[key] = None
        else:
            result[key] = _bounded(key, value, _BOUNDS[key])
    return result


def _bounded(key: str, value: Any, limit: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= limit:
        raise ValueError(f"{key} must be a number from 0 to {limit:g}.")
    return float(value)


def _sn_time(value: Any) -> float | None:
    """A ServiceNow UTC timestamp ('YYYY-MM-DD HH:MM:SS') as epoch seconds."""
    text = str(value or "")[:19]
    try:
        return float(calendar.timegm(time.strptime(text, "%Y-%m-%d %H:%M:%S")))
    except ValueError:
        return None


def _parse_json(text: Any) -> Any:
    if isinstance(text, (dict, list)):
        return text
    if not isinstance(text, str) or not text.strip().startswith(("{", "[")):
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


# ── facts ──
def run_fact(run: dict[str, Any], *, function: str, channel: str) -> dict[str, Any]:
    """The compact, durable record of one finished interaction."""
    stats = run.get("stats") or {}
    models = {}
    credits, unpriced = 0.0, False
    for name, entry in (stats.get("models") or {}).items():
        if type(entry) is not dict:
            continue
        spent = _num(entry.get("credits"))
        if "credits" not in entry:  # A run recorded before credits were tracked: price its tokens now.
            spent, known = price_call(name, entry.get("prompt_tokens", 0), entry.get("completion_tokens", 0),
                                      entry.get("cached_tokens", 0))
            unpriced = unpriced or not known
        unpriced = unpriced or bool(entry.get("unpriced"))
        credits += spent
        models[str(name)[:60]] = {"calls": int(_num(entry.get("calls"))), "in": int(_num(entry.get("prompt_tokens"))),
                                  "out": int(_num(entry.get("completion_tokens"))),
                                  "cached": int(_num(entry.get("cached_tokens"))), "credits": round(spent, 4)}
    tools = [item for item in (run.get("toolData") or {}).values() if type(item) is dict]
    workiq = sum(1 for item in tools if item.get("server") == "workiq")
    counts = run.get("serverCallCounts") or {}
    workiq = max(workiq, int(_num(counts.get("workiq"))))
    guard = {"deny": 0, "escalate": 0}
    for item in run.get("guardrails") or ():
        decision = str((item or {}).get("decision") or "")
        if decision in guard:
            guard[decision] += 1
    start = _num(run.get("startedAt")) / 1000 or time.time()
    end = _num(run.get("completedAt")) / 1000 or time.time()
    actor = run.get("actor") or {}
    agentic = run.get("agenticUser") or {}
    return {
        "id": str(run.get("id") or "")[:80], "day": day_key(end), "start": start, "end": max(end, start),
        "src": str(run.get("source") or "")[:40], "channel": channel[:40], "fn": function,
        "colleague": str(agentic.get("name") or actor.get("agenticAppName") or run.get("instanceLabel") or "")[:80],
        "instance": str(run.get("instanceKey") or "")[:80], "case": str(actor.get("caseKey") or "")[:40],
        "status": str(run.get("status") or "")[:20], "error": run.get("status") == "error",
        "dry": bool(actor.get("dryRun") or run.get("dryRun")),
        "in": int(_num(stats.get("prompt_tokens"))), "out": int(_num(stats.get("completion_tokens"))),
        "cached": int(_num(stats.get("cached_tokens"))), "credits": round(credits, 4), "unpriced": unpriced,
        "models": models, "workiq": workiq, "tools": len(tools) or int(sum(_num(v) for v in counts.values())),
        "guard": guard, "approvals": len(run.get("approvals") or ()),
        "ms": int(max(end - start, 0) * 1000),
    }


def case_fact(case: dict[str, Any], previous: dict[str, Any] | None, now: float) -> dict[str, Any]:
    """A case's analytics record; transitions (resolutions, approval waits) are counted across updates."""
    previous = previous or {}
    status = str(case.get("status") or "")
    waiting = str((case.get("waiting") or {}).get("for") or "")
    origin = case.get("origin") or {}
    record = case.get("record") or {}
    source = str(origin.get("source") or "")
    channel = source if source not in {"sweep", "timer"} else (record.get("system") or source)
    timeline = [item for item in case.get("timeline") or () if type(item) is dict]
    created = _num(case.get("createdAt")) or now
    resolutions = int(previous.get("resolutions", 0)) + (1 if status == "resolved" and previous.get("status") != "resolved" else 0)
    resolved = previous.get("resolved") or (now if status == "resolved" else None)
    if status == "closed" and not resolved:
        resolved = _num(case.get("closedAt")) or now
    finished = previous.get("finished") or ((_num(case.get("closedAt")) or now) if status in FINAL else None)
    if status not in FINAL:
        finished = None  # Reopened.
    responses = [_num(item.get("at")) for item in timeline
                 if item.get("kind") in {"colleague.message", "document.edited", "review.started", "case.escalated"}]
    if origin.get("channel", {}).get("kind") == "document":
        responses.append(created)  # A Word comment is acknowledged in its thread as it arrives.
    if resolved:
        responses.append(_num(resolved))
    first = min([at for at in responses if at] or [0]) or previous.get("firstResponse")
    review = case.get("review") or {}
    return {
        "key": str(case.get("key") or "")[:40], "day": day_key(created), "fn": str(case.get("function") or ""),
        "colleague": str((case.get("colleague") or {}).get("name") or "")[:80], "title": str(case.get("title") or "")[:160],
        "src": str(channel)[:40], "system": str(record.get("system") or "")[:20], "number": str(record.get("number") or "")[:40],
        "created": created, "updated": _num(case.get("updatedAt")) or now, "status": status, "waiting": waiting,
        "firstResponse": first or None, "resolved": resolved, "finished": finished,
        "escalated": status == "escalated" or any(item.get("kind") == "case.escalated" for item in timeline)
        or bool(previous.get("escalated")),
        "resolutions": resolutions,
        "approvals": int(previous.get("approvals", 0)) + (1 if waiting == "approval" and previous.get("waiting") != "approval" else 0),
        "reviewReplies": len(review.get("replies") or ()) if review else int(previous.get("reviewReplies", 0)),
        "turns": int(_num(case.get("turns"))), "tokens": int(_num(case.get("tokens"))),
        "errors": max(int(previous.get("errors", 0)), sum(1 for item in timeline if item.get("kind") == "colleague.error")),
        "runs": [str(run)[:80] for run in (case.get("runs") or ())][-40:],
    }


ASSET_TOOLS = {"create_knowledge_article": "knowledge", "create_catalog_item": "catalog",
               "set_catalog_item_active": "catalog"}


def asset_fact(tool: str, arguments: Any, result: Any, *, at: float, colleague: str, function: str,
               run_id: str, case: str) -> dict[str, Any] | None:
    """A knowledge article or catalog item a colleague created or published, from its successful tool result."""
    kind = ASSET_TOOLS.get(tool)
    data = _parse_json(result)
    if kind is None or type(data) is not dict or data.get("success") is False or data.get("error"):
        return None
    args = arguments if type(arguments) is dict else {}
    if kind == "knowledge":
        article = data.get("article") if type(data.get("article")) is dict else {}
        sys_id = str(article.get("sys_id") or "")
        title = str(article.get("title") or args.get("title") or "")
        extra = {"number": str(article.get("number") or ""), "state": str(article.get("state") or "draft")}
    else:
        sys_id = str(data.get("sys_id") or args.get("sys_id") or "")
        title = str(data.get("name") or args.get("name") or "")
        extra = {"active": bool(data.get("active")), "published": at if data.get("active") else None}
    if not sys_id and not title:
        return None
    return {"id": f"{kind}:{sys_id or title.lower()}"[:120], "day": day_key(at), "kind": kind, "sysId": sys_id[:40],
            "title": title[:160], "created": at, "colleague": colleague[:80], "fn": function, "run": run_id[:80],
            "case": case[:40], "update": tool == "set_catalog_item_active", **extra}


# ── the fixed daily cost of the infrastructure ──
class AzureCostSource:
    """The average daily cost of the host's resource group from Azure Cost Management (host managed identity)."""

    def __init__(self, scope: str, *, token: Callable[[], Any] | None = None, clock: Callable[[], float] = time.time,
                 days: int = 7, ttl: float = 6 * 3600) -> None:
        self.scope = scope.rstrip("/")
        self._token = token
        self.clock = clock
        self.days = days
        self.ttl = ttl
        self._value: dict[str, Any] | None = None
        self._at = 0.0
        self._error = ""
        self._lock = asyncio.Lock()
        self._credential: Any = None

    @property
    def configured(self) -> bool:
        return bool(re.fullmatch(r"/subscriptions/[0-9a-fA-F-]{36}(/resourceGroups/[\w.()-]{1,90})?", self.scope))

    async def _bearer(self) -> str:
        if self._token is not None:
            value = self._token()
            return await value if asyncio.iscoroutine(value) else value
        if self._credential is None:
            from azure.identity.aio import DefaultAzureCredential

            self._credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        return (await self._credential.get_token("https://management.azure.com/.default")).token

    async def close(self) -> None:
        credential, self._credential = self._credential, None
        if credential is not None:
            with contextlib.suppress(Exception):
                await credential.close()

    async def daily(self) -> dict[str, Any]:
        if not self.configured:
            return {"source": "unconfigured", "error": "No Azure cost scope is configured (AUTOPILOT_COST_SCOPE)."}
        async with self._lock:
            if self._value is not None and self.clock() - self._at < self.ttl:
                return self._value
            if self._error and self.clock() - self._at < 600:
                return {**(self._value or {"source": "azure"}), "error": self._error}
            try:
                self._value, self._error = await self._query(), ""
            except Exception as error:  # noqa: BLE001 - reported, never raised
                self._error = f"Azure Cost Management could not be read ({type(error).__name__})."
                _logger.warning("analytics.cost query failed reason=%s", type(error).__name__)
            self._at = self.clock()
            return self._value if not self._error else {**(self._value or {"source": "azure"}), "error": self._error}

    async def _query(self) -> dict[str, Any]:
        today = _dt.datetime.fromtimestamp(self.clock(), _dt.timezone.utc).date()
        start = today - _dt.timedelta(days=self.days + 7)
        end = today - _dt.timedelta(days=1)
        body = {"type": "ActualCost", "timeframe": "Custom",
                "timePeriod": {"from": f"{start.isoformat()}T00:00:00Z", "to": f"{end.isoformat()}T23:59:59Z"},
                "dataset": {"granularity": "Daily", "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                            "grouping": [{"type": "Dimension", "name": "ServiceName"}]}}
        url = f"https://management.azure.com{self.scope}/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
        async with httpx.AsyncClient(timeout=30, trust_env=False) as client:
            response = await client.post(url, json=body, headers={"Authorization": f"Bearer {await self._bearer()}"})
            response.raise_for_status()
            data = response.json()
        return summarise_costs(data, days=self.days, until=end.isoformat())


def summarise_costs(data: dict[str, Any], *, days: int, until: str) -> dict[str, Any]:
    """Average per day over the last `days` days that have cost data, split into fixed services and model tokens."""
    properties = data.get("properties") or {}
    columns = [str(column.get("name") or "") for column in properties.get("columns") or ()]
    index = {name.lower(): position for position, name in enumerate(columns)}
    rows = properties.get("rows") or []
    per_day: dict[str, dict[str, float]] = {}
    currency = "USD"
    for row in rows:
        try:
            cost = float(row[index["cost"]]) if "cost" in index else float(row[index["pretaxcost"]])
            stamp = str(row[index["usagedate"]])
            service = str(row[index["servicename"]] or "Other")
            currency = str(row[index["currency"]]) if "currency" in index else currency
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        date = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}" if len(stamp) >= 8 and stamp[:8].isdigit() else stamp[:10]
        if date > until:
            continue
        services = per_day.setdefault(date, {})
        services[service] = services.get(service, 0.0) + cost
    dates = sorted(date for date, services in per_day.items() if sum(services.values()) > 0)[-days:]
    if not dates:
        raise ValueError("Azure Cost Management returned no cost for the resource group yet.")
    totals: dict[str, float] = {}
    for date in dates:
        for service, cost in per_day[date].items():
            totals[service] = totals.get(service, 0.0) + cost
    services = sorted(({"name": name, "perDay": round(total / len(dates), 4),
                        "fixed": not any(meter in name.lower() for meter in _MODEL_METERS)}
                       for name, total in totals.items() if total > 0), key=lambda item: -item["perDay"])
    return {"source": "azure", "currency": currency, "days": len(dates), "from": dates[0], "to": dates[-1],
            "fixedPerDay": round(sum(item["perDay"] for item in services if item["fixed"]), 4),
            "modelPerDay": round(sum(item["perDay"] for item in services if not item["fixed"]), 4),
            "services": services}


# ── the ledger ──
class AnalyticsLedger:
    """In-memory facts for the retention window, written through to one state-store scope per UTC day."""

    def __init__(self, store: Store, tenant_id: str, *, costs: AzureCostSource | None = None,
                 clock: Callable[[], float] = time.time, flush_delay: float = 2.0) -> None:
        self.store = store
        self.tenant_id = tenant_id
        self.costs = costs
        self.clock = clock
        self.flush_delay = flush_delay
        self.runs: dict[str, dict[str, Any]] = {}
        self.cases: dict[str, dict[str, Any]] = {}
        self.approvals: dict[str, dict[str, Any]] = {}
        self.assets: dict[str, dict[str, Any]] = {}
        self.overhead: dict[str, dict[str, dict[str, float]]] = {}
        self.settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.since: float | None = None  # When this host started recording: the platform is costed from here.
        self._dirty: set[str] = set()
        self._loaded = False
        self._load_lock = asyncio.Lock()
        self._flush_task: asyncio.Task[Any] | None = None
        self._closing = False

    # scopes
    def _scope(self, name: str) -> ChatScope:
        return ChatScope(self.tenant_id, _AGENT, name)

    def scopes(self) -> tuple[ChatScope, ...]:
        """Every scope analytics may hold, so a control-room reset can keep them."""
        now = self.clock()
        return (self._scope("settings"), *(self._scope("day:" + day_key(now - offset * DAY))
                                           for offset in range(RETENTION_DAYS + 1)))

    async def load(self) -> None:
        if self._loaded:
            return
        async with self._load_lock:
            if self._loaded:
                return
            try:
                state = await self.store.read(self._scope("settings"))
                record = state["tasks"].get("settings") or {}
                if record.get("values"):
                    self.settings = clean_settings(record["values"])
                self.since = _num(record.get("since")) or self.since
                if not record.get("since"):
                    self.since = self.since or self.clock()
                    await self.store.update(self._scope("settings"), self._settings_change(self.settings))
            except Exception as error:  # noqa: BLE001
                _logger.warning("analytics.settings not restored reason=%s", type(error).__name__)
            now = self.clock()
            for offset in range(RETENTION_DAYS + 1):
                day = day_key(now - offset * DAY)
                try:
                    tasks = (await self.store.read(self._scope("day:" + day)))["tasks"]
                except Exception as error:  # noqa: BLE001
                    _logger.warning("analytics.day %s not restored reason=%s", day, type(error).__name__)
                    continue
                for item in (tasks.get("runs") or {}).get("items") or ():
                    self.runs.setdefault(item["id"], item)
                for key, item in ((tasks.get("cases") or {}).get("items") or {}).items():
                    self.cases.setdefault(key, item)
                for key, item in ((tasks.get("approvals") or {}).get("items") or {}).items():
                    self.approvals.setdefault(key, item)
                for key, item in ((tasks.get("assets") or {}).get("items") or {}).items():
                    self.assets.setdefault(key, item)
                models = (tasks.get("overhead") or {}).get("models")
                if models:
                    self.overhead.setdefault(day, models)
            self._loaded = True

    def _mark(self, day: str) -> None:
        self._dirty.add(day)
        if self._closing:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = loop.create_task(self._flush_soon())

    async def _flush_soon(self) -> None:
        await asyncio.sleep(self.flush_delay)
        await self.flush()

    def _payload(self, day: str) -> dict[str, Any]:
        runs = sorted((item for item in self.runs.values() if item["day"] == day), key=lambda item: item["end"])
        cases = sorted((item for item in self.cases.values() if item["day"] == day), key=lambda item: item["created"])
        return {
            "runs": {"items": runs[-MAX_DAY_RUNS:]},
            "cases": {"items": {item["key"]: item for item in cases[-MAX_DAY_CASES:]}},
            "approvals": {"items": {key: item for key, item in self.approvals.items() if item["day"] == day}},
            "assets": {"items": {key: item for key, item in self.assets.items() if item["day"] == day}},
            "overhead": {"models": self.overhead.get(day, {})},
        }

    async def flush(self) -> None:
        await self.load()
        self._prune()
        days, self._dirty = self._dirty, set()
        for day in sorted(days):
            payload = self._payload(day)

            def replace(state: dict[str, Any], payload: dict[str, Any] = payload) -> None:
                state["tasks"].clear()
                state["tasks"].update(payload)

            try:
                await self.store.update(self._scope("day:" + day), replace)
            except Exception as error:  # noqa: BLE001 - retried on the next change
                self._dirty.add(day)
                _logger.warning("analytics.flush %s failed reason=%s", day, type(error).__name__)

    def _prune(self) -> None:
        cutoff = day_key(self.clock() - RETENTION_DAYS * DAY)
        for facts in (self.runs, self.cases, self.approvals, self.assets):
            for key in [key for key, item in facts.items() if item["day"] < cutoff]:
                facts.pop(key, None)
        for day in [day for day in self.overhead if day < cutoff]:
            self.overhead.pop(day, None)

    async def close(self) -> None:
        self._closing = True
        task, self._flush_task = self._flush_task, None
        if task is not None and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if self._dirty:
            with contextlib.suppress(Exception):
                await self.flush()
        if self.costs is not None:
            await self.costs.close()

    # notes
    def note_run(self, run: dict[str, Any], *, function: str, channel: str) -> dict[str, Any] | None:
        if not run.get("id") or not run.get("completedAt"):
            return None
        fact = run_fact(run, function=function, channel=channel)
        previous = self.runs.get(fact["id"])
        if previous is not None and previous["day"] != fact["day"]:
            self._mark(previous["day"])
        self.runs[fact["id"]] = fact
        self._mark(fact["day"])
        return fact

    def note_case(self, case: dict[str, Any]) -> dict[str, Any] | None:
        key = str(case.get("key") or "")[:40]
        if not key:
            return None
        fact = case_fact(case, self.cases.get(key), self.clock())
        self.cases[key] = fact
        self._mark(fact["day"])
        return fact

    def note_approval(self, item: dict[str, Any], *, run: dict[str, Any], function: str) -> None:
        request_id = str(item.get("id") or "")[:80]
        if not request_id:
            return
        requested = _num(item.get("at")) / 1000 or self.clock()
        previous = self.approvals.get(request_id) or {}
        fact = {"id": request_id, "day": previous.get("day") or day_key(requested), "run": str(run.get("id") or "")[:80],
                "case": str((run.get("actor") or {}).get("caseKey") or "")[:40], "fn": function,
                "label": str(item.get("label") or "")[:160], "requested": previous.get("requested") or requested,
                "status": str(item.get("status") or "pending")[:20],
                "decided": (_num(item.get("decidedAt")) / 1000 or None) if item.get("status") != "pending" else None}
        self.approvals[request_id] = fact
        self._mark(fact["day"])

    def note_asset(self, fact: dict[str, Any]) -> None:
        existing = self.assets.get(fact["id"])
        if existing is not None:
            if fact.get("update"):
                existing.update(active=fact.get("active", existing.get("active")),
                                published=existing.get("published") or fact.get("published"))
            self._mark(existing["day"])
            return
        if fact.get("update") and fact["kind"] == "catalog":
            match = next((item for item in self.assets.values() if item["kind"] == "catalog" and fact["sysId"]
                          and item.get("sysId") == fact["sysId"]), None)
            if match is not None:
                match.update(active=fact.get("active"), published=match.get("published") or fact.get("published"))
                self._mark(match["day"])
                return
        self.assets[fact["id"]] = fact
        self._mark(fact["day"])

    def note_usage(self, usage: dict[str, Any]) -> None:
        """Model use no run owns (the conversation planner and memory summaries)."""
        model = str(usage.get("model") or "")[:60] or "unknown"
        credits, known = price_call(model, usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                                    usage.get("cached_tokens", 0), usage.get("nano_aiu"))
        day = day_key(self.clock())
        entry = self.overhead.setdefault(day, {}).setdefault(model, {"calls": 0, "in": 0, "out": 0, "credits": 0.0})
        entry["calls"] += 1
        entry["in"] += int(_num(usage.get("input_tokens")))
        entry["out"] += int(_num(usage.get("output_tokens")))
        entry["credits"] = round(entry["credits"] + credits, 4)
        if not known:
            entry["unpriced"] = True
        self._mark(day)

    def close_open_cases(self, reason: str) -> int:
        """A control-room reset discards the live cases; their analytics end as cancelled rather than open forever."""
        now, closed = self.clock(), 0
        for fact in self.cases.values():
            if fact.get("status") not in FINAL:
                fact.update(status="cancelled", finished=now, waiting="", cancelReason=reason[:60])
                self._mark(fact["day"])
                closed += 1
        return closed

    def _settings_change(self, values: dict[str, Any]) -> Callable[[dict[str, Any]], None]:
        since = self.since

        def change(state: dict[str, Any]) -> None:
            state["tasks"]["settings"] = {"values": values, "at": self.clock(), "since": since}

        return change

    async def save_settings(self, raw: Any) -> dict[str, Any]:
        values = clean_settings(raw)
        await self.store.update(self._scope("settings"), self._settings_change(values))
        self.settings = values
        return values

    # the report
    async def infrastructure(self) -> dict[str, Any]:
        override = self.settings.get("dailyInfraUsd")
        derived = await self.costs.daily() if self.costs is not None else {"source": "unconfigured",
                                                                            "error": "No Azure cost source."}
        if override is not None:
            return {**derived, "source": "override", "fixedPerDay": float(override), "derived": derived.get("fixedPerDay")}
        return derived

    def report(self, *, days: int, function: str = "", infra: dict[str, Any] | None = None,
               servicenow: dict[str, Any] | None = None, backlog: Iterable[dict[str, Any]] = ()) -> dict[str, Any]:
        return build_report(self, days=days, function=function, now=self.clock(), infra=infra or {},
                            servicenow=servicenow, backlog=list(backlog))


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * share
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _minutes(values: list[float]) -> dict[str, Any]:
    minutes = [value / 60 for value in values if value >= 0]
    median, p90 = _percentile(minutes, 0.5), _percentile(minutes, 0.9)
    return {"count": len(minutes), "median": round(median, 1) if median is not None else None,
            "p90": round(p90, 1) if p90 is not None else None}


def _ratio(part: float, whole: float) -> float | None:
    return round(part / whole, 4) if whole else None


def _themes(titles: list[str], limit: int = 6) -> list[dict[str, Any]]:
    """Recurring two-word themes across case titles: candidates for a knowledge article or catalog item."""
    counts: dict[str, set[int]] = {}
    for index, title in enumerate(titles):
        words = [word for word in re.findall(r"[a-z][a-z0-9'-]{2,}", title.lower()) if word not in _STOP]
        for pair in {f"{a} {b}" for a, b in zip(words, words[1:])}:
            counts.setdefault(pair, set()).add(index)
    ranked = sorted(((len(found), phrase, found) for phrase, found in counts.items() if len(found) >= 2),
                    key=lambda item: (-item[0], item[1]))
    result, used = [], set()
    for count, phrase, found in ranked:
        if len(found & used) >= 0.7 * count:
            continue  # Mostly the same cases as a theme already listed.
        examples = list(dict.fromkeys(titles[i][:100] for i in sorted(found)))[:3]
        result.append({"theme": phrase, "cases": count, "examples": examples})
        used |= found
        if len(result) >= limit:
            break
    return result


def build_report(ledger: AnalyticsLedger, *, days: int, function: str, now: float, infra: dict[str, Any],
                 servicenow: dict[str, Any] | None, backlog: list[dict[str, Any]]) -> dict[str, Any]:
    settings = ledger.settings
    if days not in PERIODS:
        raise ValueError(f"days is one of {', '.join(map(str, PERIODS))}.")
    if function and function not in (*FUNCTIONS, "platform"):
        raise ValueError("Unknown function.")
    start = now - days * DAY
    hourly = days == 1
    bucket_size = 3600 if hourly else DAY
    bucket_count = 24 if hourly else days
    first_bucket = (math.floor(now / bucket_size) - bucket_count + 1) * bucket_size

    def bucket(at: float) -> int | None:
        index = int((at - first_bucket) // bucket_size)
        return index if 0 <= index < bucket_count else None

    def selected(fn: str) -> bool:
        return not function or fn == function

    all_runs = [run for run in ledger.runs.values() if start <= run["end"] <= now]
    runs = [run for run in all_runs if selected(run["fn"])]
    cases = [case for case in ledger.cases.values() if selected(case["fn"])]
    credit_usd = USD_PER_CREDIT
    cpc = float(settings["workIqCreditsPerCall"])
    rate = float(settings["peopleHourlyUsd"]) / 60

    infra_per_day = _num(infra.get("fixedPerDay"))
    # The platform is only costed while this host was recording what it did, so early periods aren't inflated.
    coverage = min([ledger.since or now] + [item["start"] for item in ledger.runs.values()]
                   + [item["created"] for item in ledger.cases.values()])
    recorded_from = max(start, coverage)
    recorded_days = max(now - recorded_from, 0.0) / DAY
    infra_total = infra_per_day * recorded_days
    overhead_credits = sum(_num(entry.get("credits")) for day, models in ledger.overhead.items()
                           if day >= day_key(start) for entry in models.values())
    share = (len(runs) / len(all_runs)) if all_runs else (0.0 if function else 1.0)
    per_run_fixed = infra_total / len(all_runs) if all_runs else 0.0
    per_run_overhead = overhead_credits * credit_usd / len(all_runs) if all_runs else 0.0

    def run_cost(run: dict[str, Any]) -> dict[str, float]:
        return {"ai": run["credits"] * credit_usd + per_run_overhead, "workiq": run["workiq"] * cpc * credit_usd,
                "infra": per_run_fixed}

    by_case_runs: dict[str, list[dict[str, Any]]] = {}
    for run in runs:
        if run["case"]:
            by_case_runs.setdefault(run["case"], []).append(run)
    approvals = [item for item in ledger.approvals.values() if selected(item["fn"]) and start <= item["requested"] <= now]
    decided = [item for item in approvals if item.get("decided")]
    approvals_by_case: dict[str, int] = {}
    for item in decided:
        if item.get("case"):
            approvals_by_case[item["case"]] = approvals_by_case.get(item["case"], 0) + 1

    def people_cost(case: dict[str, Any]) -> float:
        minutes = approvals_by_case.get(case["key"], 0) * settings["approvalMinutes"]
        if case.get("escalated") and case.get("finished") and start <= case["finished"] <= now:
            minutes += settings["escalationMinutes"]
        minutes += case.get("reviewReplies", 0) * settings["reviewReplyMinutes"] if start <= case["created"] <= now else 0
        return minutes * rate

    worked = [case for case in cases if case["key"] in by_case_runs or start <= case["created"] <= now]

    def baseline(case: dict[str, Any]) -> float:
        return float(settings["baselineByFunction"].get(case["fn"], settings["baselineCostPerCase"]))

    case_rows = []
    for case in worked:
        parts = {"ai": 0.0, "workiq": 0.0, "infra": 0.0}
        for run in by_case_runs.get(case["key"], ()):
            for name, value in run_cost(run).items():
                parts[name] += value
        parts["people"] = people_cost(case)
        total = sum(parts.values())
        case_rows.append({"case": case, "parts": parts, "total": total, "runs": len(by_case_runs.get(case["key"], ()))})

    ai_usd = sum(run["credits"] for run in runs) * credit_usd + overhead_credits * credit_usd * share
    workiq_calls = sum(run["workiq"] for run in runs)
    workiq_usd = workiq_calls * cpc * credit_usd
    people_minutes = (len(decided) * settings["approvalMinutes"]
                      + sum(settings["escalationMinutes"] for case in cases if case["status"] == "escalated"
                            and case.get("finished") and start <= case["finished"] <= now)
                      + sum(case.get("reviewReplies", 0) * settings["reviewReplyMinutes"] for case in cases
                            if start <= case["created"] <= now))
    people_usd = people_minutes * rate
    infra_usd = infra_total * share
    total_usd = ai_usd + workiq_usd + infra_usd + people_usd
    case_total = sum(row["total"] for row in case_rows)
    baseline_total = sum(baseline(row["case"]) for row in case_rows)

    finished = [case for case in cases if case.get("finished") and start <= case["finished"] <= now]
    resolved = [case for case in cases if case.get("resolved") and start <= _num(case["resolved"]) <= now]
    outcome = {"closed": sum(1 for case in finished if case["status"] == "closed"),
               "escalated": sum(1 for case in finished if case["status"] == "escalated"),
               "cancelled": sum(1 for case in finished if case["status"] == "cancelled"),
               "awaitingConfirmation": sum(1 for case in cases if case["status"] == "resolved"
                                           and start <= _num(case.get("resolved")) <= now)}
    done_without_person = outcome["closed"] + outcome["awaitingConfirmation"] - sum(
        1 for case in finished if case["status"] == "closed" and case.get("escalated"))
    decided_outcomes = outcome["closed"] + outcome["awaitingConfirmation"] + outcome["escalated"]
    opened = [case for case in cases if start <= case["created"] <= now]
    hours_absorbed = max(done_without_person, 0) * settings["humanHandleMinutes"] / 60

    # trends
    series = [{"at": first_bucket + index * bucket_size, "interactions": 0, "ai": 0.0, "workiq": 0.0,
               "infra": infra_per_day * share * max(0.0, min(first_bucket + (index + 1) * bucket_size, now)
                                                   - max(first_bucket + index * bucket_size, recorded_from)) / DAY,
               "people": 0.0, "opened": 0, "finished": 0,
               "escalated": 0, "caseCost": 0.0, "casesWorked": 0} for index in range(bucket_count)]
    for run in runs:
        index = bucket(run["end"])
        if index is not None:
            cost = run_cost(run)
            series[index]["interactions"] += 1
            series[index]["ai"] += cost["ai"]
            series[index]["workiq"] += cost["workiq"]
    for item in decided:
        index = bucket(item["decided"])
        if index is not None:
            series[index]["people"] += settings["approvalMinutes"] * rate
    for case in cases:
        index = bucket(case["created"])
        if index is not None:
            series[index]["opened"] += 1
            series[index]["people"] += case.get("reviewReplies", 0) * settings["reviewReplyMinutes"] * rate
        if case.get("finished"):
            index = bucket(case["finished"])
            if index is not None:
                series[index]["finished"] += 1
                if case["status"] == "escalated":
                    series[index]["escalated"] += 1
                    series[index]["people"] += settings["escalationMinutes"] * rate
    for row in case_rows:
        ends = [run["end"] for run in by_case_runs.get(row["case"]["key"], ())] or [row["case"]["created"]]
        index = bucket(max(ends))
        if index is not None:
            series[index]["caseCost"] += row["total"]
            series[index]["casesWorked"] += 1
    for point in series:
        point["total"] = round(point["ai"] + point["workiq"] + point["infra"] + point["people"], 4)
        point["costPerInteraction"] = round(point["total"] / point["interactions"], 4) if point["interactions"] else None
        point["costPerCase"] = round(point["caseCost"] / point["casesWorked"], 4) if point["casesWorked"] else None
        for name in ("ai", "workiq", "infra", "people", "caseCost"):
            point[name] = round(point[name], 4)

    # breakdowns
    def grouped(key: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for run in runs:
            group = groups.setdefault(key(run), {"interactions": 0, "cost": 0.0, "credits": 0.0, "workiq": 0, "errors": 0})
            group["interactions"] += 1
            group["cost"] += sum(run_cost(run).values())
            group["credits"] += run["credits"]
            group["workiq"] += run["workiq"]
            group["errors"] += 1 if run["error"] else 0
        return sorted(({"name": name, **{k: round(v, 4) if isinstance(v, float) else v for k, v in values.items()},
                        "costPerInteraction": round(values["cost"] / values["interactions"], 4)}
                       for name, values in groups.items()), key=lambda item: -item["cost"])

    colleagues: dict[str, dict[str, Any]] = {}

    def colleague(name: str, fn: str) -> dict[str, Any]:
        return colleagues.setdefault(name, {"name": name, "function": fn, "cases": 0, "caseCost": 0.0, "cost": 0.0,
                                            "baseline": 0.0, "closed": 0, "escalated": 0, "conversations": 0,
                                            "resolutionSeconds": []})

    for row in case_rows:
        case = row["case"]
        entry = colleague(case["colleague"] or FUNCTION_LABELS.get(case["fn"], case["fn"]), case["fn"])
        entry["cases"] += 1
        entry["caseCost"] += row["total"]
        entry["cost"] += row["total"]
        entry["baseline"] += baseline(case)
        if case.get("finished") and start <= case["finished"] <= now:
            entry["closed"] += 1 if case["status"] == "closed" else 0
            entry["escalated"] += 1 if case["status"] == "escalated" else 0
        if case.get("resolved"):
            entry["resolutionSeconds"].append(_num(case["resolved"]) - case["created"])
    for run in runs:
        if not run["case"]:
            entry = colleague(run["colleague"] or "Group Functions Autopilot", run["fn"])
            entry["cost"] += sum(run_cost(run).values())
            entry["conversations"] += 1
    colleague_rows = []
    for entry in colleagues.values():
        seconds = entry.pop("resolutionSeconds")
        interactions = sum(1 for run in runs if (run["colleague"] or "Group Functions Autopilot") == entry["name"])
        colleague_rows.append({**entry, "interactions": interactions, "cost": round(entry["cost"], 4),
                               "caseCost": round(entry["caseCost"], 4), "baseline": round(entry["baseline"], 2),
                               "costPerCase": round(entry["caseCost"] / entry["cases"], 4) if entry["cases"] else None,
                               "autonomousRate": _ratio(entry["closed"], entry["closed"] + entry["escalated"]),
                               "resolution": _minutes(seconds), "functionLabel": FUNCTION_LABELS.get(entry["function"], "")})
    colleague_rows.sort(key=lambda item: -item["cost"])

    models: dict[str, dict[str, Any]] = {}
    for run in runs:
        for name, entry in run["models"].items():
            row = models.setdefault(name, {"model": name, "calls": 0, "in": 0, "out": 0, "cached": 0, "credits": 0.0})
            for field in ("calls", "in", "out", "cached"):
                row[field] += entry.get(field, 0)
            row["credits"] += entry.get("credits", 0.0)
    for day, entries in ledger.overhead.items():
        if day < day_key(start):
            continue
        for name, entry in entries.items():
            row = models.setdefault(name, {"model": name, "calls": 0, "in": 0, "out": 0, "cached": 0, "credits": 0.0})
            row["calls"] += entry.get("calls", 0)
            row["in"] += entry.get("in", 0)
            row["out"] += entry.get("out", 0)
            row["credits"] += entry.get("credits", 0.0) * share
            row["background"] = True
    model_rows = sorted(({**row, "credits": round(row["credits"], 3), "usd": round(row["credits"] * credit_usd, 4),
                          "priced": model_key(row["model"]) is not None} for row in models.values()),
                        key=lambda item: -item["credits"])

    top_cases = sorted(case_rows, key=lambda row: -row["total"])[:8]

    # backlog now
    open_rows = [row for row in backlog if row.get("status") not in FINAL and selected(row.get("function", ""))]
    ages = {"under 1h": 0, "1-4h": 0, "4-24h": 0, "1-3 days": 0, "over 3 days": 0}
    for row in open_rows:
        age = now - _num(row.get("createdAt"))
        label = ("under 1h" if age < 3600 else "1-4h" if age < 4 * 3600 else "4-24h" if age < DAY
                 else "1-3 days" if age < 3 * DAY else "over 3 days")
        ages[label] += 1
    waiting: dict[str, int] = {}
    for row in open_rows:
        reason = row.get("waiting") or ("working" if row.get("status") in {"new", "working"} else row.get("status", ""))
        waiting[reason] = waiting.get(reason, 0) + 1

    # self-service
    self_service = _self_service(ledger, servicenow, runs=runs, cases=cases, opened=opened, start=start, now=now,
                                 function=function, baseline_per_case=float(settings["baselineCostPerCase"]),
                                 cost_per_case=(case_total / len(case_rows)) if case_rows else None)

    run_errors = sum(1 for run in runs if run["error"])
    guard = {"deny": sum(run["guard"]["deny"] for run in runs), "escalate": sum(run["guard"]["escalate"] for run in runs)}
    approved = sum(1 for item in decided if item["status"] in {"completed", "approved"})
    rejected = sum(1 for item in decided if item["status"] == "rejected")
    first_times = [case["firstResponse"] - case["created"] for case in opened if case.get("firstResponse")]
    resolution_times = [_num(case["resolved"]) - case["created"] for case in resolved]
    chats = [run for run in runs if run["src"] == "teams-chat" and not run["case"]]
    return {
        "generatedAt": now, "days": days, "function": function, "currency": "USD", "bucket": "hour" if hourly else "day",
        "coverageSince": coverage, "recordedDays": round(recorded_days, 3),
        "kpis": {
            "costPerCase": round(case_total / len(case_rows), 4) if case_rows else None,
            "baselineCostPerCase": round(baseline_total / len(case_rows), 2) if case_rows else float(settings["baselineCostPerCase"]),
            "costPerInteraction": round(total_usd / len(runs), 4) if runs else None,
            "marginalCostPerCase": round(sum(row["parts"]["ai"] + row["parts"]["workiq"] for row in case_rows) / len(case_rows), 4)
            if case_rows else None,
            "totalCost": round(total_usd, 4), "baselineCost": round(baseline_total, 2),
            "saving": round(baseline_total - case_total, 2) if case_rows else None,
            "savingRate": _ratio(baseline_total - case_total, baseline_total),
            "interactions": len(runs), "casesWorked": len(case_rows), "casesOpened": len(opened),
            "casesFinished": len(finished), "autonomousRate": _ratio(max(done_without_person, 0), decided_outcomes),
            "escalationRate": _ratio(outcome["escalated"], decided_outcomes),
            "hoursAbsorbed": round(hours_absorbed, 1),
            "fteEquivalent": round(hours_absorbed / (7.5 * recorded_days * 5 / 7), 2) if recorded_days >= 1 else None,
            "projectedMonthlyCost": round(total_usd / recorded_days * 30, 2) if recorded_days >= 1 else None,
            "conversationsWithoutCase": len(chats),
        },
        "costs": {
            "ai": round(ai_usd, 4), "workiq": round(workiq_usd, 4), "infrastructure": round(infra_usd, 4),
            "people": round(people_usd, 4), "aiCredits": round(ai_usd / credit_usd, 2),
            "backgroundAiCredits": round(overhead_credits * share, 2), "workiqCalls": workiq_calls,
            "workiqCredits": round(workiq_calls * cpc, 2),
        },
        "series": series,
        "channels": grouped(lambda run: CHANNEL_LABELS.get(run["channel"], run["channel"].replace("-", " ").title() or "Other")),
        "functions": grouped(lambda run: FUNCTION_LABELS.get(run["fn"], run["fn"] or "Platform")),
        "colleagues": colleague_rows,
        "models": model_rows,
        "topCases": [{"key": row["case"]["key"], "title": row["case"]["title"], "colleague": row["case"]["colleague"],
                      "status": row["case"]["status"], "number": row["case"]["number"], "turns": row["case"]["turns"],
                      "interactions": row["runs"], "cost": round(row["total"], 4),
                      "parts": {name: round(value, 4) for name, value in row["parts"].items()},
                      "baseline": baseline(row["case"])} for row in top_cases],
        "quality": {
            "outcomes": outcome, "firstResponse": _minutes(first_times), "resolution": _minutes(resolution_times),
            "reopenRate": _ratio(sum(1 for case in resolved if case.get("resolutions", 0) > 1), len(resolved)),
            "turnsPerCase": round(sum(row["case"]["turns"] for row in case_rows) / len(case_rows), 2) if case_rows else None,
            "runFailureRate": _ratio(run_errors, len(runs)), "runFailures": run_errors,
            "caseErrors": sum(case.get("errors", 0) for case in worked), "guardrails": guard,
            "approvals": {"requested": len(approvals), "decided": len(decided), "approved": approved, "rejected": rejected,
                          "decisionTime": _minutes([item["decided"] - item["requested"] for item in decided])},
        },
        "backlog": {"open": len(open_rows), "ages": ages, "waiting": waiting},
        "selfService": self_service,
        "assumptions": {
            "settings": settings, "usdPerCredit": credit_usd, "infrastructure": infra,
            "prices": {name: {"input": rates[0], "cachedInput": rates[1], "output": rates[2],
                              "longContextAbove": threshold or None} for name, (rates, threshold, _long) in MODEL_PRICES.items()},
            "unpricedModels": sorted({name for run in runs if run.get("unpriced") for name in run["models"]
                                      if model_key(name) is None}),
        },
    }


def _self_service(ledger: AnalyticsLedger, servicenow: dict[str, Any] | None, *, runs: list[dict[str, Any]],
                  cases: list[dict[str, Any]], opened: list[dict[str, Any]], start: float, now: float, function: str,
                  baseline_per_case: float, cost_per_case: float | None) -> dict[str, Any]:
    sn = servicenow if isinstance(servicenow, dict) else {}
    knowledge = sn.get("knowledge") if isinstance(sn.get("knowledge"), dict) else {}
    requests = sn.get("requests") if isinstance(sn.get("requests"), dict) else {}
    incidents = sn.get("incidents") if isinstance(sn.get("incidents"), dict) else {}
    catalog = sn.get("catalog") if isinstance(sn.get("catalog"), dict) else {}
    orders = {str(item.get("id")): int(_num(item.get("count"))) for item in requests.get("byItem") or () if item.get("id")}
    # New self-service content: everything ServiceNow says was created in the window, and whatever the colleagues
    # created (seen in their tool results), matched by sys_id or number.
    content: dict[str, dict[str, Any]] = {}
    if not function or function == "it":
        for item in knowledge.get("created") or ():
            key = f"knowledge:{item.get('id') or item.get('number')}"
            content[key] = {"kind": "knowledge", "sysId": str(item.get("id") or ""), "number": str(item.get("number") or ""),
                            "title": str(item.get("title") or ""), "state": item.get("state"), "active": None,
                            "created": _sn_time(item.get("createdOn")) or now, "colleague": "", "fn": "it", "case": "",
                            "uses": int(_num(item.get("usesInWindow"))), "views": int(_num(item.get("views")))}
        for item in catalog.get("created") or ():
            key = f"catalog:{item.get('id')}"
            content[key] = {"kind": "catalog", "sysId": str(item.get("id") or ""), "number": "", "title": str(item.get("name") or ""),
                            "state": None, "active": bool(item.get("active")), "created": _sn_time(item.get("createdOn")) or now,
                            "colleague": "", "fn": "it", "case": "", "uses": orders.get(str(item.get("id") or ""), 0),
                            "views": None}
    numbers = {item["number"]: key for key, item in content.items() if item["number"]}
    for fact in ledger.assets.values():
        if function and fact["fn"] != function:
            continue
        key = f"{fact['kind']}:{fact['sysId']}" if fact["sysId"] else numbers.get(fact.get("number", ""), fact["id"])
        key = key if key in content else numbers.get(fact.get("number", ""), key)
        if key in content:
            found = content[key]
            found.update(colleague=fact["colleague"], fn=fact["fn"], case=fact.get("case", ""),
                         created=min(found["created"], fact["created"]), title=found["title"] or fact["title"],
                         number=found["number"] or fact.get("number", ""))
            continue
        uses = orders.get(fact["sysId"], 0) if fact["kind"] == "catalog" and sn.get("requests") else None
        content[key] = {"kind": fact["kind"], "sysId": fact["sysId"], "number": fact.get("number", ""), "title": fact["title"],
                        "state": fact.get("state"), "active": fact.get("active"), "created": fact["created"],
                        "colleague": fact["colleague"], "fn": fact["fn"], "case": fact.get("case", ""), "uses": uses,
                        "views": None}
    assets = sorted(content.values(), key=lambda item: -item["created"])
    uses = sum(item["uses"] or 0 for item in assets)
    self_served = int(_num(requests.get("total"))) + int(_num(knowledge.get("uses")))
    assisted = int(_num(incidents.get("total"))) + sum(1 for case in opened if case["src"] not in {"servicenow", "sweep"})
    channels = incidents.get("byChannel") or {}
    self_channels = sum(int(_num(value)) for name, value in channels.items()
                        if name in {"self-service", "virtual_agent", "chat", "portal"})
    by_day: dict[str, dict[str, int]] = {}
    for day, counts in (incidents.get("byDay") or {}).items():
        if isinstance(counts, dict):
            by_day.setdefault(day, {})["incidents"] = sum(int(_num(value)) for value in counts.values())
    for day, count in (requests.get("byDay") or {}).items():
        by_day.setdefault(day, {})["requests"] = int(_num(count))
    for day, count in (knowledge.get("usesByDay") or {}).items():
        by_day.setdefault(day, {})["knowledge"] = int(_num(count))
    resolved_chats = sum(1 for run in runs if run["src"] == "teams-chat" and not run["case"] and not run["error"])
    connected = bool(sn) and not sn.get("error") and not all(
        isinstance(section, dict) and section.get("error") for section in (incidents, requests, knowledge) if section)
    return {
        "connected": connected, "error": sn.get("error") or "",
        "assets": assets[:30], "assetsCreated": sum(1 for item in assets if start <= item["created"] <= now),
        "assetsByColleagues": sum(1 for item in assets if item["colleague"]),
        "assetUses": uses, "casesAvoided": uses,
        "avoidedValueAtBaseline": round(uses * baseline_per_case, 2),
        "avoidedValueAtCurrentCost": round(uses * cost_per_case, 4) if cost_per_case is not None else None,
        "demand": {"selfServed": self_served, "assisted": assisted,
                   "selfServiceRate": _ratio(self_served, self_served + assisted) if connected else None,
                   "catalogRequests": int(_num(requests.get("total"))), "knowledgeUses": int(_num(knowledge.get("uses"))),
                   "incidents": int(_num(incidents.get("total"))), "incidentsSelfRaised": self_channels,
                   "incidentChannels": channels, "publishedArticles": knowledge.get("published"),
                   "activeCatalogItems": catalog.get("active"), "topRequests": (requests.get("byItem") or [])[:8],
                   "byDay": dict(sorted(by_day.items()))},
        "resolvedInConversation": resolved_chats,
        "themes": _themes([case["title"] for case in cases if start <= case["created"] <= now and case["title"]]),
    }
