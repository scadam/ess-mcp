import os
import re
import sys
from pathlib import Path

sys.stdout = open(os.path.join(os.environ["TEMP"], "ap-atk-frontmatter.txt"), "w", encoding="utf-8")
ext = sorted(Path(os.environ["USERPROFILE"], ".vscode", "extensions").glob("teamsdevapp.ms-teams-vscode-extension-*"))[-1]
source = (ext / "out/src/extension.js").read_text(encoding="utf-8", errors="replace")
for match in list(re.finditer(r"parseYamlFrontmatter\(\w+\)\{", source))[:2]:
    print(source[match.start():match.start() + 700].replace("\n", " "))
    print("----")
