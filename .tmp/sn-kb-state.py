"""Find the crash-scene knowledge article(s) and print their workflow state (read-only)."""
import asyncio
import json

from fastmcp import Client

URL = "https://essmcp-caldova-servicenow.livelysky-91807d17.eastus2.azurecontainerapps.io/servicenow/mcp"


def _data(result):
    return result.structured_content or result.data or json.loads(result.content[0].text)


async def main() -> None:
    async with Client(URL) as client:
        refs = _data(await client.call_tool("search_reference_values",
                                            {"table": "kb_knowledge", "search": "Latitude 7440", "limit": 100}))
        ids = [row["sys_id"] for row in refs.get("results", [])]
        print("candidates:", len(ids))
        found = 0
        for sys_id in ids:
            article = _data(await client.call_tool("get_knowledge_article", {"sys_id": sys_id}))
            text = json.dumps(article)
            if "Latitude 7440" in text and "Laptop crashes" in text:
                found += 1
                keep = {k: article.get(k) for k in ("number", "short_description", "state", "workflow_state",
                                                     "knowledge_base", "valid_to", "published", "sys_updated_on")}
                print(json.dumps(keep)[:400])
        print("matching articles:", found)


asyncio.run(main())
