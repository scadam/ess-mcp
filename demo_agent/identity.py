"""Agent identity and Agent 365 runtime helpers.

The tenant-side Entra Agent ID setup creates a Blueprint and one or more Agent
Identity service principals. This module keeps the runtime values together and
provides a small token client for the Microsoft Entra SDK for AgentID sidecar or
another configured Agent ID token endpoint.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class AgentIdentityContext:
    """Runtime metadata for one hosted autonomous agent instance."""

    display_name: str
    blueprint_client_id: str
    blueprint_object_id: str
    blueprint_principal_id: str
    agent_identity_id: str
    agent_identity_client_id: str
    tenant_id: str
    foundry_project_endpoint: str
    foundry_agent_id: str
    gateway_base_url: str

    @property
    def enabled(self) -> bool:
        return bool(self.blueprint_client_id and self.agent_identity_id and self.tenant_id)

    @classmethod
    def from_env(cls) -> "AgentIdentityContext":
        return cls(
            display_name=os.getenv("ESS_AGENT_DISPLAY_NAME", "Group Functions Autopilot"),
            blueprint_client_id=os.getenv("ENTRA_AGENT_BLUEPRINT_CLIENT_ID", ""),
            blueprint_object_id=os.getenv("ENTRA_AGENT_BLUEPRINT_OBJECT_ID", ""),
            blueprint_principal_id=os.getenv("ENTRA_AGENT_BLUEPRINT_PRINCIPAL_ID", ""),
            agent_identity_id=os.getenv("ENTRA_AGENT_IDENTITY_OBJECT_ID", ""),
            agent_identity_client_id=os.getenv("ENTRA_AGENT_IDENTITY_CLIENT_ID", ""),
            tenant_id=os.getenv("AZURE_TENANT_ID", ""),
            foundry_project_endpoint=os.getenv("AZURE_FOUNDRY_PROJECT_ENDPOINT", ""),
            foundry_agent_id=os.getenv("AZURE_FOUNDRY_AGENT_ID", ""),
            gateway_base_url=os.getenv("ESS_AI_GATEWAY_BASE_URL", ""),
        )

    def system_prompt_preamble(self) -> str:
        if not self.enabled:
            return ""
        return (
            "\n\nHosted agent identity:\n"
            f"- Agent display name: {self.display_name}\n"
            f"- Entra Agent Identity object ID: {self.agent_identity_id}\n"
            f"- Entra Agent Identity client ID: {self.agent_identity_client_id or 'not provided'}\n"
            f"- Agent Identity Blueprint app ID: {self.blueprint_client_id}\n"
            "- Operate as this autonomous agent instance for audit, policy, and tool calls."
        )


@dataclass
class CachedToken:
    access_token: str
    expires_at: float

    def valid(self) -> bool:
        return bool(self.access_token) and time.time() < self.expires_at - 60


class AgentIdentityTokenClient:
    """Acquire tokens for the configured Agent Identity runtime.

    The preferred production path is the Microsoft Entra SDK for AgentID
    sidecar. Because the sidecar is distributed separately and its API may move
    during preview, the token endpoint is configured explicitly through
    ENTRA_AGENT_ID_SDK_TOKEN_URL.
    """

    def __init__(self, context: AgentIdentityContext | None = None) -> None:
        self.context = context or AgentIdentityContext.from_env()
        self.token_url = os.getenv("ENTRA_AGENT_ID_SDK_TOKEN_URL", "")
        self.timeout = float(os.getenv("ENTRA_AGENT_ID_SDK_TIMEOUT", "15"))
        self._cache: dict[str, CachedToken] = {}

    @property
    def available(self) -> bool:
        return self.context.enabled and bool(self.token_url)

    async def get_token(self, scope: str, *, resource: str = "") -> str:
        cache_key = f"{scope}|{resource}"
        cached = self._cache.get(cache_key)
        if cached and cached.valid():
            return cached.access_token
        if not self.available:
            raise RuntimeError(
                "Agent Identity token endpoint is not configured. Set "
                "ENTRA_AGENT_ID_SDK_TOKEN_URL plus ENTRA_AGENT_* values."
            )

        payload: dict[str, Any] = {
            "scope": scope,
            "tenantId": self.context.tenant_id,
            "blueprintClientId": self.context.blueprint_client_id,
            "agentIdentityId": self.context.agent_identity_id,
        }
        if self.context.agent_identity_client_id:
            payload["agentIdentityClientId"] = self.context.agent_identity_client_id
        if resource:
            payload["resource"] = resource

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(self.token_url, json=payload)
            response.raise_for_status()
            data = response.json()

        access_token = data.get("access_token") or data.get("accessToken") or data.get("token")
        if not access_token:
            raise RuntimeError("Agent Identity token endpoint did not return an access token")
        expires_in = int(data.get("expires_in") or data.get("expiresIn") or 3600)
        self._cache[cache_key] = CachedToken(access_token=access_token, expires_at=time.time() + expires_in)
        return access_token


def agent_headers(context: AgentIdentityContext | None = None) -> dict[str, str]:
    """Headers that help gateways and logs correlate calls to this agent."""
    ctx = context or AgentIdentityContext.from_env()
    headers: dict[str, str] = {"X-Agent-Name": ctx.display_name}
    if ctx.agent_identity_id:
        headers["X-Agent-Identity-Id"] = ctx.agent_identity_id
    if ctx.agent_identity_client_id:
        headers["X-Agent-Identity-Client-Id"] = ctx.agent_identity_client_id
    if ctx.blueprint_client_id:
        headers["X-Agent-Blueprint-Client-Id"] = ctx.blueprint_client_id
    if ctx.foundry_agent_id:
        headers["X-Foundry-Agent-Id"] = ctx.foundry_agent_id
    return headers


def mcp_url_for(name: str, context: AgentIdentityContext) -> str:
    """Resolve the MCP URL, preferring the AI Gateway route when configured."""
    direct = os.getenv(f"ESS_{name.upper()}_MCP_URL", "")
    gateway = os.getenv(f"ESS_{name.upper()}_AI_GATEWAY_MCP_URL", "")
    if gateway:
        return gateway
    if context.gateway_base_url:
        return context.gateway_base_url.rstrip("/") + f"/{name}/mcp"
    return direct


@dataclass(frozen=True)
class RunPrincipal:
    """Identifies the human caller behind a single agent run.

    Populated from the Bot Framework `turn_context.activity.from_property` for
    Teams runs, or built as an anonymous control-plane principal for the web
    UI. Carried through to Agent 365 telemetry as `UserDetails`/`CallerDetails`
    and used for Purview labelling decisions in Phase 3.
    """

    aad_object_id: str = ""
    upn: str = ""
    display_name: str = ""
    tenant_id: str = ""
    client_ip: str = ""
    channel_id: str = ""
    conversation_id: str = ""
    source: str = "control-plane"  # "teams-chat" | "control-plane" | etc.

    @property
    def user_id(self) -> str:
        return self.aad_object_id or self.upn or "anonymous-control-plane"

    @property
    def is_anonymous(self) -> bool:
        return not (self.aad_object_id or self.upn)

    @classmethod
    def anonymous(cls, *, source: str = "control-plane", tenant_id: str = "", client_ip: str = "") -> "RunPrincipal":
        return cls(
            display_name="Control Plane Operator",
            tenant_id=tenant_id or os.getenv("AZURE_TENANT_ID", ""),
            client_ip=client_ip,
            source=source,
        )

    @classmethod
    def from_actor(
        cls,
        actor: dict[str, Any] | None,
        *,
        source: str = "control-plane",
        client_ip: str = "",
        tenant_id: str = "",
    ) -> "RunPrincipal":
        actor = actor or {}
        aad = (actor.get("aadObjectId") or actor.get("aad_object_id") or "").strip()
        upn = (
            actor.get("upn")
            or actor.get("userPrincipalName")
            or actor.get("email")
            or actor.get("managerEmail")
            or actor.get("managerUpn")
            or ""
        ).strip()
        display = (
            actor.get("name")
            or actor.get("displayName")
            or actor.get("managerName")
            or ""
        ).strip()
        if not (aad or upn):
            return cls.anonymous(source=source, tenant_id=tenant_id, client_ip=client_ip)
        return cls(
            aad_object_id=aad,
            upn=upn,
            display_name=display or upn or aad,
            tenant_id=tenant_id or os.getenv("AZURE_TENANT_ID", ""),
            client_ip=client_ip,
            channel_id=(actor.get("channelId") or "").strip(),
            conversation_id=(actor.get("conversationId") or "").strip(),
            source=source,
        )