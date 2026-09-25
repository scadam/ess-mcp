"""Diagnose a device from its diagnostic report text: failing component, severity, evidence and prescribed action.

Usage: diagnose_device.py <report path in the workspace>
Writes analysis/diagnosis.json and prints it. Standard library only.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


def _number(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def diagnose(text: str) -> dict:
    findings: list[dict] = []
    design = _number(r"DESIGN CAPACITY\s*[:\-]?\s*([\d,]+)\s*mWh", text)
    full = _number(r"FULL CHARGE CAPACITY\s*[:\-]?\s*([\d,]+)\s*mWh", text)
    cycles = _number(r"CYCLE COUNT\s*[:\-]?\s*([\d,]+)", text)
    if design and full:
        health = round(full / design * 100, 1)
        evidence = [f"Full charge capacity {full:,.0f} mWh of design {design:,.0f} mWh ({health}%)."]
        if cycles is not None:
            evidence.append(f"Cycle count {cycles:,.0f}.")
        if health < 60 or (cycles or 0) > 800:
            findings.append({"component": "battery", "severity": "critical" if health < 50 else "major",
                             "evidence": evidence, "action": "replace_battery_or_device",
                             "field_replaceable": True})
        elif health < 80:
            findings.append({"component": "battery", "severity": "minor", "evidence": evidence,
                             "action": "replace_at_refresh", "field_replaceable": True})
    reallocated = _number(r"Reallocated[_ ]Sector[s]?[_ ]C(?:ou)?nt[^\n\d]*(\d+)", text)
    pending = _number(r"Current[_ ]Pending[_ ]Sector[^\n\d]*(\d+)", text)
    uncorrectable = _number(r"(?:Offline[_ ])?Uncorrectable[^\n\d]*(\d+)", text)
    wear = _number(r"Percentage Used[^\n\d]*(\d+)\s*%", text)
    if any((value or 0) > 0 for value in (reallocated, pending, uncorrectable)) or (wear or 0) > 90:
        findings.append({"component": "storage", "severity": "critical", "action": "backup_now_replace_disk",
                         "field_replaceable": True, "evidence": [
                             f"Reallocated {reallocated or 0:g}, pending {pending or 0:g}, uncorrectable "
                             f"{uncorrectable or 0:g}" + (f", wear {wear:g}%" if wear is not None else "")]})
    codes = re.findall(r"\b(2000-0\d{3})\b", text)
    for code in dict.fromkeys(codes):
        number = int(code.split("-")[1])
        if 122 <= number <= 126:
            findings.append({"component": "memory", "severity": "critical", "action": "replace_memory",
                             "field_replaceable": True, "evidence": [f"ePSA error {code}"]})
        elif number in (511, 512):
            findings.append({"component": "thermal", "severity": "major", "action": "service_fan_heatsink",
                             "field_replaceable": True, "evidence": [f"ePSA error {code}"]})
        elif number == 141:
            findings.append({"component": "display", "severity": "major", "action": "replace_display",
                             "field_replaceable": True, "evidence": [f"ePSA error {code}"]})
    if re.search(r"hardware problems were detected", text, re.IGNORECASE):
        findings.append({"component": "memory", "severity": "critical", "action": "replace_memory",
                         "field_replaceable": True, "evidence": ["Windows Memory Diagnostic reported hardware problems"]})
    serial = re.search(r"(?:SERIAL(?: NUMBER)?|Service Tag)\s*[:\-]?\s*([A-Z0-9-]{5,20})", text, re.IGNORECASE)
    model = re.search(r"(?:SYSTEM PRODUCT NAME|Model)\s*[:\-]?\s*([^\n]{3,60})", text, re.IGNORECASE)
    order = {"critical": 0, "major": 1, "minor": 2}
    findings.sort(key=lambda item: order[item["severity"]])
    return {"device": {"serial": serial.group(1) if serial else "", "model": model.group(1).strip() if model else ""},
            "primary": findings[0] if findings else None, "findings": findings,
            "conclusion": (f"{findings[0]['component']} fault ({findings[0]['severity']})" if findings
                           else "No fault found in the report; ask for the vendor diagnostic or more detail.")}


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: diagnose_device.py <report path>")
        sys.exit(2)
    report = Path(sys.argv[1])
    if not report.is_file():
        print(json.dumps({"error": f"{report} is not in the workspace; save the report first."}))
        sys.exit(1)
    result = diagnose(report.read_text(encoding="utf-8", errors="replace"))
    Path("analysis").mkdir(exist_ok=True)
    Path("analysis/diagnosis.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
