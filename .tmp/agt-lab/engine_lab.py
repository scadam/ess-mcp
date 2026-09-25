import asyncio
import json
import sys
import time

sys.path.insert(0, "/repo")

from demo_agent.guardrails import GuardrailEngine, case_snapshot, default_policy, parse_rules
from demo_agent.code_sandbox import analyse


async def main():
    engine = GuardrailEngine(mode="enforce")
    print("available", engine.available, engine.engine_info())
    engine.set_catalog({"servicenow.list_incidents": {"access": "read", "server": "servicenow"},
                        "servicenow.create_incident": {"access": "write", "server": "servicenow"},
                        "code.run_python": {"access": "code", "server": "code"}})
    print("error:", engine._error or "none")
    rego, data = default_policy()
    print("rules:", [rule["id"] for rule in parse_rules(rego)])
    started = time.perf_counter()
    report = await engine.validate(rego, data)
    print(f"validate valid={report['valid']} in {(time.perf_counter() - started):.1f}s")
    for item in report["diagnostics"]:
        print("  diag", item)
    for test in report["tests"]:
        print(f"  {'OK ' if test['ok'] else 'BAD'} {test['name']}: expect={test['expect']} got={test['decision']} {test['reason']} | {test['message'][:90]}")
    verdict = await engine.evaluate("pre_tool_call", case_snapshot({"point": "pre_tool_call", "tool": "code.run_python",
        "args": {"code": "import json\nprint(1)", "purpose": "x", "timeout_seconds": 100}}, analyse), run_id="r1")
    print("code transform:", verdict.decision, verdict.reason, verdict.transformed)
    text = ("line\n" * 30000) + "password: Hunter2Secret!\n" + ("more\n" * 20000)
    snap = case_snapshot({"point": "post_tool_call", "tool": "servicenow.list_incidents", "args": {}}, analyse)
    started = time.perf_counter()
    verdict, redacted = await engine.evaluate_text("post_tool_call", snap, "tool_result", text, run_id="r1", tool="servicenow.list_incidents")
    print(f"long text: {verdict.decision} {verdict.reason} chars {len(text)}->{len(redacted)} redacted={'[REDACTED]' in redacted} {(time.perf_counter() - started) * 1000:.0f}ms")
    bad = rego.replace("default verdict := {\"decision\": \"allow\"}", "default verdict := {\"decision\": \"allow\"}\nverdict := {\"decision\": \"allow\"}")
    report = await engine.validate(bad, data)
    print("conflicting rego valid:", report["valid"], [d["message"][:120] for d in report["diagnostics"]][:2])
    report = await engine.validate(rego.replace("package guardrails", "package guardrails\nbroken := {"), data)
    print("syntax error valid:", report["valid"], [(d.get("line"), d.get("message")) for d in report["diagnostics"]][:2])
    try:
        await engine.publish(bad, data, author="lab")
    except ValueError as error:
        print("publish refused:", str(error)[:160])
    published = await engine.publish(rego, {**data, "autopilot": {**data["autopilot"], "paused": True}}, author="lab", note="pause")
    print("published", published["version"])
    verdict = await engine.evaluate("agent_startup", case_snapshot({"point": "agent_startup"}, analyse))
    print("paused startup:", verdict.decision, verdict.reason, verdict.message)
    result = await engine.test("pre_tool_call", case_snapshot({"point": "pre_tool_call", "tool": "coupa.approve_reject",
                                                               "args": {"action": "approve"}}, analyse))
    print("test bench:", result["decision"], result["reason"], result["draft"])
    exported = engine.export()
    other = GuardrailEngine(mode="enforce")
    other.set_catalog(engine._catalog)
    other.restore(json.loads(json.dumps(exported)))
    print("restored version", other.active.version, "mode", other.mode, "error", other._error or "none")
    print("decisions:", [(d["point"], d["decision"], d["reason"]) for d in engine.decisions()][:6])
    started = time.perf_counter()
    for _ in range(10):
        await engine.evaluate("pre_tool_call", case_snapshot({"point": "pre_tool_call", "tool": "servicenow.list_incidents", "args": {}}, analyse))
    print(f"avg pre_tool_call {(time.perf_counter() - started) * 100:.0f}ms")


asyncio.run(main())
