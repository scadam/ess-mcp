"""Run records: files and a hashed manifest are filed as the colleague, and the answer links to them."""

from __future__ import annotations

import asyncio
import hashlib
import json
import unittest
from typing import Any

from demo_agent.agent_comms import Colleague, CommsError
from demo_agent.run_records import RunRecords, folder_for, link_files, safe_name

HR = Colleague("HR Agent", "ada46fdd-f531-40b0-82cf-4c904d33d022", "f84f67e1-2e3d-4fe6-a2f8-01191bd74c5c")
BASE = "https://contoso.sharepoint.com/sites/records/Shared%20Documents"


class FakeComms:
    def __init__(self, *, share_fails: bool = False) -> None:
        self.uploads: list[tuple[Colleague, str, str, bytes, str]] = []
        self.shared: list[tuple[str, list[str]]] = []
        self.share_fails = share_fails

    def available(self, colleague: Any) -> bool:
        return bool(colleague and colleague.instance_app_id and colleague.agentic_user_id)

    async def upload(self, colleague: Colleague, drive: str, path: str, data: bytes, content_type: str) -> dict[str, Any]:
        self.uploads.append((colleague, drive, path, data, content_type))
        return {"id": "item-" + str(len(self.uploads)), "webUrl": f"{BASE}/{path.replace(' ', '%20')}"}

    async def item(self, colleague: Colleague, drive: str, path: str) -> dict[str, Any]:
        return {"id": "folder-1", "webUrl": f"{BASE}/{path.replace(' ', '%20')}"}

    async def share(self, colleague: Colleague, drive: str, item_id: str, user_ids: list[str]) -> None:
        if self.share_fails:
            raise CommsError("no")
        self.shared.append((item_id, user_ids))


class RunRecordsTests(unittest.TestCase):
    def test_files_and_a_hashed_manifest_are_uploaded_as_the_colleague(self) -> None:
        comms = FakeComms()
        records = RunRecords(comms, "drive-1", BASE)  # type: ignore[arg-type]
        files = [{"path": "plan.md", "data": b"# Plan\n", "source": "orchestrator"},
                 {"path": "reports/team_status_report.md", "data": b"# Report\n", "source": "orchestrator"}]
        folder = folder_for("HR Agent", "Team Review", "run-94bd8fe9d6ae4f049671e386c2753f02", at=1790353100)
        self.assertEqual(folder, "HR Agent/Runs/2026-09-25 1618 Team Review 94bd8fe9")
        record = asyncio.run(records.file(HR, folder, files, {"schema": "s", "answer": "done"}, share_with=["user-1"]))
        self.assertEqual([upload[2] for upload in comms.uploads],
                         [f"{folder}/plan.md", f"{folder}/reports/team_status_report.md", f"{folder}/run-manifest.json"])
        self.assertTrue(all(upload[0] is HR and upload[1] == "drive-1" for upload in comms.uploads))
        self.assertEqual(comms.uploads[0][4], "text/markdown")
        manifest = json.loads(comms.uploads[-1][3])
        self.assertEqual(manifest["files"][0], {"path": "plan.md", "bytes": 7, "writtenBy": "orchestrator",
                                                "sha256": hashlib.sha256(b"# Plan\n").hexdigest()})
        self.assertEqual(record["manifestSha256"], hashlib.sha256(comms.uploads[-1][3]).hexdigest())
        self.assertEqual(comms.shared, [("folder-1", ["user-1"])])
        self.assertTrue(record["folderUrl"].startswith(BASE))

    def test_a_failed_share_still_files_the_run(self) -> None:
        records = RunRecords(FakeComms(share_fails=True), "drive-1")  # type: ignore[arg-type]
        record = asyncio.run(records.file(HR, "HR Agent/Runs/x", [{"path": "a.md", "data": b"a"}], {}, share_with=["u"]))
        self.assertEqual(len(record["files"]), 1)

    def test_answers_link_the_files_they_mention(self) -> None:
        record = {"folder": "HR Agent/Runs/2026-09-25 1618 Team Review 94bd8fe9", "folderUrl": BASE + "/HR%20Agent",
                  "files": [{"path": "plan.md", "url": BASE + "/plan.md"},
                            {"path": "reports/team_status_report.md", "url": BASE + "/reports/team_status_report.md"}]}
        text = link_files("Deliverables:\n- `plan.md`\n- `reports/team_status_report.md`\n- `missing.md`", record, "HR Agent")
        self.assertIn(f"- [plan.md]({BASE}/plan.md)", text)
        self.assertIn(f"[reports/team_status_report.md]({BASE}/reports/team_status_report.md)", text)
        self.assertIn("- `missing.md`", text)
        self.assertIn("**Files:** [2026-09-25 1618 Team Review 94bd8fe9]", text)
        self.assertIn("2 files and a run manifest, filed by HR Agent", text)

    def test_folder_names_are_safe_for_sharepoint_and_cases_group_their_turns(self) -> None:
        self.assertEqual(safe_name('INC0010005 · Laptop: "dies" on battery (20 min)?'), "INC0010005 · Laptop dies on battery 20 min")
        self.assertEqual(safe_name("..."), "Untitled")
        case = folder_for("IT Agent", "ignored", "run-abcdef1234", case_label="INC0010005 · Laptop dies", at=1790353100)
        self.assertEqual(case, "IT Agent/Cases/INC0010005 · Laptop dies/2026-09-25 1618 abcdef12")

    def test_no_identity_or_library_means_nothing_is_filed(self) -> None:
        self.assertFalse(RunRecords(FakeComms(), "").available(HR))  # type: ignore[arg-type]
        self.assertFalse(RunRecords(FakeComms(), "drive").available(None))  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
