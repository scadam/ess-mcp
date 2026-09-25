"""Offline unittest coverage for control-plane JWTs and aiohttp authorization.

RSA keys are generated in memory, never saved. JWT key retrieval always uses
an injected callback or httpx.MockTransport; no Entra endpoints are contacted.
aiohttp.test_utils uses only its temporary loopback test servers. Middleware
stubs deliberately use non-Azure identity strings: they are trusted test
injections, not an anonymous/local authentication feature.
"""

from __future__ import annotations

import asyncio
import base64
import os
import time
import unittest
from collections.abc import Iterable, Mapping
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch

import httpx
import jwt
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer, make_mocked_request
from cryptography.hazmat.primitives.asymmetric import rsa

from demo_agent import control_auth
from demo_agent.control_auth import (
    ControlAuthConfigurationError,
    ControlAuthenticationError,
    ControlAuthorizationError,
    ControlPrincipal,
    EntraTokenValidator,
    control_auth_response_prepare,
    create_control_auth_middleware,
    principal_from_request,
    require_operator,
)

# Synthetic GUID fixtures, not identities in any Azure tenant.
TENANT = "11111111-1111-4111-8111-1111111111aa"
AUDIENCE = "22222222-2222-4222-8222-2222222222bb"
OPERATOR = "33333333-3333-4333-8333-3333333333cc"
READER = "44444444-4444-4444-8444-4444444444dd"
OUTSIDER = "55555555-5555-4555-8555-5555555555ee"
OTHER_TENANT = "66666666-6666-4666-8666-6666666666ff"
JWKS_URL = f"https://login.microsoftonline.com/{TENANT}/discovery/v2.0/keys"
ENVIRONMENT = {
    "AZURE_TENANT_ID": TENANT,
    "AUTOPILOT_CONTROL_PLANE_AUDIENCE": AUDIENCE,
    "AUTOPILOT_OPERATOR_IDS": OPERATOR,
    "AUTOPILOT_READER_IDS": READER,
    "AUTOPILOT_ENVIRONMENT": "development",
}
STUB_TOKEN = "e30.e30.c2ln"
BEARER = {"Authorization": f"Bearer {STUB_TOKEN}"}


def _jwk(private_key: rsa.RSAPrivateKey, kid: str = "key-1") -> dict[str, Any]:
    numbers = private_key.public_key().public_numbers()

    def encode(value: int) -> str:
        raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return {"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256", "n": encode(numbers.n), "e": encode(numbers.e)}


class ConfigurationAndPrincipalTests(unittest.TestCase):
    def setUp(self) -> None:
        environment = patch.dict(os.environ, ENVIRONMENT, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_invalid_configuration_fails_closed(self) -> None:
        cases = [
            ("AZURE_TENANT_ID", ""),
            ("AZURE_TENANT_ID", "common"),
            ("AZURE_TENANT_ID", TENANT.replace("-", "")),
            ("AZURE_TENANT_ID", "00000000-0000-0000-0000-000000000000"),
            ("AUTOPILOT_CONTROL_PLANE_AUDIENCE", ""),
            ("AUTOPILOT_CONTROL_PLANE_AUDIENCE", f"{AUDIENCE},{OUTSIDER}"),
            ("AUTOPILOT_CONTROL_PLANE_AUDIENCE", f"api://{AUDIENCE} other-audience"),
            ("AUTOPILOT_CONTROL_PLANE_AUDIENCE", "*"),
            ("AUTOPILOT_CONTROL_PLANE_AUDIENCE", "not-a-uri"),
            ("AUTOPILOT_CONTROL_PLANE_AUDIENCE", "http://example.invalid/api"),
            ("AUTOPILOT_CONTROL_PLANE_AUDIENCE", "https://user:password@example.invalid/api"),
            ("AUTOPILOT_CONTROL_PLANE_AUDIENCE", "https://example.invalid/api?aud=other"),
            ("AUTOPILOT_CONTROL_PLANE_AUDIENCE", f"api://{AUDIENCE}/.default"),
            ("AUTOPILOT_OPERATOR_IDS", "someone@example.invalid"),
            ("AUTOPILOT_OPERATOR_IDS", f"{OPERATOR},"),
            ("AUTOPILOT_READER_IDS", f"{READER},not-a-guid"),
        ]
        for setting, value in cases:
            with self.subTest(setting=setting, value=value), patch.dict(os.environ, {setting: value}):
                with self.assertRaises(ControlAuthConfigurationError) as caught:
                    EntraTokenValidator(jwks_fetcher=AsyncMock())
                self.assertIn(setting, str(caught.exception))
                if value and value != "*":
                    self.assertNotIn(value, str(caught.exception))

    def test_injections_are_mutually_exclusive(self) -> None:
        with self.assertRaises(ControlAuthConfigurationError):
            EntraTokenValidator(http_client=Mock(spec=httpx.AsyncClient), jwks_fetcher=AsyncMock())

    def test_production_factory_checks_configuration_without_io(self) -> None:
        with patch.dict(os.environ, {"AUTOPILOT_ENVIRONMENT": " Production "}):
            for setting in ("AZURE_TENANT_ID", "AUTOPILOT_CONTROL_PLANE_AUDIENCE"):
                with self.subTest(setting=setting), patch.dict(os.environ, {setting: ""}):
                    with self.assertRaises(ControlAuthConfigurationError):
                        create_control_auth_middleware()
            with patch.object(control_auth.httpx, "AsyncClient", side_effect=AssertionError("Unexpected HTTP client")):
                self.assertTrue(callable(create_control_auth_middleware()))

    def test_principal_is_frozen_and_helpers_do_not_trust_headers(self) -> None:
        operator = ControlPrincipal("offline-tenant", "offline-operator", "Operator", frozenset({"operator"}))
        with self.assertRaises(FrozenInstanceError):
            setattr(operator, "name", "Changed")
        self.assertIsInstance(operator.roles, frozenset)
        request = make_mocked_request("GET", "/api/runs", headers={"X-Actor": OPERATOR, "X-User": OPERATOR})
        with self.assertRaises(web.HTTPUnauthorized) as unauthorized:
            principal_from_request(request)
        self.assertEqual(unauthorized.exception.content_type, "application/json")
        with self.assertRaises(web.HTTPForbidden):
            require_operator(request)
        request["autopilot_principal"] = {"roles": ["operator"]}
        with self.assertRaises(web.HTTPUnauthorized):
            principal_from_request(request)
        with self.assertRaises(web.HTTPForbidden):
            require_operator(request)
        request["autopilot_principal"] = operator
        self.assertIs(principal_from_request(request), operator)
        self.assertIs(require_operator(request), operator)
        request["autopilot_principal"] = ControlPrincipal("offline-tenant", "offline-reader", "Reader", frozenset({"reader"}))
        with self.assertRaises(web.HTTPForbidden) as forbidden:
            require_operator(request)
        self.assertEqual(forbidden.exception.headers["Cache-Control"], "no-store")
        # Runtime type annotations alone must not permit substring membership
        # or mutable role collections to satisfy the public helper's guard.
        for malformed_roles in ("not-an-operator", ["operator"], None):
            request["autopilot_principal"] = ControlPrincipal(
                "offline", "offline", "Offline", cast(frozenset[str], malformed_roles)
            )
            with self.assertRaises(web.HTTPForbidden):
                require_operator(request)

    def test_static_allowlist_cannot_exempt_apis_or_directories(self) -> None:
        for path in (
            "/api/runs", "/api/messages", "/static/", "/static/*", "/static/../private.js",
            "/static/.env.js", "/static/app.js?x=1", "/static/%2e%2e/private.js",
            "/static/app.js/", "/static/config.json", "/static/app.js.map",
        ):
            with self.subTest(path=path), self.assertRaises(ControlAuthConfigurationError):
                create_control_auth_middleware(public_static_paths=[path])


class EntraTokenValidatorTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.rotated_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self) -> None:
        environment = patch.dict(os.environ, ENVIRONMENT, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.document = {"keys": [_jwk(self.signing_key)]}
        self.fetcher = AsyncMock(return_value=self.document)
        self.validator = EntraTokenValidator(jwks_fetcher=self.fetcher)

    def claims(self) -> dict[str, Any]:
        now = int(time.time())
        return {
            "aud": AUDIENCE, "tid": TENANT, "oid": OPERATOR,
            "iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "ver": "2.0",
            "exp": now + 600, "nbf": now - 60,
            "scp": "openid access_agent_as_user profile", "name": "Offline operator", "idtyp": "user",
        }

    def token(
        self,
        *,
        claims: Mapping[str, Any] | None = None,
        omit: Iterable[str] = (),
        key: rsa.RSAPrivateKey | None = None,
        headers: Mapping[str, Any] | None = None,
    ) -> str:
        payload = self.claims()
        payload.update(claims or {})
        for claim in omit:
            payload.pop(claim, None)
        return jwt.encode(payload, key or self.signing_key, algorithm="RS256", headers={"kid": "key-1", **(headers or {})})

    async def test_valid_v2_principal_and_pinned_key_url(self) -> None:
        token = self.token(headers={
            "jku": "https://attacker.invalid/keys", "x5u": "https://attacker.invalid/cert",
            "jwk": _jwk(self.rotated_key),
        })
        principal = await self.validator.validate(token)
        self.assertEqual(principal, ControlPrincipal(TENANT, OPERATOR, "Offline operator", frozenset({"operator"})))
        self.fetcher.assert_awaited_once_with(JWKS_URL)

    async def test_valid_v1_issuer_is_paired_with_verified_version(self) -> None:
        principal = await self.validator.validate(self.token(claims={"ver": "1.0", "iss": f"https://sts.windows.net/{TENANT}/"}))
        self.assertEqual(principal.object_id, OPERATOR)
        for claims in (
            {"ver": "1.0"},
            {"iss": f"https://sts.windows.net/{TENANT}/"},
            {"ver": "3.0"},
            {"iss": f"https://sts.windows.net/{TENANT}"},
        ):
            with self.subTest(claims=claims), self.assertRaises(ControlAuthenticationError):
                await self.validator.validate(self.token(claims=claims))

    async def test_exact_application_id_uri_audiences(self) -> None:
        for audience in (f"api://{AUDIENCE}", "https://example.invalid/control-plane"):
            with self.subTest(audience=audience), patch.dict(os.environ, {"AUTOPILOT_CONTROL_PLANE_AUDIENCE": audience}):
                validator = EntraTokenValidator(jwks_fetcher=self.fetcher)
                self.assertEqual((await validator.validate(self.token(claims={"aud": audience}))).object_id, OPERATOR)
                for bad_audience in (AUDIENCE, [audience], audience + "/other"):
                    with self.assertRaises(ControlAuthenticationError):
                        await validator.validate(self.token(claims={"aud": bad_audience}))

    async def test_allowlists_are_normalized_and_token_roles_are_ignored(self) -> None:
        with patch.dict(os.environ, {
            "AZURE_TENANT_ID": TENANT.upper(),
            "AUTOPILOT_CONTROL_PLANE_AUDIENCE": AUDIENCE.upper(),
            "AUTOPILOT_OPERATOR_IDS": f" {OPERATOR.upper()}, {OUTSIDER} , {OPERATOR}",
            "AUTOPILOT_READER_IDS": f"{READER}, {OPERATOR}",
        }):
            validator = EntraTokenValidator(jwks_fetcher=self.fetcher)
        principal = await validator.validate(self.token(claims={"oid": OPERATOR.upper(), "roles": ["administrator"]}, omit=["name"]))
        self.assertEqual(principal.roles, frozenset({"operator", "reader"}))
        self.assertEqual(principal.object_id, OPERATOR)
        self.assertEqual(principal.name, OPERATOR)
        reader = await validator.validate(self.token(claims={"oid": READER, "roles": ["operator"]}))
        self.assertEqual(reader.roles, frozenset({"reader"}))

    async def test_unlisted_and_empty_allowlists_deny_valid_tokens(self) -> None:
        with self.assertRaises(ControlAuthorizationError):
            await self.validator.validate(self.token(claims={"oid": OUTSIDER, "roles": ["operator"]}))
        with patch.dict(os.environ, {"AUTOPILOT_OPERATOR_IDS": "", "AUTOPILOT_READER_IDS": ""}):
            validator = EntraTokenValidator(jwks_fetcher=self.fetcher)
        with self.assertRaises(ControlAuthorizationError):
            await validator.validate(self.token())

    async def test_claim_failures_are_rejected_without_rotation(self) -> None:
        await self.validator.validate(self.token())
        now = int(time.time())
        cases = [
            {"aud": OUTSIDER}, {"aud": [AUDIENCE]}, {"tid": OTHER_TENANT}, {"tid": "common"},
            {"oid": "not-a-guid"}, {"oid": "00000000-0000-0000-0000-000000000000"},
            {"iss": f"https://login.microsoftonline.com/{OTHER_TENANT}/v2.0"},
            {"iss": "https://attacker.invalid/v2.0"},
            {"iss": f"http://login.microsoftonline.com/{TENANT}/v2.0"},
            {"exp": now - 120}, {"nbf": now + 300}, {"exp": str(now + 600)},
            {"nbf": str(now - 60)}, {"nbf": False}, {"exp": float("inf")},
            {"scp": ""}, {"scp": "access_agent_as_user_extra"}, {"scp": "prefix_access_agent_as_user"},
            {"scp": ["access_agent_as_user"]}, {"scp": "access_agent_as_user\tother"},
            {"idtyp": "app"}, {"idtyp": None}, {"ver": 2}, {"ver": ["2.0"]},
        ]
        for claims in cases:
            with self.subTest(claims=claims), self.assertRaises(ControlAuthenticationError):
                await self.validator.validate(self.token(claims=claims))
        for claim in ("exp", "nbf", "aud", "tid", "oid", "iss", "ver", "scp"):
            with self.subTest(missing=claim), self.assertRaises(ControlAuthenticationError):
                await self.validator.validate(self.token(omit=[claim]))
        self.fetcher.assert_awaited_once_with(JWKS_URL)

    async def test_app_only_and_id_token_shapes_are_denied(self) -> None:
        for token in (
            self.token(claims={"idtyp": "app", "roles": ["operator"]}, omit=["scp"]),
            self.token(claims={"idtyp": "app", "roles": ["operator"]}),
            self.token(omit=["scp", "idtyp"]),
        ):
            with self.assertRaises(ControlAuthenticationError):
                await self.validator.validate(token)
        # idtyp is optional on real delegated tokens; scp is not optional.
        self.assertEqual((await self.validator.validate(self.token(omit=["idtyp"]))).object_id, OPERATOR)

    async def test_unsigned_wrong_algorithm_and_bad_headers_do_not_fetch(self) -> None:
        tokens = [
            jwt.encode(self.claims(), key=None, algorithm="none", headers={"kid": "key-1"}),
            jwt.encode(self.claims(), key=b"offline-hmac-key-that-is-not-an-rsa-signing-key", algorithm="HS256", headers={"kid": "key-1"}),
            self.token(headers={"kid": ""}), self.token(headers={"kid": "x" * 257}),
            self.token(headers={"crit": ["unknown"]}),
            jwt.encode(self.claims(), self.signing_key, algorithm="RS256"),
            "not-a-jwt", "A.B.C", "A.B.C.D", "x" * 32769,
        ]
        for token in tokens:
            with self.subTest(length=len(token)), self.assertRaises(ControlAuthenticationError):
                await self.validator.validate(token)
        self.fetcher.assert_not_awaited()

    async def test_initial_concurrent_validation_fetches_once(self) -> None:
        entered, release = asyncio.Event(), asyncio.Event()

        async def fetch(_url: str) -> Mapping[str, Any]:
            entered.set()
            await release.wait()
            return self.document

        self.fetcher.side_effect = fetch
        token = self.token()
        tasks = [asyncio.create_task(self.validator.validate(token)) for _ in range(32)]
        await entered.wait()
        release.set()
        principals = await asyncio.gather(*tasks)
        self.assertTrue(all(principal.object_id == OPERATOR for principal in principals))
        self.fetcher.assert_awaited_once_with(JWKS_URL)

    async def test_unknown_kid_rotation_is_one_coalesced_forced_refresh(self) -> None:
        await self.validator.validate(self.token())
        self.fetcher.return_value = {"keys": [_jwk(self.rotated_key, "key-2")]}
        token = self.token(key=self.rotated_key, headers={"kid": "key-2"})
        principals = await asyncio.gather(*(self.validator.validate(token) for _ in range(32)))
        self.assertTrue(all(principal.object_id == OPERATOR for principal in principals))
        self.assertEqual(self.fetcher.await_count, 2)
        self.assertEqual(len(self.validator._keys), 1)

    async def test_same_kid_signature_rotation_retries_once(self) -> None:
        await self.validator.validate(self.token())
        self.fetcher.return_value = {"keys": [_jwk(self.rotated_key)]}
        self.assertEqual((await self.validator.validate(self.token(key=self.rotated_key))).object_id, OPERATOR)
        self.assertEqual(self.fetcher.await_count, 2)

    async def test_invalid_signature_and_random_kid_flood_are_bounded(self) -> None:
        await self.validator.validate(self.token())
        bad_signature = self.token(key=self.rotated_key)
        tokens = [bad_signature] * 16 + [self.token(headers={"kid": f"unknown-{index}"}) for index in range(32)]
        results = await asyncio.gather(*(self.validator.validate(token) for token in tokens), return_exceptions=True)
        self.assertTrue(all(isinstance(result, ControlAuthenticationError) for result in results))
        self.assertEqual(self.fetcher.await_count, 2)
        # The cooldown applies to later requests too, not just overlapping ones.
        with self.assertRaises(ControlAuthenticationError):
            await self.validator.validate(self.token(headers={"kid": "another-unknown"}))
        self.assertEqual(self.fetcher.await_count, 2)
        self.assertEqual(set(self.validator._keys), {"key-1"})

    async def test_cache_expires_at_one_hour_and_never_extends_on_reads(self) -> None:
        token = self.token()
        with patch.object(control_auth, "time") as clock:
            clock.monotonic.return_value = 1000.0
            await self.validator.validate(token)
            self.assertEqual(self.validator._expires_at, 4600.0)
            clock.monotonic.return_value = 4599.0
            await self.validator.validate(token)
            self.assertEqual(self.validator._expires_at, 4600.0)
            self.assertEqual(self.fetcher.await_count, 1)
            clock.monotonic.return_value = 4600.0
            await self.validator.validate(token)
            self.assertEqual(self.fetcher.await_count, 2)

    async def test_expired_keys_and_refresh_failures_never_fall_back(self) -> None:
        token = self.token()
        with patch.object(control_auth, "time") as clock:
            clock.monotonic.return_value = 1000.0
            await self.validator.validate(token)
            clock.monotonic.return_value = 4600.0
            self.fetcher.side_effect = RuntimeError("sensitive-upstream-response")
            results = await asyncio.gather(*(self.validator.validate(token) for _ in range(24)), return_exceptions=True)
            self.assertTrue(all(isinstance(result, ControlAuthenticationError) for result in results))
            self.assertTrue(all("sensitive-upstream-response" not in str(result) for result in results))
            self.assertEqual(self.fetcher.await_count, 2)
            clock.monotonic.return_value = 4660.0
            self.fetcher.side_effect = None
            await self.validator.validate(token)
            self.assertEqual(self.fetcher.await_count, 3)

    async def test_forced_refresh_failure_is_coalesced_without_extending_cache(self) -> None:
        with patch.object(control_auth, "time") as clock:
            clock.monotonic.return_value = 1000.0
            await self.validator.validate(self.token())
            self.fetcher.side_effect = RuntimeError("sensitive-upstream-response")
            bad = self.token(headers={"kid": "rotated"})
            results = await asyncio.gather(*(self.validator.validate(bad) for _ in range(24)), return_exceptions=True)
            self.assertTrue(all(isinstance(result, ControlAuthenticationError) for result in results))
            self.assertEqual(self.fetcher.await_count, 2)
            self.assertEqual(self.validator._expires_at, 4600.0)
            # Already cached keys are usable only inside their original TTL.
            self.assertEqual((await self.validator.validate(self.token())).object_id, OPERATOR)

    async def test_fetcher_has_wall_clock_timeout(self) -> None:
        cancelled = asyncio.Event()

        async def never_finishes(_url: str) -> Mapping[str, Any]:
            try:
                await asyncio.Event().wait()
                return self.document
            finally:
                cancelled.set()

        validator = EntraTokenValidator(jwks_fetcher=never_finishes)
        with patch.object(control_auth, "_JWKS_TIMEOUT_SECONDS", 0.01):
            with self.assertRaises(ControlAuthenticationError):
                await validator.validate(self.token())
        self.assertTrue(cancelled.is_set())

    async def test_malformed_ambiguous_and_oversized_jwks_fail_closed(self) -> None:
        valid = _jwk(self.signing_key)
        documents = [
            {}, {"keys": []}, {"keys": "not-a-list"}, {"keys": [None]},
            {"keys": [valid, valid]}, {"keys": [valid] * 65},
            {"keys": [dict(valid, kid="")]}, {"keys": [dict(valid, d="private")]},
            {"keys": [dict(valid, kty="oct")]}, {"keys": [dict(valid, alg="RS512")]},
            {"keys": [dict(valid, use="enc")]}, {"keys": [dict(valid, key_ops=["sign"])]},
            {"keys": [dict(valid, n="x" * 1401)]}, {"keys": [dict(valid, e="")]},
        ]
        for index, document in enumerate(documents):
            with self.subTest(case=index):
                fetcher = AsyncMock(return_value=document)
                validator = EntraTokenValidator(jwks_fetcher=fetcher)
                for _ in range(2):
                    with self.assertRaises(ControlAuthenticationError):
                        await validator.validate(self.token())
                fetcher.assert_awaited_once_with(JWKS_URL)

    async def test_http_client_is_pinned_timed_and_caller_owned(self) -> None:
        requests: list[httpx.Request] = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            self.assertEqual(str(request.url), JWKS_URL)
            self.assertNotIn("authorization", request.headers)
            self.assertEqual(set(request.extensions["timeout"].values()), {10.0})
            return httpx.Response(200, json=self.document)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond), timeout=99, follow_redirects=True) as client:
            validator = EntraTokenValidator(http_client=client)
            await validator.validate(self.token())
            self.assertFalse(client.is_closed)
        self.assertEqual(len(requests), 1)

    async def test_http_redirects_errors_invalid_json_and_large_bodies_are_denied(self) -> None:
        responses = [
            httpx.Response(302, headers={"Location": "https://attacker.invalid/jwks"}),
            httpx.Response(500, text="sensitive-upstream-response"),
            httpx.Response(200, text="not-json"),
            httpx.Response(200, content=b" " * (256 * 1024 + 1)),
        ]
        for response in responses:
            with self.subTest(status=response.status_code):
                visited: list[str] = []

                def respond(request: httpx.Request) -> httpx.Response:
                    visited.append(str(request.url))
                    return response

                async with httpx.AsyncClient(transport=httpx.MockTransport(respond), follow_redirects=True) as client:
                    validator = EntraTokenValidator(http_client=client)
                    with self.assertRaises(ControlAuthenticationError):
                        await validator.validate(self.token())
                self.assertEqual(visited, [JWKS_URL])

    async def test_real_jwt_attacks_are_denied_by_middleware(self) -> None:
        handled: list[ControlPrincipal] = []

        async def handler(request: web.Request) -> web.Response:
            handled.append(principal_from_request(request))
            return web.json_response({"ok": True})

        app = web.Application(middlewares=[create_control_auth_middleware(self.validator)])
        app.on_response_prepare.append(control_auth_response_prepare)
        app.router.add_get("/api/runs", handler)
        client = TestClient(TestServer(app))
        self.addAsyncCleanup(client.close)
        await client.start_server()
        response = await client.get("/api/runs", headers={"Authorization": f"Bearer {self.token()}"})
        self.assertEqual(response.status, 200)
        attacks = [
            (self.token(key=self.rotated_key), 401),
            (self.token(claims={"aud": OUTSIDER}), 401),
            (self.token(claims={"tid": OTHER_TENANT}), 401),
            (self.token(claims={"exp": int(time.time()) - 120}), 401),
            (self.token(claims={"idtyp": "app"}), 401),
            (self.token(omit=["scp"]), 401),
            (self.token(claims={"oid": OUTSIDER, "roles": ["operator"]}), 403),
        ]
        for token, status in attacks:
            response = await client.get("/api/runs", headers={"Authorization": f"Bearer {token}", "X-Actor": OPERATOR})
            self.assertEqual(response.status, status)
            self.assertEqual(await response.json(), {"error": "forbidden" if status == 403 else "unauthorized"})
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(len(handled), 1)


class ControlMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        environment = patch.dict(os.environ, ENVIRONMENT, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        self.operator = ControlPrincipal("offline-tenant", "offline-operator", "Operator", frozenset({"operator"}))
        self.reader = ControlPrincipal("offline-tenant", "offline-reader", "Reader", frozenset({"reader"}))
        self.validator = SimpleNamespace(validate=AsyncMock(return_value=self.operator))
        self.handled: list[tuple[str, str]] = []
        self.seen_principals: list[Any] = []

    async def handler(self, request: web.Request) -> web.StreamResponse:
        self.handled.append((request.method, request.path))
        principal = request.get("autopilot_principal")
        self.seen_principals.append(principal)
        if request.path == "/api/stream":
            response = web.StreamResponse(headers={"Cache-Control": "public", "X-Content-Type-Options": "wrong"})
            await response.prepare(request)
            await response.write(b"data: offline\n\n")
            await response.write_eof()
            return response
        if request.path == "/api/error":
            raise web.HTTPNotFound()
        return web.json_response(
            {"object_id": principal.object_id if isinstance(principal, ControlPrincipal) else None},
            headers={"Cache-Control": "public", "X-Content-Type-Options": "wrong"},
        )

    async def client(
        self,
        *,
        use_injected_validator: bool = True,
        public_static_paths: Iterable[str] = (),
        sdk_middleware: Any = None,
    ) -> TestClient:
        middleware = create_control_auth_middleware(
            self.validator if use_injected_validator else None,
            public_static_paths=public_static_paths,
        )
        middlewares = [middleware]
        if sdk_middleware is not None:
            middlewares.append(sdk_middleware)
        app = web.Application(middlewares=middlewares)
        app.on_response_prepare.append(control_auth_response_prepare)
        app.router.add_route("*", "/{tail:.*}", self.handler)
        client = TestClient(TestServer(app))
        self.addAsyncCleanup(client.close)
        await client.start_server()
        return client

    async def test_public_pages_are_exact_and_do_not_validate(self) -> None:
        client = await self.client()
        for path in ("/", "/control-plane", "/privacy", "/terms", "/healthz", "/app-config"):
            for method in ("GET", "HEAD"):
                response = await client.request(method, path, headers={"Authorization": "malformed"})
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                if path == "/app-config":
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.validator.validate.assert_not_awaited()
        self.assertTrue(all(principal is None for principal in self.seen_principals))
        for path in ("/control-plane/", "/privacy/extra", "/healthz/extra", "/app-config/", "/app-config/extra", "/static/app.js", "/other"):
            response = await client.get(path)
            self.assertEqual(response.status, 404)
        response = await client.post("/healthz")
        self.assertEqual(response.status, 404)
        self.assertEqual((await client.post("/app-config")).status, 404)

    async def test_only_declared_static_assets_are_public(self) -> None:
        client = await self.client(public_static_paths=["/static/control.js", "/static/css/control.css"])
        for path in ("/static/control.js", "/static/css/control.css"):
            self.assertEqual((await client.get(path)).status, 200)
        for path in ("/static/other.js", "/static/control.js/extra", "/static/css/"):
            self.assertEqual((await client.get(path)).status, 404)
        self.assertEqual((await client.post("/static/control.js")).status, 404)
        self.validator.validate.assert_not_awaited()

    async def test_messages_is_exact_sdk_owned_exclusion(self) -> None:
        sdk_seen: list[str] = []

        @web.middleware
        async def sdk_guard(request: web.Request, handler: Any) -> web.StreamResponse:
            if request.path == "/api/messages":
                sdk_seen.append(request.path)
                if request.headers.get("Authorization") != "Bearer offline-sdk-token":
                    raise web.HTTPUnauthorized()
            return await handler(request)

        client = await self.client(sdk_middleware=sdk_guard)
        response = await client.post("/api/messages")
        self.assertEqual(response.status, 401)
        response = await client.post("/api/messages", headers={"Authorization": "Bearer offline-sdk-token"})
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertIsNone(self.seen_principals[-1])
        self.assertEqual(len(sdk_seen), 2)
        for path in ("/api/messages/", "/api/messages/extra"):
            self.assertEqual((await client.post(path)).status, 401)
        self.validator.validate.assert_not_awaited()

    async def test_all_diagnostics_are_hidden_even_from_operators(self) -> None:
        client = await self.client()
        for path in ("/api/diag", "/api/diag/", "/api/diag/sdk-source", "/api/diag/nested/token", "/api/diagnostics"):
            for method in ("GET", "POST", "DELETE"):
                for headers in ({}, BEARER):
                    response = await client.request(method, path, headers=headers)
                    self.assertEqual(response.status, 404)
                    self.assertEqual(await response.json(), {"error": "not_found"})
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.validator.validate.assert_not_awaited()
        self.assertEqual(self.handled, [])

    async def test_bearer_format_duplicate_headers_and_actor_shortcuts_are_denied(self) -> None:
        client = await self.client()
        headers_to_reject: list[Any] = [
            {}, {"X-Actor": OPERATOR}, {"X-User": OPERATOR}, {"X-User-Principal-Name": OPERATOR},
            {"X-MS-Client-Principal-Name": OPERATOR}, {"X-MS-Client-Principal": "operator"},
            {"Cookie": f"access_token={STUB_TOKEN}"},
            [("Authorization", BEARER["Authorization"]), ("Authorization", BEARER["Authorization"])],
        ]
        for value in ("", "Basic dGVzdA==", "Bearer", "Bearer one", "Bearer A.B", "Bearer A.B.C.D", "Bearer  A.B.C", "Bearer\tA.B.C", "Bearer A.B.C extra", "Bearer A.B.C,Bearer D.E.F"):
            headers_to_reject.append({"Authorization": value})
        for headers in headers_to_reject:
            response = await client.get(f"/api/runs?access_token={STUB_TOKEN}", headers=headers)
            self.assertEqual(response.status, 401)
            self.assertEqual(await response.json(), {"error": "unauthorized"})
            self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
            self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.validator.validate.assert_not_awaited()
        self.assertEqual(self.handled, [])

    async def test_operator_can_read_write_and_identity_is_not_an_actor_header(self) -> None:
        client = await self.client()
        for method in ("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"):
            response = await client.request(method, "/api/runs", headers={**BEARER, "X-Actor": "arbitrary-actor"})
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertIs(self.seen_principals[-1], self.operator)
        self.validator.validate.assert_awaited_with(STUB_TOKEN)
        response = await client.get("/api/runs", headers={"Authorization": f"bEaReR {STUB_TOKEN}"})
        self.assertEqual(response.status, 200)

    async def test_reader_gets_views_but_no_non_get_privilege_escalation(self) -> None:
        self.validator.validate.return_value = self.reader
        client = await self.client()
        response = await client.get("/api/runs", headers=BEARER)
        self.assertEqual(response.status, 200)
        self.assertIs(self.seen_principals[-1], self.reader)
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"):
            response = await client.request(method, "/api/runs", headers={**BEARER, "X-Actor": OPERATOR, "X-User": OPERATOR})
            self.assertEqual(response.status, 403)
            if method != "HEAD":
                self.assertEqual(await response.json(), {"error": "forbidden"})
        self.assertEqual(len(self.handled), 1)

    async def test_hitl_exception_is_authenticated_exact_post_only(self) -> None:
        self.validator.validate.return_value = self.reader
        client = await self.client()
        path = "/api/hitl/approval-1/respond"
        self.assertEqual((await client.post(path)).status, 401)
        self.assertEqual((await client.post(path, headers=BEARER)).status, 200)
        self.assertIs(self.seen_principals[-1], self.reader)
        for method, other_path in (
            ("PATCH", path), ("DELETE", path), ("POST", path + "/"),
            ("POST", path + "/extra"), ("POST", "/api/hitl/a/b/respond"),
            ("POST", "/api/hitl//respond"), ("POST", "/api/hitl/approval-1/approve"),
        ):
            response = await client.request(method, other_path, headers=BEARER)
            self.assertEqual(response.status, 403)
        self.assertEqual(len(self.handled), 1)

    async def test_validator_errors_and_untyped_or_roleless_principals_fail_closed(self) -> None:
        client = await self.client()
        for error, status in (
            (ControlAuthenticationError(), 401), (ControlAuthorizationError(), 403),
            (ControlAuthConfigurationError("sensitive-config"), 401),
            (RuntimeError("sensitive-token-in-upstream-error"), 401),
        ):
            self.validator.validate.side_effect = error
            response = await client.get("/api/runs", headers=BEARER)
            self.assertEqual(response.status, status)
            self.assertEqual(await response.json(), {"error": "forbidden" if status == 403 else "unauthorized"})
        self.validator.validate.side_effect = None
        for principal, status in (
            ({"roles": ["operator"]}, 401),
            (ControlPrincipal("offline", "offline", "Offline", frozenset()), 403),
            (ControlPrincipal("offline", "offline", "Offline", frozenset({"administrator"})), 403),
        ):
            self.validator.validate.return_value = principal
            self.assertEqual((await client.get("/api/runs", headers=BEARER)).status, status)
        self.assertEqual(self.handled, [])

    async def test_missing_dev_configuration_keeps_health_public_but_never_authenticates(self) -> None:
        with patch.dict(os.environ, {"AUTOPILOT_ALLOW_ANONYMOUS_LOCAL": "true"}, clear=True):
            client = await self.client(use_injected_validator=False)
            self.assertEqual((await client.get("/healthz")).status, 200)
            for headers in ({}, BEARER, {"X-Actor": OPERATOR, "X-Forwarded-For": "127.0.0.1"}):
                response = await client.get("/api/runs", headers=headers)
                self.assertEqual(response.status, 401)
                self.assertEqual(await response.json(), {"error": "unauthorized"})
        self.assertEqual(self.handled, [("GET", "/healthz")])

    async def test_anonymous_flag_never_bypasses_production(self) -> None:
        with patch.dict(os.environ, {"AUTOPILOT_ENVIRONMENT": "production", "AUTOPILOT_ALLOW_ANONYMOUS_LOCAL": "true"}):
            client = await self.client(use_injected_validator=False)
            self.assertEqual((await client.get("/api/runs")).status, 401)
            self.assertEqual((await client.get("/healthz")).status, 200)

    async def test_security_headers_cover_prepared_streams_and_handler_errors(self) -> None:
        client = await self.client()
        response = await client.get("/api/stream", headers=BEARER)
        self.assertEqual(response.status, 200)
        self.assertEqual(await response.text(), "data: offline\n\n")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        response = await client.get("/api/error", headers=BEARER)
        self.assertEqual(response.status, 404)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")


if __name__ == "__main__":
    unittest.main()