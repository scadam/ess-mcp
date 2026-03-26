"""Check if tool metadata survives import_server."""
import asyncio
from mcp_servers.cli import build_combined_server


async def check():
    root = await build_combined_server()
    tm = root._tool_manager
    for name, tool in tm._tools.items():
        if name in ("list_incidents", "create_incident", "get_worker"):
            print(f"TOOL: {name}")
            print(f"  annotations: {tool.annotations}")
            meta = getattr(tool, "meta", "NOT_FOUND")
            print(f"  meta: {meta}")
            # Check all attributes
            for attr in sorted(dir(tool)):
                if not attr.startswith("__"):
                    val = getattr(tool, attr)
                    if not callable(val):
                        print(f"  {attr}: {val}")
            print()


asyncio.run(check())
