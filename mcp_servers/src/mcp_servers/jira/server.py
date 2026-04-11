"""Jira MCP server – registers tools, resources, and prompts with FastMCP."""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.resources import TextResource

from .resources import JIRA_RESOURCES
from .tools import JIRA_TOOL_SPECS


def build_jira_server() -> FastMCP:
    """Create and return a fully-configured Jira MCP server."""
    mcp = FastMCP(
        "jira",
        instructions=(
            "Jira project management, agile boards, sprints, epics, "
            "and issue tracking."
        ),
    )

    # ── Register tools ──────────────────────────────────────────────────
    for spec in JIRA_TOOL_SPECS:
        kwargs: dict = {"name": spec["name"], "description": spec["summary"]}
        annotations = spec.get("annotations")
        if annotations:
            kwargs["annotations"] = annotations
        meta = spec.get("meta")
        if meta:
            kwargs["meta"] = meta
        mcp.tool(**kwargs)(spec["func"])

    # ── Register resources ──────────────────────────────────────────────
    for name, res in JIRA_RESOURCES.items():
        resource_kwargs: dict = {
            "uri": f"ui://widget/{name}.html",
            "name": name,
            "description": res["description"],
            "mime_type": res["mime_type"],
            "text": res["content"],
        }
        meta = res.get("meta")
        if meta:
            resource_kwargs["meta"] = meta
        mcp.add_resource(TextResource(**resource_kwargs))

    return mcp
