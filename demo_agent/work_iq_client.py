"""Current Work IQ MCP adapter for verified, delegated SDK turns.

ToolingManifest.json contains the bare permission and resource application ID
for A365 provisioning. MSAL requests must use the fully qualified scope below.
Work IQ is not the preview Agent 365 Teams MCP server, and it is not app-only.

The host supplies a live, authenticated SDK context and an explicitly configured
user authorization handler. Normal group replies use the captured SDK reference,
not this cross-chat helper. Callers must obtain exact human confirmation BEFORE
using send_oneonone; Work IQ tenant policy and user permissions still apply.
Policy failures never trigger a direct-Graph/email fallback or automatic retry.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

from .identity import AgentIdentityContext, agent_headers

_logger = logging.getLogger(__name__)

WORK_IQ_RESOURCE_APP_ID = "fdcc1f02-fc51-4226-8753-f668596af7f7"
DEFAULT_TEAMS_MCP_URL = "https://workiq.svc.cloud.microsoft/mcp"
DEFAULT_TEAMS_MCP_SCOPE = "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"
DEFAULT_AUTH_HANDLER = "OBO"


def _http_client(headers: dict[str, str] | None = None, timeout: httpx.Timeout | None = None,
                 auth: httpx.Auth | None = None, **_kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=headers, timeout=timeout or httpx.Timeout(30, read=300), auth=auth,
        follow_redirects=False, transport=httpx.AsyncHTTPTransport(retries=0),
    )


@dataclass(frozen=True)
class WorkIqTeamsConfig:
    url: str
    scope: str
    auth_handler: str
    timeout: float

    def __post_init__(self) -> None:
        if self.url != DEFAULT_TEAMS_MCP_URL:
            raise ValueError("Work IQ requires the current production MCP endpoint.")
        if self.scope not in {
            DEFAULT_TEAMS_MCP_SCOPE, f"{WORK_IQ_RESOURCE_APP_ID}/WorkIQAgent.Ask",
        }:
            raise ValueError("Work IQ requires its fully qualified delegated WorkIQAgent.Ask scope.")
        if not self.auth_handler or not math.isfinite(self.timeout) or not 0 < self.timeout <= 300:
            raise ValueError("Work IQ requires an SDK user authorization handler and a bounded timeout.")

    @classmethod
    def from_env(cls) -> "WorkIqTeamsConfig":
        return cls(
            url=os.getenv("ESS_WORK_IQ_MCP_URL") or os.getenv("ESS_WORK_IQ_TEAMS_MCP_URL", DEFAULT_TEAMS_MCP_URL),
            scope=os.getenv("ESS_WORK_IQ_SCOPE") or os.getenv("ESS_WORK_IQ_TEAMS_SCOPE", DEFAULT_TEAMS_MCP_SCOPE),
            auth_handler=os.getenv("ESS_WORK_IQ_AUTH_HANDLER", DEFAULT_AUTH_HANDLER),
            timeout=float(os.getenv("ESS_WORK_IQ_TIMEOUT", "60")),
        )


class WorkIqTeamsClient:
    """Compatibility name for the current Work IQ chat adapter.

    Construct once at process start. Each call to :meth:`send_oneonone` must
    pass the active ``agent_app`` (``microsoft_agents.hosting.core.AgentApplication``)
    and the in-flight ``context`` (``TurnContext``) so the SDK can issue a
    delegated user token. It never acquires an app-only replacement identity.
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
        if not isinstance(token, str) or not token:
            raise RuntimeError("Work IQ requires a consented delegated token from the SDK.")
        return token

    async def _connect(self, agent_app: Any, context: Any) -> Client:
        token = await self._exchange_token(agent_app, context)
        headers = {"Authorization": f"Bearer {token}", **agent_headers(self.identity_context)}
        transport = StreamableHttpTransport(
            self.config.url, headers=headers, httpx_client_factory=_http_client,
        )
        client = Client(transport, name="workiq")
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
                "channel": "workiq-mcp",
                "reason": "Work IQ Teams MCP config missing (URL/scope/handler).",
            }
        if not (sender_aad_id and recipient_aad_id):
            return {
                "status": "skipped",
                "channel": "workiq-mcp",
                "reason": "missing sender or recipient AAD id",
            }

        client: Client | None = None
        phase = "discovery"
        try:
            sender_aad_id = str(UUID(sender_aad_id))
            recipient_aad_id = str(UUID(recipient_aad_id))
            if not UUID(sender_aad_id).int or not UUID(recipient_aad_id).int or not body_text.strip():
                raise ValueError("A sender, recipient and message are required.")
            client = await asyncio.wait_for(self._connect(agent_app, context), timeout=self.config.timeout)
            # Names and schemas are discovered from THIS endpoint, not inferred
            # from retired preview tools. Discovery itself has no side effect.
            tools = await asyncio.wait_for(client.list_tools(), timeout=self.config.timeout)
            if "create_entity" not in {tool.name for tool in tools}:
                raise RuntimeError("Work IQ create_entity is unavailable in this tenant.")
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
            phase = "create_chat"
            create_result = await asyncio.wait_for(client.call_tool("create_entity", {
                "parentUrl": "/chats",
                "jsonBody": json.dumps(create_args),
            }), timeout=self.config.timeout)
            chat_id = _created_entity_id(create_result)
            if not chat_id:
                return {
                    "status": "unknown",
                    "channel": "workiq-mcp",
                    "reason": "Work IQ did not confirm chat creation. Nothing was retried.",
                }
            phase = "post_message"
            post_result = await asyncio.wait_for(client.call_tool("create_entity", {
                "parentUrl": f"/chats/{quote(chat_id, safe='')}/messages",
                "jsonBody": json.dumps({"body": {"content": body_text, "contentType": "text"}}),
            }), timeout=self.config.timeout)
            message_id = _created_entity_id(post_result)
            if not message_id:
                return {"status": "unknown", "channel": "workiq-mcp",
                        "reason": "Work IQ did not confirm message creation. Nothing was retried."}
            return {
                "status": "sent",
                "channel": "workiq-mcp",
                "chat_id": chat_id,
                "message_id": message_id,
            }
        except Exception as exc:  # noqa: BLE001
            # Exception/result bodies can carry tokens or private messages.
            # No raw exception, token response, arguments or payload is logged.
            _logger.warning("Work IQ request failed phase=%s category=%s", phase, type(exc).__name__)
            return {
                "status": "unknown" if phase != "discovery" else "error",
                "channel": "workiq-mcp", "phase": phase,
                "reason": "Work IQ did not confirm the operation. Check delegated consent and tenant policy; no fallback or retry was attempted.",
            }
        finally:
            if client is not None:
                try:
                    await client.__aexit__(None, None, None)
                except Exception:  # noqa: BLE001
                    pass


def _created_entity_id(result: Any) -> str:
    """Require both a successful entity status and an ID, including structuredContent."""
    if result is None or getattr(result, "is_error", False) or getattr(result, "isError", False):
        return ""
    candidates = []
    for name in ("structured_content", "structuredContent", "data"):
        data = getattr(result, name, None)
        if isinstance(data, dict):
            candidates.append(data)
    content = getattr(result, "content", None)
    if isinstance(content, list):
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                except (ValueError, TypeError):
                    continue
                if isinstance(parsed, dict):
                    candidates.append(parsed)
    identifiers = set()
    for data in candidates:
        status = data.get("statusCode")
        entity = data.get("data")
        if type(status) is not int or not 200 <= status < 300 or not isinstance(entity, dict):
            return ""
        identifier = entity.get("id")
        if not isinstance(identifier, str) or not identifier or len(identifier) > 2048:
            return ""
        identifiers.add(identifier)
    return next(iter(identifiers)) if len(identifiers) == 1 else ""
