"""Coupa MCP server – registers tools, resources, and prompts with FastMCP."""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.resources import TextResource

from .resources import COUPA_RESOURCES
from .tools import COUPA_TOOL_SPECS


def build_coupa_server() -> FastMCP:
    mcp = FastMCP(
        "coupa",
        instructions=(
            "Coupa procurement self-service for invoices, purchase orders, "
            "requisitions, goods receipts, catalog ordering, supplier management, "
            "and approval workflows. All responses are mocked."
        ),
    )

    for spec in COUPA_TOOL_SPECS:
        kwargs: dict = {"name": spec["name"], "description": spec["summary"]}
        if annotations := spec.get("annotations"):
            kwargs["annotations"] = annotations
        if meta := spec.get("meta"):
            kwargs["meta"] = meta
        mcp.tool(**kwargs)(spec["func"])

    for name, res in COUPA_RESOURCES.items():
        resource_kwargs: dict = {
            "uri": f"ui://widget/{name}.html",
            "name": name,
            "description": res["description"],
            "mime_type": res["mime_type"],
            "text": res["content"],
        }
        if meta := res.get("meta"):
            resource_kwargs["meta"] = meta
        mcp.add_resource(TextResource(**resource_kwargs))

    return mcp
