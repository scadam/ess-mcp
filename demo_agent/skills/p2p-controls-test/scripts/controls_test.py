"""Test the P2P controls C1-C4 over the whole Coupa population and draft Salesforce cases for reportable findings.

Usage: controls_test.py [--as-of YYYY-MM-DD]
Reads data/coupa/ (request-to-pay chains, approvals, suppliers, receipts) and data/salesforce/list_cases*.json,
and writes analysis/controls.json and reports/findings.csv. Standard library only; amounts are GBP.
"""

from __future__ import annotations

import csv
import glob
import json
import os
import sys
from datetime import date, timedelta

TOLERANCE_ABS, TOLERANCE_PCT = 250.0, 0.02
HIGH_COMMITMENT, SOD_THRESHOLD, CASE_THRESHOLD = 50_000.0, 10_000.0, 25_000.0
CONTRACT_DAYS, MIN_ON_TIME, MAX_DEFECTS = 60, 85.0, 2.0
OPEN_PO = {"issued", "pending_supplier_ack", "supplier_acknowledged", "partially_received"}
CONTROLS = {
    "C1": ("Three-way match", "Operational Risk Event", "Accounts Payable lead",
           "Stop or recover the payment; re-bill on receipt", 5),
    "C2": ("Approval before commitment", "Policy Breach", "Approver at the required authority",
           "Approve retrospectively or cancel; root-cause the bypass", 10),
    "C3": ("Segregation of duties at receipt", "Policy Breach", "IT Asset Management",
           "Independent confirmation of the receipts; enforce receiver different from requester", 10),
    "C4": ("Third-party risk", "Third-Party / Vendor Risk", "Category manager",
           "Renew or re-source; no new orders until resolved", 20),
}


def money(value) -> float:
    try:
        return float(str(value).replace(",", "").replace("£", "").strip() or 0)
    except ValueError:
        return 0.0


def gbp(value: float) -> str:
    return f"£{value:,.2f}"


def load(pattern: str) -> list:
    docs = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="utf-8") as handle:
                docs.append(json.load(handle))
        except (OSError, ValueError):
            print(f"warning: {path} is not JSON; skipped", file=sys.stderr)
    return docs


def records(docs: list, *keys: str) -> list[dict]:
    return [item for doc in docs if isinstance(doc, dict) for key in keys
            if isinstance(doc.get(key), list) for item in doc[key] if isinstance(item, dict)]


def unique(items: list[dict], key: str) -> list[dict]:
    seen: dict = {}
    for item in items:
        if item.get(key):
            seen.setdefault(item[key], item)
    return list(seen.values())


def parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def working_days(start: date, days: int) -> date:
    current = start
    while days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


def same_person(name: str, email: str) -> bool:
    local = (email or "").split("@", 1)[0].replace(".", " ").replace("_", " ").strip().lower()
    return bool(local) and local == " ".join((name or "").lower().split())


def main(argv: list[str]) -> int:
    flows = unique(records(load("data/coupa/get_servicenow_coupa_flow*.json"), "flows"), "service-now-request")
    if not flows:
        print("No request-to-pay chains in the workspace: call coupa get_servicenow_coupa_flow first, then rerun.")
        return 2
    approvals = unique(records(load("data/coupa/list_approvals*.json"), "results"), "id")
    suppliers = unique(records(load("data/coupa/list_suppliers*.json"), "results")
                       + records(load("data/coupa/get_supplier_performance*.json"), "suppliers"), "id")
    receipts = unique(records(load("data/coupa/list_receipts*.json"), "results")
                      + [receipt for flow in flows for receipt in flow.get("receipts") or [] if isinstance(receipt, dict)],
                      "receipt-number")
    existing = records(load("data/salesforce/list_cases*.json"), "cases")
    today = None
    if "--as-of" in argv:
        today = date.fromisoformat(argv[argv.index("--as-of") + 1])
    for flow in flows if today is None else ():
        order = flow.get("purchase_order") or {}
        expected, days = parse_date(order.get("expected-delivery")), order.get("days-to-delivery")
        if expected and isinstance(days, int):
            today = expected - timedelta(days=days)
            break
    today = today or date.today()
    by_po = {(flow.get("purchase_order") or {}).get("po-number"): flow for flow in flows}
    findings, observations = [], []
    population = {"invoices": sum(len(flow.get("invoices") or []) for flow in flows), "purchase_orders": len(by_po),
                  "approvals": len(approvals), "receipts": len(receipts), "suppliers": len(suppliers)}

    def finding(control: str, key: str, severity: str, title: str, detail: str, exposure: float, evidence: list[str]) -> None:
        name, case_type, owner, remediation, due_days = CONTROLS[control]
        identifier = f"P2P-{control}-{key}"
        required = severity == "high" or (severity == "medium" and exposure >= CASE_THRESHOLD)
        opened = next((case for case in existing if identifier in str(case.get("subject", ""))), None)
        due = working_days(today, due_days)
        description = (f"{detail}\n\nControl: {control} {name}. Severity: {severity}. Exposure: {gbp(exposure)}.\n"
                       f"Evidence: {'; '.join(evidence)}.\nOwner: {owner}. Remediation: {remediation}. Due: {due}.\n"
                       f"Raised by the compliance colleague (Group Functions Autopilot) from the P2P controls test as of {today}.")
        findings.append({
            "id": identifier, "control": control, "control_name": name, "severity": severity, "title": title,
            "detail": detail, "exposure": round(exposure, 2), "evidence": evidence, "owner": owner,
            "remediation": remediation, "due": due.isoformat(),
            "case": {"required": required, "existing": (opened or {}).get("case_number"),
                     "draft": {"subject": f"[{identifier}] {title}", "compliance_type": case_type,
                               "priority": "High" if severity == "high" else "Medium", "description": description}
                     if required else None},
        })

    for flow in flows:
        order = flow.get("purchase_order") or {}
        received = money(order.get("received-value"))
        for invoice in flow.get("invoices") or []:
            billed = money(invoice.get("total"))
            gap = billed - received
            if gap <= max(TOLERANCE_ABS, TOLERANCE_PCT * billed):
                continue
            number = invoice.get("invoice-number") or str(invoice.get("id"))
            where = f"{number} ({gbp(billed)}) on {order.get('po-number')} with {gbp(received)} received"
            if invoice.get("status") == "pending_approval":
                observations.append({"control": "C1", "id": f"P2P-C1-{number}",
                                     "detail": f"{where} is held at approval: the control caught it."})
                continue
            finding("C1", number, "high", f"Invoice approved ahead of goods receipt - {(flow.get('supplier') or {}).get('name')} {gbp(gap)}",
                    f"{where} is {invoice.get('status')} with payment {str(invoice.get('payment-status')).lower()}: "
                    f"{gbp(gap)} would be paid for goods not received.", gap,
                    [number, str(order.get("po-number")), f"receipts {', '.join(r.get('receipt-number', '') for r in flow.get('receipts') or []) or 'none'}"])

    for approval in approvals:
        if approval.get("status", "pending") != "pending" or approval.get("type") not in {"Requisition", "Purchase Order"}:
            continue
        flow = next((item for item in flows if item.get("service-now-request") == approval.get("service-now-request")), None)
        order = (flow or {}).get("purchase_order") or {}
        if order.get("status") not in OPEN_PO | {"closed"}:
            continue
        value = money(approval.get("total")) or money(order.get("total"))
        how = "sent to the supplier" if order.get("status") == "pending_supplier_ack" else "issued"
        finding("C2", str(order.get("po-number")), "high" if value > HIGH_COMMITMENT else "medium",
                f"PO {how} before approval - {order.get('po-number')} {gbp(value)}",
                f"{order.get('po-number')} ({gbp(value)}) was {how} on {order.get('created-at')} while "
                f"{str(approval.get('type')).lower()} approval {approval.get('id')} (submitted {approval.get('submitted-at')}) "
                f"is still pending.", value, [str(approval.get("id")), str(order.get("po-number")), str(approval.get("service-now-request"))])

    material, minor = [], []
    for receipt in receipts:
        flow = by_po.get(receipt.get("po-number"))
        if not flow:
            continue
        requester = (flow.get("requisition") or {}).get("requester") or flow.get("employee") or ""
        if same_person(requester, receipt.get("received-by", "")):
            value = money((flow.get("purchase_order") or {}).get("total"))
            (material if value > SOD_THRESHOLD else minor).append((receipt, requester, value))
    if material:
        finding("C3", f"SOD-{today:%Y-%m}", "medium", f"Requesters receipted their own deliveries - {len(material)} POs",
                "; ".join(f"{requester} requested and receipted {receipt.get('po-number')} ({gbp(value)}, {receipt.get('receipt-number')})"
                          for receipt, requester, value in material) + ".",
                sum(value for _, _, value in material),
                [f"{receipt.get('receipt-number')} / {receipt.get('po-number')}" for receipt, _, _ in material])
    for receipt, requester, value in minor:
        observations.append({"control": "C3", "id": f"P2P-C3-{receipt.get('receipt-number')}",
                             "detail": f"{requester} receipted {receipt.get('po-number')} ({gbp(value)}), at or below the £10,000 threshold."})

    for supplier in suppliers:
        open_orders = [flow["purchase_order"] for flow in flows if (flow.get("purchase_order") or {}).get("supplier-id") == supplier.get("id")
                       and flow["purchase_order"].get("status") in OPEN_PO]
        if not open_orders:
            continue
        reasons = []
        contract = supplier.get("contract") or {}
        expires = parse_date(contract.get("expires"))
        metrics = supplier.get("metrics") or {}
        if not expires or (expires - today).days < CONTRACT_DAYS:
            reasons.append(f"contract {contract.get('id')} expires {expires} (in {(expires - today).days} days)" if expires else "no contract")
        if isinstance(metrics.get("on_time_rate"), (int, float)) and metrics["on_time_rate"] < MIN_ON_TIME:
            reasons.append(f"on-time delivery {metrics['on_time_rate']}%")
        if isinstance(metrics.get("defect_rate"), (int, float)) and metrics["defect_rate"] > MAX_DEFECTS:
            reasons.append(f"defect rate {metrics['defect_rate']}%")
        if reasons:
            exposure = money(metrics.get("open_value")) or sum(money(order.get("open-value")) for order in open_orders)
            finding("C4", str(supplier.get("id")), "medium", f"Open orders with a watch-list supplier - {supplier.get('name')}",
                    f"{supplier.get('name')} has open orders ({', '.join(order.get('po-number', '') for order in open_orders)}) "
                    f"while it breaches: {'; '.join(reasons)}.", exposure,
                    [str(supplier.get("id")), *[str(order.get("po-number")) for order in open_orders]])

    controls = []
    for control, (name, *_rest) in CONTROLS.items():
        mine = [item for item in findings if item["control"] == control]
        controls.append({"control": control, "name": name, "result": "Exceptions noted" if mine else "Effective",
                         "findings": len(mine), "high": sum(1 for item in mine if item["severity"] == "high"),
                         "observations": sum(1 for item in observations if item["control"] == control)})
    failed = sum(1 for item in controls if item["findings"])
    to_open = [item for item in findings if item["case"]["required"] and not item["case"]["existing"]]
    conclusion = (f"{failed} of {len(controls)} controls showed exceptions: {len(findings)} findings "
                  f"({sum(1 for item in findings if item['severity'] == 'high')} high) with {gbp(sum(item['exposure'] for item in findings))} "
                  f"exposure. {len(to_open)} cases to open.") if findings else "All four controls operated effectively."
    os.makedirs("analysis", exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    with open("analysis/controls.json", "w", encoding="utf-8") as handle:
        json.dump({"as_of": today.isoformat(), "population": population, "conclusion": conclusion, "controls": controls,
                   "findings": findings, "observations": observations}, handle, indent=2)
    with open("reports/findings.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "control", "severity", "title", "exposure", "owner", "due", "case required", "existing case"])
        for item in findings:
            writer.writerow([item["id"], item["control"], item["severity"], item["title"], f"{item['exposure']:.2f}",
                             item["owner"], item["due"], item["case"]["required"], item["case"]["existing"] or ""])
    print(f"As of {today}: tested {population}. {conclusion}")
    for item in findings:
        case = ("case exists " + item["case"]["existing"]) if item["case"]["existing"] else \
            ("open a case" if item["case"]["required"] else "workpaper only")
        print(f"{item['id']} {item['severity']}: {item['title']} ({gbp(item['exposure'])}) -> {case}")
    for item in observations:
        print(f"observation {item['id']}: {item['detail']}")
    print("Wrote analysis/controls.json and reports/findings.csv.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
