"""Deterministic policy check run by the host before any pre-approved action; prints {"allow", "reason"}.

Input on stdin: {"action": {"server", "tool", "args"}, "used": [earlier pre-approved actions]}.
It verifies the action against the evidence saved in the workspace. Anything it cannot verify is declined, and
the host then turns the action into a proposal that waits for a person.
"""

from __future__ import annotations

import glob
import json
import sys
from datetime import date, timedelta

TOLERANCE_ABS, TOLERANCE_PCT = 250.0, 0.02
AUTONOMY_LIMIT = 15_000.0
ALTERNATIVE_WINDOW_DAYS = 90
CONTRACT_MIN_DAYS, MIN_ON_TIME, MAX_DEFECTS = 60, 85.0, 2.0


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
            pass
    return docs


def records(docs: list, *keys: str) -> list[dict]:
    return [item for doc in docs if isinstance(doc, dict) for key in keys
            if isinstance(doc.get(key), list) for item in doc[key] if isinstance(item, dict)]


def parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def verdict(allow: bool, reason: str) -> int:
    print(json.dumps({"allow": allow, "reason": reason}))
    return 0


def over_receipt(flow: dict, invoice: dict) -> tuple[bool, str]:
    billed = money(invoice.get("total"))
    received = money((flow.get("purchase_order") or {}).get("received-value"))
    gap, tolerance = billed - received, max(TOLERANCE_ABS, TOLERANCE_PCT * billed)
    detail = f"billed {gbp(billed)} against {gbp(received)} received (tolerance {gbp(tolerance)})"
    return gap > tolerance, detail


def main() -> int:
    try:
        request = json.load(sys.stdin)
        action = request["action"]
        server, tool, args = action["server"], action["tool"], action.get("args") or {}
        used = request.get("used") or []
    except (ValueError, KeyError, TypeError):
        return verdict(False, "The action could not be read.")
    flows = records(load("data/coupa/get_servicenow_coupa_flow*.json"), "flows")
    approvals = records(load("data/coupa/list_approvals*.json"), "results")
    dashboards = load("data/coupa/get_category_manager_dashboard*.json")
    suppliers = {item.get("id"): item for item in records(load("data/coupa/list_suppliers*.json"), "results")
                 + records(load("data/coupa/get_supplier_performance*.json"), "suppliers")
                 + records(dashboards, "supplier_performance")}
    catalog = {item.get("id"): item for item in records(load("data/coupa/get_item_demand*.json"), "items")
               + records(load("data/coupa/list_catalog_items*.json"), "results") + records(dashboards, "demand")}
    today = next((parse_date(doc.get("as_of")) for doc in dashboards if isinstance(doc, dict) and parse_date(doc.get("as_of"))), None)
    if today is None:
        for flow in flows:
            order = flow.get("purchase_order") or {}
            expected, days = parse_date(order.get("expected-delivery")), order.get("days-to-delivery")
            if expected and isinstance(days, int):
                today = expected - timedelta(days=days)
                break
    today = today or date.today()

    if (server, tool) == ("coupa", "reject_invoice"):
        number = str(args.get("invoice_id") or "")
        for flow in flows:
            for invoice in flow.get("invoices") or []:
                if number and number in {str(invoice.get("invoice-number")), str(invoice.get("id"))}:
                    if str(invoice.get("payment-status", "")).lower() == "paid" or invoice.get("status") == "paid":
                        return verdict(False, f"{number} is already paid: recovery belongs to Accounts Payable.")
                    exceeds, detail = over_receipt(flow, invoice)
                    return verdict(exceeds, f"{number} {detail}." if exceeds else f"{number} is within tolerance: {detail}.")
        return verdict(False, f"{number or 'The invoice'} is not in the saved Coupa request-to-pay data.")

    if (server, tool) == ("coupa", "approve_reject"):
        if str(args.get("action", "")).lower() != "reject":
            return verdict(False, "The procurement colleague never approves; only rejections can run on their own.")
        approval = next((item for item in approvals if item.get("id") == args.get("approvable_id")), None)
        if approval is None:
            return verdict(False, "That approval is not in the saved Coupa approvals.")
        if approval.get("type") != "Invoice":
            return verdict(False, f"{approval.get('id')} is a {str(approval.get('type')).lower()} approval: it belongs to its approver.")
        for flow in flows:
            if flow.get("service-now-request") != approval.get("service-now-request"):
                continue
            for invoice in flow.get("invoices") or []:
                if str(invoice.get("invoice-number")) in str(approval.get("title", "")) or len(flow.get("invoices") or []) == 1:
                    exceeds, detail = over_receipt(flow, invoice)
                    return verdict(exceeds, f"{approval.get('id')}: {detail}." if exceeds
                                   else f"{approval.get('id')} is within tolerance: {detail}.")
        return verdict(False, f"The invoice behind {approval.get('id')} is not in the saved request-to-pay data.")

    if (server, tool) == ("coupa", "create_requisition"):
        lines = args.get("line_items") or []
        if not isinstance(lines, list) or not lines:
            return verdict(False, "A requisition needs line items.")
        earlier = {line.get("item-id") for item in used if item.get("action") == "coupa.create_requisition"
                   for line in ((item.get("args") or {}).get("line_items") or []) if isinstance(line, dict)}
        total = 0.0
        for line in lines:
            item = catalog.get(line.get("item-id")) if isinstance(line, dict) else None
            if item is None:
                return verdict(False, "Every line must be a catalogue item saved in the workspace.")
            if not item.get("contracted"):
                return verdict(False, f"{item.get('name')} is not a contracted item.")
            if line.get("item-id") in earlier:
                return verdict(False, f"{item.get('name')} was already requisitioned in this close (one per item per month).")
            quantity = line.get("quantity")
            if not isinstance(quantity, int) or quantity <= 0:
                return verdict(False, "Quantities must be whole numbers.")
            list_price = money(item.get("unit-price"))
            price = money(line.get("unit-price")) or list_price
            if price > list_price:
                return verdict(False, f"{gbp(price)} is above the catalogue price of {gbp(list_price)}.")
            supplier_id = line.get("supplier-id") or item.get("supplier-id")
            supplier = suppliers.get(supplier_id)
            if not supplier:
                return verdict(False, f"Supplier {supplier_id} is not in the saved Coupa supplier data.")
            problems = []
            if not (supplier.get("preferred") or supplier.get("tier") in {"strategic", "preferred"}):
                problems.append("not preferred")
            if supplier.get("risk") != "low":
                problems.append(f"risk {supplier.get('risk')}")
            expires = parse_date((supplier.get("contract") or {}).get("expires"))
            if not expires or (expires - today).days < CONTRACT_MIN_DAYS:
                problems.append(f"contract ends {expires}")
            metrics = supplier.get("metrics") or {}
            if (metrics.get("on_time_rate") or 0) < MIN_ON_TIME:
                problems.append(f"on-time {metrics.get('on_time_rate')}%")
            if (metrics.get("defect_rate") if isinstance(metrics.get("defect_rate"), (int, float)) else 99) > MAX_DEFECTS:
                problems.append(f"defects {metrics.get('defect_rate')}%")
            if problems:
                return verdict(False, f"{supplier.get('name')} is not an eligible source ({', '.join(problems)}).")
            if supplier_id != item.get("supplier-id"):
                evidenced = any(
                    ((flow.get("purchase_order") or {}).get("supplier-id") == supplier_id
                     and parse_date((flow.get("purchase_order") or {}).get("created-at"))
                     and (today - parse_date(flow["purchase_order"]["created-at"])).days <= ALTERNATIVE_WINDOW_DAYS
                     and any(entry.get("item-id") == item.get("id") and money(entry.get("unit-price")) <= list_price
                             for entry in flow["purchase_order"].get("lines") or []))
                    for flow in flows)
                if not evidenced:
                    return verdict(False, f"{supplier.get('name')} has not supplied {item.get('name')} on a recent PO at catalogue price.")
            total += quantity * price
        if total > AUTONOMY_LIMIT:
            return verdict(False, f"{gbp(total)} is above the £15,000 limit for requisitions raised without approval.")
        return verdict(True, f"{gbp(total)} of contracted items from an eligible source.")

    if (server, tool) == ("servicenow", "create_incident"):
        if not str(args.get("short_description", "")).startswith("Month-end P2P follow-ups"):
            return verdict(False, "Only the month-end P2P follow-up ticket may be raised without approval.")
        if any(item.get("action") == "servicenow.create_incident" for item in used):
            return verdict(False, "One follow-up ticket per close has already been raised.")
        return verdict(True, "The single month-end follow-up ticket.")

    return verdict(False, "This action is not pre-approved for the procurement month-end close.")


if __name__ == "__main__":
    sys.exit(main())
