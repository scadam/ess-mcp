"""Jira MCP resource definitions – self-contained HTML+Skybridge widgets."""

from __future__ import annotations

from pathlib import Path as _Path


def _read_widget(name: str) -> str:
    """Read a widget HTML file from the ui/widget directory."""
    widget_dir = _Path(__file__).resolve().parent.parent / "ui" / "widget"
    widget_path = widget_dir / name
    if widget_path.exists():
        return widget_path.read_text(encoding="utf-8")
    return f"<html><body>{name} widget</body></html>"


# ---------------------------------------------------------------------------
# Registry: map of resource name → (description, mime_type, content)
# ---------------------------------------------------------------------------
JIRA_RESOURCES = {
    "jira-issue": {
        "description": "Interactive Jira issue card – displays issue details, comments, and transitions via Skybridge.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("jira-issue.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "create-issue": {
        "description": "Jira issue creation form widget – pre-fills fields and submits via Skybridge.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("create-issue-jira.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "create-project": {
        "description": "Jira project creation form widget – pre-fills project details and submits via Skybridge.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("create-project.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "sprint-board": {
        "description": "Sprint board widget – displays sprint issues organized by status columns.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("sprint-board.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
}
