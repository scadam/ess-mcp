"""Find the Agents Toolkit CLI 1.1.17 in the npx cache and show how it handles agent skills and DA v1.9."""

import os
import re
import sys
from pathlib import Path

sys.stdout = open(os.path.join(os.environ["TEMP"], "ap-atk-cli-skills.txt"), "w", encoding="utf-8")
cache = Path(os.environ["LOCALAPPDATA"]) / "npm-cache" / "_npx"
roots = [path for path in cache.glob("*/node_modules/@microsoft/m365agentstoolkit-cli") if (path / "package.json").exists()]
for root in roots:
    version = re.search(r'"version":\s*"([^"]+)"', (root / "package.json").read_text(encoding="utf-8")).group(1)
    print("cli", root, version)
    schemas = sorted(str(path.relative_to(root)) for path in root.rglob("schema.json") if "declarative-agent" in str(path))
    print("DA schemas:", schemas[-6:])
    bundles = [path for path in root.rglob("*.js") if path.stat().st_size > 2_000_000][:3]
    for bundle in bundles:
        source = bundle.read_text(encoding="utf-8", errors="replace")
        print("bundle", bundle.relative_to(root), len(source))
        for pattern in (r"v1\.9", r"agent_skills", r"addSkill\(", r"AgentSkillsManifest", r"x-agent_skills"):
            hits = [match.start() for match in re.finditer(pattern, source)]
            print(f"  {pattern}: {len(hits)}")
        for match in list(re.finditer(r"v1\.9", source))[:8]:
            print("   ...", source[max(0, match.start() - 220):match.end() + 220].replace("\n", " "))
        for match in list(re.finditer(r"version\s*[:=]\s*\"v1\.9\"|\"v1\.9\"", source))[:4]:
            print("   >>>", source[max(0, match.start() - 400):match.end() + 300].replace("\n", " "))
