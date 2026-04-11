"""Workday MCP server – registers tools, resources, and prompts with FastMCP."""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.resources import TextResource

from .resources import WORKDAY_RESOURCES
from .tools import WORKDAY_TOOL_SPECS


def build_workday_server() -> FastMCP:
    """Create and return a fully-configured Workday MCP server."""
    mcp = FastMCP(
        "workday",
        instructions=(
            "Workday employee self-service for HR, compensation, benefits, "
            "and time management."
        ),
    )

    # ── Register tools ──────────────────────────────────────────────────
    for spec in WORKDAY_TOOL_SPECS:
        kwargs: dict = {"name": spec["name"], "description": spec["summary"]}
        annotations = spec.get("annotations")
        if annotations:
            kwargs["annotations"] = annotations
        meta = spec.get("meta")
        if meta:
            kwargs["meta"] = meta
        mcp.tool(**kwargs)(spec["func"])

    # ── Register resources ──────────────────────────────────────────────
    for name, res in WORKDAY_RESOURCES.items():
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
