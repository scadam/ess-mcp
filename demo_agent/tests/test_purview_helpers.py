"""Smoke test for demo_agent.purview helpers (paging, retry, token cache, parent flatten)."""

from __future__ import annotations

import base64
import json
import threading
import time
from typing import Any

import httpx

from demo_agent.purview import (
    PurviewLabelClient,
    _TokenCache,
    _fetch_paged,
    _get_with_retry,
    _jwt_exp,
)


def _forge_jwt(exp_in_seconds: int = 3600) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    claims = {"exp": int(time.time()) + exp_in_seconds, "aud": "graph"}
    payload = (
        base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    )
    return f"{header}.{payload}.sig"


def test_jwt_exp() -> None:
    tok = _forge_jwt(3600)
    exp = _jwt_exp(tok)
    assert exp is not None and abs(exp - (time.time() + 3600)) < 2, f"exp parse failed: {exp}"
    print(f"[1] _jwt_exp OK (in {int(exp - time.time())}s)")


def test_token_cache_reuse_and_invalidate() -> None:
    tok = _forge_jwt(3600)
    calls = {"n": 0}

    def provider() -> str:
        calls["n"] += 1
        return tok

    tc = _TokenCache(provider)
    assert tc.token() == tok
    assert tc.token() == tok  # cached
    assert calls["n"] == 1, calls["n"]
    tc.invalidate()
    assert tc.token() == tok
    assert calls["n"] == 2, calls["n"]
    print(f"[2] _TokenCache OK (provider called {calls['n']}x for 4 reads)")


def test_token_cache_none_provider() -> None:
    assert _TokenCache(None).token() is None
    print("[3] _TokenCache(None) returns None")


def test_token_cache_provider_raises() -> None:
    def bad() -> str:
        raise RuntimeError("nope")

    assert _TokenCache(bad).token() is None
    print("[4] _TokenCache survives provider exception")


def test_get_with_retry_honours_retry_after() -> None:
    """Use a MockTransport to simulate two 429s then a 200."""
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] < 3:
            return httpx.Response(
                429, headers={"Retry-After": "0"}, json={"error": "throttled"}
            )
        return httpx.Response(200, json={"value": [{"id": "a", "name": "Public"}]})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        resp = _get_with_retry(client, "https://example/x", {})
    assert resp is not None and resp.status_code == 200
    assert state["n"] == 3
    print(f"[5] _get_with_retry honoured 429 Retry-After ({state['n']} attempts)")


def test_get_with_retry_gives_up() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "0"})

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        resp = _get_with_retry(client, "https://example/x", {}, max_attempts=2)
    # After exhausting attempts the last 429 is returned (not None)
    assert resp is not None and resp.status_code == 429
    print("[6] _get_with_retry returns final 429 after max_attempts")


def test_fetch_paged_follows_next_link() -> None:
    pages = [
        {
            "value": [{"id": f"p1-{i}", "name": f"L{i}"} for i in range(3)],
            "@odata.nextLink": "https://example/page/2",
        },
        {
            "value": [{"id": f"p2-{i}", "name": f"M{i}"} for i in range(2)],
            # no nextLink → end
        },
    ]
    state = {"i": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        page = pages[state["i"]]
        state["i"] += 1
        return httpx.Response(200, json=page)

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        entries, err = _fetch_paged(client, "https://example/page/1", {})
    assert entries is not None and len(entries) == 5, entries
    assert state["i"] == 2
    print(f"[7] _fetch_paged combined {len(entries)} entries across {state['i']} pages")


def test_fetch_paged_initial_404_signals_fallback() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    transport = httpx.MockTransport(handler)
    with httpx.Client(transport=transport) as client:
        entries, err = _fetch_paged(client, "https://example/x", {})
    assert entries is None and "404" in err, (entries, err)
    print(f"[8] _fetch_paged initial 404 -> entries=None err={err!r}")


def test_purview_label_client_parent_flatten() -> None:
    """End-to-end: graph returns a Confidential parent + a custom child sub-label;
    the child should inherit the parent's canonical priority of 50."""
    tok = _forge_jwt(3600)
    data = {
        "value": [
            {"id": "p-conf", "name": "Confidential"},
            {
                "id": "c-eng-only",
                "name": "Engineering-Only",
                "parent": {"id": "p-conf", "name": "Confidential"},
            },
            {"id": "p-pub", "name": "Public"},
        ]
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=data)

    transport = httpx.MockTransport(handler)
    client = PurviewLabelClient(graph_token_provider=lambda: tok)
    # Inject our mock transport via monkey-patching httpx.Client
    real_client_cls = httpx.Client

    class _PatchedClient(real_client_cls):  # type: ignore[misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    httpx.Client = _PatchedClient  # type: ignore[assignment]
    try:
        labels = client.reload()
    finally:
        httpx.Client = real_client_cls  # type: ignore[assignment]
    by_name = {l.name: l for l in labels}
    assert "Engineering-Only" in by_name, list(by_name)
    eng = by_name["Engineering-Only"]
    conf = by_name["Confidential"]
    pub = by_name["Public"]
    assert eng.parent_id == "p-conf", eng
    # Child inherits Confidential's canonical priority (50) since its leaf name
    # is custom and not in _WELL_KNOWN_PRIORITY.
    assert eng.priority >= 50, eng
    assert conf.priority == 50, conf
    assert pub.priority == 10, pub
    print(
        f"[9] parent flatten OK: Public={pub.priority}, "
        f"Confidential={conf.priority}, child={eng.priority} (parent_id={eng.parent_id})"
    )


def main() -> None:
    test_jwt_exp()
    test_token_cache_reuse_and_invalidate()
    test_token_cache_none_provider()
    test_token_cache_provider_raises()
    test_get_with_retry_honours_retry_after()
    test_get_with_retry_gives_up()
    test_fetch_paged_follows_next_link()
    test_fetch_paged_initial_404_signals_fallback()
    test_purview_label_client_parent_flatten()
    print("ALL OK")


if __name__ == "__main__":
    main()
