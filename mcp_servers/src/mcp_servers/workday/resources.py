"""Workday MCP resource definitions – self-contained HTML+Skybridge widgets."""

from __future__ import annotations

from pathlib import Path as _Path

def _read_widget(name: str) -> str:
    """Read a widget HTML file from the ui/widget directory."""
    widget_dir = _Path(__file__).resolve().parent.parent / "ui" / "widget"
    return (widget_dir / name).read_text(encoding="utf-8")

# ---------------------------------------------------------------------------
# Worker Profile card – loaded from the shared ui/widget directory.
# Uses the OpenAI Skybridge (window.openai) to call the `get_worker` MCP tool
# and render a profile card with full dark/light theme support.
# ---------------------------------------------------------------------------

WORKER_PROFILE_HTML = _read_widget("worker-profile.html")

# ---------------------------------------------------------------------------
# Registry: map of resource name → (description, mime_type, content)
# ---------------------------------------------------------------------------
WORKDAY_RESOURCES = {
    "worker-profile": {
        "description": "Interactive worker profile card – calls get_worker via Skybridge and renders an employee details widget.",
        "mime_type": "text/html+skybridge",
        "content": WORKER_PROFILE_HTML,
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "leave-booking": {
        "description": "Leave booking widget – calendar view of booked PTO, balance chips, and a form to request time off via book_leave.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("leave-booking.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "compensation-summary": {
        "description": "Compensation summary widget showing base salary, bonuses, and total compensation.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("compensation-summary.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "org-chart": {
        "description": "Organization chart widget showing manager, current worker, and direct reports hierarchy.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("org-chart.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "team-calendar": {
        "description": "Team time-off calendar showing who is out and upcoming absences.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("team-calendar.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "team-dashboard": {
        "description": "Team overview dashboard showing headcount, role breakdown, and roster via get_team_overview.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("team-dashboard.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
}
