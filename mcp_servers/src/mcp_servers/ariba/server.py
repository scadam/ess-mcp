"""SAP Ariba MCP server – registers tools, resources, and prompts with FastMCP."""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.resources import TextResource

from .resources import ARIBA_RESOURCES
from .tools import ARIBA_TOOL_SPECS


def build_ariba_server() -> FastMCP:
    mcp = FastMCP(
        "ariba",
        instructions=(
            "SAP Ariba procurement self-service for invoices, purchase orders, "
            "requisitions, goods receipts, catalog ordering, supplier management, "
            "and approval workflows."
        ),
    )

    for spec in ARIBA_TOOL_SPECS:
        kwargs: dict = {"name": spec["name"], "description": spec["summary"]}
        if annotations := spec.get("annotations"):
            kwargs["annotations"] = annotations
        if meta := spec.get("meta"):
            kwargs["meta"] = meta
        mcp.tool(**kwargs)(spec["func"])

    for name, res in ARIBA_RESOURCES.items():
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
