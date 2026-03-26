"""Check raw wire-format JSON for tools/list meta fields via SSE.

SSE transport: one persistent GET /<name>/sse connection receives all responses.
POST /<name>/messages/?session_id=... sends requests.

Streamable-HTTP transport: POST /<name>/mcp for all JSON-RPC messages.
"""
import asyncio
import json
import httpx
import httpx_sse


BASE = "https://m365copilot-mcp-app.redground-c0937a09.eastus.azurecontainerapps.io"
# Per-server SSE endpoint (use /servicenow/sse or /workday/sse)
SSE_PATH = "/servicenow/sse"


async def main():
    async with httpx.AsyncClient(timeout=60) as client:
        responses: dict[int, asyncio.Future] = {}

        messages_url = None
        ready = asyncio.Event()

        async def sse_reader():
            nonlocal messages_url
            async with httpx_sse.aconnect_sse(client, "GET", f"{BASE}{SSE_PATH}") as sse:
                async for event in sse.aiter_sse():
                    if event.event == "endpoint":
                        messages_url = BASE + event.data
                        ready.set()
                        continue
                    if event.event == "message":
                        data = json.loads(event.data)
                        rid = data.get("id")
                        if rid and rid in responses:
                            responses[rid].set_result(data)

        reader_task = asyncio.create_task(sse_reader())
        await asyncio.wait_for(ready.wait(), timeout=15)
        print(f"Messages URL: {messages_url}")

        async def rpc(method, params=None, rid=None):
            payload = {"jsonrpc": "2.0", "method": method}
            if rid is not None:
                payload["id"] = rid
                responses[rid] = asyncio.get_event_loop().create_future()
            if params is not None:
                payload["params"] = params
            resp = await client.post(messages_url, json=payload, headers={"Content-Type": "application/json"})
            print(f"POST {method} → {resp.status_code}")
            if rid is not None:
                return await asyncio.wait_for(responses[rid], timeout=15)
            return None

        # Initialize
        init = await rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1.0"}}, rid=1)
        print(f"Protocol: {init['result']['protocolVersion']}")

        await rpc("notifications/initialized")

        # tools/list
        tools_resp = await rpc("tools/list", {}, rid=10)
        tools = tools_resp.get("result", {}).get("tools", [])
        print(f"\n{'='*70}")
        print(f"tools/list: {len(tools)} tools")
        print(f"{'='*70}")
        for t in tools:
            name = t["name"]
            meta = t.get("_meta")
            annot = t.get("annotations")
            if name in ("list_incidents", "create_incident", "get_worker"):
                print(f"\n  TOOL: {name}")
                print(f"    _meta: {json.dumps(meta, indent=6)}")
                print(f"    annotations: {json.dumps(annot, indent=6) if annot else 'None'}")

        reader_task.cancel()


asyncio.run(main())
