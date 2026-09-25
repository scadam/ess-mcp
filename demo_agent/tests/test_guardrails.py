"""Guardrail engine contracts. The ACS-backed class runs only where the Linux ACS wheel and OPA are installed."""

from __future__ import annotations

import asyncio
import copy
import sys
import unittest
from types import SimpleNamespace
from typing import Any

from demo_agent import guardrails
from demo_agent.code_sandbox import analyse
from demo_agent.guardrails import GuardrailEngine, case_snapshot, default_cases, default_policy, parse_rules


class FakeControl:
    def __init__(self, decision: str, *, reason: str = "rule:test", transformed: Any = None) -> None:
        self.decision, self.reason, self.transformed = decision, reason, transformed
        self.calls: list[tuple[str, dict[str, Any], str]] = []

    async def evaluate_intervention_point(self, point: str, snapshot: dict[str, Any], mode: str) -> Any:
        self.calls.append((point, snapshot, mode))
        verdict = SimpleNamespace(decision=SimpleNamespace(value=self.decision), reason=self.reason, message="because")
        return SimpleNamespace(verdict=verdict, transformed_policy_target=self.transformed, enforced_identity="")


def engine_with(control: Any, mode: str = "enforce") -> GuardrailEngine:
    engine = GuardrailEngine(mode=mode, opa_path="")
    engine._control = control
    return engine


class PolicyBundleTests(unittest.TestCase):
    def test_every_rule_has_metadata(self) -> None:
        rego, data = default_policy()
        rules = parse_rules(rego)
        self.assertGreaterEqual(len(rules), 15)
        for rule in rules:
            self.assertTrue(rule["id"] and rule["title"] and rule["decision"], rule)
        self.assertIn("autopilot", data)

    def test_case_snapshots_carry_code_facts(self) -> None:
        case = next(item for item in default_cases() if item.get("tool") == "code.run_python")
        snapshot = case_snapshot(case, analyse)
        self.assertEqual(snapshot["tool_call"]["name"], "code.run_python")
        self.assertIn("json", snapshot["code"]["imports"])

    def test_long_text_is_windowed_without_loss(self) -> None:
        text = "x" * (guardrails.TEXT_CHUNK * 2 + 5)
        self.assertEqual("".join(guardrails._windows(text)), text)
        self.assertEqual(len(guardrails._windows(text)), 3)


class EngineModeTests(unittest.TestCase):
    def test_off_never_evaluates(self) -> None:
        control = FakeControl("deny")
        verdict = asyncio.run(engine_with(control, "off").evaluate("pre_tool_call", {}))
        self.assertEqual(verdict.decision, "allow")
        self.assertEqual(control.calls, [])

    def test_shadow_mode_records_but_does_not_enforce(self) -> None:
        engine = engine_with(FakeControl("deny"), "evaluate_only")
        verdict = asyncio.run(engine.evaluate("pre_tool_call", {}, tool="servicenow.delete_cart"))
        self.assertEqual(verdict.decision, "deny")
        self.assertFalse(verdict.enforced)
        self.assertFalse(verdict.denies)
        self.assertEqual(engine.decisions()[-1]["decision"], "deny")

    def test_enforce_denies(self) -> None:
        verdict = asyncio.run(engine_with(FakeControl("deny")).evaluate("pre_tool_call", {}))
        self.assertTrue(verdict.denies)

    def test_no_control_fails_closed(self) -> None:
        verdict = asyncio.run(engine_with(None).evaluate("pre_tool_call", {}))
        self.assertTrue(verdict.denies)
        self.assertEqual(verdict.reason, "host_error:evaluation_failed")

    def test_text_transform_applies_per_window(self) -> None:
        engine = engine_with(FakeControl("transform", transformed={"text": "[REDACTED]"}))
        verdict, text = asyncio.run(engine.evaluate_text("output", {}, "output", "secret"))
        self.assertTrue(verdict.transforms)
        self.assertEqual(text, "[REDACTED]")

    def test_export_restore_round_trip(self) -> None:
        engine = engine_with(None)
        rego, data = default_policy()
        changed = copy.deepcopy(data)
        changed["autopilot"]["limits"]["max_amount"] = 1000
        engine._versions.append(guardrails.PolicyVersion(2, rego, changed, "op", "lower", 1, guardrails._sha(rego, changed)))
        engine.mode = "evaluate_only"
        restored = GuardrailEngine(mode="enforce", opa_path="")
        restored.restore(engine.export())
        self.assertEqual(restored.active.version, 2)
        self.assertEqual(restored.active.data["autopilot"]["limits"]["max_amount"], 1000)

    def test_restore_rejects_malformed_versions(self) -> None:
        engine = GuardrailEngine(mode="enforce", opa_path="")
        engine.restore({"versions": [{"version": "2", "rego": 1, "data": []}]})
        self.assertEqual(engine.active.version, 1)


@unittest.skipUnless(sys.platform == "linux" and guardrails.AgentControl is not None
                     and GuardrailEngine().available, "ACS runtime and OPA are Linux-only")
class RealPolicyTests(unittest.TestCase):
    def test_default_policy_passes_its_scenarios(self) -> None:
        engine = GuardrailEngine(mode="enforce")
        rego, data = default_policy()
        report = asyncio.run(engine.validate(rego, data))
        self.assertTrue(report["valid"], report)
        self.assertTrue(all(item["ok"] for item in report["tests"]), report["tests"])

    def test_broken_policy_is_refused(self) -> None:
        engine = GuardrailEngine(mode="enforce")
        _, data = default_policy()
        with self.assertRaises(ValueError):
            asyncio.run(engine.publish("package guardrails\nverdict := {", data, author="test"))
        self.assertEqual(engine.active.version, 1)


if __name__ == "__main__":
    unittest.main()
