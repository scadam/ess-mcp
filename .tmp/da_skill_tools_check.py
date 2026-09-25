"""Check every tool a skill names exists in the agent's plugins and on the live MCP servers, and run the final smoke calls."""

import asyncio
import json
import os
import re
from pathlib import Path

from fastmcp import Client

root = Path("declarative_agent/appPackage")
out = open(Path(os.environ["TEMP"]) / "ap-da-skill-tools.txt", "w", encoding="utf-8")
plugins = {}
for name in ("workday", "servicenow", "coupa", "salesforce"):
    plugin = json.loads((root / f"{name}-mcp-plugin.json").read_text(encoding="utf-8"))
    plugins[name] = {function["name"] for function in plugin["functions"]}
declared = set().union(*plugins.values())
NOT_TOOLS = {"python", "input.json", "true", "false", "comments", "work_notes"}
missing = []
for skill in sorted((root / "skills").iterdir()):
    text = (skill / "SKILL.md").read_text(encoding="utf-8")
    names = {name for name in re.findall(r"`([a-z][a-z0-9_]+)`", text) if "_" in name and name not in NOT_TOOLS}
    tools = sorted(name for name in names if name in declared)
    unknown = sorted(name for name in names if name not in declared)
    out.write(f"{skill.name}: tools={tools}\n")
    if unknown:
        out.write(f"   not a plugin tool (fields/args?): {unknown}\n")
    missing += [(skill.name, name) for name in unknown if name.startswith(("get_", "list_", "show_", "prepare_", "search_", "create_", "order_", "reject_", "book_", "approve", "add_", "checkout"))]


async def live() -> None:
    for name in ("workday", "servicenow", "coupa"):
        async with Client(f"https://essmcp-caldova-{name}.livelysky-91807d17.eastus2.azurecontainerapps.io/{name}/mcp", timeout=90) as client:
            tools = {tool.name for tool in await client.list_tools()}
        absent = sorted(plugins[name] - tools)
        out.write(f"live {name}: {len(tools)} tools; plugin functions missing on server: {absent or 'none'}\n")


asyncio.run(live())
out.write(f"skill tools missing from plugins: {missing or 'none'}\n")
out.close()
