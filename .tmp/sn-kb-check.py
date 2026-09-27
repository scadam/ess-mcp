"""Look up the crash-scene knowledge article regardless of workflow state (read-only)."""
import asyncio
import json

from fastmcp import Client

URL = "https://essmcp-caldova-servicenow.livelysky-91807d17.eastus2.azurecontainerapps.io/servicenow/mcp"


async def main() -> None:
    async with Client(URL) as client:
        for args in ({"table": "kb_knowledge", "search": "Laptop crashes", "limit": 5},):
            try:
                result = await client.call_tool("search_reference_values", args)
                print("kb_knowledge:", json.dumps(result.structured_content or result.data)[:500])
            except Exception as error:
                print("search_reference_values failed:", str(error)[:300])
        for text in ("Latitude 7440", "blue screens", "password", "Laptop crashes"):
            result = await client.call_tool("search_knowledge", {"search_text": text})
            print(f"search_knowledge {text!r}:", json.dumps(result.structured_content or result.data)[:300])


asyncio.run(main())
