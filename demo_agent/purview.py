"""Purview Information Protection integration for the ESS demo agent.

Two responsibilities:

1. **Label classification** — `PurviewLabelClient` resolves a sensitivity label
   for a piece of content. When the agent's managed identity has been granted
   `InformationProtectionPolicy.Read.All` Microsoft Graph permissions and a
   tenant Purview Information Protection policy exists, we pull the live
   sensitivity-label catalogue and pick the most-restrictive matching label.
   When Graph is unavailable we fall back to a deterministic heuristic
   classifier that recognises common HR identifiers (SSN, US phone numbers,
   compensation strings, named confidential keywords). Either way the result
   is a `ResolvedLabel` with `id`, `name`, `priority`, `source`.

2. **Policy enforcement** — `LabelPolicy` loads `purview-policy.yaml` and
   maps a `ResolvedLabel` to one of `allow | redact | block`, optionally
   redacting matching patterns inline. It returns a `PolicyDecision` containing
   the action, the (possibly transformed) content, and a list of
   `applied_patterns` used for telemetry.

Both classes are designed to never raise: every external dependency is wrapped
so a misconfigured Purview tenant degrades to "label as Public, allow" rather
than blocking the run. Telemetry attributes follow Microsoft's Agent 365
conventions (`microsoft.purview.sensitivity_label_id`,
`microsoft.purview.sensitivity_label_name`, `agent.tool_result.policy_applied`).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import httpx

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ResolvedLabel:
    """A sensitivity label assigned to a piece of content."""

    id: str
    name: str
    priority: int = 0
    color: str = ""
    source: str = "heuristic"  # "graph" | "heuristic" | "explicit"
    matched_signals: tuple[str, ...] = ()
    parent_id: str = ""


@dataclass
class PolicyDecision:
    """Outcome of running a `ResolvedLabel` through `LabelPolicy.evaluate`."""

    action: str  # "allow" | "redact" | "block"
    content: str
    label: ResolvedLabel
    reason: str = ""
    applied_patterns: list[str] = field(default_factory=list)

    @property
    def transformed(self) -> bool:
        return self.action != "allow"

    def telemetry_attributes(self) -> dict[str, Any]:
        return {
            "microsoft.purview.sensitivity_label_id": self.label.id,
            "microsoft.purview.sensitivity_label_name": self.label.name,
            "microsoft.purview.sensitivity_label_priority": self.label.priority,
            "microsoft.purview.sensitivity_label_source": self.label.source,
            "agent.tool_result.policy_applied": self.action,
            "agent.tool_result.policy_reason": self.reason,
            "agent.tool_result.policy_patterns": ",".join(self.applied_patterns),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Purview label client
# ─────────────────────────────────────────────────────────────────────────────


# Default heuristic label catalogue (used when Graph is unreachable). Higher
# priority is more sensitive.
_HEURISTIC_LABELS: tuple[ResolvedLabel, ...] = (
    ResolvedLabel(id="ess-demo-public", name="ESS-Demo-General", priority=10, color="#107C10", source="heuristic"),
    ResolvedLabel(id="ess-demo-confidential", name="ESS-Demo-Confidential", priority=50, color="#FFB900", source="heuristic"),
    ResolvedLabel(id="ess-demo-highly-confidential", name="ESS-Demo-Highly-Confidential", priority=90, color="#A80000", source="heuristic"),
)

# Map well-known Microsoft Purview label names to the same 10/50/90 priority
# scale the heuristic classifier uses, so a Graph-sourced catalogue routes
# `confidential-signal` to a label named "Confidential" rather than to the
# most-sensitive label in the catalogue (which is what raw Graph `sensitivity`
# integers, typically 0..4, would otherwise produce).
_WELL_KNOWN_PRIORITY: dict[str, int] = {
    "personal": 5,
    "non-business": 5,
    "public": 10,
    "general": 25,
    "internal": 25,
    "confidential": 50,
    "highly confidential": 90,
    "restricted": 85,
    "secret": 95,
    "top secret": 99,
}

_HIGHLY_CONFIDENTIAL_SIGNALS = (
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # US SSN
    re.compile(r"\bpassport\s*(?:no\.?|number)\s*[:#]?\s*[A-Z0-9]{6,}\b", re.IGNORECASE),
    re.compile(r"\bpassword\s*[:=]\s*\S+", re.IGNORECASE),
    re.compile(r"\bbank\s+account\s+number\b", re.IGNORECASE),
)

_CONFIDENTIAL_SIGNALS = (
    re.compile(r"\b\$\s?\d{2,3}(?:,\d{3})+(?:\.\d{2})?\b"),  # salary
    re.compile(r"\bsalary\s*[:=]?\s*\$?\d", re.IGNORECASE),
    re.compile(r"\b(?:compensation|stock\s+grant|severance|offer\s+letter)\b", re.IGNORECASE),
    re.compile(r"\b(?:performance\s+rating|pip|under\s+performing)\b", re.IGNORECASE),
    re.compile(r"\b\d{3}-\d{3}-\d{4}\b"),  # phone
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
)


# ---------------------------------------------------------------------------
# Token + HTTP helpers (Graph)
# ---------------------------------------------------------------------------


def _jwt_exp(token: str) -> float | None:
    """Best-effort `exp` claim extraction from a JWT, returning epoch seconds."""
    try:
        parts = token.split(".")
        if len(parts) < 2:
            return None
        payload = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload).decode("utf-8"))
        exp = claims.get("exp")
        return float(exp) if exp is not None else None
    except Exception:
        return None


class _TokenCache:
    """In-process bearer-token cache. Reuses a token until ~5 min before its
    JWT `exp` claim; if the claim can't be decoded, falls back to a 50-minute
    TTL (Graph tokens are typically 60–90 min)."""

    def __init__(
        self,
        provider: Any,
        *,
        refresh_buffer_seconds: int = 300,
        default_ttl_seconds: int = 3000,
    ) -> None:
        self._provider = provider
        self._refresh_buffer = refresh_buffer_seconds
        self._default_ttl = default_ttl_seconds
        self._lock = threading.Lock()
        self._token: str | None = None
        self._expires_at: float = 0.0

    def token(self) -> str | None:
        if self._provider is None:
            return None
        now = time.time()
        with self._lock:
            if self._token and now < (self._expires_at - self._refresh_buffer):
                return self._token
        try:
            raw = self._provider() if callable(self._provider) else self._provider
        except Exception as exc:
            logger.warning("Purview token provider raised: %s", exc)
            return None
        if not raw:
            return None
        token = str(raw)
        exp = _jwt_exp(token) or (time.time() + self._default_ttl)
        with self._lock:
            self._token = token
            self._expires_at = exp
        return token

    def invalidate(self) -> None:
        with self._lock:
            self._token = None
            self._expires_at = 0.0


def _bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def _get_with_retry(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    *,
    max_attempts: int = 3,
) -> httpx.Response | None:
    """GET `url`, honouring `Retry-After` on 429/503 with capped backoff.
    Returns None when every attempt raised at the transport layer."""
    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.get(url, headers=headers)
        except Exception:
            if attempt == max_attempts:
                return None
            time.sleep(min(2 ** (attempt - 1), 5))
            continue
        if resp.status_code in (429, 503) and attempt < max_attempts:
            retry_after = resp.headers.get("Retry-After", "")
            try:
                delay = float(retry_after)
            except ValueError:
                delay = float(2 ** (attempt - 1))
            time.sleep(min(delay, 30.0))
            continue
        return resp
    return None


def _fetch_paged(
    client: httpx.Client,
    url: str,
    headers: dict[str, str],
    *,
    max_pages: int = 20,
) -> tuple[list[dict] | None, str]:
    """Fetch a Graph collection, following `@odata.nextLink`.

    Returns `(entries, last_error)`. `entries` is `None` when the **initial**
    page failed in a way the caller should treat as "try the next fallback
    endpoint" (transport error or non-200 on page 1). Subsequent page failures
    return whatever was accumulated so far.
    """
    out: list[dict] = []
    page_url: str = url
    pages = 0
    last_err = ""
    while page_url and pages < max_pages:
        pages += 1
        resp = _get_with_retry(client, page_url, headers)
        if resp is None:
            return (None, f"{page_url} → transport error") if pages == 1 else (out, "transport error mid-page")
        if resp.status_code != 200:
            err = f"{page_url} → {resp.status_code}: {resp.text[:160]}"
            return (None, err) if pages == 1 else (out, err)
        try:
            payload = resp.json()
        except Exception as exc:
            err = f"{page_url} → invalid json: {exc}"
            return (None, err) if pages == 1 else (out, err)
        if isinstance(payload, dict):
            value = payload.get("value") or []
            if isinstance(value, list):
                out.extend(value)
            page_url = str(payload.get("@odata.nextLink") or "")
        else:
            page_url = ""
    return out, last_err


class PurviewLabelClient:
    """Resolves sensitivity labels for tool outputs.

    Args:
        graph_token_provider: optional callable returning a Microsoft Graph
            access token (string) for the calling MI/principal. When provided
            and the token grants `InformationProtectionPolicy.Read.All`, the
            tenant's labels are fetched once per `cache_seconds` and used to
            classify content.
        enabled: master switch; when False the client always returns the
            "ESS-Demo-General" heuristic label (`source="heuristic"`).
    """

    GRAPH_LABELS_URL = "https://graph.microsoft.com/v1.0/security/informationProtection/sensitivityLabels"
    # Fallback endpoints tried in order until one returns 200. The v1.0
    # `security/informationProtection` path is not exposed on every tenant;
    # `beta` consistently is when the MI has `InformationProtectionPolicy.Read.All`.
    GRAPH_LABELS_URLS: tuple[str, ...] = (
        "https://graph.microsoft.com/beta/security/informationProtection/sensitivityLabels",
        "https://graph.microsoft.com/beta/informationProtection/policy/labels",
        "https://graph.microsoft.com/v1.0/security/informationProtection/sensitivityLabels",
    )

    def __init__(
        self,
        *,
        graph_token_provider: Any = None,
        enabled: bool = True,
        cache_seconds: int = 900,
    ) -> None:
        self._token_provider = graph_token_provider
        self._token_cache = _TokenCache(graph_token_provider)
        self._enabled = enabled
        self._cache_seconds = cache_seconds
        self._cache_lock = threading.Lock()
        self._cached_labels: list[ResolvedLabel] = []
        self._cached_at: float = 0.0
        self._graph_warning_logged = False
        self._last_graph_error: str | None = None
        self._last_graph_endpoint: str | None = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def cached_labels(self) -> list[ResolvedLabel]:
        with self._cache_lock:
            return list(self._cached_labels)

    @property
    def cached_at(self) -> float:
        return self._cached_at

    @property
    def last_graph_error(self) -> str | None:
        return self._last_graph_error

    @property
    def last_graph_endpoint(self) -> str | None:
        return self._last_graph_endpoint

    def refresh(self) -> None:
        """Bust the in-memory cache so the next classify() re-fetches from Graph."""
        with self._cache_lock:
            self._cached_labels = []
            self._cached_at = 0.0
            self._graph_warning_logged = False
            self._last_graph_error = None

    def reload(self) -> list[ResolvedLabel]:
        """Force-refresh and return the active catalogue (for diagnostics)."""
        self.refresh()
        return self._labels()

    # -- Public API ---------------------------------------------------------

    def classify(self, content: str, *, hint: str | None = None) -> ResolvedLabel:
        """Return the most-restrictive label that matches `content`.

        `hint` is an optional explicit label name (e.g. provided by an MCP
        server in its response payload). If supplied and known, it short-
        circuits classification.
        """
        if not self._enabled:
            return _HEURISTIC_LABELS[0]
        if not content:
            return _HEURISTIC_LABELS[0]

        catalogue = self._labels()

        if hint:
            for lbl in catalogue:
                if lbl.name.lower() == hint.lower() or lbl.id.lower() == hint.lower():
                    return ResolvedLabel(
                        id=lbl.id,
                        name=lbl.name,
                        priority=lbl.priority,
                        color=lbl.color,
                        source="explicit",
                        matched_signals=("hint",),
                        parent_id=lbl.parent_id,
                    )

        signals: list[str] = []
        if any(p.search(content) for p in _HIGHLY_CONFIDENTIAL_SIGNALS):
            signals.append("highly-confidential-signal")
            return _pick_label(catalogue, target_priority=90, signals=tuple(signals))
        if any(p.search(content) for p in _CONFIDENTIAL_SIGNALS):
            signals.append("confidential-signal")
            return _pick_label(catalogue, target_priority=50, signals=tuple(signals))
        return _pick_label(catalogue, target_priority=10, signals=("default",))

    # -- Internals ----------------------------------------------------------

    def _labels(self) -> list[ResolvedLabel]:
        with self._cache_lock:
            now = time.time()
            if self._cached_labels and (now - self._cached_at) < self._cache_seconds:
                return self._cached_labels

        graph_labels: list[ResolvedLabel] = []
        if self._token_provider is not None:
            try:
                graph_labels = self._fetch_graph_labels()
                self._last_graph_error = None
            except Exception as exc:
                self._last_graph_error = str(exc)
                if not self._graph_warning_logged:
                    logger.warning("Purview Graph label fetch failed: %s — falling back to heuristic catalogue", exc)
                    self._graph_warning_logged = True

        labels = graph_labels or list(_HEURISTIC_LABELS)
        with self._cache_lock:
            self._cached_labels = labels
            self._cached_at = time.time()
        return labels

    def _fetch_graph_labels(self) -> list[ResolvedLabel]:
        token = self._token_cache.token()
        if not token:
            return []
        data: list[dict] = []
        last_err: str = ""
        used_endpoint = ""
        with httpx.Client(timeout=10.0) as client:
            for url in self.GRAPH_LABELS_URLS:
                entries, err = _fetch_paged(client, url, _bearer_headers(token))
                if entries is not None:
                    data = entries
                    used_endpoint = url
                    break
                if err:
                    last_err = err
        if not used_endpoint:
            # If the failure looks token-related, drop the cached bearer so the
            # next call re-mints (covers revoked / role-change scenarios).
            if "401" in last_err or "403" in last_err:
                self._token_cache.invalidate()
            raise RuntimeError(f"all Graph label endpoints failed; last: {last_err}")
        self._last_graph_endpoint = used_endpoint  # type: ignore[attr-defined]

        # Index entries by id so we can resolve parent priority for sub-labels.
        by_id: dict[str, dict] = {}
        for entry in data:
            lid = str(entry.get("id") or entry.get("labelId") or "").strip()
            if lid:
                by_id[lid] = entry

        def _parent_id(entry: dict) -> str:
            parent = entry.get("parent") or {}
            if isinstance(parent, dict):
                return str(parent.get("id") or "").strip()
            return ""

        def _canonical_for(entry: dict, *, depth: int = 0) -> int:
            """Return canonical priority for a label, inheriting from its parent
            if the leaf name isn't in the well-known table."""
            name = str(entry.get("name") or entry.get("displayName") or "").strip().lower()
            own = _WELL_KNOWN_PRIORITY.get(name, 0)
            pid = _parent_id(entry)
            parent_prio = 0
            if pid and pid in by_id and depth < 5:
                parent_prio = _canonical_for(by_id[pid], depth=depth + 1)
            return max(own, parent_prio)

        # First pass: collect raw entries with their native sensitivity rank.
        raw: list[tuple[int, dict]] = []
        for entry in data:
            try:
                sens = int(entry.get("sensitivity") or entry.get("priority") or 0)
            except Exception:
                sens = 0
            raw.append((sens, entry))
        # Sort low → high sensitivity so we can rank-normalise unknown names.
        raw.sort(key=lambda t: t[0])
        n = len(raw)
        out: list[ResolvedLabel] = []
        for idx, (sens, entry) in enumerate(raw):
            name = str(entry.get("name") or entry.get("displayName") or "").strip()
            lid = str(entry.get("id") or entry.get("labelId") or "").strip()
            pid = _parent_id(entry)
            canonical = _canonical_for(entry)
            if canonical:
                priority = canonical
            elif n <= 1:
                priority = 50
            else:
                # Evenly map rank into the 10..90 band so the signal-target
                # priorities (10/50/90) used by the classifier still pick the
                # right label even when tenant label names are custom.
                priority = int(round(10 + (idx / (n - 1)) * 80))
            try:
                out.append(
                    ResolvedLabel(
                        id=lid,
                        name=name,
                        priority=priority,
                        color=str(entry.get("color") or ""),
                        source="graph",
                        parent_id=pid,
                    )
                )
            except Exception:
                continue
        return [lbl for lbl in out if lbl.id and lbl.name]


def _pick_label(catalogue: Iterable[ResolvedLabel], *, target_priority: int, signals: tuple[str, ...]) -> ResolvedLabel:
    """Return the label whose priority is closest to (but not exceeding) target."""
    candidates = sorted(catalogue, key=lambda l: l.priority)
    chosen: ResolvedLabel | None = None
    for lbl in candidates:
        if lbl.priority <= target_priority:
            chosen = lbl
        else:
            break
    if chosen is None and candidates:
        chosen = candidates[0]
    if chosen is None:
        chosen = _HEURISTIC_LABELS[0]
    return ResolvedLabel(
        id=chosen.id,
        name=chosen.name,
        priority=chosen.priority,
        color=chosen.color,
        source=chosen.source,
        matched_signals=signals,
        parent_id=chosen.parent_id,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Label policy (YAML-driven enforcement)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _PolicyRule:
    match_id: str | None
    match_name: str | None
    match_priority_min: int | None
    action: str
    reason: str

    def matches(self, label: ResolvedLabel) -> bool:
        if self.match_id and label.id and self.match_id.strip().lower() == label.id.strip().lower():
            return True
        if self.match_name and label.name and self.match_name.strip().lower() == label.name.strip().lower():
            return True
        if self.match_priority_min is not None and label.priority >= self.match_priority_min:
            return True
        return False


@dataclass(frozen=True)
class _RedactionPattern:
    name: str
    pattern: re.Pattern[str]
    placeholder: str


class LabelPolicy:
    """Loads `purview-policy.yaml` and decides what to do per label."""

    def __init__(
        self,
        *,
        rules: list[_PolicyRule],
        redaction_patterns: list[_RedactionPattern],
        default_action: str = "allow",
    ) -> None:
        self._rules = rules
        self._redaction_patterns = redaction_patterns
        self._default_action = default_action

    @classmethod
    def load(cls, path: str | Path) -> "LabelPolicy":
        try:
            import yaml  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("PyYAML is required to load purview-policy.yaml") from exc
        text = Path(path).read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
        rules: list[_PolicyRule] = []
        for entry in data.get("rules", []) or []:
            match = entry.get("match", {}) or {}
            rules.append(
                _PolicyRule(
                    match_id=str(match["id"]) if match.get("id") else None,
                    match_name=str(match["name"]) if match.get("name") else None,
                    match_priority_min=int(match["priority_min"]) if match.get("priority_min") is not None else None,
                    action=str(entry.get("action", "allow")).lower(),
                    reason=str(entry.get("reason", "")),
                )
            )
        patterns: list[_RedactionPattern] = []
        for entry in data.get("redaction_patterns", []) or []:
            try:
                patterns.append(
                    _RedactionPattern(
                        name=str(entry.get("name", "pattern")),
                        pattern=re.compile(str(entry["pattern"]), re.IGNORECASE),
                        placeholder=str(entry.get("placeholder", "[REDACTED]")),
                    )
                )
            except (KeyError, re.error) as exc:
                logger.warning("Skipping bad Purview redaction pattern %r: %s", entry, exc)
        default_action = str(data.get("default_action", "allow")).lower()
        return cls(rules=rules, redaction_patterns=patterns, default_action=default_action)

    @classmethod
    def default(cls) -> "LabelPolicy":
        """Return a permissive in-memory policy used when the YAML is absent."""
        return cls(
            rules=[
                _PolicyRule(None, "ESS-Demo-Highly-Confidential", None, "block", "Heuristic block"),
                _PolicyRule(None, "ESS-Demo-Confidential", None, "redact", "Heuristic redact"),
            ],
            redaction_patterns=[
                _RedactionPattern("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED:SSN]"),
                _RedactionPattern("phone", re.compile(r"\b\d{3}-\d{3}-\d{4}\b"), "[REDACTED:PHONE]"),
                _RedactionPattern("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE), "[REDACTED:EMAIL]"),
                _RedactionPattern("salary", re.compile(r"\$\s?\d{2,3}(?:,\d{3})+(?:\.\d{2})?"), "[REDACTED:SALARY]"),
            ],
            default_action="allow",
        )

    # -- Public API ---------------------------------------------------------

    def evaluate(self, *, content: str, label: ResolvedLabel) -> PolicyDecision:
        action = self._default_action
        reason = ""
        for rule in self._rules:
            if rule.matches(label):
                action = rule.action
                reason = rule.reason or f"Matched policy for {label.name}"
                break

        if action == "block":
            blocked = (
                f"[BLOCKED BY PURVIEW POLICY: label={label.name} ({label.id}); "
                f"reason={reason or 'sensitivity exceeds allowed threshold'}]"
            )
            return PolicyDecision(action="block", content=blocked, label=label, reason=reason or "blocked by policy")

        if action == "redact":
            redacted, applied = self._apply_redactions(content)
            if not applied:
                # No patterns matched: still mark as redacted-no-op for telemetry.
                return PolicyDecision(action="redact", content=redacted, label=label, reason=reason or "policy redact (no patterns matched)", applied_patterns=[])
            return PolicyDecision(action="redact", content=redacted, label=label, reason=reason or "policy redact", applied_patterns=applied)

        return PolicyDecision(action="allow", content=content, label=label, reason=reason)

    def _apply_redactions(self, content: str) -> tuple[str, list[str]]:
        out = content
        applied: list[str] = []
        for pat in self._redaction_patterns:
            new, n = pat.pattern.subn(pat.placeholder, out)
            if n > 0:
                applied.append(pat.name)
                out = new
        return out, applied


# ─────────────────────────────────────────────────────────────────────────────
# Module-level singletons
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_POLICY_PATH = Path(__file__).with_name("purview-policy.yaml")


def load_default_policy() -> LabelPolicy:
    """Load the bundled YAML policy, falling back to a permissive in-memory one."""
    try:
        if _DEFAULT_POLICY_PATH.exists():
            return LabelPolicy.load(_DEFAULT_POLICY_PATH)
    except Exception as exc:
        logger.warning("Failed to load %s: %s — using default in-memory policy", _DEFAULT_POLICY_PATH, exc)
    return LabelPolicy.default()


def is_purview_enabled() -> bool:
    """Master env switch — defaults to true, can be disabled via PURVIEW_ENABLED=false."""
    raw = os.getenv("PURVIEW_ENABLED", "true").strip().lower()
    return raw in ("1", "true", "yes", "on")
