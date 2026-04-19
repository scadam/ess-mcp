"""Coupa MCP resource definitions – self-contained HTML+Skybridge widgets."""

from __future__ import annotations

from pathlib import Path as _Path


def _read_widget(name: str) -> str:
    widget_dir = _Path(__file__).resolve().parent.parent / "ui" / "widget"
    return (widget_dir / name).read_text(encoding="utf-8")


COUPA_RESOURCES: dict[str, dict] = {
    "coupa-invoice-status": {
        "description": "Invoice payment status card from Coupa.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("coupa-invoice-status.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "coupa-po-status": {
        "description": "Purchase order status card from Coupa.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("coupa-po-status.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "coupa-confirm-action": {
        "description": "Confirmation widget for Coupa actions (reject invoice, close PO, etc.).",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("coupa-confirm-action.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "coupa-receipt-list": {
        "description": "Goods receipts list from Coupa.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("coupa-receipt-list.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "coupa-create-receipt": {
        "description": "Goods receipt creation form for Coupa.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("coupa-create-receipt.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "coupa-requisition-list": {
        "description": "Purchase requisitions list from Coupa.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("coupa-requisition-list.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "coupa-create-requisition": {
        "description": "Purchase requisition creation form for Coupa.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("coupa-create-requisition.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "coupa-catalog-search": {
        "description": "Procurement catalog search widget for Coupa.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("coupa-catalog-search.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "coupa-supplier-list": {
        "description": "Supplier search results from Coupa.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("coupa-supplier-list.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "coupa-supplier-profile": {
        "description": "Supplier detail profile from Coupa.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("coupa-supplier-profile.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "coupa-supplier-registration": {
        "description": "Supplier registration/onboarding form for Coupa.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("coupa-supplier-registration.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "coupa-approval-list": {
        "description": "Pending approvals list from Coupa.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("coupa-approval-list.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
}
