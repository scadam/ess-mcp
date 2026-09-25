"""Workday read tools, one fresh MCP session per call (a 403 on one tool drops the whole session)."""

import asyncio
import json
import os
import sys

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

URL = "https://essmcp-caldova-workday.livelysky-91807d17.eastus2.azurecontainerapps.io/workday/mcp"
TOOLS = sys.argv[1:] or [
    "get_goals", "get_feedback", "get_feedback_badges", "get_development_items", "get_learning_records",
    "get_check_ins", "get_check_in_topics", "get_worker_skills", "get_team_goals", "get_job_profiles",
    "get_job_profile", "get_job_families", "get_jobs", "get_job_requisitions", "get_supervisory_orgs",
    "get_supervisory_org_members", "get_job_change_reasons", "get_job_change",
]


async def call(name: str) -> str:
    try:
        async with Client(StreamableHttpTransport(URL), timeout=45, init_timeout=45) as client:
            result = await asyncio.wait_for(client.call_tool_mcp(name, {}), 40)
            parts = "\n".join(getattr(part, "text", "") or "" for part in (result.content or []))
            structured = getattr(result, "structuredContent", None)
            text = json.dumps(structured, default=str) if structured is not None else parts
            state = "error" if result.isError else "ok"
            return f"[{state}] {name} {len(text)} chars :: {text[:220]}"
    except Exception as exc:  # noqa: BLE001
        return f"[fail] {name} {type(exc).__name__}: {str(exc)[:160]}"


async def main() -> None:
    lines = [await call(name) for name in TOOLS]
    out = os.path.join(os.environ.get("TEMP", "."), "ap-probe-wd2.txt")
    open(out, "w", encoding="utf-8").write("\n".join(lines))
    print(len(lines))


asyncio.run(main())
