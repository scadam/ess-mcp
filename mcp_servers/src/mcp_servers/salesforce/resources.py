"""Salesforce MCP resource definitions – self-contained HTML+Skybridge widgets."""

from __future__ import annotations

from pathlib import Path as _Path


def _read_widget(name: str) -> str:
    """Read a widget HTML file from the ui/widget directory."""
    widget_dir = _Path(__file__).resolve().parent.parent / "ui" / "widget"
    widget_path = widget_dir / name
    if widget_path.exists():
        return widget_path.read_text(encoding="utf-8")
    return f"<html><body>{name} widget</body></html>"


SALESFORCE_RESOURCES = {
    "crm-account-360": {
        "description": "360-degree account view with contacts, opportunities, activities, and cases.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("crm-account-360.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "crm-pipeline": {
        "description": "Sales pipeline funnel dashboard with stage breakdown.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("crm-pipeline.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "crm-opportunity": {
        "description": "Opportunity creation form with account lookup and guided workflow.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("crm-opportunity.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "crm-event": {
        "description": "Event/meeting scheduling form with account/contact linking.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("crm-event.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "compliance-case": {
        "description": "Compliance case creation/update form for AML/KYC, fraud, and regulatory cases.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("compliance-case.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "crm-lead": {
        "description": "Lead creation/update form for managing Salesforce leads.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("crm-lead.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "crm-quote": {
        "description": "Quote creation/update form with opportunity linking.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("crm-quote.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "lead-pipeline": {
        "description": "Lead pipeline view showing leads by status and source.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("lead-pipeline.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "team-pipeline": {
        "description": "Team pipeline dashboard showing manager view with rep breakdowns and leaderboard.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("team-pipeline.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
}
