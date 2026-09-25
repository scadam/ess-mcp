"""Probe: native SDK skill preload through a selected custom agent (empty mode, BYOK Azure)."""

import asyncio
import collections
import os

from azure.identity import AzureCliCredential
from copilot import CopilotClient, ToolSet
from copilot.session import PermissionDecisionApproveOnce

ENDPOINT = "https://oai-autopilot-caldova-78f0.openai.azure.com"
SKILLS = os.path.join(os.path.dirname(__file__), "..", "demo_agent", "skills")
credential = AzureCliCredential()
events: collections.Counter = collections.Counter()


def token(_args):
    return credential.get_token("https://cognitiveservices.azure.com/.default").token


def on_event(event):
    kind = getattr(event.type, "value", str(event.type))
    events[kind] += 1
    if kind.startswith("skill") or kind == "session.skills_loaded":
        data = event.data
        print("EV", kind, {key: str(getattr(data, key, ""))[:120] for key in ("name", "path", "allowed_tools", "skills")
                           if getattr(data, key, None) is not None})


async def main() -> None:
    home = os.path.join(os.path.dirname(__file__), "copilot-home")
    async with CopilotClient(mode="empty", base_directory=home, log_level="warning") as client:
        session = await client.create_session(
            model="gpt-5.4", reasoning_effort="low",
            provider={"type": "azure", "base_url": ENDPOINT, "bearer_token_provider": token},
            available_tools=ToolSet().add_custom("*"),
            enable_skills=True, skill_directories=[os.path.abspath(SKILLS)],
            custom_agents=[{"name": "colleague", "display_name": "Colleague", "prompt": "You are an AI colleague.",
                            "skills": ["procurement-month-end-close"], "infer": False}],
            agent="colleague",
            on_permission_request=lambda request, invocation: PermissionDecisionApproveOnce(),
            on_event=on_event,
        )
        reply = await session.send_and_wait(
            "Without using tools: which reference file must you read before acting, and what is step 1 of your playbook?",
            timeout=180)
        print("ANSWER:", reply.data.content if reply else None)
        print("EVENTS:", dict(events))
        await session.disconnect()
        await client.delete_session(session.session_id)


asyncio.run(main())
