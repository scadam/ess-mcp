"""CLI entry point for running MCP servers."""
from __future__ import annotations
import argparse
import asyncio
import json as _json
from contextlib import asynccontextmanager
from typing import Dict, List
import uvicorn
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from .jira import build_jira_server
from .logging import configure_logging, get_logger
from .salesforce import build_salesforce_server
from .servicenow import build_servicenow_server
from .workday import build_workday_server

LOGGER = get_logger(__name__)

# ── Auth-error passthrough ──────────────────────────────────────────
# M365 Copilot declarative agents rely on the *HTTP status code* to
# trigger OAuth re-authentication.  FastMCP always returns HTTP 200 for
# MCP protocol responses, even when a tool encounters a backend 401.
# This middleware inspects JSON-RPC response bodies and, when a backend
# 401/403 is detected inside an MCP tool error, rewrites the HTTP status
# so the agent's token service initiates a token refresh.


def _detect_auth_error_status(body: bytes) -> int:
    """Return 401 or 403 if the JSON-RPC body signals a backend auth failure."""
    try:
        data = _json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return 0

    # Path 1 – JSON-RPC error object
    error = data.get("error") if isinstance(data, dict) else None
    if isinstance(error, dict):
        msg = str(error.get("message", ""))
        if "401" in msg and "nauthorized" in msg:
            return 401
        if "403" in msg and "orbidden" in msg:
            return 403

    # Path 2 – MCP CallToolResult with isError
    result = data.get("result") if isinstance(data, dict) else None
    if isinstance(result, dict) and result.get("isError"):
        for item in result.get("content", []):
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", ""))
            if "401 Unauthorized" in text:
                return 401
            if "403 Forbidden" in text:
                return 403

    return 0


class AuthErrorPassthroughMiddleware:
    """ASGI middleware that rewrites HTTP 200 → 401/403 for MCP auth errors."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_message = None
        body_chunks: list[bytes] = []
        is_sse = False

        async def buffered_send(message):
            nonlocal start_message, is_sse

            if message["type"] == "http.response.start":
                start_message = message
                # Detect SSE (streaming) – pass through immediately
                for key, val in message.get("headers", []):
                    if key in (b"content-type", "content-type"):
                        val_str = val if isinstance(val, str) else val.decode("latin-1")
                        if "text/event-stream" in val_str:
                            is_sse = True
                            break
                if is_sse:
                    await send(message)
                return

            if message["type"] == "http.response.body":
                if is_sse:
                    await send(message)
                    return

                body = message.get("body", b"")
                more_body = message.get("more_body", False)
                body_chunks.append(body)

                if not more_body:
                    full_body = b"".join(body_chunks)
                    status = start_message.get("status", 200) if start_message else 200

                    if status == 200:
                        auth_status = _detect_auth_error_status(full_body)
                        if auth_status:
                            status = auth_status

                    # Forward (possibly rewritten) start + body
                    out_start = dict(start_message) if start_message else {
                        "type": "http.response.start", "headers": [],
                    }
                    out_start["status"] = status
                    await send(out_start)
                    await send({"type": "http.response.body", "body": full_body})
                else:
                    # Chunked non-SSE – unlikely for MCP, forward as-is
                    if start_message:
                        await send(start_message)
                        start_message = None
                    await send(message)

        await self.app(scope, receive, buffered_send)


# ── Server registry ─────────────────────────────────────────────────

SERVER_BUILDERS: Dict[str, callable] = {
    "workday": build_workday_server,
    "servicenow": build_servicenow_server,
    "salesforce": build_salesforce_server,
    "jira": build_jira_server,
}


def _mount_server(server: FastMCP, name: str, transport: str) -> tuple[Mount, list]:
    routes: list = []
    lifespan_apps: list = []
    if transport in ("sse", "both"):
        sse_path = "/sse" if transport == "both" else "/mcp"
        sse_app = server.http_app(path=sse_path, transport="sse")
        routes.extend(sse_app.routes)
        lifespan_apps.append(sse_app)
    if transport in ("http", "both"):
        http_app = server.http_app(path="/mcp", transport="streamable-http")
        routes.extend(http_app.routes)
        lifespan_apps.append(http_app)
    return Mount(f"/{name}", routes=routes), lifespan_apps


def build_app(server_names: List[str] | None = None, transport: str = "both", middleware: list | None = None) -> Starlette:
    names = server_names or list(SERVER_BUILDERS.keys())
    all_routes: list = []
    all_lifespan_apps: list = []
    for name in names:
        builder = SERVER_BUILDERS.get(name)
        if builder is None:
            raise ValueError(f"Unknown MCP server: {name}")
        server = builder()
        mount, lifespan_apps = _mount_server(server, name, transport)
        all_routes.append(mount)
        all_lifespan_apps.extend(lifespan_apps)
        LOGGER.info("server_mounted", server=name, transport=transport, prefix=f"/{name}")

    async def health(request):
        return JSONResponse({"status": "ok"})

    all_routes.append(Route("/healthz", health))

    @asynccontextmanager
    async def lifespan(app):
        managers = []
        for sub_app in all_lifespan_apps:
            mgr = sub_app.lifespan(sub_app)
            await mgr.__aenter__()
            managers.append(mgr)
        try:
            yield
        finally:
            for mgr in reversed(managers):
                await mgr.__aexit__(None, None, None)

    return Starlette(routes=all_routes, lifespan=lifespan, middleware=middleware or [])


async def build_combined_server(server_names: List[str] | None = None) -> FastMCP:
    names = server_names or list(SERVER_BUILDERS.keys())
    root = FastMCP("ess-mcp")
    for name in names:
        builder = SERVER_BUILDERS.get(name)
        if builder is None:
            raise ValueError(f"Unknown MCP server: {name}")
        server: FastMCP = builder()
        await root.import_server(server)
        LOGGER.info("mcp_server_imported", server=name)
    LOGGER.info("combined_server_ready", servers=names)
    return root


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MCP servers")
    parser.add_argument("server", nargs="?", choices=[*SERVER_BUILDERS.keys(), "all"], default="all")
    parser.add_argument("--transport", choices=["stdio", "sse", "http", "both"], default="stdio")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    configure_logging()
    if args.transport == "stdio":
        if args.server == "all":
            parser.error("stdio transport requires a specific server name, not 'all'")
        builder = SERVER_BUILDERS.get(args.server)
        if builder is None:
            raise ValueError(f"Unknown server: {args.server}")
        builder().run()
        return
    server_names = None if args.server == "all" else [args.server]
    cors = Middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["mcp-session-id", "mcp-protocol-version"],
        allow_credentials=True,
    )
    auth_passthrough = Middleware(AuthErrorPassthroughMiddleware)
    app = build_app(server_names, transport=args.transport, middleware=[cors, auth_passthrough])
    LOGGER.info("starting_server", transport=args.transport, host=args.host, port=args.port)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
