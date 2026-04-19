"""SAP SuccessFactors MCP resource definitions – self-contained HTML+Skybridge widgets."""

from __future__ import annotations

from pathlib import Path as _Path


def _read_widget(name: str) -> str:
    """Read a widget HTML file from the ui/widget directory."""
    widget_dir = _Path(__file__).resolve().parent.parent / "ui" / "widget"
    return (widget_dir / name).read_text(encoding="utf-8")


SAP_SF_RESOURCES: dict[str, dict] = {
    "sf-employee-profile": {
        "description": "Interactive employee profile card showing personal and job details from SAP SuccessFactors.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("sf-employee-profile.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "sf-leave-balance": {
        "description": "Leave balance widget showing remaining days for each leave type.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("sf-leave-balance.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "sf-time-off-history": {
        "description": "Time-off history table showing past leave records with dates, types, and approval status.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("sf-time-off-history.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "sf-leave-booking": {
        "description": "Interactive leave booking form with balance chips, calendar date picker, and type selector.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("sf-leave-booking.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "sf-personal-data-form": {
        "description": "Personal data change form pre-populated with current address, phone, and email.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("sf-personal-data-form.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "sf-org-chart": {
        "description": "Organisation chart showing manager, current employee, and direct reports hierarchy.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("sf-org-chart.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "sf-payslip-list": {
        "description": "Recent payslips list showing pay dates, gross/net amounts, and currency.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("sf-payslip-list.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "sf-payslip-detail": {
        "description": "Detailed payslip breakdown showing earnings, deductions, and net pay.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("sf-payslip-detail.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "sf-move-employee": {
        "description": "Move employee form to transfer an employee to a new position.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("sf-move-employee.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
    "sf-document-list": {
        "description": "Employee document list showing contracts, letters, and certificates.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("sf-document-list.html"),
        "meta": {"openai/widgetCSP": {"connect_domains": [], "resource_domains": []}},
    },
}
