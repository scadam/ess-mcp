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
    "change-business-title": {
        "description": "Business title change form – submit a request to change an employee's business title via change_business_title.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("change-business-title.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "learning-assignments": {
        "description": "Learning assignments widget – view assigned training courses, completion status, and due dates.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("learning-assignments.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "learning-catalog": {
        "description": "Learning catalog widget – browse and filter learning content by skills, view lessons, and enroll.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("learning-catalog.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "inbox-tasks": {
        "description": "Inbox tasks widget – view, search, and approve/deny Workday inbox tasks inline with comments.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("inbox-tasks.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "give-feedback": {
        "description": "Give feedback widget – 3-step wizard to select a colleague, pick a badge, and write recognition feedback.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("give-feedback.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "goals-dashboard": {
        "description": "Goals dashboard – view performance goals with status indicators, progress bars, and category filters.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("goals-dashboard.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "create-check-in-form": {
        "description": "Check-in creation widget – 3-step wizard to select a team member, pick topics, and create a 1:1 check-in.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("create-check-in-form.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "development-items": {
        "description": "Development items widget – view individual development plan items with skills, status filters, and category icons.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("development-items.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
    "team-goals": {
        "description": "Team goals widget – manager view of all direct reports' goals with aggregate stats and expandable per-report sections.",
        "mime_type": "text/html+skybridge",
        "content": _read_widget("team-goals.html"),
        "meta": {
            "openai/widgetCSP": {
                "connect_domains": [],
                "resource_domains": [],
            }
        },
    },
}
