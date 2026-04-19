"""SAP Ariba MCP tool definitions and async handler functions.

Authentication: Static API key from .env sent as header on every request.
Uses sandbox.api.sap.com for the demo.  When a specific API path is not
available on the sandbox the tool falls back to realistic mock data so
widgets always render correctly.
"""

from __future__ import annotations

import copy
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastmcp import Context

from ..http import create_async_client
from ..logging import get_logger
from ..settings import load_ariba_settings

LOGGER = get_logger(__name__)


# ── Mock data store (used as sandbox fallback) ──────────────────────

_MOCK_INVOICES = [
    {
        "InvoiceId": "INV-2026-0448",
        "InvoiceNumber": "INV-2026-0448",
        "Status": "pending_approval",
        "TotalAmount": {"Amount": "18,750.00", "Currency": "GBP"},
        "Supplier": {"Name": "Kingsley Automation Ltd", "SupplierId": "SUP-3001"},
        "InvoiceDate": "2026-03-22",
        "DueDate": "2026-04-21",
        "PaymentStatus": "Not Paid",
        "PurchaseOrderNumber": "PO-2026-1102",
    },
    {
        "InvoiceId": "INV-2026-0391",
        "InvoiceNumber": "INV-2026-0391",
        "Status": "approved",
        "TotalAmount": {"Amount": "4,800.00", "Currency": "GBP"},
        "Supplier": {"Name": "Nexus Data Services", "SupplierId": "SUP-3042"},
        "InvoiceDate": "2026-03-10",
        "DueDate": "2026-04-09",
        "PaymentStatus": "Paid",
        "PurchaseOrderNumber": "PO-2026-1055",
    },
]

_MOCK_POS = [
    {
        "OrderId": "PO-2026-1102",
        "OrderNumber": "PO-2026-1102",
        "Status": "Ordered",
        "TotalAmount": {"Amount": "35,000.00", "Currency": "GBP"},
        "Supplier": {"Name": "Kingsley Automation Ltd", "SupplierId": "SUP-3001"},
        "CreatedDate": "2026-02-28",
        "ShipTo": {"City": "London", "Country": "GB"},
        "LineCount": 4,
    },
    {
        "OrderId": "PO-2026-1055",
        "OrderNumber": "PO-2026-1055",
        "Status": "Closed",
        "TotalAmount": {"Amount": "4,800.00", "Currency": "GBP"},
        "Supplier": {"Name": "Nexus Data Services", "SupplierId": "SUP-3042"},
        "CreatedDate": "2026-01-20",
        "ShipTo": {"City": "Edinburgh", "Country": "GB"},
        "LineCount": 2,
    },
]

_MOCK_RECEIPTS = [
    {
        "ReceiptId": "REC-7101",
        "PurchaseOrderNumber": "PO-2026-1102",
        "ReceiptDate": "2026-03-18",
        "Status": "Received",
        "ReceivedBy": "procurement@example.com",
        "LineItems": [
            {"Description": "Robotic Arm Module", "Quantity": 2, "Unit": "EA"},
            {"Description": "Sensor Pack", "Quantity": 10, "Unit": "EA"},
        ],
    },
]

_MOCK_REQUISITIONS = [
    {
        "RequisitionId": "REQ-4501",
        "Title": "Warehouse Safety Equipment Q2 2026",
        "Status": "Pending Approval",
        "Requester": "hse@example.com",
        "CreatedDate": "2026-03-20",
        "TotalAmount": {"Amount": "2,600.00", "Currency": "GBP"},
        "LineItems": [
            {"Description": "Safety Helmets (box 20)", "Quantity": 5, "UnitPrice": "120.00"},
            {"Description": "High-Vis Vests (box 50)", "Quantity": 4, "UnitPrice": "200.00"},
        ],
    },
]

_MOCK_CATALOG = [
    {
        "ItemId": "CAT-A001",
        "Name": "Robotic Arm Module (6-axis)",
        "Category": "Automation",
        "UnitPrice": "12,500.00",
        "Currency": "GBP",
        "Supplier": "Kingsley Automation Ltd",
    },
    {
        "ItemId": "CAT-A002",
        "Name": "Industrial Sensor Pack (12-unit)",
        "Category": "Automation",
        "UnitPrice": "750.00",
        "Currency": "GBP",
        "Supplier": "Kingsley Automation Ltd",
    },
    {
        "ItemId": "CAT-A003",
        "Name": "Ergonomic Sit-Stand Desk",
        "Category": "Office Furniture",
        "UnitPrice": "680.00",
        "Currency": "GBP",
        "Supplier": "Workspace Solutions plc",
    },
]

_MOCK_SUPPLIERS = [
    {
        "SupplierId": "SUP-3001",
        "Name": "Kingsley Automation Ltd",
        "Status": "Active",
        "Address": {"Street": "7 Innovation Park", "City": "Cambridge", "PostCode": "CB1 2AA", "Country": "GB"},
        "Contact": {"Name": "Oliver Marsh", "Email": "oliver@kingsley.example.com", "Phone": "+44 1223 555 0100"},
        "TaxId": "GB112233445",
        "BankAccount": {"BankName": "Lloyds", "AccountNumber": "****6789", "SortCode": "30-00-00"},
    },
    {
        "SupplierId": "SUP-3042",
        "Name": "Nexus Data Services",
        "Status": "Active",
        "Address": {"Street": "20 Techno Rd", "City": "Edinburgh", "PostCode": "EH1 1AA", "Country": "GB"},
        "Contact": {"Name": "Fiona Grant", "Email": "fiona@nexusdata.example.com", "Phone": "+44 131 555 0200"},
        "TaxId": "GB998877665",
        "BankAccount": {"BankName": "RBS", "AccountNumber": "****1234", "SortCode": "83-00-00"},
    },
]

_MOCK_APPROVALS = [
    {
        "ApprovableId": "APR-601",
        "Type": "Requisition",
        "Title": "Warehouse Safety Equipment Q2 2026",
        "Requester": "hse@example.com",
        "TotalAmount": {"Amount": "2,600.00", "Currency": "GBP"},
        "SubmittedDate": "2026-03-20",
        "Status": "Pending",
    },
    {
        "ApprovableId": "APR-602",
        "Type": "Invoice",
        "Title": "INV-2026-0448 — Kingsley Automation Ltd",
        "Requester": "accounts@example.com",
        "TotalAmount": {"Amount": "18,750.00", "Currency": "GBP"},
        "SubmittedDate": "2026-03-23",
        "Status": "Pending",
    },
]


def _mock(data: Any) -> Dict[str, Any]:
    """Wrap mock data in a standard Ariba API envelope."""
    return copy.deepcopy(data) if isinstance(data, dict) else {"results": copy.deepcopy(data)}


# ── API Helpers (with mock fallback) ────────────────────────────────

async def _ariba_get(path: str, params: Optional[Dict[str, str]] = None, *, fallback: Any = None) -> Dict[str, Any]:
    """GET request to Ariba API. Falls back to *fallback* when sandbox returns an error."""
    settings = load_ariba_settings()
    url = f"{settings.api_url}{path}"
    all_params = {"realm": settings.realm}
    if params:
        all_params.update(params)
    try:
        async with create_async_client() as client:
            resp = await client.get(
                url,
                headers={"apiKey": settings.api_key},
                params=all_params,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        if fallback is not None:
            LOGGER.info("ariba_sandbox_fallback path=%s err=%s", path, exc)
            return _mock(fallback) if not isinstance(fallback, dict) else copy.deepcopy(fallback)
        raise


async def _ariba_post(path: str, payload: Dict[str, Any], *, fallback: Any = None) -> Dict[str, Any]:
    """POST request to Ariba API with mock fallback."""
    settings = load_ariba_settings()
    url = f"{settings.api_url}{path}"
    try:
        async with create_async_client() as client:
            resp = await client.post(
                url,
                headers={
                    "apiKey": settings.api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                params={"realm": settings.realm},
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as exc:
        if fallback is not None:
            LOGGER.info("ariba_sandbox_fallback path=%s err=%s", path, exc)
            return copy.deepcopy(fallback) if isinstance(fallback, dict) else fallback
        raise


async def _ariba_patch(path: str, payload: Dict[str, Any], *, fallback: Any = None) -> Dict[str, Any]:
    """PATCH request to Ariba API with mock fallback."""
    settings = load_ariba_settings()
    url = f"{settings.api_url}{path}"
    try:
        async with create_async_client() as client:
            resp = await client.patch(
                url,
                headers={
                    "apiKey": settings.api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
                params={"realm": settings.realm},
            )
            resp.raise_for_status()
            try:
                return resp.json()
            except Exception:
                return {"status": "ok"}
    except Exception as exc:
        if fallback is not None:
            LOGGER.info("ariba_sandbox_fallback path=%s err=%s", path, exc)
            return copy.deepcopy(fallback) if isinstance(fallback, dict) else fallback
        raise


# ── Tool handlers ───────────────────────────────────────────────────

async def tool_get_invoice_status(
    invoice_number: str,
    ctx: Context | None = None,
) -> dict:
    """Get invoice payment status from SAP Ariba."""
    # No working sandbox invoice endpoint — return mock directly
    fb = copy.deepcopy(_MOCK_INVOICES[0])
    fb["InvoiceNumber"] = invoice_number
    return fb


async def tool_get_po_status(
    po_number: str,
    ctx: Context | None = None,
) -> dict:
    """Get purchase order status from SAP Ariba."""
    data = await _ariba_get(
        "/purchase-orders/v1/sandbox/orders",
        fallback=_MOCK_POS,
    )
    # Try to find the specific PO in live data
    if isinstance(data, dict) and "content" in data:
        orders = data["content"]
        match = next((o for o in orders if o.get("documentNumber") == po_number), orders[0] if orders else None)
        return match or data
    if isinstance(data, dict) and "results" in data:
        orders = data["results"]
        match = next((o for o in orders if o.get("OrderNumber") == po_number), orders[0] if orders else None)
        return match or data
    return data


async def tool_reject_invoice(
    invoice_id: str,
    reason: str = "",
    ctx: Context | None = None,
) -> dict:
    """Reject an invoice in SAP Ariba."""
    # No working sandbox write endpoint — return mock directly
    return {"status": "rejected", "detail": {"status": "rejected", "invoiceId": invoice_id, "reason": reason}}


async def tool_close_purchase_order(
    po_id: str,
    reason: str = "",
    ctx: Context | None = None,
) -> dict:
    """Close a purchase order in SAP Ariba."""
    # No working sandbox write endpoint — return mock directly
    return {"status": "closed", "detail": {"status": "closed", "orderId": po_id, "reason": reason}}


async def tool_list_receipts(
    po_number: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """List goods receipts, optionally filtered by PO number."""
    # No working sandbox receipt endpoint — return mock directly
    if po_number:
        results = [r for r in _MOCK_RECEIPTS if r.get("PurchaseOrderNumber") == po_number]
    else:
        results = copy.deepcopy(_MOCK_RECEIPTS)
    return {"results": results}


async def tool_prepare_create_receipt(
    po_number: str,
    ctx: Context | None = None,
) -> dict:
    """Show the goods receipt creation form for a PO."""
    fb = copy.deepcopy(_MOCK_POS[0])
    fb["OrderNumber"] = po_number
    data = await _ariba_get(
        "/purchase-orders/v1/sandbox/orders",
        fallback=fb,
    )
    # Extract the matching PO from the list if we got live data
    if isinstance(data, dict) and "content" in data:
        orders = data["content"]
        po_data = next((o for o in orders if o.get("documentNumber") == po_number), orders[0] if orders else data)
    else:
        po_data = data
    return {**(po_data if isinstance(po_data, dict) else {}), "_widget_hint": "Goods receipt form ready."}


async def tool_create_receipt(
    po_number: str,
    line_items: list[dict],
    receipt_date: str,
    ctx: Context | None = None,
) -> dict:
    """Post a goods receipt against a purchase order."""
    # No working sandbox write endpoint — return mock directly
    return {"status": "created", "detail": {"status": "created", "ReceiptId": "REC-7199", "PurchaseOrderNumber": po_number, "ReceiptDate": receipt_date, "LineItems": line_items}}


async def tool_list_requisitions(
    status: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """List purchase requisitions."""
    data = await _ariba_get("/procurement/v1/sandbox/requisitions", fallback=_MOCK_REQUISITIONS)
    # Live data is a plain array of requisition objects
    results = data if isinstance(data, list) else data.get("results", [data])
    return {"results": results}


async def tool_prepare_create_requisition(
    ctx: Context | None = None,
) -> dict:
    """Show the requisition creation form."""
    return {"_widget_hint": "Requisition form ready."}


async def tool_create_requisition(
    title: str,
    line_items: list[dict],
    requester: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Submit a new purchase requisition."""
    # No working sandbox write endpoint — return mock directly
    return {"status": "created", "detail": {"status": "created", "RequisitionId": "REQ-4599", "Title": title, "Requester": requester}}


async def tool_update_requisition(
    requisition_id: str,
    updates: dict,
    ctx: Context | None = None,
) -> dict:
    """Update an existing purchase requisition."""
    # No working sandbox write endpoint — return mock directly
    return {"status": "updated", "detail": {"status": "updated", "RequisitionId": requisition_id, "updates": updates}}


async def tool_list_catalog_items(
    query: str | None = None,
    category: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Search the procurement catalog."""
    params = {}
    if query:
        params["q"] = query
    if category:
        params["category"] = category
    # Use the real sandbox catalog endpoint
    data = await _ariba_get("/catalog/v1/sandbox/items", params, fallback=_MOCK_CATALOG)
    # If we got live catalog data, extract the items list
    if isinstance(data, list) and data and "catalogItems" in data[0]:
        items = data[0].get("catalogItems", [])
        return {"results": items}
    return data


async def tool_order_catalog_item(
    catalog_item_id: str,
    quantity: int = 1,
    deliver_to: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Create a purchase requisition from a catalog item."""
    # No working sandbox write endpoint — return mock directly
    item = next((c for c in _MOCK_CATALOG if c["ItemId"] == catalog_item_id), _MOCK_CATALOG[0])
    return {"status": "ordered", "detail": {"status": "ordered", "RequisitionId": "REQ-4600", "Item": item["Name"], "Quantity": quantity, "DeliverTo": deliver_to}}


async def tool_list_suppliers(
    query: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Search the supplier master."""
    # No working sandbox supplier endpoint — return mock directly
    results = copy.deepcopy(_MOCK_SUPPLIERS)
    if query:
        q = query.lower()
        results = [s for s in results if q in s["Name"].lower()]
    return {"results": results}


async def tool_get_supplier(
    supplier_id: str,
    ctx: Context | None = None,
) -> dict:
    """Get supplier detail."""
    # No working sandbox supplier endpoint — return mock directly
    return next((s for s in _MOCK_SUPPLIERS if s["SupplierId"] == supplier_id), _MOCK_SUPPLIERS[0])


async def tool_update_supplier_address(
    supplier_id: str,
    address: dict,
    ctx: Context | None = None,
) -> dict:
    """Update a supplier's address."""
    # No working sandbox write endpoint — return mock directly
    return {"status": "updated", "detail": {"status": "updated", "SupplierId": supplier_id, "Address": address}}


async def tool_update_supplier_bank(
    supplier_id: str,
    bank_details: dict,
    ctx: Context | None = None,
) -> dict:
    """Update a supplier's bank details."""
    # No working sandbox write endpoint — return mock directly
    return {"status": "updated", "detail": {"status": "updated", "SupplierId": supplier_id, "BankAccount": bank_details}}


async def tool_register_supplier(
    name: str,
    address: dict,
    contact: dict,
    tax_id: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Register/onboard a new supplier."""
    # No working sandbox write endpoint — return mock directly
    return {"status": "registered", "detail": {"status": "registered", "SupplierId": "SUP-9999", "Name": name, "Address": address, "Contact": contact, "TaxId": tax_id}}


async def tool_transfer_purchase_order(
    po_id: str,
    new_owner: str,
    reason: str = "",
    ctx: Context | None = None,
) -> dict:
    """Transfer a PO to a new owner."""
    # No working sandbox write endpoint — return mock directly
    return {"status": "transferred", "detail": {"status": "transferred", "OrderId": po_id, "NewOwner": new_owner, "Reason": reason}}


async def tool_list_approvals(
    ctx: Context | None = None,
) -> dict:
    """List pending approvals."""
    data = await _ariba_get("/approval/v2/sandbox/pendingApprovables", fallback=_MOCK_APPROVALS)
    # Live endpoint returns {"count": N, "value": [...]}
    if isinstance(data, dict) and "value" in data:
        return {"results": data["value"]}
    if isinstance(data, list):
        return {"results": data}
    return data


async def tool_approve_reject(
    approvable_id: str,
    action: str,
    comment: str = "",
    ctx: Context | None = None,
) -> dict:
    """Approve or reject a pending approval. action must be 'approve' or 'reject'."""
    # No working sandbox write endpoint — return mock directly
    status_word = "approved" if action == "approve" else "rejected"
    return {"status": status_word, "detail": {"status": status_word, "ApprovableId": approvable_id, "Comment": comment}}


# ── TOOL_SPECS Registry ─────────────────────────────────────────────

ARIBA_TOOL_SPECS: list[dict] = [
    {
        "name": "get_invoice_status",
        "summary": "Get invoice payment status from SAP Ariba by invoice number.",
        "func": tool_get_invoice_status,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/ariba-invoice-status.html",
            "openai/toolInvocation/invoking": "Checking invoice status…",
            "openai/toolInvocation/invoked": "Invoice status ready.",
        },
    },
    {
        "name": "get_po_status",
        "summary": "Get purchase order status from SAP Ariba by PO number.",
        "func": tool_get_po_status,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/ariba-po-status.html",
            "openai/toolInvocation/invoking": "Checking PO status…",
            "openai/toolInvocation/invoked": "PO status ready.",
        },
    },
    {
        "name": "reject_invoice",
        "summary": "Reject an invoice in SAP Ariba.",
        "func": tool_reject_invoice,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/outputTemplate": "ui://widget/ariba-confirm-action.html",
            "openai/toolInvocation/invoking": "Rejecting invoice…",
            "openai/toolInvocation/invoked": "Invoice rejected.",
        },
    },
    {
        "name": "close_purchase_order",
        "summary": "Close a purchase order in SAP Ariba.",
        "func": tool_close_purchase_order,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/outputTemplate": "ui://widget/ariba-confirm-action.html",
            "openai/toolInvocation/invoking": "Closing PO…",
            "openai/toolInvocation/invoked": "PO closed.",
        },
    },
    {
        "name": "list_receipts",
        "summary": "List goods receipts from SAP Ariba, optionally filtered by PO number.",
        "func": tool_list_receipts,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/ariba-receipt-list.html",
            "openai/toolInvocation/invoking": "Loading receipts…",
            "openai/toolInvocation/invoked": "Receipts loaded.",
        },
    },
    {
        "name": "prepare_create_receipt",
        "summary": "Show the goods receipt creation form for a purchase order.",
        "func": tool_prepare_create_receipt,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/ariba-create-receipt.html",
            "openai/toolInvocation/invoking": "Preparing receipt form…",
            "openai/toolInvocation/invoked": "Form ready.",
        },
    },
    {
        "name": "create_receipt",
        "summary": "Post a goods receipt against a purchase order in SAP Ariba.",
        "func": tool_create_receipt,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Creating goods receipt…",
            "openai/toolInvocation/invoked": "Receipt created.",
        },
    },
    {
        "name": "list_requisitions",
        "summary": "List purchase requisitions from SAP Ariba.",
        "func": tool_list_requisitions,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/ariba-requisition-list.html",
            "openai/toolInvocation/invoking": "Loading requisitions…",
            "openai/toolInvocation/invoked": "Requisitions loaded.",
        },
    },
    {
        "name": "prepare_create_requisition",
        "summary": "Show the purchase requisition creation form.",
        "func": tool_prepare_create_requisition,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/ariba-create-requisition.html",
            "openai/toolInvocation/invoking": "Preparing requisition form…",
            "openai/toolInvocation/invoked": "Form ready.",
        },
    },
    {
        "name": "create_requisition",
        "summary": "Submit a new purchase requisition in SAP Ariba.",
        "func": tool_create_requisition,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Creating requisition…",
            "openai/toolInvocation/invoked": "Requisition created.",
        },
    },
    {
        "name": "update_requisition",
        "summary": "Update an existing purchase requisition in SAP Ariba.",
        "func": tool_update_requisition,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Updating requisition…",
            "openai/toolInvocation/invoked": "Requisition updated.",
        },
    },
    {
        "name": "list_catalog_items",
        "summary": "Search the SAP Ariba procurement catalog for items to order.",
        "func": tool_list_catalog_items,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/ariba-catalog-search.html",
            "openai/toolInvocation/invoking": "Searching catalog…",
            "openai/toolInvocation/invoked": "Catalog results ready.",
        },
    },
    {
        "name": "order_catalog_item",
        "summary": "Create a purchase requisition from a catalog item in SAP Ariba.",
        "func": tool_order_catalog_item,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Ordering catalog item…",
            "openai/toolInvocation/invoked": "Item ordered.",
        },
    },
    {
        "name": "list_suppliers",
        "summary": "Search the SAP Ariba supplier master.",
        "func": tool_list_suppliers,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/ariba-supplier-list.html",
            "openai/toolInvocation/invoking": "Searching suppliers…",
            "openai/toolInvocation/invoked": "Suppliers loaded.",
        },
    },
    {
        "name": "get_supplier",
        "summary": "Get supplier details from SAP Ariba.",
        "func": tool_get_supplier,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/ariba-supplier-profile.html",
            "openai/toolInvocation/invoking": "Loading supplier profile…",
            "openai/toolInvocation/invoked": "Supplier profile ready.",
        },
    },
    {
        "name": "update_supplier_address",
        "summary": "Update a supplier's address in SAP Ariba.",
        "func": tool_update_supplier_address,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Updating supplier address…",
            "openai/toolInvocation/invoked": "Address updated.",
        },
    },
    {
        "name": "update_supplier_bank",
        "summary": "Update a supplier's bank details in SAP Ariba.",
        "func": tool_update_supplier_bank,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Updating bank details…",
            "openai/toolInvocation/invoked": "Bank details updated.",
        },
    },
    {
        "name": "register_supplier",
        "summary": "Register and onboard a new supplier in SAP Ariba.",
        "func": tool_register_supplier,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/outputTemplate": "ui://widget/ariba-supplier-registration.html",
            "openai/toolInvocation/invoking": "Registering supplier…",
            "openai/toolInvocation/invoked": "Supplier registered.",
        },
    },
    {
        "name": "transfer_purchase_order",
        "summary": "Transfer a purchase order to a new owner in SAP Ariba.",
        "func": tool_transfer_purchase_order,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Transferring PO…",
            "openai/toolInvocation/invoked": "PO transferred.",
        },
    },
    {
        "name": "list_approvals",
        "summary": "List pending approval items in SAP Ariba.",
        "func": tool_list_approvals,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/ariba-approval-list.html",
            "openai/toolInvocation/invoking": "Loading approvals…",
            "openai/toolInvocation/invoked": "Approvals loaded.",
        },
    },
    {
        "name": "approve_reject",
        "summary": "Approve or reject a pending approval in SAP Ariba. Set action to 'approve' or 'reject'.",
        "func": tool_approve_reject,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Processing approval…",
            "openai/toolInvocation/invoked": "Approval processed.",
        },
    },
]
