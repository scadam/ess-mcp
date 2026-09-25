"""Three-way match every Coupa request-to-pay chain and classify the exceptions under the P2P policy.

Usage: p2p_exceptions.py [--as-of YYYY-MM-DD]
Reads the Coupa results saved under data/coupa/ and writes analysis/exceptions.json and reports/exceptions.csv.
Standard library only; amounts are GBP.
"""

from __future__ import annotations

import csv
import glob
import json
import os
import sys
from datetime import date, timedelta

TOLERANCE_ABS, TOLERANCE_PCT = 250.0, 0.02
DUE_SOON_DAYS = 3
ACK_DAYS, ACK_ESCALATE_DAYS = 2, 5
SOD_THRESHOLD = 10_000.0
CONTRACT_WARNING_DAYS, MIN_ON_TIME, MAX_DEFECTS = 60, 85.0, 2.0
AUTHORITY = ((10_000.0, "Line manager"), (50_000.0, "Category manager"), (float("inf"), "Finance Director"))
OPEN_PO = {"issued", "pending_supplier_ack", "supplier_acknowledged", "partially_received"}


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
    found = []
    for doc in docs:
        for key in keys:
            value = doc.get(key) if isinstance(doc, dict) else None
            if isinstance(value, list):
                found.extend(item for item in value if isinstance(item, dict))
    return found


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


def as_of_date(argv: list[str], dashboards: list, flows: list[dict]) -> date:
    if "--as-of" in argv:
        return date.fromisoformat(argv[argv.index("--as-of") + 1])
    for doc in dashboards:
        if isinstance(doc, dict) and parse_date(doc.get("as_of")):
            return parse_date(doc["as_of"])
    for flow in flows:  # Expected delivery minus days-to-delivery is the dataset's own "today".
        order = flow.get("purchase_order") or {}
        expected, days = parse_date(order.get("expected-delivery")), order.get("days-to-delivery")
        if expected and isinstance(days, int):
            return expected - timedelta(days=days)
    return date.today()


def approver(value: float) -> str:
    return next(name for limit, name in AUTHORITY if value <= limit)


def same_person(name: str, email: str) -> bool:
    local = (email or "").split("@", 1)[0].replace(".", " ").replace("_", " ").strip().lower()
    return bool(local) and local == " ".join((name or "").lower().split())


def main(argv: list[str]) -> int:
    flows = unique(records(load("data/coupa/get_servicenow_coupa_flow*.json"), "flows"), "service-now-request")
    if not flows:
        print("No request-to-pay chains in the workspace: call coupa get_servicenow_coupa_flow first, then rerun.")
        return 2
    approvals = unique(records(load("data/coupa/list_approvals*.json"), "results"), "id")
    dashboards = load("data/coupa/get_category_manager_dashboard*.json")
    suppliers = unique(records(load("data/coupa/list_suppliers*.json"), "results")
                       + records(load("data/coupa/get_supplier_performance*.json"), "suppliers")
                       + records(dashboards, "supplier_performance"), "id")
    today = as_of_date(argv, dashboards, flows)
    exceptions: list[dict] = []
    chains: list[dict] = []

    def add(check: str, severity: str, base: dict, finding: str, rule: str, action: dict, **extra) -> None:
        exceptions.append({"id": f"EX-{len(exceptions) + 1:02d}", "check": check, "severity": severity, **base,
                           "finding": finding, "rule": rule, "action": action, **extra})

    for flow in flows:
        order = flow.get("purchase_order") or {}
        requisition = flow.get("requisition") or {}
        supplier = (flow.get("supplier") or {}).get("name") or (order.get("supplier") or {}).get("name", "")
        po_number, status = order.get("po-number", ""), order.get("status", "")
        ordered, received = money(order.get("total")), money(order.get("received-value"))
        lines = [line for line in order.get("lines") or [] if isinstance(line, dict)]
        outstanding = [f"{line['quantity'] - int(line.get('received') or 0)} x {line.get('description') or line.get('item-id')}"
                       for line in lines if isinstance(line.get("quantity"), int) and int(line.get("received") or 0) < line["quantity"]]
        received_text = ", ".join(f"{int(line.get('received') or 0)} of {line.get('quantity')} {line.get('description') or line.get('item-id')}"
                                  for line in lines)
        expected = parse_date(order.get("expected-delivery"))
        to_delivery = order.get("days-to-delivery")
        if not isinstance(to_delivery, int):
            to_delivery = (expected - today).days if expected else None
        requester = requisition.get("requester") or flow.get("employee") or ""
        base = {"request": flow.get("service-now-request"), "po": po_number, "supplier": supplier,
                "supplier_id": (flow.get("supplier") or {}).get("number") or order.get("supplier-id"),
                "requester": requester, "value": ordered}
        before = len(exceptions)

        for invoice in flow.get("invoices") or []:
            billed = money(invoice.get("total"))
            number = invoice.get("invoice-number") or str(invoice.get("id"))
            gap, tolerance = billed - received, max(TOLERANCE_ABS, TOLERANCE_PCT * billed)
            if gap <= tolerance:
                continue
            paid = str(invoice.get("payment-status", "")).lower() == "paid" or invoice.get("status") == "paid"
            rule = "Rule 1: approve or pay only up to received value plus tolerance (greater of £250 or 2%)."
            if paid:
                add("paid_ahead_of_receipt", "high", base,
                    f"{number} was paid at {gbp(billed)} but only {gbp(received)} has been received ({received_text}).",
                    rule, {"type": "decision", "owner": "Accounts Payable",
                           "summary": f"Recover {gbp(gap)} or confirm delivery for {number}"},
                    invoice=number, exposure=gap)
            elif invoice.get("status") == "approved":
                reason = (f"Billed {gbp(billed)} on {po_number} but only {gbp(received)} has been received "
                          f"({received_text}). Please issue a credit note for {gbp(gap)} or re-invoice on delivery.")
                add("invoice_over_receipt", "high", base,
                    f"{number} is approved and {str(invoice.get('payment-status', 'unpaid')).lower()} for payment at "
                    f"{gbp(billed)}, but only {gbp(received)} has been received ({received_text}).",
                    rule, {"type": "autonomous", "summary": f"Reject {number} so the scheduled payment stops",
                           "call": {"server": "coupa", "tool": "reject_invoice",
                                    "args": {"invoice_id": number, "reason": reason}}},
                    invoice=number, exposure=gap)
            else:
                approval = next((item for item in approvals if item.get("type") == "Invoice"
                                 and (number in str(item.get("title", ""))
                                      or item.get("service-now-request") == flow.get("service-now-request"))), None)
                comment = (f"Rejected: billed {gbp(billed)} but {gbp(received)} received on {po_number} "
                           f"({received_text}). Please send a credit note for {gbp(gap)} or re-bill once the balance is delivered.")
                action = ({"type": "autonomous", "summary": f"Reject approval {approval['id']} for {number}",
                           "call": {"server": "coupa", "tool": "approve_reject",
                                    "args": {"approvable_id": approval["id"], "action": "reject", "comment": comment}}}
                          if approval else {"type": "decision", "owner": "Accounts Payable",
                                            "summary": f"Hold {number}: no pending approval was found to reject"})
                add("invoice_over_receipt", "medium", base,
                    f"{number} awaits approval at {gbp(billed)} but only {gbp(received)} has been received ({received_text}).",
                    rule, action, invoice=number, exposure=gap, approval=approval["id"] if approval else None)

        if status in OPEN_PO and isinstance(to_delivery, int) and outstanding:
            if to_delivery < 0:
                add("late_delivery", "medium", base,
                    f"{po_number} was due {expected} ({-to_delivery} days late); outstanding: {', '.join(outstanding)}.",
                    "Rule 2: chase the supplier for the outstanding quantity and a firm date.",
                    {"type": "chase", "owner": supplier,
                     "summary": f"Chase {supplier} for {', '.join(outstanding)} on {po_number}"})
            elif to_delivery <= DUE_SOON_DAYS:
                add("delivery_due", "low", base,
                    f"{po_number} is due {expected} with {', '.join(outstanding)} still to arrive.",
                    "Rule 2: confirm the receipt plan when delivery is within 3 days.",
                    {"type": "chase", "owner": "IT Asset Management",
                     "summary": f"Confirm the receipt plan for {po_number} ({', '.join(outstanding)})"})

        if status == "pending_supplier_ack":
            issued = parse_date(order.get("created-at"))
            waited = (today - issued).days if issued else None
            if waited is not None and waited > ACK_DAYS:
                escalate = waited > ACK_ESCALATE_DAYS
                add("ack_overdue", "high" if escalate else "medium", base,
                    f"{supplier} has not acknowledged {po_number} ({gbp(ordered)}), issued {issued}: {waited} days.",
                    "Rule 3: acknowledgement within 2 days; the category manager decides on re-sourcing after 5.",
                    {"type": "decision" if escalate else "chase", "owner": "Category manager" if escalate else supplier,
                     "summary": (f"Decide whether to re-source {po_number}" if escalate
                                 else f"Chase {supplier} to acknowledge {po_number}")})

        for approval in approvals:
            if (approval.get("status", "pending") != "pending" or approval.get("type") not in {"Requisition", "Purchase Order"}
                    or (approval.get("service-now-request") != flow.get("service-now-request")
                        and po_number not in str(approval.get("title", "")))
                    or status not in OPEN_PO | {"closed"}):
                continue
            value = money(approval.get("total")) or ordered
            owner = approver(value)
            how = "sent to the supplier" if status == "pending_supplier_ack" else "issued"
            add("approval_bypass", "high" if value > 50_000 else "medium", base,
                f"{po_number} was {how} on {order.get('created-at')} while {approval['type'].lower()} approval "
                f"{approval['id']} ({gbp(value)}, submitted {approval.get('submitted-at')}) is still pending.",
                f"Rule 4: {gbp(value)} needs the {owner.lower()}; a PO before approval is an approval bypass.",
                {"type": "decision", "owner": owner,
                 "summary": f"Approve {approval['id']} retrospectively or cancel {po_number}; tell Compliance"},
                approval=approval["id"])

        for receipt in flow.get("receipts") or []:
            if same_person(requester, receipt.get("received-by", "")):
                material = ordered > SOD_THRESHOLD
                add("sod_self_receipt", "medium" if material else "low", base,
                    f"{requester} requested {po_number} ({gbp(ordered)}) and also receipted it ({receipt.get('receipt-number')}).",
                    "Rule 5: above £10,000 the receipt is confirmed by someone other than the requester.",
                    {"type": "decision" if material else "monitor", "owner": "IT Asset Management",
                     "summary": "Confirm the receipt independently and report it to Compliance"})
                break

        mine = exceptions[before:]
        serious = sum(1 for item in mine if item["severity"] in {"high", "medium"})
        state = ("exceptions" if serious else "observations" if mine
                 else "closed" if status == "closed" else "awaiting delivery")
        chains.append({"request": flow.get("service-now-request"), "requester": requester,
                       "department": flow.get("department"), "supplier": supplier, "po": po_number,
                       "po_status": status, "ordered": ordered, "received": received,
                       "invoiced": sum(money(item.get("total")) for item in flow.get("invoices") or []),
                       "expected_delivery": str(expected or ""), "state": state, "exceptions": serious,
                       "observations": len(mine) - serious})

    for supplier in suppliers:
        reasons = []
        contract = supplier.get("contract") or {}
        expires = parse_date(contract.get("expires"))
        metrics = supplier.get("metrics") or {}
        if expires and (expires - today).days <= CONTRACT_WARNING_DAYS:
            reasons.append(f"contract {contract.get('id')} expires {expires} (in {(expires - today).days} days)")
        if isinstance(metrics.get("on_time_rate"), (int, float)) and metrics["on_time_rate"] < MIN_ON_TIME:
            reasons.append(f"on-time delivery {metrics['on_time_rate']}% (below 85%)")
        if isinstance(metrics.get("defect_rate"), (int, float)) and metrics["defect_rate"] > MAX_DEFECTS:
            reasons.append(f"defect rate {metrics['defect_rate']}% (above 2%)")
        if not reasons:
            continue
        open_orders = [chain["po"] for chain in chains if chain["supplier"] == supplier.get("name")
                       and chain["po_status"] in OPEN_PO]
        add("supplier_watch", "medium",
            {"request": None, "po": ", ".join(open_orders) or None, "supplier": supplier.get("name"),
             "supplier_id": supplier.get("id"), "requester": None, "value": money(metrics.get("open_value"))},
            f"{supplier.get('name')}: " + "; ".join(reasons) + (f". Open POs: {', '.join(open_orders)}." if open_orders else "."),
            "Rule 6: a watch-list supplier needs a renew-or-re-source decision before new orders.",
            {"type": "decision", "owner": "Category manager",
             "summary": f"Renew or re-source {supplier.get('name')} before placing new orders"})

    severities = {level: sum(1 for item in exceptions if item["severity"] == level) for level in ("high", "medium", "low")}
    kinds = {kind: sum(1 for item in exceptions if item["action"]["type"] == kind)
             for kind in ("autonomous", "chase", "decision", "monitor")}
    exposure = sum(item.get("exposure") or 0 for item in exceptions)
    clean = sum(1 for chain in chains if chain["exceptions"] == 0)
    summary = {"as_of": today.isoformat(), "chains": len(chains), "clean_chains": clean, "exceptions": len(exceptions),
               "by_severity": severities, "by_action": kinds, "exposure": round(exposure, 2)}
    os.makedirs("analysis", exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    with open("analysis/exceptions.json", "w", encoding="utf-8") as handle:
        json.dump({"as_of": today.isoformat(), "summary": summary, "chains": chains, "exceptions": exceptions}, handle, indent=2)
    with open("reports/exceptions.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "severity", "check", "request", "po", "supplier", "value", "exposure", "finding",
                         "action", "owner", "next step"])
        for item in exceptions:
            action = item["action"]
            writer.writerow([item["id"], item["severity"], item["check"], item.get("request") or "", item.get("po") or "",
                             item.get("supplier") or "", f"{item.get('value') or 0:.2f}", f"{item.get('exposure') or 0:.2f}",
                             item["finding"], action["type"], action.get("owner", "procurement colleague"), action["summary"]])
    print(f"As of {today}: {len(chains)} request-to-pay chains, {clean} clean. {len(exceptions)} exceptions "
          f"({severities['high']} high, {severities['medium']} medium, {severities['low']} low); "
          f"{gbp(exposure)} billed ahead of receipt.")
    for item in exceptions:
        print(f"{item['id']} {item['severity']:<6} {item['check']:<22} {item.get('po') or item.get('supplier')}: "
              f"{item['action']['type']} - {item['action']['summary']}")
    print("Wrote analysis/exceptions.json and reports/exceptions.csv.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
