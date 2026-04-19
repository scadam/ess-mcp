"""SAP SuccessFactors MCP server – registers tools, resources, and prompts with FastMCP."""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.resources import TextResource

from .resources import SAP_SF_RESOURCES
from .tools import SAP_SF_TOOL_SPECS


def build_sap_sf_server() -> FastMCP:
    """Create and return a fully-configured SAP SuccessFactors MCP server."""
    mcp = FastMCP(
        "sap_sf",
        instructions=(
            "SAP SuccessFactors employee self-service for personal data, "
            "leave management, pay stubs, org hierarchy, position management, "
            "background checks, and employee documents."
        ),
    )

    # ── Register tools ──────────────────────────────────────────────────
    for spec in SAP_SF_TOOL_SPECS:
        kwargs: dict = {"name": spec["name"], "description": spec["summary"]}
        annotations = spec.get("annotations")
        if annotations:
            kwargs["annotations"] = annotations
        meta = spec.get("meta")
        if meta:
            kwargs["meta"] = meta
        mcp.tool(**kwargs)(spec["func"])

    # ── Register resources ──────────────────────────────────────────────
    for name, res in SAP_SF_RESOURCES.items():
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
