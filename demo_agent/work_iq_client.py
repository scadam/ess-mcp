"""Work IQ Teams MCP client (canonical Agent 365 SDK pattern).

Uses the in-pod Agent 365 SDK's `Authorization.exchange_token(context, scopes,
auth_handler_id="AGENTIC")` to mint a **delegated** agent-identity token, then
calls the Work IQ Teams MCP server (`mcp_TeamsServer`, scope
`McpServers.Teams.All`) to create a 1:1 chat between the agent identity user
and a recipient (typically the manager) and post a message.

This pattern requires a live `TurnContext` (i.e. the call must happen inside
an in-flight Teams turn handler or notification handler). For headless /
autonomous flows there is no SDK-supported MCP path — use the Graph email
fallback (`demo_agent.graph_chat`) instead.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from .identity import AgentIdentityContext, agent_headers

_logger = logging.getLogger(__name__)

DEFAULT_TEAMS_MCP_URL = "https://agent365.svc.cloud.microsoft/agents/servers/mcp_TeamsServer"
# Canonical Agent 365 sample (BaseA365AgentWithTeams) uses the bare scope name
# (e.g. "McpServers.Mail.All"). MSAL's user_fic grant accepts bare scope and the
# Agent 365 token service resolves the resource server-side. Do not change to a
# fully-qualified URI without verifying against the canonical sample first.
DEFAULT_TEAMS_MCP_SCOPE = "McpServers.Teams.All"
DEFAULT_AUTH_HANDLER = "AGENTIC"


@dataclass(frozen=True)
class WorkIqTeamsConfig:
    url: str
    scope: str
    auth_handler: str
    timeout: float

    @classmethod
    def from_env(cls) -> "WorkIqTeamsConfig":
        return cls(
            url=os.getenv("ESS_WORK_IQ_TEAMS_MCP_URL", DEFAULT_TEAMS_MCP_URL),
            scope=os.getenv("ESS_WORK_IQ_TEAMS_SCOPE", DEFAULT_TEAMS_MCP_SCOPE),
            auth_handler=os.getenv("AUTH_HANDLER_NAME", DEFAULT_AUTH_HANDLER),
            timeout=float(os.getenv("ESS_WORK_IQ_TEAMS_TIMEOUT", "30")),
        )


class WorkIqTeamsClient:
    """Canonical-pattern Work IQ Teams MCP client.

    Construct once at process start. Each call to :meth:`send_oneonone` must
    pass the active ``agent_app`` (``microsoft_agents.hosting.core.AgentApplication``)
    and the in-flight ``context`` (``TurnContext``) so the SDK can issue a
    delegated agentic token.
    """

    def __init__(
        self,
        config: WorkIqTeamsConfig | None = None,
        context: AgentIdentityContext | None = None,
    ) -> None:
        self.identity_context = context or AgentIdentityContext.from_env()
        self.config = config or WorkIqTeamsConfig.from_env()

    @property
    def available(self) -> bool:
        return bool(self.config.url and self.config.scope and self.config.auth_handler)

    async def _exchange_token(self, agent_app: Any, context: Any) -> str:
        if agent_app is None:
            raise RuntimeError("Work IQ Teams MCP requires the live AgentApplication")
        if context is None:
            raise RuntimeError(
                "Work IQ Teams MCP requires a live TurnContext (call from inside "
                "a Teams turn handler or notification handler)"
            )
        auth = getattr(agent_app, "auth", None)
        if auth is None:
            raise RuntimeError("AgentApplication has no Authorization configured")
        token_response = await auth.exchange_token(
            context,
            scopes=[self.config.scope],
            auth_handler_id=self.config.auth_handler,
        )
        token = getattr(token_response, "token", None) or getattr(token_response, "access_token", None)
        if not token:
            raise RuntimeError(f"exchange_token returned no token: {token_response!r}")
        return token

    async def _connect(self, agent_app: Any, context: Any) -> Client:
        token = await self._exchange_token(agent_app, context)
        headers = {"Authorization": f"Bearer {token}", **agent_headers(self.identity_context)}
        transport = StreamableHttpTransport(self.config.url, headers=headers)
        client = Client(transport, name="mcp_TeamsServer")
        await client.__aenter__()
        return client

    async def send_oneonone(
        self,
        *,
        agent_app: Any,
        context: Any,
        sender_aad_id: str,
        recipient_aad_id: str,
        body_text: str,
    ) -> dict[str, Any]:
        if not self.available:
            return {
                "status": "disabled",
                "channel": "teams-mcp",
                "reason": "Work IQ Teams MCP config missing (URL/scope/handler).",
            }
        if not (sender_aad_id and recipient_aad_id):
            return {
                "status": "skipped",
                "channel": "teams-mcp",
                "reason": "missing sender or recipient AAD id",
            }

        client: Client | None = None
        try:
            client = await self._connect(agent_app, context)
            create_args = {
                "chatType": "oneOnOne",
                "members": [
                    {
                        "@odata.type": "#microsoft.graph.aadUserConversationMember",
                        "roles": ["owner"],
                        "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{sender_aad_id}')",
                    },
                    {
                        "@odata.type": "#microsoft.graph.aadUserConversationMember",
                        "roles": ["owner"],
                        "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{recipient_aad_id}')",
                    },
                ],
            }
            create_result = await client.call_tool("mcp_graph_chat_createChat", create_args)
            chat_id = _extract_id(create_result)
            if not chat_id:
                return {
                    "status": "error",
                    "channel": "teams-mcp",
                    "reason": "createChat did not return a chat id",
                    "raw": _safe_dump(create_result),
                }
            post_result = await client.call_tool(
                "mcp_graph_chat_postMessage",
                {
                    "chat-id": chat_id,
                    "body": {"content": body_text, "contentType": "text"},
                },
            )
            return {
                "status": "sent",
                "channel": "teams-mcp",
                "chat_id": chat_id,
                "message_id": _extract_id(post_result),
            }
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Work IQ Teams send failed: %s", exc)
            return {"status": "error", "channel": "teams-mcp", "reason": str(exc)}
        finally:
            if client is not None:
                try:
                    await client.__aexit__(None, None, None)
                except Exception:  # noqa: BLE001
                    pass


def _extract_id(result: Any) -> str:
    if result is None:
        return ""
    import json as _json

    content = getattr(result, "content", None)
    if isinstance(content, list):
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str) and text.strip().startswith("{"):
                try:
                    parsed = _json.loads(text)
                except Exception:  # noqa: BLE001
                    continue
                if isinstance(parsed, dict) and "id" in parsed:
                    return str(parsed["id"])
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict) and "id" in structured:
        return str(structured["id"])
    data = getattr(result, "data", None)
    if isinstance(data, dict) and "id" in data:
        return str(data["id"])
    return ""


def _safe_dump(result: Any) -> str:
    try:
        return repr(result)[:500]
    except Exception:  # noqa: BLE001
        return "<unrepr>"
