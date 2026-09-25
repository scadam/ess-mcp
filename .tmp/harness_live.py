"""Live local smoke: the host's Copilot SDK path (real runtime + Azure OpenAI), Coupa served from the test fixture."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
os.environ.update(
    AZURE_OPENAI_ENDPOINT="https://oai-autopilot-caldova-78f0.openai.azure.com/",
    AUTOPILOT_GUARDRAILS="off", ENABLE_OBSERVABILITY="false", ENABLE_A365_OBSERVABILITY="false",
    ENABLE_A365_OBSERVABILITY_EXPORTER="false", OTEL_SDK_DISABLED="true", PURVIEW_ENABLED="false",
    AUTOPILOT_MODEL_ROUTES=json.dumps({"reasoning": "gpt-5.4", "standard": "gpt-5.4", "fast": "gpt-5.4"}),
    AUTOPILOT_COPILOT_HOME=str(ROOT / ".tmp" / "copilot-home-live"),
)
sys.path.insert(0, str(ROOT))
with patch("dotenv.load_dotenv"):
    from demo_agent import web  # noqa: E402

FIXTURE = json.loads((ROOT / "demo_agent" / "tests" / "fixtures" / "coupa_snapshot.json").read_text(encoding="utf-8"))
WRITES = ["reject_invoice", "approve_reject", "create_requisition"]
changes: list[tuple[str, dict]] = []


async def fake_call(server: str, tool: str, args: dict) -> str:
    if tool in FIXTURE:
        return json.dumps(FIXTURE[tool])
    changes.append((tool, args))
    return json.dumps({"status": "dry-run", "message": "Dry run: nothing was changed."})


async def noop() -> None:
    return None


async def main() -> None:
    session = web._start_skill_session("procurement-month-end-close", "live-smoke", dry_run=True)
    tools = [{"type": "function", "function": {"name": f"coupa__{name}", "description": f"Coupa: {name.replace('_', ' ')}.",
                                               "parameters": {"type": "object", "properties": {}}}}
             for name in [*FIXTURE, *WRITES]]
    stats = {"turns": 0, "tool_calls": 0, "models": {}, "start_time": time.time()}
    seen: list[str] = []

    async def emit(kind: str, data: dict) -> None:
        if kind in {"turn", "subagent", "script", "tool_call", "status"}:
            line = f"{kind}: " + json.dumps({key: data.get(key) for key in (
                "turn", "phase", "model", "name", "tool", "agent", "script", "purpose", "exitCode", "message")
                if data.get(key) is not None})
            seen.append(line)
            print(line[:220], flush=True)

    async def observe(name: str, **attributes: object) -> None:
        return None

    web._current_run_ctx.set({"run_id": "live-smoke", "source": "control-plane", "actor": {}, "skill": session,
                              "stats": stats})
    loop = web._Loop(run_id="live-smoke", stats=stats, emit=emit, observe=observe,
                     tools=web._skill_run_tools(session, tools), session=session, mcp_tools=tools)
    messages = web._task_messages("Close the IT hardware procurement month end. This is a dry run.", session=session)
    started = time.time()
    try:
        with patch.object(web, "_call_tool_safe", fake_call), patch.object(web, "_ensure_run_authority", noop):
            result = await web._run_session(loop, model="gpt-5.4", instructions=messages[0]["content"],
                                            prompt=messages[1]["content"], max_turns=25)
        print("\n=== ANSWER ===\n" + result.content[:2500])
    finally:
        await web._harness.stop()
    print("\n=== STATS ===", json.dumps({key: stats.get(key) for key in ("turns", "tool_calls", "total_tokens", "models")}))
    print("=== FILES ===", [entry["path"] for entry in session.workspace.listing()])
    print("=== CHANGES ATTEMPTED ===", [tool for tool, _ in changes])
    print(f"=== {time.time() - started:.0f}s; sub-agent events: {sum('subagent' in line for line in seen)} ===")


asyncio.run(main())
