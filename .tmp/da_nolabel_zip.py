"""Write a fallback copy of the built package without the agent's sensitivity label (all other entries unchanged)."""

import json
import zipfile
from pathlib import Path

source = Path("declarative_agent/appPackage/build/appPackage.caldova.zip")
target = source.with_name("appPackage.caldova-no-label.zip")
with zipfile.ZipFile(source) as original, zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as copy:
    manifest = json.loads(original.read("manifest.json"))
    agent_file = manifest["copilotAgents"]["declarativeAgents"][0]["file"]
    for info in original.infolist():
        data = original.read(info.filename)
        if info.filename == agent_file:
            agent = json.loads(data)
            agent.pop("sensitivity_label", None)
            data = (json.dumps(agent, indent=4, ensure_ascii=False) + "\n").encode("utf-8")
        copy.writestr(info, data)
with zipfile.ZipFile(target) as check:
    agent = json.loads(check.read(agent_file))
    assert "sensitivity_label" not in agent and agent.get("agent_skills")
    print(f"{target} {target.stat().st_size:,} bytes, {len(check.namelist())} entries, no sensitivity_label")
