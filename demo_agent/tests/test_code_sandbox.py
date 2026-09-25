"""Model-written code: static facts for the policy and the runtime sandbox around the child process."""

from __future__ import annotations

import asyncio
import json
import unittest

from demo_agent.code_sandbox import analyse
from demo_agent.skill_runtime import Workspace, run_code


class AnalyseTests(unittest.TestCase):
    def test_reports_imports_calls_and_dunders(self) -> None:
        facts = analyse("import os.path, json\nfrom urllib import request\nx = ().__class__\ngetattr(x, '__subclasses__')\nos.system('x')")
        self.assertTrue(facts["syntax_ok"])
        self.assertTrue({"os", "json", "urllib"} <= set(facts["imports"]))
        self.assertIn("os.system", facts["calls"])
        self.assertTrue({"__class__", "__subclasses__"} <= set(facts["attributes"]))

    def test_syntax_errors_are_facts_not_exceptions(self) -> None:
        facts = analyse("def (:")
        self.assertFalse(facts["syntax_ok"])
        self.assertTrue(facts["error"])


class SandboxTests(unittest.TestCase):
    def run_program(self, code: str, workspace: Workspace | None = None) -> dict:
        return asyncio.run(run_code(code, workspace or Workspace("test"), timeout=20))

    def test_standard_library_code_reads_and_writes_the_workspace(self) -> None:
        workspace = Workspace("test")
        workspace.write("data/rows.json", json.dumps([1, 2, 3]).encode(), source="test")
        result = self.run_program(
            "import json, pathlib\nrows = json.loads(pathlib.Path('data/rows.json').read_text())\n"
            "pathlib.Path('out.txt').write_text(str(sum(rows)))\nprint(len(rows))", workspace)
        self.assertEqual(result["exitCode"], 0, result["stderr"])
        self.assertEqual(result["stdout"].strip(), "3")
        self.assertEqual(result["files"], ["out.txt"])

    def test_network_and_processes_are_blocked(self) -> None:
        for code in ("import socket", "import os\nos.system('echo hi')", "import subprocess"):
            with self.subTest(code=code):
                result = self.run_program(code)
                self.assertNotEqual(result["exitCode"], 0)

    def test_files_outside_the_workspace_are_blocked(self) -> None:
        result = self.run_program("import os\nprint(os.listdir(os.path.expanduser('~')))")
        self.assertNotEqual(result["exitCode"], 0)


if __name__ == "__main__":
    unittest.main()
