"""SAP Ariba MCP resource definitions – self-contained HTML+Skybridge widgets."""

from __future__ import annotations

from pathlib import Path as _Path


def _read_widget(name: str) -> str:
    widget_dir = _Path(__file__).resolve().parent.parent / "ui" / "widget"
    return (widget_dir / name).read_text(encoding="utf-8")


ARIBA_RESOURCES: dict[str, dict] = {
    "ariba-invoice-status": {
        "description": "Invoice payment status card from SAP Ariba.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("ariba-invoice-status.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "ariba-po-status": {
        "description": "Purchase order status card from SAP Ariba.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("ariba-po-status.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "ariba-confirm-action": {
        "description": "Confirmation widget for Ariba actions (reject invoice, close PO, etc.).",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("ariba-confirm-action.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "ariba-receipt-list": {
        "description": "Goods receipts list from SAP Ariba.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("ariba-receipt-list.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "ariba-create-receipt": {
        "description": "Goods receipt creation form for SAP Ariba.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("ariba-create-receipt.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "ariba-requisition-list": {
        "description": "Purchase requisitions list from SAP Ariba.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("ariba-requisition-list.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "ariba-create-requisition": {
        "description": "Purchase requisition creation form for SAP Ariba.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("ariba-create-requisition.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "ariba-catalog-search": {
        "description": "Procurement catalog search widget for SAP Ariba.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("ariba-catalog-search.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "ariba-supplier-list": {
        "description": "Supplier search results from SAP Ariba.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("ariba-supplier-list.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "ariba-supplier-profile": {
        "description": "Supplier detail profile from SAP Ariba.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("ariba-supplier-profile.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "ariba-supplier-registration": {
        "description": "Supplier registration/onboarding form for SAP Ariba.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("ariba-supplier-registration.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "ariba-approval-list": {
        "description": "Pending approvals list from SAP Ariba.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("ariba-approval-list.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
}
