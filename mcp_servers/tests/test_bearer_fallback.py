"""Network-isolated regressions for bearer-first, server-owned OAuth fallback."""
import ast
import asyncio
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from mcp_servers.auth import TokenValidationError
from mcp_servers.auth import salesforce as sf_auth
from mcp_servers.auth import servicenow as sn_auth
from mcp_servers.servicenow import tools as sn_tools
from mcp_servers.settings import SalesforceSettings, ServiceNowSettings, WorkdaySettings
from mcp_servers.workday import helpers as wd_helpers
from mcp_servers.workday import tools as wd_tools


def context(header=None):
    headers = httpx.Headers({"Authorization": header} if header is not None else {})
    return SimpleNamespace(request_context=SimpleNamespace(request=SimpleNamespace(headers=headers)))


def sn_settings(**overrides):
    values = {"SERVICENOW_INSTANCE_URL": "https://demo.service-now.com",
              "SERVICENOW_OAUTH_CLIENT_ID": "test-client",
              "SERVICENOW_OAUTH_CLIENT_SECRET": "test-secret"}
    values.update(overrides)
    return ServiceNowSettings(_env_file=None, **values)


def wd_settings(**overrides):
    values = {"WORKDAY_BASE_URL": "https://demo.workday.com", "WORKDAY_TENANT": "demo",
              "WORKDAY_OAUTH_TOKEN_URL": "https://demo.workday.com/oauth2/token",
              "WORKDAY_OAUTH_CLIENT_ID": "test-client", "WORKDAY_OAUTH_CLIENT_SECRET": "test-secret",
              "WORKDAY_OAUTH_REFRESH_TOKEN": "test-refresh", "WORKDAY_OAUTH_AUTH_METHOD": "client_secret_post",
              "WORKDAY_OAUTH_GRANT_TYPE": "refresh_token"}
    values.update(overrides)
    return WorkdaySettings(_env_file=None, **values)


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    factory = lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    monkeypatch.setattr(httpx, "AsyncClient", factory)
    return factory


@pytest.fixture(autouse=True)
def reset_caches(monkeypatch):
    sn_auth.reset_servicenow_token_cache()
    sf_auth.reset_salesforce_token_cache()
    wd_helpers._TOKEN_CACHE.clear()
    monkeypatch.setattr(sn_auth, "_token_lock", asyncio.Lock())
    monkeypatch.setattr(sf_auth, "_token_lock", asyncio.Lock())
    monkeypatch.setattr(wd_helpers, "_TOKEN_LOCK", asyncio.Lock())
    yield
    sn_auth.reset_servicenow_token_cache()
    sf_auth.reset_salesforce_token_cache()
    wd_helpers._TOKEN_CACHE.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "client_credentials", "oauth_bearer"])
async def test_salesforce_caller_always_wins(monkeypatch, mode):
    settings = SalesforceSettings(SALESFORCE_DOMAIN="demo.my.salesforce.com", SF_AUTH_MODE=mode, _env_file=None)
    monkeypatch.setattr(sf_auth, "load_salesforce_settings", lambda: settings)
    fallback = AsyncMock(side_effect=AssertionError("Caller token must not mint a service token"))
    monkeypatch.setattr(sf_auth, "_get_cached_client_credentials_token", fallback)
    token = await sf_auth.resolve_salesforce_token(context("bEaReR caller-token"))
    assert token.access_token == "caller-token"
    fallback.assert_not_awaited()
    assert sf_auth._token_cache is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["auto", "client_credentials"])
async def test_salesforce_fallback_and_concurrent_cache(monkeypatch, mode):
    settings = SalesforceSettings(SALESFORCE_DOMAIN="demo.my.salesforce.com", SF_AUTH_MODE=mode,
                                  SF_CLIENT_ID="test-client", SF_CLIENT_SECRET="test-secret", _env_file=None)
    monkeypatch.setattr(sf_auth, "load_salesforce_settings", lambda: settings)
    calls = []
    def handler(request):
        calls.append(request)
        body = parse_qs(request.content.decode())
        assert body["grant_type"] == ["client_credentials"]
        assert body["client_id"] == ["test-client"]
        assert body["client_secret"] == ["test-secret"]
        return httpx.Response(200, json={"access_token": "service-token", "instance_url": "https://demo.my.salesforce.com"})
    mock_http(monkeypatch, handler)
    tokens = await asyncio.gather(*(sf_auth.resolve_salesforce_token(context()) for _ in range(8)))
    assert {token.access_token for token in tokens} == {"service-token"}
    assert len(calls) == 1
    assert (await sf_auth.resolve_salesforce_token(context("Bearer caller-token"))).access_token == "caller-token"
    assert (await sf_auth.resolve_salesforce_token(context())).access_token == "service-token"
    assert sf_auth._token_cache is not None
    sf_auth._token_cache.issued_at = 0
    await sf_auth.resolve_salesforce_token(context())
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_salesforce_bearer_only_and_missing_credentials_fail_closed(monkeypatch):
    settings = SalesforceSettings(SALESFORCE_DOMAIN="demo.my.salesforce.com", SF_AUTH_MODE="oauth_bearer", _env_file=None)
    monkeypatch.setattr(sf_auth, "load_salesforce_settings", lambda: settings)
    with pytest.raises(TokenValidationError, match="header is required"):
        await sf_auth.resolve_salesforce_token(context())
    settings.auth_mode = "auto"
    settings.client_id = settings.client_secret = ""
    with pytest.raises(TokenValidationError, match="not configured"):
        await sf_auth.resolve_salesforce_token(context())


@pytest.mark.asyncio
async def test_servicenow_bearer_never_loads_fallback(monkeypatch):
    monkeypatch.setattr(sn_auth, "load_servicenow_settings", lambda: pytest.fail("Fallback config accessed for caller token"))
    assert await sn_auth.resolve_servicenow_token(context("bEaReR caller-token")) == "caller-token"
    assert sn_auth._token_cache is None


@pytest.mark.asyncio
@pytest.mark.parametrize("header", [None, "Basic not-a-bearer", "Bearer "])
async def test_servicenow_no_bearer_selects_fallback(monkeypatch, header):
    settings = sn_settings()
    monkeypatch.setattr(sn_auth, "load_servicenow_settings", lambda: settings)
    mint = AsyncMock(return_value=sn_auth._CachedToken("service-token", time.monotonic()+300, sn_auth._configuration_key(settings)))
    monkeypatch.setattr(sn_auth, "_mint_token", mint)
    assert await sn_auth.resolve_servicenow_token(context(header)) == "service-token"
    mint.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("grant", ["client_credentials", "password"])
@pytest.mark.parametrize("method", ["client_secret_post", "client_secret_basic"])
async def test_servicenow_grants_and_client_auth(monkeypatch, grant, method):
    settings = sn_settings(SERVICENOW_OAUTH_GRANT_TYPE=grant, SERVICENOW_OAUTH_AUTH_METHOD=method,
                           SERVICENOW_OAUTH_USERNAME="demo-user", SERVICENOW_OAUTH_PASSWORD="demo-password")
    monkeypatch.setattr(sn_auth, "load_servicenow_settings", lambda: settings)
    def handler(request):
        assert str(request.url) == "https://demo.service-now.com/oauth_token.do"
        body = parse_qs(request.content.decode())
        assert body["grant_type"] == [grant]
        if method == "client_secret_post":
            assert body["client_id"] == ["test-client"] and body["client_secret"] == ["test-secret"]
        else:
            assert request.headers["authorization"].startswith("Basic ")
            assert "client_secret" not in body
        if grant == "password":
            assert body["username"] == ["demo-user"] and body["password"] == ["demo-password"]
        else:
            assert "username" not in body and "password" not in body
        return httpx.Response(200, json={"access_token":"service-token", "expires_in":300, "token_type":"Bearer"})
    mock_http(monkeypatch, handler)
    assert await sn_auth.resolve_servicenow_token(context()) == "service-token"
    assert "service-token" not in repr(sn_auth._token_cache)


@pytest.mark.asyncio
async def test_servicenow_cache_expiry_rotation_and_caller_isolation(monkeypatch):
    settings = sn_settings()
    monkeypatch.setattr(sn_auth, "load_servicenow_settings", lambda: settings)
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json={"access_token":f"service-{len(requests)}","expires_in":300})
    mock_http(monkeypatch,handler)
    assert set(await asyncio.gather(*(sn_auth.resolve_servicenow_token(context()) for _ in range(12)))) == {"service-1"}
    assert len(requests)==1
    assert await sn_auth.resolve_servicenow_token(context("Bearer other-user")) == "other-user"
    assert await sn_auth.resolve_servicenow_token(context()) == "service-1"
    sn_auth._token_cache.refresh_at=0
    assert await sn_auth.resolve_servicenow_token(context()) == "service-2"
    settings.oauth_client_secret="rotated-secret"
    assert await sn_auth.resolve_servicenow_token(context()) == "service-3"


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"access_token":""}, {"access_token":123},
                                     {"access_token":"token","expires_in":0},
                                     {"access_token":"token","expires_in":"NaN"},
                                     {"access_token":"token","token_type":"Basic"}])
async def test_servicenow_malformed_token_not_cached(monkeypatch,payload):
    monkeypatch.setattr(sn_auth,"load_servicenow_settings",lambda:sn_settings())
    mock_http(monkeypatch,lambda request:httpx.Response(200,json=payload))
    with pytest.raises(RuntimeError):
        await sn_auth.resolve_servicenow_token(context())
    assert sn_auth._token_cache is None


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [
    {"SERVICENOW_OAUTH_CLIENT_SECRET":""},
    {"SERVICENOW_OAUTH_TOKEN_URL":"http://demo.service-now.com/oauth_token.do"},
    {"SERVICENOW_OAUTH_GRANT_TYPE":"unsupported"},
    {"SERVICENOW_OAUTH_GRANT_TYPE":"password","SERVICENOW_OAUTH_PASSWORD":""},
    {"SERVICENOW_OAUTH_AUTH_METHOD":"none"},
])
async def test_servicenow_invalid_fallback_config_never_calls_network(monkeypatch,overrides):
    settings=sn_settings(**overrides)
    monkeypatch.setattr(sn_auth,"load_servicenow_settings",lambda:settings)
    mock_http(monkeypatch,lambda request:pytest.fail("Invalid config made a network request"))
    with pytest.raises((RuntimeError,TokenValidationError)):
        await sn_auth.resolve_servicenow_token(context())


@pytest.mark.asyncio
async def test_servicenow_token_error_propagates_without_secret_logging(monkeypatch,capsys):
    monkeypatch.setattr(sn_auth,"load_servicenow_settings",lambda:sn_settings())
    mock_http(monkeypatch,lambda request:httpx.Response(401,json={"secret":"test-secret"}))
    with pytest.raises(httpx.HTTPStatusError) as error:
        await sn_auth.resolve_servicenow_token(context())
    assert error.value.response.status_code==401
    assert "test-secret" not in str(error.value)
    assert "test-secret" not in capsys.readouterr().out
    assert sn_auth._token_cache is None


@pytest.mark.asyncio
@pytest.mark.parametrize("header,expected", [(None,"service-token"),("Bearer caller-token","caller-token")])
async def test_servicenow_tool_forwards_selected_token(monkeypatch,header,expected):
    settings=sn_settings()
    monkeypatch.setattr(sn_auth,"load_servicenow_settings",lambda:settings)
    monkeypatch.setattr(sn_tools,"load_servicenow_settings",lambda:settings)
    mint=AsyncMock(return_value=sn_auth._CachedToken("service-token",time.monotonic()+300,sn_auth._configuration_key(settings)))
    monkeypatch.setattr(sn_auth,"_mint_token",mint)
    def handler(request):
        assert request.headers['authorization']==f'Bearer {expected}'
        return httpx.Response(200,json={"result":[]})
    factory=mock_http(monkeypatch,handler)
    monkeypatch.setattr(sn_tools,"create_async_client",factory)
    result=await sn_tools.tool_list_incidents(limit=1,ctx=context(header))
    assert result['total_returned']==0
    assert mint.await_count == (0 if header else 1)


@pytest.mark.asyncio
async def test_servicenow_rejected_caller_never_retries_as_service(monkeypatch):
    monkeypatch.setattr(sn_tools,"load_servicenow_settings",lambda:sn_settings())
    mint=AsyncMock(side_effect=AssertionError("Must not switch identities"))
    monkeypatch.setattr(sn_auth,"_mint_token",mint)
    requests=[]
    def handler(request):
        requests.append(request)
        assert request.headers['authorization']=='Bearer rejected-caller'
        return httpx.Response(401,json={"error":"unauthorized"})
    factory=mock_http(monkeypatch,handler)
    monkeypatch.setattr(sn_tools,"create_async_client",factory)
    with pytest.raises(httpx.HTTPStatusError):
        await sn_tools.tool_list_incidents(ctx=context('Bearer rejected-caller'))
    assert len(requests)==1
    mint.assert_not_awaited()


def test_all_servicenow_auth_callsites_use_awaited_resolver():
    source=Path(sn_tools.__file__).read_text(encoding='utf-8')
    tree=ast.parse(source)
    calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name)]
    assert not any(node.func.id=='get_bearer_token' for node in calls)
    resolver_calls=[node for node in calls if node.func.id=='resolve_servicenow_token']
    assert len(resolver_calls)==43
    awaited={id(node.value) for node in ast.walk(tree) if isinstance(node,ast.Await)}
    assert all(id(node) in awaited for node in resolver_calls)


@pytest.mark.asyncio
async def test_workday_bearer_first_and_no_header_fallback(monkeypatch):
    fallback=AsyncMock(return_value='service-token')
    monkeypatch.setattr(wd_tools,'get_workday_fallback_access_token',fallback)
    assert await wd_tools._get_access_token(context('Bearer caller-token'))=='caller-token'
    fallback.assert_not_awaited()
    assert await wd_tools._get_access_token(context())=='service-token'
    fallback.assert_awaited_once()


@pytest.mark.asyncio
async def test_workday_worker_context_preserves_caller_and_does_not_retry(monkeypatch):
    fallback=AsyncMock(return_value='service-worker')
    bearer=AsyncMock(return_value='caller-worker')
    monkeypatch.setattr(wd_tools,'build_worker_context_from_fallback',fallback)
    monkeypatch.setattr(wd_tools,'build_worker_context_from_bearer',bearer)
    assert await wd_tools._get_worker_context(context('Bearer caller-token'))=='caller-worker'
    bearer.assert_awaited_once_with('caller-token')
    fallback.assert_not_awaited()
    assert await wd_tools._get_worker_context(context())=='service-worker'
    fallback.reset_mock()
    bearer.side_effect=TokenValidationError('Backend rejected caller')
    with pytest.raises(TokenValidationError,match='Backend rejected'):
        await wd_tools._get_worker_context(context('Bearer rejected-caller'))
    fallback.assert_not_awaited()


@pytest.mark.asyncio
async def test_workday_refresh_fallback_is_cached_and_serialized(monkeypatch):
    monkeypatch.setattr(wd_helpers,'load_workday_settings',lambda:wd_settings())
    requests=[]
    def handler(request):
        requests.append(request)
        body=parse_qs(request.content.decode())
        assert body['grant_type']==['refresh_token'] and body['refresh_token']==['test-refresh']
        assert body['client_id']==['test-client'] and body['client_secret']==['test-secret']
        return httpx.Response(200,json={'access_token':'service-token','expires_in':1800})
    factory=mock_http(monkeypatch,handler)
    monkeypatch.setattr(wd_helpers,'create_async_client',factory)
    assert set(await asyncio.gather(*(wd_helpers.get_workday_fallback_access_token() for _ in range(10))))=={'service-token'}
    assert len(requests)==1
    wd_helpers._TOKEN_CACHE['workday'].expires_at=0
    assert await wd_helpers.get_workday_fallback_access_token()=='service-token'
    assert len(requests)==2