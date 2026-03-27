"""ServiceNow MCP server – registers tools, resources, and prompts with FastMCP."""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.resources import TextResource

from .resources import SERVICENOW_RESOURCES
from .tools import SERVICENOW_TOOL_SPECS


def build_servicenow_server() -> FastMCP:
    """Create and return a fully-configured ServiceNow MCP server."""
    mcp = FastMCP(
        "servicenow",
        instructions=(
            "ServiceNow employee self-service for incidents, changes, problems, "
            "approvals, service catalog, knowledge base, and CMDB."
        ),
    )

    # ── Register tools ──────────────────────────────────────────────────
    for spec in SERVICENOW_TOOL_SPECS:
        kwargs: dict = {"name": spec["name"], "description": spec["summary"]}
        annotations = spec.get("annotations")
        if annotations:
            kwargs["annotations"] = annotations
        meta = spec.get("meta")
        if meta:
            kwargs["meta"] = meta
        mcp.tool(**kwargs)(spec["func"])

    # ── Register resources ──────────────────────────────────────────────
    for name, res in SERVICENOW_RESOURCES.items():
        resource_kwargs: dict = {
            "uri": f"ui://servicenow/{name}",
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
