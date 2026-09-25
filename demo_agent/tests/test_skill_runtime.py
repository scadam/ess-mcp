"""Offline contracts for skill packages, the run workspace, sandboxed scripts, policy checks and model routing."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from demo_agent.skill_runtime import (
    ModelRouter, SkillSession, Workspace, check_autonomy, load_library, load_skill, parse_grants, run_script,
)

SKILLS = Path(__file__).resolve().parent.parent / "skills"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
COUPA = json.loads((FIXTURES / "coupa_snapshot.json").read_text(encoding="utf-8"))
INBOX = json.loads((FIXTURES / "workday_inbox.json").read_text(encoding="utf-8"))
QUEUE = json.loads((FIXTURES / "servicenow_queue.json").read_text(encoding="utf-8"))


def coupa_workspace(run_id: str = "run-test") -> Workspace:
    workspace = Workspace(run_id)
    for tool, value in COUPA.items():
        workspace.save_tool_result("coupa", tool, {}, json.dumps(value))
    return workspace


def write_skill(root: Path, name: str, frontmatter: str, scripts: dict[str, str] | None = None) -> Path:
    folder = root / name
    (folder / "scripts").mkdir(parents=True)
    (folder / "SKILL.md").write_text(f"---\n{frontmatter}\n---\nDo the work.\n", encoding="utf-8")
    for script, body in (scripts or {}).items():
        (folder / "scripts" / script).write_text(body, encoding="utf-8")
    return folder


class LibraryTests(unittest.TestCase):
    def test_every_shipped_skill_loads_with_metadata_and_the_flagships_are_packages(self) -> None:
        library = load_library(SKILLS)
        self.assertEqual(len(library), 20)
        for name in ("it-second-line", "hr-second-line", "compliance-second-line", "supply-second-line"):
            self.assertEqual(library[name].metadata["mode"], "case")
        for name in ("access-review-panel", "supplier-onboarding-panel"):
            self.assertEqual(library[name].metadata["mode"], "assignment")
        for name, package in library.items():
            self.assertEqual(package.name, name)
            self.assertTrue(package.summary and package.servers and package.launch)
        for name in ("procurement-month-end-close", "hr-hiring-backlog-clearance", "p2p-controls-test", "zero-touch-service-desk"):
            package = library[name]
            self.assertFalse(package.legacy)
            self.assertEqual((package.tier("orchestrator"), package.tier("subagents")), ("reasoning", "fast"))
            self.assertTrue(package.grants and package.budget and package.metadata["autonomy-check"])
            paths = {item["path"] for item in package.files()}
            self.assertIn(package.metadata["autonomy-check"], paths)
            self.assertTrue(any(path.startswith("references/") for path in paths))
            self.assertTrue(any(path.startswith("templates/") for path in paths))
        self.assertTrue(library["incident-triage"].legacy)
        self.assertEqual(library["incident-triage"].title, "Incident Triage")
        self.assertEqual(library["incident-triage"].budget, 0)

    def test_grants_parse_argument_limits_and_ignore_reads(self) -> None:
        grants = parse_grants("coupa__approve_reject(action=reject) coupa__get_po_status servicenow__create_incident")
        self.assertEqual([grant.label() for grant in grants],
                         ["coupa.approve_reject (action: reject)", "servicenow.create_incident"])
        self.assertTrue(grants[0].matches("coupa", "approve_reject", {"action": "Reject"}))
        self.assertFalse(grants[0].matches("coupa", "approve_reject", {"action": "approve"}))
        for bad in ("Bash(rm:*)", "coupa__x(a=b c)", "github__merge"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_grants(bad)

    def test_invalid_packages_are_skipped_and_bundled_reads_stay_inside_the_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write_skill(root, "good-skill", "name: good-skill\ndescription: Does good work. Use when needed.")
            write_skill(root, "bad-skill", "name: other-name\ndescription: Mismatched.")
            write_skill(root, "worse-skill", "name: worse-skill\ndescription: Bad grants.\nallowed-tools: Bash(*)")
            (root / "good-skill" / "references").mkdir()
            (root / "good-skill" / "references" / "rules.md").write_text("# Rules\nBe exact.", encoding="utf-8")
            (root / "secret.txt").write_text("outside", encoding="utf-8")
            library = load_library(root)
            self.assertEqual(sorted(library), ["good-skill"])
            package = library["good-skill"]
            self.assertIn("Be exact.", package.read("references/rules.md")["content"])
            for path in ("../secret.txt", "references/../../secret.txt", "/etc/passwd", "SKILL.md", "references\\rules.md"):
                with self.subTest(path=path), self.assertRaises((ValueError, FileNotFoundError)):
                    package.read(path)
            with self.assertRaises(FileNotFoundError):
                package.script("../../secret.txt")

    def test_flat_skill_without_frontmatter_still_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "old-skill.md"
            path.write_text("You are an agent that checks things.\n\n1. Check.", encoding="utf-8")
            package = load_skill(path)
            self.assertTrue(package.legacy)
            self.assertEqual(package.description, "You are an agent that checks things.")


class WorkspaceTests(unittest.TestCase):
    def test_paths_are_relative_and_bounded(self) -> None:
        workspace = Workspace("run")
        for bad in ("../x", "/abs", "a\\b", "c:x", "a/../b", ".", "a/./b", "", "x" * 201, "a/b/c/d/e/f"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                workspace.write(bad, "x", source="test")
        self.assertEqual(workspace.write("./reports/brief.md", "hello", source="test")["path"], "reports/brief.md")
        with patch.object(Workspace, "MAX_FILE_BYTES", 10), self.assertRaises(ValueError):
            workspace.write("big.txt", "x" * 11, source="test")
        with patch.object(Workspace, "MAX_FILES", 1), self.assertRaises(ValueError):
            workspace.write("second.txt", "x", source="test")
        self.assertEqual(workspace.read_text("reports/brief.md", offset=1, limit=2)["content"], "el")

    def test_tool_results_land_on_predictable_paths(self) -> None:
        workspace = Workspace("run")
        self.assertEqual(workspace.save_tool_result("coupa", "list_approvals", {"x": None}, "{}"), "data/coupa/list_approvals.json")
        self.assertRegex(workspace.save_tool_result("coupa", "get_po_status", {"po_number": "PO-1"}, "not json"),
                         r"^data/coupa/get_po_status-[0-9a-f]{8}\.txt$")


class ScriptTests(unittest.IsolatedAsyncioTestCase):
    async def test_script_runs_isolated_without_credentials_or_site_packages(self) -> None:
        probe = (
            "import json, os, sys\n"
            "try:\n    import yaml\n    site = True\nexcept ImportError:\n    site = False\n"
            "open('out/env.json', 'w').write(json.dumps({'keys': sorted(os.environ), 'site': site, 'data': open('data/in.txt').read()}))\n"
            "print('£ ok')\n"
        )
        with tempfile.TemporaryDirectory() as temp:
            package = load_skill(write_skill(Path(temp), "probe-skill", "name: probe-skill\ndescription: Probe.", {"probe.py": probe}))
            workspace = Workspace("run")
            workspace.write("data/in.txt", "input", source="test")
            workspace.write("out/keep.txt", "", source="test")
            with patch.dict(os.environ, {"IDENTITY_ENDPOINT": "http://secret", "IDENTITY_HEADER": "secret",
                                         "AZURE_CLIENT_SECRET": "secret"}):
                result = await run_script(package, "probe.py", [], workspace)
            self.assertEqual(result["exitCode"], 0, result)
            self.assertIn("£ ok", result["stdout"])
            data = json.loads(workspace.read_bytes("out/env.json"))
            self.assertFalse(data["site"])
            self.assertEqual(data["data"], "input")
            self.assertFalse({"IDENTITY_ENDPOINT", "IDENTITY_HEADER", "AZURE_CLIENT_SECRET"} & set(data["keys"]))
            self.assertEqual(result["files"], ["out/env.json"])

    async def test_script_time_limit_and_unbundled_scripts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            package = load_skill(write_skill(Path(temp), "slow-skill", "name: slow-skill\ndescription: Slow.",
                                             {"slow.py": "import time\ntime.sleep(30)\n"}))
            with self.assertRaises(asyncio.TimeoutError):
                await run_script(package, "slow.py", [], Workspace("run"), timeout=1.0)
            for bad in ("missing.py", "../SKILL.md", "slow.sh"):
                with self.subTest(bad=bad), self.assertRaises(FileNotFoundError):
                    await run_script(package, bad, [], Workspace("run"))
            with self.assertRaises(ValueError):
                await run_script(package, "slow.py", ["two\nlines"], Workspace("run"))


class FlagshipScriptTests(unittest.IsolatedAsyncioTestCase):
    async def test_procurement_close_matches_chains_and_sources_replenishment_within_policy(self) -> None:
        library = load_library(SKILLS)
        package, workspace = library["procurement-month-end-close"], coupa_workspace()
        result = await run_script(package, "p2p_exceptions.py", [], workspace)
        self.assertEqual(result["exitCode"], 0, result["stderr"])
        analysis = json.loads(workspace.read_bytes("analysis/exceptions.json"))
        summary = analysis["summary"]
        self.assertEqual((summary["as_of"], summary["chains"], summary["clean_chains"]), ("2026-05-06", 7, 3))
        self.assertEqual((summary["by_severity"]["high"], summary["exposure"]), (2, 11010.0))
        calls = {item["action"]["call"]["tool"]: item["action"]["call"]["args"] for item in analysis["exceptions"]
                 if item["action"].get("call")}
        self.assertEqual(calls["reject_invoice"]["invoice_id"], "INV-2026-0412")
        self.assertEqual((calls["approve_reject"]["approvable_id"], calls["approve_reject"]["action"]), ("APR-602", "reject"))
        checks = {item["check"] for item in analysis["exceptions"]}
        self.assertTrue({"approval_bypass", "sod_self_receipt", "late_delivery", "ack_overdue", "supplier_watch"} <= checks)
        result = await run_script(package, "stock_cover.py", [], workspace)
        self.assertEqual(result["exitCode"], 0, result["stderr"])
        rows = {row["item"]: row for row in json.loads(workspace.read_bytes("analysis/replenishment.json"))["items"]
                if row["status"] == "reorder"}
        self.assertEqual(sorted(rows), ["IT-DOCK-USBC", "IT-IPHONE-15P"])
        self.assertEqual((rows["IT-DOCK-USBC"]["mode"], rows["IT-DOCK-USBC"]["quantity"], rows["IT-DOCK-USBC"]["supplier_id"]),
                         ("autonomous", 70, "SUP-4103"))
        self.assertEqual((rows["IT-IPHONE-15P"]["mode"], rows["IT-IPHONE-15P"]["value"]), ("approval", 29970.0))
        session = SkillSession.start(package, "run-test")
        session.workspace = workspace
        allowed, reason = await check_autonomy(session, "coupa", "create_requisition", rows["IT-DOCK-USBC"]["call"]["args"])
        self.assertTrue(allowed, reason)
        allowed, reason = await check_autonomy(session, "coupa", "create_requisition", rows["IT-IPHONE-15P"]["call"]["args"])
        self.assertFalse(allowed)
        self.assertIn("not an eligible source", reason)
        for tool, args in (("reject_invoice", calls["reject_invoice"]), ("approve_reject", calls["approve_reject"])):
            self.assertTrue((await check_autonomy(session, "coupa", tool, args))[0])
        self.assertFalse((await check_autonomy(session, "coupa", "approve_reject", {"approvable_id": "APR-601", "action": "reject"}))[0])
        self.assertFalse((await check_autonomy(session, "coupa", "reject_invoice", {"invoice_id": "INV-2026-0398"}))[0])
        session.spend(session.package.grants[2], "coupa", "create_requisition", rows["IT-DOCK-USBC"]["call"]["args"])
        self.assertFalse((await check_autonomy(session, "coupa", "create_requisition", rows["IT-DOCK-USBC"]["call"]["args"]))[0])
        result = await run_script(package, "render_brief.py", ["--by", "Supply Chain Agent"], workspace)
        self.assertEqual(result["exitCode"], 0, result["stderr"])
        self.assertIn("3 of 7 request-to-pay chains are clean", workspace.read_bytes("reports/month-end-brief.md").decode())

    async def test_policy_check_without_evidence_declines(self) -> None:
        package = load_library(SKILLS)["procurement-month-end-close"]
        allowed, reason = await check_autonomy(SkillSession.start(package, "empty"), "coupa", "reject_invoice", {"invoice_id": "INV-2026-0412"})
        self.assertFalse(allowed)
        self.assertIn("not in the saved", reason)

    async def test_hr_triage_routes_bulk_work_and_ranks_decisions(self) -> None:
        package = load_library(SKILLS)["hr-hiring-backlog-clearance"]
        workspace = Workspace("run-hr")
        workspace.save_tool_result("workday", "get_inbox_tasks", {}, json.dumps(INBOX))
        result = await run_script(package, "triage_inbox.py", ["--as-of", "2026-09-24"], workspace)
        self.assertEqual(result["exitCode"], 0, result["stderr"])
        triage = json.loads(workspace.read_bytes("analysis/triage.json"))
        self.assertEqual(triage["summary"]["total"], 100)
        self.assertEqual([ticket["bucket"] for ticket in triage["tickets"]], ["account-setup", "unassigned", "test-data"])
        self.assertEqual(triage["decisions"][0]["bucket"], "compensation")
        self.assertTrue(all(item["bucket"] != "test-data" for item in triage["decisions"]))
        session = SkillSession.start(package, "run-hr")
        session.workspace = workspace
        ticket = {"short_description": triage["tickets"][0]["short_description"]}
        self.assertTrue((await check_autonomy(session, "servicenow", "create_incident", ticket))[0])
        self.assertFalse((await check_autonomy(session, "servicenow", "create_incident", {"short_description": "HR backlog: other"}))[0])
        self.assertFalse((await check_autonomy(session, "workday", "action_inbox_task", {"task_id": "x", "decision": "approve"}))[0])

    async def test_controls_test_finds_reportable_exceptions_and_cases_stay_idempotent(self) -> None:
        package = load_library(SKILLS)["p2p-controls-test"]
        workspace = coupa_workspace("run-controls")
        workspace.save_tool_result("salesforce", "list_cases", {"search_text": "P2P-C"}, json.dumps(
            {"cases": [{"case_number": "00001071", "subject": "[P2P-C4-SUP-4105] earlier case"}]}))
        result = await run_script(package, "controls_test.py", [], workspace)
        self.assertEqual(result["exitCode"], 0, result["stderr"])
        controls = json.loads(workspace.read_bytes("analysis/controls.json"))
        findings = {item["id"]: item for item in controls["findings"]}
        self.assertEqual(sorted(findings), ["P2P-C1-INV-2026-0412", "P2P-C2-PO-2026-1055", "P2P-C2-PO-2026-1074",
                                            "P2P-C3-SOD-2026-05", "P2P-C4-SUP-4105"])
        self.assertEqual([item["severity"] for item in controls["findings"] if item["severity"] == "high"], ["high", "high"])
        self.assertEqual(findings["P2P-C4-SUP-4105"]["case"]["existing"], "00001071")
        session = SkillSession.start(package, "run-controls")
        session.workspace = workspace
        draft = findings["P2P-C1-INV-2026-0412"]["case"]["draft"]
        args = {key: draft[key] for key in ("subject", "compliance_type", "priority", "description")}
        self.assertTrue((await check_autonomy(session, "salesforce", "create_case", args))[0])
        self.assertFalse((await check_autonomy(session, "salesforce", "create_case", {**args, "priority": "Low"}))[0])
        existing = findings["P2P-C4-SUP-4105"]["case"]["draft"]
        self.assertFalse((await check_autonomy(session, "salesforce", "create_case", {
            key: existing[key] for key in ("subject", "compliance_type", "priority")}))[0])
        result = await run_script(package, "render_workpaper.py", [], workspace)
        self.assertEqual(result["exitCode"], 0, result["stderr"])
        self.assertIn("P2P-C2-PO-2026-1055", workspace.read_bytes("reports/controls-workpaper.md").decode())

    async def test_service_desk_plans_every_incident_and_the_check_holds_the_colleague_to_the_plan(self) -> None:
        package = load_library(SKILLS)["zero-touch-service-desk"]
        workspace = Workspace("run-it")
        for tool, value in QUEUE.items():
            workspace.save_tool_result("servicenow", tool, {}, json.dumps(value))
        workspace.save_tool_result("servicenow", "list_problems", {"search_text": "SFA"}, json.dumps({"problems": [
            {"number": "PRB0000006", "state": "Fix in Progress", "short_description": "Can't access SFA software"}]}))
        result = await run_script(package, "triage_queue.py", ["--as-of", "2026-06-15"], workspace)
        self.assertEqual(result["exitCode"], 0, result["stderr"])
        self.assertIn("Worklist:", result["stdout"])
        self.assertLess(len(result["stdout"]), 12_000)
        queue = json.loads(workspace.read_bytes("analysis/queue.json"))
        plans = {plan["number"]: plan for plan in queue["incidents"]}
        self.assertEqual(queue["summary"]["incidents"], 40)
        self.assertEqual({plans[number]["action"]["do"] for number in ("INC0008001", "INC0008111", "INC0008112")}, {"cancel"})
        clusters = {item["cluster"]: item for item in queue["problems"]}
        self.assertEqual(sorted(clusters), ["email", "known-PRB0000006", "network", "sap", "web-defect"])
        self.assertEqual(plans["INC0000046"]["action"], {"do": "link_problem", "cluster": "known-PRB0000006"})
        self.assertEqual(package.max_turns, 80)
        self.assertEqual(len(clusters["sap"]["incidents"]), 6)
        phone = plans["INC0000020"]["action"]
        self.assertEqual((phone["do"], phone["requested_for"]), ("order_and_resolve", "David Loo"))
        self.assertEqual((plans["INC0000016"]["action"]["do"], plans["INC0000017"]["kind"]), ("dispatch", "howto"))
        gaps = {gap["topic"]: gap for gap in queue["catalog_gaps"]}
        self.assertEqual((gaps["file-share-access"]["build"], gaps["database-access"]["build"]), (True, False))

        session = SkillSession.start(package, "run-it")
        session.workspace = workspace

        async def allowed(tool: str, args: dict) -> bool:
            return (await check_autonomy(session, "servicenow", tool, args))[0]

        def spend(tool: str, args: dict) -> None:
            session.spend(session.grant_for("servicenow", tool, args), "servicenow", tool, args)

        self.assertTrue(await allowed("update_incident", {"number": "INC0008001", "state": "canceled", "work_notes": "ATF record."}))
        self.assertFalse(await allowed("update_incident", {"number": "INC0000044", "state": "canceled", "work_notes": "x"}))
        fix = {"number": "INC0000015", "state": "resolved", "close_code": "Workaround provided",
               "close_notes": "Reinstalled the VPN client.", "comments": "Hi, reinstall the client from Company Portal."}
        self.assertFalse(await allowed("update_incident", {**fix, "comments": ""}))
        self.assertTrue(await allowed("update_incident", fix))
        stale = {**fix, "number": "INC0000048", "close_code": "Solution provided"}
        self.assertFalse(await allowed("update_incident", stale))
        self.assertTrue(await allowed("update_incident", {**stale, "close_code": "No resolution provided"}))
        link = {"number": "INC0000044", "problem": "PRB0040001", "work_notes": "SAP cluster.", "comments": "Known problem."}
        self.assertFalse(await allowed("update_incident", link))
        draft = clusters["sap"]["draft"]
        self.assertTrue(await allowed("create_problem", draft))
        spend("create_problem", draft)
        self.assertFalse(await allowed("create_problem", draft))
        self.assertTrue(await allowed("update_incident", link))
        self.assertTrue(await allowed("update_incident", {"number": "INC0000046", "problem": "PRB0000006",
                                                           "work_notes": "Same fault.", "comments": "Known problem."}))
        self.assertFalse(await allowed("update_incident", {"number": "INC0000046", "problem": "PRB0000011",
                                                            "work_notes": "Wrong problem."}))
        resolve = {"number": "INC0000020", "state": "resolved", "close_code": "Resolved by request",
                   "close_notes": "Ordered a replacement.", "comments": "Hi David, your phone is on order."}
        self.assertFalse(await allowed("update_incident", resolve))
        order = {"sys_id": phone["catalog_item"]["sys_id"], "requested_for": "David Loo"}
        self.assertFalse(await allowed("order_catalog_item", {**order, "requested_for": "Joe Employee"}))
        self.assertTrue(await allowed("order_catalog_item", order))
        spend("order_catalog_item", order)
        self.assertFalse(await allowed("order_catalog_item", order))
        self.assertTrue(await allowed("update_incident", resolve))
        spec = gaps["file-share-access"]["spec"]
        item = {"name": spec["name"], "short_description": spec["short_description"], "description": "For team shares.",
                "variables": spec["variables"]}
        self.assertFalse(await allowed("create_catalog_item", {**item, "active": True}))
        self.assertFalse(await allowed("create_catalog_item", {**item, "name": "Database access request"}))
        self.assertTrue(await allowed("create_catalog_item", item))
        article = {"title": "VPN client won't start after a software update",
                   "body_text": "<p>" + "Reinstall the VPN client from Company Portal. " * 6 + "</p>"}
        self.assertTrue(await allowed("create_knowledge_article", article))
        self.assertFalse(await allowed("create_knowledge_article", {**article, "body_text": "Reinstall."}))
        self.assertFalse(await allowed("create_knowledge_article", {**article, "title": "Holiday rota"}))
        self.assertFalse(await allowed("set_catalog_item_active", {"sys_id": "a" * 32}))
        self.assertFalse(await allowed("update_incident", {"number": "INC9999999", "comments": "Hello."}))

        saved = {"update_incident": [{"updated": True, "number": "INC0008001", "incident": {"state": "8"}},
                                      {"updated": True, "number": "INC0000044", "incident": {"state": "2"}},
                                      {"updated": True, "number": "INC0000020", "incident": {"state": "6"}}],
                 "create_problem": [{"created": True, "number": "PRB0040001", "short_description": draft["short_description"]}],
                 "order_catalog_item": [{"success": True, "request_number": "REQ0010001", "sys_id": order["sys_id"]}],
                 "create_catalog_item": [{"success": True, "sys_id": "b" * 32, "name": spec["name"], "active": False}],
                 "create_knowledge_article": [{"success": True, "article": {"number": "KB0010100", "title": article["title"]}}]}
        for tool, docs in saved.items():
            for index, doc in enumerate(docs):
                workspace.save_tool_result("servicenow", tool, {"n": index}, json.dumps(doc))
        result = await run_script(package, "render_report.py", ["--by", "IT Agent"], workspace)
        self.assertEqual(result["exitCode"], 0, result["stderr"])
        report = workspace.read_bytes("reports/service-desk-report.md").decode()
        for text in ("Worked 3 of 40 active incidents", "linked to PRB0040001", "Canceled", "REQ0010001",
                     "publishing waits for approval", "KB0010100", "37 not reached"):
            self.assertIn(text, report)
        result = await run_script(package, "render_report.py", ["--dry-run"], workspace)
        self.assertIn("Dry run, nothing changed", result["stdout"])


class RouterTests(unittest.TestCase):
    def test_routes_are_validated_and_unavailable_models_fall_back(self) -> None:
        router = ModelRouter("gpt-4.1", json.dumps({"reasoning": "gpt-5.4", "fast": "gpt-4.1-mini", "bogus": "x", "standard": "bad model"}))
        self.assertEqual(router.describe()["tiers"], {"reasoning": "gpt-5.4", "standard": "gpt-4.1", "fast": "gpt-4.1-mini"})
        router.unavailable.add("gpt-5.4")
        self.assertEqual(router.model("reasoning"), "gpt-4.1")
        self.assertEqual(ModelRouter("gpt-4.1", "not json").model("fast"), "gpt-4.1")
        with patch.dict(os.environ, {"AUTOPILOT_REASONING_EFFORT": "low"}):
            self.assertEqual(router.options("gpt-5.4"), {"reasoning_effort": "low"})
            self.assertEqual(router.options("gpt-4.1-mini"), {})


if __name__ == "__main__":
    unittest.main()
