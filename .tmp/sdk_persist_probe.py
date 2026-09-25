"""Probe: Copilot SDK session persistence (disk layout, resume after restart, restore from a tarball) and streaming."""

import asyncio
import collections
import io
import os
import shutil
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path

from azure.identity import AzureCliCredential
from copilot import CopilotClient, ToolSet

ENDPOINT = "https://oai-autopilot-caldova-78f0.openai.azure.com"
credential = AzureCliCredential()
HOME = Path(tempfile.gettempdir()) / "copilot-persist-probe"


def token(_args=None):
    return credential.get_token("https://cognitiveservices.azure.com/.default").token


def provider():
    return {"type": "azure", "base_url": ENDPOINT, "bearer_token_provider": token}


def tree(root: Path, limit=40):
    out = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            out.append(f"{path.relative_to(root)} {path.stat().st_size}")
        if len(out) >= limit:
            break
    return out


async def client():
    c = CopilotClient(mode="empty", base_directory=str(HOME), log_level="warning")
    await c.start()
    return c


async def main():
    shutil.rmtree(HOME, ignore_errors=True)
    sid = f"case-probe-{uuid.uuid4().hex[:8]}"
    kinds = collections.Counter()
    deltas = []

    def on_event(event):
        kind = getattr(event.type, "value", str(event.type))
        kinds[kind] += 1
        if kind == "assistant.message_delta":
            deltas.append(event.data.delta_content)
        if kind == "assistant.usage":
            d = event.data
            print("usage", d.model, d.input_tokens, d.output_tokens, "cache_read", d.cache_read_tokens, "reasoning", d.reasoning_tokens)

    c = await client()
    s = await c.create_session(session_id=sid, model="gpt-5.4-mini", reasoning_effort="low", provider=provider(),
                               available_tools=ToolSet(), streaming=True, on_event=on_event,
                               system_message={"mode": "append", "content": "Be brief."})
    r = await s.send_and_wait("Remember this case code word: PELICAN-42. Reply only 'noted'.", timeout=120)
    print("reply1", r.data.content if r else None, "deltas", len(deltas))
    await s.disconnect()
    print("kinds", dict(kinds))
    print("tree after disconnect:", *tree(HOME), sep="\n  ")
    await c.stop()

    # Resume in a fresh runtime from the same disk.
    c = await client()
    s = await c.resume_session(sid, model="gpt-5.4-mini", reasoning_effort="low", provider=provider(),
                               available_tools=ToolSet(), on_event=on_event)
    r = await s.send_and_wait("What was the case code word? Reply with just the word.", timeout=120)
    print("reply2 (resume after restart)", r.data.content if r else None)
    await s.disconnect()
    await c.stop()

    # Archive the state, wipe the home, restore, resume.
    state_dirs = [p for p in HOME.rglob(sid) if p.is_dir()]
    print("state dirs", [str(p.relative_to(HOME)) for p in state_dirs])
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for d in state_dirs:
            tar.add(d, arcname=str(d.relative_to(HOME)))
    print("archive bytes", len(buffer.getvalue()))
    shutil.rmtree(HOME)
    HOME.mkdir(parents=True)
    buffer.seek(0)
    with tarfile.open(fileobj=buffer, mode="r:gz") as tar:
        tar.extractall(HOME, filter="data")
    c = await client()
    s = await c.resume_session(sid, model="gpt-5.4-mini", reasoning_effort="low", provider=provider(),
                               available_tools=ToolSet(), on_event=on_event)
    r = await s.send_and_wait("Repeat the code word once more, then say done.", timeout=120)
    print("reply3 (restored from archive)", r.data.content if r else None)
    await s.disconnect()
    await c.delete_session(sid)
    await c.stop()
    print("tree after delete:", *tree(HOME), sep="\n  ")


asyncio.run(main())
