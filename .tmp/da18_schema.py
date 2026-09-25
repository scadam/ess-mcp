import json
import os
from pathlib import Path

ext = sorted(Path(os.environ["USERPROFILE"], ".vscode", "extensions").glob("teamsdevapp.ms-teams-vscode-extension-*"))[-1]
schema = json.loads((ext / "out/json-schemas/copilot/declarative-agent/v1.8/schema.json").read_text(encoding="utf-8"))
out = open(Path(os.environ["TEMP"]) / "ap-da18.txt", "w", encoding="utf-8")
out.write(f"root additionalProperties={schema.get('additionalProperties')}\n")
out.write(f"root properties={sorted(schema.get('properties', {}))}\n")
starters = schema.get("properties", {}).get("conversation_starters", {})
out.write(f"conversation_starters={json.dumps(starters)[:600]}\n")
defs = schema.get("$defs") or schema.get("definitions") or {}
for name in defs:
    if "starter" in name.lower() or "skill" in name.lower():
        out.write(f"{name}: {json.dumps(defs[name])[:600]}\n")
out.close()
