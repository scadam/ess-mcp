"""Provides issue search, detail, comments, and transitions against
the Jira REST API v3 using Bearer token auth.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastmcp import Context

from ..auth import TokenValidationError, get_bearer_token
from ..http import create_async_client
from ..logging import get_logger
from ..settings import load_jira_settings

LOGGER = get_logger(__name__)


# ── HTTP helpers ─────────────────────────────────────────────────────


async def _jira_get(
    path: str, ctx: Optional[Context] = None, params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Make an authenticated GET request to Jira REST API v3."""
    settings = load_jira_settings()
    url = f"{settings.base_url.rstrip('/')}/rest/api/3{path}"
    headers = {
        "Authorization": f"Bearer {get_bearer_token(ctx)}",
        "Accept": "application/json",
    }
    async with create_async_client() as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _jira_post(path: str, body: Dict[str, Any], ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Make an authenticated POST request to Jira REST API v3."""
    settings = load_jira_settings()
    url = f"{settings.base_url.rstrip('/')}/rest/api/3{path}"
    headers = {
        "Authorization": f"Bearer {get_bearer_token(ctx)}",
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


async def _jira_put(path: str, body: Dict[str, Any], ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Make an authenticated PUT request to Jira REST API v3."""
    settings = load_jira_settings()
    url = f"{settings.base_url.rstrip('/')}/rest/api/3{path}"
    headers = {
        "Authorization": f"Bearer {get_bearer_token(ctx)}",
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
    jql: str, max_results: int = 50, fields: Optional[str] = None, ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """Search issues via POST /rest/api/3/search/jql."""
    body: Dict[str, Any] = {"jql": jql, "maxResults": max_results}
    if fields:
        body["fields"] = [f.strip() for f in fields.split(",")]
    return await _jira_post("/search/jql", body, ctx)


async def _jira_agile_get(
    path: str, ctx: Optional[Context] = None, params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Make an authenticated GET request to the Jira Agile REST API (v1.0)."""
    settings = load_jira_settings()
    url = f"{settings.base_url.rstrip('/')}/rest/agile/1.0{path}"
    headers = {
        "Authorization": f"Bearer {get_bearer_token(ctx)}",
        "Accept": "application/json",
    }
    async with create_async_client() as client:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        return resp.json()

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
    ctx: Optional[Context] = None,
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

    data = await _jira_search(jql, max_results=safe_limit, fields=_SEARCH_FIELDS, ctx=ctx)

    issues = [_simplify_issue(i) for i in data.get("issues", [])]
    return {
        "total": data.get("total", 0),
        "returned": len(issues),
        "issues": issues,
    }


async def tool_get_issue(key: str, ctx: Optional[Context] = None) -> Dict[str, Any]:
    """Get full details, comments, and transitions for a Jira issue.

    Args:
        key: The issue key (e.g. PROJ-123).
    """
    LOGGER.info("jira_get_issue", key=key)

    raw = await _jira_get(f"/issue/{key}", ctx)

    # Fetch comments
    comments_data = await _jira_get(
        f"/issue/{key}/comment", ctx, params={"maxResults": 50}
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
    transitions_data = await _jira_get(f"/issue/{key}/transitions", ctx)
    raw = await _jira_get(f"/issue/{key}", ctx)
    issue = _simplify_issue(raw)

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
    ctx: Optional[Context] = None,
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

        result = await _jira_post(f"/issue/{key}/comment", {"body": adf_body}, ctx)
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
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Transition a Jira issue to a new status.

    Issue transitions require transition ID lookup (impl notes S6).
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

        await _jira_post(f"/issue/{key}/transitions", payload, ctx)

        # Fetch updated issue
        updated = await _jira_get(
            f"/issue/{key}", ctx, params={"fields": _SEARCH_FIELDS}
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
    ctx: Optional[Context] = None,
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
        # Resolve lead account ID -- default to the authenticated user
        if not lead_account_id:
            me = await _jira_get("/myself", ctx)
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

        result = await _jira_post("/project", payload, ctx)

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


async def tool_update_project(
    key: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    lead_account_id: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Update an existing Jira project.

    Only the provided fields are modified; omitted fields remain unchanged.

    Args:
        key: Project key (e.g. "PROJ").
        name: New display name for the project.
        description: New project description.
        lead_account_id: New Atlassian account ID for the project lead.
    """
    LOGGER.info("jira_update_project", key=key)

    try:
        payload: Dict[str, Any] = {}
        if name is not None:
            payload["name"] = name
        if description is not None:
            payload["description"] = description
        if lead_account_id is not None:
            payload["leadAccountId"] = lead_account_id

        if payload:
            await _jira_put(f"/project/{key}", payload, ctx)

        # Fetch updated project
        updated = await _jira_get(f"/project/{key}", ctx)

        return {
            "success": True,
            "project": {
                "id": updated.get("id"),
                "key": updated.get("key"),
                "name": updated.get("name"),
                "description": updated.get("description"),
                "lead": updated.get("lead", {}).get("displayName"),
                "self": updated.get("self"),
            },
        }
    except Exception as exc:
        LOGGER.error("jira_update_project_error", key=key, error=str(exc))
        return {"success": False, "error": str(exc)}


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
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Create a new Jira issue in a project.

    Args:
        project_key: Project key (e.g. "PROJ").
        summary: Issue summary / title.
        issue_type: Issue type name -- "Task", "Bug", "Story", "Epic" (default "Task").
        description: Plain text description (converted to ADF automatically).
        priority: Priority name -- "Highest", "High", "Medium", "Low", "Lowest".
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

        result = await _jira_post("/issue", {"fields": fields}, ctx)
        issue_key = result.get("key")

        # Fetch created issue for full details
        raw = await _jira_get(f"/issue/{issue_key}", ctx)
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
    ctx: Optional[Context] = None,
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
            await _jira_put(f"/issue/{key}", {"fields": fields}, ctx)

        if comment:
            await tool_add_comment(key, comment, ctx=ctx)

        # Fetch updated issue
        raw = await _jira_get(f"/issue/{key}", ctx)
        result = _simplify_issue(raw)

        return {
            "success": True,
            "issueKey": key,
            "issue": result,
        }
    except Exception as exc:
        LOGGER.error("jira_update_issue_error", key=key, error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_move_issues_to_sprint(
    sprint_id: int,
    issue_keys: List[str],
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Move one or more issues into a sprint.

    Args:
        sprint_id: The sprint ID (from list_sprints).
        issue_keys: List of issue keys to move (e.g. ["PROJ-1", "PROJ-2"]).
    """
    LOGGER.info("jira_move_issues_to_sprint", sprint_id=sprint_id, issue_keys=issue_keys)

    try:
        settings = load_jira_settings()
        url = f"{settings.base_url.rstrip('/')}/rest/agile/1.0/sprint/{sprint_id}/issue"
        headers = {
            "Authorization": f"Bearer {get_bearer_token(ctx)}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        async with create_async_client() as client:
            resp = await client.post(url, json={"issues": issue_keys}, headers=headers)
            resp.raise_for_status()
        return {
            "success": True,
            "sprint_id": sprint_id,
            "issues_moved": issue_keys,
            "count": len(issue_keys),
        }
    except Exception as exc:
        LOGGER.error("jira_move_issues_to_sprint_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_link_issues(
    inward_issue_key: str,
    outward_issue_key: str,
    link_type: str = "Blocks",
    comment: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Create a link between two Jira issues.

    Args:
        inward_issue_key: The issue that IS blocked/cloned/etc.
        outward_issue_key: The issue that BLOCKS/clones/etc.
        link_type: Link type name -- "Blocks", "Cloners", "Duplicate", "Relates".
        comment: Optional comment to add to the link.
    """
    LOGGER.info(
        "jira_link_issues",
        inward=inward_issue_key,
        outward=outward_issue_key,
        link_type=link_type,
    )

    try:
        body: Dict[str, Any] = {
            "type": {"name": link_type},
            "inwardIssue": {"key": inward_issue_key},
            "outwardIssue": {"key": outward_issue_key},
        }
        if comment:
            body["comment"] = _build_adf(comment)
        await _jira_post("/issueLink", body, ctx)
        return {
            "success": True,
            "link_type": link_type,
            "inward_issue": inward_issue_key,
            "outward_issue": outward_issue_key,
        }
    except Exception as exc:
        LOGGER.error("jira_link_issues_error", error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Agile & additional tool functions ───────────────────────────────


async def tool_list_boards(
    project_key: Optional[str] = None,
    board_type: Optional[str] = None,
    limit: int = 50,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List agile boards visible to the current user.

    Args:
        project_key: Filter boards by project key (e.g. "PROJ").
        board_type: Filter by board type -- "scrum", "kanban", or "simple".
        limit: Maximum results (default 50, max 100).
    """
    LOGGER.info("jira_list_boards", project_key=project_key, board_type=board_type)

    params: Dict[str, Any] = {"maxResults": max(1, min(int(limit), 100))}
    if project_key:
        params["projectKeyOrId"] = project_key
    if board_type:
        params["type"] = board_type

    data = await _jira_agile_get("/board", ctx, params=params)
    boards = [
        {
            "id": b.get("id"),
            "name": b.get("name"),
            "type": b.get("type"),
            "projectKey": (b.get("location", {}) or {}).get("projectKey"),
            "projectName": (b.get("location", {}) or {}).get("projectName"),
        }
        for b in data.get("values", [])
    ]
    return {"total": data.get("total", len(boards)), "boards": boards}


async def tool_get_board(
    board_id: int,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Get board details including column configuration.

    Args:
        board_id: The numeric ID of the agile board.
    """
    LOGGER.info("jira_get_board", board_id=board_id)

    config = await _jira_agile_get(f"/board/{board_id}/configuration", ctx)
    columns = [
        {
            "name": col.get("name"),
            # Status self-links end with the status ID (e.g. ".../status/10001")
            "statuses": [s.get("id", s.get("self", "").split("/")[-1]) for s in col.get("status", [])],
        }
        for col in config.get("columnConfig", {}).get("columns", [])
    ]
    return {
        "id": config.get("id"),
        "name": config.get("name"),
        "type": config.get("type"),
        "columns": columns,
        "filter": {
            "id": config.get("filter", {}).get("id"),
            "name": config.get("filter", {}).get("name"),
        },
    }


async def tool_list_sprints(
    board_id: int,
    state: Optional[str] = None,
    limit: int = 50,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List sprints for an agile board.

    Args:
        board_id: The numeric ID of the agile board.
        state: Filter by sprint state -- "active", "future", or "closed".
        limit: Maximum results (default 50, max 100).
    """
    LOGGER.info("jira_list_sprints", board_id=board_id, state=state)

    params: Dict[str, Any] = {"maxResults": max(1, min(int(limit), 100))}
    if state:
        params["state"] = state

    data = await _jira_agile_get(f"/board/{board_id}/sprint", ctx, params=params)
    sprints = [
        {
            "id": s.get("id"),
            "name": s.get("name"),
            "state": s.get("state"),
            "startDate": s.get("startDate"),
            "endDate": s.get("endDate"),
            "completeDate": s.get("completeDate"),
            "goal": s.get("goal"),
        }
        for s in data.get("values", [])
    ]
    return {"total": data.get("total", len(sprints)), "sprints": sprints}


async def tool_get_sprint(
    sprint_id: int,
    include_issues: bool = True,
    limit: int = 50,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Get sprint details and optionally its issues.

    Args:
        sprint_id: The numeric ID of the sprint.
        include_issues: Whether to include the sprint's issues (default True).
        limit: Maximum issues to return (default 50, max 100).
    """
    LOGGER.info("jira_get_sprint", sprint_id=sprint_id)

    sprint = await _jira_agile_get(f"/sprint/{sprint_id}", ctx)
    result: Dict[str, Any] = {
        "id": sprint.get("id"),
        "name": sprint.get("name"),
        "state": sprint.get("state"),
        "startDate": sprint.get("startDate"),
        "endDate": sprint.get("endDate"),
        "completeDate": sprint.get("completeDate"),
        "goal": sprint.get("goal"),
    }

    if include_issues:
        params: Dict[str, Any] = {"maxResults": max(1, min(int(limit), 100))}
        issues_data = await _jira_agile_get(
            f"/sprint/{sprint_id}/issue", ctx, params=params
        )
        result["issues"] = [_simplify_issue(i) for i in issues_data.get("issues", [])]
        result["issueCount"] = issues_data.get("total", len(result["issues"]))

    return result


async def tool_get_backlog(
    board_id: int,
    limit: int = 50,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Get backlog issues for an agile board.

    Args:
        board_id: The numeric ID of the agile board.
        limit: Maximum issues to return (default 50, max 100).
    """
    LOGGER.info("jira_get_backlog", board_id=board_id)

    params: Dict[str, Any] = {"maxResults": max(1, min(int(limit), 100))}
    data = await _jira_agile_get(f"/board/{board_id}/backlog", ctx, params=params)

    issues = [_simplify_issue(i) for i in data.get("issues", [])]
    return {
        "total": data.get("total", len(issues)),
        "returned": len(issues),
        "issues": issues,
    }


async def tool_list_epics(
    board_id: int,
    limit: int = 50,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List epics for an agile board.

    Args:
        board_id: The numeric ID of the agile board.
        limit: Maximum results (default 50, max 100).
    """
    LOGGER.info("jira_list_epics", board_id=board_id)

    params: Dict[str, Any] = {"maxResults": max(1, min(int(limit), 100))}
    data = await _jira_agile_get(f"/board/{board_id}/epic", ctx, params=params)

    epics = [
        {
            "id": e.get("id"),
            "key": e.get("key"),
            "name": e.get("name"),
            "summary": e.get("summary"),
            "done": e.get("done", False),
        }
        for e in data.get("values", [])
    ]
    return {"total": data.get("total", len(epics)), "epics": epics}


async def tool_log_work(
    key: str,
    time_spent: str,
    comment: Optional[str] = None,
    started: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Log work (time tracking) on a Jira issue.

    Args:
        key: The issue key (e.g. PROJ-123).
        time_spent: Time spent in Jira duration format (e.g. "2h 30m", "1d").
        comment: Optional work description.
        started: Optional ISO-8601 datetime when work started.
                 Defaults to now if omitted.
    """
    LOGGER.info("jira_log_work", key=key, time_spent=time_spent)

    try:
        payload: Dict[str, Any] = {"timeSpent": time_spent}
        if comment:
            payload["comment"] = _build_adf(comment)
        if started:
            payload["started"] = started

        result = await _jira_post(f"/issue/{key}/worklog", payload, ctx)
        return {
            "success": True,
            "issueKey": key,
            "worklogId": result.get("id"),
            "timeSpent": result.get("timeSpent", time_spent),
            "author": (result.get("author", {}) or {}).get("displayName"),
        }
    except Exception as exc:
        LOGGER.error("jira_log_work_error", key=key, error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_my_issues(
    limit: int = 20,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Get issues assigned to the current user -- a quick 'my work' view.

    Args:
        limit: Maximum results (default 20, max 100).
    """
    LOGGER.info("jira_get_my_issues")

    safe_limit = max(1, min(int(limit), 100))
    jql = "assignee = currentUser() AND resolution = Unresolved ORDER BY updated DESC"
    data = await _jira_search(jql, max_results=safe_limit, fields=_SEARCH_FIELDS, ctx=ctx)

    issues = [_simplify_issue(i) for i in data.get("issues", [])]
    return {
        "total": data.get("total", 0),
        "returned": len(issues),
        "issues": issues,
    }


async def tool_list_projects(
    limit: int = 50,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List all Jira projects accessible to the current user.

    Args:
        limit: Maximum results (default 50, max 100).
    """
    LOGGER.info("jira_list_projects")

    safe_limit = max(1, min(int(limit), 100))
    data = await _jira_get(
        "/project/search", ctx, params={"maxResults": safe_limit}
    )
    projects = [
        {
            "id": p.get("id"),
            "key": p.get("key"),
            "name": p.get("name"),
            "style": p.get("style"),
            "isPrivate": p.get("isPrivate", False),
            "lead": (p.get("lead", {}) or {}).get("displayName"),
        }
        for p in data.get("values", [])
    ]
    return {"total": data.get("total", len(projects)), "projects": projects}


async def tool_list_versions(
    project_key: str,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """List versions/releases for a Jira project.

    Args:
        project_key: The Jira project key (e.g. 'PROJ').
    """
    LOGGER.info("jira_list_versions", project_key=project_key)

    data = await _jira_get(f"/project/{project_key}/versions", ctx)
    versions = [
        {
            "id": v.get("id"),
            "name": v.get("name"),
            "description": v.get("description"),
            "released": v.get("released", False),
            "archived": v.get("archived", False),
            "startDate": v.get("startDate"),
            "releaseDate": v.get("releaseDate"),
            "overdue": v.get("overdue", False),
            "projectId": v.get("projectId"),
        }
        for v in (data if isinstance(data, list) else data.get("values", []))
    ]
    return {"total": len(versions), "versions": versions}


async def tool_create_version(
    project_key: str,
    name: str,
    description: Optional[str] = None,
    start_date: Optional[str] = None,
    release_date: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Create a new version/release in a Jira project.

    Args:
        project_key: The Jira project key (e.g. 'PROJ').
        name: Version name (e.g. 'v2.1.0').
        description: Version description.
        start_date: Start date (YYYY-MM-DD).
        release_date: Planned release date (YYYY-MM-DD).
    """
    LOGGER.info("jira_create_version", project_key=project_key, name=name)

    body: Dict[str, Any] = {
        "name": name,
        "projectId": None,
    }

    projects = await _jira_get("/project/search", ctx, params={"keys": project_key})
    proj_list = projects.get("values", [])
    if proj_list:
        body["projectId"] = int(proj_list[0].get("id", 0))
    else:
        return {"success": False, "error": f"Project {project_key} not found"}

    if description:
        body["description"] = description
    if start_date:
        body["startDate"] = start_date
    if release_date:
        body["releaseDate"] = release_date

    try:
        result = await _jira_post("/version", body, ctx)
        return {
            "success": True,
            "version": {
                "id": result.get("id"),
                "name": result.get("name"),
                "description": result.get("description"),
                "startDate": result.get("startDate"),
                "releaseDate": result.get("releaseDate"),
            },
        }
    except Exception as exc:
        LOGGER.error("jira_create_version_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_update_version(
    version_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    release_date: Optional[str] = None,
    released: Optional[bool] = None,
    archived: Optional[bool] = None,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Update an existing version/release. Can be used to release or archive a version.

    Args:
        version_id: The Jira version ID (required).
        name: Updated version name.
        description: Updated description.
        release_date: Updated release date (YYYY-MM-DD).
        released: Set to true to mark version as released.
        archived: Set to true to archive the version.
    """
    LOGGER.info("jira_update_version", version_id=version_id)

    body: Dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description
    if release_date is not None:
        body["releaseDate"] = release_date
    if released is not None:
        body["released"] = released
    if archived is not None:
        body["archived"] = archived

    if not body:
        return {"success": False, "error": "No fields provided to update."}

    try:
        result = await _jira_put(f"/version/{version_id}", body, ctx)
        return {
            "success": True,
            "version": {
                "id": result.get("id", version_id),
                "name": result.get("name"),
                "description": result.get("description"),
                "released": result.get("released"),
                "archived": result.get("archived"),
                "releaseDate": result.get("releaseDate"),
            },
        }
    except Exception as exc:
        LOGGER.error("jira_update_version_error", error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Provider functions for TaskServer integration ───────────────────


async def provider_list_tasks(ctx: Optional[Context] = None) -> List[Dict[str, Any]]:
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
        ctx=ctx,
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
    completes and submits the form inside the widget -- this tool does not
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
    completes and submits the form inside the widget -- this tool does not
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


# ── Manager-focused tools ────────────────────────────────────────────

_OVERLOAD_THRESHOLD = 15


async def tool_get_team_workload(
    project_key: str = "",
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Show work distribution across the team for a manager view.

    Args:
        project_key: Optional Jira project key to scope results (e.g. "ENG").
    """
    LOGGER.info("jira_get_team_workload", project_key=project_key or "(all)")

    jql = "resolution = Unresolved"
    if project_key:
        jql = f'project = "{project_key}" AND {jql}'
    jql += " ORDER BY assignee ASC"

    data = await _jira_search(
        jql, max_results=100, fields=_SEARCH_FIELDS, ctx=ctx,
    )
    issues = data.get("issues", [])
    total = data.get("total", len(issues))

    assignee_map: Dict[str, Dict[str, Any]] = {}
    unassigned_count = 0

    for raw in issues:
        fields = raw.get("fields", {})
        assignee_obj = fields.get("assignee") or {}
        name = (
            assignee_obj.get("displayName")
            if isinstance(assignee_obj, dict)
            else None
        )

        priority = (
            fields.get("priority", {}).get("name", "None")
            if isinstance(fields.get("priority"), dict)
            else "None"
        )
        status_obj = fields.get("status", {})
        category = (
            status_obj.get("statusCategory", {}).get("name", "Unknown")
            if isinstance(status_obj, dict)
            else "Unknown"
        )

        if not name:
            unassigned_count += 1
            continue

        if name not in assignee_map:
            assignee_map[name] = {
                "assignee": name,
                "total": 0,
                "byPriority": {},
                "byStatusCategory": {},
            }
        entry = assignee_map[name]
        entry["total"] += 1
        entry["byPriority"][priority] = entry["byPriority"].get(priority, 0) + 1
        entry["byStatusCategory"][category] = (
            entry["byStatusCategory"].get(category, 0) + 1
        )

    members = sorted(assignee_map.values(), key=lambda m: m["total"], reverse=True)
    for m in members:
        m["overloaded"] = m["total"] > _OVERLOAD_THRESHOLD

    return {
        "projectKey": project_key or None,
        "totalUnresolved": total,
        "unassignedCount": unassigned_count,
        "teamSize": len(members),
        "overloadedCount": sum(1 for m in members if m["overloaded"]),
        "members": members,
    }


async def tool_get_team_sprint_health(
    board_id: int = 0,
    ctx: Optional[Context] = None,
) -> Dict[str, Any]:
    """Sprint health overview for engineering managers.

    Args:
        board_id: Optional board ID. When 0 or omitted, returns an error
                  asking the caller to supply a board ID.
    """
    LOGGER.info("jira_get_team_sprint_health", board_id=board_id)

    if not board_id:
        return {"error": "board_id is required. Use list_boards to find one."}

    params: Dict[str, Any] = {"state": "active"}
    sprints_data = await _jira_agile_get(
        f"/board/{board_id}/sprint", ctx, params=params,
    )
    active_sprints = sprints_data.get("values", [])
    if not active_sprints:
        return {"board_id": board_id, "sprints": [], "message": "No active sprints."}

    results: List[Dict[str, Any]] = []
    for sprint in active_sprints:
        sprint_id = sprint.get("id")
        sprint_name = sprint.get("name")
        end_date_str = sprint.get("endDate")

        days_remaining: Optional[float] = None
        if end_date_str:
            try:
                end_dt = datetime.fromisoformat(
                    end_date_str.replace("Z", "+00:00"),
                )
                days_remaining = max(
                    0.0,
                    round(
                        (end_dt - datetime.now(timezone.utc)).total_seconds()
                        / 86400,
                        1,
                    ),
                )
            except (ValueError, TypeError):
                pass

        issues_data = await _jira_agile_get(
            f"/sprint/{sprint_id}/issue", ctx, params={"maxResults": 100},
        )
        issues = issues_data.get("issues", [])
        total_issues = issues_data.get("total", len(issues))

        done_count = 0
        in_progress_count = 0
        todo_count = 0
        blocked_count = 0
        person_map: Dict[str, Dict[str, int]] = {}

        for raw in issues:
            fields = raw.get("fields", {})
            status_obj = fields.get("status", {})
            category = (
                status_obj.get("statusCategory", {}).get("name", "Unknown")
                if isinstance(status_obj, dict)
                else "Unknown"
            )

            if category == "Done":
                done_count += 1
            elif category == "In Progress":
                in_progress_count += 1
            else:
                todo_count += 1

            labels = fields.get("labels", [])
            status_name = (
                status_obj.get("name", "")
                if isinstance(status_obj, dict)
                else ""
            )
            if (
                "blocked" in [lbl.lower() for lbl in labels]
                or "blocked" in status_name.lower()
            ):
                blocked_count += 1

            assignee_obj = fields.get("assignee") or {}
            name = (
                assignee_obj.get("displayName")
                if isinstance(assignee_obj, dict)
                else None
            )
            if name:
                if name not in person_map:
                    person_map[name] = {"done": 0, "inProgress": 0, "toDo": 0}
                if category == "Done":
                    person_map[name]["done"] += 1
                elif category == "In Progress":
                    person_map[name]["inProgress"] += 1
                else:
                    person_map[name]["toDo"] += 1

        completion_pct = (
            round(done_count / total_issues * 100, 1) if total_issues else 0.0
        )
        work_remaining = total_issues - done_count

        contributions = [
            {"assignee": k, **v} for k, v in sorted(person_map.items())
        ]

        results.append({
            "sprintId": sprint_id,
            "sprintName": sprint_name,
            "startDate": sprint.get("startDate"),
            "endDate": end_date_str,
            "daysRemaining": days_remaining,
            "totalIssues": total_issues,
            "done": done_count,
            "inProgress": in_progress_count,
            "toDo": todo_count,
            "completionPct": completion_pct,
            "workRemaining": work_remaining,
            "blockedCount": blocked_count,
            "contributions": contributions,
        })

    return {"board_id": board_id, "sprints": results}


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
            "Transition a Jira issue to a new status. Called by the jira-issue widget when the user changes status."
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
        "name": "update_project",
        "func": tool_update_project,
        "summary": "Update an existing Jira project. Called by the create-project widget when the user submits an update.",
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/outputTemplate": "ui://widget/create-project.html",
            "openai/toolInvocation/invoking": "Updating project\u2026",
            "openai/toolInvocation/invoked": "Project updated.",
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
    {
        "name": "move_issues_to_sprint",
        "func": tool_move_issues_to_sprint,
        "summary": (
            "Move one or more issues into a sprint. Provide the sprint ID "
            "(from list_sprints) and a list of issue keys."
        ),
        "annotations": {"readOnlyHint": False},
    },
    {
        "name": "link_issues",
        "func": tool_link_issues,
        "summary": (
            "Create a link between two Jira issues. Common link types: "
            "'Blocks', 'Cloners', 'Duplicate', 'Relates'. "
            "The inward issue is the one that IS blocked/cloned/etc."
        ),
        "annotations": {"readOnlyHint": False},
    },
    {
        "name": "list_boards",
        "func": tool_list_boards,
        "summary": (
            "List agile boards (Scrum or Kanban) visible to the current user. "
            "Optionally filter by project key or board type."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_board",
        "func": tool_get_board,
        "summary": (
            "Get board details including column configuration for an agile board."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_sprints",
        "func": tool_list_sprints,
        "summary": (
            "List sprints for an agile board. Filter by state: active, future, or closed."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_sprint",
        "func": tool_get_sprint,
        "summary": (
            "Get sprint details and its issues. Use to view sprint progress "
            "and what work is planned, in progress, or done."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_backlog",
        "func": tool_get_backlog,
        "summary": (
            "Get backlog issues for an agile board -- items not yet assigned to a sprint."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_epics",
        "func": tool_list_epics,
        "summary": (
            "List epics for an agile board. Shows epic name, key, summary, and completion status."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "log_work",
        "func": tool_log_work,
        "summary": (
            "Log work (time tracking) on a Jira issue. "
            "Specify time spent in Jira format (e.g. '2h 30m', '1d')."
        ),
        "annotations": {"readOnlyHint": False},
    },
    {
        "name": "get_my_issues",
        "func": tool_get_my_issues,
        "summary": (
            "Get unresolved issues assigned to the current user -- "
            "a quick 'my work' view sorted by last updated."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_projects",
        "func": tool_list_projects,
        "summary": (
            "List all Jira projects accessible to the current user."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_team_workload",
        "func": tool_get_team_workload,
        "summary": (
            "Show work distribution across team members -- total issues, "
            "breakdown by priority and status, and overload warnings."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/team-sprint-health.html",
            "openai/toolInvocation/invoking": "Loading team workload…",
            "openai/toolInvocation/invoked": "Team workload ready.",
        },
    },
    {
        "name": "get_team_sprint_health",
        "func": tool_get_team_sprint_health,
        "summary": (
            "Sprint health overview for engineering managers -- completion "
            "percentage, blocked items, per-person contributions, and "
            "days remaining."
        ),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "list_versions",
        "func": tool_list_versions,
        "summary": "List versions/releases for a Jira project. Shows release status, dates, and whether versions are overdue.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "create_version",
        "func": tool_create_version,
        "summary": "Create a new version/release in a Jira project with name, description, and planned release date.",
        "annotations": {"readOnlyHint": False},
    },
    {
        "name": "update_version",
        "func": tool_update_version,
        "summary": "Update a Jira version/release. Use to mark as released, update release date, or archive.",
        "annotations": {"readOnlyHint": False},
    },
]
