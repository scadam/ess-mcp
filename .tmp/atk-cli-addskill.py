import os
import re
import sys
from pathlib import Path

sys.stdout = open(os.path.join(os.environ["TEMP"], "ap-atk-cli-addskill.txt"), "w", encoding="utf-8")
bundle = next(Path(os.environ["LOCALAPPDATA"], "npm-cache", "_npx").glob("*/node_modules/@microsoft/m365agentstoolkit-cli/lib/index.js"))
source = bundle.read_text(encoding="utf-8", errors="replace")
seen = set()
for pattern in (r"\.addSkill\(", r"agent_skills", r"skill.{0,40}version|version.{0,60}skill", r"upgradeDeclarativeAgent|declarativeAgentVersion|DA_VERSION|minimumVersion"):
    print(f"##### {pattern}")
    for match in list(re.finditer(pattern, source, re.I))[:12]:
        start = max(0, match.start() - 380)
        key = start // 500
        if key in seen:
            continue
        seen.add(key)
        print("...", source[start:match.end() + 380].replace("\n", " "), "...\n")
