import asyncio
import json
import os
from pathlib import Path

from fastmcp import Client

URL = "https://essmcp-caldova-servicenow.livelysky-91807d17.eastus2.azurecontainerapps.io/servicenow/mcp"
out = open(Path(os.environ["TEMP"]) / "ap-sn-catalog.txt", "w", encoding="utf-8")


async def main() -> None:
    async with Client(URL, timeout=90) as client:
        for term in ("laptop", "monitor", "keyboard", "headset", "iphone", "mouse", "dock", "ipad"):
            result = await client.call_tool("list_catalog_items", {"search": term, "limit": 10}, raise_on_error=False)
            data = json.loads(next(block.text for block in result.content if getattr(block, "text", None)))
            out.write(f"{term}: " + " | ".join(f"{item['name']} [{item.get('short_description', '')[:40]}] {item.get('price')}"
                                               for item in data.get("items", [])) + "\n")
        result = await client.call_tool("show_create_incident_form", {"short_description": "Locked out of laptop"}, raise_on_error=False)
        text = next(block.text for block in result.content if getattr(block, "text", None))
        out.write(f"incident form error={result.is_error}: {text[:300]}\n")
        result = await client.call_tool("list_catalog_categories", {"limit": 30}, raise_on_error=False)
        data = json.loads(next(block.text for block in result.content if getattr(block, "text", None)))
        out.write(f"categories default: {data.get('total_returned')} e.g. {[item.get('title') for item in data.get('categories', [])][:8]}\n")


asyncio.run(main())
out.close()
