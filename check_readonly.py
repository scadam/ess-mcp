"""Check which ServiceNow tool specs are missing readOnlyHint: True."""
import re

with open("mcp_servers/src/mcp_servers/servicenow/tools.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

current_tool = None
current_has_readonly = False
tool_line = 0
results = {"missing": [], "ok": []}

for i, line in enumerate(lines):
    stripped = line.strip()
    m = re.search(r'"name"\s*:\s*"(\w+)"', stripped)
    if m:
        if current_tool is not None:
            if current_has_readonly:
                results["ok"].append(current_tool)
            else:
                results["missing"].append((current_tool, tool_line))
        current_tool = m.group(1)
        tool_line = i + 1
        current_has_readonly = False
    if "readOnlyHint" in stripped and "True" in stripped:
        current_has_readonly = True

# Check last tool
if current_tool is not None:
    if current_has_readonly:
        results["ok"].append(current_tool)
    else:
        results["missing"].append((current_tool, tool_line))

print(f"Tools WITH readOnlyHint: {len(results['ok'])}")
for t in results["ok"]:
    print(f"  OK: {t}")
print(f"\nTools MISSING readOnlyHint: {len(results['missing'])}")
for t, ln in results["missing"]:
    print(f"  MISSING: {t} (line {ln})")
