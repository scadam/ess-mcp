"""Render reports/controls-workpaper.md from analysis/controls.json and analysis/cases.json.

Usage: render_workpaper.py [--by "Compliance Agent"]
Fills templates/workpaper.md. analysis/cases.json is the list the colleague writes after opening cases:
[{"finding": id, "case_number": ..., "case_id": ...}]. Standard library only.
"""

from __future__ import annotations

import json
import os
import sys


def read(path: str, default):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "_None._"
    clean = [[str(cell).replace("|", "/").replace("\n", " ") for cell in row] for row in rows]
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)] + ["| " + " | ".join(row) + " |" for row in clean])


def main(argv: list[str]) -> int:
    by = argv[argv.index("--by") + 1] if "--by" in argv else "the compliance colleague"
    results = read("analysis/controls.json", None)
    if results is None:
        print("analysis/controls.json is missing: run controls_test.py first.")
        return 2
    cases = read("analysis/cases.json", [])
    cases = {item.get("finding"): item for item in cases if isinstance(item, dict)} if isinstance(cases, list) else {}
    population = ", ".join(f"{count} {name.replace('_', ' ')}" for name, count in results["population"].items())
    control_rows = [[item["control"], item["name"], item["result"], item["findings"], item["high"], item["observations"]]
                    for item in results["controls"]]
    finding_blocks = []
    for item in results["findings"]:
        case = cases.get(item["id"]) or {}
        reference = case.get("case_number") or item["case"].get("existing") or (
            "to open" if item["case"]["required"] else "workpaper only (below case threshold)")
        finding_blocks.append(
            f"### {item['id']} — {item['title']}\n\n"
            f"- Control: {item['control']} {item['control_name']} · Severity: **{item['severity']}** · Exposure: £{item['exposure']:,.2f}\n"
            f"- Finding: {item['detail']}\n- Evidence: {'; '.join(item['evidence'])}\n"
            f"- Owner: {item['owner']} · Remediation: {item['remediation']} · Due: {item['due']}\n"
            f"- Salesforce case: {reference}\n")
    observation_rows = [[item["id"], item["control"], item["detail"]] for item in results["observations"]]
    case_rows = [[finding, item.get("case_number", ""), item.get("case_id", "")] for finding, item in cases.items()]
    with open(os.path.join(os.environ.get("SKILL_DIR", "."), "templates", "workpaper.md"), encoding="utf-8") as handle:
        template = handle.read()
    values = {
        "as_of": results["as_of"], "by": by, "population": population, "conclusion": results["conclusion"],
        "controls": table(["Control", "Name", "Result", "Findings", "High", "Observations"], control_rows),
        "findings": "\n".join(finding_blocks) or "_No findings._",
        "observations": table(["ID", "Control", "Observation"], observation_rows),
        "cases": table(["Finding", "Case number", "Case ID"], case_rows),
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", str(value))
    os.makedirs("reports", exist_ok=True)
    with open("reports/controls-workpaper.md", "w", encoding="utf-8") as handle:
        handle.write(template)
    print(results["conclusion"])
    print("Wrote reports/controls-workpaper.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
