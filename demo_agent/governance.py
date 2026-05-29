"""Runtime control-plane enforcement for the ESS Agent 365 demo.

This module is the runtime side of WPP's "Control Plane enforcement" agenda
item:

* Centralised, in-process policy state — kill switch per agent identity
  instance, and a deny-list of MCP tool patterns.
* Enforced before every MCP tool call (via ``is_tool_blocked``) and before
  every instance launch (via ``is_instance_disabled``).
* Decisions are recorded into an in-memory audit ledger so the control plane
  UI / compliance officer can see exactly which agents were isolated, which
  tools were blocked, and when — i.e. "evidence for investigations".

State is persisted best-effort to ``/tmp/ess-governance.json`` so a single
container restart does not lose the operator's enforcement actions. The file
is JSON, hand-editable, and recreated on startup if missing/corrupt.

Importing this module is side-effect free; ``governance_state`` is the
process-wide singleton.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("ess-mcp.demo_agent.governance")

_STATE_PATH = Path(os.getenv("ESS_GOVERNANCE_STATE_PATH", "/tmp/ess-governance.json"))
_AUDIT_LIMIT = 200


@dataclass
class EnforcementDecision:
    """Outcome of a governance check against a single tool call or run."""

    allowed: bool
    reason: str = ""
    rule: str = ""

    @property
    def blocked(self) -> bool:
        return not self.allowed


@dataclass
class GovernanceEvent:
    """One entry in the governance audit ledger."""

    timestamp_ms: int
    actor: str
    action: str
    target: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestampMs": self.timestamp_ms,
            "actor": self.actor,
            "action": self.action,
            "target": self.target,
            "detail": self.detail,
        }


class GovernanceState:
    """Process-wide control-plane enforcement state."""

    def __init__(self, state_path: Path = _STATE_PATH) -> None:
        self._lock = threading.RLock()
        self._state_path = state_path
        self._disabled_instances: dict[str, str] = {}
        self._tool_denylist: list[str] = []
        self._audit: list[GovernanceEvent] = []
        self._load()

    # ── persistence ────────────────────────────────────────────────
    def _load(self) -> None:
        try:
            if self._state_path.exists():
                raw = json.loads(self._state_path.read_text(encoding="utf-8"))
                self._disabled_instances = dict(raw.get("disabledInstances") or {})
                self._tool_denylist = list(raw.get("toolDenylist") or [])
                for entry in raw.get("audit") or []:
                    try:
                        self._audit.append(GovernanceEvent(
                            timestamp_ms=int(entry.get("timestampMs", 0)),
                            actor=str(entry.get("actor", "")),
                            action=str(entry.get("action", "")),
                            target=str(entry.get("target", "")),
                            detail=dict(entry.get("detail") or {}),
                        ))
                    except Exception:  # noqa: BLE001 - best effort restore
                        continue
                self._audit = self._audit[-_AUDIT_LIMIT:]
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            logger.warning("Failed to load governance state from %s: %s", self._state_path, exc)
            self._disabled_instances = {}
            self._tool_denylist = []
            self._audit = []

    def _persist(self) -> None:
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(
                json.dumps(
                    {
                        "disabledInstances": self._disabled_instances,
                        "toolDenylist": self._tool_denylist,
                        "audit": [e.to_dict() for e in self._audit[-_AUDIT_LIMIT:]],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001 - persistence is best effort
            logger.warning("Failed to persist governance state to %s: %s", self._state_path, exc)

    # ── audit log ──────────────────────────────────────────────────
    def _record(self, actor: str, action: str, target: str, detail: dict[str, Any] | None = None) -> GovernanceEvent:
        event = GovernanceEvent(
            timestamp_ms=int(time.time() * 1000),
            actor=actor,
            action=action,
            target=target,
            detail=detail or {},
        )
        self._audit.append(event)
        self._audit = self._audit[-_AUDIT_LIMIT:]
        return event

    def audit_log(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in reversed(self._audit[-limit:])]

    # ── kill switch ────────────────────────────────────────────────
    def disable_instance(self, instance_id: str, *, reason: str, actor: str) -> GovernanceEvent:
        if not instance_id:
            raise ValueError("instance_id is required")
        with self._lock:
            self._disabled_instances[instance_id] = reason or "Disabled by control plane operator"
            event = self._record(actor, "disable_instance", instance_id, {"reason": reason})
            self._persist()
            return event

    def enable_instance(self, instance_id: str, *, actor: str) -> GovernanceEvent | None:
        with self._lock:
            if instance_id not in self._disabled_instances:
                return None
            previous_reason = self._disabled_instances.pop(instance_id)
            event = self._record(actor, "enable_instance", instance_id, {"previousReason": previous_reason})
            self._persist()
            return event

    def is_instance_disabled(self, instance_id: str) -> EnforcementDecision:
        with self._lock:
            reason = self._disabled_instances.get(instance_id or "")
        if reason:
            return EnforcementDecision(allowed=False, reason=reason, rule="instance_disabled")
        return EnforcementDecision(allowed=True)

    def disabled_instances(self) -> dict[str, str]:
        with self._lock:
            return dict(self._disabled_instances)

    # ── tool deny-list ─────────────────────────────────────────────
    def set_tool_denylist(self, patterns: list[str], *, actor: str) -> GovernanceEvent:
        cleaned: list[str] = []
        for pat in patterns or []:
            pat = (pat or "").strip()
            if pat and pat not in cleaned:
                cleaned.append(pat)
        with self._lock:
            previous = list(self._tool_denylist)
            self._tool_denylist = cleaned
            event = self._record(actor, "set_tool_denylist", "*", {
                "patterns": cleaned,
                "previous": previous,
            })
            self._persist()
            return event

    def tool_denylist(self) -> list[str]:
        with self._lock:
            return list(self._tool_denylist)

    def is_tool_blocked(self, server: str, tool: str) -> EnforcementDecision:
        qualified = f"{server}.{tool}".lower()
        bare = (tool or "").lower()
        server_lc = (server or "").lower()
        with self._lock:
            patterns = list(self._tool_denylist)
        for pat in patterns:
            pat_lc = pat.lower()
            if (
                fnmatch.fnmatchcase(qualified, pat_lc)
                or fnmatch.fnmatchcase(bare, pat_lc)
                or fnmatch.fnmatchcase(server_lc, pat_lc)
                or fnmatch.fnmatchcase(f"{server_lc}.*", pat_lc)
            ):
                return EnforcementDecision(
                    allowed=False,
                    reason=f"Tool '{qualified}' matches control-plane deny rule '{pat}'",
                    rule=pat,
                )
        return EnforcementDecision(allowed=True)

    def record_tool_block(self, *, server: str, tool: str, decision: EnforcementDecision, run_id: str, actor: str) -> GovernanceEvent:
        return self._record(
            actor,
            "tool_blocked",
            f"{server}.{tool}",
            {
                "rule": decision.rule,
                "reason": decision.reason,
                "runId": run_id,
            },
        )

    def record_run_blocked(self, *, instance_id: str, decision: EnforcementDecision, actor: str, scenario: str = "") -> GovernanceEvent:
        return self._record(
            actor,
            "run_blocked",
            instance_id,
            {
                "rule": decision.rule,
                "reason": decision.reason,
                "scenario": scenario,
            },
        )

    # ── snapshot ───────────────────────────────────────────────────
    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "disabledInstances": dict(self._disabled_instances),
                "toolDenylist": list(self._tool_denylist),
                "auditCount": len(self._audit),
                "statePath": str(self._state_path),
            }


# Process-wide singleton
governance_state = GovernanceState()


__all__ = [
    "EnforcementDecision",
    "GovernanceEvent",
    "GovernanceState",
    "governance_state",
]
