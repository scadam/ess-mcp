/* Shared authentication for both existing pages. No token is exposed by this API.
 * Host contract: public GET /app-config and the two /static assets; protected
 * /api/* backed by control_auth.py. /api/messages keeps its separate SDK auth.
 * Register location.origin + '/control-plane' as an Entra SPA redirect URI.
 */
(() => {
  'use strict';

  const BRAND = 'Group Functions Autopilot';
  const nativeFetch = window.fetch.bind(window);
  // Microsoft CDN 2.38.3 returns 404; v3 Microsoft CDN distribution is retired.
  // This exact Microsoft package version was verified on jsDelivr. No fallback
  // to an unpinned version or a different library is attempted at runtime.
  const MSAL_URL = 'https://cdn.jsdelivr.net/npm/@azure/msal-browser@2.38.3/lib/msal-browser.min.js';
  const GUID = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
  const LEGACY_RUN_STORAGE_KEYS = ['ess-control-plane-runs-v3', 'ess-control-plane-runs-v2'];
  const messages = Object.freeze({
    checking: 'Checking sign-in. No operational data has been loaded.',
    signIn: 'Sign in with your organization account to continue. No operational data has been loaded.',
    expired: 'Your session could not be renewed. Sign in again to continue.',
    accountChanged: 'The active account changed. This page has been cleared. Reload to continue with the current account.',
    denied: 'Access denied. This account is not permitted to perform this operation. Contact your administrator or sign in with an allowed account.',
    config: 'Sign-in configuration is unavailable or invalid. Ask your administrator to check the public app configuration, then reload.',
    teams: 'Teams sign-in is unavailable. Retry sign-in, or open this page in your organization browser. Check Teams SSO configuration with your administrator.',
    library: 'The sign-in library could not load. Check your connection and your organization’s content policy, then reload.',
    network: 'The service could not be reached. Check your connection, then reload.',
    cancelled: 'Sign-in was cancelled. Select Sign in when you are ready.',
    popup: 'The sign-in window could not open. Allow popups for this site and select Sign in again.',
    failed: 'Sign-in could not complete. Try again or ask your administrator to check consent, the tenant, API scope, and SPA redirect URI.',
    locked: 'This page is locked and its operational data has been cleared. Sign in to continue. In Teams, switch accounts in Teams itself.',
    callback: 'Completing sign-in. Return to the original application window.',
  });

  let config = null;
  let pca = null;
  let account = null;
  let teamsContext = null;
  let inTeams = false;
  let authenticated = false;
  let interactive = false;
  let canSignIn = false;
  let message = messages.checking;
  let bootstrapPromise = null;
  let tokenRequest = null;
  let signedInCallback = null;
  let generation = 0;
  let sessionController = new AbortController();

  // The opener/parent MSAL instance owns the PKCE response. Do not consume or
  // clear its hash, initialize another auth flow, or fetch any application data.
  const authReturn = (Boolean(window.opener) && window.name.startsWith('msal.'))
    || ((Boolean(window.opener) || window.parent !== window)
      && /(?:^#|&)(?:code|error)=/.test(window.location.hash));

  function clearLegacyRunStorage() {
    try {
      const keys = new Set(LEGACY_RUN_STORAGE_KEYS);
      // Enumerate key names only: never deserialize another account's content.
      for (let i = 0; i < localStorage.length; i += 1) {
        const key = localStorage.key(i);
        if (key && /^ess-control-plane-(?:runs|evidence)(?:$|-)/.test(key)) keys.add(key);
      }
      for (const key of keys) localStorage.removeItem(key);
    } catch (_) { /* Storage may be disabled; no stored run content is ever read. */ }
  }

  function authError(code) {
    const error = new Error(messages[code] || messages.failed);
    error.name = 'AutopilotAuthError';
    error.code = code;
    return error;
  }

  function withTimeout(promise, milliseconds, code) {
    let timer;
    return Promise.race([
      promise,
      new Promise((_, reject) => { timer = setTimeout(() => reject(authError(code)), milliseconds); }),
    ]).finally(() => clearTimeout(timer));
  }

  async function initializeTeams() {
    if (authReturn) return;
    const embedded = window.parent !== window || Boolean(window.nativeInterface);
    if (!window.microsoftTeams?.app) {
      if (embedded) throw authError('teams');
      return;
    }
    try {
      await withTimeout(window.microsoftTeams.app.initialize(), 8000, 'teams');
      // Notify Teams as soon as the shell is available, BEFORE config/token/API
      // work. A sign-in panel is a successfully loaded tab, not a tab load error.
      Promise.resolve(window.microsoftTeams.app.notifySuccess()).catch(() => {});
      teamsContext = await withTimeout(window.microsoftTeams.app.getContext(), 8000, 'teams');
      const host = teamsContext?.app?.host?.name;
      inTeams = host === 'Teams' || host === 'TeamsModern';
      if (embedded && !inTeams) throw authError('teams');
      if (inTeams) {
        // Inside Teams the frame's theme wins over the OS preference, so the tab never contrasts with it.
        applyTeamsTheme(teamsContext?.app?.theme);
        try { window.microsoftTeams.app.registerOnThemeChangeHandler(applyTeamsTheme); } catch (_) {}
      }
    } catch (_) {
      if (embedded) throw authError('teams');
      teamsContext = null;
    }
  }

  function applyTeamsTheme(theme) {
    if (new URLSearchParams(window.location.search).get('clawpilotTheme')) return;
    document.documentElement.setAttribute('data-theme', theme === 'dark' || theme === 'contrast' ? 'dark' : 'light');
  }

  // Begin the SDK handshake immediately when this head script loads. Attach a
  // rejection handler now so an unavailable host never logs an SDK error object.
  const teamsReady = initializeTeams().then(() => true, () => false);
  clearLegacyRunStorage();

  function getAppContext() {
    // Presentation metadata only. Neither SDK context nor account metadata
    // grants roles; only the server validates tenant, audience, scope, allowlist.
    return Object.freeze({
      displayName: BRAND,
      tenantId: config?.tenantId || '',
      clientId: config?.clientId || '',
      scope: config?.scope || '',
      controlPlaneAudience: config?.controlPlaneAudience || '',
      host: inTeams ? 'Microsoft Teams' : 'Browser',
      userName: authenticated
        ? String(inTeams ? (teamsContext?.user?.displayName || 'Teams user') : (account?.name || account?.username || 'Organization account'))
        : '',
    });
  }

  function renderAuthUi() {
    const panel = document.getElementById('autopilotAuthPanel');
    const text = document.getElementById('autopilotAuthMessage');
    const signInButton = document.getElementById('autopilotSignIn');
    const context = document.getElementById('autopilotContext');
    if (text) text.textContent = message;
    if (signInButton) {
      signInButton.disabled = !canSignIn || interactive || authReturn;
      signInButton.textContent = interactive ? 'Signing in…' : (inTeams ? 'Sign in with Teams' : 'Sign in');
    }
    if (panel) panel.hidden = document.documentElement.dataset.auth === 'ready';
    if (context) {
      const app = getAppContext();
      context.textContent = [app.host, app.userName, app.tenantId ? `Tenant: ${app.tenantId}` : ''].filter(Boolean).join(' · ');
    }
  }

  function hideApp() {
    document.documentElement.dataset.auth = 'locked';
    document.querySelectorAll('[data-auth-protected]').forEach(element => {
      element.hidden = true;
      element.inert = true;
    });
  }

  function blockAccess(code) {
    authenticated = false;
    generation += 1;
    tokenRequest = null;
    sessionController.abort(); // Includes outstanding streaming response bodies.
    sessionController = new AbortController();
    message = messages[code] || messages.failed;
    hideApp();
    window.dispatchEvent(new Event('autopilot-auth-lost'));
    renderAuthUi();
  }

  function showError(text) {
    // Callers pass fixed UI copy, never SDK exceptions or response/token bodies.
    message = text;
    hideApp();
    renderAuthUi();
  }

  function showApp() {
    if (!authenticated) return false;
    document.documentElement.dataset.auth = 'ready';
    document.querySelectorAll('[data-auth-protected]').forEach(element => {
      element.hidden = false;
      element.inert = false;
    });
    renderAuthUi();
    return true;
  }

  async function loadConfig() {
    const response = await nativeFetch('/app-config', {
      method: 'GET', credentials: 'omit', cache: 'no-store', redirect: 'error',
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw authError('config');
    const value = await response.json();
    if (!value || !GUID.test(value.tenantId) || !GUID.test(value.clientId)
      || typeof value.scope !== 'string'
      || !/^(?:api:\/\/|https:\/\/)[^\s?#]+\/access_agent_as_user$/.test(value.scope)
      || typeof value.controlPlaneAudience !== 'string' || !value.controlPlaneAudience.trim()) {
      throw authError('config');
    }
    return Object.freeze({
      tenantId: value.tenantId, clientId: value.clientId, scope: value.scope,
      displayName: BRAND, controlPlaneAudience: value.controlPlaneAudience,
    });
  }

  async function initializeBrowser() {
    if (!window.msal) {
      await withTimeout(new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = MSAL_URL;
        script.crossOrigin = 'anonymous';
        script.referrerPolicy = 'no-referrer';
        script.onload = resolve;
        script.onerror = () => reject(authError('library'));
        document.head.appendChild(script);
      }), 15000, 'library');
    }
    if (!window.msal?.PublicClientApplication) throw authError('library');
    pca = new window.msal.PublicClientApplication({
      auth: {
        clientId: config.clientId,
        authority: `https://login.microsoftonline.com/${config.tenantId}`,
        redirectUri: window.location.origin + '/control-plane',
        navigateToLoginRequestUrl: false,
      },
      cache: {
        cacheLocation: 'sessionStorage',
        temporaryCacheLocation: 'sessionStorage',
        storeAuthStateInCookie: false,
        cacheMigrationEnabled: false,
      },
      system: {
        asyncPopups: false,
        allowNativeBroker: false,
        loggerOptions: { piiLoggingEnabled: false, loggerCallback: () => {} },
      },
    });
    await pca.initialize();
    const accounts = pca.getAllAccounts().filter(item => item.tenantId?.toLowerCase() === config.tenantId.toLowerCase());
    const active = pca.getActiveAccount();
    account = accounts.find(item => item.homeAccountId === active?.homeAccountId)
      || (accounts.length === 1 ? accounts[0] : null);
    if (account) pca.setActiveAccount(account);
  }

  function failureCode(error) {
    if (error?.name === 'AutopilotAuthError') return error.code;
    // Allowlisted categories only: SDK messages can contain credentials/claims.
    switch (error?.errorCode) {
      case 'user_cancelled': case 'user_canceled': return 'cancelled';
      case 'popup_window_error': case 'empty_window_error': return 'popup';
      case 'interaction_required': case 'consent_required': case 'login_required': return 'expired';
      case 'no_network_connectivity': case 'get_request_failed': case 'post_request_failed': return 'network';
      default: return inTeams ? 'teams' : 'failed';
    }
  }

  async function acquireAccessToken() {
    if (tokenRequest) return tokenRequest;
    const requestGeneration = generation;
    const pending = (async () => {
      let token;
      if (inTeams) {
        const currentContext = await withTimeout(window.microsoftTeams.app.getContext(), 8000, 'teams');
        if (authenticated && (currentContext?.user?.id !== teamsContext?.user?.id
          || currentContext?.user?.tenant?.id !== teamsContext?.user?.tenant?.id)) {
          throw authError('accountChanged');
        }
        teamsContext = currentContext;
        // Teams owns its cache and refresh. No browser popup on background work.
        token = await withTimeout(window.microsoftTeams.authentication.getAuthToken({ silent: true }), 15000, 'teams');
      } else {
        if (!pca || !account) throw authError('signIn');
        const active = pca.getActiveAccount();
        if (authenticated && (active?.homeAccountId !== account.homeAccountId || active?.tenantId !== account.tenantId)) {
          throw authError('accountChanged');
        }
        const result = await withTimeout(pca.acquireTokenSilent({ scopes: [config.scope], account }), 15000, 'expired');
        token = result.accessToken;
      }
      if (requestGeneration !== generation) throw authError('expired');
      if (typeof token !== 'string' || !token) throw authError('failed');
      return token;
    })();
    tokenRequest = pending;
    try { return await pending; }
    finally { if (tokenRequest === pending) tokenRequest = null; }
  }

  async function verifyAccess(token, requestGeneration) {
    // No JWT decoding or client-side authorization. A protected read must pass
    // the backend validator before any dashboard data or polling is initialized.
    const response = await nativeFetch('/api/identity', {
      method: 'GET', credentials: 'omit', cache: 'no-store', redirect: 'error',
      mode: 'same-origin', signal: AbortSignal.any([sessionController.signal, AbortSignal.timeout(15000)]),
      headers: { Accept: 'application/json', Authorization: `Bearer ${token}` },
    });
    if (response.status === 401) throw authError('expired');
    if (response.status === 403) throw authError('denied');
    if (!response.ok || !response.headers.get('Content-Type')?.includes('application/json')) throw authError('network');
    if (response.body) await response.body.cancel();
    if (requestGeneration !== generation) throw authError('expired');
    authenticated = true;
    message = 'Signed in. Loading operational data…';
    renderAuthUi();
  }

  async function bootstrap() {
    if (authReturn) {
      message = messages.callback;
      renderAuthUi();
      return;
    }
    try {
      if (!(await teamsReady)) throw authError('teams');
      try { config = await withTimeout(loadConfig(), 15000, 'config'); } catch (_) { throw authError('config'); }
      if (!inTeams) await initializeBrowser();
      canSignIn = true;
      if (!inTeams && !account) {
        message = messages.signIn;
        renderAuthUi();
        return;
      }
      const requestGeneration = generation;
      const token = await acquireAccessToken();
      await verifyAccess(token, requestGeneration);
    } catch (error) {
      blockAccess(failureCode(error));
    }
  }

  async function ready(onSignedIn) {
    if (typeof onSignedIn === 'function') signedInCallback = onSignedIn;
    if (!bootstrapPromise) bootstrapPromise = bootstrap();
    await bootstrapPromise;
    return authenticated;
  }

  async function signIn(event) {
    // This is the ONLY interactive sign-in entry point. Do not await anything
    // before loginPopup: it must open within the explicit button user gesture.
    if (!event?.isTrusted || !canSignIn || interactive || authReturn) return;
    interactive = true;
    // Also clears data when retrying after a service error with a different user.
    blockAccess('checking');
    const requestGeneration = generation;
    try {
      const interaction = inTeams
        ? window.microsoftTeams.authentication.getAuthToken({ silent: false })
        : pca.loginPopup({ scopes: [config.scope], prompt: 'select_account' });
      const result = await interaction;
      if (requestGeneration !== generation) throw authError('expired');
      const token = inTeams ? result : result.accessToken;
      if (typeof token !== 'string' || !token) throw authError('failed');
      if (!inTeams) {
        account = result.account;
        pca.setActiveAccount(account);
      }
      await verifyAccess(token, requestGeneration);
      if (signedInCallback) await signedInCallback();
      else window.location.reload(); // Clears all prior in-memory UI/run state.
    } catch (error) {
      blockAccess(failureCode(error));
    } finally {
      interactive = false;
      renderAuthUi();
    }
  }

  async function lock() {
    const previousAccount = account;
    const wasSignInEnabled = canSignIn;
    canSignIn = false;
    blockAccess('locked');
    clearLegacyRunStorage();
    account = null;
    if (pca) {
      // MSAL's supported local-only logout: clear this application's cache,
      // deliberately cancel navigation. Never clear unrelated browser storage.
      try { await pca.logoutRedirect({ account: previousAccount, onRedirectNavigate: () => false }); }
      catch (_) { message = 'The page is locked. Close this browser tab to finish clearing the sign-in session.'; }
    }
    canSignIn = wasSignInEnabled;
    renderAuthUi();
  }

  async function controlFetch(input, options) {
    const request = new Request(input, options);
    const url = new URL(request.url);
    const headers = new Headers(request.headers);
    headers.delete('Authorization');
    let path;
    try { path = decodeURIComponent(url.pathname); } catch (_) { throw authError('failed'); }
    const isControlApi = url.origin === window.location.origin
      && (path === '/api' || path.startsWith('/api/'))
      && path !== '/api/messages' && !path.startsWith('/api/messages/');
    if (!isControlApi) {
      // Never carry caller-supplied or cached Authorization to another origin,
      // public assets, or the bot endpoint. MSAL's own Entra requests still work.
      return nativeFetch(new Request(request, { headers, credentials: 'omit' }));
    }
    if (!(await ready())) throw authError('signIn');
    const requestGeneration = generation;
    let token;
    try { token = await acquireAccessToken(); }
    catch (error) {
      if (requestGeneration === generation) blockAccess(failureCode(error));
      throw authError(failureCode(error));
    }
    if (!authenticated || requestGeneration !== generation) throw authError('expired');
    headers.set('Authorization', `Bearer ${token}`);
    const response = await nativeFetch(new Request(request, {
      headers, credentials: 'omit', cache: 'no-store', redirect: 'error', mode: 'same-origin',
      signal: AbortSignal.any([request.signal, sessionController.signal]),
    }));
    if (requestGeneration !== generation) throw authError('expired');
    if (response.status === 401 || response.status === 403) {
      const code = response.status === 403 ? 'denied' : 'expired';
      blockAccess(code);
      throw authError(code); // Never retry POSTs or convert denial into empty data.
    }
    return response; // Preserve the streaming body; no SSE buffering or EventSource.
  }

  window.fetch = controlFetch;
  window.autopilotAuth = Object.freeze({
    ready, getAppContext, showApp, showError, clearLegacyRunStorage,
    isAuthenticated: () => authenticated,
  });

  document.addEventListener('DOMContentLoaded', () => {
    document.getElementById('autopilotSignIn')?.addEventListener('click', signIn);
    document.getElementById('autopilotLock')?.addEventListener('click', lock);
    renderAuthUi();
  }, { once: true });
  window.addEventListener('pagehide', () => blockAccess('locked'));
  window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
})();