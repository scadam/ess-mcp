"""Inspect the built app package: entries, resolved manifests, skill folders and limits."""

import json
import os
import re
import sys
import zipfile
from pathlib import Path

import yaml

package = Path("declarative_agent/appPackage/build/appPackage.caldova.zip")
out = open(Path(os.environ["TEMP"]) / "ap-da-zip.txt", "w", encoding="utf-8")
problems = []
with zipfile.ZipFile(package) as archive:
    names = archive.namelist()
    out.write(f"{package} {package.stat().st_size:,} bytes, {len(names)} entries\n")
    for info in archive.infolist():
        out.write(f"  {info.filename}  {info.file_size:,}\n")
    manifest = json.loads(archive.read("manifest.json"))
    agent_file = manifest["copilotAgents"]["declarativeAgents"][0]["file"]
    agent = json.loads(archive.read(agent_file))
    out.write(f"manifest version={manifest['version']} manifestVersion={manifest['manifestVersion']} id={manifest['id']}\n")
    out.write(f"agent version={agent['version']} name={agent['name']!r} disclaimer={agent['disclaimer']['text']!r}\n")
    out.write(f"instructions chars={len(agent['instructions'])} starts={agent['instructions'][:60]!r}\n")
    out.write(f"sensitivity_label={agent.get('sensitivity_label')}\n")
    out.write(f"actions={[(a['id'], a['file']) for a in agent['actions']]}\n")
    out.write(f"starters={len(agent['conversation_starters'])}: {[s['title'] for s in agent['conversation_starters']]}\n")
    out.write(f"agent_skills={agent.get('agent_skills')}\n")
    if "${{" in json.dumps(agent) + json.dumps(manifest):
        problems.append("unresolved ${{...}} placeholder")
    for action in agent["actions"]:
        if action["file"] not in names:
            problems.append(f"missing action file {action['file']}")
    for icon in manifest["icons"].values():
        if icon not in names:
            problems.append(f"missing icon {icon}")
    skills = agent.get("agent_skills") or []
    if len(skills) > 8:
        problems.append("more than 8 skills")
    skill_files = [name for name in names if name.startswith("skills/")]
    if len(skill_files) > 350:
        problems.append("more than 350 skill files")
    allowed = {".json", ".xml", ".yaml", ".yml", ".md", ".txt", ".csv", ".tsv", ".html", ".htm", ".py", ".js", ".png"}
    for name in skill_files:
        if name.endswith("/"):
            continue
        if Path(name).suffix.lower() not in allowed:
            problems.append(f"unsupported file type {name}")
        if len(Path(name).parts) - 2 > 3:
            problems.append(f"too deep {name}")
    for skill in skills:
        folder = skill["folder"].rstrip("/")
        text = archive.read(f"{folder}/SKILL.md").decode("utf-8")
        front = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
        meta = yaml.safe_load(front.group(1)) if front else {}
        name = meta.get("name") if isinstance(meta, dict) else None
        description = str(meta.get("description") or "") if isinstance(meta, dict) else ""
        if isinstance(meta, dict) and set(meta) - {"name", "description"}:
            problems.append(f"{folder}: unexpected frontmatter keys {sorted(set(meta) - {'name', 'description'})}")
        body = text[front.end():] if front else text
        files = sorted(entry[len(folder) + 1:] for entry in skill_files if entry.startswith(folder + "/") and not entry.endswith("/"))
        out.write(f"skill {folder}: name={name} description={len(description)} chars, body={len(body)} chars, files={files}\n")
        if name != Path(folder).name:
            problems.append(f"{folder}: frontmatter name {name!r} does not match the folder")
        if not description or len(description) > 1024:
            problems.append(f"{folder}: description missing or longer than 1024 characters")
        if len(body) >= 20000:
            problems.append(f"{folder}: instructions are 20,000 characters or more")
        for reference in re.findall(r"`((?:scripts|references)/[^`\s]+)`", body):
            if f"{folder}/{reference}" not in names:
                problems.append(f"{folder}: SKILL.md mentions {reference}, which is not in the package")
    extra = [name for name in names if not name.startswith("skills/") and name not in
             {"manifest.json", agent_file, *manifest["icons"].values(), *(a["file"] for a in agent["actions"])}]
    if extra:
        out.write(f"other entries: {extra}\n")
out.write("problems: " + ("none" if not problems else "; ".join(problems)) + "\n")
out.close()
sys.exit(1 if problems else 0)
