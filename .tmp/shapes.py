import json
import os

data = json.load(open(os.path.join(os.environ["TEMP"], "ap-data-samples.json"), encoding="utf-8"))
lines = []


def show(value, indent="    ", depth=0):
    if isinstance(value, dict):
        for key, item in list(value.items())[:25]:
            if isinstance(item, list):
                lines.append(f"{indent}{key}: list[{len(item)}]")
                if item and depth < 2:
                    first = item[0]
                    if isinstance(first, dict):
                        lines.append(f"{indent}  [0] = {json.dumps(first, default=str)[:600]}")
                    else:
                        lines.append(f"{indent}  [0] = {str(first)[:200]}")
            elif isinstance(item, dict) and depth < 2:
                lines.append(f"{indent}{key}: {{")
                show(item, indent + "  ", depth + 1)
                lines.append(f"{indent}}}")
            else:
                lines.append(f"{indent}{key}: {str(item)[:160]}")
    else:
        lines.append(f"{indent}{str(value)[:400]}")


for server, tools in data.items():
    lines.append(f"== {server}")
    for name, value in tools.items():
        lines.append(f"  -- {name}")
        show(value)
open(os.path.join(os.environ["TEMP"], "ap-data-shapes.txt"), "w", encoding="utf-8").write("\n".join(lines))
print(len(lines))
