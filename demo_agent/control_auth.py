"""Fail-closed Entra delegated-user authentication for the control plane.

Integration (no environment or network work happens merely on import):
    app = web.Application(middlewares=[create_control_auth_middleware(), ...])
    app.on_response_prepare.append(control_auth_response_prepare)

Register the middleware outermost, retaining the Agents SDK JWT middleware for
the exact /api/messages route. That exclusion is NOT authentication: the host
must refuse bot traffic if SDK authentication is unavailable. Register the
response-prepare hook after other header hooks so prepared/SSE responses also
receive the security headers; middleware alone cannot change headers already
sent by a streaming handler.

AZURE_TENANT_ID must be a tenant GUID. AUTOPILOT_CONTROL_PLANE_AUDIENCE must be
one GUID or one exact api:// or https:// application ID URI (never a scope).
AUTOPILOT_OPERATOR_IDS and optional AUTOPILOT_READER_IDS are comma-separated
object GUIDs. Empty lists grant nobody access; malformed settings are errors.
Only these allowlists grant roles, never token roles, names, or actor headers.

The factory checks configuration synchronously in AUTOPILOT_ENVIRONMENT=
production, so missing/invalid tenant or audience prevents app construction.
Elsewhere it creates the validator on the first protected request: public
health/pages still work without configuration, but APIs still deny access.
There is deliberately NO anonymous mode, including on loopback, and
AUTOPILOT_ALLOW_ANONYMOUS_LOCAL is not consulted. Inject a validator for tests.

IMPORTANT: initially, only operators should receive full run/evidence content
in production. Before enabling readers, handlers MUST filter/scrub individual
rows and sensitive fields. POST /api/hitl/{id}/respond still requires an
allowlisted delegated principal; its handler MUST additionally check the
principal's tenant/object ID against that particular approval's intended
recipient and scope. Authentication here does not implement those checks.

Dependencies: PyJWT[crypto], httpx, aiohttp. An injected HTTP client remains
caller-owned. An injected async JWKS fetcher receives only the pinned URL,
never a token. Neither injection may be selected from request data.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import urlsplit
from uuid import UUID

import httpx
import jwt
from aiohttp import web
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from jwt.algorithms import RSAAlgorithm

__all__ = [
    "ControlPrincipal",
    "ControlAuthConfigurationError",
    "ControlAuthenticationError",
    "ControlAuthorizationError",
    "ControlTokenValidator",
    "EntraTokenValidator",
    "create_control_auth_middleware",
    "control_auth_response_prepare",
    "principal_from_request",
    "require_operator",
]

_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_JWT_PATTERN = r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
_COMPACT_JWT = re.compile(_JWT_PATTERN)
_BEARER = re.compile(r"(?i:Bearer) (" + _JWT_PATTERN + r")")
_HITL_RESPONSE = re.compile(r"/api/hitl/[^/]+/respond")
_PRINCIPAL_KEY = "autopilot_principal"
_REQUIRED_SCOPE = "access_agent_as_user"
_PUBLIC_PATHS = frozenset({"/", "/control-plane", "/privacy", "/terms", "/healthz", "/app-config"})
# Systems of record authenticate these by HMAC signature, verified in the handler before any parsing.
_SIGNED_EVENT_PATHS = frozenset({"/api/events/servicenow", "/api/events/salesforce"})
_STATIC_SUFFIXES = frozenset({"css", "js", "png", "jpg", "jpeg", "gif", "svg", "ico", "webp", "woff", "woff2"})
_MAX_TOKEN_LENGTH = 32_768
_MAX_KID_LENGTH = 256
_MAX_JWKS_KEYS = 64
_MAX_JWKS_BYTES = 256 * 1024
_JWKS_TIMEOUT_SECONDS = 10.0
_CACHE_TTL_SECONDS = 3600.0
_REFRESH_COOLDOWN_SECONDS = 60.0

_Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]
_Middleware = Callable[[web.Request, _Handler], Awaitable[web.StreamResponse]]
_JwksFetcher = Callable[[str], Awaitable[Mapping[str, Any]]]


@dataclass(frozen=True)
class ControlPrincipal:
    tenant_id: str
    object_id: str
    name: str
    roles: frozenset[str]


class ControlAuthConfigurationError(ValueError):
    """Missing or malformed trusted configuration; messages omit its values."""


class ControlAuthenticationError(ValueError):
    """Invalid/unverifiable token, deliberately without token/claim details."""

    def __init__(self) -> None:
        super().__init__("Invalid control-plane access token")


class ControlAuthorizationError(PermissionError):
    """A verified delegated user is not on either configured allowlist."""

    def __init__(self) -> None:
        super().__init__("Control-plane access denied")


class ControlTokenValidator(Protocol):
    async def validate(self, token: str) -> ControlPrincipal: ...


def _canonical_guid(value: object) -> str:
    if not isinstance(value, str) or _GUID.fullmatch(value) is None:
        raise ValueError("A GUID is required")
    guid = UUID(value)
    if not guid.int:
        raise ValueError("A nonzero GUID is required")
    return str(guid)


def _configured_guid(name: str, value: str) -> str:
    try:
        return _canonical_guid(value.strip())
    except ValueError:
        raise ControlAuthConfigurationError(f"{name} must contain a GUID") from None


def _configured_ids(name: str) -> frozenset[str]:
    value = os.environ.get(name, "").strip()
    if not value:
        return frozenset()
    # Do not silently drop invalid entries (including trailing commas).
    return frozenset(_configured_guid(name, item) for item in value.split(","))


def _configured_audience() -> str:
    value = os.environ.get("AUTOPILOT_CONTROL_PLANE_AUDIENCE", "").strip()
    message = "AUTOPILOT_CONTROL_PLANE_AUDIENCE must be one GUID or exact application ID URI"
    if _GUID.fullmatch(value):
        return _configured_guid("AUTOPILOT_CONTROL_PLANE_AUDIENCE", value)
    if not value or any(character.isspace() for character in value) or any(
        character in value for character in (",", "*", "\\", "?", "#")
    ):
        raise ControlAuthConfigurationError(message)
    try:
        uri = urlsplit(value)
        if (
            uri.scheme not in {"api", "https"}
            or not uri.hostname
            or uri.username is not None
            or uri.password is not None
            or uri.port is not None
            or value.endswith("/.default")
        ):
            raise ValueError
    except ValueError:
        raise ControlAuthConfigurationError(message) from None
    return value


class EntraTokenValidator:
    """Verify RS256 JWTs and derive roles only from configured object IDs.

    ``http_client`` and ``jwks_fetcher`` are mutually exclusive test/transport
    injection points. Construction validates configuration but performs no I/O.
    Cache entries live at most one hour, contain at most 64 public keys, and
    never contain tokens. One lock coalesces refreshes. An unknown kid or bad
    signature can force at most one refresh per validation; a global 60-second
    cooldown also prevents arbitrary-kid/signature floods from causing a fetch
    per request. A fetch already performed for this request needs no retry.
    Failed fetches are backed off, and expired keys are never used as fallback.
    """

    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        jwks_fetcher: _JwksFetcher | None = None,
    ) -> None:
        if http_client is not None and jwks_fetcher is not None:
            raise ControlAuthConfigurationError("Inject an HTTP client or a JWKS fetcher, not both")
        self._tenant_id = _configured_guid("AZURE_TENANT_ID", os.environ.get("AZURE_TENANT_ID", ""))
        self._audience = _configured_audience()
        self._operator_ids = _configured_ids("AUTOPILOT_OPERATOR_IDS")
        self._reader_ids = _configured_ids("AUTOPILOT_READER_IDS")
        self._issuers = {
            "1.0": f"https://sts.windows.net/{self._tenant_id}/",
            "2.0": f"https://login.microsoftonline.com/{self._tenant_id}/v2.0",
        }
        # Pin the tenant's HTTPS key endpoint. Never discover URLs from a JWT's
        # iss/jku/x5u/jwk headers or from unverified payload claims.
        self._jwks_url = f"https://login.microsoftonline.com/{self._tenant_id}/discovery/v2.0/keys"
        self._http_client = http_client
        self._jwks_fetcher = jwks_fetcher
        self._keys: dict[str, RSAPublicKey] = {}
        self._expires_at = 0.0
        self._generation = 0
        self._retry_after = 0.0
        self._force_refresh_after = 0.0
        self._refresh_lock = asyncio.Lock()

    async def _read_http_jwks(self, client: httpx.AsyncClient) -> Mapping[str, Any]:
        # Explicitly disable redirects even when the injected client enables
        # them. Only a dedicated, credential-free HTTP client should be injected.
        async with client.stream(
            "GET",
            self._jwks_url,
            headers={"Accept": "application/json"},
            timeout=_JWKS_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as response:
            if response.status_code != 200:
                raise ControlAuthenticationError()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > _MAX_JWKS_BYTES:
                    raise ControlAuthenticationError()
                body.extend(chunk)
            return json.loads(body)

    async def _fetch_jwks(self) -> Mapping[str, Any]:
        if self._jwks_fetcher is not None:
            return await self._jwks_fetcher(self._jwks_url)
        if self._http_client is not None:
            return await self._read_http_jwks(self._http_client)
        # A short-lived client per infrequent refresh needs no app cleanup hook.
        async with httpx.AsyncClient(trust_env=False) as client:
            return await self._read_http_jwks(client)

    @staticmethod
    def _parse_jwks(document: Mapping[str, Any]) -> dict[str, RSAPublicKey]:
        if not isinstance(document, Mapping):
            raise ValueError("Invalid key set")
        entries = document.get("keys")
        if not isinstance(entries, list) or not 0 < len(entries) <= _MAX_JWKS_KEYS:
            raise ValueError("Invalid key set")
        keys: dict[str, RSAPublicKey] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Invalid key set")
            if entry.get("kty") != "RSA" or entry.get("use", "sig") != "sig" or entry.get("alg", "RS256") != "RS256":
                continue
            kid = entry.get("kid")
            if not isinstance(kid, str) or not 0 < len(kid) <= _MAX_KID_LENGTH or kid in keys:
                raise ValueError("Invalid key set")
            if "key_ops" in entry and entry["key_ops"] != ["verify"]:
                raise ValueError("Invalid signing key operations")
            if any(field in entry for field in ("d", "p", "q", "dp", "dq", "qi", "oth")):
                raise ValueError("Only public signing keys are accepted")
            # Bound RSA inputs before doing expensive big-integer work.
            if not isinstance(entry.get("n"), str) or not 0 < len(entry["n"]) <= 1400:
                raise ValueError("Invalid RSA modulus")
            if not isinstance(entry.get("e"), str) or not 0 < len(entry["e"]) <= 16:
                raise ValueError("Invalid RSA exponent")
            key = RSAAlgorithm.from_jwk(entry)
            if not isinstance(key, RSAPublicKey) or not 2048 <= key.key_size <= 8192:
                raise ValueError("Unsupported signing key")
            keys[kid] = key
        if not keys:
            raise ValueError("No usable signing keys")
        return keys

    async def _get_keys(
        self, *, force: bool = False, observed_generation: int | None = None
    ) -> tuple[dict[str, RSAPublicKey], int]:
        async with self._refresh_lock:
            now = time.monotonic()
            fresh = bool(self._keys) and now < self._expires_at
            if fresh and (
                not force
                or observed_generation != self._generation
                or now < self._force_refresh_after
            ):
                return self._keys, self._generation
            if now < self._retry_after:
                raise ControlAuthenticationError()
            if force:
                self._force_refresh_after = now + _REFRESH_COOLDOWN_SECONDS
            try:
                document = await asyncio.wait_for(self._fetch_jwks(), timeout=_JWKS_TIMEOUT_SECONDS)
                keys = self._parse_jwks(document)
            except Exception:
                # No logs, exception chaining, payloads, or stale-key fallback.
                # Cancellation (a BaseException) still propagates normally.
                self._retry_after = time.monotonic() + _REFRESH_COOLDOWN_SECONDS
                self._generation += 1
                raise ControlAuthenticationError() from None
            self._keys = keys
            self._expires_at = time.monotonic() + _CACHE_TTL_SECONDS
            self._retry_after = 0.0
            self._generation += 1
            return self._keys, self._generation

    def _principal(self, claims: Mapping[str, Any]) -> ControlPrincipal:
        try:
            version = claims.get("ver")
            if not isinstance(version, str) or version not in self._issuers:
                raise ValueError
            if claims.get("iss") != self._issuers[version] or claims.get("aud") != self._audience:
                raise ValueError
            tenant_id = _canonical_guid(claims.get("tid"))
            object_id = _canonical_guid(claims.get("oid"))
            if tenant_id != self._tenant_id:
                raise ValueError
            for claim in ("exp", "nbf"):
                value = claims.get(claim)
                if type(value) not in (int, float) or not math.isfinite(cast(int | float, value)):
                    raise ValueError
            if claims["exp"] <= claims["nbf"]:
                raise ValueError
            scopes = claims.get("scp")
            if not isinstance(scopes, str) or _REQUIRED_SCOPE not in scopes.split(" "):
                raise ValueError
            # An app-only token has no delegated scp; reject an explicit app
            # identity too, even if it is accompanied by a scope-like claim.
            if "idtyp" in claims and claims["idtyp"] != "user":
                raise ValueError
        except (ValueError, TypeError, OverflowError):
            raise ControlAuthenticationError() from None
        roles = frozenset(
            role
            for role, ids in (("operator", self._operator_ids), ("reader", self._reader_ids))
            if object_id in ids
        )
        if not roles:
            raise ControlAuthorizationError()
        name = claims.get("name")
        return ControlPrincipal(tenant_id, object_id, name if isinstance(name, str) else object_id, roles)

    async def validate(self, token: str) -> ControlPrincipal:
        """Return a verified allowlisted user, or raise a sanitized auth error."""
        if not isinstance(token, str) or len(token) > _MAX_TOKEN_LENGTH or _COMPACT_JWT.fullmatch(token) is None:
            raise ControlAuthenticationError()
        try:
            header = jwt.get_unverified_header(token)
        except (jwt.PyJWTError, ValueError, TypeError):
            raise ControlAuthenticationError() from None
        kid = header.get("kid")
        if (
            header.get("alg") != "RS256"
            or not isinstance(kid, str)
            or not 0 < len(kid) <= _MAX_KID_LENGTH
            or "crit" in header
            or "b64" in header
        ):
            raise ControlAuthenticationError()
        starting_generation = self._generation
        keys, generation = await self._get_keys()
        for attempt in range(2):
            key = keys.get(kid)
            if key is not None:
                try:
                    # Both issuers are statically pinned. The exact version-to-
                    # issuer pairing is checked only AFTER signature validation.
                    claims = jwt.decode(
                        token,
                        key=key,
                        algorithms=["RS256"],
                        audience=self._audience,
                        issuer=list(self._issuers.values()),
                        leeway=0,
                        options={
                            "require": ["exp", "nbf", "aud", "tid", "oid", "iss", "ver", "scp"],
                            "verify_signature": True,
                            "verify_exp": True,
                            "verify_nbf": True,
                            "verify_aud": True,
                            "verify_iss": True,
                            "strict_aud": True,
                        },
                    )
                except jwt.InvalidSignatureError:
                    pass  # A cached key may have rotated; retry once below.
                except (jwt.PyJWTError, ValueError, TypeError, OverflowError):
                    raise ControlAuthenticationError() from None
                else:
                    return self._principal(claims)
            if attempt or generation != starting_generation:
                raise ControlAuthenticationError()
            keys, _ = await self._get_keys(force=True, observed_generation=generation)
        raise ControlAuthenticationError()


def _denial(status: int) -> web.HTTPException:
    exception, label = {
        401: (web.HTTPUnauthorized, "unauthorized"),
        403: (web.HTTPForbidden, "forbidden"),
        404: (web.HTTPNotFound, "not_found"),
    }[status]
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    if status == 401:
        headers["WWW-Authenticate"] = "Bearer"
    return exception(text=json.dumps({"error": label}), content_type="application/json", headers=headers)


def principal_from_request(request: web.Request) -> ControlPrincipal:
    """Return only the middleware's typed principal, never an identity header."""
    principal = request.get(_PRINCIPAL_KEY)
    if not isinstance(principal, ControlPrincipal):
        raise _denial(401)
    return principal


def require_operator(request: web.Request) -> ControlPrincipal:
    """Return the operator, or raise HTTPForbidden (also when unauthenticated)."""
    principal = request.get(_PRINCIPAL_KEY)
    if (
        not isinstance(principal, ControlPrincipal)
        or not isinstance(principal.roles, frozenset)
        or "operator" not in principal.roles
    ):
        raise _denial(403)
    return principal


def _is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _security_headers(request: web.Request, response: web.StreamResponse) -> None:
    response.headers["X-Content-Type-Options"] = "nosniff"
    if _is_api(request.path) or request.path == "/app-config":
        response.headers["Cache-Control"] = "no-store"


async def control_auth_response_prepare(request: web.Request, response: web.StreamResponse) -> None:
    """Register on app.on_response_prepare to cover streaming and error responses."""
    _security_headers(request, response)


def _static_paths(paths: Iterable[str]) -> frozenset[str]:
    result: set[str] = set()
    for path in paths:
        if (
            not isinstance(path, str)
            or not path.startswith("/static/")
            or re.fullmatch(r"/[A-Za-z0-9_./-]+", path) is None
            or any(not part or part.startswith(".") for part in path[1:].split("/"))
            or path.rsplit(".", 1)[-1] not in _STATIC_SUFFIXES
        ):
            raise ControlAuthConfigurationError("Public static paths must be exact reviewed asset paths under /static/")
        result.add(path)
    return frozenset(result)


def create_control_auth_middleware(
    validator: ControlTokenValidator | None = None,
    *,
    public_static_paths: Iterable[str] = (),
) -> _Middleware:
    """Create one app-scoped guard; injected validators are trusted code only.

    Only exact public paths/assets permit anonymous GET/HEAD. No directory or
    prefix bypasses are supported. All other non-API paths return 404. Every
    non-GET API request (including HEAD/OPTIONS) needs an operator, except the
    exact authenticated POST HITL response route whose object scope the handler
    must enforce. Register ``control_auth_response_prepare`` for SSE headers.
    """
    assets = _static_paths(public_static_paths)
    resolved_validator = validator
    if resolved_validator is None and os.environ.get("AUTOPILOT_ENVIRONMENT", "").strip().lower() == "production":
        resolved_validator = EntraTokenValidator()

    @web.middleware
    async def middleware(request: web.Request, handler: _Handler) -> web.StreamResponse:
        nonlocal resolved_validator
        try:
            path = request.path
            if path.startswith("/api/diag"):
                raise _denial(404)
            if path == "/api/messages":
                pass  # The host MUST retain separate Agents SDK JWT validation.
            elif path in _SIGNED_EVENT_PATHS and request.method == "POST":
                pass
            elif path in (_PUBLIC_PATHS | assets) and request.method in {"GET", "HEAD"}:
                pass
            elif not _is_api(path):
                raise _denial(404)
            else:
                authorizations = request.headers.getall("Authorization", [])
                if len(authorizations) != 1 or len(authorizations[0]) > _MAX_TOKEN_LENGTH + 7:
                    raise _denial(401)
                match = _BEARER.fullmatch(authorizations[0])
                if match is None:
                    raise _denial(401)
                try:
                    if resolved_validator is None:
                        resolved_validator = EntraTokenValidator()
                    principal = await resolved_validator.validate(match.group(1))
                except ControlAuthorizationError:
                    raise _denial(403) from None
                except Exception:
                    # Configuration/network/library failures never allow a
                    # fallback principal or leak token-bearing error details.
                    raise _denial(401) from None
                if not isinstance(principal, ControlPrincipal) or not isinstance(principal.roles, frozenset):
                    raise _denial(401)
                if not principal.roles.intersection({"operator", "reader"}):
                    raise _denial(403)
                request[_PRINCIPAL_KEY] = principal
                hitl_response = request.method == "POST" and _HITL_RESPONSE.fullmatch(path) is not None
                if request.method != "GET" and not hitl_response:
                    require_operator(request)
            response = await handler(request)
        except web.HTTPException as error:
            _security_headers(request, error)
            raise
        _security_headers(request, response)
        return response

    return middleware