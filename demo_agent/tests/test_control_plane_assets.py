"""Offline, standard-library-only static contracts for the existing frontends.

These tests read source assets; they do not import the host, execute JavaScript,
start a browser, contact a CDN/Entra, or prove that runtime authentication works.
"""

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "static"
BRAND = "Group Functions Autopilot"
PAGES = ("control-plane.html", "index.html")
TEAMS_URL = "https://res.cdn.office.net/teams-js/2.34.0/js/MicrosoftTeams.min.js"
MSAL_URL = "https://cdn.jsdelivr.net/npm/@azure/msal-browser@2.38.3/lib/msal-browser.min.js"


class PageMarkup(HTMLParser):
    """Collect actual markup, not HTML templates embedded in JavaScript."""

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str | None]]] = []
        self.visible_text: list[str] = []
        self._raw_tag: str | None = None
        self.feed(source)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        self.tags.append((tag, attributes))
        if tag in {"script", "style"}:
            self._raw_tag = tag
        if self._raw_tag is None:
            for attribute in ("title", "aria-label", "placeholder", "alt"):
                value = attributes.get(attribute)
                if value:
                    self.visible_text.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == self._raw_tag:
            self._raw_tag = None

    def handle_data(self, data: str) -> None:
        if self._raw_tag is None:
            self.visible_text.append(data)


def function_source(source: str, name: str) -> str:
    """Extract one consistently indented declaration for source-contract checks.

    This deliberately is not a JavaScript parser or an execution substitute.
    """
    start = re.search(
        rf"(?m)^(?P<indent>[ \t]*)(?:async )?function {re.escape(name)}\([^\n]*\) \{{\s*$",
        source,
    )
    if start is None:
        raise AssertionError(f"Missing function: {name}")
    end = source.find("\n" + start.group("indent") + "}", start.end())
    if end < 0:
        raise AssertionError(f"Missing closing brace: {name}")
    return source[start.start():end + len(start.group("indent")) + 2]


class ControlPlaneAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.pages = {name: (STATIC / name).read_text(encoding="utf-8") for name in PAGES}
        cls.auth = (STATIC / "control-auth.js").read_text(encoding="utf-8")
        cls.theme = (STATIC / "autopilot-theme.css").read_text(encoding="utf-8")

    def test_visible_branding_and_control_plane_tab(self) -> None:
        for name, source in self.pages.items():
            with self.subTest(page=name):
                visible = " ".join(PageMarkup(source).visible_text)
                self.assertIn(BRAND, visible)
                self.assertNotRegex(visible, r"(?i)\b(?:ESS|ProjectESS|ESSHostedAgent)\b")
                self.assertNotIn("ESS Hosted Agent", visible)
                self.assertNotIn("Project ESS", visible)
                self.assertRegex(source, rf"<title>{BRAND}(?: — Control Plane)?</title>")
                self.assertRegex(source, r'<a\b[^>]*href="/control-plane"[^>]*>Control Plane</a>')

    def test_theme_detection_is_first_script_and_shared_css_is_late(self) -> None:
        for name, source in self.pages.items():
            with self.subTest(page=name):
                scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", source, re.S)
                self.assertIn('get("clawpilotTheme")', scripts[0][1])
                self.assertIn('matchMedia("(prefers-color-scheme: dark)")', scripts[0][1])
                self.assertIn('setAttribute("data-theme", theme)', scripts[0][1])
                self.assertLess(source.rindex("</style>"), source.index('href="/static/autopilot-theme.css"'))

    def test_pinned_teams_and_shared_auth_load_before_application(self) -> None:
        for name, source in self.pages.items():
            with self.subTest(page=name):
                self.assertIn(f'src="{TEAMS_URL}"', source)
                self.assertIn('src="/static/control-auth.js"', source)
                self.assertLess(source.index(TEAMS_URL), source.index('src="/static/control-auth.js"'))
                self.assertLess(source.index('src="/static/control-auth.js"'), source.index("async function init()"))
                self.assertNotRegex(source, r"(?i)(?:access_token|id_token|bearer)\s*[:=]")
        self.assertIn(MSAL_URL, self.auth)
        self.assertNotIn("@latest", self.auth)

    def test_protected_shell_is_hidden_and_sign_in_is_explicit(self) -> None:
        for name, source in self.pages.items():
            with self.subTest(page=name):
                tags = PageMarkup(source).tags
                protected = [attrs for _, attrs in tags if "data-auth-protected" in attrs]
                self.assertGreaterEqual(len(protected), 3)
                for attrs in protected:
                    self.assertIn("hidden", attrs)
                    self.assertIn("inert", attrs)
                sign_in = [attrs for tag, attrs in tags if tag == "button" and attrs.get("id") == "autopilotSignIn"]
                self.assertEqual(len(sign_in), 1)
                self.assertIn("disabled", sign_in[0])
                self.assertIn('id="autopilotAuthMessage"', source)
                self.assertIn('aria-live="polite"', source)
                self.assertIn('id="autopilotContext"', source)
                self.assertIn('[data-auth-protected][hidden] { display: none !important; }', source)

    def test_init_requires_auth_before_normal_fetches_or_polling(self) -> None:
        for name, source in self.pages.items():
            with self.subTest(page=name):
                init = function_source(source, "init")
                gate = "if (!(await window.autopilotAuth.ready())) return;"
                self.assertIn(gate, init)
                self.assertLess(init.index(gate), init.index("fetchJson("))
                self.assertIn("if (!window.autopilotAuth)", init)
                self.assertIn("window.autopilotAuth.showApp()", init)
                self.assertNotRegex(init, r"\.catch\(\(\)\s*=>\s*(?:\[\]|null)\)")
                self.assertIn("not an empty dashboard", init)
                self.assertNotRegex(source, r"DOMContentLoaded[^\n]*loadA365Value")
                self.assertNotIn("new EventSource", source)
        control = self.pages["control-plane.html"]
        self.assertIn("loadA365Value()", function_source(control, "init"))
        self.assertIn("isAuthenticated()", function_source(control, "startPolling"))

    def test_no_run_or_evidence_browser_storage_persistence(self) -> None:
        for source in [*self.pages.values(), self.auth]:
            self.assertNotRegex(source, r"(?:localStorage|sessionStorage)\s*\.\s*(?:getItem|setItem)\s*\(")
            self.assertNotIn("indexedDB", source)
            self.assertNotIn("localStorage.clear", source)
        control = self.pages["control-plane.html"]
        load = function_source(control, "loadRuns")
        self.assertIn("runs = [];", load)
        self.assertIn("localStorage.removeItem(key)", load)
        self.assertIn("[RUN_STORAGE_KEY, ...LEGACY_RUN_STORAGE_KEYS]", load)
        save = function_source(control, "saveRuns")
        self.assertNotIn("Storage", save)
        self.assertNotIn("JSON.stringify", save)
        self.assertIn("expireStaleRunsNoSave();", save)
        cleanup = function_source(self.auth, "clearLegacyRunStorage")
        self.assertIn("localStorage.key(i)", cleanup)
        self.assertIn("localStorage.removeItem(key)", cleanup)

    def test_teams_handshake_and_notification_precede_auth(self) -> None:
        teams = function_source(self.auth, "initializeTeams")
        self.assertLess(teams.index("app.initialize()"), teams.index("app.notifySuccess()"))
        self.assertLess(teams.index("app.notifySuccess()"), teams.index("app.getContext()"))
        self.assertIn("host === 'Teams' || host === 'TeamsModern'", teams)
        bootstrap = function_source(self.auth, "bootstrap")
        self.assertLess(bootstrap.index("await teamsReady"), bootstrap.index("loadConfig()"))
        acquisition = function_source(self.auth, "acquireAccessToken")
        self.assertIn("if (inTeams)", acquisition)
        self.assertIn("getAuthToken({ silent: true })", acquisition)
        self.assertIn("pca.acquireTokenSilent", acquisition)
        self.assertNotIn("loginPopup", acquisition)

    def test_msal_uses_tenant_scope_and_session_only_cache(self) -> None:
        browser = function_source(self.auth, "initializeBrowser")
        self.assertIn("new window.msal.PublicClientApplication", browser)
        self.assertIn("https://login.microsoftonline.com/${config.tenantId}", browser)
        self.assertIn("redirectUri: window.location.origin + '/control-plane'", browser)
        self.assertIn("cacheLocation: 'sessionStorage'", browser)
        self.assertIn("temporaryCacheLocation: 'sessionStorage'", browser)
        self.assertIn("storeAuthStateInCookie: false", browser)
        self.assertIn("piiLoggingEnabled: false", browser)
        self.assertIn("await pca.initialize();", browser)
        self.assertNotIn("/common", browser)
        self.assertIn("access_agent_as_user", function_source(self.auth, "loadConfig"))

    def test_popup_is_only_in_trusted_sign_in_button_handler(self) -> None:
        sign_in = function_source(self.auth, "signIn")
        self.assertEqual(self.auth.count("pca.loginPopup("), 1)
        self.assertIn("!event?.isTrusted", sign_in)
        self.assertLess(sign_in.index("pca.loginPopup("), sign_in.index("await interaction"))
        self.assertIn("getAuthToken({ silent: false })", sign_in)
        self.assertIn("addEventListener('click', signIn)", self.auth)
        self.assertIn("window.location.reload()", sign_in)
        self.assertNotIn("acquireTokenPopup(", self.auth)
        self.assertNotIn("loginRedirect(", self.auth)

    def test_popup_return_does_not_bootstrap_or_consume_auth_response(self) -> None:
        self.assertIn("window.name.startsWith('msal.')", self.auth)
        bootstrap = function_source(self.auth, "bootstrap")
        self.assertLess(bootstrap.index("if (authReturn)"), bootstrap.index("await teamsReady"))
        self.assertNotIn("handleRedirectPromise", self.auth)
        self.assertNotRegex(self.auth, r"location\.hash\s*=")

    def test_server_not_decoded_claims_decides_access(self) -> None:
        verify = function_source(self.auth, "verifyAccess")
        self.assertIn("nativeFetch('/api/identity'", verify)
        self.assertIn("response.status === 401", verify)
        self.assertIn("response.status === 403", verify)
        self.assertLess(verify.index("response.status === 403"), verify.index("authenticated = true"))
        self.assertNotIn("atob(", self.auth)
        self.assertNotIn("idTokenClaims", self.auth)
        self.assertNotIn("result.idToken", self.auth)
        self.assertNotRegex(self.auth, r"console\.(?:log|error|warn|debug)")
        self.assertNotIn("innerHTML", self.auth)

    def test_fetch_wrapper_confines_bearer_and_preserves_requests(self) -> None:
        wrapper = function_source(self.auth, "controlFetch")
        self.assertIn("window.fetch = controlFetch;", self.auth)
        self.assertIn("new Request(input, options)", wrapper)
        self.assertIn("new Headers(request.headers)", wrapper)
        self.assertIn("headers.delete('Authorization')", wrapper)
        self.assertIn("url.origin === window.location.origin", wrapper)
        self.assertIn("path.startsWith('/api/')", wrapper)
        self.assertIn("path !== '/api/messages'", wrapper)
        self.assertIn("!path.startsWith('/api/messages/')", wrapper)
        self.assertLess(wrapper.index("if (!isControlApi)"), wrapper.index("await ready()"))
        self.assertLess(wrapper.index("await acquireAccessToken()"), wrapper.index("headers.set('Authorization'"))
        self.assertIn("credentials: 'omit'", wrapper)
        self.assertIn("cache: 'no-store'", wrapper)
        self.assertIn("redirect: 'error'", wrapper)
        self.assertIn("mode: 'same-origin'", wrapper)
        self.assertIn("response.status === 401 || response.status === 403", wrapper)
        self.assertIn("return response;", wrapper)
        self.assertNotIn("response.json()", wrapper)
        self.assertNotIn("response.text()", wrapper)

    def test_sse_and_evidence_use_normal_authenticated_fetch(self) -> None:
        for name, method in [("control-plane.html", "runScenario"), ("index.html", "runAgent")]:
            with self.subTest(page=name):
                run = function_source(self.pages[name], method)
                self.assertIn("fetch('/api/run'", run)
                self.assertIn("isAuthenticated()", run)
                self.assertLess(run.index("!response.ok"), run.index("response.body.getReader()"))
                self.assertIn("text/event-stream", run)
                self.assertLess(run.index("let eventType = null;"), run.index("while (true)"))
        evidence = function_source(self.pages["control-plane.html"], "downloadEvidence")
        self.assertIn("await fetch(`/api/runs/", evidence)
        self.assertIn("URL.createObjectURL(blob)", evidence)
        self.assertIn("URL.revokeObjectURL", evidence)
        self.assertNotIn("window.location", evidence)

    def test_auth_loss_clears_runs_ui_and_polling(self) -> None:
        block = function_source(self.auth, "blockAccess")
        self.assertIn("authenticated = false", block)
        self.assertIn("sessionController.abort()", block)
        self.assertIn("autopilot-auth-lost", block)
        control = self.pages["control-plane.html"]
        self.assertIn("for (const timer of pollingTimers) clearInterval(timer);", control)
        for source in self.pages.values():
            self.assertIn("addEventListener('autopilot-auth-lost'", source)
            self.assertIn("replaceChildren()", source)

    def test_account_change_does_not_merge_previous_user_data(self) -> None:
        acquisition = function_source(self.auth, "acquireAccessToken")
        self.assertIn("currentContext?.user?.id !== teamsContext?.user?.id", acquisition)
        self.assertIn("active?.homeAccountId !== account.homeAccountId", acquisition)
        self.assertIn("throw authError('accountChanged')", acquisition)
        sign_in = function_source(self.auth, "signIn")
        self.assertLess(sign_in.index("blockAccess('checking')"), sign_in.index("pca.loginPopup("))

    def test_untrusted_content_is_text_or_escaped_not_raw_html(self) -> None:
        control = self.pages["control-plane.html"]
        index = self.pages["index.html"]
        self.assertIn("getElementById('runResultContent').textContent = run.result", control)
        self.assertIn("getElementById('resultContent').textContent = data.content", index)
        for source in self.pages.values():
            self.assertIn("getElementById('detailOutput').textContent", source)
            self.assertNotRegex(source, r"\.innerHTML\s*=\s*(?:data\.(?:content|result|message)|run\.result)")
            self.assertNotIn("marked.parse", source)
        self.assertIn("${escapeHtml(eventPreview(record))}", control)
        self.assertIn("${escapeHtml(srv.url || '')}", control)
        self.assertIn("return escapeHtml(JSON.stringify(String(value ?? '')));", control)
        self.assertIn("${safeHref(p.url)}", control)
        self.assertIn("${escapeHtml(server)}/", index)
        self.assertIn("${escapeHtml(tool)}", index)

    def test_palette_fonts_aliases_and_no_component_color_literals(self) -> None:
        required = (
            "bg", "bg-elevated", "surface", "surface-soft", "border", "border-strong",
            "text", "text-muted", "text-soft", "accent", "accent-hover", "accent-soft",
            "accent-fg", "success", "danger", "warning", "link", "shadow", "overlay",
            "panel", "panel-strong", "sheen", "highlight",
        )
        light = self.theme.split('html[data-theme="dark"]', 1)[0]
        dark = self.theme.split('html[data-theme="dark"]', 1)[1].split("}", 1)[0]
        for token in required:
            with self.subTest(token=token):
                self.assertIn(f"--cp-{token}:", light)
                self.assertIn(f"--cp-{token}:", dark)
        self.assertIn('"Segoe UI", Aptos, Calibri, -apple-system, BlinkMacSystemFont, sans-serif', self.theme)
        self.assertIn('Consolas, "Courier New", Courier, monospace', self.theme)
        for alias in ("bg", "surface", "border", "text", "accent", "purple", "pill-bg"):
            self.assertRegex(self.theme, rf"--{alias}: var\(--cp-[a-z-]+\)")
        for source in self.pages.values():
            styles = "\n".join(re.findall(r"<style>(.*?)</style>", source, re.S))
            self.assertNotRegex(styles, r"#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(")
            self.assertNotIn("linear-gradient", styles)

    def test_existing_feature_sections_are_preserved(self) -> None:
        markup = PageMarkup(self.pages["control-plane.html"])
        ids = {attrs.get("id") for _, attrs in markup.tags}
        for element_id in (
            "dashboardView", "runView", "approvalsView", "fleetTicker", "activeNow",
            "instanceGrid", "agenticUserGrid", "serverGrid", "scenarioGrid", "runHistory",
            "governanceCard", "a365ValueCard", "surfacesCard", "evidenceBtn", "lookupPurviewBtn",
            "lookupDefenderBtn", "humanPanel", "toolTimeline", "loggedEventStream",
        ):
            self.assertIn(element_id, ids)


if __name__ == "__main__":
    unittest.main()