"""Offline smoke run of the three flagship skills' scripts against the saved probe snapshots."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
skills = root / "demo_agent" / "skills"
fixtures = root / "demo_agent" / "tests" / "fixtures"
coupa = json.loads((fixtures / "coupa_snapshot.json").read_text(encoding="utf-8"))
inbox = json.loads((fixtures / "workday_inbox.json").read_text(encoding="utf-8"))
out = []


def workspace(files: dict) -> Path:
    work = Path(tempfile.mkdtemp(prefix="skill-smoke-"))
    for relative, value in files.items():
        target = work / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value), encoding="utf-8")
    return work


def run(skill: str, work: Path, script: str, args=(), stdin=None) -> str:
    env = {"PATH": os.environ["PATH"], "SKILL_DIR": str(skills / skill), "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
    result = subprocess.run([sys.executable, "-I", "-S", "-X", "utf8", str(skills / skill / "scripts" / script), *args],
                            cwd=work, env=env, input=stdin, capture_output=True, text=True, encoding="utf-8")
    return f"[exit {result.returncode}] {result.stdout}{result.stderr}"


coupa_files = {f"data/coupa/{tool}.json": value for tool, value in coupa.items()}
work = workspace(coupa_files)
for script in ("p2p_exceptions.py", "stock_cover.py"):
    out.append(f"== procurement {script}\n" + run("procurement-month-end-close", work, script))
out.append("== procurement render\n" + run("procurement-month-end-close", work, "render_brief.py", ["--by", "Supply Chain Agent"]))

work = workspace({"data/workday/get_inbox_tasks.json": inbox,
                  "data/workday/get_team_overview.json": {"teamMembers": [{"name": "Betty Liu (On Leave)"}]}})
out.append("== hr triage\n" + run("hr-hiring-backlog-clearance", work, "triage_inbox.py", ["--as-of", "2026-09-24", "--for", "Siva Vasireddy"]))
triage = json.loads((work / "analysis" / "triage.json").read_text(encoding="utf-8"))
out.append(json.dumps(triage["summary"], indent=1))
out.append(json.dumps([{key: item[key] for key in ("bucket", "short_description", "tasks")} for item in triage["tickets"]], indent=1))
out.append(triage["tickets"][0]["description"][:700])
out.append(json.dumps([(item["bucket"], item["process"], item["step"], item["waiting_days"], item["urgent"]) for item in triage["decisions"]], indent=0))
for ticket in triage["tickets"][:1]:
    action = {"server": "servicenow", "tool": "create_incident", "args": {"short_description": ticket["short_description"]}}
    out.append("hr check: " + run("hr-hiring-backlog-clearance", work, "authorise.py", stdin=json.dumps({"action": action, "used": []})))
    out.append("hr check dup: " + run("hr-hiring-backlog-clearance", work, "authorise.py",
                                       stdin=json.dumps({"action": action, "used": [{"action": "servicenow.create_incident", "args": action["args"]}]})))

files = dict(coupa_files)
files["data/coupa/list_receipts.json"] = {"results": [r for f in coupa["get_servicenow_coupa_flow"]["flows"] for r in f.get("receipts", [])]}
files["data/salesforce/list_cases.json"] = {"cases": [{"case_number": "00001071", "subject": "[P2P-C4-SUP-4105] earlier case"}]}
work = workspace(files)
out.append("== compliance test\n" + run("p2p-controls-test", work, "controls_test.py"))
controls = json.loads((work / "analysis" / "controls.json").read_text(encoding="utf-8"))
for item in controls["findings"]:
    draft = item["case"]["draft"]
    if draft:
        action = {"server": "salesforce", "tool": "create_case", "args": {key: draft[key] for key in ("subject", "compliance_type", "priority")}}
        out.append(f"compliance check {item['id']}: " + run("p2p-controls-test", work, "authorise.py", stdin=json.dumps({"action": action, "used": []})))
(work / "analysis" / "cases.json").write_text(json.dumps([{"finding": controls["findings"][0]["id"], "case_number": "00001080", "case_id": "500x"}]), encoding="utf-8")
out.append("== compliance render\n" + run("p2p-controls-test", work, "render_workpaper.py", ["--by", "Compliance Agent"]))
out.append((work / "reports" / "controls-workpaper.md").read_text(encoding="utf-8")[:3000])
Path(os.environ["TEMP"], "ap-skill-smoke.txt").write_text("\n".join(out), encoding="utf-8")
print("ok")
