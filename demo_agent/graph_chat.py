"""Headless Microsoft Graph chat helper for HITL fallback.

The Bot Framework proactive-message path requires the manager to have
previously installed the bot in Teams (so we have a captured
``ConversationReference``). When that hasn't happened we still need to deliver
a HITL prompt — so this module posts a 1:1 Teams chat between the agent
identity user and the manager via Microsoft Graph.

Token source order (first available wins):

1. **Entra agent identity sidecar** (``ENTRA_AGENT_ID_SDK_TOKEN_URL``). Mints a
   token *as the agent identity itself*, so created chats and posted messages
   are attributed to the agent identity user (e.g. "ESS Workday ServiceNow
   Hosted Demo Agent"). Requires delegated ``Chat.Create``, ``ChatMessage.Send``,
   ``User.Read`` scopes consented on the blueprint app.
2. **Host container managed identity** (IMDS / IDENTITY_ENDPOINT). Falls back to
   app-only Graph; messages are attributed to the calling application. Requires
   ``Chat.Create`` + ``ChatMessage.Send`` *Application* permissions on the MI.

Falls back to Graph ``sendMail`` (Application ``Mail.Send`` on the agent
identity user) when chat creation/posting is unavailable.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any

import httpx

from .identity import AgentIdentityContext, AgentIdentityTokenClient

logger = logging.getLogger("ess.graph_chat")

GRAPH_RESOURCE = "https://graph.microsoft.com"
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
# Default Graph scopes requested from the agent-identity sidecar. ".default"
# returns whatever's been admin-consented on the blueprint app for Graph.
_DEFAULT_AGENT_GRAPH_SCOPE = os.getenv(
    "ENTRA_AGENT_GRAPH_SCOPE", "https://graph.microsoft.com/.default"
)


def _sidecar_graph_available() -> bool:
    """True iff the Entra auth-sidecar is configured with a Graph downstream
    API entry and an agent identity is known."""
    has_url = bool(os.getenv("A365_SIDECAR_URL"))
    has_graph_api = bool(os.getenv("A365_SIDECAR_GRAPH_API"))
    has_agent = bool(
        os.getenv("A365_AGENT_APP_ID")
        or os.getenv("ENTRA_AGENT_IDENTITY_CLIENT_ID")
        or os.getenv("ENTRA_AGENT_IDENTITY_OBJECT_ID")
    )
    return has_url and has_graph_api and has_agent


@dataclass
class _CachedToken:
    token: str
    expires_at: float

    def valid(self, skew: float = 60.0) -> bool:
        return self.token and time.time() + skew < self.expires_at


class _MITokenClient:
    """Acquire Graph tokens via the Container Apps / IMDS managed identity."""

    def __init__(self) -> None:
        self._cache: _CachedToken | None = None
        self._lock = asyncio.Lock()

    async def get_token(self) -> str:
        async with self._lock:
            if self._cache and self._cache.valid():
                return self._cache.token
            token, expires_in = await self._acquire()
            self._cache = _CachedToken(token=token, expires_at=time.time() + max(60, expires_in - 60))
            return token

    async def _acquire(self) -> tuple[str, int]:
        endpoint = os.getenv("IDENTITY_ENDPOINT") or os.getenv("MSI_ENDPOINT")
        header = os.getenv("IDENTITY_HEADER") or os.getenv("MSI_SECRET")
        if endpoint and header:
            params = {
                "api-version": "2019-08-01",
                "resource": GRAPH_RESOURCE,
            }
            async with httpx.AsyncClient(timeout=15.0) as c:
                r = await c.get(endpoint, params=params, headers={"X-IDENTITY-HEADER": header})
                r.raise_for_status()
                data = r.json()
            return data["access_token"], int(data.get("expires_in", 3600))
        # IMDS fallback (Azure VM)
        url = "http://169.254.169.254/metadata/identity/oauth2/token"
        params = {"api-version": "2018-02-01", "resource": GRAPH_RESOURCE}
        async with httpx.AsyncClient(timeout=15.0) as c:
            r = await c.get(url, params=params, headers={"Metadata": "true"})
            r.raise_for_status()
            data = r.json()
        return data["access_token"], int(data.get("expires_in", 3600))


class GraphChatClient:
    """Headless Teams 1:1 chat poster + email fallback."""

    def __init__(self) -> None:
        self._tokens = _MITokenClient()
        # Prefer issuing tokens as the agent identity itself (via sidecar)
        # whenever it's configured.  Falls back to the host MI silently.
        try:
            self._agent_token_client: AgentIdentityTokenClient | None = (
                AgentIdentityTokenClient()
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("AgentIdentityTokenClient init failed: %s", exc)
            self._agent_token_client = None
        # Cache (member1_id, member2_id) → chat_id so we re-use the same chat.
        self._chat_cache: dict[frozenset[str], str] = {}
        # Records which token source was last used by a write call so callers
        # can surface it for debugging.
        self.last_token_source: str = ""
        # Cached agent-identity Graph token from the Entra auth-sidecar
        # (separate from AgentIdentityTokenClient which uses a different API).
        self._sidecar_graph_cache: _CachedToken | None = None

    @property
    def available(self) -> bool:
        return bool(
            os.getenv("IDENTITY_ENDPOINT")
            or os.getenv("MSI_ENDPOINT")
            or (self._agent_token_client and self._agent_token_client.available)
            or _sidecar_graph_available()
        )

    async def _agent_identity_graph_token(self) -> str | None:
        """Acquire a Graph token *as the agent identity*.

        Two paths, in order:
          1. Entra auth-sidecar (``A365_SIDECAR_URL`` /
             ``A365_SIDECAR_GRAPH_API``) — the official Microsoft sidecar that
             mints Agent-Identity-scoped tokens via Microsoft.Identity.Web.
          2. Legacy custom ``ENTRA_AGENT_ID_SDK_TOKEN_URL`` JSON POST endpoint
             (``AgentIdentityTokenClient``) — kept for backwards compatibility.

        Returns ``None`` when neither path is configured / both fail. Callers
        fall back to the MI token (app-only) in that case.
        """
        # 1) Entra auth-sidecar (preferred).
        if _sidecar_graph_available():
            if self._sidecar_graph_cache and self._sidecar_graph_cache.valid():
                return self._sidecar_graph_cache.token
            try:
                token, ttl = await self._fetch_sidecar_graph_token()
            except Exception as exc:
                logger.warning(
                    "Entra auth-sidecar Graph token acquisition failed: %s", exc
                )
                token = None
                ttl = 0
            if token:
                self._sidecar_graph_cache = _CachedToken(
                    token=token, expires_at=time.time() + max(60, ttl - 60)
                )
                return token
        # 2) Legacy custom token endpoint.
        client = self._agent_token_client
        if client and client.available:
            try:
                return await client.get_token(
                    _DEFAULT_AGENT_GRAPH_SCOPE, resource=GRAPH_RESOURCE
                )
            except Exception as exc:
                logger.warning(
                    "Legacy agent-identity Graph token endpoint failed: %s", exc
                )
        return None

    async def _fetch_sidecar_graph_token(self) -> tuple[str, int]:
        """Call ``GET {SIDECAR_URL}/AuthorizationHeaderUnauthenticated/{api}``.

        This is the Microsoft.Identity.Web sidecar contract used by Microsoft's
        Entra Agent ID auth-sidecar image. The ``AgentIdentity`` query param
        selects which agent identity the sidecar mints the downstream token
        for; the configured downstream API name (default ``graph``) picks the
        target resource (Microsoft Graph).
        """
        sidecar_url = os.getenv("A365_SIDECAR_URL", "http://localhost:5000").rstrip("/")
        downstream_api = (
            os.getenv("A365_SIDECAR_GRAPH_API", "graph").strip() or "graph"
        )
        agent_app_id = (
            os.getenv("A365_AGENT_APP_ID", "").strip()
            or os.getenv("ENTRA_AGENT_IDENTITY_CLIENT_ID", "").strip()
            or os.getenv("ENTRA_AGENT_IDENTITY_OBJECT_ID", "").strip()
        )
        if not agent_app_id:
            raise RuntimeError(
                "agent-identity Graph token needs A365_AGENT_APP_ID or "
                "ENTRA_AGENT_IDENTITY_CLIENT_ID set."
            )
        import uuid
        params = {
            "AgentIdentity": agent_app_id,
            "optionsOverride.AcquireTokenOptions.ForceRefresh": "true",
            "optionsOverride.AcquireTokenOptions.CorrelationId": str(uuid.uuid4()),
        }
        url = (
            f"{sidecar_url}/AuthorizationHeaderUnauthenticated/{downstream_api}"
            f"?{urllib.parse.urlencode(params)}"
        )
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(url)
            if r.status_code != 200:
                raise RuntimeError(
                    f"sidecar {url} returned HTTP {r.status_code}: {r.text[:300]}"
                )
            data = r.json() or {}
        header = data.get("authorizationHeader") or data.get("AuthorizationHeader") or ""
        if not header.lower().startswith("bearer "):
            raise RuntimeError(
                f"sidecar missing Bearer authorizationHeader: {str(data)[:200]}"
            )
        token = header.split(" ", 1)[1].strip()
        ttl = 50 * 60
        expires_on = data.get("expiresOn") or data.get("ExpiresOn")
        if isinstance(expires_on, (int, float)):
            ttl = max(60, int(expires_on) - int(time.time()))
        elif isinstance(expires_on, str):
            try:
                from datetime import datetime
                exp_ts = datetime.fromisoformat(expires_on.replace("Z", "+00:00")).timestamp()
                ttl = max(60, int(exp_ts) - int(time.time()))
            except Exception:
                pass
        logger.info(
            "fetched agent-identity Graph token via sidecar (api=%s agent=%s ttl=%ds)",
            downstream_api, agent_app_id, ttl,
        )
        return token, ttl

    async def _resolve_token(self, *, prefer_agent_identity: bool = False) -> tuple[str, str]:
        """Return (token, source) tuple. source ∈ {"agent_identity", "managed_identity"}."""
        if prefer_agent_identity:
            tok = await self._agent_identity_graph_token()
            if tok:
                return tok, "agent_identity"
        return await self._tokens.get_token(), "managed_identity"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        token: str | None = None,
        prefer_agent_identity: bool = False,
    ) -> tuple[int, Any]:
        if token is None:
            token, source = await self._resolve_token(
                prefer_agent_identity=prefer_agent_identity
            )
            self.last_token_source = source
        url = path if path.startswith("http") else f"{GRAPH_BASE}{path}"
        async with httpx.AsyncClient(timeout=20.0) as c:
            r = await c.request(
                method,
                url,
                json=json,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                },
            )
        ct = (r.headers.get("content-type") or "").lower()
        body: Any
        if "application/json" in ct and r.content:
            try:
                body = r.json()
            except Exception:
                body = r.text
        else:
            body = r.text
        return r.status_code, body

    async def lookup_user_id(self, *, upn_or_email: str = "", aad_object_id: str = "") -> str | None:
        """Resolve to a Graph user id. Prefers AAD object id when present."""
        if aad_object_id:
            status, body = await self._request("GET", f"/users/{aad_object_id}")
            if status == 200 and isinstance(body, dict):
                return body.get("id") or aad_object_id
        if upn_or_email:
            quoted = urllib.parse.quote(upn_or_email)
            status, body = await self._request("GET", f"/users/{quoted}")
            if status == 200 and isinstance(body, dict):
                return body.get("id")
        return None

    async def ensure_one_on_one_chat(self, user_a_id: str, user_b_id: str) -> str | None:
        """Create (or return cached) 1:1 chat id between two users.

        Prefers the agent-identity sidecar token: when the agent identity is
        one of the two members, the chat is created *as* that identity and
        messages we post into it are attributed to the agent identity user.
        """
        if not (user_a_id and user_b_id):
            return None
        key = frozenset({user_a_id, user_b_id})
        cached = self._chat_cache.get(key)
        if cached:
            return cached
        payload = {
            "chatType": "oneOnOne",
            "members": [
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": f"{GRAPH_BASE}/users('{user_a_id}')",
                },
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": f"{GRAPH_BASE}/users('{user_b_id}')",
                },
            ],
        }
        status, body = await self._request(
            "POST", "/chats", json=payload, prefer_agent_identity=True
        )
        logger.info(
            "graph create-chat (agent-identity) members=[%s,%s] status=%s body=%s",
            user_a_id, user_b_id, status, str(body)[:300],
        )
        if status in (200, 201) and isinstance(body, dict):
            chat_id = body.get("id")
            if chat_id:
                self._chat_cache[key] = chat_id
                return chat_id
        # If agent-identity path was tried and refused (e.g. missing scope),
        # retry once with the host MI before giving up.
        if self.last_token_source == "agent_identity":
            logger.info(
                "chat-create with agent-identity token failed (status=%s); retrying with MI",
                status,
            )
            status, body = await self._request(
                "POST", "/chats", json=payload, prefer_agent_identity=False
            )
            logger.info(
                "graph create-chat (MI) members=[%s,%s] status=%s body=%s",
                user_a_id, user_b_id, status, str(body)[:300],
            )
            if status in (200, 201) and isinstance(body, dict):
                chat_id = body.get("id")
                if chat_id:
                    self._chat_cache[key] = chat_id
                    return chat_id
        logger.warning("Graph create chat failed status=%s body=%s", status, str(body)[:600])
        return None

    async def post_chat_message(self, chat_id: str, html: str) -> tuple[bool, str]:
        payload = {"body": {"contentType": "html", "content": html}}
        status, body = await self._request(
            "POST", f"/chats/{chat_id}/messages", json=payload, prefer_agent_identity=True
        )
        if status in (200, 201):
            return True, ""
        # Retry with MI if agent-identity token was rejected.
        if self.last_token_source == "agent_identity":
            logger.info(
                "chat-post with agent-identity token failed (status=%s); retrying with MI",
                status,
            )
            status, body = await self._request(
                "POST", f"/chats/{chat_id}/messages", json=payload, prefer_agent_identity=False
            )
            if status in (200, 201):
                return True, ""
        reason = str(body)[:600]
        logger.warning("Graph post chat message failed status=%s body=%s", status, reason)
        return False, f"HTTP {status}: {reason}"

    async def deliver_hitl_as_agentic_user(
        self,
        *,
        connection_manager: Any,
        tenant_id: str,
        instance_app_id: str,
        agentic_user_id: str,
        manager_user_id: str,
        html: str,
    ) -> dict[str, Any]:
        """Post a HITL message AS the per-user teammate user in a 1:1 chat
        with the manager, using the Microsoft Agents SDK's agentic federated
        user_fic flow to mint a delegated Graph token.

        This is the production HITL delivery path for teammate-mediated runs.
        It bypasses the Entra-Agent-Identity-SP path (which can't be a Teams
        chat member) and the blueprint-app-only path (which can't post to 1:1
        chats it doesn't own). The per-user teammate user is a real
        ME5+Teams-licensed user, so Teams accepts it as a roster member and
        the delegated `Chat.ReadWrite` scope authorizes posting.

        :param connection_manager: ``MsalConnectionManager`` whose default
            ``SERVICE_CONNECTION`` ``MsalAuth`` exposes
            ``get_agentic_user_token``.
        :param tenant_id: tenant GUID.
        :param instance_app_id: per-user teammate's instance app ID
            (the ``agenticAppId`` seen on inbound activities).
        :param agentic_user_id: per-user teammate user's AAD object ID
            (e.g. user account for ``hraiteammate-sivav2@\u2026``).
        :param manager_user_id: the manager's AAD object ID
            (the recipient of the HITL prompt).
        :returns: dict with ``status`` \u2208 {``sent``, ``error``} plus
            ``chatId`` / ``messageId`` / ``reason``.
        """
        if not (connection_manager and tenant_id and instance_app_id and agentic_user_id and manager_user_id):
            return {
                "status": "error",
                "channel": "teams-chat-agentic-user",
                "reason": "missing required arguments",
            }
        # 1) Mint the delegated Graph token via the agentic-user federation.
        try:
            conn = connection_manager.get_default_connection()
            scopes = [
                os.getenv(
                    "ESS_AGENTIC_USER_GRAPH_SCOPE",
                    "https://graph.microsoft.com/.default",
                )
            ]
            token = await conn.get_agentic_user_token(
                tenant_id, instance_app_id, agentic_user_id, scopes
            )
        except Exception as exc:
            logger.warning(
                "agentic-user token acquisition failed instance=%s user=%s: %s",
                instance_app_id, agentic_user_id, exc,
            )
            return {
                "status": "error",
                "channel": "teams-chat-agentic-user",
                "reason": f"token: {type(exc).__name__}: {exc}",
            }
        if not token:
            return {
                "status": "error",
                "channel": "teams-chat-agentic-user",
                "reason": "SDK returned no access_token",
            }
        self.last_token_source = "agentic_user"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        # 2) Ensure (or fetch existing) 1:1 chat. POST /chats with the same
        # two members returns the canonical chat (creates it or returns the
        # existing one); status 200/201 both expose ``id``.
        chat_payload = {
            "chatType": "oneOnOne",
            "members": [
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": f"{GRAPH_BASE}/users/{agentic_user_id}",
                },
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "roles": ["owner"],
                    "user@odata.bind": f"{GRAPH_BASE}/users/{manager_user_id}",
                },
            ],
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            try:
                cr = await client.post(
                    f"{GRAPH_BASE}/chats", json=chat_payload, headers=headers
                )
            except Exception as exc:
                logger.warning("agentic-user chat create raised: %s", exc)
                return {
                    "status": "error",
                    "channel": "teams-chat-agentic-user",
                    "reason": f"create chat: {type(exc).__name__}: {exc}",
                }
            if cr.status_code not in (200, 201):
                logger.warning(
                    "agentic-user chat create failed status=%s body=%s",
                    cr.status_code, cr.text[:600],
                )
                return {
                    "status": "error",
                    "channel": "teams-chat-agentic-user",
                    "reason": f"create chat HTTP {cr.status_code}: {cr.text[:400]}",
                }
            chat_data = cr.json() or {}
            chat_id = chat_data.get("id")
            if not chat_id:
                return {
                    "status": "error",
                    "channel": "teams-chat-agentic-user",
                    "reason": f"create chat returned no id: {str(chat_data)[:300]}",
                }
            # 3) Post the message.
            encoded_chat = urllib.parse.quote(chat_id, safe="")
            try:
                mr = await client.post(
                    f"{GRAPH_BASE}/chats/{encoded_chat}/messages",
                    json={"body": {"contentType": "html", "content": html}},
                    headers=headers,
                )
            except Exception as exc:
                logger.warning("agentic-user post message raised: %s", exc)
                return {
                    "status": "error",
                    "channel": "teams-chat-agentic-user",
                    "chatId": chat_id,
                    "reason": f"post message: {type(exc).__name__}: {exc}",
                }
            if mr.status_code not in (200, 201):
                logger.warning(
                    "agentic-user post message failed status=%s body=%s",
                    mr.status_code, mr.text[:600],
                )
                return {
                    "status": "error",
                    "channel": "teams-chat-agentic-user",
                    "chatId": chat_id,
                    "reason": f"post message HTTP {mr.status_code}: {mr.text[:400]}",
                }
            msg_id = (mr.json() or {}).get("id")
            logger.info(
                "agentic-user HITL delivered chat=%s message=%s user=%s manager=%s",
                chat_id, msg_id, agentic_user_id, manager_user_id,
            )
            return {
                "status": "sent",
                "channel": "teams-chat-agentic-user",
                "chatId": chat_id,
                "messageId": msg_id,
                "tokenSource": "agentic_user",
            }

    async def send_mail_as(self, sender_user_id: str, to_email: str, subject: str, html: str) -> tuple[bool, str]:
        """Last-ditch fallback: send an email from sender_user_id to to_email."""
        if not (sender_user_id and to_email):
            return False, "missing sender_user_id or to_email"
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": html},
                "toRecipients": [{"emailAddress": {"address": to_email}}],
            },
            "saveToSentItems": True,
        }
        status, body = await self._request("POST", f"/users/{sender_user_id}/sendMail", json=payload)
        if status in (200, 202):
            return True, ""
        reason = str(body)[:600]
        logger.warning("Graph sendMail failed status=%s body=%s", status, reason)
        return False, f"HTTP {status}: {reason}"

    async def deliver_hitl(
        self,
        *,
        agent_user_id: str,
        agent_user_upn: str,
        manager_aad_id: str,
        manager_upn: str,
        manager_email: str,
        subject: str,
        html: str,
    ) -> dict[str, Any]:
        """Try Teams 1:1 chat → fall back to email. Returns a status dict."""
        if not self.available:
            return {"status": "unavailable", "reason": "no managed identity endpoint"}

        agent_id_resolved = agent_user_id or await self.lookup_user_id(upn_or_email=agent_user_upn)
        manager_id_resolved = manager_aad_id or await self.lookup_user_id(upn_or_email=manager_upn or manager_email)

        if agent_id_resolved and manager_id_resolved:
            chat_id = await self.ensure_one_on_one_chat(agent_id_resolved, manager_id_resolved)
            if chat_id:
                ok, reason = await self.post_chat_message(chat_id, html)
                if ok:
                    return {
                        "status": "sent",
                        "channel": "teams-chat",
                        "chatId": chat_id,
                        "tokenSource": self.last_token_source,
                    }
                chat_reason = reason
            else:
                chat_reason = "chat creation failed"
        else:
            chat_reason = f"could not resolve users (agent={bool(agent_id_resolved)}, manager={bool(manager_id_resolved)})"

        # Email fallbacks intentionally removed — when Teams 1:1 chat delivery
        # fails we want the run to surface that failure rather than silently
        # masquerading as "delivered" via an email channel the manager isn't
        # monitoring. Fixing chat delivery is the only acceptable resolution.
        return {"status": "error", "channel": "teams-chat", "reason": chat_reason}
