"""Show the Agents Toolkit add-skill implementation: SKILL.md template, folder naming and manifest wiring."""

import os
import re
import sys
from pathlib import Path

sys.stdout = open(os.path.join(os.environ["TEMP"], "ap-atk-addskill.txt"), "w", encoding="utf-8")
ext = sorted(Path(os.environ["USERPROFILE"], ".vscode", "extensions").glob("teamsdevapp.ms-teams-vscode-extension-*"))[-1]
source = (ext / "out/src/extension.js").read_text(encoding="utf-8", errors="replace")
patterns = [r"SKILL\.md", r"exposeToCopilot", r"TEAMSFX_AGENT_SKILLS", r"agentSkills\.push|agentSkills=|\.agentSkills\b", r"lZr=\d+",
            r"skills/\$\{", r'"skills"', r"version:\s*\"v1\.9\"|\"v1\.9\"", r"declarative-agent/v1\.9"]
for pattern in patterns:
    hits = list(re.finditer(pattern, source))
    print(f"##### {pattern}: {len(hits)} hits")
    shown = set()
    for match in hits[:6]:
        start = max(0, match.start() - 450)
        snippet = source[start:match.end() + 450].replace("\n", " ")
        key = snippet[:120]
        if key in shown:
            continue
        shown.add(key)
        print("...", snippet, "...\n")
