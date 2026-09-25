"""AGT/ACS lab: discover the 0.3.1b1 contract (manifest version, invocation shape, verdicts, latency)."""
import asyncio
import json
import os
import tempfile
import time
from pathlib import Path

from agent_control_specification import (
    AgentControl, AgentControlBlocked, ApprovalOutcome, ApprovalResolution, Decision, validate_manifest,
    validate_acs_artifacts,
)

REGO = """package autopilot.guardrails

import rego.v1

default verdict := {"decision": "allow"}

verdict := {"decision": "deny", "reason": "destructive", "message": "Deletes are blocked."} if {
    input.intervention_point == "pre_tool_call"
    endswith(input.tool.name, "delete_record")
}

verdict := {"decision": "escalate", "reason": "big_money", "message": "Needs a person."} if {
    input.intervention_point == "pre_tool_call"
    input.policy_target.value.amount > data.autopilot.limits.max_amount
}

verdict := {"decision": "warn", "reason": "noisy", "message": "Careful."} if {
    input.intervention_point == "pre_tool_call"
    input.tool.name == "servicenow.list_incidents"
}

verdict := {"decision": "transform", "reason": "redacted", "message": "Secret removed.",
            "transform": {"path": "$target.body", "value": regex.replace(input.policy_target.value.body, `sk-[A-Za-z0-9]+`, "[REDACTED]")}} if {
    input.intervention_point == "pre_tool_call"
    regex.match(`sk-[A-Za-z0-9]+`, input.policy_target.value.body)
}
"""


def manifest(version: str, policy: dict) -> str:
    return json.dumps({
        "agent_control_specification_version": version,
        "metadata": {"name": "lab"},
        "policies": {"guard": policy},
        "intervention_points": {
            "pre_tool_call": {"policy_target": "$.tool_call.args", "policy_target_kind": "tool_args",
                              "tool_name_from": "$.tool_call.name", "policy": {"id": "guard"}},
            "output": {"policy_target": "$.output", "policy_target_kind": "final_output", "policy": {"id": "guard"}},
        },
        "tools": {"servicenow.delete_record": {"clearance": "internal"}, "coupa.create_po": {},
                  "servicenow.list_incidents": {}, "mail.send": {}},
    })


class Recorder:
    def __init__(self):
        self.invocations = []

    def evaluate(self, invocation):
        self.invocations.append(invocation)
        return {"decision": "allow"}


async def main():
    for version in ("0.3.1-beta", "0.3.1-beta-agt", "0.3.0-alpha", "0.4.0-alpha.1"):
        try:
            validate_manifest(manifest(version, {"type": "custom", "adapter": "lab"}))
            print("version ok:", version)
        except Exception as exc:  # noqa: BLE001
            print("version rejected:", version, type(exc).__name__, str(exc)[:160])

    recorder = Recorder()
    control = AgentControl.from_native(manifest("0.3.1-beta", {"type": "custom", "adapter": "lab"}), policy_dispatcher=recorder)
    result = await control.evaluate_intervention_point("pre_tool_call", {
        "tool_call": {"name": "coupa.create_po", "args": {"amount": 12.5, "note": None}, "id": "c1"},
        "agent": {"id": "a1"}, "run": {"id": "r1"}})
    print("custom verdict:", result.verdict, "identity:", result.enforced_identity)
    print("custom invocation keys:", sorted(recorder.invocations[0].keys()))
    print("custom invocation (trimmed):", json.dumps(recorder.invocations[0], default=str)[:900])
    try:
        bad = await control.evaluate_intervention_point("pre_tool_call", {"tool_call": {"name": "unknown.tool", "args": {}}})
        print("unknown tool verdict:", bad.verdict)
    except Exception as exc:  # noqa: BLE001
        print("unknown tool raised", type(exc).__name__, exc)

    bundle = Path(tempfile.mkdtemp(prefix="agt-bundle-"))
    (bundle / "guardrails.rego").write_text(REGO)
    (bundle / "data.json").write_text(json.dumps({"autopilot": {"limits": {"max_amount": 10000}}}))
    rego_manifest = manifest("0.3.1-beta", {"type": "rego", "bundle": str(bundle), "query": "data.autopilot.guardrails.verdict"})
    report = validate_acs_artifacts(manifest=rego_manifest, rego={"guardrails.rego": REGO})
    print("validate_acs_artifacts:", json.dumps(report.to_dict(), default=str)[:600])
    rego = AgentControl.from_native(rego_manifest)
    cases = [
        ("coupa.create_po", {"amount": 50, "body": "ok"}),
        ("coupa.create_po", {"amount": 50000, "body": "ok"}),
        ("servicenow.delete_record", {"sys_id": "x"}),
        ("servicenow.list_incidents", {"limit": 5}),
        ("mail.send", {"body": "key sk-abc123 here", "to": "x"}),
    ]
    for name, args in cases:
        started = time.perf_counter()
        result = await rego.evaluate_intervention_point("pre_tool_call", {"tool_call": {"name": name, "args": args}})
        elapsed = (time.perf_counter() - started) * 1000
        print(f"rego {name}: {result.verdict.decision.value} reason={result.verdict.reason} "
              f"target={result.transformed_policy_target} {elapsed:.1f}ms")
    started = time.perf_counter()
    for _ in range(20):
        await rego.evaluate_intervention_point("pre_tool_call", {"tool_call": {"name": "coupa.create_po", "args": {"amount": 1}}})
    print(f"rego avg latency: {(time.perf_counter() - started) * 1000 / 20:.1f}ms")
    started = time.perf_counter()
    for _ in range(200):
        await control.evaluate_intervention_point("pre_tool_call", {"tool_call": {"name": "coupa.create_po", "args": {"amount": 1}}})
    print(f"custom avg latency: {(time.perf_counter() - started) * 1000 / 200:.2f}ms")

    out = await rego.evaluate_intervention_point("output", {"output": "hello"})
    print("output verdict:", out.verdict)

    result = await rego.evaluate_intervention_point("pre_tool_call", {"tool_call": {"name": "coupa.create_po", "args": {"amount": 50000}}})
    try:
        await rego.enforce(result.verdict.decision and __import__("agent_control_specification").InterventionPoint.PRE_TOOL_CALL,
                           result, __import__("agent_control_specification").EnforcementMode.ENFORCE,
                           approval_resolver=lambda point, res: ApprovalResolution.allow(res.enforced_identity))
        print("escalate approved -> proceed")
    except AgentControlBlocked as exc:
        print("escalate blocked", exc)
    try:
        await rego.enforce(__import__("agent_control_specification").InterventionPoint.PRE_TOOL_CALL, result,
                           __import__("agent_control_specification").EnforcementMode.ENFORCE)
    except AgentControlBlocked as exc:
        print("escalate without resolver blocked:", exc)

    broken = Path(tempfile.mkdtemp(prefix="agt-broken-"))
    (broken / "x.rego").write_text("package autopilot.guardrails\nverdict := {")
    bm = manifest("0.3.1-beta", {"type": "rego", "bundle": str(broken), "query": "data.autopilot.guardrails.verdict"})
    try:
        b = AgentControl.from_native(bm)
        r = await b.evaluate_intervention_point("pre_tool_call", {"tool_call": {"name": "coupa.create_po", "args": {}}})
        print("broken rego verdict:", r.verdict)
    except Exception as exc:  # noqa: BLE001
        print("broken rego raised", type(exc).__name__, str(exc)[:200])
    report = validate_acs_artifacts(manifest=bm, rego={"x.rego": "package autopilot.guardrails\nverdict := {"})
    print("broken validate:", json.dumps(report.to_dict(), default=str)[:500])


asyncio.run(main())
