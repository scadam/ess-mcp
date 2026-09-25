import inspect

import copilot
from copilot import session as session_mod
from copilot.generated import session_events

for name, param in inspect.signature(copilot.CopilotClient.create_session).parameters.items():
    print(f"{name}: {param.annotation} = {param.default!r}")
print()
print([m.name for m in copilot.SessionEventType][80:])
print()
print([n for n in dir(session_mod) if not n.startswith("_")][60:])
print()
for name in ("ModelCallStartData", "ModelCallFinishedData", "ModelCallFailureData", "AssistantUsageData",
             "ToolExecutionStartData", "ToolExecutionCompleteData", "SessionErrorData", "SandboxDecisionData",
             "SubagentStartedData", "SubagentCompletedData", "AssistantTurnStartData", "SessionIdleData"):
    cls = getattr(session_events, name, None)
    if cls is None:
        print(name, "missing")
        continue
    fields = getattr(cls, "__dataclass_fields__", None) or getattr(cls, "model_fields", None) or {}
    print(name, list(fields))
print()
print(inspect.signature(copilot.RuntimeConnection.for_stdio))
print(inspect.getsource(copilot.PermissionHandler)[:1500])
