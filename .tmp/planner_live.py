"""Live local smoke: the conversation planner answering through a tool-free Copilot SDK session."""

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
os.environ.update(
    AZURE_OPENAI_ENDPOINT="https://oai-autopilot-caldova-78f0.openai.azure.com/", AUTOPILOT_GUARDRAILS="off",
    ENABLE_OBSERVABILITY="false", OTEL_SDK_DISABLED="true",
    AUTOPILOT_MODEL_ROUTES=json.dumps({"reasoning": "gpt-5.4", "standard": "gpt-5.4", "fast": "gpt-5.4"}),
    AUTOPILOT_COPILOT_HOME=str(ROOT / ".tmp" / "copilot-home-live"),
)
sys.path.insert(0, str(ROOT))
with patch("dotenv.load_dotenv"):
    from demo_agent import web  # noqa: E402
from demo_agent.copilot_harness import parse_json_reply  # noqa: E402


async def main() -> None:
    try:
        text = await web._answer([
            {"role": "system", "content": "Respond with only a JSON object with mode 'reply' or 'task' and text."},
            {"role": "user", "content": json.dumps({"kind": "current_user_message", "text": "Hi! What can you do?"})},
        ])
        print("RAW:", text[:400])
        print("PARSED:", parse_json_reply(text))
    finally:
        await web._harness.stop()


asyncio.run(main())
