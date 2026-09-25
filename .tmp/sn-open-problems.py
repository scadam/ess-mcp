"""Read-only: show the open problems the live triage matched (number, state, title only)."""

import asyncio
import json

from fastmcp import Client

URL = "https://essmcp-caldova-servicenow.livelysky-91807d17.eastus2.azurecontainerapps.io/servicenow/mcp"


async def main() -> None:
    async with Client(URL, timeout=60) as client:
        result = await client.call_tool("list_problems", {"limit": 50})
    data = json.loads(result.content[0].text)
    for problem in data.get("problems", []):
        if problem.get("state") not in {"Closed", "Resolved", "Canceled"}:
            print(problem.get("number"), "|", problem.get("state"), "|", " ".join(str(problem.get("short_description")).split())[:90])


asyncio.run(main())
