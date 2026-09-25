"""Coupa Core API–shaped simulator state and tools (the one simulated system in this solution).

Objects follow the Coupa Core REST API resources and their JSON conventions: integer ``id``, dasherized keys,
references as nested objects (``supplier``, ``currency``, ``uom``, ``requested-by``), decimals as strings and
ISO-8601 timestamps. Status values and actions mirror /api/invoices (dispute, withdraw_dispute,
revalidate_tolerances), /api/purchase_orders (order-lines, acknowledged-flag, version), /api/receiving_transactions
and /api/approvals. State is in memory and changes are visible to every later read, including the older
composite demo views, so a colleague's fix is reflected everywhere.
"""
from __future__ import annotations

import copy
import itertools
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastmcp import Context

from ..logging import get_logger
from . import tools as legacy

LOGGER = get_logger(__name__)
PRICE_TOLERANCE_PCT = 2.0
PRICE_TOLERANCE_ABS = 100.0  # Per line, in document currency.
DISPUTE_REASONS = ("INCORRECT_PRICE", "INCORRECT_QUANTITY", "NOT_RECEIVED", "DUPLICATE", "MISSING_PO", "OTHER")
EXCEPTION_STATUSES = ("ap_hold", "pending_receipt", "on_hold", "pending_action")
_ids = itertools.count(91000)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _dec(value: float) -> str:
    return f"{value:.2f}"


def _user(name: str, email: str) -> Dict[str, Any]:
    first, _, last = name.partition(" ")
    return {"id": zlib.crc32(email.encode()) % 90000 + 1000, "login": email.split("@")[0], "email": email,
            "firstname": first, "lastname": last, "fullname": name}


def _supplier_ref(legacy_id: str) -> Dict[str, Any]:
    supplier = next(item for item in legacy._MOCK_SUPPLIERS if item["id"] == legacy_id)
    return {"id": int(legacy_id.split("-")[1]), "name": supplier["name"], "number": supplier["number"]}


# ── Caldova second-line scenarios, added to the shared demo data so every view agrees ──
_START = _now()
_SCENARIO_POS = [
    (30208, "PO-2026-1082", "supplier_acknowledged", "SUP-4101", (_START - timedelta(days=21)).date().isoformat(),
     (_START - timedelta(days=7)).date().isoformat(), "REQ0013120", "RITM0019304", "Colin Ballinger",
     "Sourcing and Procurement", "London", "Laptop hardware", [("IT-STD-LAPTOP", "Standard Laptop", 20, "1180.00", 20)]),
    (30209, "PO-2026-1085", "partially_received", "SUP-4105", (_START - timedelta(days=16)).date().isoformat(),
     (_START - timedelta(days=9)).date().isoformat(), "REQ0013157", "RITM0019355", "Karin Blair",
     "Distribution & Cold Chain Logistics", "Manchester", "Accessories",
     [("IT-HEADSET", "Teams Certified Headset", 40, "96.00", 32)]),
]
REQUESTERS = {
    "Colin Ballinger": "colinb@caldova74201480.onmicrosoft.com",
    "Karin Blair": "karinb@caldova74201480.onmicrosoft.com",
}
for _seed in _SCENARIO_POS:
    if not any(po["id"] == _seed[0] for po in legacy._MOCK_POS):
        legacy._MOCK_POS.append(legacy._build_po(_seed))
if not any(receipt["id"] == 7004 for receipt in legacy._MOCK_RECEIPTS):
    legacy._MOCK_RECEIPTS.extend([
        {"id": 7004, "receipt-number": "RCPT-2026-7004", "po-number": "PO-2026-1082",
         "receipt-date": (_START - timedelta(days=6)).date().isoformat(), "status": "received",
         "received-by": REQUESTERS["Colin Ballinger"], "line-items": [{"description": "Standard Laptop", "quantity": 20, "unit": "EA"}]},
        {"id": 7005, "receipt-number": "RCPT-2026-7005", "po-number": "PO-2026-1085",
         "receipt-date": (_START - timedelta(days=8)).date().isoformat(), "status": "partial",
         "received-by": REQUESTERS["Karin Blair"], "line-items": [{"description": "Teams Certified Headset", "quantity": 32, "unit": "EA"}]},
    ])
if not any(invoice["id"] == 50430 for invoice in legacy._MOCK_INVOICES):
    legacy._MOCK_INVOICES.extend([
        {"id": 50430, "invoice-number": "INV-TD-88213", "status": "ap_hold", "total": "24,240.00", "currency": {"code": "GBP"},
         "supplier": {"name": "TechDirect UK Ltd", "number": "SUP-4101"}, "invoice-date": (_START - timedelta(days=4)).date().isoformat(),
         "due-date": (_START + timedelta(days=26)).date().isoformat(), "payment-status": "Not Paid", "po-number": "PO-2026-1082"},
        {"id": 50431, "invoice-number": "INV-INS-4471", "status": "pending_receipt", "total": "3,840.00", "currency": {"code": "GBP"},
         "supplier": {"name": "Insight Enterprise Technology", "number": "SUP-4105"}, "invoice-date": (_START - timedelta(days=3)).date().isoformat(),
         "due-date": (_START + timedelta(days=27)).date().isoformat(), "payment-status": "Not Paid", "po-number": "PO-2026-1085"},
    ])
_INVOICE_LINES = {  # invoice id -> [(po line number, description, quantity billed, unit price billed)]
    50412: [(1, "Standard Laptop", 12, 1180.00), (2, "USB-C Docking Station", 12, 189.00)],
    50413: [(1, "iPhone 15 128GB", 42, 699.00), (2, "Teams Certified Headset", 42, 96.00)],
    50414: [(1, "34 inch USB-C Monitor", 12, 510.00), (2, "Keyboard and Mouse Bundle", 20, 64.00)],
    50430: [(1, "Standard Laptop", 20, 1212.00)],
    50431: [(1, "Teams Certified Headset", 40, 96.00)],
}

# ── native state ──
STATE: Dict[str, Any] = {"orders": {}, "invoices": {}, "receipts": [], "comments": [], "approvals": {},
                         "supplier_information": {}}


def _order_lines(po: Dict[str, Any]) -> List[Dict[str, Any]]:
    lines = []
    for number, line in enumerate(po["lines"], start=1):
        price = legacy._float_money(line["unit-price"])
        lines.append({"id": po["id"] * 10 + number, "line-num": number, "description": line["description"],
                      "item": {"id": line["item-id"], "name": line["description"]}, "quantity": _dec(line["quantity"]),
                      "price": _dec(price), "total": _dec(price * line["quantity"]), "uom": {"code": "EA"},
                      "received": _dec(line.get("received", 0)), "need-by-date": po["expected-delivery"],
                      "receipt-required": True})
    return lines


def _build_state() -> None:
    for po in legacy._MOCK_POS:
        requester = REQUESTERS.get(po["employee"], f"{po['employee'].lower().replace(' ', '.')}@example.com")
        acknowledged = po["status"] in {"supplier_acknowledged", "partially_received", "closed"}
        created = f"{po['created-at']}T09:00:00+00:00"
        STATE["orders"][po["id"]] = {
            "id": po["id"], "po-number": po["po-number"], "status": "closed" if po["status"] == "closed" else "issued",
            "version": 1, "acknowledged-flag": acknowledged, "acknowledged-at": created if acknowledged else None,
            "invoice-stop": False, "supplier": _supplier_ref(po["supplier-id"]), "currency": {"code": "GBP"},
            "requester": _user(po["employee"], requester), "ship-to-address": {"city": po["location"], "country": {"code": "GB"}},
            "payment-term": {"code": "Net 30"}, "created-at": created, "updated-at": created,
            "order-lines": _order_lines(po), "exported": False, "transmission-status": "sent_via_cxml"}
    for invoice in legacy._MOCK_INVOICES:
        po = next(item for item in STATE["orders"].values() if item["po-number"] == invoice["po-number"])
        lines = []
        for index, (line_num, description, quantity, price) in enumerate(_INVOICE_LINES[invoice["id"]], start=1):
            order_line = po["order-lines"][line_num - 1]
            lines.append({"id": invoice["id"] * 10 + index, "line-num": index, "description": description,
                          "quantity": _dec(quantity), "price": _dec(price), "total": _dec(quantity * price),
                          "uom": {"code": "EA"}, "order-line-id": order_line["id"], "order-header-num": po["po-number"],
                          "po-line-num": line_num, "type": "InvoiceQuantityLine"})
        created = f"{invoice['invoice-date']}T08:30:00+00:00"
        native = {
            "id": invoice["id"], "invoice-number": invoice["invoice-number"], "status": invoice["status"],
            "invoice-date": invoice["invoice-date"], "created-at": created, "updated-at": created,
            "supplier": _supplier_ref(invoice["supplier"]["number"]), "currency": {"code": "GBP"},
            "invoice-lines": lines, "gross-total": _dec(sum(float(line["total"]) for line in lines)),
            "payment-term": {"code": "Net 30"}, "net-due-date": invoice["due-date"],
            "paid": invoice["status"] == "paid", "requested-by": po["requester"], "tolerance-failures": None,
            "failed-tolerances": [], "dispute-reasons": [], "comments": [], "approvals": []}
        if native["status"] == "paid":
            native["status"], native["payment-date"] = "approved", invoice["due-date"]
        STATE["invoices"][invoice["id"]] = native
    for receipt in legacy._MOCK_RECEIPTS:
        po = next(item for item in STATE["orders"].values() if item["po-number"] == receipt["po-number"])
        for entry in receipt["line-items"]:
            line = next(item for item in po["order-lines"] if item["description"] == entry["description"])
            STATE["receipts"].append(_receiving(po, line, entry["quantity"], f"{receipt['receipt-date']}T15:00:00+00:00",
                                                receipt["received-by"]))
    for invoice in STATE["invoices"].values():
        if invoice["status"] in {"ap_hold", "pending_receipt"}:
            _validate(invoice)


def _receiving(po: Dict[str, Any], line: Dict[str, Any], quantity: float, when: str, by: str) -> Dict[str, Any]:
    return {"id": next(_ids), "type": "ReceivingQuantityConsumption", "status": "created", "quantity": _dec(quantity),
            "price": line["price"], "total": _dec(quantity * float(line["price"])), "transaction-date": when,
            "created-at": when, "uom": {"code": "EA"}, "item": line["item"],
            "order-line": {"id": line["id"], "line-num": line["line-num"], "order-header-number": po["po-number"]},
            "created-by": {"email": by}}


def _received(order_line_id: int) -> float:
    return sum(float(item["quantity"]) for item in STATE["receipts"] if item["order-line"]["id"] == order_line_id)


def _billed(order_line_id: int) -> float:
    return sum(float(line["quantity"]) for invoice in STATE["invoices"].values() if invoice["status"] not in {"voided", "disputed", "abandoned"}
               for line in invoice["invoice-lines"] if line["order-line-id"] == order_line_id)


def _order_line(invoice_line: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    for po in STATE["orders"].values():
        for line in po["order-lines"]:
            if line["id"] == invoice_line["order-line-id"]:
                return po, line
    raise KeyError("order line")


def _validate(invoice: Dict[str, Any]) -> None:
    """Three-way match every line: price against the PO within tolerance, quantity billed against received."""
    failures: List[Dict[str, Any]] = []
    for line in invoice["invoice-lines"]:
        po, order_line = _order_line(line)
        po_price, price = float(order_line["price"]), float(line["price"])
        variance = (price - po_price) * float(line["quantity"])
        pct = (price - po_price) / po_price * 100 if po_price else 0.0
        if pct > PRICE_TOLERANCE_PCT or variance > PRICE_TOLERANCE_ABS:
            failures.append({"code": "price_variance", "line-num": line["line-num"], "po-number": po["po-number"],
                             "message": (f"Line {line['line-num']}: billed {line['price']} vs PO {order_line['price']} "
                                         f"(+{pct:.1f}%, {variance:,.2f} over) exceeds the {PRICE_TOLERANCE_PCT:g}% / "
                                         f"{PRICE_TOLERANCE_ABS:,.0f} tolerance")})
        received, billed = _received(order_line["id"]), _billed(order_line["id"])
        if billed > received:
            failures.append({"code": "quantity_not_received", "line-num": line["line-num"], "po-number": po["po-number"],
                             "message": (f"Line {line['line-num']}: {billed:g} billed against PO line "
                                         f"{order_line['line-num']} but only {received:g} received")})
    invoice["failed-tolerances"] = failures
    invoice["tolerance-failures"] = "; ".join(item["message"] for item in failures) or None
    if invoice["status"] in {"disputed", "voided", "approved", "abandoned"}:
        return
    if any(item["code"] == "price_variance" for item in failures):
        invoice["status"] = "ap_hold"
    elif failures:
        invoice["status"] = "pending_receipt"
    else:
        invoice["status"] = "pending_approval"
        if not any(item["status"] == "pending" for item in invoice["approvals"]):
            approval = {"id": next(_ids), "status": "pending", "position": 1, "type": "ManagementHierarchyApproval",
                        "approvable-type": "InvoiceHeader", "approvable-id": invoice["id"],
                        "approver": invoice["requested-by"], "created-at": _stamp(), "note": None}
            invoice["approvals"].append(approval)
            STATE["approvals"][approval["id"]] = approval
    invoice["updated-at"] = _stamp()
    _sync_legacy_invoice(invoice)


def _sync_legacy_invoice(invoice: Dict[str, Any]) -> None:
    for item in legacy._MOCK_INVOICES:
        if item["id"] == invoice["id"]:
            item["status"] = invoice["status"]


def _find_invoice(invoice: str) -> Optional[Dict[str, Any]]:
    value = str(invoice or "").strip()
    for item in STATE["invoices"].values():
        if str(item["id"]) == value or item["invoice-number"].lower() == value.lower():
            return item
    return None


def _find_order(order: str) -> Optional[Dict[str, Any]]:
    value = str(order or "").strip()
    for item in STATE["orders"].values():
        if str(item["id"]) == value or item["po-number"].lower() == value.lower():
            return item
    return None


def _order_view(po: Dict[str, Any]) -> Dict[str, Any]:
    view = copy.deepcopy(po)
    for line in view["order-lines"]:
        line["received"] = _dec(_received(line["id"]))
        line["invoiced"] = _dec(_billed(line["id"]))
    return view


def _comment(object_type: str, object_id: int, text: str, to_supplier: bool) -> Dict[str, Any]:
    comment = {"id": next(_ids), "commentable-type": object_type, "commentable-id": object_id, "comments": text[:2000],
               "to-supplier": to_supplier, "created-at": _stamp(), "created-by": {"login": "autopilot.supply"}}
    STATE["comments"].append(comment)
    return comment


# ── tools ──
async def tool_list_invoices(status: str | None = None, supplier: str | None = None, updated_since: str | None = None,
                             limit: int = 50, offset: int = 0, ctx: Context | None = None) -> Dict[str, Any]:
    """Query invoices like GET /api/invoices: filter by status, supplier name/number and updated-at[gt]; max 50."""
    rows = sorted(STATE["invoices"].values(), key=lambda item: item["updated-at"])
    if status:
        rows = [item for item in rows if item["status"] == status]
    if supplier:
        term = supplier.lower()
        rows = [item for item in rows if term in item["supplier"]["name"].lower() or term == item["supplier"]["number"].lower()]
    if updated_since:
        rows = [item for item in rows if item["updated-at"] > updated_since]
    page = rows[max(0, offset): max(0, offset) + max(1, min(limit, 50))]
    return {"invoices": [copy.deepcopy(item) for item in page], "count": len(page), "total": len(rows)}


async def tool_get_invoice(invoice: str, ctx: Context | None = None) -> Dict[str, Any]:
    """GET /api/invoices/:id — one invoice with lines, tolerance failures, approvals, disputes and comments.

    Args:
        invoice: Coupa invoice id or invoice number.
    """
    item = _find_invoice(invoice)
    if item is None:
        return {"found": False, "error": f"No invoice {invoice!r}."}
    view = copy.deepcopy(item)
    view["comments"] = [c for c in STATE["comments"] if c["commentable-type"] == "InvoiceHeader" and c["commentable-id"] == item["id"]]
    return {"found": True, "invoice": view}


async def tool_dispute_invoice(invoice: str, reason_code: str, comment: str, ctx: Context | None = None) -> Dict[str, Any]:
    """PUT /api/invoices/:id/dispute — move the invoice to disputed and notify the supplier with the reason.

    Args:
        invoice: Invoice id or number.
        reason_code: One of INCORRECT_PRICE, INCORRECT_QUANTITY, NOT_RECEIVED, DUPLICATE, MISSING_PO, OTHER.
        comment: The message the supplier sees.
    """
    item = _find_invoice(invoice)
    if item is None:
        return {"success": False, "error": f"No invoice {invoice!r}."}
    if reason_code not in DISPUTE_REASONS:
        return {"success": False, "error": f"reason_code must be one of {', '.join(DISPUTE_REASONS)}."}
    if item["status"] not in {"pending_approval", "ap_hold", "pending_receipt", "on_hold", "pending_action"}:
        return {"success": False, "error": f"An invoice in status {item['status']} cannot be disputed."}
    item["status"] = "disputed"
    item["dispute-reasons"].append({"code": reason_code, "comment": comment[:2000], "created-at": _stamp()})
    item["updated-at"] = _stamp()
    _comment("InvoiceHeader", item["id"], comment, True)
    _sync_legacy_invoice(item)
    return {"success": True, "invoice-number": item["invoice-number"], "status": item["status"],
            "supplier-notified": item["supplier"]["name"]}


async def tool_withdraw_invoice_dispute(invoice: str, comment: str = "", ctx: Context | None = None) -> Dict[str, Any]:
    """PUT /api/invoices/:id/withdraw_dispute — return a disputed invoice to matching and approval."""
    item = _find_invoice(invoice)
    if item is None or item["status"] != "disputed":
        return {"success": False, "error": "Only a disputed invoice can have its dispute withdrawn."}
    item["status"] = "pending_approval"
    if comment:
        _comment("InvoiceHeader", item["id"], comment, True)
    _validate(item)
    return {"success": True, "status": item["status"], "tolerance-failures": item["tolerance-failures"]}


async def tool_revalidate_invoice_tolerances(invoice: str, ctx: Context | None = None) -> Dict[str, Any]:
    """PUT /api/invoices/:id/revalidate_tolerances — rerun the three-way match after a receipt or PO change."""
    item = _find_invoice(invoice)
    if item is None:
        return {"success": False, "error": f"No invoice {invoice!r}."}
    _validate(item)
    return {"success": True, "status": item["status"], "tolerance-failures": item["tolerance-failures"],
            "failed-tolerances": item["failed-tolerances"]}


async def tool_get_purchase_order(order: str, ctx: Context | None = None) -> Dict[str, Any]:
    """GET /api/purchase_orders/:id — header, order lines with received and invoiced quantities, acknowledgement."""
    po = _find_order(order)
    if po is None:
        return {"found": False, "error": f"No purchase order {order!r}."}
    view = _order_view(po)
    view["comments"] = [c for c in STATE["comments"] if c["commentable-type"] == "OrderHeader" and c["commentable-id"] == po["id"]]
    view["invoices"] = [{"id": inv["id"], "invoice-number": inv["invoice-number"], "status": inv["status"]}
                        for inv in STATE["invoices"].values()
                        if any(line["order-header-num"] == po["po-number"] for line in inv["invoice-lines"])]
    return {"found": True, "purchase-order": view}


async def tool_list_purchase_orders(status: str | None = None, supplier: str | None = None,
                                    acknowledged: bool | None = None, limit: int = 50,
                                    ctx: Context | None = None) -> Dict[str, Any]:
    """Query purchase orders like GET /api/purchase_orders (status, supplier, acknowledged-flag)."""
    rows = list(STATE["orders"].values())
    if status:
        rows = [po for po in rows if po["status"] == status]
    if supplier:
        term = supplier.lower()
        rows = [po for po in rows if term in po["supplier"]["name"].lower() or term == po["supplier"]["number"].lower()]
    if acknowledged is not None:
        rows = [po for po in rows if po["acknowledged-flag"] is acknowledged]
    return {"purchase-orders": [_order_view(po) for po in rows[: max(1, min(limit, 50))]], "count": len(rows)}


async def tool_create_receiving_transaction(order: str, line_num: int, quantity: float, received_by: str,
                                            transaction_date: str = "", ctx: Context | None = None) -> Dict[str, Any]:
    """POST /api/receiving_transactions — record goods received against a PO line, then rematch its invoices.

    Args:
        order: PO number or id.
        line_num: The order line number.
        quantity: Quantity received now (not cumulative).
        received_by: Email of the person confirming receipt.
        transaction_date: ISO date of receipt; defaults to now.
    """
    po = _find_order(order)
    if po is None:
        return {"success": False, "error": f"No purchase order {order!r}."}
    line = next((item for item in po["order-lines"] if item["line-num"] == int(line_num)), None)
    if line is None:
        return {"success": False, "error": f"{po['po-number']} has no line {line_num}."}
    if quantity <= 0 or _received(line["id"]) + quantity > float(line["quantity"]):
        return {"success": False, "error": (f"Receiving {quantity:g} would exceed the ordered {line['quantity']} "
                                            f"({_received(line['id']):g} already received).")}
    when = f"{transaction_date}T12:00:00+00:00" if len(transaction_date) == 10 else (transaction_date or _stamp())
    receipt = _receiving(po, line, quantity, when, received_by)
    STATE["receipts"].append(receipt)
    for legacy_po in legacy._MOCK_POS:
        if legacy_po["id"] == po["id"]:
            legacy_po["lines"][line["line-num"] - 1]["received"] = int(_received(line["id"]))
    po["updated-at"] = _stamp()
    rematched = []
    for invoice in STATE["invoices"].values():
        if any(item["order-line-id"] == line["id"] for item in invoice["invoice-lines"]):
            _validate(invoice)
            rematched.append({"invoice-number": invoice["invoice-number"], "status": invoice["status"],
                              "tolerance-failures": invoice["tolerance-failures"]})
    return {"success": True, "receiving-transaction": receipt, "received-to-date": _dec(_received(line["id"])),
            "invoices-rematched": rematched}


async def tool_list_receiving_transactions(order: str, ctx: Context | None = None) -> Dict[str, Any]:
    """GET /api/receiving_transactions for one purchase order."""
    po = _find_order(order)
    if po is None:
        return {"found": False, "error": f"No purchase order {order!r}."}
    rows = [item for item in STATE["receipts"] if item["order-line"]["order-header-number"] == po["po-number"]]
    return {"found": True, "receiving-transactions": copy.deepcopy(rows), "count": len(rows)}


async def tool_add_comment(object_type: str, object_id: str, text: str, to_supplier: bool = False,
                           ctx: Context | None = None) -> Dict[str, Any]:
    """Add a comment to a purchase order or invoice; to_supplier makes it visible to the supplier in the CSP.

    Args:
        object_type: purchase_order or invoice.
        object_id: PO or invoice number/id.
        text: Comment text.
        to_supplier: Share with the supplier.
    """
    if object_type == "purchase_order":
        target, kind = _find_order(object_id), "OrderHeader"
    elif object_type == "invoice":
        target, kind = _find_invoice(object_id), "InvoiceHeader"
    else:
        return {"success": False, "error": "object_type must be purchase_order or invoice."}
    if target is None:
        return {"success": False, "error": f"No {object_type} {object_id!r}."}
    return {"success": True, "comment": _comment(kind, target["id"], text, bool(to_supplier))}


async def tool_list_invoice_exceptions(updated_since: str = "", ctx: Context | None = None) -> Dict[str, Any]:
    """Invoices held by matching exceptions changed since a watermark (the supply desk's sweep)."""
    records = []
    for item in sorted(STATE["invoices"].values(), key=lambda row: row["updated-at"]):
        if item["status"] not in EXCEPTION_STATUSES or (updated_since and item["updated-at"] <= updated_since):
            continue
        requester = item["requested-by"]
        records.append({"id": str(item["id"]), "number": item["invoice-number"], "version": item["updated-at"],
                        "title": f"Invoice {item['invoice-number']} from {item['supplier']['name']} is {item['status']}: "
                                 f"{item['tolerance-failures'] or 'needs action'}"[:230],
                        "new": True, "updated_by_integration": False,
                        "requester": {"name": requester["fullname"], "email": requester["email"]},
                        "event_id": f"coupa:inv:{item['id']}:{item['updated-at']}"})
    return {"records": records, "count": len(records)}


# ── supplier onboarding: /api/supplier_information (draft → pending_approval → approved | rejected) ──
SIM_SECTIONS = ("information_security", "data_protection", "financial_crime", "financial_standing", "operational_resilience")
SIM_STATUSES = ("draft", "pending_approval", "approved", "rejected")


def _find_sim(record: str) -> Optional[Dict[str, Any]]:
    value = str(record or "").strip().lower()
    for item in STATE["supplier_information"].values():
        if str(item["id"]) == value or item["name"].lower() == value:
            return item
    return None


async def tool_create_supplier_information(name: str, country: str, commodity: str, contact_name: str,
                                           contact_email: str, tax_id: str = "", description: str = "",
                                           handles_personal_data: bool = False, critical_ict_service: bool = False,
                                           ctx: Context | None = None) -> Dict[str, Any]:
    """POST /api/supplier_information — start onboarding a new supplier (status draft) for due diligence.

    Args:
        name: Supplier legal name.
        country: ISO country code of the contracting entity.
        commodity: What the bank will buy (commodity name).
        contact_name: Supplier contact's full name.
        contact_email: Supplier contact's email.
        tax_id: VAT or tax registration number.
        description: The service and the business need.
        handles_personal_data: The supplier will process personal or client data.
        critical_ict_service: The service supports a critical or important function (DORA).
    """
    if not name.strip() or len(country.strip()) != 2 or "@" not in contact_email:
        return {"success": False, "error": "A name, a two-letter country code and a contact email are required."}
    if _find_sim(name) is not None or any(item["name"].lower() == name.strip().lower() for item in legacy._MOCK_SUPPLIERS):
        return {"success": False, "error": f"{name} already exists as a supplier or onboarding request."}
    first, _, last = contact_name.strip().partition(" ")
    record = {
        "id": next(_ids), "name": name.strip()[:120], "display-name": name.strip()[:120], "status": "draft",
        "tax-id": tax_id[:40], "primary-address": {"country": {"code": country.strip().upper()}},
        "primary-contact": {"name-given": first, "name-family": last, "email": contact_email.strip()[:120]},
        "commodity": {"name": commodity[:80]}, "description": description[:2000],
        "custom-fields": {"handles-personal-data": bool(handles_personal_data),
                          "critical-ict-service": bool(critical_ict_service)},
        "due-diligence": {section: None for section in SIM_SECTIONS}, "comments": [], "supplier": None,
        "created-at": _stamp(), "updated-at": _stamp()}
    STATE["supplier_information"][record["id"]] = record
    return {"success": True, "supplier-information": copy.deepcopy(record)}


async def tool_get_supplier_information(record: str, ctx: Context | None = None) -> Dict[str, Any]:
    """GET /api/supplier_information/:id — an onboarding request with its due-diligence sections and status."""
    item = _find_sim(record)
    if item is None:
        return {"found": False, "error": f"No supplier information {record!r}."}
    return {"found": True, "supplier-information": copy.deepcopy(item)}


async def tool_record_due_diligence(record: str, section: str, outcome: str, summary: str, reviewer: str,
                                    ctx: Context | None = None) -> Dict[str, Any]:
    """Record one due-diligence section's outcome on an onboarding request (moves it to pending_approval when all
    sections are complete).

    Args:
        record: Supplier information id or name.
        section: information_security, data_protection, financial_crime, financial_standing or operational_resilience.
        outcome: pass, pass_with_conditions or fail.
        summary: The reviewer's findings and any conditions.
        reviewer: Who gave the outcome.
    """
    item = _find_sim(record)
    if item is None:
        return {"success": False, "error": f"No supplier information {record!r}."}
    if section not in SIM_SECTIONS or outcome not in ("pass", "pass_with_conditions", "fail"):
        return {"success": False, "error": f"section must be one of {', '.join(SIM_SECTIONS)}; outcome pass, "
                                           "pass_with_conditions or fail."}
    if item["status"] in ("approved", "rejected"):
        return {"success": False, "error": f"The request is already {item['status']}."}
    item["due-diligence"][section] = {"outcome": outcome, "summary": summary[:2000], "reviewer": reviewer[:120],
                                      "recorded-at": _stamp()}
    if all(item["due-diligence"].values()):
        item["status"] = "pending_approval"
    item["updated-at"] = _stamp()
    return {"success": True, "status": item["status"],
            "outstanding": [name for name, value in item["due-diligence"].items() if not value]}


async def tool_approve_supplier_information(record: str, comment: str, ctx: Context | None = None) -> Dict[str, Any]:
    """Approve an onboarding request whose due diligence is complete with no failed section; creates the active
    supplier. Args: record (id or name), comment (approval basis and conditions)."""
    item = _find_sim(record)
    if item is None:
        return {"success": False, "error": f"No supplier information {record!r}."}
    if item["status"] != "pending_approval":
        return {"success": False, "error": f"Only a request pending approval can be approved (status {item['status']})."}
    if any(value["outcome"] == "fail" for value in item["due-diligence"].values()):
        return {"success": False, "error": "A due-diligence section failed; the request must be rejected."}
    number = 4100 + len(legacy._MOCK_SUPPLIERS) + 1
    contact = item["primary-contact"]
    supplier = {"id": f"SUP-{number}", "number": f"SUP-{number}", "name": item["name"], "status": "active",
                "category": item["commodity"]["name"], "tier": "approved", "risk": "onboarded", "preferred": False,
                "address": {"country": item["primary-address"]["country"]["code"]}, "tax-id": item["tax-id"],
                "contact": {"name": f"{contact['name-given']} {contact['name-family']}".strip(), "email": contact["email"]}}
    legacy._MOCK_SUPPLIERS.append(supplier)
    item["status"], item["supplier"] = "approved", {"id": number, "name": item["name"], "number": supplier["number"]}
    item["comments"].append({"comments": comment[:2000], "created-at": _stamp(), "created-by": {"login": "autopilot.supply"}})
    item["updated-at"] = _stamp()
    return {"success": True, "status": "approved", "supplier": item["supplier"]}


async def tool_reject_supplier_information(record: str, reason: str, ctx: Context | None = None) -> Dict[str, Any]:
    """Reject an onboarding request with the reason. Args: record (id or name), reason."""
    item = _find_sim(record)
    if item is None or item["status"] in ("approved", "rejected"):
        return {"success": False, "error": "No open supplier information request matches."}
    item["status"] = "rejected"
    item["comments"].append({"comments": reason[:2000], "created-at": _stamp(), "created-by": {"login": "autopilot.supply"}})
    item["updated-at"] = _stamp()
    return {"success": True, "status": "rejected"}



_build_state()

CORE_TOOL_SPECS: list[dict] = [
    {"name": "list_invoices", "func": tool_list_invoices, "annotations": {"readOnlyHint": True},
     "summary": "Query Coupa invoices (GET /api/invoices) by status, supplier and updated-at."},
    {"name": "get_invoice", "func": tool_get_invoice, "annotations": {"readOnlyHint": True},
     "summary": "One Coupa invoice with lines, tolerance failures, approvals, disputes and comments."},
    {"name": "dispute_invoice", "func": tool_dispute_invoice,
     "summary": "Dispute a Coupa invoice with a reason code; the supplier is notified (PUT /api/invoices/:id/dispute)."},
    {"name": "withdraw_invoice_dispute", "func": tool_withdraw_invoice_dispute,
     "summary": "Withdraw an invoice dispute and return it to matching and approval."},
    {"name": "revalidate_invoice_tolerances", "func": tool_revalidate_invoice_tolerances,
     "summary": "Rerun an invoice's three-way match after a receipt or PO change."},
    {"name": "get_purchase_order", "func": tool_get_purchase_order, "annotations": {"readOnlyHint": True},
     "summary": "One Coupa purchase order: lines with received and invoiced quantities, acknowledgement, invoices."},
    {"name": "list_purchase_orders", "func": tool_list_purchase_orders, "annotations": {"readOnlyHint": True},
     "summary": "Query Coupa purchase orders by status, supplier and supplier acknowledgement."},
    {"name": "create_receiving_transaction", "func": tool_create_receiving_transaction,
     "summary": "Record goods received against a PO line (POST /api/receiving_transactions) and rematch its invoices."},
    {"name": "list_receiving_transactions", "func": tool_list_receiving_transactions, "annotations": {"readOnlyHint": True},
     "summary": "Receiving transactions recorded against one purchase order."},
    {"name": "add_comment", "func": tool_add_comment,
     "summary": "Comment on a PO or invoice; to_supplier shares it with the supplier in the Coupa Supplier Portal."},
    {"name": "list_invoice_exceptions", "func": tool_list_invoice_exceptions, "annotations": {"readOnlyHint": True},
     "summary": "Invoices held by matching exceptions changed since a watermark (reconciliation sweep)."},
    {"name": "create_supplier_information", "func": tool_create_supplier_information,
     "summary": "Start onboarding a new supplier (POST /api/supplier_information, status draft) for due diligence."},
    {"name": "get_supplier_information", "func": tool_get_supplier_information, "annotations": {"readOnlyHint": True},
     "summary": "A supplier onboarding request with its due-diligence sections and status."},
    {"name": "record_due_diligence", "func": tool_record_due_diligence,
     "summary": "Record one due-diligence section's outcome and reviewer on a supplier onboarding request."},
    {"name": "approve_supplier_information", "func": tool_approve_supplier_information,
     "summary": "Approve a supplier onboarding request with complete due diligence; creates the active supplier."},
    {"name": "reject_supplier_information", "func": tool_reject_supplier_information,
     "summary": "Reject a supplier onboarding request with the reason."},
]
