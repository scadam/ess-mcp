"""Read-only follow-up probe: raw incident fields, knowledge coverage for common symptoms, one incident's history."""

import asyncio
import json
import os

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

URL = "https://essmcp-caldova-servicenow.livelysky-91807d17.eastus2.azurecontainerapps.io/servicenow/mcp"


def text(result) -> str:
    return "\n".join(getattr(part, "text", "") or "" for part in (getattr(result, "content", None) or []))


async def call(name, args):
    async with Client(StreamableHttpTransport(URL)) as client:
        return text(await client.call_tool(name, args))


async def main() -> None:
    out = {}
    incidents = json.loads(await call("list_incidents", {"active": True, "limit": 100}))
    out["incident_fields"] = sorted(incidents["incidents"][0])
    out["incident_samples"] = incidents["incidents"][:3]
    for query in ("email", "password", "VPN", "wifi", "printer", "SAP", "file share", "outlook", "reset", "laptop"):
        data = json.loads(await call("search_knowledge", {"search_text": query, "limit": 10}))
        out[f"kb:{query}"] = [(a.get("number"), a.get("short_description")) for a in data.get("articles", [])]
    out["incident_detail"] = json.loads(await call("get_incident", {"number": "INC0000020"}))
    catalog = json.loads(await call("list_catalog_items", {"search": "iPhone", "limit": 5}))
    out["catalog_iphone"] = catalog.get("items", [])[:3]
    with open(os.path.join(os.environ["TEMP"], "ap-itsm-probe2.json"), "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=1, default=str)


asyncio.run(main())
