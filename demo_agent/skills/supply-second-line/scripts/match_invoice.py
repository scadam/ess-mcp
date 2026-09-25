"""Recompute the three-way match for a Coupa invoice and say which exception it is and what clears it.

Usage: match_invoice.py <invoice json> <order json> [<receipts json>]
Accepts the tool results as saved (with or without the "invoice" / "purchase-order" wrapper).
Prints and writes analysis/match.json. Standard library only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PCT, ABS = 2.0, 100.0


def _load(path: str, key: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get(key, data) if isinstance(data, dict) else {}


def _num(value) -> float:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return 0.0


def match(invoice: dict, order: dict, receipts: dict | None = None) -> dict:
    lines = {int(line.get("line-num") or 0): line for line in order.get("order-lines", [])}
    received_by_line: dict[int, float] = {}
    for item in (receipts or {}).get("receiving-transactions", []):
        number = int((item.get("order-line") or {}).get("line-num") or 0)
        received_by_line[number] = received_by_line.get(number, 0.0) + _num(item.get("quantity"))
    results, exceptions = [], []
    for line in invoice.get("invoice-lines", []):
        number = int(line.get("po-line-num") or line.get("line-num") or 0)
        po_line = lines.get(number, {})
        billed_price, po_price = _num(line.get("price")), _num(po_line.get("price"))
        billed_qty = _num(line.get("quantity"))
        received = received_by_line[number] if number in received_by_line else _num(po_line.get("received"))
        variance = round((billed_price - po_price) * billed_qty, 2)
        pct = round((billed_price - po_price) / po_price * 100, 2) if po_price else 0.0
        row = {"line": number, "description": line.get("description", ""), "billed_price": billed_price,
               "order_price": po_price, "price_variance_total": variance, "price_variance_pct": pct,
               "billed_qty": billed_qty, "ordered_qty": _num(po_line.get("quantity")), "received_qty": received}
        if po_price and (pct > PCT or variance > ABS):
            exceptions.append({"line": number, "type": "price_variance",
                               "clears_with": "credit note or corrected invoice at the order price (dispute "
                                              "INCORRECT_PRICE), or an order amendment backed by an agreed increase",
                               "question": f"Was a price of {billed_price:,.2f} (order {po_price:,.2f}) agreed?"})
        if billed_qty > received:
            short = billed_qty - received
            exceptions.append({"line": number, "type": "quantity_not_received", "shortfall": short,
                               "clears_with": f"a receipt for {short:g} once the requester confirms they arrived, or "
                                              "a supplier credit for the shortfall",
                               "question": f"Have the remaining {short:g} of {row['description'] or 'the items'} "
                                           "arrived, and on what date?"})
        results.append(row)
    return {"invoice": invoice.get("invoice-number"), "status": invoice.get("status"),
            "order": order.get("po-number"), "requester": invoice.get("requested-by"),
            "supplier": (invoice.get("supplier") or {}).get("name"), "lines": results,
            "exceptions": exceptions, "matched": not exceptions}


def main() -> None:
    if len(sys.argv) not in (3, 4):
        print("usage: match_invoice.py <invoice json> <order json> [<receipts json>]")
        sys.exit(2)
    for path in sys.argv[1:]:
        if not Path(path).is_file():
            print(json.dumps({"error": f"{path} is not in the workspace; save the tool result first."}))
            sys.exit(1)
    receipts = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8")) if len(sys.argv) == 4 else None
    result = match(_load(sys.argv[1], "invoice"), _load(sys.argv[2], "purchase-order"), receipts)
    Path("analysis").mkdir(exist_ok=True)
    Path("analysis/match.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
