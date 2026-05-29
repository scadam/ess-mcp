"""Validate the deployed Salesforce MCP server: health, tools/list, and a sample tool call.

Usage:
  python scripts/validate_salesforce_deploy.py [BASE_URL] [BEARER_TOKEN]

If no BEARER_TOKEN is supplied, no Authorization header is sent — exercising the
client-credentials fallback flow on the server.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
import urllib.error

DEFAULT_BASE = "https://essmcp-salesforce.wittysand-460bf1d9.eastus.azurecontainerapps.io"
MCP_PATH = "/salesforce/mcp"


def _post(url: str, body: dict, headers: dict, timeout: int = 30) -> tuple[int, dict, str]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return resp.status, dict(resp.headers), raw
    except urllib.error.HTTPError as e:  # noqa: PERF203
        raw = e.read().decode("utf-8", errors="replace") if e.fp else ""
        return e.code, dict(e.headers or {}), raw


def _parse_sse_or_json(body: str) -> dict | None:
    body = body.strip()
    if not body:
        return None
    if body.startswith("{"):
        try:
            return json.loads(body)
        except Exception:
            return None
    # SSE: "event: message\ndata: {...}\n\n"
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload.startswith("{"):
                try:
                    return json.loads(payload)
                except Exception:
                    continue
    return None


def main() -> int:
    base = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE
    bearer = sys.argv[2] if len(sys.argv) > 2 else None
    base = base.rstrip("/")
    mcp_url = base + MCP_PATH

    auth_hdr = {"Authorization": f"Bearer {bearer}"} if bearer else {}

    print(f"=== Salesforce MCP validation ===")
    print(f"URL        : {mcp_url}")
    print(f"Auth header: {'set' if bearer else 'OMITTED (client-credentials fallback)'}")
    print()

    # 1) Health
    print("[1/3] GET /healthz")
    try:
        with urllib.request.urlopen(base + "/healthz", timeout=15) as r:
            print(f"  -> {r.status} {r.read().decode('utf-8')}")
    except Exception as e:  # noqa: BLE001
        print(f"  -> ERROR: {e}")
        return 2

    # 2) Initialize
    print("\n[2/3] initialize + tools/list")
    init_body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "validate-script", "version": "1.0"},
        },
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        **auth_hdr,
    }
    status, resp_headers, body = _post(mcp_url, init_body, headers)
    sid = resp_headers.get("mcp-session-id") or resp_headers.get("Mcp-Session-Id")
    print(f"  initialize -> HTTP {status} | session={sid!r}")
    if status >= 400:
        print(f"  body: {body[:600]}")
        return 3

    # notifications/initialized
    headers_sid = {**headers, "mcp-session-id": sid or ""}
    _post(mcp_url, {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, headers_sid)

    # tools/list
    list_body = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    status, _h, body = _post(mcp_url, list_body, headers_sid)
    parsed = _parse_sse_or_json(body)
    print(f"  tools/list -> HTTP {status}")
    if not parsed:
        print(f"  raw body: {body[:1200]}")
        return 4
    tools = (parsed.get("result") or {}).get("tools") or []
    print(f"  tools count: {len(tools)}")
    for t in tools[:10]:
        print(f"    - {t.get('name')}")

    # 3) Tool call: list_tasks with limit 1
    print("\n[3/3] tools/call list_tasks limit=1")
    call_body = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "list_tasks", "arguments": {"limit": 1}},
    }
    status, _h, body = _post(mcp_url, call_body, headers_sid, timeout=60)
    parsed = _parse_sse_or_json(body) or {}
    print(f"  tools/call -> HTTP {status}")
    result = parsed.get("result") or parsed.get("error") or parsed
    out = json.dumps(result, indent=2, default=str)
    print(f"  result (first 1500 chars):\n{out[:1500]}")

    # Heuristic: did the call succeed?
    err_text = json.dumps(parsed)
    if "Authorization: Bearer" in err_text or "Authorization header" in err_text:
        print("\n[CONCLUSION] Server still requires bearer token — client-credentials fallback NOT active.")
        return 10
    if status >= 400 or parsed.get("error"):
        print("\n[CONCLUSION] tools/call failed for another reason — see body above.")
        return 11
    print("\n[CONCLUSION] tools/call succeeded.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
