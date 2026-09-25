"""Offline smoke run of the procurement skill scripts against the saved Coupa snapshot."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
skill = root / "demo_agent" / "skills" / "procurement-month-end-close"
snapshot = json.loads((root / "demo_agent" / "tests" / "fixtures" / "coupa_snapshot.json").read_text(encoding="utf-8"))
work = Path(tempfile.mkdtemp(prefix="skill-smoke-"))
(work / "data" / "coupa").mkdir(parents=True)
for tool, value in snapshot.items():
    (work / "data" / "coupa" / f"{tool}.json").write_text(json.dumps(value), encoding="utf-8")
env = {"PATH": os.environ["PATH"], "SKILL_DIR": str(skill), "PYTHONIOENCODING": "utf-8", "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}
out = []
for script, args in (("p2p_exceptions.py", []), ("stock_cover.py", []), ("render_brief.py", ["--by", "Supply Chain Agent"])):
    result = subprocess.run([sys.executable, "-I", "-S", str(skill / "scripts" / script), *args], cwd=work, env=env,
                            capture_output=True, text=True, encoding="utf-8")
    out.append(f"== {script} exit={result.returncode}\n{result.stdout}\n{result.stderr}")
replenishment = json.loads((work / "analysis" / "replenishment.json").read_text(encoding="utf-8"))
exceptions = json.loads((work / "analysis" / "exceptions.json").read_text(encoding="utf-8"))
calls = [item["action"]["call"] for item in exceptions["exceptions"] if item["action"].get("call")]
calls += [row["call"] for row in replenishment["items"] if row.get("call")]
calls.append({"server": "coupa", "tool": "approve_reject", "args": {"approvable_id": "APR-601", "action": "reject"}})
calls.append({"server": "servicenow", "tool": "create_incident", "args": {"short_description": "Month-end P2P follow-ups: 3 chases", "caller": "System Administrator"}})
for call in calls:
    result = subprocess.run([sys.executable, "-I", "-S", str(skill / "scripts" / "authorise.py")], cwd=work, env=env,
                            input=json.dumps({"action": call, "used": []}), capture_output=True, text=True, encoding="utf-8")
    out.append(f"-- {call['server']}.{call['tool']} {json.dumps(call['args'])[:90]} -> {result.stdout.strip()} {result.stderr.strip()}")
out.append((work / "reports" / "month-end-brief.md").read_text(encoding="utf-8"))
Path(os.environ["TEMP"], "ap-skill-smoke.txt").write_text("\n".join(out), encoding="utf-8")
print(work)
