import json
import os

path = os.path.join(os.environ.get("TEMP", "."), "ap-tool-probe.json")
reports = json.load(open(path, encoding="utf-8"))
lines = []
for report in reports:
    lines.append(f"== {report['server']} {report.get('error', '')[:120]}")
    for entry in report["tools"]:
        status = entry.get("status", "?")
        extra = entry.get("shape") or entry.get("detail") or ""
        args = entry.get("args")
        lines.append(f"  [{status}] {entry['tool']} req={entry['required']} args={args} :: {str(extra)[:170]}")
out = os.path.join(os.environ.get("TEMP", "."), "ap-tool-probe.txt")
open(out, "w", encoding="utf-8").write("\n".join(lines))
print(len(lines))
