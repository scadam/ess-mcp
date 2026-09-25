"""Local feasibility probe: Copilot SDK (empty mode) + BYOK Azure OpenAI with Entra token + custom tool + hooks + sub-agent."""

import asyncio
import collections
import json
import os
import sys

from azure.identity import AzureCliCredential
from copilot import CopilotClient, Tool, ToolInvocation, ToolResult, ToolSet
from copilot.session import ModelCapabilitiesOverride, ModelSupportsOverride, PermissionDecisionApproveOnce

ENDPOINT = "https://oai-autopilot-caldova-78f0.openai.azure.com"
credential = AzureCliCredential()
calls: list[dict] = []
events: collections.Counter = collections.Counter()
hooks_seen: list[str] = []


def token(_args):
    return credential.get_token("https://cognitiveservices.azure.com/.default").token


async def get_incident(invocation: ToolInvocation) -> ToolResult:
    calls.append({"args": invocation.arguments, "session": invocation.session_id[:8], "call": invocation.tool_call_id})
    number = str((invocation.arguments or {}).get("number", ""))
    return ToolResult(text_result_for_llm=json.dumps(
        {"number": number, "priority": 1 if number.endswith("2") else 4, "assigned_to": "Service Desk"}))


TOOL = Tool(
    name="servicenow__get_incident",
    description="Get one ServiceNow incident by number.",
    parameters={"type": "object", "properties": {"number": {"type": "string"}}, "required": ["number"]},
    handler=get_incident,
    skip_permission=True,
)


async def pre_tool(hook_input, _invocation):
    hooks_seen.append(f"pre:{hook_input['toolName']}")
    if hook_input["toolName"] == "servicenow__get_incident" and hook_input["toolArgs"].get("number") == "INC0009":
        return {"permissionDecision": "deny", "permissionDecisionReason": "guardrail tools.blocked: INC0009 is off limits"}
    return {"permissionDecision": "allow"}


async def post_tool(hook_input, _invocation):
    hooks_seen.append(f"post:{hook_input['toolName']}")
    return None


async def permission(request, _invocation):
    hooks_seen.append(f"permission:{type(request).__name__}")
    return PermissionDecisionApproveOnce()


def on_event(event):
    kind = getattr(event.type, "value", str(event.type))
    events[kind] += 1
    if kind.startswith(("subagent.", "tool.execution", "assistant.turn_start", "skill.")):
        data = event.data
        print("EV", kind, "agent_id=", getattr(event, "agent_id", None),
              {key: getattr(data, key, None) for key in ("tool_call_id", "tool_name", "agent_name", "agent_display_name",
                                                         "model", "turn_id", "name", "total_tool_calls")
               if getattr(data, key, None) is not None})


async def main() -> None:
    home = os.path.join(os.path.dirname(__file__), "copilot-home")
    async with CopilotClient(mode="empty", base_directory=home, log_level="warning") as client:
        session = await client.create_session(
            model=os.getenv("PROBE_MODEL", "gpt-4.1-mini"),
            model_capabilities=ModelCapabilitiesOverride(supports=ModelSupportsOverride(
                reasoning_effort=os.getenv("PROBE_MODEL", "").startswith("gpt-5"))),
            provider={"type": "azure", "base_url": ENDPOINT, "bearer_token_provider": token,
                      **({"model_id": os.environ["PROBE_MODEL_ID"]} if os.getenv("PROBE_MODEL_ID") else {}),
                      **({"wire_api": os.environ["PROBE_WIRE"]} if os.getenv("PROBE_WIRE") else {})},
            tools=[TOOL],
            available_tools=ToolSet().add_custom("*").add_builtin(["task", "read_agent", "list_agents"]),
            custom_agents=[{
                "name": "researcher", "display_name": "Researcher",
                "description": "Looks up ServiceNow incidents and reports the facts. Read-only.",
                "prompt": "You look up incidents with your tools and report the facts in one line each.",
                "tools": ["servicenow__get_incident"], "model": os.getenv("PROBE_MODEL", "gpt-4.1-mini"),
                "reasoning_effort": "low",
            }],
            system_message={"mode": "customize", "content": "You are Group Functions Autopilot, an AI teammate.",
                            "sections": {"code_change_rules": {"action": "remove"},
                                         "environment_context": {"action": "remove"}}},
            hooks={"on_pre_tool_use": pre_tool, "on_post_tool_use": post_tool},
            on_permission_request=permission,
            on_event=on_event,
        )
        prompt = sys.argv[1] if len(sys.argv) > 1 else (
            "Delegate to the researcher agent: look up INC0001 and INC0002, then also look up INC0009 yourself. "
            "Tell me which incident has the highest priority and what happened with INC0009.")
        reply = await session.send_and_wait(prompt, timeout=240)
        print("ANSWER:", reply.data.content if reply else None)
        print("TOOL CALLS:", calls)
        print("HOOKS:", hooks_seen)
        print("EVENTS:", dict(events))
        await session.disconnect()
        await client.delete_session(session.session_id)


asyncio.run(main())
