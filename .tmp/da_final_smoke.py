import asyncio
import json
import os
from pathlib import Path

from fastmcp import Client

BASE = "https://essmcp-caldova-{0}.livelysky-91807d17.eastus2.azurecontainerapps.io/{0}/mcp"
out = open(Path(os.environ["TEMP"]) / "ap-da-final-smoke.txt", "w", encoding="utf-8")


async def call(server, tool, args):
    async with Client(BASE.format(server), timeout=90) as client:
        result = await client.call_tool(tool, args, raise_on_error=False)
    text = next((block.text for block in result.content or [] if getattr(block, "text", None)), "")
    out.write(f"{'ERR' if result.is_error else 'ok '} {server}.{tool}: {text[:260]}\n")


async def main():
    await call("servicenow", "get_knowledge_article", {"sys_id": "931f95cbdb013200a042f278f0b8f508"})
    await call("servicenow", "show_create_incident_form", {"short_description": "Locked out of my laptop after too many password attempts",
                                                           "description": "Tried KB0005012 steps.", "category": "inquiry", "urgency": "2"})
    # The Coupa demo server only echoes a rejection; it stores nothing.
    await call("coupa", "reject_invoice", {"invoice_id": "50412", "reason": "Smoke test of the rejection path."})


asyncio.run(main())
out.close()
