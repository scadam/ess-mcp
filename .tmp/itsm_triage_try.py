"""Run the zero-touch triage script against the offline fixture and print the incident texts for rule tuning."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
fixture = json.loads((root / "demo_agent/tests/fixtures/servicenow_queue.json").read_text(encoding="utf-8"))
work = Path(tempfile.mkdtemp(prefix="ztsd-"))
(work / "data/servicenow").mkdir(parents=True)
for tool, payload in fixture.items():
    (work / f"data/servicenow/{tool}.json").write_text(json.dumps(payload), encoding="utf-8")
script = root / "demo_agent/skills/zero-touch-service-desk/scripts/triage_queue.py"
done = subprocess.run([sys.executable, "-I", "-S", "-X", "utf8", str(script), "--as-of", "2026-06-15"], cwd=work,
                      capture_output=True, text=True, encoding="utf-8")
print("exit", done.returncode, "stdout chars", len(done.stdout))
print(done.stdout)
print(done.stderr[-3000:])
shutil.rmtree(work, ignore_errors=True)
raise SystemExit(0)
if done.returncode == 0:
    queue = json.loads((work / "analysis/queue.json").read_text(encoding="utf-8"))
    by_number = {item["number"]: item for item in fixture["list_incidents"]["incidents"]}
    for plan in queue["incidents"]:
        source = by_number[plan["number"]]
        print(f"{plan['number']} [{plan['kind']}/{plan['topic']}] {plan['action']['do']} | {plan['short_description']} | "
              f"by={plan['opened_by']} grp={plan['assignment_group']} upd={str(source.get('sys_updated_on'))[:10]} "
              f"stale={plan['stale']} kb={[k['number'] for k in plan['knowledge']]}")
        print("    desc:", " ".join(str(source.get("description") or "").split())[:220])
    print(json.dumps(queue["summary"], indent=1))
    print(json.dumps(queue["problems"], indent=1)[:2500])
    print(json.dumps(queue["kb_gaps"], indent=1)[:1500])
    print(json.dumps([{k: v for k, v in gap.items() if k != "spec"} for gap in queue["catalog_gaps"]], indent=1))
shutil.rmtree(work, ignore_errors=True)
