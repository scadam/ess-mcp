"""Coupa MCP tool definitions — ALL MOCKED.

No Coupa sandbox is available. Every tool returns realistic canned data
matching real Coupa REST API response shapes from docs.coupa.com.
The mock layer is structured so it can be swapped for real API calls
if a Coupa instance becomes available.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any, Dict

from fastmcp import Context

from ..logging import get_logger

LOGGER = get_logger(__name__)


# ── Mock data store ─────────────────────────────────────────────────

_MOCK_INVOICES = [
    {
        "id": 50412,
        "invoice-number": "INV-2026-0312",
        "status": "pending_approval",
        "total": "12,450.00",
        "currency": {"code": "GBP"},
        "supplier": {"name": "Acme Industrial Ltd", "number": "SUP-1042"},
        "invoice-date": "2026-03-15",
        "due-date": "2026-04-14",
        "payment-status": "Not Paid",
        "po-number": "PO-2026-0847",
    },
    {
        "id": 50413,
        "invoice-number": "INV-2026-0288",
        "status": "approved",
        "total": "3,200.00",
        "currency": {"code": "GBP"},
        "supplier": {"name": "Global Parts Co", "number": "SUP-2091"},
        "invoice-date": "2026-03-01",
        "due-date": "2026-03-31",
        "payment-status": "Paid",
        "po-number": "PO-2026-0801",
    },
]

_MOCK_POS = [
    {
        "id": 30201,
        "po-number": "PO-2026-0847",
        "status": "issued",
        "total": "25,000.00",
        "currency": {"code": "GBP"},
        "supplier": {"name": "Acme Industrial Ltd", "number": "SUP-1042"},
        "created-at": "2026-02-20",
        "ship-to": {"city": "London", "country": "GB"},
        "line-count": 3,
    },
    {
        "id": 30202,
        "po-number": "PO-2026-0801",
        "status": "closed",
        "total": "3,200.00",
        "currency": {"code": "GBP"},
        "supplier": {"name": "Global Parts Co", "number": "SUP-2091"},
        "created-at": "2026-01-15",
        "ship-to": {"city": "Manchester", "country": "GB"},
        "line-count": 1,
    },
]

_MOCK_RECEIPTS = [
    {
        "id": 7001,
        "po-number": "PO-2026-0847",
        "receipt-date": "2026-03-10",
        "status": "received",
        "received-by": "jsmith@example.com",
        "line-items": [
            {"description": "Widget A", "quantity": 100, "unit": "EA"},
            {"description": "Widget B", "quantity": 50, "unit": "EA"},
        ],
    },
]

_MOCK_REQUISITIONS = [
    {
        "id": 9001,
        "title": "Office Supplies Q2 2026",
        "status": "pending_approval",
        "requester": "jsmith@example.com",
        "created-at": "2026-03-18",
        "total": "1,250.00",
        "currency": {"code": "GBP"},
        "line-items": [
            {"description": "A4 Paper (5000 sheets)", "quantity": 10, "unit-price": "25.00"},
            {"description": "Printer Toner Black", "quantity": 5, "unit-price": "200.00"},
        ],
    },
]

_MOCK_CATALOG = [
    {
        "id": "CAT-001",
        "name": "A4 Paper (5000 sheets)",
        "category": "Office Supplies",
        "unit-price": "25.00",
        "currency": "GBP",
        "supplier": "Office World Ltd",
    },
    {
        "id": "CAT-002",
        "name": "Printer Toner Black (HP 58A)",
        "category": "Office Supplies",
        "unit-price": "200.00",
        "currency": "GBP",
        "supplier": "Tech Supplies Inc",
    },
    {
        "id": "CAT-003",
        "name": "Ergonomic Office Chair",
        "category": "Furniture",
        "unit-price": "450.00",
        "currency": "GBP",
        "supplier": "Comfort Works Ltd",
    },
]

_MOCK_SUPPLIERS = [
    {
        "id": "SUP-1042",
        "name": "Acme Industrial Ltd",
        "status": "active",
        "address": {"street": "42 Industrial Way", "city": "Birmingham", "postcode": "B1 1AA", "country": "GB"},
        "contact": {"name": "Jane Doe", "email": "jane@acme.example.com", "phone": "+44 121 555 0100"},
        "tax-id": "GB123456789",
        "bank": {"name": "Barclays", "account": "****4321", "sort-code": "20-00-00"},
    },
    {
        "id": "SUP-2091",
        "name": "Global Parts Co",
        "status": "active",
        "address": {"street": "10 Trade Rd", "city": "Leeds", "postcode": "LS1 1AA", "country": "GB"},
        "contact": {"name": "Bob Smith", "email": "bob@globalparts.example.com", "phone": "+44 113 555 0200"},
        "tax-id": "GB987654321",
        "bank": {"name": "HSBC", "account": "****8765", "sort-code": "40-00-00"},
    },
]

_MOCK_APPROVALS = [
    {
        "id": "APR-501",
        "type": "Requisition",
        "title": "Office Supplies Q2 2026",
        "requester": "jsmith@example.com",
        "total": "1,250.00",
        "currency": "GBP",
        "submitted-at": "2026-03-18",
        "status": "pending",
    },
    {
        "id": "APR-502",
        "type": "Invoice",
        "title": "INV-2026-0312 — Acme Industrial Ltd",
        "requester": "accounts@example.com",
        "total": "12,450.00",
        "currency": "GBP",
        "submitted-at": "2026-03-16",
        "status": "pending",
    },
]


def _mock_response(data: Any) -> Dict[str, Any]:
    """Wrap mock data in a standard Coupa-like API envelope."""
    return copy.deepcopy(data) if isinstance(data, dict) else {"results": copy.deepcopy(data)}


# ── Tool handlers ───────────────────────────────────────────────────

async def tool_get_invoice_status(
    invoice_number: str,
    ctx: Context | None = None,
) -> dict:
    """Get invoice payment status from Coupa (mocked)."""
    match = next((i for i in _MOCK_INVOICES if i["invoice-number"] == invoice_number), _MOCK_INVOICES[0])
    result = copy.deepcopy(match)
    result["invoice-number"] = invoice_number
    return result


async def tool_get_po_status(
    po_number: str,
    ctx: Context | None = None,
) -> dict:
    """Get PO status from Coupa (mocked)."""
    match = next((p for p in _MOCK_POS if p["po-number"] == po_number), _MOCK_POS[0])
    result = copy.deepcopy(match)
    result["po-number"] = po_number
    return result


async def tool_reject_invoice(
    invoice_id: str,
    reason: str = "",
    ctx: Context | None = None,
) -> dict:
    """Reject an invoice in Coupa (mocked)."""
    return {"status": "rejected", "invoice-id": invoice_id, "reason": reason}


async def tool_close_purchase_order(
    po_id: str,
    reason: str = "",
    ctx: Context | None = None,
) -> dict:
    """Close a PO in Coupa (mocked)."""
    return {"status": "closed", "po-id": po_id, "reason": reason}


async def tool_list_receipts(
    po_number: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """List goods receipts from Coupa (mocked)."""
    if po_number:
        results = [r for r in _MOCK_RECEIPTS if r.get("po-number") == po_number]
    else:
        results = _MOCK_RECEIPTS
    return _mock_response(results)


async def tool_prepare_create_receipt(
    po_number: str,
    ctx: Context | None = None,
) -> dict:
    """Show the goods receipt creation form (mocked)."""
    match = next((p for p in _MOCK_POS if p["po-number"] == po_number), _MOCK_POS[0])
    return {**copy.deepcopy(match), "_widget_hint": "Goods receipt form ready."}


async def tool_create_receipt(
    po_number: str,
    line_items: list[dict],
    receipt_date: str,
    ctx: Context | None = None,
) -> dict:
    """Post a goods receipt in Coupa (mocked)."""
    return {
        "status": "created",
        "id": 7099,
        "po-number": po_number,
        "receipt-date": receipt_date,
        "line-items": line_items,
    }


async def tool_list_requisitions(
    status: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """List purchase requisitions from Coupa (mocked)."""
    results = _MOCK_REQUISITIONS
    if status:
        results = [r for r in results if r.get("status") == status]
    return _mock_response(results)


async def tool_prepare_create_requisition(
    ctx: Context | None = None,
) -> dict:
    """Show the requisition creation form (mocked)."""
    return {"_widget_hint": "Requisition form ready."}


async def tool_create_requisition(
    title: str,
    line_items: list[dict],
    requester: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Submit a new purchase requisition in Coupa (mocked)."""
    return {
        "status": "created",
        "id": 9099,
        "title": title,
        "requester": requester,
        "line-items": line_items,
    }


async def tool_update_requisition(
    requisition_id: str,
    updates: dict,
    ctx: Context | None = None,
) -> dict:
    """Update an existing purchase requisition in Coupa (mocked)."""
    return {"status": "updated", "id": requisition_id, "updates": updates}


async def tool_list_catalog_items(
    query: str | None = None,
    category: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Search the Coupa procurement catalog (mocked)."""
    results = _MOCK_CATALOG
    if query:
        q = query.lower()
        results = [c for c in results if q in c["name"].lower()]
    if category:
        cat = category.lower()
        results = [c for c in results if cat in c["category"].lower()]
    return _mock_response(results)


async def tool_order_catalog_item(
    catalog_item_id: str,
    quantity: int = 1,
    deliver_to: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Create a PR from a catalog item in Coupa (mocked)."""
    item = next((c for c in _MOCK_CATALOG if c["id"] == catalog_item_id), _MOCK_CATALOG[0])
    return {
        "status": "ordered",
        "requisition-id": 9100,
        "item": item["name"],
        "quantity": quantity,
        "deliver-to": deliver_to,
    }


async def tool_list_suppliers(
    query: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Search suppliers in Coupa (mocked)."""
    results = _MOCK_SUPPLIERS
    if query:
        q = query.lower()
        results = [s for s in results if q in s["name"].lower()]
    return _mock_response(results)


async def tool_get_supplier(
    supplier_id: str,
    ctx: Context | None = None,
) -> dict:
    """Get supplier detail from Coupa (mocked)."""
    match = next((s for s in _MOCK_SUPPLIERS if s["id"] == supplier_id), _MOCK_SUPPLIERS[0])
    return copy.deepcopy(match)


async def tool_update_supplier_address(
    supplier_id: str,
    address: dict,
    ctx: Context | None = None,
) -> dict:
    """Update a supplier's address in Coupa (mocked)."""
    return {"status": "updated", "supplier-id": supplier_id, "address": address}


async def tool_update_supplier_bank(
    supplier_id: str,
    bank_details: dict,
    ctx: Context | None = None,
) -> dict:
    """Update a supplier's bank details in Coupa (mocked)."""
    return {"status": "updated", "supplier-id": supplier_id, "bank": bank_details}


async def tool_register_supplier(
    name: str,
    address: dict,
    contact: dict,
    tax_id: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Register/onboard a new supplier in Coupa (mocked)."""
    return {
        "status": "registered",
        "id": "SUP-9999",
        "name": name,
        "address": address,
        "contact": contact,
        "tax-id": tax_id,
    }


async def tool_transfer_purchase_order(
    po_id: str,
    new_owner: str,
    reason: str = "",
    ctx: Context | None = None,
) -> dict:
    """Transfer a PO to a new owner in Coupa (mocked)."""
    return {"status": "transferred", "po-id": po_id, "new-owner": new_owner, "reason": reason}


async def tool_list_approvals(
    ctx: Context | None = None,
) -> dict:
    """List pending approvals in Coupa (mocked)."""
    return _mock_response(_MOCK_APPROVALS)


async def tool_approve_reject(
    approvable_id: str,
    action: str,
    comment: str = "",
    ctx: Context | None = None,
) -> dict:
    """Approve or reject a pending approval in Coupa (mocked)."""
    status_word = "approved" if action == "approve" else "rejected"
    return {"status": status_word, "approvable-id": approvable_id, "comment": comment}


# ── TOOL_SPECS Registry ─────────────────────────────────────────────

COUPA_TOOL_SPECS: list[dict] = [
    {
        "name": "get_invoice_status",
        "summary": "Get invoice payment status from Coupa by invoice number (mocked).",
        "func": tool_get_invoice_status,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/coupa-invoice-status.html",
            "openai/toolInvocation/invoking": "Checking invoice status…",
            "openai/toolInvocation/invoked": "Invoice status ready.",
        },
    },
    {
        "name": "get_po_status",
        "summary": "Get purchase order status from Coupa by PO number (mocked).",
        "func": tool_get_po_status,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/coupa-po-status.html",
            "openai/toolInvocation/invoking": "Checking PO status…",
            "openai/toolInvocation/invoked": "PO status ready.",
        },
    },
    {
        "name": "reject_invoice",
        "summary": "Reject an invoice in Coupa (mocked).",
        "func": tool_reject_invoice,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/outputTemplate": "ui://widget/coupa-confirm-action.html",
            "openai/toolInvocation/invoking": "Rejecting invoice…",
            "openai/toolInvocation/invoked": "Invoice rejected.",
        },
    },
    {
        "name": "close_purchase_order",
        "summary": "Close a purchase order in Coupa (mocked).",
        "func": tool_close_purchase_order,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/outputTemplate": "ui://widget/coupa-confirm-action.html",
            "openai/toolInvocation/invoking": "Closing PO…",
            "openai/toolInvocation/invoked": "PO closed.",
        },
    },
    {
        "name": "list_receipts",
        "summary": "List goods receipts from Coupa, optionally filtered by PO (mocked).",
        "func": tool_list_receipts,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/coupa-receipt-list.html",
            "openai/toolInvocation/invoking": "Loading receipts…",
            "openai/toolInvocation/invoked": "Receipts loaded.",
        },
    },
    {
        "name": "prepare_create_receipt",
        "summary": "Show the goods receipt creation form for a PO (mocked).",
        "func": tool_prepare_create_receipt,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/coupa-create-receipt.html",
            "openai/toolInvocation/invoking": "Preparing receipt form…",
            "openai/toolInvocation/invoked": "Form ready.",
        },
    },
    {
        "name": "create_receipt",
        "summary": "Post a goods receipt in Coupa (mocked).",
        "func": tool_create_receipt,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Creating goods receipt…",
            "openai/toolInvocation/invoked": "Receipt created.",
        },
    },
    {
        "name": "list_requisitions",
        "summary": "List purchase requisitions from Coupa (mocked).",
        "func": tool_list_requisitions,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/coupa-requisition-list.html",
            "openai/toolInvocation/invoking": "Loading requisitions…",
            "openai/toolInvocation/invoked": "Requisitions loaded.",
        },
    },
    {
        "name": "prepare_create_requisition",
        "summary": "Show the purchase requisition creation form (mocked).",
        "func": tool_prepare_create_requisition,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/coupa-create-requisition.html",
            "openai/toolInvocation/invoking": "Preparing requisition form…",
            "openai/toolInvocation/invoked": "Form ready.",
        },
    },
    {
        "name": "create_requisition",
        "summary": "Submit a new purchase requisition in Coupa (mocked).",
        "func": tool_create_requisition,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Creating requisition…",
            "openai/toolInvocation/invoked": "Requisition created.",
        },
    },
    {
        "name": "update_requisition",
        "summary": "Update an existing purchase requisition in Coupa (mocked).",
        "func": tool_update_requisition,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Updating requisition…",
            "openai/toolInvocation/invoked": "Requisition updated.",
        },
    },
    {
        "name": "list_catalog_items",
        "summary": "Search the Coupa procurement catalog (mocked).",
        "func": tool_list_catalog_items,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/coupa-catalog-search.html",
            "openai/toolInvocation/invoking": "Searching catalog…",
            "openai/toolInvocation/invoked": "Catalog results ready.",
        },
    },
    {
        "name": "order_catalog_item",
        "summary": "Create a PR from a catalog item in Coupa (mocked).",
        "func": tool_order_catalog_item,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Ordering catalog item…",
            "openai/toolInvocation/invoked": "Item ordered.",
        },
    },
    {
        "name": "list_suppliers",
        "summary": "Search suppliers in Coupa (mocked).",
        "func": tool_list_suppliers,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/coupa-supplier-list.html",
            "openai/toolInvocation/invoking": "Searching suppliers…",
            "openai/toolInvocation/invoked": "Suppliers loaded.",
        },
    },
    {
        "name": "get_supplier",
        "summary": "Get supplier details from Coupa (mocked).",
        "func": tool_get_supplier,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/coupa-supplier-profile.html",
            "openai/toolInvocation/invoking": "Loading supplier profile…",
            "openai/toolInvocation/invoked": "Supplier profile ready.",
        },
    },
    {
        "name": "update_supplier_address",
        "summary": "Update a supplier's address in Coupa (mocked).",
        "func": tool_update_supplier_address,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Updating supplier address…",
            "openai/toolInvocation/invoked": "Address updated.",
        },
    },
    {
        "name": "update_supplier_bank",
        "summary": "Update a supplier's bank details in Coupa (mocked).",
        "func": tool_update_supplier_bank,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Updating bank details…",
            "openai/toolInvocation/invoked": "Bank details updated.",
        },
    },
    {
        "name": "register_supplier",
        "summary": "Register and onboard a new supplier in Coupa (mocked).",
        "func": tool_register_supplier,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/outputTemplate": "ui://widget/coupa-supplier-registration.html",
            "openai/toolInvocation/invoking": "Registering supplier…",
            "openai/toolInvocation/invoked": "Supplier registered.",
        },
    },
    {
        "name": "transfer_purchase_order",
        "summary": "Transfer a purchase order to a new owner in Coupa (mocked).",
        "func": tool_transfer_purchase_order,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Transferring PO…",
            "openai/toolInvocation/invoked": "PO transferred.",
        },
    },
    {
        "name": "list_approvals",
        "summary": "List pending approval items in Coupa (mocked).",
        "func": tool_list_approvals,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/coupa-approval-list.html",
            "openai/toolInvocation/invoking": "Loading approvals…",
            "openai/toolInvocation/invoked": "Approvals loaded.",
        },
    },
    {
        "name": "approve_reject",
        "summary": "Approve or reject a pending approval in Coupa (mocked). Set action to 'approve' or 'reject'.",
        "func": tool_approve_reject,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Processing approval…",
            "openai/toolInvocation/invoked": "Approval processed.",
        },
    },
]
