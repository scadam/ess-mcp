import inspect
import typing

import copilot
from copilot import client as client_mod
from copilot import session as session_mod
from copilot import tools as tools_mod


def show(obj, label=None):
    label = label or getattr(obj, "__name__", str(obj))
    print(f"\n=== {label} ===")
    try:
        print(inspect.signature(obj))
    except (TypeError, ValueError):
        pass
    hints = getattr(obj, "__annotations__", None)
    if hints and isinstance(obj, type):
        for key, value in typing.get_type_hints(obj, include_extras=False).items() if False else hints.items():
            print(f"  {key}: {value}")


show(copilot.CopilotClient.__init__, "CopilotClient.__init__")
show(copilot.CopilotClient.create_session, "CopilotClient.create_session")
show(copilot.CopilotClient.delete_session, "CopilotClient.delete_session")
for name in ("Tool", "ToolInvocation", "ToolResult", "SessionHooks", "ProviderConfig", "SystemMessageConfig",
             "PreToolUseHookInput", "PreToolUseHookOutput", "PostToolUseHookInput", "PostToolUseHookOutput",
             "PreMcpToolCallHookInput", "PreMcpToolCallHookOutput", "MCPHTTPServerConfig", "McpAuthRequest",
             "McpAuthResult", "McpAuthToken", "McpAuthContext", "InfiniteSessionConfig", "SessionLimitsConfig",
             "LargeToolOutputConfig", "ToolSearchConfig", "UserPromptSubmittedHookInput", "UserPromptSubmittedHookOutput",
             "SessionStartHookInput", "SessionEndHookInput", "ErrorOccurredHookInput", "ErrorOccurredHookOutput",
             "AgentStopHookInput", "AgentStopHookOutput", "ProviderTokenArgs", "LlmInferenceHeaders"):
    show(getattr(copilot, name), name)
print("\nCopilotClientMode:", copilot.CopilotClientMode)
print("BUILTIN_TOOLS_ISOLATED:", copilot.BUILTIN_TOOLS_ISOLATED)
print("\nsession module names:", [n for n in dir(session_mod) if not n.startswith("_")])
for name in dir(session_mod):
    if "Agent" in name and "Config" in name:
        show(getattr(session_mod, name), "session." + name)
show(copilot.CopilotSession.send_and_wait, "CopilotSession.send_and_wait")
show(copilot.CopilotSession.send, "CopilotSession.send")
show(copilot.CopilotSession.abort, "CopilotSession.abort")
show(copilot.CopilotSession.disconnect, "CopilotSession.disconnect")
print("\nCopilotSession methods:", [n for n in dir(copilot.CopilotSession) if not n.startswith("_")])
print("\ntools module:", [n for n in dir(tools_mod) if not n.startswith("_")])
print("\nSessionEventType members (subset):", [m.name for m in copilot.SessionEventType][:200])
