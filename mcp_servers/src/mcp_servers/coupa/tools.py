"""Coupa MCP tool definitions - mocked procurement data for demos.

The Coupa demo models employee ServiceNow requests that become requisitions,
purchase orders, supplier orders, receipts, and invoices in Coupa. The data is
static, but shaped like operational procurement data so category managers can
inspect IT hardware spend, supplier performance, fulfilment risk, and demand.
"""

from __future__ import annotations

import copy
from collections import Counter, defaultdict
from datetime import date, datetime
from typing import Any, Dict, Iterable

from fastmcp import Context

from ..logging import get_logger

LOGGER = get_logger(__name__)
TODAY = date(2026, 5, 6)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _days_between(start: str | None, end: str | None = None) -> int | None:
    start_date = _parse_date(start)
    end_date = _parse_date(end) if end else TODAY
    if not start_date or not end_date:
        return None
    return (end_date - start_date).days


def _float_money(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    return float(str(value).replace(",", ""))


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _mock_response(data: Any) -> Dict[str, Any]:
    return copy.deepcopy(data) if isinstance(data, dict) else {"results": copy.deepcopy(data)}


_MOCK_SUPPLIERS = [
    {"id": "SUP-4101", "number": "SUP-4101", "name": "TechDirect UK Ltd", "status": "active", "category": "Laptop hardware", "tier": "strategic", "risk": "low", "preferred": True, "contract": {"id": "CTR-IT-2026-01", "expires": "2027-03-31", "rebate": "4.0%"}, "address": {"street": "10 Thames Innovation Park", "city": "London", "postcode": "E14 9TS", "country": "GB"}, "contact": {"name": "Priya Raman", "email": "priya.raman@techdirect.example.com", "phone": "+44 20 5555 0140"}, "tax-id": "GB441230010", "bank": {"name": "Barclays", "account": "****4182", "sort-code": "20-00-00"}, "metrics": {"on_time_rate": 94, "defect_rate": 1.1, "avg_lead_days": 6, "open_orders": 6, "open_value": 97840.00}},
    {"id": "SUP-4102", "number": "SUP-4102", "name": "Apple Business Reseller UK", "status": "active", "category": "Mobile devices", "tier": "strategic", "risk": "medium", "preferred": True, "contract": {"id": "CTR-MOB-2025-04", "expires": "2026-12-31", "rebate": "2.5%"}, "address": {"street": "One New Change", "city": "London", "postcode": "EC4M 9AF", "country": "GB"}, "contact": {"name": "Liam Brooks", "email": "liam.brooks@apple-reseller.example.com", "phone": "+44 20 5555 0182"}, "tax-id": "GB441230011", "bank": {"name": "HSBC", "account": "****2199", "sort-code": "40-00-00"}, "metrics": {"on_time_rate": 88, "defect_rate": 0.7, "avg_lead_days": 9, "open_orders": 7, "open_value": 76430.00}},
    {"id": "SUP-4103", "number": "SUP-4103", "name": "Dell Premier Solutions", "status": "active", "category": "Developer workstations", "tier": "preferred", "risk": "low", "preferred": True, "contract": {"id": "CTR-DEV-2026-02", "expires": "2028-01-31", "rebate": "5.0%"}, "address": {"street": "Bracknell Business Park", "city": "Bracknell", "postcode": "RG12 1LF", "country": "GB"}, "contact": {"name": "Hannah Patel", "email": "hannah.patel@dell-premier.example.com", "phone": "+44 1344 555 010"}, "tax-id": "GB441230012", "bank": {"name": "NatWest", "account": "****7721", "sort-code": "60-00-00"}, "metrics": {"on_time_rate": 97, "defect_rate": 0.9, "avg_lead_days": 5, "open_orders": 4, "open_value": 112660.00}},
    {"id": "SUP-4104", "number": "SUP-4104", "name": "OfficeWorks Managed Supply", "status": "active", "category": "Office equipment", "tier": "approved", "risk": "low", "preferred": False, "contract": {"id": "CTR-OFF-2025-11", "expires": "2026-09-30", "rebate": "1.5%"}, "address": {"street": "42 Distribution Way", "city": "Birmingham", "postcode": "B24 8DW", "country": "GB"}, "contact": {"name": "Marcus Lee", "email": "marcus.lee@officeworks.example.com", "phone": "+44 121 555 0190"}, "tax-id": "GB441230013", "bank": {"name": "Lloyds", "account": "****0921", "sort-code": "30-00-00"}, "metrics": {"on_time_rate": 91, "defect_rate": 1.8, "avg_lead_days": 4, "open_orders": 5, "open_value": 18520.00}},
    {"id": "SUP-4105", "number": "SUP-4105", "name": "Insight Enterprise Technology", "status": "active", "category": "Accessories", "tier": "preferred", "risk": "medium", "preferred": True, "contract": {"id": "CTR-ACC-2025-07", "expires": "2026-06-30", "rebate": "3.0%"}, "address": {"street": "6 City Exchange", "city": "Manchester", "postcode": "M1 3LD", "country": "GB"}, "contact": {"name": "Sofia Evans", "email": "sofia.evans@insight.example.com", "phone": "+44 161 555 0162"}, "tax-id": "GB441230014", "bank": {"name": "Santander", "account": "****5528", "sort-code": "09-00-00"}, "metrics": {"on_time_rate": 84, "defect_rate": 2.4, "avg_lead_days": 8, "open_orders": 8, "open_value": 33475.00}},
]

_MOCK_CATALOG = [
    {"id": "IT-IPHONE-15", "name": "iPhone 15 128GB", "category": "Mobile devices", "subcategory": "Phones", "unit-price": "699.00", "currency": "GBP", "supplier-id": "SUP-4102", "supplier": "Apple Business Reseller UK", "lead-time-days": 7, "contracted": True, "stock": 84, "monthly-demand": 48},
    {"id": "IT-IPHONE-15P", "name": "iPhone 15 Pro 256GB", "category": "Mobile devices", "subcategory": "Phones", "unit-price": "999.00", "currency": "GBP", "supplier-id": "SUP-4102", "supplier": "Apple Business Reseller UK", "lead-time-days": 11, "contracted": True, "stock": 28, "monthly-demand": 34},
    {"id": "IT-STD-LAPTOP", "name": "Standard Laptop", "category": "Laptop hardware", "subcategory": "Laptops", "unit-price": "1180.00", "currency": "GBP", "supplier-id": "SUP-4101", "supplier": "TechDirect UK Ltd", "lead-time-days": 5, "contracted": True, "stock": 132, "monthly-demand": 72},
    {"id": "IT-DEV-LAPTOP", "name": "Developer Laptop", "category": "Developer workstations", "subcategory": "Laptops", "unit-price": "2450.00", "currency": "GBP", "supplier-id": "SUP-4103", "supplier": "Dell Premier Solutions", "lead-time-days": 6, "contracted": True, "stock": 42, "monthly-demand": 31},
    {"id": "IT-MON-34", "name": "34 inch USB-C Monitor", "category": "Office equipment", "subcategory": "Monitors", "unit-price": "510.00", "currency": "GBP", "supplier-id": "SUP-4104", "supplier": "OfficeWorks Managed Supply", "lead-time-days": 4, "contracted": True, "stock": 76, "monthly-demand": 25},
    {"id": "IT-DOCK-USBC", "name": "USB-C Docking Station", "category": "Accessories", "subcategory": "Docks", "unit-price": "189.00", "currency": "GBP", "supplier-id": "SUP-4105", "supplier": "Insight Enterprise Technology", "lead-time-days": 8, "contracted": True, "stock": 39, "monthly-demand": 68},
    {"id": "IT-HEADSET", "name": "Teams Certified Headset", "category": "Accessories", "subcategory": "Audio", "unit-price": "96.00", "currency": "GBP", "supplier-id": "SUP-4105", "supplier": "Insight Enterprise Technology", "lead-time-days": 6, "contracted": True, "stock": 110, "monthly-demand": 45},
    {"id": "IT-KBDMOUSE", "name": "Keyboard and Mouse Bundle", "category": "Office equipment", "subcategory": "Peripherals", "unit-price": "64.00", "currency": "GBP", "supplier-id": "SUP-4104", "supplier": "OfficeWorks Managed Supply", "lead-time-days": 3, "contracted": True, "stock": 214, "monthly-demand": 83},
    {"id": "IT-IPAD-AIR", "name": "iPad Air Wi-Fi 256GB", "category": "Mobile devices", "subcategory": "Tablets", "unit-price": "729.00", "currency": "GBP", "supplier-id": "SUP-4102", "supplier": "Apple Business Reseller UK", "lead-time-days": 9, "contracted": True, "stock": 21, "monthly-demand": 18},
    {"id": "IT-CONF-PHONE", "name": "Teams Desk Phone", "category": "Office equipment", "subcategory": "Phones", "unit-price": "275.00", "currency": "GBP", "supplier-id": "SUP-4104", "supplier": "OfficeWorks Managed Supply", "lead-time-days": 5, "contracted": False, "stock": 36, "monthly-demand": 12},
]

_PO_SEEDS = [
    (30201, "PO-2026-1048", "issued", "SUP-4101", "2026-04-12", "2026-05-09", "REQ0012458", "RITM0018374", "Maya Singh", "Finance Operations", "London", "Laptop hardware", [("IT-STD-LAPTOP", "Standard Laptop", 18, "1180.00", 12), ("IT-DOCK-USBC", "USB-C Docking Station", 18, "189.00", 12)]),
    (30202, "PO-2026-1051", "partially_received", "SUP-4102", "2026-04-14", "2026-05-04", "REQ0012491", "RITM0018442", "Noah Bennett", "Sales EMEA", "Manchester", "Mobile devices", [("IT-IPHONE-15", "iPhone 15 128GB", 42, "699.00", 38), ("IT-HEADSET", "Teams Certified Headset", 42, "96.00", 42)]),
    (30203, "PO-2026-1055", "issued", "SUP-4103", "2026-04-17", "2026-05-13", "REQ0012533", "RITM0018528", "Aisha Khan", "Platform Engineering", "Bristol", "Developer workstations", [("IT-DEV-LAPTOP", "Developer Laptop", 24, "2450.00", 0), ("IT-MON-34", "34 inch USB-C Monitor", 24, "510.00", 0), ("IT-DOCK-USBC", "USB-C Docking Station", 24, "189.00", 0)]),
    (30204, "PO-2026-1062", "closed", "SUP-4104", "2026-04-02", "2026-04-12", "REQ0012380", "RITM0018221", "Oliver Taylor", "People Team", "Edinburgh", "Office equipment", [("IT-MON-34", "34 inch USB-C Monitor", 12, "510.00", 12), ("IT-KBDMOUSE", "Keyboard and Mouse Bundle", 20, "64.00", 20)]),
    (30205, "PO-2026-1065", "supplier_acknowledged", "SUP-4105", "2026-04-29", "2026-05-16", "REQ0012707", "RITM0018792", "Grace Williams", "Customer Success", "Leeds", "Accessories", [("IT-DOCK-USBC", "USB-C Docking Station", 60, "189.00", 0), ("IT-HEADSET", "Teams Certified Headset", 75, "96.00", 0), ("IT-KBDMOUSE", "Keyboard and Mouse Bundle", 75, "64.00", 0)]),
    (30206, "PO-2026-1070", "issued", "SUP-4102", "2026-05-01", "2026-05-17", "REQ0012750", "RITM0018878", "Leo Martin", "Executive Office", "London", "Mobile devices", [("IT-IPHONE-15P", "iPhone 15 Pro 256GB", 16, "999.00", 0), ("IT-IPAD-AIR", "iPad Air Wi-Fi 256GB", 8, "729.00", 0)]),
    (30207, "PO-2026-1074", "pending_supplier_ack", "SUP-4101", "2026-05-03", "2026-05-12", "REQ0012794", "RITM0018960", "Ethan Brown", "Risk and Compliance", "Cardiff", "Laptop hardware", [("IT-STD-LAPTOP", "Standard Laptop", 35, "1180.00", 0)]),
]


def _supplier_ref(supplier_id: str) -> dict:
    supplier = next(s for s in _MOCK_SUPPLIERS if s["id"] == supplier_id)
    return {"name": supplier["name"], "number": supplier["number"]}


def _build_po(seed: tuple) -> dict:
    po_id, po_number, status, supplier_id, created, expected, sn_req, ritm, employee, department, location, category, lines = seed
    line_items = [{"item-id": item_id, "description": desc, "quantity": qty, "unit-price": unit, "received": received} for item_id, desc, qty, unit, received in lines]
    total = sum(qty * _float_money(unit) for _, _, qty, unit, _ in lines)
    received_value = sum(received * _float_money(unit) for _, _, _, unit, received in lines)
    days_to_delivery = _days_between(TODAY.isoformat(), expected)
    delivery_risk = "late" if days_to_delivery is not None and days_to_delivery < 0 and status != "closed" else "at_risk" if days_to_delivery is not None and days_to_delivery <= 3 and status != "closed" else "on_track"
    return {"id": po_id, "po-number": po_number, "status": status, "total": _money(total), "currency": {"code": "GBP"}, "supplier-id": supplier_id, "supplier": _supplier_ref(supplier_id), "created-at": created, "expected-delivery": expected, "service-now-request": sn_req, "requested-item": ritm, "employee": employee, "department": department, "location": location, "ship-to": {"city": location, "country": "GB"}, "category": category, "line-count": len(line_items), "lines": line_items, "open-value": _money(max(total - received_value, 0)), "received-value": _money(received_value), "days-open": _days_between(created), "days-to-delivery": days_to_delivery, "delivery-risk": delivery_risk}


_MOCK_POS = [_build_po(seed) for seed in _PO_SEEDS]

_MOCK_REQUISITIONS = [
    {"id": 9000 + idx, "requisition-number": f"REQ-C-2026-{9000 + idx}", "title": f"{po['department']} hardware fulfilment - {po['service-now-request']}", "status": "approved" if po["status"] != "pending_supplier_ack" else "pending_supplier_ack", "requester": po["employee"], "created-at": po["created-at"], "service-now-request": po["service-now-request"], "requested-item": po["requested-item"], "department": po["department"], "location": po["location"], "total": po["total"], "currency": {"code": "GBP"}, "line-items": copy.deepcopy(po["lines"]), "po-number": po["po-number"]}
    for idx, po in enumerate(_MOCK_POS, start=1)
]

_MOCK_RECEIPTS = [
    {"id": 7001, "receipt-number": "RCPT-2026-7001", "po-number": "PO-2026-1048", "receipt-date": "2026-05-02", "status": "partial", "received-by": "maya.singh@example.com", "line-items": [{"description": "Standard Laptop", "quantity": 12, "unit": "EA"}, {"description": "USB-C Docking Station", "quantity": 12, "unit": "EA"}]},
    {"id": 7002, "receipt-number": "RCPT-2026-7002", "po-number": "PO-2026-1051", "receipt-date": "2026-05-04", "status": "partial", "received-by": "noah.bennett@example.com", "line-items": [{"description": "iPhone 15 128GB", "quantity": 38, "unit": "EA"}, {"description": "Teams Certified Headset", "quantity": 42, "unit": "EA"}]},
    {"id": 7003, "receipt-number": "RCPT-2026-7003", "po-number": "PO-2026-1062", "receipt-date": "2026-04-11", "status": "received", "received-by": "oliver.taylor@example.com", "line-items": [{"description": "34 inch USB-C Monitor", "quantity": 12, "unit": "EA"}, {"description": "Keyboard and Mouse Bundle", "quantity": 20, "unit": "EA"}]},
]

_MOCK_INVOICES = [
    {"id": 50412, "invoice-number": "INV-2026-0412", "status": "approved", "total": "24,642.00", "currency": {"code": "GBP"}, "supplier": {"name": "TechDirect UK Ltd", "number": "SUP-4101"}, "invoice-date": "2026-05-03", "due-date": "2026-06-02", "payment-status": "Scheduled", "po-number": "PO-2026-1048"},
    {"id": 50413, "invoice-number": "INV-2026-0417", "status": "pending_approval", "total": "33,390.00", "currency": {"code": "GBP"}, "supplier": {"name": "Apple Business Reseller UK", "number": "SUP-4102"}, "invoice-date": "2026-05-05", "due-date": "2026-06-04", "payment-status": "Not Paid", "po-number": "PO-2026-1051"},
    {"id": 50414, "invoice-number": "INV-2026-0398", "status": "paid", "total": "7,400.00", "currency": {"code": "GBP"}, "supplier": {"name": "OfficeWorks Managed Supply", "number": "SUP-4104"}, "invoice-date": "2026-04-12", "due-date": "2026-05-12", "payment-status": "Paid", "po-number": "PO-2026-1062"},
]

_MOCK_APPROVALS = [
    {"id": "APR-601", "type": "Requisition", "title": "Developer Laptop wave - Platform Engineering", "requester": "aisha.khan@example.com", "total": "75,576.00", "currency": "GBP", "submitted-at": "2026-04-17", "status": "pending", "risk": "high value", "service-now-request": "REQ0012533"},
    {"id": "APR-602", "type": "Invoice", "title": "INV-2026-0417 - Apple Business Reseller UK", "requester": "accounts.payable@example.com", "total": "33,390.00", "currency": "GBP", "submitted-at": "2026-05-05", "status": "pending", "risk": "quantity mismatch", "service-now-request": "REQ0012491"},
    {"id": "APR-603", "type": "Purchase Order", "title": "PO-2026-1074 - Standard Laptop replenishment", "requester": "ethan.brown@example.com", "total": "41,300.00", "currency": "GBP", "submitted-at": "2026-05-03", "status": "pending", "risk": "supplier acknowledgement overdue", "service-now-request": "REQ0012794"},
]


def _orders_for(filters: dict[str, Any]) -> list[dict]:
    results = _MOCK_POS
    if filters.get("status"):
        results = [p for p in results if p.get("status") == filters["status"]]
    if filters.get("category"):
        category = str(filters["category"]).lower()
        results = [p for p in results if category in str(p.get("category", "")).lower()]
    if filters.get("supplier_id"):
        results = [p for p in results if p.get("supplier-id") == filters["supplier_id"]]
    if filters.get("location"):
        location = str(filters["location"]).lower()
        results = [p for p in results if location in str(p.get("location", "")).lower()]
    return copy.deepcopy(results)


def _summarize_orders(orders: Iterable[dict]) -> dict:
    order_list = list(orders)
    value = sum(_float_money(po.get("total")) for po in order_list)
    open_value = sum(_float_money(po.get("open-value")) for po in order_list)
    return {"order_count": len(order_list), "total_value": _money(value), "open_value": _money(open_value), "at_risk_orders": sum(1 for po in order_list if po.get("delivery-risk") in {"late", "at_risk"}), "by_status": dict(Counter(po.get("status", "unknown") for po in order_list)), "by_category": dict(Counter(po.get("category", "Uncategorised") for po in order_list)), "by_supplier": dict(Counter(po.get("supplier", {}).get("name", "Unknown") for po in order_list))}


def _item_demand() -> list[dict]:
    quantities: dict[str, int] = defaultdict(int)
    open_quantities: dict[str, int] = defaultdict(int)
    values: dict[str, float] = defaultdict(float)
    for po in _MOCK_POS:
        for line in po.get("lines", []):
            item_id = line["item-id"]
            qty = int(line.get("quantity", 0))
            received = int(line.get("received", 0))
            quantities[item_id] += qty
            open_quantities[item_id] += max(qty - received, 0)
            values[item_id] += qty * _float_money(line.get("unit-price"))
    demand = []
    for item in _MOCK_CATALOG:
        monthly = int(item.get("monthly-demand", 0))
        stock = int(item.get("stock", 0))
        coverage = round(stock / monthly, 1) if monthly else None
        demand.append({**copy.deepcopy(item), "ordered_quantity": quantities[item["id"]], "open_quantity": open_quantities[item["id"]], "ordered_value": _money(values[item["id"]]), "stock_coverage_months": coverage, "risk": "stockout" if coverage is not None and coverage < 1 else "watch" if coverage is not None and coverage < 2 else "healthy"})
    return demand


def _supplier_rollup() -> list[dict]:
    rollup = []
    for supplier in _MOCK_SUPPLIERS:
        orders = [po for po in _MOCK_POS if po.get("supplier-id") == supplier["id"]]
        rollup.append({**copy.deepcopy(supplier), "order_summary": _summarize_orders(orders), "orders": copy.deepcopy(orders)})
    return rollup


async def tool_get_invoice_status(invoice_number: str, ctx: Context | None = None) -> dict:
    match = next((i for i in _MOCK_INVOICES if i["invoice-number"] == invoice_number), _MOCK_INVOICES[0])
    result = copy.deepcopy(match)
    result["invoice-number"] = invoice_number
    return result


async def tool_get_po_status(po_number: str, ctx: Context | None = None) -> dict:
    match = next((p for p in _MOCK_POS if p["po-number"] == po_number), _MOCK_POS[0])
    result = copy.deepcopy(match)
    result["po-number"] = po_number
    return result


async def tool_reject_invoice(invoice_id: str, reason: str = "", ctx: Context | None = None) -> dict:
    return {"status": "rejected", "invoice-id": invoice_id, "reason": reason, "actioned-at": TODAY.isoformat()}


async def tool_close_purchase_order(po_id: str, reason: str = "", ctx: Context | None = None) -> dict:
    return {"status": "closed", "po-id": po_id, "reason": reason, "actioned-at": TODAY.isoformat()}


async def tool_list_receipts(po_number: str | None = None, ctx: Context | None = None) -> dict:
    results = [r for r in _MOCK_RECEIPTS if r.get("po-number") == po_number] if po_number else _MOCK_RECEIPTS
    return _mock_response(results)


async def tool_prepare_create_receipt(po_number: str, ctx: Context | None = None) -> dict:
    match = next((p for p in _MOCK_POS if p["po-number"] == po_number), _MOCK_POS[0])
    return {**copy.deepcopy(match), "_widget_hint": "Goods receipt form ready."}


async def tool_create_receipt(po_number: str, line_items: list[dict], receipt_date: str, ctx: Context | None = None) -> dict:
    return {"status": "created", "id": 7099, "receipt-number": "RCPT-2026-7099", "po-number": po_number, "receipt-date": receipt_date, "line-items": line_items}


async def tool_list_requisitions(status: str | None = None, ctx: Context | None = None) -> dict:
    results = [r for r in _MOCK_REQUISITIONS if r.get("status") == status] if status else _MOCK_REQUISITIONS
    return _mock_response(results)


async def tool_prepare_create_requisition(ctx: Context | None = None) -> dict:
    return {"_widget_hint": "Requisition form ready.", "catalog_items": copy.deepcopy(_MOCK_CATALOG), "preferred_suppliers": copy.deepcopy(_MOCK_SUPPLIERS)}


async def tool_create_requisition(title: str, line_items: list[dict], requester: str | None = None, ctx: Context | None = None) -> dict:
    total = sum(_float_money(item.get("unit-price", item.get("unit_price", 0))) * int(item.get("quantity", 1)) for item in line_items)
    return {"status": "created", "id": 9099, "requisition-number": "REQ-C-2026-9099", "title": title, "requester": requester, "total": _money(total), "currency": {"code": "GBP"}, "line-items": line_items}


async def tool_update_requisition(requisition_id: str, updates: dict, ctx: Context | None = None) -> dict:
    return {"status": "updated", "id": requisition_id, "updates": updates}


async def tool_list_catalog_items(query: str | None = None, category: str | None = None, ctx: Context | None = None) -> dict:
    results = _MOCK_CATALOG
    if query:
        q = query.lower()
        results = [c for c in results if q in c["name"].lower() or q in c["category"].lower() or q in c["supplier"].lower()]
    if category:
        cat = category.lower()
        results = [c for c in results if cat in c["category"].lower()]
    return {"results": copy.deepcopy(results), "demand": _item_demand()}


async def tool_order_catalog_item(catalog_item_id: str, quantity: int = 1, deliver_to: str | None = None, ctx: Context | None = None) -> dict:
    item = next((c for c in _MOCK_CATALOG if c["id"] == catalog_item_id), _MOCK_CATALOG[0])
    return {"status": "ordered", "requisition-id": 9100, "requisition-number": "REQ-C-2026-9100", "source": "ServiceNow catalog request", "item": item["name"], "item-id": item["id"], "quantity": quantity, "supplier": item["supplier"], "deliver-to": deliver_to}


async def tool_list_suppliers(query: str | None = None, ctx: Context | None = None) -> dict:
    results = _supplier_rollup()
    if query:
        q = query.lower()
        results = [s for s in results if q in s["name"].lower() or q in s.get("category", "").lower()]
    return _mock_response(results)


async def tool_get_supplier(supplier_id: str, ctx: Context | None = None) -> dict:
    suppliers = _supplier_rollup()
    return copy.deepcopy(next((s for s in suppliers if s["id"] == supplier_id), suppliers[0]))


async def tool_update_supplier_address(supplier_id: str, address: dict, ctx: Context | None = None) -> dict:
    return {"status": "updated", "supplier-id": supplier_id, "address": address}


async def tool_update_supplier_bank(supplier_id: str, bank_details: dict, ctx: Context | None = None) -> dict:
    return {"status": "updated", "supplier-id": supplier_id, "bank": bank_details}


async def tool_register_supplier(name: str, address: dict, contact: dict, tax_id: str | None = None, ctx: Context | None = None) -> dict:
    return {"status": "registered", "id": "SUP-4999", "name": name, "address": address, "contact": contact, "tax-id": tax_id, "risk": "pending_review"}


async def tool_transfer_purchase_order(po_id: str, new_owner: str, reason: str = "", ctx: Context | None = None) -> dict:
    return {"status": "transferred", "po-id": po_id, "new-owner": new_owner, "reason": reason}


async def tool_list_approvals(ctx: Context | None = None) -> dict:
    return _mock_response(_MOCK_APPROVALS)


async def tool_approve_reject(approvable_id: str, action: str, comment: str = "", ctx: Context | None = None) -> dict:
    status_word = "approved" if action == "approve" else "rejected"
    return {"status": status_word, "approvable-id": approvable_id, "comment": comment, "actioned-at": TODAY.isoformat()}


async def tool_get_category_manager_dashboard(category: str | None = None, supplier_id: str | None = None, ctx: Context | None = None) -> dict:
    orders = _orders_for({"category": category, "supplier_id": supplier_id})
    demand = [d for d in _item_demand() if not category or category.lower() in d.get("category", "").lower()]
    alerts = []
    for po in orders:
        if po.get("delivery-risk") == "late":
            alerts.append({"severity": "high", "title": f"{po['po-number']} is past expected delivery", "detail": f"{po['supplier']['name']} order for {po['department']} is overdue."})
        elif po.get("delivery-risk") == "at_risk":
            alerts.append({"severity": "medium", "title": f"{po['po-number']} due within 3 days", "detail": f"Check supplier acknowledgement and receipt plan for {po['location']}."})
    for item in demand:
        if item.get("risk") == "stockout":
            alerts.append({"severity": "high", "title": f"{item['name']} stock coverage below one month", "detail": f"Open demand is {item['open_quantity']} units with {item['stock']} in stock."})
    return {"success": True, "as_of": TODAY.isoformat(), "category": category or "All IT hardware", "summary": _summarize_orders(orders), "orders": orders, "supplier_performance": _supplier_rollup(), "demand": demand, "alerts": alerts[:8]}


async def tool_list_it_hardware_orders(status: str | None = None, category: str | None = None, supplier_id: str | None = None, location: str | None = None, limit: int = 50, ctx: Context | None = None) -> dict:
    orders = _orders_for({"status": status, "category": category, "supplier_id": supplier_id, "location": location})
    safe_limit = max(1, min(int(limit), 100))
    return {"success": True, "results": orders[:safe_limit], "summary": _summarize_orders(orders), "filters": {"status": status, "category": category, "supplier_id": supplier_id, "location": location}, "categories": sorted({po["category"] for po in _MOCK_POS}), "locations": sorted({po["location"] for po in _MOCK_POS})}


async def tool_get_supplier_performance(supplier_id: str | None = None, ctx: Context | None = None) -> dict:
    suppliers = _supplier_rollup()
    if supplier_id:
        suppliers = [s for s in suppliers if s["id"] == supplier_id]
    total_value = sum(_float_money(s.get("order_summary", {}).get("total_value")) for s in suppliers)
    open_value = sum(_float_money(s.get("order_summary", {}).get("open_value")) for s in suppliers)
    return {
        "success": True,
        "suppliers": suppliers,
        "summary": {
            "supplier_count": len(suppliers),
            "strategic_suppliers": sum(1 for s in suppliers if s.get("tier") == "strategic"),
            "at_risk_suppliers": sum(1 for s in suppliers if s.get("risk") != "low"),
            "total_value": _money(total_value),
            "open_value": _money(open_value),
            "by_supplier": {s["name"]: s.get("metrics", {}).get("on_time_rate", 0) for s in suppliers},
        },
    }


async def tool_get_item_demand(item_id: str | None = None, category: str | None = None, ctx: Context | None = None) -> dict:
    demand = _item_demand()
    if item_id:
        demand = [d for d in demand if d["id"] == item_id]
    if category:
        demand = [d for d in demand if category.lower() in d.get("category", "").lower()]
    return {"success": True, "items": demand, "summary": {"item_count": len(demand), "stockout_risk": sum(1 for d in demand if d.get("risk") == "stockout"), "watch_items": sum(1 for d in demand if d.get("risk") == "watch")}}


async def tool_get_servicenow_coupa_flow(request_number: str | None = None, ctx: Context | None = None) -> dict:
    orders = _MOCK_POS if not request_number else [po for po in _MOCK_POS if po.get("service-now-request") == request_number or po.get("requested-item") == request_number]
    flows = []
    for po in orders:
        receipts = [copy.deepcopy(r) for r in _MOCK_RECEIPTS if r.get("po-number") == po["po-number"]]
        invoices = [copy.deepcopy(i) for i in _MOCK_INVOICES if i.get("po-number") == po["po-number"]]
        blocked_reason = None
        if po.get("delivery-risk") == "late":
            blocked_reason = "Overdue delivery"
        elif po.get("status") == "pending_supplier_ack":
            blocked_reason = "Waiting for supplier acknowledgement"
        elif not receipts and po.get("status") != "closed":
            blocked_reason = "Goods receipt not posted"
        flows.append({"service-now-request": po["service-now-request"], "requested-item": po["requested-item"], "employee": po["employee"], "department": po["department"], "location": po["location"], "status": po["status"], "supplier": po["supplier"], "category": po["category"], "total": po["total"], "open-value": po["open-value"], "blocked-reason": blocked_reason or "Progressing", "requisition": next((r for r in _MOCK_REQUISITIONS if r.get("po-number") == po["po-number"]), None), "purchase_order": copy.deepcopy(po), "receipts": receipts, "invoices": invoices})
    summary = _summarize_orders(orders)
    summary.update({"flow_count": len(flows), "with_receipts": sum(1 for f in flows if f["receipts"]), "with_invoices": sum(1 for f in flows if f["invoices"]), "blocked_flows": sum(1 for f in flows if f.get("blocked-reason") != "Progressing"), "by_department": dict(Counter(f["department"] for f in flows))})
    return {"success": True, "flows": flows, "summary": summary}


COUPA_TOOL_SPECS: list[dict] = [
    {"name": "get_invoice_status", "summary": "Get invoice payment status from Coupa by invoice number (mocked).", "func": tool_get_invoice_status, "annotations": {"readOnlyHint": True}, "meta": {"openai/outputTemplate": "ui://widget/coupa-invoice-status.html", "openai/toolInvocation/invoking": "Checking invoice status...", "openai/toolInvocation/invoked": "Invoice status ready."}},
    {"name": "get_po_status", "summary": "Get purchase order status from Coupa by PO number (mocked).", "func": tool_get_po_status, "annotations": {"readOnlyHint": True}, "meta": {"openai/outputTemplate": "ui://widget/coupa-po-status.html", "openai/toolInvocation/invoking": "Checking PO status...", "openai/toolInvocation/invoked": "PO status ready."}},
    {"name": "reject_invoice", "summary": "Reject an invoice in Coupa (mocked).", "func": tool_reject_invoice, "annotations": {"readOnlyHint": False}, "meta": {"openai/outputTemplate": "ui://widget/coupa-confirm-action.html", "openai/toolInvocation/invoking": "Rejecting invoice...", "openai/toolInvocation/invoked": "Invoice rejected."}},
    {"name": "close_purchase_order", "summary": "Close a purchase order in Coupa (mocked).", "func": tool_close_purchase_order, "annotations": {"readOnlyHint": False}, "meta": {"openai/outputTemplate": "ui://widget/coupa-confirm-action.html", "openai/toolInvocation/invoking": "Closing PO...", "openai/toolInvocation/invoked": "PO closed."}},
    {"name": "list_receipts", "summary": "List goods receipts from Coupa, optionally filtered by PO (mocked).", "func": tool_list_receipts, "annotations": {"readOnlyHint": True}, "meta": {"openai/outputTemplate": "ui://widget/coupa-receipt-list.html", "openai/toolInvocation/invoking": "Loading receipts...", "openai/toolInvocation/invoked": "Receipts loaded."}},
    {"name": "prepare_create_receipt", "summary": "Show the goods receipt creation form for a PO (mocked).", "func": tool_prepare_create_receipt, "annotations": {"readOnlyHint": True}, "meta": {"openai/outputTemplate": "ui://widget/coupa-create-receipt.html", "openai/toolInvocation/invoking": "Preparing receipt form...", "openai/toolInvocation/invoked": "Form ready."}},
    {"name": "create_receipt", "summary": "Post a goods receipt in Coupa (mocked).", "func": tool_create_receipt, "annotations": {"readOnlyHint": False}, "meta": {"openai/toolInvocation/invoking": "Creating goods receipt...", "openai/toolInvocation/invoked": "Receipt created."}},
    {"name": "list_requisitions", "summary": "List purchase requisitions from Coupa (mocked).", "func": tool_list_requisitions, "annotations": {"readOnlyHint": True}, "meta": {"openai/outputTemplate": "ui://widget/coupa-requisition-list.html", "openai/toolInvocation/invoking": "Loading requisitions...", "openai/toolInvocation/invoked": "Requisitions loaded."}},
    {"name": "prepare_create_requisition", "summary": "Show the purchase requisition creation form (mocked).", "func": tool_prepare_create_requisition, "annotations": {"readOnlyHint": True}, "meta": {"openai/outputTemplate": "ui://widget/coupa-create-requisition.html", "openai/toolInvocation/invoking": "Preparing requisition form...", "openai/toolInvocation/invoked": "Form ready."}},
    {"name": "create_requisition", "summary": "Submit a new purchase requisition in Coupa (mocked).", "func": tool_create_requisition, "annotations": {"readOnlyHint": False}, "meta": {"openai/toolInvocation/invoking": "Creating requisition...", "openai/toolInvocation/invoked": "Requisition created."}},
    {"name": "update_requisition", "summary": "Update an existing purchase requisition in Coupa (mocked).", "func": tool_update_requisition, "annotations": {"readOnlyHint": False}, "meta": {"openai/toolInvocation/invoking": "Updating requisition...", "openai/toolInvocation/invoked": "Requisition updated."}},
    {"name": "list_catalog_items", "summary": "Search the Coupa IT hardware procurement catalog (mocked).", "func": tool_list_catalog_items, "annotations": {"readOnlyHint": True}, "meta": {"openai/outputTemplate": "ui://widget/coupa-catalog-search.html", "openai/toolInvocation/invoking": "Searching catalog...", "openai/toolInvocation/invoked": "Catalog results ready."}},
    {"name": "order_catalog_item", "summary": "Create a Coupa requisition from a catalog item, as if sourced from ServiceNow (mocked).", "func": tool_order_catalog_item, "annotations": {"readOnlyHint": False}, "meta": {"openai/toolInvocation/invoking": "Ordering catalog item...", "openai/toolInvocation/invoked": "Item ordered."}},
    {"name": "list_suppliers", "summary": "Search IT hardware suppliers in Coupa with performance rollups (mocked).", "func": tool_list_suppliers, "annotations": {"readOnlyHint": True}, "meta": {"openai/outputTemplate": "ui://widget/coupa-supplier-list.html", "openai/toolInvocation/invoking": "Searching suppliers...", "openai/toolInvocation/invoked": "Suppliers loaded."}},
    {"name": "get_supplier", "summary": "Get supplier details and open order performance from Coupa (mocked).", "func": tool_get_supplier, "annotations": {"readOnlyHint": True}, "meta": {"openai/outputTemplate": "ui://widget/coupa-supplier-profile.html", "openai/toolInvocation/invoking": "Loading supplier profile...", "openai/toolInvocation/invoked": "Supplier profile ready."}},
    {"name": "update_supplier_address", "summary": "Update a supplier's address in Coupa (mocked).", "func": tool_update_supplier_address, "annotations": {"readOnlyHint": False}, "meta": {"openai/toolInvocation/invoking": "Updating supplier address...", "openai/toolInvocation/invoked": "Address updated."}},
    {"name": "update_supplier_bank", "summary": "Update a supplier's bank details in Coupa (mocked).", "func": tool_update_supplier_bank, "annotations": {"readOnlyHint": False}, "meta": {"openai/toolInvocation/invoking": "Updating bank details...", "openai/toolInvocation/invoked": "Bank details updated."}},
    {"name": "register_supplier", "summary": "Register and onboard a new IT hardware supplier in Coupa (mocked).", "func": tool_register_supplier, "annotations": {"readOnlyHint": False}, "meta": {"openai/outputTemplate": "ui://widget/coupa-supplier-registration.html", "openai/toolInvocation/invoking": "Registering supplier...", "openai/toolInvocation/invoked": "Supplier registered."}},
    {"name": "transfer_purchase_order", "summary": "Transfer a purchase order to a new owner in Coupa (mocked).", "func": tool_transfer_purchase_order, "annotations": {"readOnlyHint": False}, "meta": {"openai/toolInvocation/invoking": "Transferring PO...", "openai/toolInvocation/invoked": "PO transferred."}},
    {"name": "list_approvals", "summary": "List pending approval items in Coupa (mocked).", "func": tool_list_approvals, "annotations": {"readOnlyHint": True}, "meta": {"openai/outputTemplate": "ui://widget/coupa-approval-list.html", "openai/toolInvocation/invoking": "Loading approvals...", "openai/toolInvocation/invoked": "Approvals loaded."}},
    {"name": "approve_reject", "summary": "Approve or reject a pending approval in Coupa (mocked). Set action to 'approve' or 'reject'.", "func": tool_approve_reject, "annotations": {"readOnlyHint": False}, "meta": {"openai/toolInvocation/invoking": "Processing approval...", "openai/toolInvocation/invoked": "Approval processed."}},
    {"name": "get_category_manager_dashboard", "summary": "Category manager dashboard for ServiceNow-sourced IT hardware orders in Coupa (mocked).", "func": tool_get_category_manager_dashboard, "annotations": {"readOnlyHint": True}, "meta": {"openai/outputTemplate": "ui://widget/coupa-category-dashboard.html", "openai/toolInvocation/invoking": "Building category dashboard...", "openai/toolInvocation/invoked": "Dashboard ready."}},
    {"name": "list_it_hardware_orders", "summary": "List ServiceNow-originated IT hardware purchase orders in Coupa with category, supplier, and delivery filters (mocked).", "func": tool_list_it_hardware_orders, "annotations": {"readOnlyHint": True}, "meta": {"openai/outputTemplate": "ui://widget/coupa-hardware-order-list.html", "openai/toolInvocation/invoking": "Loading hardware orders...", "openai/toolInvocation/invoked": "Hardware orders ready."}},
    {"name": "get_supplier_performance", "summary": "Supplier performance dashboard for Coupa IT hardware suppliers (mocked).", "func": tool_get_supplier_performance, "annotations": {"readOnlyHint": True}, "meta": {"openai/outputTemplate": "ui://widget/coupa-supplier-performance.html", "openai/toolInvocation/invoking": "Loading supplier performance...", "openai/toolInvocation/invoked": "Supplier performance ready."}},
    {"name": "get_item_demand", "summary": "Item demand and stock coverage for phones, laptops, accessories, and office equipment in Coupa (mocked).", "func": tool_get_item_demand, "annotations": {"readOnlyHint": True}, "meta": {"openai/outputTemplate": "ui://widget/coupa-item-demand.html", "openai/toolInvocation/invoking": "Loading item demand...", "openai/toolInvocation/invoked": "Item demand ready."}},
    {"name": "get_servicenow_coupa_flow", "summary": "Trace ServiceNow employee requests through Coupa requisitions, POs, receipts, and invoices (mocked).", "func": tool_get_servicenow_coupa_flow, "annotations": {"readOnlyHint": True}, "meta": {"openai/outputTemplate": "ui://widget/coupa-request-flow.html", "openai/toolInvocation/invoking": "Tracing request flow...", "openai/toolInvocation/invoked": "Request flow ready."}},
]
