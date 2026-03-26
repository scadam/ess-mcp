
Provides issue search, detail, comments, and transitions against
the Jira REST API v3 using API token basic auth (impl notes §6).
"""

import base64
from typing import Any, Dict, List, Optional

from ..http import create_async_client
from ..logging import get_logger
from ..settings import load_jira_settings

LOGGER = get_logger(__name__)


# ── HTTP helpers ─────────────────────────────────────────────────────


def _build_auth_header() -> str:
    """Build Basic auth header from Jira email + API token."""
    settings = load_jira_settings()
    credentials = f"{settings.email}:{settings.api_token}"
    encoded = base64.b64encode(credentials.encode()).decode()
    return f"Basic {encoded}"


async def _jira_get(
    path: str, params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Make an authenticated GET request to Jira REST API v3."""
    settings = load_jira_settings()
    url = f"{settings.base_url.rstrip('/')}/rest/api/3{path}"
    headers = {
        "Authorization": _build_auth_header(),
        "Accept": "application/json",
    }
    async with create_async_client() as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _jira_post(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Make an authenticated POST request to Jira REST API v3."""
    settings = load_jira_settings()
    url = f"{settings.base_url.rstrip('/')}/rest/api/3{path}"
    headers = {
        "Authorization": _build_auth_header(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with create_async_client() as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type and resp.content:
            return resp.json()
        return {"status": "ok"}

async def _jira_put(path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Make an authenticated PUT request to Jira REST API v3."""
    settings = load_jira_settings()
    url = f"{settings.base_url.rstrip('/')}/rest/api/3{path}"
    headers = {
        "Authorization": _build_auth_header(),
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    async with create_async_client() as client:
        resp = await client.put(url, json=body, headers=headers)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "application/json" in content_type and resp.content:
            return resp.json()
        return {"status": "ok"}


async def _jira_search(
    jql: str, max_results: int = 50, fields: Optional[str] = None
) -> Dict[str, Any]:
    """Search issues via POST /rest/api/3/search/jql.

    The legacy GET /search endpoint was removed (410 Gone) in newer
    Jira Cloud versions.  The new endpoint expects a JSON body.
    """
    body: Dict[str, Any] = {"jql": jql, "maxResults": max_results}
    if fields:
        body["fields"] = [f.strip() for f in fields.split(",")]
    return await _jira_post("/search/jql", body)

# ── Data helpers ─────────────────────────────────────────────────────

_SEARCH_FIELDS = (
    "summary,status,priority,assignee,reporter,issuetype,"
    "project,created,updated,duedate,labels,description"
)


def _simplify_issue(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a Jira issue into a concise dict."""
    fields = raw.get("fields", {})
    status = fields.get("status", {})
    priority = fields.get("priority", {})
    assignee = fields.get("assignee") or {}
    reporter = fields.get("reporter") or {}
    issue_type = fields.get("issuetype", {})
    project = fields.get("project", {})

    return {
        "key": raw.get("key"),
        "id": raw.get("id"),
        "summary": fields.get("summary"),
        "description": fields.get("description"),
        "status": (
            status.get("name") if isinstance(status, dict) else status
        ),
        "priority": (
            priority.get("name") if isinstance(priority, dict) else priority
        ),
        "assignee": (
            assignee.get("displayName")
            if isinstance(assignee, dict)
            else None
        ),
        "reporter": (
            reporter.get("displayName")
            if isinstance(reporter, dict)
            else None
        ),
        "issueType": (
            issue_type.get("name")
            if isinstance(issue_type, dict)
            else issue_type
        ),
        "project": (
            project.get("name") if isinstance(project, dict) else project
        ),
        "projectKey": (
            project.get("key") if isinstance(project, dict) else None
        ),
        "created": fields.get("created"),
        "updated": fields.get("updated"),
        "duedate": fields.get("duedate"),
        "labels": fields.get("labels", []),
    }


def _extract_adf_text(body: Any) -> str:
    """Extract plain text from Jira ADF (Atlassian Document Format)."""
    if isinstance(body, str):
        return body
    if not isinstance(body, dict):
        return ""
    parts: List[str] = []
    for content_block in body.get("content", []):
        for inline in content_block.get("content", []):
            if inline.get("type") == "text":
                parts.append(inline.get("text", ""))
    return "".join(parts)


# ── MCP tool functions ──────────────────────────────────────────────


async def tool_list_issues(
    jql: Optional[str] = None,
    project: Optional[str] = None,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Search Jira issues using JQL or common filters.

    Args:
        jql: Full JQL query string. Overrides other filters if provided.
        project: Filter by project key (e.g. PROJ).
        status: Filter by status name (e.g. "In Progress").
        assignee: Filter by assignee. Use "currentUser()" for yourself.
        limit: Maximum results (default 20, max 100).
    """
    if not jql:
        clauses: List[str] = []
        if project:
            clauses.append(f'project = "{project}"')
        if status:
            clauses.append(f'status = "{status}"')
        if assignee:
            if assignee.lower() == "currentuser()":
                clauses.append("assignee = currentUser()")
            else:
                clauses.append(f'assignee = "{assignee}"')
        jql = " AND ".join(clauses) if clauses else "assignee = currentUser() ORDER BY updated DESC"

    if "ORDER BY" not in jql.upper():
        jql += " ORDER BY updated DESC"

    safe_limit = max(1, min(int(limit), 100))

    LOGGER.info("jira_search", jql=jql, limit=safe_limit)

    data = await _jira_search(jql, max_results=safe_limit, fields=_SEARCH_FIELDS)

    issues = [_simplify_issue(i) for i in data.get("issues", [])]
    return {
        "total": data.get("total", 0),
        "returned": len(issues),
        "issues": issues,
    }


async def tool_get_issue(key: str) -> Dict[str, Any]:
    """Get full details, comments, and transitions for a Jira issue.

    Args:
        key: The issue key (e.g. PROJ-123).
    """
    LOGGER.info("jira_get_issue", key=key)

    raw = await _jira_get(f"/issue/{key}")
    issue = _simplify_issue(raw)

    # Fetch comments
    comments_data = await _jira_get(
        f"/issue/{key}/comment", params={"maxResults": 50}
    )
    comments = []
    for c in comments_data.get("comments", []):
        author = c.get("author", {})
        comments.append(
            {
                "id": c.get("id"),
                "author": (
                    author.get("displayName")
                    if isinstance(author, dict)
                    else None
                ),
                "body": _extract_adf_text(c.get("body", {})),
                "created": c.get("created"),
            }
        )

    # Fetch available transitions (requires transition ID for actions)
    transitions_data = await _jira_get(f"/issue/{key}/transitions")
    transitions = [
        {"id": t.get("id"), "name": t.get("name")}
        for t in transitions_data.get("transitions", [])
    ]

    return {
        "issue": issue,
        "comments": comments,
        "commentCount": len(comments),
        "transitions": transitions,
    }


async def tool_add_comment(
    key: str,
    body: str,
) -> Dict[str, Any]:
    """Add a comment to a Jira issue.

    Args:
        key: The issue key (e.g. PROJ-123).
        body: The comment text.
    """
    LOGGER.info("jira_add_comment", key=key)

    try:
        # Jira API v3 expects ADF (Atlassian Document Format)
        adf_body = {
            "version": 1,
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": body}],
                }
            ],
        }

        result = await _jira_post(f"/issue/{key}/comment", {"body": adf_body})
        return {
            "success": True,
            "commentId": result.get("id"),
            "issueKey": key,
        }
    except Exception as exc:
        LOGGER.error("jira_add_comment_error", key=key, error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_transition_issue(
    key: str,
    transition_id: str,
    comment: Optional[str] = None,
) -> Dict[str, Any]:
    """Transition a Jira issue to a new status.

    Issue transitions require transition ID lookup (impl notes §6).
    Use ``get_issue`` first to see available transitions and their IDs.

    Args:
        key: The issue key (e.g. PROJ-123).
        transition_id: The transition ID (from the transitions list).
        comment: Optional comment to add with the transition.
    """
    LOGGER.info("jira_transition", key=key, transition_id=transition_id)

    try:
        payload: Dict[str, Any] = {
            "transition": {"id": transition_id},
        }

        if comment:
            payload["update"] = {
                "comment": [
                    {
                        "add": {
                            "body": {
                                "version": 1,
                                "type": "doc",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {"type": "text", "text": comment}
                                        ],
                                    }
                                ],
                            }
                        }
                    }
                ]
            }

        await _jira_post(f"/issue/{key}/transitions", payload)

        # Fetch updated issue
        updated = await _jira_get(
            f"/issue/{key}", params={"fields": _SEARCH_FIELDS}
        )

        return {
            "success": True,
            "issueKey": key,
            "newStatus": (
                updated.get("fields", {}).get("status", {}).get("name")
            ),
            "issue": _simplify_issue(updated),
        }
    except Exception as exc:
        LOGGER.error("jira_transition_error", key=key, error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_create_project(
    name: str,
    key: str,
    description: Optional[str] = None,
    lead_account_id: Optional[str] = None,
    project_type: str = "software",
) -> Dict[str, Any]:
    """Create a new Jira project.

    Args:
        name: Display name for the project (e.g. "AML Compliance Review").
        key: Unique project key (2-10 uppercase letters, e.g. "AMLREV").
        description: Optional project description.
        lead_account_id: Atlassian account ID for the project lead.
                         If omitted, uses the current authenticated user.
        project_type: "software" (default) or "business".
    """
    LOGGER.info("jira_create_project", name=name, key=key)

    try:
        # Resolve lead account ID — default to the authenticated user
        if not lead_account_id:
            me = await _jira_get("/myself")
            lead_account_id = me.get("accountId")

        template_key = (
            "com.pyxis.greenhopper.jira:gh-simplified-kanban-classic"
            if project_type == "software"
            else "com.atlassian.jira-core-project-templates:jira-core-simplified-task-tracking"
        )

        payload: Dict[str, Any] = {
            "name": name,
            "key": key.upper(),
            "projectTypeKey": project_type,
            "projectTemplateKey": template_key,
            "leadAccountId": lead_account_id,
        }
        if description:
            payload["description"] = description

        result = await _jira_post("/project", payload)

        return {
            "created": True,
            "project": {
                "id": result.get("id"),
                "key": result.get("key"),
                "name": name,
                "self": result.get("self"),
            },
        }
    except Exception as exc:
        LOGGER.error("jira_create_project_error", name=name, error=str(exc))
        return {"created": False, "error": str(exc)}


def _build_adf(text: str) -> Dict[str, Any]:
    """Build a simple ADF document from plain text."""
    return {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


async def tool_create_issue(
    project_key: str,
    summary: str,
    issue_type: str = "Task",
    description: Optional[str] = None,
    priority: Optional[str] = None,
    assignee_account_id: Optional[str] = None,
    labels: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Create a new Jira issue in a project.

    Args:
        project_key: Project key (e.g. "PROJ").
        summary: Issue summary / title.
        issue_type: Issue type name — "Task", "Bug", "Story", "Epic" (default "Task").
        description: Plain text description (converted to ADF automatically).
        priority: Priority name — "Highest", "High", "Medium", "Low", "Lowest".
        assignee_account_id: Atlassian account ID to assign. Omit for unassigned.
        labels: Optional list of labels to apply.
    """
    LOGGER.info("jira_create_issue", project=project_key, summary=summary)

    try:
        fields: Dict[str, Any] = {
            "project": {"key": project_key.upper()},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }
        if description:
            fields["description"] = _build_adf(description)
        if priority:
            fields["priority"] = {"name": priority}
        if assignee_account_id:
            fields["assignee"] = {"accountId": assignee_account_id}
        if labels:
            fields["labels"] = labels

        result = await _jira_post("/issue", {"fields": fields})
        issue_key = result.get("key")

        # Fetch created issue for full details
        raw = await _jira_get(f"/issue/{issue_key}")
        return {
            "created": True,
            "issue": _simplify_issue(raw),
        }
    except Exception as exc:
        LOGGER.error("jira_create_issue_error", project=project_key, error=str(exc))
        return {"created": False, "error": str(exc)}


async def tool_update_issue(
    key: str,
    summary: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None,
    assignee_account_id: Optional[str] = None,
    labels: Optional[List[str]] = None,
    comment: Optional[str] = None,
) -> Dict[str, Any]:
    """Update fields and/or add a comment on an existing Jira issue.

    Only the provided fields are modified; omitted fields remain unchanged.

    Args:
        key: Issue key (e.g. PROJ-123).
        summary: New summary text.
        description: New plain text description (converted to ADF).
        priority: New priority name.
        assignee_account_id: New assignee Atlassian account ID.
        labels: Replace labels with this list.
        comment: Add this text as a new comment.
    """
    LOGGER.info("jira_update_issue", key=key)

    try:
        fields: Dict[str, Any] = {}
        if summary is not None:
            fields["summary"] = summary
        if description is not None:
            fields["description"] = _build_adf(description)
        if priority is not None:
            fields["priority"] = {"name": priority}
        if assignee_account_id is not None:
            fields["assignee"] = {"accountId": assignee_account_id}
        if labels is not None:
            fields["labels"] = labels

        if fields:
            await _jira_put(f"/issue/{key}", {"fields": fields})

        if comment:
            await tool_add_comment(key, comment)

        # Fetch updated issue
        raw = await _jira_get(f"/issue/{key}")
        result = _simplify_issue(raw)

        return {
            "success": True,
            "issueKey": key,
            "issue": result,
        }
    except Exception as exc:
        LOGGER.error("jira_update_issue_error", key=key, error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Provider functions for TaskServer integration ───────────────────


async def provider_list_tasks() -> List[Dict[str, Any]]:
    """List Jira issues assigned to the configured user.

    Returns raw Jira issue data for TaskServer normalization.
    """
    try:
        load_jira_settings()
    except Exception:  # noqa: BLE001
        LOGGER.debug("jira_settings_not_configured")
        return []

    data = await _jira_search(
        jql="assignee = currentUser() ORDER BY updated DESC",
        max_results=50,
        fields=_SEARCH_FIELDS,
    )
    return data.get("issues", [])


# ── Form-show helpers (GET-pattern, widget submits the POST) ────────

async def tool_show_create_issue_form(
    project_key: Optional[str] = None,
    summary: Optional[str] = None,
    issue_type: Optional[str] = None,
    description: Optional[str] = None,
    priority: Optional[str] = None,
) -> Dict[str, Any]:
    """Show the Jira issue creation form widget.

    Returns pre-fill data so the widget can populate the form.  The user
    completes and submits the form inside the widget — this tool does not
    create the issue directly.

    Args:
        project_key: Optional project key to pre-select (e.g. "PROJ").
        summary: Optional issue summary to pre-fill.
        issue_type: Optional issue type to pre-select (Task, Bug, Story, Epic).
        description: Optional description to pre-fill.
        priority: Optional priority to pre-select (High, Medium, Low).
    """
    prefill: Dict[str, Any] = {}
    if project_key:
        prefill["project_key"] = project_key
    if summary:
        prefill["summary"] = summary
    if issue_type:
        prefill["issue_type"] = issue_type
    if description:
        prefill["description"] = description
    if priority:
        prefill["priority"] = priority

    return {
        "_widget_hint": "The form is ready. Acknowledge with one short sentence (e.g. 'Here is the Jira issue creation form.').",
        **prefill,
    }


async def tool_show_create_project_form(
    name: Optional[str] = None,
    key: Optional[str] = None,
    description: Optional[str] = None,
    project_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Show the Jira project creation form widget.

    Returns pre-fill data so the widget can populate the form.  The user
    completes and submits the form inside the widget — this tool does not
    create the project directly.

    Args:
        name: Optional project display name to pre-fill.
        key: Optional project key to pre-fill (2-10 uppercase letters).
        description: Optional project description to pre-fill.
        project_type: Optional project type ("software" or "business").
    """
    prefill: Dict[str, Any] = {}
    if name:
        prefill["name"] = name
    if key:
        prefill["key"] = key
    if description:
        prefill["description"] = description
    if project_type:
        prefill["project_type"] = project_type

    return {
        "_widget_hint": "The form is ready. Acknowledge with one short sentence (e.g. 'Here is the Jira project creation form.').",
        **prefill,
    }


# ── Tool registry ───────────────────────────────────────────────────

JIRA_TOOL_SPECS: list[dict] = [
    {
        "name": "list_issues",
        "func": tool_list_issues,
        "summary": (
            "Search Jira issues using JQL or common filters (project, status, "
            "assignee). Returns up to 100 issues per call."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_issue",
        "func": tool_get_issue,
        "summary": (
            "Get full details, comments, and available transitions for a Jira "
            "issue by its key (e.g. PROJ-123). Result is rendered as an interactive "
            "widget where the user can view the issue and submit updates."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/jira-issue.html",
            "openai/toolInvocation/invoking": "Loading Jira issue\u2026",
            "openai/toolInvocation/invoked": "Issue loaded.",
        },
    },
    {
        "name": "show_create_issue_form",
        "func": tool_show_create_issue_form,
        "summary": (
            "Show the Jira issue creation form. Pass any known details "
            "(project_key, summary, issue_type, description, priority) to pre-fill the form. "
            "The widget handles submission."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/jira-issue.html",
            "openai/toolInvocation/invoking": "Loading issue creation form\u2026",
            "openai/toolInvocation/invoked": "Issue form ready.",
        },
    },
    {
        "name": "add_comment",
        "func": tool_add_comment,
        "summary": (
            "Add a comment to a Jira issue. Called by the jira-issue widget when the user submits a comment."
        ),
        "annotations": {"readOnlyHint": False},
    },
    {
        "name": "transition_issue",
        "func": tool_transition_issue,
        "summary": (
            "Transition a Jira issue to a new status. Called by the task-list or jira-issue widget when the user changes status."
        ),
        "annotations": {"readOnlyHint": False},
    },
    {
        "name": "show_create_project_form",
        "func": tool_show_create_project_form,
        "summary": (
            "Show the Jira project creation form. Pass any known details "
            "(name, key, description, project_type) to pre-fill the form. "
            "The widget handles submission."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/create-project.html",
            "openai/toolInvocation/invoking": "Loading project creation form\u2026",
            "openai/toolInvocation/invoked": "Project form ready.",
        },
    },
    {
        "name": "create_project",
        "func": tool_create_project,
        "summary": (
            "Create a new Jira project. Called by the create-project widget when the user clicks Submit. "
            "Use show_create_project_form to display the form first."
        ),
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/outputTemplate": "ui://widget/create-project.html",
            "openai/toolInvocation/invoking": "Creating Jira project\u2026",
            "openai/toolInvocation/invoked": "Project created.",
        },
    },
    {
        "name": "create_issue",
        "func": tool_create_issue,
        "summary": (
            "Create a new Jira issue in a project. Called by the jira-issue widget when the user clicks Submit. "
            "Use show_create_issue_form to display the form first."
        ),
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/outputTemplate": "ui://widget/jira-issue.html",
            "openai/toolInvocation/invoking": "Creating Jira issue\u2026",
            "openai/toolInvocation/invoked": "Issue created.",
        },
    },
    {
        "name": "update_issue",
        "func": tool_update_issue,
        "summary": (
            "Update fields and/or add a comment on an existing Jira issue. Called by the jira-issue widget when the user clicks Submit. "
            "Use get_issue first to load the issue widget."
        ),
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/outputTemplate": "ui://widget/jira-issue.html",
            "openai/toolInvocation/invoking": "Updating Jira issue\u2026",
            "openai/toolInvocation/invoked": "Issue updated.",
        },
    },
]
