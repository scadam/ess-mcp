"""Syntax-check every inline <script> block of the control plane with node --check."""
import pathlib
import re
import subprocess
import sys
import tempfile

html = pathlib.Path("demo_agent/static/control-plane.html").read_text(encoding="utf-8")
blocks = [body for attrs, body in re.findall(r"<script([^>]*)>(.*?)</script>", html, re.S) if "src=" not in attrs]
failed = 0
for index, body in enumerate(blocks):
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(body)
    result = subprocess.run(["node", "--check", handle.name], capture_output=True, text=True)
    pathlib.Path(handle.name).unlink()
    status = "ok" if result.returncode == 0 else "FAIL"
    failed += result.returncode != 0
    print(f"block {index}: {len(body)} chars {status} {result.stderr.strip()[:400]}")
sys.exit(1 if failed else 0)
