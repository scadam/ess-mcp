"""AGT/ACS lab round 3: exact snapshot size limit with a valid transform path."""
import asyncio
import json
import tempfile
import time
from pathlib import Path

from agent_control_specification import AgentControl

REGO = r"""package autopilot.guardrails

import rego.v1

default verdict := {"decision": "allow"}

verdict := {"decision": "transform", "reason": "results.redact", "message": "redacted",
            "transform": {"path": "$policy_target", "value": redacted}} if {
    input.intervention_point == "post_tool_call"
    redacted := regex.replace(input.policy_target.value, `sk-[A-Za-z0-9]{6,}`, "[REDACTED]")
    redacted != input.policy_target.value
}
"""


async def main():
    bundle = Path(tempfile.mkdtemp(prefix="agt3-"))
    (bundle / "guardrails.rego").write_text(REGO)
    control = AgentControl.from_native(json.dumps({
        "agent_control_specification_version": "0.3.1-beta",
        "policies": {"guard": {"type": "rego", "bundle": str(bundle), "query": "data.autopilot.guardrails.verdict"}},
        "intervention_points": {"post_tool_call": {"policy_target": "$.tool_result", "tool_name_from": "$.tool_call.name",
                                                   "policy": {"id": "guard"}}},
        "tools": {"t": {}},
    }))
    for size in (50_000, 100_000, 150_000, 200_000, 250_000, 300_000, 400_000, 480_000):
        text = ("x" * (size - 12)) + " sk-abcdef99"
        started = time.perf_counter()
        r = await control.evaluate_intervention_point("post_tool_call", {"tool_call": {"name": "t", "args": {}}, "tool_result": text})
        ms = (time.perf_counter() - started) * 1000
        applied = isinstance(r.transformed_policy_target, str) and r.transformed_policy_target.endswith("[REDACTED]")
        print(f"size {size:>7}: {r.verdict.decision.value:9} {r.verdict.reason} applied={applied} {ms:.0f}ms")


asyncio.run(main())
