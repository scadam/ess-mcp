"""Analytics contracts: credit pricing, the derived infrastructure cost, durable facts and the operator's report."""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import httpx

from demo_agent import analytics
from demo_agent.analytics import (
    DAY, AnalyticsLedger, AzureCostSource, asset_fact, build_report, case_fact, clean_settings, model_key, price_call,
    summarise_costs,
)
from demo_agent.conversation_memory import ChatScope, SQLiteStore

TENANT = "17371818-07cb-47f2-9ca3-18f96f0125d7"
NOW = 1_790_550_000.0  # 2026-09-27 (UTC)
CASE = "c" * 40


def costs_payload(rows: list[list[Any]]) -> dict[str, Any]:
    return {"properties": {"columns": [{"name": "Cost"}, {"name": "UsageDate"}, {"name": "ServiceName"},
                                       {"name": "Currency"}], "rows": rows}}


class PricingTests(unittest.TestCase):
    def test_tokens_are_priced_at_githubs_rates_per_model_and_tier(self) -> None:
        credits, known = price_call("gpt-5.4", 100_000, 2_000, cached_tokens=40_000)
        # (60k x $2.50 + 40k x $0.25 + 2k x $15.00) / 1M = $0.19 = 19 AI credits.
        self.assertTrue(known)
        self.assertAlmostEqual(credits, 19.0)
        long_context, _ = price_call("gpt-5.4", 300_000, 1_000)
        self.assertAlmostEqual(long_context, (300_000 * 5.00 + 1_000 * 22.50) / 1e6 / 0.01)
        mini, _ = price_call("GPT-5.4-mini", 10_000, 1_000)
        self.assertAlmostEqual(mini, (10_000 * 0.75 + 1_000 * 4.50) / 1e6 / 0.01)
        self.assertEqual(model_key("gpt-5.4-mini-2026-03-17"), "gpt-5.4-mini")

    def test_the_sdks_own_figure_wins_and_unknown_models_are_flagged(self) -> None:
        self.assertEqual(price_call("gpt-5.4", 1_000_000, 1_000_000, nano_aiu=3e9), (3.0, True))
        credits, known = price_call("gpt-4.1", 1_000, 0)
        self.assertFalse(known)
        self.assertAlmostEqual(credits, 1_000 * 2.50 / 1e6 / 0.01)  # Priced as the fallback model, and flagged.

    def test_settings_are_bounded_and_unknown_keys_refused(self) -> None:
        values = clean_settings({"baselineCostPerCase": 32, "baselineByFunction": {"hr": 45}, "dailyInfraUsd": None})
        self.assertEqual((values["baselineCostPerCase"], values["baselineByFunction"], values["dailyInfraUsd"]),
                         (32.0, {"hr": 45.0}, None))
        for bad in ({"baselineCostPerCase": -1}, {"workIqCreditsPerCall": "1"}, {"secret": 1},
                    {"baselineByFunction": {"finance": 10}}, {"peopleHourlyUsd": True}, {"approvalMinutes": float("nan")}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                clean_settings(bad)


class InfrastructureCostTests(unittest.IsolatedAsyncioTestCase):
    def test_fixed_services_are_averaged_and_model_tokens_kept_apart(self) -> None:
        rows = []
        for day in range(20, 28):
            rows += [[1.0, 20260900 + day, "Azure Container Apps", "USD"], [0.1, 20260900 + day, "Log Analytics", "USD"],
                     [0.5 if day % 2 else 0.3, 20260900 + day, "Foundry Models", "USD"]]
        summary = summarise_costs(costs_payload(rows), days=7, until="2026-09-26")
        self.assertEqual((summary["days"], summary["from"], summary["to"]), (7, "2026-09-20", "2026-09-26"))
        self.assertAlmostEqual(summary["fixedPerDay"], 1.1)
        self.assertAlmostEqual(summary["modelPerDay"], round((0.3 * 4 + 0.5 * 3) / 7, 4))
        self.assertEqual([item["fixed"] for item in summary["services"] if item["name"] == "Foundry Models"], [False])
        with self.assertRaises(ValueError):
            summarise_costs(costs_payload([]), days=7, until="2026-09-26")

    async def test_the_daily_cost_is_read_once_with_the_host_identity_and_cached(self) -> None:
        seen: list[httpx.Request] = []
        rows = [[2.0, 20260926, "Azure Container Apps", "USD"]]

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json=costs_payload(rows))

        original = httpx.AsyncClient
        scope = "/subscriptions/54b04cf7-73f7-4ea0-aa82-b15694ea8033/resourceGroups/essmcp-caldova-rg"
        source = AzureCostSource(scope, token=lambda: "mi-token", clock=lambda: NOW)
        with patch.object(analytics.httpx, "AsyncClient",
                          lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)):
            first = await source.daily()
            second = await source.daily()
        self.assertEqual((first["fixedPerDay"], first["source"]), (2.0, "azure"))
        self.assertIs(first, second)
        self.assertEqual(len(seen), 1)
        request = seen[0]
        self.assertEqual(request.headers["Authorization"], "Bearer mi-token")
        self.assertTrue(str(request.url).startswith(f"https://management.azure.com{scope}/providers/Microsoft.CostManagement/query"))
        body = json.loads(request.content)
        self.assertEqual((body["type"], body["dataset"]["granularity"]), ("ActualCost", "Daily"))
        self.assertEqual(body["timePeriod"]["to"], "2026-09-26T23:59:59Z")  # Complete days only.

    async def test_a_failed_read_is_reported_and_an_unconfigured_scope_says_so(self) -> None:
        original = httpx.AsyncClient
        source = AzureCostSource("/subscriptions/54b04cf7-73f7-4ea0-aa82-b15694ea8033", token=lambda: "t", clock=lambda: NOW)
        with patch.object(analytics.httpx, "AsyncClient", lambda **kwargs: original(
                transport=httpx.MockTransport(lambda request: httpx.Response(403)), **kwargs)):
            failed = await source.daily()
        self.assertIn("could not be read", failed["error"])
        self.assertEqual((await AzureCostSource("").daily())["source"], "unconfigured")


def run(run_id: str, *, end: float, case: str = "", source: str = "case-desk", models: dict[str, Any] | None = None,
        workiq: int = 0, status: str = "complete", colleague: str = "HR Agent") -> dict[str, Any]:
    tool_data = {f"w{index}": {"server": "workiq", "tool": "fetch"} for index in range(workiq)}
    tool_data["s1"] = {"server": "workday", "tool": "get_worker"}
    return {"id": run_id, "source": source, "status": status, "startedAt": (end - 30) * 1000, "completedAt": end * 1000,
            "actor": {"caseKey": case, "agenticAppName": colleague}, "agenticUser": {"name": colleague},
            "instanceKey": "hr", "toolData": tool_data, "serverCallCounts": {"workiq": workiq, "workday": 1},
            "stats": {"prompt_tokens": 1000, "completion_tokens": 100, "cached_tokens": 0,
                      "models": models or {"gpt-5.4": {"calls": 1, "prompt_tokens": 1000, "completion_tokens": 100,
                                                       "cached_tokens": 0, "credits": 40.0}}},
            "guardrails": [{"decision": "deny"}]}


def case(status: str, *, created: float, waiting: str = "", timeline: list[dict[str, Any]] | None = None,
         source: str = "document", key: str = CASE, title: str = "Word comment on Hybrid working guidelines") -> dict[str, Any]:
    return {"key": key, "function": "hr", "status": status, "title": title, "createdAt": created, "updatedAt": created,
            "closedAt": None, "origin": {"source": source, "channel": {"kind": source}},
            "colleague": {"name": "HR Agent"}, "record": {}, "waiting": {"for": waiting} if waiting else None,
            "timeline": timeline or [], "turns": 2, "tokens": 2200, "runs": []}


class LedgerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.store = SQLiteStore(self.root / "state.sqlite3")
        self.clock = [NOW - 3 * DAY]
        self.ledger = AnalyticsLedger(self.store, TENANT, clock=lambda: self.clock[0], flush_delay=0)

    async def asyncTearDown(self) -> None:
        await self.ledger.close()
        await self.store.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def at(self, when: float) -> None:
        self.clock[0] = when

    def work_a_case(self) -> None:
        created = NOW - 3 * DAY
        self.at(created)
        self.ledger.note_case(case("new", created=created))
        self.at(created + 60)
        self.ledger.note_case(case("waiting", created=created, waiting="approval"))
        self.ledger.note_run(run("run-1", end=created + 90, case=CASE, workiq=2), function="hr", channel="document")
        self.at(created + 600)
        self.ledger.note_case(case("resolved", created=created, timeline=[{"kind": "document.edited", "at": created + 590}]))
        self.ledger.note_run(run("run-2", end=created + 600, case=CASE), function="hr", channel="document")
        self.at(created + DAY)
        self.ledger.note_case(case("closed", created=created))
        self.ledger.note_approval({"id": "req-1", "at": (created + 60) * 1000, "status": "completed",
                                   "decidedAt": (created + 360) * 1000, "label": "Update a worker"},
                                  run={"id": "run-1", "actor": {"caseKey": CASE}}, function="hr")

    async def test_a_case_costs_its_interactions_its_share_of_the_platform_and_the_people_in_the_loop(self) -> None:
        self.ledger.since = NOW - 10 * DAY
        self.work_a_case()
        self.ledger.note_run(run("chat-1", end=NOW - DAY, source="teams-chat", colleague="Group Functions Autopilot",
                                 models={"gpt-5.4-mini": {"calls": 1, "prompt_tokens": 10, "completion_tokens": 1,
                                                          "credits": 10.0}}), function="platform", channel="teams-chat")
        self.at(NOW - DAY)
        self.ledger.note_usage({"model": "gpt-5.4-mini", "input_tokens": 1000, "output_tokens": 0, "nano_aiu": 3e9})
        self.at(NOW)
        report = self.ledger.report(days=7, infra={"fixedPerDay": 3.0, "source": "azure"})
        kpis, costs = report["kpis"], report["costs"]
        self.assertEqual((kpis["interactions"], kpis["casesWorked"], kpis["casesFinished"]), (3, 1, 1))
        # AI: 40 + 40 + 10 run credits + 3 background credits = $0.93. Work IQ: 2 calls x 1 credit = $0.02.
        self.assertAlmostEqual(costs["ai"], 0.93)
        self.assertEqual((costs["workiqCalls"], costs["workiq"]), (2, 0.02))
        self.assertAlmostEqual(costs["infrastructure"], 21.0)  # Seven days of the fixed daily cost.
        self.assertAlmostEqual(costs["people"], 3 * 50 / 60)  # One approval: three minutes at $50/hour.
        self.assertAlmostEqual(kpis["totalCost"], 0.93 + 0.02 + 21.0 + 2.5)
        self.assertAlmostEqual(kpis["costPerInteraction"], kpis["totalCost"] / 3)
        # The case: its two runs (0.80 + 0.02 Work IQ + 2/3 of the platform and background AI) and the approval.
        self.assertAlmostEqual(kpis["costPerCase"], 0.80 + 0.02 + 21.0 * 2 / 3 + 0.03 * 2 / 3 + 2.5, places=3)
        self.assertEqual(kpis["baselineCostPerCase"], 40.0)
        self.assertAlmostEqual(kpis["saving"], 40.0 - kpis["costPerCase"], places=2)
        self.assertEqual((kpis["autonomousRate"], kpis["hoursAbsorbed"]), (1.0, 0.5))
        quality = report["quality"]
        self.assertEqual(quality["firstResponse"]["median"], 0.0)  # A Word comment is acknowledged as it arrives.
        self.assertEqual(quality["resolution"]["median"], 10.0)
        self.assertEqual(quality["approvals"]["decisionTime"]["median"], 5.0)
        self.assertEqual(quality["guardrails"]["deny"], 3)
        self.assertEqual({row["name"] for row in report["channels"]}, {"Word comment", "Teams chat"})
        hr = next(row for row in report["colleagues"] if row["name"] == "HR Agent")
        self.assertEqual((hr["cases"], hr["interactions"], hr["closed"]), (1, 2, 1))
        self.assertEqual(report["topCases"][0]["key"], CASE)
        self.assertEqual(sum(point["interactions"] for point in report["series"]), 3)
        only_hr = self.ledger.report(days=7, function="hr", infra={"fixedPerDay": 3.0})
        self.assertEqual(only_hr["kpis"]["interactions"], 2)
        self.assertAlmostEqual(only_hr["costs"]["infrastructure"], 14.0)  # Its share of the platform.

    async def test_self_service_assets_are_matched_to_their_use_in_servicenow(self) -> None:
        self.work_a_case()
        self.at(NOW - DAY)
        article = asset_fact("create_knowledge_article", {"title": "Laptop crashes"},
                             json.dumps({"success": True, "article": {"sys_id": "k1", "number": "KB0010042",
                                                                      "title": "Laptop crashes", "state": "draft"}}),
                             at=NOW - DAY, colleague="IT Service Agent", function="it", run_id="run-9", case="")
        item = asset_fact("create_catalog_item", {"name": "Driver rollback"},
                          {"success": True, "sys_id": "c1", "name": "Driver rollback", "active": False},
                          at=NOW - DAY, colleague="IT Service Agent", function="it", run_id="run-9", case="")
        published = asset_fact("set_catalog_item_active", {"sys_id": "c1"}, {"success": True, "sys_id": "c1", "active": True},
                               at=NOW - DAY + 60, colleague="IT Service Agent", function="it", run_id="run-9", case="")
        self.assertIsNone(asset_fact("create_catalog_item", {}, {"success": False, "error": "x"}, at=NOW, colleague="",
                                     function="it", run_id="", case=""))
        for fact in (article, item, published):
            self.ledger.note_asset(fact)
        self.assertEqual(len(self.ledger.assets), 2)
        servicenow = {"incidents": {"total": 6, "byChannel": {"self-service": 2, "phone": 4}, "byDay": {"2026-09-26": {"phone": 4}}},
                      "requests": {"total": 9, "byItem": [{"id": "c1", "name": "Driver rollback", "count": 5},
                                                          {"id": "c2", "name": "Loaner laptop", "count": 2}],
                                   "byDay": {"2026-09-26": 9}},
                      "knowledge": {"published": 40, "uses": 3, "created": [{"id": "k1", "number": "KB0010042",
                                                                             "usesInWindow": 3, "state": "published"}]},
                      "catalog": {"active": 12, "created": [{"id": "c1", "active": True},
                                                            {"id": "c2", "name": "Loaner laptop", "active": True,
                                                             "createdOn": "2026-09-25 10:00:00"}]}}
        self.at(NOW)
        report = self.ledger.report(days=7, infra={"fixedPerDay": 1.0}, servicenow=servicenow)
        service = report["selfService"]
        self.assertTrue(service["connected"])
        uses = {item["title"]: (item["uses"], item.get("active"), item.get("state"), item["colleague"])
                for item in service["assets"]}
        self.assertEqual(uses, {"Laptop crashes": (3, None, "published", "IT Service Agent"),
                                "Driver rollback": (5, True, None, "IT Service Agent"),
                                "Loaner laptop": (2, True, None, "")})  # New in ServiceNow, not by a colleague.
        self.assertEqual((service["assetsByColleagues"], service["casesAvoided"], service["avoidedValueAtBaseline"]),
                         (2, 10, 400.0))
        demand = service["demand"]
        # Self-served: 9 catalog requests + 3 article uses; assisted: 6 incidents + 1 case from a Word comment.
        self.assertEqual((demand["selfServed"], demand["assisted"]), (12, 7))
        self.assertAlmostEqual(demand["selfServiceRate"], round(12 / 19, 4))
        self.assertEqual(demand["incidentsSelfRaised"], 2)
        missing = self.ledger.report(days=7, infra={}, servicenow={"error": "not connected"})["selfService"]
        self.assertFalse(missing["connected"])
        self.assertIsNone(missing["demand"]["selfServiceRate"])

    async def test_facts_survive_a_restart_and_a_reset_keeps_them(self) -> None:
        self.work_a_case()
        self.at(NOW)
        await self.ledger.flush()
        other = ChatScope(TENANT, "case-desk", "case:" + CASE)
        await self.store.update(other, lambda state: state["tasks"].update(case={"k": 1}))
        await self.store.clear_all(keep=self.ledger.scopes())
        self.assertEqual((await self.store.read(other))["tasks"], {})
        restarted = AnalyticsLedger(self.store, TENANT, clock=lambda: NOW)
        await restarted.load()
        self.assertEqual(set(restarted.runs), {"run-1", "run-2"})
        self.assertEqual(restarted.cases[CASE]["status"], "closed")
        self.assertEqual(restarted.approvals["req-1"]["status"], "completed")
        saved = await restarted.save_settings({"baselineCostPerCase": 55})
        again = AnalyticsLedger(self.store, TENANT, clock=lambda: NOW)
        await again.load()
        self.assertEqual((saved["baselineCostPerCase"], again.settings["baselineCostPerCase"]), (55.0, 55.0))

    async def test_the_platform_is_costed_only_while_this_host_was_recording(self) -> None:
        self.at(NOW - 1.5 * DAY)
        await self.ledger.load()  # First start: recording begins now, and survives a restart.
        self.at(NOW)
        report = self.ledger.report(days=7, infra={"fixedPerDay": 3.0})
        self.assertEqual((report["recordedDays"], report["costs"]["infrastructure"]), (1.5, 4.5))
        self.assertAlmostEqual(sum(point["infra"] for point in report["series"]), 4.5)
        self.assertIsNotNone(report["kpis"]["projectedMonthlyCost"])
        restarted = AnalyticsLedger(self.store, TENANT, clock=lambda: NOW)
        await restarted.load()
        self.assertEqual(restarted.since, NOW - 1.5 * DAY)

    async def test_a_reset_ends_open_cases_as_cancelled_and_bad_requests_are_refused(self) -> None:
        self.ledger.note_case(case("working", created=NOW - 3 * DAY))
        self.assertEqual(self.ledger.close_open_cases("control-room reset"), 1)
        self.assertEqual(self.ledger.cases[CASE]["status"], "cancelled")
        self.at(NOW)
        with self.assertRaises(ValueError):
            self.ledger.report(days=5)
        with self.assertRaises(ValueError):
            self.ledger.report(days=7, function="finance")

    def test_case_transitions_count_resolutions_and_approval_waits(self) -> None:
        first = case_fact(case("waiting", created=NOW, waiting="approval", source="email"), None, NOW + 10)
        second = case_fact(case("resolved", created=NOW, source="email"), first, NOW + 20)
        reopened = case_fact(case("working", created=NOW, source="email"), second, NOW + 30)
        again = case_fact(case("resolved", created=NOW, source="email"), reopened, NOW + 40)
        self.assertEqual((first["approvals"], again["resolutions"], again["resolved"]), (1, 2, NOW + 20))
        self.assertIsNone(first["firstResponse"])  # An email isn't answered until the colleague writes back.
        self.assertEqual(second["firstResponse"], NOW + 20)

    def test_recurring_themes_suggest_self_service(self) -> None:
        themes = analytics._themes(["Laptop blue screen after update", "Blue screen on my laptop again",
                                    "Laptop blue screen twice today", "Password reset for SAP"])
        self.assertEqual(themes[0]["theme"], "blue screen")
        self.assertEqual(themes[0]["cases"], 3)


if __name__ == "__main__":
    unittest.main()
