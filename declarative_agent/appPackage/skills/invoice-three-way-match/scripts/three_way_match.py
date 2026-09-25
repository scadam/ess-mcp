"""Three-way match Coupa invoices against their purchase order lines and goods received.

Usage: python three_way_match.py input.json      (or pipe the JSON on stdin)

Input is either a list of invoices:
  [{"invoice", "invoice_id", "status", "payment_status", "billed", "currency", "po", "supplier",
    "lines": [{"item", "ordered_qty", "received_qty", "unit_price"}]}]
or the raw get_servicenow_coupa_flow result ({"flows": [...]}) or a single flow.
Prints JSON with one result per invoice, a summary and a Markdown table. Standard library only.
"""

from __future__ import annotations

import json
import re
import sys

ABSOLUTE_TOLERANCE = 250.0
RELATIVE_TOLERANCE = 0.02
SYMBOLS = {"GBP": "£", "USD": "$", "EUR": "€"}


def money(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^0-9.\-]", "", str(value or ""))
    try:
        return float(text) if text not in {"", "-", "."} else 0.0
    except ValueError:
        return 0.0


def quantity(value) -> float:
    return money(value)


def from_flows(data) -> list[dict]:
    flows = data.get("flows") if isinstance(data, dict) and isinstance(data.get("flows"), list) else [data]
    invoices = []
    for flow in flows:
        if not isinstance(flow, dict):
            continue
        order = flow.get("purchase_order") or {}
        lines = [{"item": line.get("description") or line.get("item-id"), "ordered_qty": line.get("quantity"),
                  "received_qty": line.get("received"), "unit_price": line.get("unit-price")}
                 for line in order.get("lines") or [] if isinstance(line, dict)]
        for invoice in flow.get("invoices") or []:
            if not isinstance(invoice, dict):
                continue
            invoices.append({
                "invoice": invoice.get("invoice-number"), "invoice_id": str(invoice.get("id") or ""),
                "status": invoice.get("status"), "payment_status": invoice.get("payment-status"),
                "billed": invoice.get("total"), "currency": (invoice.get("currency") or {}).get("code", "GBP"),
                "po": order.get("po-number") or invoice.get("po-number"),
                "supplier": (invoice.get("supplier") or {}).get("name"), "lines": lines,
                "received": order.get("received-value") if not lines else None,
                "ordered": order.get("total") if not lines else None,
            })
    return invoices


def normalise(data) -> list[dict]:
    if isinstance(data, dict) and ("flows" in data or "invoices" in data or "purchase_order" in data):
        return from_flows(data)
    if isinstance(data, list) and data and isinstance(data[0], dict) and "purchase_order" in data[0]:
        return from_flows({"flows": data})
    if isinstance(data, dict):
        return [data]
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def match(entry: dict) -> dict:
    currency = str(entry.get("currency") or "GBP").upper()
    symbol = SYMBOLS.get(currency, currency + " ")
    lines = entry.get("lines") or []
    ordered = sum(quantity(line.get("ordered_qty")) * money(line.get("unit_price")) for line in lines) if lines \
        else money(entry.get("ordered"))
    received = sum(quantity(line.get("received_qty")) * money(line.get("unit_price")) for line in lines) if lines \
        else money(entry.get("received"))
    billed = money(entry.get("billed"))
    tolerance = max(ABSOLUTE_TOLERANCE, RELATIVE_TOLERANCE * billed)
    outstanding = []
    for line in lines:
        short = quantity(line.get("ordered_qty")) - quantity(line.get("received_qty"))
        if short > 0:
            outstanding.append({"item": line.get("item"), "quantity": short,
                                "value": round(short * money(line.get("unit_price")), 2)})
    paid = "paid" in {str(entry.get("status") or "").lower(), str(entry.get("payment_status") or "").lower()}
    po = entry.get("po") or "the purchase order"
    pending = ", ".join(f"{item['quantity']:g} × {item['item']}" for item in outstanding)

    def fmt(amount: float) -> str:
        return f"{symbol}{amount:,.2f}"

    if ordered and billed - ordered > tolerance:
        verdict, action, owner = "Billed above the order", "reject", "Procurement"
        reason = (f"Billed {fmt(billed)} against an order value of {fmt(ordered)} on {po}. "
                  "Please re-issue the invoice at the purchase order price and quantity.")
    elif billed - received > tolerance:
        verdict = "Paid ahead of receipt" if paid else "Billed ahead of receipt"
        action, owner = ("recover", "Accounts Payable") if paid else ("reject", "Procurement")
        reason = (f"Billed {fmt(billed)} against {fmt(received)} received on {po}"
                  + (f" ({pending} outstanding)" if pending else "") + ". "
                  + ("Request a credit note for the undelivered goods." if paid
                     else "Please issue a credit note or re-bill once the rest is delivered."))
    elif received - billed > tolerance:
        verdict, action, owner = "Under-billed", "note", "Accounts Payable"
        reason = f"Billed {fmt(billed)} but {fmt(received)} has been received on {po}; a further invoice may follow."
    else:
        verdict, action, owner = "Matches", "approve", "Accounts Payable"
        reason = f"Billed {fmt(billed)} is within {fmt(tolerance)} of the {fmt(received)} received on {po}."
    return {"invoice": entry.get("invoice"), "invoice_id": entry.get("invoice_id") or entry.get("invoice"),
            "supplier": entry.get("supplier"), "po": entry.get("po"), "status": entry.get("status"),
            "currency": currency, "billed": round(billed, 2), "ordered": round(ordered, 2), "received": round(received, 2),
            "variance": round(billed - received, 2), "tolerance": round(tolerance, 2), "verdict": verdict,
            "action": action, "owner": owner, "reason": reason, "outstanding": outstanding}


def main(argv: list[str]) -> int:
    try:
        raw = open(argv[0], encoding="utf-8").read() if argv else sys.stdin.read()
        data = json.loads(raw)
    except (OSError, ValueError) as error:
        print(json.dumps({"error": f"Could not read the input JSON: {error}"}))
        return 2
    results = [match(entry) for entry in normalise(data)]
    if not results:
        print(json.dumps({"error": "No invoices found in the input."}))
        return 2
    rows = ["| Invoice | Supplier | PO | Billed | Received | Variance | Verdict | Action |", "|---|---|---|---|---|---|---|---|"]
    for item in results:
        symbol = SYMBOLS.get(item["currency"], item["currency"] + " ")
        rows.append(f"| {item['invoice']} | {item['supplier'] or ''} | {item['po'] or ''} | {symbol}{item['billed']:,.2f} | "
                    f"{symbol}{item['received']:,.2f} | {symbol}{item['variance']:,.2f} | {item['verdict']} | {item['action']} |")
    summary = {"invoices": len(results), "matching": sum(item["action"] == "approve" for item in results),
               "to_reject": sum(item["action"] == "reject" for item in results),
               "to_recover": sum(item["action"] == "recover" for item in results),
               "exposure": round(sum(max(0.0, item["variance"]) for item in results if item["action"] in {"reject", "recover"}), 2)}
    print(json.dumps({"summary": summary, "results": results, "table": "\n".join(rows)}, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
