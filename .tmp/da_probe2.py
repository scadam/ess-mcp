"""Probe a few extra tools (read-only) to choose working prompts and check the catalog category path."""

import asyncio
import json
import os
from pathlib import Path

from fastmcp import Client

BASE = "https://essmcp-caldova-{0}.livelysky-91807d17.eastus2.azurecontainerapps.io/{0}/mcp"
out = open(Path(os.environ["TEMP"]) / "ap-da-probe2.txt", "w", encoding="utf-8")


async def probe(server: str, tool: str, args: dict | None = None) -> None:
    try:
        async with Client(BASE.format(server), timeout=90) as client:
            result = await client.call_tool(tool, args or {}, raise_on_error=False)
        text = next((block.text for block in result.content or [] if getattr(block, "text", None)), "")
        try:
            data = json.loads(text)
        except ValueError:
            data = {"text": text[:300]}
        keys = {key: (f"list[{len(value)}]" if isinstance(value, list) else type(value).__name__)
                for key, value in (data.items() if isinstance(data, dict) else []) if not key.startswith("_")}
        out.write(f"{'ERR ' if result.is_error else 'ok  '}{server}.{tool} {json.dumps(args or {})} -> {json.dumps(keys)[:400]}\n")
        if result.is_error or (isinstance(data, dict) and data.get("text")):
            out.write(f"     {str(data)[:300]}\n")
        (Path(os.environ["TEMP"]) / "da-tests" / f"{server}.{tool}.probe.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        out.write(f"FAIL {server}.{tool} {json.dumps(args or {})} -> {type(exc).__name__}: {str(exc)[:200]}\n")
    out.flush()


async def main() -> None:
    for tool, args in [("get_pay_slips", {}), ("get_learning_assignments", {}), ("search_learning_content", {}),
                       ("get_learning_records", {}), ("get_worker_skills", {}), ("get_feedback", {}), ("get_goals", {}),
                       ("get_development_items", {}), ("get_feedback_badges", {}), ("get_check_in_topics", {})]:
        await probe("workday", tool, args)
    await probe("servicenow", "list_catalog_categories", {"catalog_sys_id": "e0d08b13c3330100c8b837659bba8fb4", "limit": 30})
    for term in ("wireless", "network", "outlook", "printer", "email", "slow", "Windows", "lock"):
        await probe("servicenow", "search_knowledge", {"search_text": term, "limit": 5})
    for term in ("monitor", "keyboard", "headset", "iphone", "mouse"):
        await probe("servicenow", "list_catalog_items", {"search": term, "limit": 10})


asyncio.run(main())
out.close()
