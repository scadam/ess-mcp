"""One-use loopback receiver for the existing Jira app's browser OAuth callback.

The authorized browser forwards its registered Teams callback in memory. The
registered callback is never changed. Tokens are stored only in the new vault.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import secrets
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

from deployment_support import SESSION, Vault, audit

PORT = 8462
CALLBACK = "https://teams.microsoft.com/api/platform/v1.0/oAuthRedirect"
CLOUD_ID = "86d2487a-0a7c-477e-b827-f0b1b2c5a950"
SITE_URL = "https://microsoft-team-s108q2w6.atlassian.net"
API_BASE = f"https://api.atlassian.com/ex/jira/{CLOUD_ID}"
TOKEN_SECRET = "jira-user-oauth"
SCOPES = "read:jira-work read:jira-user offline_access"
CONSOLE = "https://developer.atlassian.com/console/myapps/9a2a3755-c789-45e0-836b-dc27b91edb45/authorization/auth-code-grant"
_refresh_lock = threading.Lock()


def user_token(vault: Vault, *, force_refresh: bool = False) -> str:
    """Read/refresh the consented user's token. Run one helper process at a time.

    The vault stores a single atomic access/refresh pair; neither value is logged.
    This is a local validation client, not a public-server authentication fallback.
    """
    with _refresh_lock:
        cached = json.loads(vault.get(TOKEN_SECRET))
        if cached.get("cloud_id") != CLOUD_ID:
            raise RuntimeError("Unexpected Jira site in saved OAuth grant")
        expires_at = float(cached.get("expires_at", 0))
        if not force_refresh and math.isfinite(expires_at) and expires_at > time.time() + 120 and cached.get("access_token"):
            return cached["access_token"]
        if not cached.get("refresh_token"):
            raise RuntimeError("Jira user consent must be renewed")
        with httpx.Client(timeout=45) as http:
            response = http.post("https://auth.atlassian.com/oauth/token", json={
                "grant_type": "refresh_token", "client_id": vault.get("jira-client-id"),
                "client_secret": vault.get("jira-client-secret"), "refresh_token": cached["refresh_token"],
            })
        if response.status_code != 200:
            raise RuntimeError(f"Jira token refresh failed: HTTP {response.status_code}")
        refreshed = response.json()
        if not refreshed.get("access_token") or not refreshed.get("refresh_token"):
            raise RuntimeError("Jira refresh response omitted a required token")
        cached.update(access_token=refreshed["access_token"], refresh_token=refreshed["refresh_token"],
                      expires_at=time.time() + int(refreshed.get("expires_in", 3600)),
                      scopes=refreshed.get("scope", cached.get("scopes", "")))
        vault.put(TOKEN_SECRET, json.dumps(cached))
        audit("jira-user-token-refresh", "succeeded")
        return cached["access_token"]


class ConsentSession:
    def __init__(self, vault: Vault):
        self.vault = vault
        self.state = secrets.token_urlsafe(32)
        self.started = time.monotonic()
        self.claimed = False
        self.lock = threading.Lock()
        self.status = "awaiting_consent"
        self.client_id = vault.get("jira-client-id")
        self.client_secret = vault.get("jira-client-secret")

    def claim(self, state: str, code: str) -> bool:
        with self.lock:
            if (self.claimed or time.monotonic() - self.started > 600 or not code
                    or not hmac.compare_digest(self.state, state)):
                return False
            self.claimed = True
            self.status = "exchanging_code"
            return True

    def authorize_url(self) -> str:
        return "https://auth.atlassian.com/authorize?" + urlencode({
            "audience": "api.atlassian.com", "client_id": self.client_id,
            "scope": SCOPES, "redirect_uri": CALLBACK, "state": self.state,
            "response_type": "code", "prompt": "consent",
        })

    def exchange(self, code: str) -> dict:
        with httpx.Client(timeout=45) as http:
            response = http.post("https://auth.atlassian.com/oauth/token", json={
                "grant_type": "authorization_code", "client_id": self.client_id,
                "client_secret": self.client_secret, "code": code, "redirect_uri": CALLBACK,
            })
            if response.status_code != 200:
                raise RuntimeError(f"Token exchange failed: HTTP {response.status_code}")
            tokens = response.json()
            if not tokens.get("access_token") or not tokens.get("refresh_token"):
                raise RuntimeError("Authorization did not return both required tokens")
            headers = {"Authorization": "Bearer " + tokens["access_token"], "Accept": "application/json"}
            resources = http.get("https://api.atlassian.com/oauth/token/accessible-resources", headers=headers)
            if resources.status_code != 200:
                raise RuntimeError(f"Site-grant lookup failed: HTTP {resources.status_code}")
            matches = [site for site in resources.json()
                       if site.get("id") == CLOUD_ID and site.get("url", "").rstrip("/") == SITE_URL]
            if not matches or not any("read:jira-work" in site.get("scopes", []) for site in matches):
                raise RuntimeError("Consent does not include the expected Jira site and read scope")
            # Store one atomic token pair, preventing refresh-token/access-token version drift.
            cached = {"access_token": tokens["access_token"], "refresh_token": tokens["refresh_token"],
                      "expires_at": time.time() + int(tokens.get("expires_in", 3600)),
                      "cloud_id": CLOUD_ID, "scopes": tokens.get("scope", "")}
            self.vault.put(TOKEN_SECRET, json.dumps(cached))
            identity = http.get(API_BASE + "/rest/api/3/myself", headers=headers)
            search = http.post(API_BASE + "/rest/api/3/search/jql", headers=headers, json={
                "jql": "assignee = currentUser() ORDER BY updated DESC", "maxResults": 1, "fields": ["summary"],
            })
            result = {"checkedUtc": datetime.now(timezone.utc).isoformat(), "grant": "authorization_code",
                      "siteGrantVerified": True, "cloudId": CLOUD_ID, "apiBaseUrl": API_BASE,
                      "requestedScopes": SCOPES, "tokenSecretName": TOKEN_SECRET,
                      "readOnlyIdentityHttp": identity.status_code, "readOnlySearchHttp": search.status_code,
                      "registeredCallbackUnchanged": True, "tokensPrinted": False}
            (SESSION / "jira-consent.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
            self.status = "authorized" if identity.status_code == 200 and search.status_code == 200 else "authorized_api_check_failed"
            audit("jira-browser-consent", self.status)
            return result


def handler_for(consent: ConsentSession):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            # Callback request targets and payloads must never enter logs.
            pass

        def reply(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def allowed_host(self) -> bool:
            return self.headers.get("Host") == f"127.0.0.1:{PORT}"

        def do_GET(self):
            if not self.allowed_host():
                self.reply(400, {"error": "unexpected_host"})
            elif urlsplit(self.path).path == "/callback":
                query = parse_qs(urlsplit(self.path).query)
                states, codes = query.get("state", []), query.get("code", [])
                if len(states) != 1 or len(codes) != 1 or not consent.claim(states[0], codes[0]):
                    self.reply(403, {"error": "invalid_expired_or_replayed_state"})
                    return
                try:
                    result = consent.exchange(codes[0])
                    print(json.dumps(result), flush=True)
                    # Remove the one-use callback query from the final browser location.
                    self.send_response(303)
                    self.send_header("Location", CONSOLE)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.end_headers()
                except Exception as exc:
                    consent.status = "failed"
                    audit("jira-browser-consent", "failed")
                    self.reply(502, {"status": "failed", "errorType": type(exc).__name__})
                    print(json.dumps({"status": "failed", "errorType": type(exc).__name__}), flush=True)
                finally:
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
            elif self.path == "/start" and not consent.claimed:
                self.send_response(302)
                self.send_header("Location", consent.authorize_url())
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
            elif self.path == "/status":
                self.reply(200, {"status": consent.status})
            else:
                self.reply(404, {"error": "not_found"})

        def do_POST(self):
            if not self.allowed_host() or self.path != "/callback" or self.headers.get("Origin"):
                self.reply(400, {"error": "unexpected_request"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 8192:
                    raise ValueError("Invalid body length")
                body = json.loads(self.rfile.read(length))
                state, code = body.get("state", ""), body.get("code", "")
                if not isinstance(state, str) or not isinstance(code, str) or not consent.claim(state, code):
                    self.reply(403, {"error": "invalid_expired_or_replayed_state"})
                    return
            except (ValueError, TypeError, AttributeError):
                self.reply(400, {"error": "invalid_request"})
                return
            try:
                result = consent.exchange(code)
                self.reply(200, {"status": consent.status, "siteGrantVerified": result["siteGrantVerified"]})
                print(json.dumps(result), flush=True)
            except Exception as exc:
                consent.status = "failed"
                audit("jira-browser-consent", "failed")
                self.reply(502, {"status": "failed", "errorType": type(exc).__name__})
                print(json.dumps({"status": "failed", "errorType": type(exc).__name__}), flush=True)
            finally:
                threading.Thread(target=self.server.shutdown, daemon=True).start()
    return Handler


def main():
    vault = Vault()
    try:
        consent = ConsentSession(vault)
        with ThreadingHTTPServer(("127.0.0.1", PORT), handler_for(consent)) as server:
            deadline = threading.Timer(600, server.shutdown)
            deadline.daemon = True
            deadline.start()
            audit("jira-browser-consent", "awaiting_browser")
            print(json.dumps({"ready": True, "startUrl": f"http://127.0.0.1:{PORT}/start"}), flush=True)
            try:
                server.serve_forever()
            finally:
                deadline.cancel()
    finally:
        vault.close()


if __name__ == "__main__":
    main()