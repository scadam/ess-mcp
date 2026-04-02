#!/usr/bin/env python3
"""Lightweight preview server for ESS-MCP widgets.

Serves the widget gallery at http://localhost:8090 (configurable).
No external dependencies – uses only Python stdlib.

Routes:
  /                     → widget-preview/index.html
  /sample-data.js       → widget-preview/sample-data.js
  /widgets/<file>.html  → mcp_servers/src/mcp_servers/ui/widget/<file>.html
"""

import argparse
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.dirname(os.path.abspath(__file__))
PREVIEW_DIR = os.path.join(ROOT, "widget-preview")
WIDGET_DIR = os.path.join(ROOT, "mcp_servers", "src", "mcp_servers", "ui", "widget")

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


class PreviewHandler(SimpleHTTPRequestHandler):
    """Route requests to the correct directories."""

    def do_GET(self):
        path = self.path.split("?")[0].split("#")[0]  # strip query/fragment

        if path == "/" or path == "/index.html":
            self._serve_file(os.path.join(PREVIEW_DIR, "index.html"))
        elif path == "/sample-data.js":
            self._serve_file(os.path.join(PREVIEW_DIR, "sample-data.js"))
        elif path.startswith("/widgets/"):
            filename = os.path.basename(path)
            self._serve_file(os.path.join(WIDGET_DIR, filename))
        else:
            # Try preview dir, then widget dir
            candidate = os.path.join(PREVIEW_DIR, path.lstrip("/"))
            if os.path.isfile(candidate):
                self._serve_file(candidate)
            else:
                self.send_error(404, "Not found")

    def _serve_file(self, filepath):
        filepath = os.path.realpath(filepath)

        # Guard against path traversal: resolved path must be inside an allowed directory
        allowed_dirs = (os.path.realpath(PREVIEW_DIR), os.path.realpath(WIDGET_DIR))
        if not any(filepath.startswith(d + os.sep) or filepath == d for d in allowed_dirs):
            self.send_error(403, "Forbidden")
            return

        if not os.path.isfile(filepath):
            self.send_error(404, "Not found")
            return

        ext = os.path.splitext(filepath)[1].lower()
        content_type = CONTENT_TYPES.get(ext, "application/octet-stream")

        with open(filepath, "rb") as f:
            body = f.read()

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Quieter logging: only show path
        sys.stderr.write(f"  {args[0]}\n")


def main():
    parser = argparse.ArgumentParser(description="ESS-MCP Widget Preview Server")
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=8090,
        help="Port to listen on (default: 8090)",
    )
    args = parser.parse_args()

    if not os.path.isdir(WIDGET_DIR):
        print(f"Error: widget directory not found at {WIDGET_DIR}", file=sys.stderr)
        sys.exit(1)

    server = HTTPServer(("127.0.0.1", args.port), PreviewHandler)
    print()
    print("  ╭─────────────────────────────────────────────╮")
    print("  │                                             │")
    print("  │   ESS-MCP Widget Preview Gallery            │")
    print("  │                                             │")
    print(f"  │   → http://localhost:{str(args.port):<24s}│")
    print("  │                                             │")
    print("  │   Press Ctrl+C to stop                      │")
    print("  │                                             │")
    print("  ╰─────────────────────────────────────────────╯")
    print()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
