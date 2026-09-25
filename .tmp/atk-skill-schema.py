"""Print the agentSkills schema from the Teams manifest schema and skill-related snippets from the ATK extension."""

import json
import os
import re
import sys
from pathlib import Path

sys.stdout = open(os.path.join(os.environ["TEMP"], "ap-atk-schema3.txt"), "w", encoding="utf-8")
ext = sorted(Path(os.environ["USERPROFILE"], ".vscode", "extensions").glob("teamsdevapp.ms-teams-vscode-extension-*"))[-1]
for version in ("v1.28", "v1.30", "vDevPreview"):
    schema = json.loads((ext / "out/json-schemas/teams" / version / "MicrosoftTeams.schema.json").read_text(encoding="utf-8"))
    prop = schema.get("properties", {}).get("agentSkills")
    print(f"== {version} agentSkills property:")
    print(json.dumps(prop, indent=1)[:1500])
    for name, definition in schema.get("definitions", {}).items():
        if "skill" in name.lower():
            print(f"-- definition {name}:")
            print(json.dumps(definition, indent=1)[:2500])
    print("manifestVersion enum:", schema.get("properties", {}).get("manifestVersion", {}).get("enum"))

nls = json.loads((ext / "out/resource/package.nls.json").read_text(encoding="utf-8"))
print("== nls strings mentioning skill:")
for key, value in nls.items():
    if re.search(r"skill", key + " " + str(value), re.I):
        print(f"{key}: {str(value)[:260]}")

source = (ext / "out/src/extension.js").read_text(encoding="utf-8", errors="replace")
print("== extension.js size", len(source))
seen = 0
for match in re.finditer(r"agentSkills|agent_skills|TEAMSFX_AGENT_SKILLS|SKILL\.md", source):
    start = max(0, match.start() - 300)
    print("...", source[start:match.end() + 300].replace("\n", " "), "...")
    seen += 1
    if seen >= 14:
        break
