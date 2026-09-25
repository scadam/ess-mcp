"""Read-only probe of the Caldova MCP servers: which tools exist and which return data.

Only tools whose names read as queries are called; writes, forms and prepares are listed, never invoked.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

BASE = "https://essmcp-caldova-{host}.livelysky-91807d17.eastus2.azurecontainerapps.io/{path}/mcp"
SERVERS = {
    "workday": ("workday", "workday"), "servicenow": ("servicenow", "servicenow"),
    "salesforce": ("salesforce", "salesforce"), "coupa": ("coupa", "coupa"),
    "ariba": ("ariba", "ariba"), "sap_sf": ("sap-sf", "sap_sf"), "jira": ("jira", "jira"),
}
READ = re.compile(r"^(?:get|list|search|find|lookup|read|check|query|describe|count)(?:_|$)")
ID_KEY = re.compile(r"(?:^|_)(?:id|number|key|code|sys_id)$|Id$|Number$|Key$", re.I)


def _texts(result) -> str:
    structured = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if structured is not None:
        return json.dumps(structured, default=str)
    return "\n".join(getattr(part, "text", "") or "" for part in (getattr(result, "content", None) or []))


def _harvest(value, pool: dict[str, list[str]], depth: int = 0) -> None:
    if depth > 6:
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, (str, int)) and ID_KEY.search(str(key)) and str(item).strip():
                bucket = pool.setdefault(str(key).lower(), [])
                if str(item) not in bucket and len(bucket) < 5:
                    bucket.append(str(item))
            else:
                _harvest(item, pool, depth + 1)
    elif isinstance(value, list):
        for item in value[:10]:
            _harvest(item, pool, depth + 1)


def _fill(schema: dict, pool: dict[str, list[str]]) -> dict | None:
    required = schema.get("required") or []
    props = schema.get("properties") or {}
    args: dict = {}
    for name in required:
        key = name.lower()
        candidates = pool.get(key) or next((values for pool_key, values in pool.items()
                                           if pool_key.endswith(key) or key.endswith(pool_key)), None)
        if not candidates:
            return None
        kind = (props.get(name) or {}).get("type")
        args[name] = int(candidates[0]) if kind == "integer" and candidates[0].isdigit() else candidates[0]
    return args


def _summary(text: str) -> str:
    try:
        data = json.loads(text)
    except ValueError:
        return f"text {len(text)} chars"
    if isinstance(data, dict):
        counts = {key: len(value) for key, value in data.items() if isinstance(value, list)}
        return f"keys={list(data)[:8]} lists={counts}"
    if isinstance(data, list):
        return f"list[{len(data)}]"
    return type(data).__name__


async def probe(name: str) -> dict:
    host, path = SERVERS[name]
    report = {"server": name, "tools": []}
    pool: dict[str, list[str]] = {}
    try:
        async with Client(StreamableHttpTransport(BASE.format(host=host, path=path)), timeout=45, init_timeout=45) as client:
            tools = await client.list_tools()
            pending = []
            for tool in tools:
                schema = tool.inputSchema or {}
                entry = {"tool": tool.name, "required": schema.get("required") or [],
                         "description": (tool.description or "").strip().split("\n")[0][:140]}
                report["tools"].append(entry)
                if not READ.match(tool.name):
                    entry["status"] = "write-or-form (not called)"
                else:
                    pending.append((tool, entry))
            for attempt in range(2):  # Second pass fills ids harvested from the first pass.
                for tool, entry in pending:
                    if entry.get("status") in {"data", "empty", "error"}:
                        continue
                    schema = tool.inputSchema or {}
                    args = {} if not schema.get("required") else _fill(schema, pool)
                    if args is None:
                        entry["status"] = "needs-args"
                        continue
                    started = time.time()
                    try:
                        result = await asyncio.wait_for(client.call_tool_mcp(tool.name, args), 40)
                        text = _texts(result)
                        if getattr(result, "isError", False):
                            entry.update(status="error", detail=text[:200])
                        else:
                            try:
                                _harvest(json.loads(text), pool)
                            except ValueError:
                                pass
                            empty = len(text.strip()) < 30 or re.search(r'"(?:total|count)"\s*:\s*0\b', text)
                            entry.update(status="empty" if empty else "data", size=len(text), shape=_summary(text))
                        entry["args"] = args
                    except Exception as exc:  # noqa: BLE001 - probe records failures
                        entry.update(status="error", detail=f"{type(exc).__name__}: {str(exc)[:160]}")
                    entry["ms"] = int((time.time() - started) * 1000)
    except Exception as exc:  # noqa: BLE001
        report["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
    return report


async def main() -> None:
    names = sys.argv[1:] or list(SERVERS)
    reports = await asyncio.gather(*(probe(name) for name in names))
    out = os.path.join(os.environ.get("TEMP", "."), "ap-tool-probe.json")
    with open(out, "w", encoding="utf-8") as handle:
        json.dump(reports, handle, indent=1)
    for report in reports:
        tools = report["tools"]
        counts = {}
        for entry in tools:
            counts[entry.get("status", "?")] = counts.get(entry.get("status", "?"), 0) + 1
        print(report["server"], len(tools), counts, report.get("error", ""))


if __name__ == "__main__":
    asyncio.run(main())
