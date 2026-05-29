"""OAuth token providers for MCP bearer-token passthrough."""

from __future__ import annotations

import base64
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from .identity import AgentIdentityTokenClient, CachedToken


@dataclass(frozen=True)
class OAuthConfig:
    name: str
    token_url: str
    client_id: str
    client_secret: str
    scope: str
    audience: str
    resource: str
    grant_type: str
    auth_method: str
    assertion_scope: str
    assertion_resource: str
    refresh_token: str
    authorization_url: str
    redirect_uri: str

    @classmethod
    def for_server(cls, name: str) -> "OAuthConfig":
        prefix = f"ESS_{name.upper()}"
        return cls(
            name=name,
            token_url=os.getenv(f"{prefix}_OAUTH_TOKEN_URL", ""),
            client_id=os.getenv(f"{prefix}_OAUTH_CLIENT_ID", ""),
            client_secret=os.getenv(f"{prefix}_OAUTH_CLIENT_SECRET", ""),
            scope=os.getenv(f"{prefix}_OAUTH_SCOPE", ""),
            audience=os.getenv(f"{prefix}_OAUTH_AUDIENCE", ""),
            resource=os.getenv(f"{prefix}_OAUTH_RESOURCE", ""),
            grant_type=os.getenv(f"{prefix}_OAUTH_GRANT_TYPE", "client_credentials"),
            auth_method=os.getenv(f"{prefix}_OAUTH_AUTH_METHOD", "client_secret_post"),
            assertion_scope=os.getenv(f"{prefix}_OAUTH_ASSERTION_SCOPE", ""),
            assertion_resource=os.getenv(f"{prefix}_OAUTH_ASSERTION_RESOURCE", ""),
            refresh_token=os.getenv(f"{prefix}_OAUTH_REFRESH_TOKEN", ""),
            authorization_url=os.getenv(f"{prefix}_OAUTH_AUTHORIZATION_URL", ""),
            redirect_uri=os.getenv(f"{prefix}_OAUTH_REDIRECT_URI", ""),
        )

    def authorization_request_url(self, state: str) -> str:
        if not self.authorization_url:
            raise RuntimeError(f"No authorization URL configured for {self.name}")
        if not self.redirect_uri:
            raise RuntimeError(f"No redirect URI configured for {self.name}")
        query: dict[str, str] = {
            "response_type": "code",
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
        }
        if self.scope:
            query["scope"] = self.scope
        if self.audience:
            query["audience"] = self.audience
        if self.resource:
            query["resource"] = self.resource
        return f"{self.authorization_url}?{urlencode(query)}"


class ServerTokenProvider:
    async def get_token(self, name: str) -> str:
        raise NotImplementedError


class EnvOrOAuthTokenProvider(ServerTokenProvider):
    """Resolve server tokens from OAuth first, then emergency local fallback.

    Hosted runs should configure ESS_<SERVER>_OAUTH_* so the agent obtains fresh
    SaaS tokens at runtime. Static ESS_<SERVER>_TOKEN is intentionally only an
    emergency local-development escape hatch.
    """

    def __init__(self, agent_tokens: AgentIdentityTokenClient | None = None) -> None:
        self.agent_tokens = agent_tokens or AgentIdentityTokenClient()
        self._cache: dict[str, CachedToken] = {}

    def invalidate(self, name: str) -> None:
        """Drop any cached token for ``name`` so the next call mints fresh.

        Called when an upstream tool returns 401/Unauthorized so we can recover
        from server-side token expiry that occurred before our cached
        ``expires_at`` (clock skew, premature revocation, etc.).
        """
        self._cache.pop(name, None)

    async def get_token(self, name: str) -> str:
        config = OAuthConfig.for_server(name)
        if config.token_url:
            return await self._get_oauth_token(config)

        token = os.getenv(f"ESS_{name.upper()}_TOKEN", "")
        if token:
            return token
        raise RuntimeError(
            f"No token source configured for {name}. Set ESS_{name.upper()}_OAUTH_* "
            f"or, for emergency local testing only, ESS_{name.upper()}_TOKEN."
        )

    async def _get_oauth_token(self, config: OAuthConfig) -> str:
        cached = self._cache.get(config.name)
        if cached and cached.valid():
            return cached.access_token

        body: dict[str, str] = {"grant_type": config.grant_type}
        headers = {"Accept": "application/json"}
        if config.scope:
            body["scope"] = config.scope
        if config.grant_type == "refresh_token":
            if not config.refresh_token:
                raise RuntimeError(f"Refresh-token OAuth is configured for {config.name}, but no refresh token is available")
            body["refresh_token"] = config.refresh_token
        if config.audience:
            body["audience"] = config.audience
        if config.resource:
            body["resource"] = config.resource

        auth: tuple[str, str] | None = None
        if config.auth_method == "client_secret_basic":
            auth = (config.client_id, config.client_secret)
        elif config.auth_method == "client_secret_post":
            body["client_id"] = config.client_id
            body["client_secret"] = config.client_secret
        elif config.auth_method == "agent_client_assertion":
            body["client_id"] = config.client_id
            body["client_assertion_type"] = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"
            body["client_assertion"] = await self._agent_assertion(config)
        elif config.auth_method == "token_exchange":
            body["client_id"] = config.client_id
            if config.client_secret:
                body["client_secret"] = config.client_secret
            body["subject_token_type"] = "urn:ietf:params:oauth:token-type:access_token"
            body["requested_token_type"] = "urn:ietf:params:oauth:token-type:access_token"
            body["subject_token"] = await self._agent_assertion(config)
        elif config.auth_method != "none":
            raise RuntimeError(f"Unsupported OAuth auth method for {config.name}: {config.auth_method}")

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(config.token_url, data=body, headers=headers, auth=auth)
            response.raise_for_status()
            data: dict[str, Any] = response.json()

        access_token = data.get("access_token") or data.get("accessToken")
        if not access_token:
            raise RuntimeError(f"OAuth endpoint for {config.name} did not return access_token")
        expires_in = int(data.get("expires_in") or data.get("expiresIn") or 1800)
        self._cache[config.name] = CachedToken(access_token=access_token, expires_at=time.time() + expires_in)
        return access_token

    async def _agent_assertion(self, config: OAuthConfig) -> str:
        scope = config.assertion_scope or config.scope or f"api://{config.client_id}/.default"
        return await self.agent_tokens.get_token(scope, resource=config.assertion_resource or config.audience)


def basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def authorization_request_url(server_name: str, state: str) -> str:
    return OAuthConfig.for_server(server_name).authorization_request_url(state)


async def exchange_authorization_code(server_name: str, code: str) -> dict[str, Any]:
    config = OAuthConfig.for_server(server_name)
    if not config.token_url:
        raise RuntimeError(f"No token URL configured for {server_name}")
    if not config.redirect_uri:
        raise RuntimeError(f"No redirect URI configured for {server_name}")

    body: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.redirect_uri,
    }
    headers = {"Accept": "application/json"}
    auth: tuple[str, str] | None = None
    if config.auth_method == "client_secret_basic":
        auth = (config.client_id, config.client_secret)
    else:
        body["client_id"] = config.client_id
        if config.client_secret:
            body["client_secret"] = config.client_secret

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(config.token_url, data=body, headers=headers, auth=auth)
        response.raise_for_status()
        return response.json()