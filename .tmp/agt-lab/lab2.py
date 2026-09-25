"""AGT/ACS lab round 2: transform paths, snapshot size limits, multi-finding Rego pattern."""
import asyncio
import json
import tempfile
import time
from pathlib import Path

from agent_control_specification import AgentControl

REGO = r"""package autopilot.guardrails

import rego.v1

severity := {"deny": 5, "escalate": 4, "transform": 3, "warn": 2}

findings contains {"decision": "deny", "reason": "tools.blocked", "message": sprintf("%s is blocked", [input.tool.name])} if {
    input.intervention_point == "pre_tool_call"
    some pattern in data.autopilot.tools.blocked
    glob.match(pattern, [], input.tool.name)
}

findings contains {"decision": "warn", "reason": "tools.watch", "message": "watched"} if {
    input.intervention_point == "pre_tool_call"
    some pattern in data.autopilot.tools.watch
    glob.match(pattern, [], input.tool.name)
}

findings contains {"decision": "transform", "reason": "results.redact", "message": "redacted",
                   "transform": {"path": data.autopilot.path, "value": redacted}} if {
    input.intervention_point == "post_tool_call"
    is_string(input.policy_target.value)
    redacted := regex.replace(input.policy_target.value, concat("|", data.autopilot.redact), "[REDACTED]")
    redacted != input.policy_target.value
}

top := max({severity[f.decision] | some f in findings})

default verdict := {"decision": "allow"}

verdict := [f | some f in findings; severity[f.decision] == top][0]
"""


def manifest(bundle: str) -> str:
    return json.dumps({
        "agent_control_specification_version": "0.3.1-beta",
        "metadata": {"name": "lab2"},
        "policies": {"guard": {"type": "rego", "bundle": bundle, "query": "data.autopilot.guardrails.verdict"}},
        "intervention_points": {
            "pre_tool_call": {"policy_target": "$.tool_call.args", "policy_target_kind": "tool_args",
                              "tool_name_from": "$.tool_call.name", "policy": {"id": "guard"}},
            "post_tool_call": {"policy_target": "$.tool_result", "policy_target_kind": "tool_result",
                               "tool_name_from": "$.tool_call.name", "policy": {"id": "guard"}},
        },
        "tools": {"servicenow.delete_record": {"access": "write"}, "servicenow.list_incidents": {"access": "read"},
                  "workday.get_worker": {"access": "read"}},
    })


async def build(path: str) -> AgentControl:
    bundle = Path(tempfile.mkdtemp(prefix="agt2-"))
    (bundle / "guardrails.rego").write_text(REGO)
    (bundle / "data.json").write_text(json.dumps({"autopilot": {
        "tools": {"blocked": ["*.delete_*"], "watch": ["servicenow.*"]},
        "redact": [r"sk-[A-Za-z0-9]{6,}", r"\b\d{3}-\d{2}-\d{4}\b"], "path": path}}))
    return AgentControl.from_native(manifest(str(bundle)))


async def main():
    control = await build("$target")
    for name in ("servicenow.delete_record", "servicenow.list_incidents", "workday.get_worker"):
        r = await control.evaluate_intervention_point("pre_tool_call", {"tool_call": {"name": name, "args": {"x": 1}}})
        print("pre", name, r.verdict.decision.value, r.verdict.reason, r.verdict.message)
    for path in ("$target", "$policy_target", "$target.value"):
        c = await build(path)
        r = await c.evaluate_intervention_point("post_tool_call", {
            "tool_call": {"name": "workday.get_worker", "args": {}}, "tool_result": "ssn 123-45-6789 and key sk-abcdef99 end"})
        print("post path", path, r.verdict.decision.value, r.verdict.reason, repr(r.transformed_policy_target)[:120])
    for size in (10_000, 100_000, 500_000, 1_000_000, 3_000_000, 8_000_000):
        text = ("x" * (size - 20)) + " sk-abcdef99"
        started = time.perf_counter()
        r = await control.evaluate_intervention_point("post_tool_call", {
            "tool_call": {"name": "workday.get_worker", "args": {}}, "tool_result": text})
        ms = (time.perf_counter() - started) * 1000
        applied = isinstance(r.transformed_policy_target, str) and r.transformed_policy_target.endswith("[REDACTED]")
        print(f"size {size:>9}: {r.verdict.decision.value} {r.verdict.reason} applied={applied} {ms:.0f}ms")
    r = await control.evaluate_intervention_point("pre_tool_call", {"tool_call": {"name": "servicenow.delete_record", "args": {}}}, "evaluate_only")
    print("evaluate_only:", r.verdict.decision.value, r.verdict.reason)
    r = await control.evaluate_intervention_point("pre_tool_call", {"tool_call": {"name": "workday.get_worker", "args": {"n": 1.5, "z": None, "l": [1, {"a": True}]}}})
    print("floats/nulls:", r.verdict.decision.value)


asyncio.run(main())
