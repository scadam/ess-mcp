"""Agent Governance Toolkit guardrails: the harness asks an AGT policy before anything happens.

The host is the policy enforcement point. At each Agent Control Specification (ACS) intervention point
(run start, request, every model call, every tool call and result, the final answer, run end) it builds
a complete snapshot and asks the ACS runtime, which evaluates the operator's Rego policy with OPA and
returns allow, warn, deny, escalate or transform. ACS fails closed: a broken policy or engine denies.
Policies are versioned, validated and tested before they are published, and swap in without a restart.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping

try:
    from agent_control_specification import AgentControl, validate_acs_artifacts
except ImportError:  # No wheel exists for Windows development hosts; the Linux image always has it.
    AgentControl = None
    validate_acs_artifacts = None

_logger = logging.getLogger("group-functions-autopilot.guardrails")

POLICY_DIR = Path(__file__).with_name("guardrail_policy")
POINTS = ("agent_startup", "input", "pre_model_call", "post_model_call", "pre_tool_call", "post_tool_call",
          "output", "agent_shutdown")
MODES = ("enforce", "evaluate_only", "off")
MANIFEST_VERSION = "0.3.1-beta"
QUERY = "data.guardrails.verdict"
MAX_REGO_BYTES = 96_000
MAX_DATA_BYTES = 48_000
MAX_VERSIONS = 12
MAX_DECISIONS = 500
TEXT_CHUNK = 60_000  # ACS bounds each snapshot (a tool result of ~250 KB is its limit); long text is windowed.
EVALUATION_TIMEOUT = 15.0

_BINDINGS: dict[str, dict[str, str]] = {
    "agent_startup": {"policy_target": "$.agent", "policy_target_kind": "agent"},
    "input": {"policy_target": "$.input", "policy_target_kind": "user_input"},
    "pre_model_call": {"policy_target": "$.model_request", "policy_target_kind": "model_request"},
    "post_model_call": {"policy_target": "$.model_response", "policy_target_kind": "model_response"},
    "pre_tool_call": {"policy_target": "$.tool_call.args", "policy_target_kind": "tool_args",
                      "tool_name_from": "$.tool_call.name"},
    "post_tool_call": {"policy_target": "$.tool_result", "policy_target_kind": "tool_result",
                       "tool_name_from": "$.tool_call.name"},
    "output": {"policy_target": "$.output", "policy_target_kind": "final_output"},
    "agent_shutdown": {"policy_target": "$.summary", "policy_target_kind": "run_summary"},
}
_METADATA = re.compile(r"(?ms)^# METADATA\s*\n((?:#[^\n]*\n)+)")


class GuardrailBlocked(PermissionError):
    """An enforced deny (or an escalation the host cannot route to a person)."""

    def __init__(self, verdict: "GuardVerdict") -> None:
        self.verdict = verdict
        super().__init__(verdict.explain())


@dataclass(frozen=True)
class PolicyVersion:
    version: int
    rego: str
    data: dict[str, Any]
    author: str
    note: str
    at: int
    sha: str

    def meta(self) -> dict[str, Any]:
        return {"version": self.version, "author": self.author, "note": self.note, "at": self.at, "sha": self.sha}


@dataclass(frozen=True)
class GuardVerdict:
    point: str
    decision: str
    reason: str = ""
    message: str = ""
    mode: str = "enforce"
    version: int = 0
    transformed: Any = None
    applied: bool = False
    identity: str = ""
    ms: float = 0.0
    tool: str = ""

    @property
    def enforced(self) -> bool:
        return self.mode == "enforce"

    @property
    def denies(self) -> bool:
        return self.enforced and self.decision == "deny"

    @property
    def escalates(self) -> bool:
        return self.enforced and self.decision == "escalate"

    @property
    def transforms(self) -> bool:
        return self.enforced and self.decision == "transform" and self.applied

    @property
    def noteworthy(self) -> bool:
        return self.decision != "allow"

    def explain(self) -> str:
        text = self.message or "Blocked by the guardrail policy."
        return f"{text} (guardrail {self.reason})" if self.reason else text

    def event(self) -> dict[str, Any]:
        return {"point": self.point, "decision": self.decision, "reason": self.reason, "message": self.message,
                "mode": self.mode, "version": self.version, "tool": self.tool, "enforced": self.enforced,
                "identity": self.identity, "ms": round(self.ms, 1)}


def _sha(rego: str, data: Any) -> str:
    return hashlib.sha256((rego + "\n" + json.dumps(data, sort_keys=True)).encode("utf-8")).hexdigest()[:16]


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, allow_nan=False))


def default_policy() -> tuple[str, dict[str, Any]]:
    rego = (POLICY_DIR / "autopilot.rego").read_text(encoding="utf-8")
    data = json.loads((POLICY_DIR / "data.json").read_text(encoding="utf-8"))
    return rego, data


def default_cases() -> list[dict[str, Any]]:
    try:
        cases = json.loads((POLICY_DIR / "cases.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [case for case in cases if type(case) is dict and case.get("point") in POINTS][:60]


def parse_rules(rego: str) -> list[dict[str, Any]]:
    """The `# METADATA` annotations of each rule: what the Rules tab lists."""
    rules = []
    for block in _METADATA.finditer(rego):
        lines = [line[1:].rstrip() for line in block.group(1).splitlines()]
        rule: dict[str, Any] = {"title": "", "description": "", "id": "", "decision": "", "points": []}
        for line in lines:
            text = line.strip()
            for key in ("title", "description", "id", "decision"):
                if text.startswith(key + ":"):
                    rule[key] = text.split(":", 1)[1].strip()
            if text.startswith("points:"):
                rule["points"] = [item.strip() for item in text.split(":", 1)[1].strip(" []").split(",") if item.strip()]
        if rule["id"]:
            rules.append(rule)
    return rules


def _validate_data(data: Any) -> list[str]:
    problems = []
    if type(data) is not dict or type(data.get("autopilot")) is not dict:
        return ['Parameters must be a JSON object with an "autopilot" object.']
    if len(json.dumps(data)) > MAX_DATA_BYTES:
        problems.append("The parameters are too large.")
    patterns = ((data["autopilot"].get("redaction") or {}).get("patterns")) or []
    for pattern in patterns if type(patterns) is list else ["(not a list)"]:
        try:
            re.compile(pattern)
        except (re.error, TypeError):
            problems.append(f"Redaction pattern {str(pattern)[:60]!r} is not a valid regular expression.")
    return problems


class GuardrailEngine:
    """The versioned policy, the live ACS control built from it, and a redaction-safe decision log."""

    def __init__(self, *, mode: str | None = None, opa_path: str | None = None) -> None:
        mode = (mode or os.getenv("AUTOPILOT_GUARDRAILS", "enforce")).strip().lower()
        self.mode = mode if mode in MODES else "enforce"
        self.opa_path = opa_path or os.getenv("ACS_OPA_PATH") or shutil.which("opa") or ""
        rego, data = default_policy()
        self._versions: list[PolicyVersion] = [PolicyVersion(1, rego, data, "built-in", "Default guardrails", 0, _sha(rego, data))]
        self._catalog: dict[str, dict[str, Any]] = {}
        self._control: Any = None
        self._bundles: deque[str] = deque()
        self._error = ""
        self._decisions: deque[dict[str, Any]] = deque(maxlen=MAX_DECISIONS)
        self._revision = 0
        self._counts: Counter[str] = Counter()
        self._reasons: Counter[str] = Counter()
        self._mode_changed = {"by": "configuration", "at": 0}
        self._versions_info: dict[str, str] = {}

    # ── status ──
    @property
    def available(self) -> bool:
        return AgentControl is not None and bool(self.opa_path)

    @property
    def active(self) -> PolicyVersion:
        return self._versions[-1]

    def engine_info(self) -> dict[str, Any]:
        if not self._versions_info:
            info = {"acs": "", "opa": ""}
            try:
                info["acs"] = metadata.version("agent-control-specification")
            except metadata.PackageNotFoundError:
                pass
            if self.opa_path:
                try:
                    out = subprocess.run([self.opa_path, "version"], capture_output=True, text=True, timeout=5).stdout
                    info["opa"] = next((line.split(":", 1)[1].strip() for line in out.splitlines()
                                        if line.lower().startswith("version:")), "")
                except (OSError, subprocess.SubprocessError):
                    pass
            self._versions_info = info
        return {"available": self.available, "acsVersion": self._versions_info.get("acs", ""),
                "opaVersion": self._versions_info.get("opa", ""), "manifestVersion": MANIFEST_VERSION,
                "error": self._error, "points": list(POINTS)}

    # ── catalog and control ──
    def manifest(self, bundle: str, catalog: Mapping[str, Any] | None = None) -> dict[str, Any]:
        tools = dict(catalog if catalog is not None else self._catalog) or {"none.none": {"access": "read"}}
        return {
            "agent_control_specification_version": MANIFEST_VERSION,
            "metadata": {"name": "group-functions-autopilot", "version": str(self.active.version)},
            "policies": {"autopilot": {"type": "rego", "bundle": bundle, "query": QUERY}},
            "intervention_points": {name: {**binding, "policy": {"id": "autopilot"}} for name, binding in _BINDINGS.items()},
            "tools": tools,
        }

    def _write_bundle(self, rego: str, data: Any) -> str:
        bundle = tempfile.mkdtemp(prefix="agt-policy-")
        Path(bundle, "autopilot.rego").write_text(rego, encoding="utf-8")
        Path(bundle, "data.json").write_text(json.dumps(data), encoding="utf-8")
        return bundle

    def _compile(self, rego: str, data: Any, catalog: Mapping[str, Any]) -> tuple[Any, str]:
        if AgentControl is None:
            raise RuntimeError("The Agent Control Specification runtime is not installed on this host.")
        bundle = self._write_bundle(rego, data)
        try:
            return AgentControl.from_native(json.dumps(self.manifest(bundle, catalog))), bundle
        except Exception:
            shutil.rmtree(bundle, ignore_errors=True)
            raise

    def _activate(self, control: Any, bundle: str) -> None:
        self._control = control
        self._bundles.append(bundle)
        while len(self._bundles) > 3:  # In-flight evaluations may still read the previous bundle.
            shutil.rmtree(self._bundles.popleft(), ignore_errors=True)

    def rebuild(self) -> None:
        if not self.available:
            self._control, self._error = None, "The ACS runtime or OPA is not installed on this host."
            return
        try:
            self._activate(*self._compile(self.active.rego, self.active.data, self._catalog))
            self._error = ""
        except Exception as error:  # The previous control stays; with none, every evaluation fails closed.
            self._error = f"The active policy could not be loaded: {str(error)[:300]}"
            _logger.warning("Guardrail policy v%s could not be loaded", self.active.version)

    def set_catalog(self, catalog: Mapping[str, Mapping[str, Any]]) -> None:
        tools = {name: dict(meta) for name, meta in sorted(catalog.items())}
        if tools != self._catalog or self._control is None:
            self._catalog = tools
            self.rebuild()

    def ensure_tool(self, name: str, meta: Mapping[str, Any]) -> None:
        if name not in self._catalog:
            self.set_catalog({**self._catalog, name: dict(meta)})

    # ── evaluation ──
    async def evaluate(self, point: str, snapshot: Mapping[str, Any], *, run_id: str = "", agent: str = "",
                       tool: str = "", record: bool = True) -> GuardVerdict:
        version = self.active.version
        if self.mode == "off":
            return GuardVerdict(point, "allow", mode="off", version=version, tool=tool)
        started = time.perf_counter()
        control = self._control
        mode = self.mode
        try:
            if control is None:
                raise RuntimeError(self._error or "No guardrail policy is loaded.")
            result = await asyncio.wait_for(
                control.evaluate_intervention_point(point, _json_safe(snapshot), mode), EVALUATION_TIMEOUT)
            verdict = result.verdict
            decision = verdict.decision.value
            transformed = result.transformed_policy_target
            outcome = GuardVerdict(
                point, decision, verdict.reason or "", verdict.message or "", mode=mode, version=version,
                transformed=transformed, applied=decision == "transform" and transformed is not None,
                identity=result.enforced_identity or "", ms=(time.perf_counter() - started) * 1000, tool=tool)
        except Exception as error:
            outcome = GuardVerdict(point, "deny", "host_error:evaluation_failed",
                                   f"The guardrail engine could not decide, so nothing ran ({type(error).__name__}).",
                                   mode=mode, version=version, ms=(time.perf_counter() - started) * 1000, tool=tool)
        if record:
            self._record(outcome, run_id=run_id, agent=agent)
        return outcome

    async def evaluate_text(self, point: str, snapshot: Mapping[str, Any], key: str, text: str, *,
                            run_id: str = "", agent: str = "", tool: str = "") -> tuple[GuardVerdict, str]:
        """Evaluate a long text in windows; the most severe verdict wins and transforms apply per window."""
        chunks = _windows(text) or [""]
        worst: GuardVerdict | None = None
        parts: list[str] = []
        rank = {"allow": 0, "warn": 1, "transform": 2, "escalate": 3, "deny": 4}
        for index, chunk in enumerate(chunks):
            window = {**snapshot, key: {"text": chunk, "chunk": index + 1, "chunks": len(chunks), "chars": len(text)}}
            verdict = await self.evaluate(point, window, tool=tool, record=False)
            transformed = verdict.transformed if verdict.transforms else None
            parts.append(transformed["text"] if isinstance(transformed, Mapping) and isinstance(transformed.get("text"), str)
                         else chunk)
            if worst is None or rank.get(verdict.decision, 4) > rank.get(worst.decision, 4):
                worst = verdict
        assert worst is not None
        self._record(worst, run_id=run_id, agent=agent)
        return worst, "".join(parts)

    def _record(self, verdict: GuardVerdict, *, run_id: str, agent: str) -> None:
        self._revision += 1
        self._counts[verdict.decision] += 1
        if verdict.reason:
            self._reasons[verdict.reason] += 1
        if verdict.decision == "allow" and verdict.point not in {"pre_tool_call", "agent_startup"}:
            return  # Every allowed model call and result would drown out the decisions that matter.
        self._decisions.append({"rev": self._revision, "at": int(time.time() * 1000), "runId": run_id,
                                "agent": agent, **verdict.event()})

    def decisions(self, after: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        return [item for item in reversed(self._decisions) if item["rev"] > after][:limit]

    # ── authoring ──
    async def validate(self, rego: Any, data: Any, *, cases: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Check the draft (syntax, parameters, ACS artifacts) and run the scenario cases against it."""
        diagnostics: list[dict[str, Any]] = []
        if not isinstance(rego, str) or not rego.strip():
            diagnostics.append({"component": "rego", "message": "The policy is empty."})
        elif len(rego.encode("utf-8")) > MAX_REGO_BYTES:
            diagnostics.append({"component": "rego", "message": "The policy is too large."})
        diagnostics += [{"component": "parameters", "message": text} for text in _validate_data(data)]
        if diagnostics:
            return {"valid": False, "diagnostics": diagnostics, "tests": []}
        if not self.available:
            return {"valid": False, "tests": [], "diagnostics": [
                {"component": "engine", "message": "The ACS runtime or OPA is not installed on this host."}]}
        bundle = self._write_bundle(rego, data)
        try:
            report = await asyncio.to_thread(
                validate_acs_artifacts, manifest=json.dumps(self.manifest(bundle)), rego={"autopilot.rego": rego})
            for item in report.to_dict().get("diagnostics", []):
                diagnostics.append({key: item.get(key) for key in ("component", "code", "message", "line", "column", "snippet")})
            if diagnostics:
                return {"valid": False, "diagnostics": diagnostics, "tests": []}
            control = AgentControl.from_native(json.dumps(self.manifest(bundle, self._case_catalog(cases))))
            tests = await self._run_cases(control, cases if cases is not None else default_cases())
        finally:
            shutil.rmtree(bundle, ignore_errors=True)
        broken = [test for test in tests if str(test.get("reason") or "").startswith(("runtime_error:", "host_error:"))]
        return {"valid": not broken, "diagnostics": [
            {"component": "rego", "message": f"“{test['name']}” fails at runtime: {test['reason']}."} for test in broken],
            "tests": tests}

    def _case_catalog(self, cases: list[dict[str, Any]] | None) -> dict[str, Any]:
        catalog = dict(self._catalog)
        for case in cases if cases is not None else default_cases():
            name = case.get("tool")
            if isinstance(name, str) and name and name not in catalog:
                catalog[name] = {"access": case.get("access") or _guess_access(name), "server": name.split(".", 1)[0]}
        return catalog

    async def _run_cases(self, control: Any, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from .code_sandbox import analyse

        results = []
        for case in cases:
            snapshot = case_snapshot(case, analyse)
            try:
                result = await asyncio.wait_for(control.evaluate_intervention_point(case["point"], snapshot, "evaluate_only"),
                                                EVALUATION_TIMEOUT)
                decision, reason, message = result.verdict.decision.value, result.verdict.reason or "", result.verdict.message or ""
            except Exception as error:
                decision, reason, message = "deny", "host_error:evaluation_failed", type(error).__name__
            expect = case.get("expect")
            results.append({"name": str(case.get("name") or case["point"])[:120], "point": case["point"],
                            "tool": case.get("tool") or "", "expect": expect, "decision": decision, "reason": reason,
                            "message": message, "ok": expect in (None, decision)})
        return results

    async def publish(self, rego: Any, data: Any, *, author: str, note: str = "") -> dict[str, Any]:
        report = await self.validate(rego, data)
        if not report["valid"]:
            raise ValueError("; ".join(item["message"] for item in report["diagnostics"][:4]) or "The policy is not valid.")
        control, bundle = self._compile(rego, data, self._catalog)
        version = PolicyVersion(self.active.version + 1, rego, copy.deepcopy(data), author[:200], str(note or "")[:300],
                                int(time.time() * 1000), _sha(rego, data))
        self._versions.append(version)
        del self._versions[:-MAX_VERSIONS]
        self._activate(control, bundle)
        self._error = ""
        return {"version": version.meta(), "tests": report["tests"]}

    async def restore_version(self, number: int, *, author: str) -> dict[str, Any]:
        match = next((item for item in self._versions if item.version == number), None)
        if match is None:
            raise ValueError("That policy version is no longer kept.")
        return await self.publish(match.rego, match.data, author=author, note=f"Restored version {number}")

    async def reset_to_default(self, *, author: str) -> dict[str, Any]:
        rego, data = default_policy()
        return await self.publish(rego, data, author=author, note="Reset to the built-in guardrails")

    def set_mode(self, mode: str, *, author: str) -> None:
        if mode not in MODES:
            raise ValueError("mode must be enforce, evaluate_only or off.")
        self.mode = mode
        self._mode_changed = {"by": author[:200], "at": int(time.time() * 1000)}

    async def test(self, point: str, snapshot: Mapping[str, Any], *, rego: Any = None, data: Any = None) -> dict[str, Any]:
        """Evaluate one snapshot (evaluate_only) against the draft, or the active policy when no draft is given."""
        if point not in POINTS:
            raise ValueError("Unknown intervention point.")
        if not self.available:
            raise RuntimeError("The ACS runtime or OPA is not installed on this host.")
        draft = rego is not None or data is not None
        rego = rego if rego is not None else self.active.rego
        data = data if data is not None else self.active.data
        problems = _validate_data(data) + ([] if isinstance(rego, str) and rego.strip() else ["The policy is empty."])
        if problems:
            raise ValueError(problems[0])
        catalog = dict(self._catalog)
        call = snapshot.get("tool_call")
        name = call.get("name") if isinstance(call, Mapping) else None
        if isinstance(name, str) and name and name not in catalog:
            catalog[name] = {"access": _guess_access(name), "server": name.split(".", 1)[0]}
        control, bundle = self._compile(rego, data, catalog)
        try:
            result = await asyncio.wait_for(control.evaluate_intervention_point(point, _json_safe(snapshot), "evaluate_only"),
                                            EVALUATION_TIMEOUT)
        finally:
            shutil.rmtree(bundle, ignore_errors=True)
        verdict = result.verdict
        return {"decision": verdict.decision.value, "reason": verdict.reason or "", "message": verdict.message or "",
                "transform": asdict(verdict.transform) if verdict.transform else None,
                "policyInput": result.policy_input, "identity": result.enforced_identity or "", "draft": draft}

    # ── persistence and presentation ──
    def export(self) -> dict[str, Any]:
        return {"mode": self.mode, "modeChanged": dict(self._mode_changed),
                "versions": [asdict(version) for version in self._versions]}

    def restore(self, state: Any) -> None:
        if type(state) is not dict:
            return
        versions = []
        for item in state.get("versions") or []:
            if (type(item) is dict and type(item.get("version")) is int and isinstance(item.get("rego"), str)
                    and type(item.get("data")) is dict and not _validate_data(item["data"])):
                versions.append(PolicyVersion(item["version"], item["rego"], item["data"], str(item.get("author") or "")[:200],
                                              str(item.get("note") or "")[:300], int(item.get("at") or 0),
                                              _sha(item["rego"], item["data"])))
        if versions:
            self._versions = sorted(versions, key=lambda version: version.version)[-MAX_VERSIONS:]
        if state.get("mode") in MODES and not os.getenv("AUTOPILOT_GUARDRAILS"):
            self.mode = state["mode"]
            if type(state.get("modeChanged")) is dict:
                self._mode_changed = {"by": str(state["modeChanged"].get("by") or "")[:200],
                                      "at": int(state["modeChanged"].get("at") or 0)}
        self.rebuild()

    def describe(self) -> dict[str, Any]:
        active = self.active
        return {
            "mode": self.mode, "modeChanged": dict(self._mode_changed), "engine": self.engine_info(),
            "active": {**active.meta(), "rego": active.rego, "data": active.data},
            "rules": parse_rules(active.rego), "versions": [version.meta() for version in reversed(self._versions)],
            "counts": dict(self._counts), "reasons": dict(self._reasons.most_common(40)),
            "revision": self._revision, "catalog": {"tools": len(self._catalog)},
            "bindings": {name: dict(binding) for name, binding in _BINDINGS.items()},
            "cases": default_cases(),
        }

    def version_source(self, number: int) -> dict[str, Any]:
        match = next((item for item in self._versions if item.version == number), None)
        if match is None:
            raise ValueError("That policy version is no longer kept.")
        return {**match.meta(), "rego": match.rego, "data": match.data}


def _windows(text: str) -> list[str]:
    chunks, start = [], 0
    while start < len(text):
        end = min(len(text), start + TEXT_CHUNK)
        if end < len(text):
            cut = text.rfind("\n", start + TEXT_CHUNK // 2, end)
            end = cut + 1 if cut > start else end
        chunks.append(text[start:end])
        start = end
    return chunks


def _guess_access(name: str) -> str:
    server, _, tool = name.partition(".")
    if server == "code":
        return "code"
    if server in {"workspace", "skill", "agent"}:
        return "local"
    if server == "human":
        return "human"
    return "read" if re.match(r"^(?:get|list|search|find|lookup|read|check)(?:_|$)", tool) else "write"


def case_snapshot(case: Mapping[str, Any], analyse: Any) -> dict[str, Any]:
    """The snapshot a scenario case stands for, shaped exactly like the host's."""
    point = case["point"]
    snapshot: dict[str, Any] = {
        "agent": {"id": "test", "name": "Policy test", "role": case.get("role") or "orchestrator", "subagent": ""},
        "run": {"id": "test", "source": "policy-test", "skill": case.get("skill") or "", "dryRun": False},
        "requester": {"id": "test", "name": "Policy test"},
        "usage": {"turns": 1, "tool_calls": 0, "writes": 0, "total_tokens": 0, **(case.get("usage") or {})},
    }
    if point in {"pre_tool_call", "post_tool_call"}:
        args = copy.deepcopy(case.get("args") or {})
        snapshot["tool_call"] = {"name": case.get("tool") or "none.none", "args": args, "id": "case"}
        if snapshot["tool_call"]["name"] == "code.run_python" and isinstance(args.get("code"), str):
            snapshot["code"] = analyse(args["code"])
        if point == "post_tool_call":
            text = str(case.get("text") or "")
            snapshot["tool_result"] = {"text": text, "chunk": 1, "chunks": 1, "chars": len(text)}
    elif point in {"input", "output"}:
        snapshot[point] = {"text": str(case.get("text") or "")}
    elif point == "pre_model_call":
        snapshot["model_request"] = {"model": case.get("model") or "gpt-5.4", "role": "orchestrator",
                                     "turn": case.get("turn") or 1, "messages": 2, "tools": 10, "estimated_tokens": 1000}
    elif point == "post_model_call":
        snapshot["model_response"] = {"model": case.get("model") or "gpt-5.4", "finish_reason": "stop",
                                      "tool_calls": [], "content_chars": 10}
    elif point == "agent_startup":
        snapshot["agent"].update({"skill": case.get("skill") or "", "tools": 10})
    else:
        snapshot["summary"] = {"turns": 1, "tool_calls": 0}
    return snapshot
