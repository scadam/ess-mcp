
// ── State ──
let servers = [];
let skills = [];
let identity = null;
let runs = [];
let activeRunId = null;
let instances = [];
const instanceState = Object.create(null);   // instance_id -> { lastError, lastDelivery, lastScenario }
// User's current scenario-dropdown selection per instance. Captured before any
// re-render so the dropdown doesn't snap back to the first option while the
// polling refresh ticks.
const instanceScenarioSelection = Object.create(null); // instance_id -> scenario value
const pollingTimers = new Set();

// Control-plane governance state — kill switch per agent identity instance,
// runtime tool deny-list, and the in-memory audit ledger. Mirrored from
// `/api/governance` on a slow timer and after every operator action.
let governance = { disabledInstances: {}, toolDenylist: [], audit: [] };

const RUN_STORAGE_KEY = 'ess-control-plane-runs-v3';
const LEGACY_RUN_STORAGE_KEYS = ['ess-control-plane-runs-v2'];
const RUN_STALE_AFTER_MS = 20 * 60 * 1000;

const SCENARIO_META = {
  'incident-triage': { icon: 'INCIDENT', desc: 'ServiceNow incident triage enriched with Workday availability and manager context.', tags: ['servicenow', 'workday'] },
  'team-review': { icon: 'REVIEW', desc: 'Executive team status report covering Workday people signals and ServiceNow operational health.', tags: ['workday', 'servicenow'] },
  'onboarding-audit': { icon: 'AUDIT', desc: 'New-hire onboarding readiness across Workday profile, learning, approvals, and ServiceNow provisioning.', tags: ['workday', 'servicenow'] },
  'sprint-readiness': { icon: 'SPRINT', desc: 'Delivery readiness using Workday capacity signals and ServiceNow IT health blockers.', tags: ['workday', 'servicenow'] },
  'hiring-pipeline': { icon: 'HIRING', desc: 'Hiring and onboarding workflow focused on Workday team context and ServiceNow provisioning.', tags: ['workday', 'servicenow'] },
  'cross-system-overview': { icon: 'SYSTEM', desc: 'Employee self-service overview across Workday profile, time off, pay, tasks, and ServiceNow IT items.', tags: ['workday', 'servicenow'] },
  'procurement-to-invoice': { icon: 'PROCURE', desc: 'Reconcile Coupa POs/invoices against ServiceNow receipts; ask manager to hold pay + reject invoice on discrepancies.', tags: ['coupa', 'servicenow'] },
  'requisition-approval-triage': { icon: 'REQUISITION', desc: 'Find Coupa requisitions stuck in approval, cross-reference requester ServiceNow tickets, ask manager approve/reject/hold.', tags: ['coupa', 'servicenow'] },
  'compliance-case-resolution': { icon: 'COMPLIANCE', desc: 'Turn an emailed compliance question into a Salesforce case, investigate approved evidence through Work IQ, resolve it with the requester in a private Teams chat, then close the case.', tags: ['salesforce', 'workiq'] },
  'manager-approval': { icon: 'APPROVAL', desc: 'Triage the top P1 incident, then ask the manager for a yes/no escalation decision in Teams before acting.', tags: ['servicenow', 'workday'] },
};

const SERVER_ICONS = { workday: 'WD', servicenow: 'SN', coupa: 'CP', salesforce: 'SF', workiq: 'WIQ' };
const SERVER_DESCS = {
  workday: 'HR, payroll, learning, performance, org structure',
  servicenow: 'Incidents, changes, problems, catalog, approvals',
  coupa: 'Procurement, requisitions, POs, receipts, invoices, supplier mgmt',
  salesforce: 'Compliance cases, case comments, activity history, CRM pipeline',
  workiq: 'Microsoft 365 work data through Work IQ, delegated per AI teammate instance',
};
const ALL_SERVER_NAMES = ['workday', 'servicenow', 'coupa', 'salesforce'];
const SERVER_LABELS = { workday: 'Workday', servicenow: 'ServiceNow', coupa: 'Coupa', salesforce: 'Salesforce', workiq: 'Work IQ' };

// ── Init ──
async function init() {
  loadRuns();
  if (!window.autopilotAuth) {
    document.getElementById('autopilotAuthMessage').textContent = 'Sign-in support could not load. Reload the page or ask your administrator to check the static assets.';
    return;
  }
  if (!(await window.autopilotAuth.ready())) return;
  try {
    const [skillRes, serverRes, identityRes, runRes] = await Promise.all([
      fetchJson('/api/skills'),
      fetchJson('/api/servers'),
      fetchJson('/api/identity'),
      fetchJson('/api/runs'),
    ]);
    if (!window.autopilotAuth.isAuthenticated()) return;
    if (!Array.isArray(skillRes) || !Array.isArray(serverRes) || !Array.isArray(runRes) || !identityRes) {
      throw new Error('Operational data is unavailable.');
    }
    skills = skillRes;
    servers = serverRes;
    identity = identityRes;
    mergeServerRuns(runRes);
    renderDashboard();
    await Promise.all([refreshInstances(false), refreshGovernance(), loadA365Value(), refreshControlRoom(), refreshFleetFeed()]);
    renderControlRoom();
    renderFleetFeed();
    crTick();
    if (!window.autopilotAuth.showApp()) return;
  } catch (_) {
    if (window.autopilotAuth.isAuthenticated()) {
      window.autopilotAuth.showError('Operational data could not be loaded. Reload to retry; this is not an empty dashboard.');
    }
    return;
  }
  startPolling(refreshServerRuns, 3500);
  startPolling(() => refreshInstances(false), 30000);
  startPolling(refreshGovernance, 10000);
  startPolling(refreshControlRoom, 3000);
  startPolling(refreshFleetFeed, 2500);
  startPolling(refreshColleagueFeed, 2000);
  startPolling(async () => crTick(), 1000);
  // Live elapsed-counter tick — keep the control room "alive" even between server polls.
  // We only re-render the lightweight ticker + Now Running cards every second; the
  // instance grid is heavier and re-rendering it tears down any open <select>.
  startPolling(() => {
    const dash = document.getElementById('dashboardView');
    if (!dash || dash.classList.contains('hidden')) return;
    renderActiveNow();
    renderFleetTicker();
    // Only re-render the instance grid if the user isn't currently interacting
    // with one of its inputs (otherwise the open <select> dropdown collapses).
    if (!isInteractingWithInstanceGrid()) renderInstances();
  }, 1000);
  // Lightweight approvals refresh — keeps the nav badge live regardless of view.
  startPolling(() => { renderApprovalsBadge(); }, 2000);
  // When the approvals view is open, keep cards in sync with run state.
  startPolling(() => {
    const v = document.getElementById('approvalsView');
    if (v && v.classList.contains('active')) renderApprovals();
  }, 3000);
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`Request failed (HTTP ${response.status}).`);
  const data = await response.json();
  if (!window.autopilotAuth.isAuthenticated()) throw new Error('Sign-in required.');
  return data;
}

function startPolling(callback, delay) {
  let busy = false;
  const timer = setInterval(async () => {
    if (!window.autopilotAuth?.isAuthenticated()) {
      clearInterval(timer);
      pollingTimers.delete(timer);
      return;
    }
    if (busy) return;
    busy = true;
    try { await callback(); }
    catch (_) {
      if (window.autopilotAuth.isAuthenticated()) document.getElementById('fleetStream').textContent = 'Updates are temporarily unavailable. Reload to reconnect.';
    } finally { busy = false; }
  }, delay);
  pollingTimers.add(timer);
  return timer;
}

window.addEventListener('autopilot-auth-lost', () => {
  for (const timer of pollingTimers) clearInterval(timer);
  pollingTimers.clear();
  runs = [];
  activeRunId = null;
  servers = [];
  skills = [];
  instances = [];
  identity = null;
  a365ValueData = null;
  governance = { disabledInstances: {}, toolDenylist: [], audit: [] };
  controlRoom = null;
  crFeed = [];
  clFeed = [];
  crRevision = 0;
  clRevision = 0;
  activeColleague = null;
  clPolicyDraft = null;
  openFeedIds.clear();
  for (const key of Object.keys(instanceState)) delete instanceState[key];
  for (const key of Object.keys(instanceScenarioSelection)) delete instanceScenarioSelection[key];
  for (const id of [
    'crWall', 'crFleetFeed', 'crSystems', 'crAnnunciators', 'clFeed', 'clCases', 'clSkills', 'clServers', 'clIssues',
    'clActions', 'clStats', 'clPresence', 'clMeta', 'clName', 'clPolicySource',
    'serverDots', 'serverGrid', 'scenarioGrid', 'runHistory', 'instanceGrid', 'agenticUserGrid',
    'identityMeta', 'runtimeMeta', 'runtimePills', 'activeNow', 'fleetStream', 'toolTimeline',
    'serversUsed', 'agentEventStream', 'loggedEventStream', 'runResultContent', 'teamsThread',
    'approvalsPending', 'approvalsCompleted', 'governanceActiveRules', 'governanceDisabledList',
    'governanceAudit', 'a365ValueSummary', 'a365ValueCategories', 'a365ModalBg',
    'detailTitle', 'detailInput', 'detailOutput', 'runTitle', 'runningText', 'humanMessage',
  ]) document.getElementById(id)?.replaceChildren();
  document.querySelectorAll('[data-auth-protected] textarea').forEach(element => { element.value = ''; });
  document.querySelectorAll('#statsPanel .value').forEach(element => { element.textContent = '—'; });
  document.getElementById('topbarTitle').textContent = 'Control Room';
  document.getElementById('toastHost')?.remove();
  document.getElementById('govToast')?.remove();
  closeDetail();
  closeA365Modal();
});

function isInteractingWithInstanceGrid() {
  const grid = document.getElementById('instanceGrid');
  if (!grid) return false;
  const ae = document.activeElement;
  if (ae && grid.contains(ae) && (ae.tagName === 'SELECT' || ae.tagName === 'BUTTON' || ae.tagName === 'INPUT')) return true;
  // Treat very recent pointerdown/click within the grid as "interacting" so the
  // re-render doesn't fight a freshly-opened native <select> dropdown.
  if (window.__instanceGridInteractAt && (Date.now() - window.__instanceGridInteractAt) < 1500) return true;
  return false;
}

document.addEventListener('pointerdown', (e) => {
  const grid = document.getElementById('instanceGrid');
  if (grid && grid.contains(e.target)) window.__instanceGridInteractAt = Date.now();
}, true);

function newRunId() {
  return 'run-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 7);
}

function loadRuns() {
  runs = [];
  activeRunId = null;
  for (const key of [RUN_STORAGE_KEY, ...LEGACY_RUN_STORAGE_KEYS]) {
    try { localStorage.removeItem(key); } catch (_) { /* Storage can be disabled. */ }
  }
  window.autopilotAuth?.clearLegacyRunStorage();
}

function isActiveStatus(status) {
  return status === 'running' || status === 'waiting';
}

function expireStaleRuns() {
  const now = Date.now();
  let changed = false;
  for (const run of runs) {
    if (!isActiveStatus(run.status) || run.caseRun) continue;
    const lastUpdate = run.updatedAt || run.startedAt || 0;
    if (lastUpdate && now - lastUpdate > RUN_STALE_AFTER_MS) {
      run.status = 'error';
      run.error = 'Marked stale by the control plane after no updates for 20 minutes.';
      run.runningText = run.error;
      run.completedAt = now;
      run.updatedAt = now;
      changed = true;
    }
  }
  if (changed) saveRuns();
}

async function resetRuns() {
  try {
    const response = await fetch('/api/runs/reset', { method: 'POST' });
    if (!response.ok) throw new Error('Reset failed.');
    if (!window.autopilotAuth.isAuthenticated()) return;
    loadRuns();
    renderRunHistory();
    renderAgenticUsers();
  } catch (_) { if (window.autopilotAuth?.isAuthenticated()) showToast('Runs could not be reset.', 'warn'); }
}

function saveRuns() {
  // In-memory bookkeeping only. Prompts, evidence, and responses never persist
  // across browser accounts, tabs, reloads, or sign-out.
  expireStaleRunsNoSave();
}

function expireStaleRunsNoSave() {
  const now = Date.now();
  for (const run of runs) {
    if (!isActiveStatus(run.status) || run.caseRun) continue;
    const lastUpdate = run.updatedAt || run.startedAt || 0;
    if (lastUpdate && now - lastUpdate > RUN_STALE_AFTER_MS) {
      run.status = 'error';
      run.error = 'Marked stale by the control plane after no updates for 20 minutes.';
      run.runningText = run.error;
      run.completedAt = now;
      run.updatedAt = now;
    }
  }
}

async function refreshServerRuns() {
  if (!window.autopilotAuth?.isAuthenticated()) return;
  try {
    const serverRuns = await fetchJson('/api/runs');
    mergeServerRuns(serverRuns);
    renderApprovalsBadge();
    const v = document.getElementById('approvalsView');
    if (v && v.classList.contains('active')) renderApprovals();
  } catch (_) { /* keep the last known state */ }
}

function mergeServerRuns(serverRuns) {
  if (!window.autopilotAuth?.isAuthenticated()) return;
  expireStaleRunsNoSave();
  if (!Array.isArray(serverRuns) || !serverRuns.length) return;
  let changed = false;
  for (const serverRun of serverRuns) {
    const index = runs.findIndex(run => run.id === serverRun.id);
    if (index < 0) {
      runs.unshift(serverRun);
      changed = true;
    } else if ((serverRun.updatedAt || 0) >= (runs[index].updatedAt || 0)) {
      runs[index] = { ...runs[index], ...serverRun };
      changed = true;
    }
  }
  runs.sort((a, b) => (b.startedAt || 0) - (a.startedAt || 0));
  if (changed) {
    saveRuns();
    renderRunHistory();
    if (activeRunId) {
      const active = getRun(activeRunId);
      if (active) renderRun(active);
    }
  }
}

function getRun(id = activeRunId) {
  return runs.find(run => run.id === id) || null;
}

function upsertRun(run) {
  if (!window.autopilotAuth?.isAuthenticated()) return;
  const index = runs.findIndex(existing => existing.id === run.id);
  if (index >= 0) runs[index] = run;
  else runs.unshift(run);
  runs.sort((a, b) => b.startedAt - a.startedAt);
  saveRuns();
  renderRunHistory();
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[ch]));
}

// A string embedded in an inline handler needs BOTH JS-string and HTML-attribute
// escaping. HTML entities alone decode before the handler's JS is compiled.
function jsString(value) {
  return escapeHtml(JSON.stringify(String(value ?? '')));
}

function brandText(value) {
  // Keep actual hostnames, paths, and configuration identifiers intact.
  return String(value ?? '').replace(/\b(?:Project\s*ESS|ESS\s*Hosted\s*Agent|ESS-MCP|ESS)\b(?![-_./])/gi, 'Group Functions Autopilot');
}

function safeHref(value) {
  try {
    const url = new URL(String(value || ''), window.location.origin);
    if (!url.username && !url.password && (url.protocol === 'https:' || (url.protocol === 'http:' && url.origin === window.location.origin))) {
      return escapeHtml(url.href);
    }
  } catch (_) { /* Unsafe links stay inert. */ }
  return '#';
}

function safeText(value, fallback = 'not configured') {
  if (value === undefined || value === null || value === '') return fallback;
  return String(value);
}

function renderDashboard() {
  const totalTools = servers.reduce((n, s) => n + s.tools, 0);

  // KPIs
  document.getElementById('kpiServers').textContent = servers.length || '0';
  document.getElementById('kpiServersDetail').textContent = servers.length
    ? servers.map(s => s.name).join(', ')
    : 'no servers connected';
  document.getElementById('kpiTools').textContent = totalTools || '0';
  document.getElementById('kpiScenarios').textContent = skills.length || '0';
  document.getElementById('navToolCount').textContent = totalTools || '—';

  // Widget resource count — known per-server resource counts
  const RESOURCE_COUNTS = { workday: 14, servicenow: 12, coupa: 9, salesforce: 9 };
  const connectedNames = new Set(servers.map(s => s.name));
  const totalResources = servers.reduce((n, s) => n + (RESOURCE_COUNTS[s.name] || 0), 0);
  document.getElementById('kpiResources').textContent = totalResources || '—';
  document.getElementById('kpiResourcesDetail').textContent = totalResources
    ? `across ${servers.length} server${servers.length !== 1 ? 's' : ''}`
    : 'connect servers to see resources';

  // Server dots in topbar
  document.getElementById('serverDots').innerHTML = ALL_SERVER_NAMES.map(name => {
    const on = connectedNames.has(name);
    return `<span class="server-dot"><span class="dot ${on ? 'on' : 'off'}"></span>${name}</span>`;
  }).join('') + '<span class="server-dot" title="Delegated per AI teammate instance"><span class="dot on"></span>workiq</span>';

  // Server cards
  document.getElementById('serverGrid').innerHTML = ALL_SERVER_NAMES.map(name => {
    const srv = servers.find(s => s.name === name);
    const icon = SERVER_ICONS[name] || '🔌';
    const desc = SERVER_DESCS[name] || '';
    if (srv) {
      return `
        <div class="server-card">
          <div class="server-header">
            <span class="server-icon">${icon}</span>
            <span class="server-name">${name}</span>
            <span class="server-status connected">Connected</span>
          </div>
          <div class="tool-count">${escapeHtml(srv.tools)}</div>
          <div class="tool-label">tools available${srv.gateway ? ' through gateway' : ''}</div>
          <div class="tool-types">${desc}</div>
          <div class="endpoint">${escapeHtml(srv.url || '')}</div>
        </div>`;
    }
    return `
      <div class="server-card">
        <div class="server-header">
          <span class="server-icon">${icon}</span>
          <span class="server-name">${name}</span>
          <span class="server-status disconnected">Not connected</span>
        </div>
        <div class="tool-count" style="color:var(--dim)">—</div>
        <div class="tool-label">configure the ${name} MCP gateway</div>
        <div class="tool-types">${desc}</div>
      </div>`;
  }).join('') + `
      <div class="server-card">
        <div class="server-header">
          <span class="server-icon">${SERVER_ICONS.workiq}</span>
          <span class="server-name">workiq</span>
          <span class="server-status connected">Delegated</span>
        </div>
        <div class="tool-count">M365</div>
        <div class="tool-label">connected per AI teammate with its agentic-user token</div>
        <div class="tool-types">${SERVER_DESCS.workiq}</div>
        <div class="endpoint">https://workiq.svc.cloud.microsoft/mcp</div>
      </div>`;

  renderIdentity();
  renderAgenticUsers();

  // Scenario cards
  const scenarioCount = skills.length;
  document.getElementById('scenarioCount').textContent = `(${scenarioCount})`;
  document.getElementById('scenarioGrid').innerHTML = skills.map((s, i) => {
    const meta = SCENARIO_META[s.name] || { icon: '🤖', desc: 'Run this skill against connected MCP servers.', tags: [] };
    const title = s.name.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    const tags = meta.tags.map(t => {
      const connected = t === 'workiq' || servers.some(srv => srv.name === t);
      return `<span class="server-tag" style="${connected ? '' : 'opacity:.4'}">${SERVER_ICONS[t] || ''} ${t}</span>`;
    }).join('');
    return `
      <div class="scenario-card" id="scenario-${i}">
        <div class="scenario-icon">${meta.icon}</div>
        <h3>${escapeHtml(title)}</h3>
        <div class="scenario-desc">${meta.desc}</div>
        <div class="scenario-servers">${tags}</div>
        <button class="run-btn" onclick="event.stopPropagation();runScenario(${i})">▶ Run Scenario</button>
      </div>`;
  }).join('');

  renderRunHistory();
}

function runStatusLabel(status) {
  return status === 'waiting' ? 'Waiting' : status === 'complete' ? 'Complete' : status === 'error' ? 'Error' : 'Running';
}

function actorInitials(name) {
  const text = safeText(name, 'AU').replace(/[^a-z0-9 ]/gi, ' ').trim();
  const parts = text.split(/\s+/).filter(Boolean);
  if (!parts.length) return 'AU';
  return parts.slice(0, 2).map(part => part[0]).join('').toUpperCase();
}

function runAgenticUser(run) {
  if (run.agenticUser) return run.agenticUser;
  const actor = run.actor || {};
  const source = run.source || 'control-plane';
  const actorName = actor.name || actor.id || (source === 'teams-chat' ? 'Teams User' : 'Control Plane Operator');
  return {
    id: actor.id || (source === 'control-plane' ? 'control-plane' : source),
    name: actorName,
    source,
    mode: source === 'teams-chat' ? 'teams-agentic-user' : 'hosted-control-plane',
    templateId: identity && identity.agentIdentity ? identity.agentIdentity.objectId : '',
    blueprintId: identity && identity.blueprint ? identity.blueprint.clientId : '',
    runtimeAgentIdentityId: identity && identity.agentIdentity ? identity.agentIdentity.objectId : '',
  };
}

function getAgenticUserSessions() {
  expireStaleRunsNoSave();
  const grouped = new Map();
  for (const run of runs) {
    const agenticUser = runAgenticUser(run);
    const key = agenticUser.id || agenticUser.name || agenticUser.source || 'unknown';
    const existing = grouped.get(key) || {
      ...agenticUser,
      totalRuns: 0,
      activeRuns: 0,
      toolCalls: 0,
      latestRun: null,
      sources: new Set(),
    };
    existing.totalRuns += 1;
    if (isActiveStatus(run.status)) existing.activeRuns += 1;
    existing.toolCalls += Object.keys(run.toolData || {}).length;
    existing.sources.add(run.source || agenticUser.source || 'unknown');
    if (!existing.latestRun || (run.startedAt || 0) > (existing.latestRun.startedAt || 0)) {
      existing.latestRun = run;
      existing.name = agenticUser.name || existing.name;
      existing.mode = agenticUser.mode || existing.mode;
    }
    grouped.set(key, existing);
  }
  return Array.from(grouped.values()).sort((a, b) => ((b.latestRun && b.latestRun.startedAt) || 0) - ((a.latestRun && a.latestRun.startedAt) || 0));
}

function renderAgenticUsers() {
  const grid = document.getElementById('agenticUserGrid');
  const countEl = document.getElementById('agenticUserCount');
  if (!grid || !countEl) return;
  const sessions = getAgenticUserSessions();
  const active = sessions.filter(session => session.activeRuns > 0).length;
  countEl.textContent = `(${sessions.length}${active ? `, ${active} active` : ''})`;
  if (!sessions.length) {
    grid.innerHTML = '<div class="run-history-empty">No agentic-user sessions yet.</div>';
    return;
  }
  grid.innerHTML = sessions.slice(0, 6).map(session => {
    const latest = session.latestRun || {};
    const sourceLabel = session.mode === 'teams-agentic-user' ? 'Teams chat' : 'Control plane';
    const when = latest.startedAt ? new Date(latest.startedAt).toLocaleTimeString() : '—';
    const templateId = session.templateId || (identity && identity.agentIdentity && identity.agentIdentity.objectId) || 'not configured';
    const latestTitle = latest.title || 'No run yet';
    // Find the actual active run for this session so the card can deep-link
    // into it, consistent with the AI Teammate Instances panel above.
    const liveRun = activeRunForAgenticSession(session.id);
    const cardClasses = ['agentic-card'];
    if (session.activeRuns) cardClasses.push('active');
    if (liveRun) cardClasses.push('clickable');
    const cardClick = liveRun ? ` onclick="openRun(${jsString(liveRun.id)})" title="Open active run"` : '';
    return `
      <div class="${cardClasses.join(' ')}"${cardClick}>
        <div class="agentic-head">
          <span class="agentic-avatar">${escapeHtml(actorInitials(session.name))}</span>
          <span class="agentic-name">${escapeHtml(brandText(session.name))}</span>
          <span class="agentic-state ${session.activeRuns ? 'active' : ''}">${session.activeRuns ? 'Active' : 'Idle'}</span>
        </div>
        <div class="agentic-metrics">
          <div class="agentic-metric"><strong>${session.activeRuns}</strong><span>Active</span></div>
          <div class="agentic-metric"><strong>${session.totalRuns}</strong><span>Runs</span></div>
          <div class="agentic-metric"><strong>${escapeHtml(session.toolCalls)}</strong><span>Tools</span></div>
        </div>
        <div class="agentic-detail">
          <div>${escapeHtml(sourceLabel)} · last ${escapeHtml(when)}</div>
          <div class="mono">${escapeHtml(latestTitle)}</div>
          <div class="mono">template ${escapeHtml(templateId)}</div>
        </div>
      </div>`;
  }).join('');
}

async function refreshInstances(force) {
  if (!window.autopilotAuth?.isAuthenticated()) return;
  const grid = document.getElementById('instanceGrid');
  try {
    const url = '/api/agentic-instances' + (force ? '?refresh=1' : '');
    const res = await fetchJson(url);
    instances = res.instances || [];
    document.getElementById('instanceCount').textContent = `(${instances.length})`;
    renderInstances();
  } catch (e) {
    if (grid && window.autopilotAuth.isAuthenticated()) grid.textContent = 'Could not load instances. Select Refresh from Entra to retry.';
  }
}

// ── Control-plane enforcement (governance) ─────────────────────────
async function refreshGovernance() {
  if (!window.autopilotAuth?.isAuthenticated()) return;
  try {
    const res = await fetchJson('/api/governance');
    governance = {
      disabledInstances: res.disabledInstances || {},
      toolDenylist: res.toolDenylist || [],
      audit: res.audit || [],
    };
    renderGovernancePanel();
    // Instance cards display "Isolated" badges / disabled Run buttons from
    // governance state — re-render so operator actions are visible immediately.
    if (instances.length) renderInstances();
  } catch (_) {
    if (window.autopilotAuth.isAuthenticated()) document.getElementById('governanceAudit').textContent = 'Governance status could not be refreshed.';
  }
}

function renderGovernancePanel() {
  const countEl = document.getElementById('governanceCount');
  if (countEl) {
    const n = Object.keys(governance.disabledInstances || {}).length + (governance.toolDenylist || []).length;
    countEl.textContent = `(${n})`;
  }
  const input = document.getElementById('governanceDenyInput');
  if (input && document.activeElement !== input) {
    input.value = (governance.toolDenylist || []).join('\n');
  }
  const chips = document.getElementById('governanceActiveRules');
  if (chips) {
    if (!governance.toolDenylist.length) {
      chips.innerHTML = '<span class="gov-sub">No active deny rules. All tools allowed.</span>';
    } else {
      chips.innerHTML = governance.toolDenylist.map(p =>
        `<span class="chip">${escapeHtml(p)}</span>`
      ).join('');
    }
  }
  const list = document.getElementById('governanceDisabledList');
  if (list) {
    const entries = Object.entries(governance.disabledInstances || {});
    if (!entries.length) {
      list.innerHTML = '<div class="gov-empty">No agents isolated. Use the Isolate button on any instance card to kill-switch a single agent identity in real time.</div>';
    } else {
      list.innerHTML = entries.map(([id, reason]) => {
        const inst = instances.find(i => i.instance_id === id);
        const name = inst ? (inst.display_name || id) : id;
        return `<div class="row">
          <div>
            <div>${escapeHtml(brandText(name))}</div>
            <div class="target">${escapeHtml(id)} · ${escapeHtml(reason)}</div>
          </div>
          <button onclick="restoreInstance(${jsString(id)})">Restore</button>
        </div>`;
      }).join('');
    }
  }
  const audit = document.getElementById('governanceAudit');
  if (audit) {
    if (!governance.audit.length) {
      audit.innerHTML = '<div class="gov-empty">No enforcement events yet.</div>';
    } else {
      audit.innerHTML = governance.audit.slice(0, 25).map(e => {
        const when = new Date(e.timestampMs).toLocaleTimeString();
        const det = Object.entries(e.detail || {})
          .filter(([k, v]) => v !== '' && v != null && k !== 'previous')
          .map(([k, v]) => `${k}=${typeof v === 'string' ? v : JSON.stringify(v)}`)
          .join(' · ');
        return `<div class="entry">
          <span class="when">${escapeHtml(when)}</span>
          <span class="act">${escapeHtml(e.action)}</span>
          <span class="who">by ${escapeHtml(e.actor)}</span>
          <div class="target">${escapeHtml(e.target)}</div>
          ${det ? `<div class="det">${escapeHtml(det)}</div>` : ''}
        </div>`;
      }).join('');
    }
  }
}

async function isolateInstance(id, name) {
  const reason = prompt(`Isolate "${name}"?\n\nAll future runs from this agent identity will be blocked immediately. Provide a reason for the audit ledger:`, 'Compliance review');
  if (reason == null) return;
  try {
    const response = await fetch(`/api/governance/instance/${encodeURIComponent(id)}/disable`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason: reason || 'Isolated by control plane operator' }),
    });
    if (!response.ok) throw new Error('The isolate request failed.');
    if (!window.autopilotAuth.isAuthenticated()) return;
    showGovernanceToast(`Agent ${name} isolated. Kill switch active.`);
    await refreshGovernance();
  } catch (e) {
    alert('Isolate failed: ' + e);
  }
}

async function restoreInstance(id) {
  try {
    const response = await fetch(`/api/governance/instance/${encodeURIComponent(id)}/enable`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (!response.ok) throw new Error('The restore request failed.');
    if (!window.autopilotAuth.isAuthenticated()) return;
    showGovernanceToast('Agent restored. Runs may resume.');
    await refreshGovernance();
  } catch (e) {
    alert('Restore failed: ' + e);
  }
}

async function applyToolDenylist() {
  const input = document.getElementById('governanceDenyInput');
  const patterns = (input.value || '')
    .split(/[\n,]/)
    .map(s => s.trim())
    .filter(Boolean);
  try {
    const response = await fetch('/api/governance/tool-denylist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ patterns }),
    });
    if (!response.ok) throw new Error('The deny-list request failed.');
    if (!window.autopilotAuth.isAuthenticated()) return;
    showGovernanceToast(patterns.length
      ? `Tool deny-list applied (${patterns.length} rule${patterns.length === 1 ? '' : 's'}).`
      : 'Tool deny-list cleared.');
    await refreshGovernance();
  } catch (e) {
    alert('Apply failed: ' + e);
  }
}

async function clearToolDenylist() {
  document.getElementById('governanceDenyInput').value = '';
  await applyToolDenylist();
}

function showGovernanceToast(message) {
  if (!window.autopilotAuth?.isAuthenticated()) return;
  const existing = document.getElementById('govToast');
  if (existing) existing.remove();
  const el = document.createElement('div');
  el.id = 'govToast';
  el.className = 'gov-toast';
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => { try { el.remove(); } catch (_) {} }, 5500);
}

async function downloadEvidence(runId) {
  if (!runId || !window.autopilotAuth?.isAuthenticated()) return;
  let objectUrl;
  try {
    const response = await fetch(`/api/runs/${encodeURIComponent(runId)}/evidence`);
    if (!response.ok) throw new Error('Evidence download failed.');
    const blob = await response.blob();
    if (!window.autopilotAuth.isAuthenticated()) return;
    objectUrl = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = objectUrl;
    link.download = `group-functions-autopilot-${String(runId).replace(/[^a-z0-9_-]/gi, '')}-evidence.json`;
    document.body.appendChild(link);
    link.click();
    link.remove();
  } catch (_) {
    if (window.autopilotAuth.isAuthenticated()) showToast('Evidence could not be downloaded.', 'warn');
  } finally {
    if (objectUrl) setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }
}

// ─── Run → portal correlation ────────────────────────────────────────────
// DSPM-for-AI's Activity Explorer does not currently accept filter values
// via URL params. Per-teammate Agent name break-out is also not possible
// today (Microsoft has not shipped a public registration API for per-
// instance AI apps; all SDK runs collapse under the parent registered
// app). The practical workaround is to open the portal at the right
// tenant/view and copy the filter values to the clipboard so the operator
// can paste them into the filter panel. We compute a tight ±5 min window
// around the run start so the row count stays manageable.
function _runFilterValues(run) {
  if (!run) return null;
  const actor = run.actor || {};
  const ident = (typeof identity !== 'undefined' && identity) ? identity : null;
  const tid = (ident && ident.tenantId) || '';
  const started = run.startedAt ? new Date(run.startedAt) : new Date();
  const fromTs = new Date(started.getTime() - 5 * 60 * 1000);
  const toTs = new Date(started.getTime() + 10 * 60 * 1000);
  // Collect every AAD object id / app id that could legitimately appear
  // on a Defender row for this run, so the AADSpnSignInEventsBeta filter
  // can match the per-teammate ServicePrincipalId AND the parent agent SP.
  const parentAppId = (ident && ident.agentIdentity && ident.agentIdentity.clientId) || '';
  const parentSpOid = (ident && ident.agentIdentity && ident.agentIdentity.objectId) || '';
  const blueprintAppId = (ident && ident.blueprint && ident.blueprint.clientId) || '';
  const blueprintSpOid = (ident && ident.blueprint && ident.blueprint.objectId) || '';
  const agenticAppId = actor.agenticAppClientId || actor.agenticAppId || '';
  const agenticSpOid = actor.agenticUserId || '';
  const managerOid = actor.aadObjectId || actor.id || '';
  const ids = [parentAppId, parentSpOid, blueprintAppId, blueprintSpOid, agenticAppId, agenticSpOid, managerOid]
    .filter(Boolean)
    .filter((v, i, a) => a.indexOf(v) === i);
  return {
    tenantId: tid,
    managerUpn: actor.upn || actor.managerEmail || actor.managerUpn || '',
    managerName: actor.name || '',
    managerOid: managerOid,
    agenticUpn: actor.agenticUserUpn || '',
    agenticAppId: agenticAppId,
    agenticSpOid: agenticSpOid,
    agenticName: actor.agenticUserName || actor.agenticAppName || '',
    parentAppId: parentAppId,
    parentSpOid: parentSpOid,
    runId: run.id || '',
    fromIso: fromTs.toISOString(),
    toIso: toTs.toISOString(),
    startedIso: started.toISOString(),
    ids: ids,
  };
}

function _copyToClipboard(text) {
  if (!navigator.clipboard) return Promise.resolve(false);
  return navigator.clipboard.writeText(text).then(() => true, () => false);
}

function lookupRunInPurview(runId) {
  const run = runs.find(r => r.id === runId);
  if (!run) { showToast('Run not found', 'warn'); return; }
  const v = _runFilterValues(run);
  if (!v) { showToast('No filter values to compute', 'warn'); return; }
  // Use the same Activity Explorer URL as the top-bar surfaces panel
  // (https://purview.microsoft.com/activityexplorer). The /dspm/* path
  // does not exist as a public route and silently redirects to the
  // Purview home/start screen. The DSPM-for-AI Activity Explorer view is
  // the same surface — it just opens with the AI filter preselected when
  // entered via the DSPM-for-AI home card, which is the secondary URL
  // we expose if the operator wants to land on the AI Hub first.
  const tenantSeg = v.tenantId ? `?tid=${encodeURIComponent(v.tenantId)}` : '';
  const url = `https://purview.microsoft.com/activityexplorer${tenantSeg}`;
  const stamp = Date.now().toString(36);
  const clip = [
    `User participant: ${v.managerUpn}`,
    `Timestamp (from): ${v.fromIso}`,
    `Timestamp (to):   ${v.toIso}`,
    `App accessed in:  agent365-control-plane`,
    v.agenticUpn ? `Agentic UPN (audit): ${v.agenticUpn}` : '',
    v.agenticAppId ? `Agentic app id (audit): ${v.agenticAppId}` : '',
    `Run id: ${v.runId}`,
    ``,
    `Hint: in Activity Explorer click the filter funnel, choose`,
    `"User" → set to manager UPN above, then "Date" → set the from/to`,
    `range above. Switch to the DSPM-for-AI view from the left nav if`,
    `you only want AI rows.`,
  ].filter(Boolean).join('\n');
  _copyToClipboard(clip).then(ok => {
    const msg = ok
      ? `Purview Activity Explorer opened. Filter values copied — paste them into the User + Date filters.`
      : `Purview opened. Apply filters manually: User=${v.managerUpn || 'manager'} · Timestamp ${v.startedIso} ±5m.`;
    showToast(msg);
  });
  window.open(`${url}${tenantSeg ? '&' : '?'}autopilotCorr=${stamp}`, `autopilotPurview_${stamp}`, 'noopener,noreferrer');
}

function lookupRunInDefender(runId) {
  const run = runs.find(r => r.id === runId);
  if (!run) { showToast('Run not found', 'warn'); return; }
  const v = _runFilterValues(run);
  if (!v) { showToast('No filter values to compute', 'warn'); return; }
  // AADSpnSignInEventsBeta is the Defender table where per-teammate
  // ServiceIdentity sign-ins (and the parent agent SP's sign-ins to
  // Azure OpenAI / Microsoft Graph / Cosmos) land for SDK-hosted agents.
  // CloudAppEvents is NOT populated for our agent in this tenant (no
  // Defender for Cloud Apps connector covers it) and the column we tried
  // to filter on (AccountUpn) does not exist on that table — produces a
  // "Failed to resolve column or scalar expression" semantic error.
  // Filtering by ServicePrincipalId against the set of known agent SP
  // oids (parent + blueprint + per-teammate) within the run's time
  // window is reliable and returns only this run's rows.
  const quotedIds = v.ids.map(id => `"${id}"`).join(', ');
  const kqlLines = [
    `// ===== Group Functions Autopilot · Correlate run ${v.runId} =====`,
    `// Run started ${v.startedIso}. Manager: ${v.managerName || v.managerUpn}`,
    `// Agentic identity: ${v.agenticUpn || '(none)'} / app ${v.agenticAppId || '(none)'}`,
    `let runStart = datetime(${v.fromIso});`,
    `let runEnd   = datetime(${v.toIso});`,
    `let agentIds = dynamic([${quotedIds}]);`,
    `AADSpnSignInEventsBeta`,
    `| where Timestamp between (runStart .. runEnd)`,
    `| where ServicePrincipalId in (agentIds) or ApplicationId in (agentIds) or ServicePrincipalName has "Group Functions Autopilot" or ResourceDisplayName has "Group Functions Autopilot"`,
    `| project-reorder Timestamp, ServicePrincipalName, ServicePrincipalId, ResourceDisplayName, ResourceId, IPAddress, ErrorCode, CorrelationId`,
    `| sort by Timestamp asc`,
  ];
  const kql = kqlLines.join('\n');
  const tid = v.tenantId ? `tid=${encodeURIComponent(v.tenantId)}&` : '';
  const stamp = Date.now().toString(36);
  const url = `https://security.microsoft.com/v2/advanced-hunting?${tid}body=${encodeURIComponent(kql)}&autopilotTab=${stamp}`;
  _copyToClipboard(kql).then(ok => {
    showToast(ok
      ? `Defender opened with AADSpnSignInEventsBeta query (also copied to clipboard).`
      : `Defender opened with query in body= param.`);
  });
  window.open(url, `autopilotDefender_${stamp}`, 'noopener,noreferrer');
}
// ─── end run → portal correlation ────────────────────────────────────────

function renderInstances() {
  const grid = document.getElementById('instanceGrid');
  if (!grid) return;
  // Snapshot any currently-open dropdown selections so we can restore them
  // after the innerHTML rebuild.
  grid.querySelectorAll('select[id^="scenario-"]').forEach(sel => {
    const id = sel.id.slice('scenario-'.length);
    if (sel.value) instanceScenarioSelection[id] = sel.value;
  });
  if (!instances.length) {
    grid.innerHTML = '<div class="run-history-empty">No AI Teammate instances found. Provision one from the blueprint to populate this list.</div>';
    return;
  }
  grid.innerHTML = instances.map(inst => {
    const id = inst.instance_id;
    // Single source of truth for "is this instance running right now?":
    // an active run whose agenticUser.id matches this instance. Same rule
    // the bottom Agentic User Sessions panel already uses, so the two stay
    // in sync and the badge clears the moment the run completes.
    const liveRun = activeRunForInstance(id);
    const state = instanceState[id] || {};
    const running = !!liveRun;
    const lastDelivery = state.lastDelivery || latestDeliveryForInstance(id);
    const stateLabel = running ? (liveRun.status === 'waiting' ? 'Waiting' : 'Running')
      : (lastDelivery && lastDelivery.status === 'sent') ? 'Delivered'
      : state.status === 'failed' ? 'Failed'
      : 'Idle';
    const stateCls = running ? (liveRun.status === 'waiting' ? 'waiting' : 'running')
      : (lastDelivery && lastDelivery.status === 'sent') ? 'delivered'
      : state.status === 'failed' ? 'failed'
      : 'idle';
    const selectedScenario = instanceScenarioSelection[id] || '';
    const skillOptions = (skills || []).map(s => {
      const sel = selectedScenario && selectedScenario === s.name ? ' selected' : '';
      return `<option value="${escapeHtml(s.name)}"${sel}>${escapeHtml(titleCase(s.name))}</option>`;
    }).join('');
    const userLabel = inst.user_display_name || inst.user_upn || '— not resolved —';
    const userClass = inst.user_id ? 'ok' : 'warn';
    const managerLabel = inst.manager_display_name
      ? `${inst.manager_display_name}${inst.manager_email ? ' · ' + inst.manager_email : ''}`
      : '— no manager in directory —';
    const managerClass = inst.manager_id ? 'ok' : 'warn';
    const teamsBits = [];
    // HITL delivery uses Microsoft Graph 1:1 chat by default (via the
    // agent-identity sidecar), falling back to Graph email. No bot install
    // step is required of the manager any more — this label reflects which
    // path will fire when the agent escalates.
    if (inst.notificationChannel === 'graph-chat') {
      teamsBits.push('Teams 1:1 chat via Graph (agent identity) · HITL ready');
    } else if (inst.notificationChannel === 'email') {
      teamsBits.push('Email fallback via Graph · HITL ready (no manager AAD id resolved)');
    } else if (!inst.user_id) {
      teamsBits.push('agent user not resolved');
    } else if (!inst.manager_id && !inst.manager_email) {
      teamsBits.push('no manager in directory — HITL cannot deliver');
    } else {
      teamsBits.push('notification channel not configured');
    }
    const initials = actorInitials(inst.user_display_name || inst.display_name);
    const lastBlock = lastDelivery ? renderInstanceDelivery(lastDelivery, state.lastScenario) : '';
    // Live activity ribbon for active runs owned by this instance
    let liveBlock = '';
    if (liveRun) {
      const elapsed = fmtElapsed(Date.now() - (liveRun.startedAt || Date.now()));
      const last = lastToolForRun(liveRun);
      const isWaiting = liveRun.status === 'waiting';
      let txt;
      let cls;
      if (isWaiting) {
        txt = '⏸ awaiting manager reply in Teams';
        cls = 'waiting';
      } else if (last) {
        txt = `${last.server}/${last.tool}`;
        cls = 'running';
      } else {
        txt = liveRun.runningText || 'starting…';
        cls = 'running';
      }
      liveBlock = `
        <div class="live-strip ${cls}" onclick="event.stopPropagation();openRun(${jsString(liveRun.id)})" title="Open run detail">
          <span class="ls-spin"></span>
          <span class="ls-text">${escapeHtml(txt)}</span>
          <span class="ls-elapsed">${elapsed}</span>
        </div>`;
    }
    const cardClasses = ['instance-card'];
    if (running) cardClasses.push('running', 'clickable');
    const cardClick = running ? ` onclick="openRun(${jsString(liveRun.id)})" title="Open active run"` : '';
    const stateClick = running ? ` onclick="event.stopPropagation();openRun(${jsString(liveRun.id)})" style="cursor:pointer" title="Open active run"` : '';
    return `
      <div class="${cardClasses.join(' ')}" data-instance="${escapeHtml(id)}"${cardClick}>
        <div class="instance-head">
          <span class="instance-avatar">${escapeHtml(initials)}</span>
          <div class="instance-id-block">
            <div class="instance-name">${escapeHtml(brandText(inst.display_name))}</div>
            <div class="instance-sub">${escapeHtml(inst.instance_app_id || id)}</div>
          </div>
          <span class="instance-state ${stateCls}"${stateClick}>${escapeHtml(stateLabel)}</span>
        </div>
        <div class="instance-meta">
          <div class="row"><div class="k">User</div><div class="v ${userClass}">${escapeHtml(userLabel)}</div></div>
          <div class="row"><div class="k">Manager</div><div class="v ${managerClass}">${escapeHtml(managerLabel)}</div></div>
          <div class="row"><div class="k">Notify</div><div class="v">${escapeHtml(teamsBits.join(' · '))}</div></div>
        </div>
        ${liveBlock}
        <div class="instance-launch" onclick="event.stopPropagation()">
          <select id="scenario-${escapeHtml(id)}" onchange="instanceScenarioSelection[${jsString(id)}]=this.value" ${running ? 'disabled' : ''}>
            ${skillOptions || '<option value="">No scenarios available</option>'}
          </select>
          <button onclick="event.stopPropagation();launchInstanceScenario(${jsString(id)})" ${running || !inst.user_id || (governance.disabledInstances || {})[id] ? 'disabled' : ''}>${running ? 'Running…' : ((governance.disabledInstances || {})[id] ? 'Isolated' : 'Run')}</button>
          ${(governance.disabledInstances || {})[id]
            ? `<button class="gov-restore" onclick="event.stopPropagation();restoreInstance(${jsString(id)})" title="Re-enable this agent">Restore</button>`
            : `<button class="gov-isolate" onclick="event.stopPropagation();isolateInstance(${jsString(id)},${jsString(brandText(inst.display_name || id))})" title="Block all future runs from this agent identity">Isolate</button>`}
        </div>
        ${(governance.disabledInstances || {})[id]
          ? `<div class="gov-banner">🛑 Isolated by control plane · ${escapeHtml((governance.disabledInstances || {})[id])}</div>`
          : ''}
        ${lastBlock}
      </div>`;
  }).join('');
}

// Most recent completed-or-error run for this instance, used to render
// "Last: delivered ..." beneath a now-idle card after a run finishes.
function latestDeliveryForInstance(instanceId) {
  if (!instanceId) return null;
  for (const r of runs) {
    if (isActiveStatus(r.status)) continue;
    const aid = r.agenticUser && r.agenticUser.id;
    if (aid === instanceId && r.delivery) return r.delivery;
  }
  return null;
}

function renderInstanceDelivery(delivery, scenario) {
  if (!delivery) return '';
  const status = delivery.status || 'unknown';
  const target = delivery.delivered_to ? ` to ${delivery.delivered_to}` : '';
  const scen = scenario ? ` · ${titleCase(scenario)}` : '';
  let detail = '';
  const channel = delivery.channel ? ` via ${delivery.channel}` : '';
  if (status === 'sent') detail = `delivered${target}${channel}${scen}`;
  else if (status === 'no_recipients') detail = `no manager resolved${scen}`;
  else if (status === 'no_sender') detail = `agent user not resolved${scen}`;
  else if (status === 'no_reference') detail = `notification path unavailable${scen}`;
  else if (status === 'disabled') detail = `notification channel disabled${scen} — ${delivery.reason || ''}`;
  else if (status === 'error') detail = `error${channel}${scen} — ${delivery.reason || ''}`;
  else detail = `${status}${channel}${scen}${delivery.reason ? ' — ' + delivery.reason : ''}`;
  return `<div class="instance-last"><span class="lbl">Last:</span>${escapeHtml(detail)}</div>`;
}

function titleCase(slug) {
  return String(slug || '').replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

async function launchInstanceScenario(instanceId) {
  if (!window.autopilotAuth?.isAuthenticated()) return;
  const select = document.getElementById('scenario-' + instanceId);
  if (!select) return;
  const scenario = select.value;
  if (!scenario) return;
  // Remember the chosen scenario so the dropdown stays put and the post-run
  // "Last: ..." line shows the right scenario name. Running state itself is
  // derived from the runs list (see activeRunForInstance).
  instanceScenarioSelection[instanceId] = scenario;
  instanceState[instanceId] = { lastScenario: scenario };
  renderInstances();
  try {
    const res = await fetch(`/api/agentic-instances/${encodeURIComponent(instanceId)}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario, prompt: scenario.replace(/-/g, ' ') }),
    });
    if (!res.ok) {
      throw new Error(`Run could not start (HTTP ${res.status}).`);
    }
    if (!window.autopilotAuth.isAuthenticated()) return;
    pollInstanceCompletion(instanceId);
  } catch (e) {
    if (!window.autopilotAuth.isAuthenticated()) return;
    instanceState[instanceId] = { status: 'failed', lastError: String(e), lastScenario: scenario };
    renderInstances();
  }
}

function launchAllInstances() {
  const idle = instances.filter(i => (instanceState[i.instance_id] && instanceState[i.instance_id].status || 'idle') !== 'running' && i.user_id);
  if (!idle.length) return;
  if (!confirm(`Launch the same scenario on all ${idle.length} ready instance(s)?`)) return;
  const first = idle[0];
  const select = document.getElementById('scenario-' + first.instance_id);
  const scenario = select && select.value;
  if (!scenario) return;
  for (const inst of idle) {
    const sel = document.getElementById('scenario-' + inst.instance_id);
    if (sel) sel.value = scenario;
    launchInstanceScenario(inst.instance_id);
  }
}

function pollInstanceCompletion(instanceId) {
  // Running-state is derived from the runs list (see activeRunForInstance),
  // so all this poll has to do is capture the final delivery result + clear
  // the scenario hint once the run completes. The global refreshServerRuns
  // tick (every 3.5s) is what actually moves the badge from Running→Idle.
  const start = Date.now();
  const interval = startPolling(async () => {
    try {
      const data = await fetchJson('/api/runs');
      const list = Array.isArray(data) ? data : (data.runs || []);
      // Server-side run lifecycle uses 'complete' (see _publish_run_event
      // 'done' branch in web.py). The 'completed' spelling was a typo that
      // caused successful runs to never match this filter, so the 5-minute
      // timeout below would fire and stamp the instance as 'failed' even
      // though the run had actually succeeded.
      const run = list.find(r => (r.agenticUser && r.agenticUser.id === instanceId) && r.startedAt >= start - 2000 && (r.status === 'complete' || r.status === 'completed' || r.status === 'error'));
      if (run) {
        clearInterval(interval);
        pollingTimers.delete(interval);
        const delivery = run.delivery || null;
        const prior = instanceState[instanceId] || {};
        instanceState[instanceId] = {
          ...prior,
          lastDelivery: delivery,
          status: (run.status === 'error') ? 'failed' : undefined,
          lastScenario: prior.lastScenario,
        };
        renderInstances();
      } else if (Date.now() - start > 5 * 60 * 1000) {
        clearInterval(interval);
        pollingTimers.delete(interval);
        const prior = instanceState[instanceId] || {};
        instanceState[instanceId] = { ...prior, status: 'failed', lastError: 'timed out waiting for run completion' };
        renderInstances();
      }
    } catch (_) { /* ignore */ }
  }, 3000);
}

function renderRunHistory() {
  expireStaleRunsNoSave();
  const count = runs.length;
  const activeCount = runs.filter(run => isActiveStatus(run.status)).length;
  document.getElementById('navRunCount').textContent = activeCount || count || '0';
  document.getElementById('runHistoryCount').textContent = `(${count})`;
  renderAgenticUsers();
  renderInstances();
  renderActiveNow();
  renderFleetTicker();
  const el = document.getElementById('runHistory');
  if (!el) return;
  if (!runs.length) {
    el.innerHTML = '<div class="run-history-empty">No runs yet. Launch a scenario to build the audit trail.</div>';
    return;
  }
  el.innerHTML = runs.slice(0, 12).map(run => {
    const when = new Date(run.startedAt).toLocaleTimeString();
    const tools = Object.keys(run.toolData || {}).length;
    const detail = run.status === 'waiting' ? (run.waitingText ? 'waiting for requester' : 'manager input required') : `${tools} tool call${tools === 1 ? '' : 's'}`;
    const origin = run.source === 'teams-chat'
      ? `Teams chat${run.actor && run.actor.name ? ' · ' + run.actor.name : ''}`
      : (run.source || 'control plane');
    return `
      <div class="run-card ${run.id === activeRunId ? 'active' : ''}" onclick="openRun(${jsString(run.id)})">
        <div class="run-card-title">${escapeHtml(run.title)}</div>
        <div class="run-card-meta"><span>${escapeHtml(when)}</span><span class="run-chip ${escapeHtml(run.status)}">${runStatusLabel(run.status)}</span></div>
        <div class="run-card-meta" style="margin-top:8px"><span>${escapeHtml(detail)}</span><span>${escapeHtml((run.servers || []).join(', '))}</span></div>
        <div class="run-card-meta" style="margin-top:6px"><span>${escapeHtml(origin)}</span><span>${run.serverRun ? 'hosted' : 'local'}</span></div>
      </div>`;
  }).join('');
}

// ─── Live operations dashboard helpers ─────────────────────────────────

function fmtElapsed(ms) {
  if (!ms || ms < 0) return '0s';
  const s = Math.floor(ms / 1000);
  if (s < 60) return s + 's';
  const m = Math.floor(s / 60);
  const r = s % 60;
  return m + 'm' + String(r).padStart(2, '0') + 's';
}

function activeRunForInstance(instanceId) {
  if (!instanceId) return null;
  for (const r of runs) {
    if (!isActiveStatus(r.status)) continue;
    const aid = r.agenticUser && r.agenticUser.id;
    if (aid === instanceId) return r;
  }
  return null;
}

function activeRunForAgenticSession(sessionId) {
  if (!sessionId) return null;
  for (const r of runs) {
    if (!isActiveStatus(r.status)) continue;
    const u = runAgenticUser(r);
    if ((u.id || '') === sessionId) return r;
  }
  return null;
}

function lastToolForRun(run) {
  const entries = Object.entries(run.toolData || {});
  if (!entries.length) return null;
  // Highest index first, fall back to insertion order (object keys preserve insertion).
  entries.sort((a, b) => (b[1].index || 0) - (a[1].index || 0));
  return entries[0][1];
}

function renderActiveNow() {
  const el = document.getElementById('activeNow');
  const countEl = document.getElementById('nowRunningCount');
  if (!el) return;
  const live = runs.filter(r => isActiveStatus(r.status)).sort((a, b) => (b.startedAt || 0) - (a.startedAt || 0));
  if (countEl) countEl.textContent = `(${live.length})`;
  if (!live.length) {
    el.innerHTML = '<div class="empty">No agents are running right now. Launch a scenario on an instance below.</div>';
    return;
  }
  const now = Date.now();
  el.innerHTML = live.map(run => {
    const who = (run.agenticUser && run.agenticUser.name) || (run.actor && run.actor.name) || 'Control Plane';
    const elapsed = fmtElapsed(now - (run.startedAt || now));
    const isWaiting = run.status === 'waiting';
    const last = lastToolForRun(run);
    let activity;
    let activityCls = '';
    if (isWaiting) {
      activity = run.waitingText ? `⏸ ${run.waitingText}` : '⏸ awaiting manager reply in Teams';
      activityCls = 'hitl';
    } else if (last) {
      activity = `→ ${last.server}/${last.tool}`;
    } else {
      activity = run.runningText || 'starting…';
    }
    return `
      <div class="now-card ${isWaiting ? 'waiting' : ''}" onclick="openRun(${jsString(run.id)})">
        <div class="now-head">
          <span class="now-spinner"></span>
          <span class="now-who">${escapeHtml(brandText(who))}</span>
          <span class="now-elapsed">${elapsed}</span>
        </div>
        <div class="now-title">${escapeHtml(run.title || run.skillName || 'Run')}</div>
        <div class="now-activity ${activityCls}">${escapeHtml(activity)}</div>
      </div>`;
  }).join('');
}

function renderFleetTicker() {
  const stream = document.getElementById('fleetStream');
  const pulse = document.getElementById('fleetPulse');
  if (!stream || !pulse) return;
  // Compose a ticker of the last few notable events: tool calls + completions.
  const events = [];
  const now = Date.now();
  for (const r of runs.slice(0, 12)) {
    const who = (r.agenticUser && r.agenticUser.name) || (r.actor && r.actor.name) || 'control-plane';
    const last = lastToolForRun(r);
    const ago = fmtElapsed(now - (r.updatedAt || r.startedAt || now)) + ' ago';
    if (isActiveStatus(r.status) && last) {
      events.push({ when: r.updatedAt || r.startedAt || 0, who, what: `calling ${last.server}/${last.tool}`, ago });
    } else if (r.status === 'waiting') {
      events.push({ when: r.updatedAt || r.startedAt || 0, who, what: r.waitingText ? 'waiting for requester' : 'awaiting manager reply', ago });
    } else if (r.status === 'complete') {
      events.push({ when: r.completedAt || r.updatedAt || 0, who, what: 'completed', ago });
    } else if (r.status === 'error') {
      events.push({ when: r.completedAt || r.updatedAt || 0, who, what: 'error', ago });
    }
  }
  events.sort((a, b) => b.when - a.when);
  const top = events.slice(0, 6);
  const anyActive = runs.some(r => isActiveStatus(r.status));
  pulse.classList.toggle('idle', !anyActive);
  if (!top.length) {
    stream.textContent = 'All instances idle. Launch a scenario to see activity.';
    return;
  }
  stream.innerHTML = top.map(e =>
    `<span class="tk"><span class="who">${escapeHtml(brandText(e.who))}</span> <span class="what">${escapeHtml(e.what)}</span><span class="when">· ${escapeHtml(e.ago)}</span></span>`
  ).join('');
}

function renderIdentity() {
  if (!identity) return;
  const idRows = [
    ['Agent display name', 'Group Functions Autopilot'],
    ['Tenant ID', identity.tenantId],
    ['Agent Identity object ID', identity.agentIdentity && identity.agentIdentity.objectId],
    ['Agent Identity client ID', identity.agentIdentity && identity.agentIdentity.clientId],
    ['Blueprint client ID', identity.blueprint && identity.blueprint.clientId],
    ['Blueprint object ID', identity.blueprint && identity.blueprint.objectId],
    ['Blueprint principal ID', identity.blueprint && identity.blueprint.principalId],
    ['Foundry agent ID', identity.foundry && identity.foundry.agentId],
  ];
  document.getElementById('identityMeta').innerHTML = idRows.map(([label, value]) => `
    <div class="meta-row"><span class="label">${escapeHtml(label)}</span><span class="value">${escapeHtml(brandText(safeText(value)))}</span></div>
  `).join('');

  const obs = identity.observability || {};
  const gateway = identity.gateway || {};
  document.getElementById('runtimePills').innerHTML = [
    `<span class="pill ${identity.enabled ? 'on' : 'warn'}">Agent identity ${identity.enabled ? 'enabled' : 'incomplete'}</span>`,
    `<span class="pill ${gateway.enabled ? 'on' : 'warn'}">AI Gateway ${gateway.enabled ? 'enabled' : 'direct'}</span>`,
    `<span class="pill ${obs.sdkConfigured ? 'on' : 'warn'}">A365 SDK ${obs.sdkConfigured ? 'configured' : 'not configured'}</span>`,
    `<span class="pill ${obs.exporterEnabled ? 'on' : 'warn'}">A365 exporter ${obs.exporterEnabled ? 'on' : 'off'}</span>`,
    `<span class="pill ${obs.payloadsEnabled ? 'on' : 'warn'}">payload logging ${obs.payloadsEnabled ? 'on' : 'off'}</span>`,
  ].join('');

  const runtimeRows = [
    ['LLM backend', identity.llmBackend],
    ['Model', identity.model],
    ['Gateway base URL', gateway.baseUrl],
    ['A365 exporter endpoint', obs.endpoint],
    ['A365 token source', obs.tokenSource],
    ['A365 token scope', obs.tokenScope],
    ['A365 last error', obs.lastError],
    ['OTEL service', obs.serviceName],
    ['Generic OTLP endpoint', obs.otlpEndpointConfigured ? obs.otlpEndpoint : 'not configured'],
    ['Payload max chars', obs.payloadMaxChars],
    ['Agent headers', Object.keys(identity.headers || {}).join(', ')],
    ['Emitted events', (obs.events || []).join(', ')],
  ];
  document.getElementById('runtimeMeta').innerHTML = runtimeRows.map(([label, value]) => `
    <div class="meta-row"><span class="label">${escapeHtml(label)}</span><span class="value">${escapeHtml(brandText(safeText(value)))}</span></div>
  `).join('');
  renderSurfaces();
}

// ── Microsoft 365 governance surfaces — deep links into Entra / Purview / Defender / Admin
function renderSurfaces() {
  const grid = document.getElementById('surfacesGrid');
  if (!grid || !identity) return;
  const tid = identity.tenantId || '';
  const agentAppId = (identity.agentIdentity && identity.agentIdentity.clientId) || '';
  const agentObjId = (identity.agentIdentity && identity.agentIdentity.objectId) || '';
  const blueprintAppId = (identity.blueprint && identity.blueprint.clientId) || '';
  const blueprintObjId = (identity.blueprint && identity.blueprint.objectId) || '';
  const tenantSeg = tid ? encodeURIComponent(tid) : 'common';

  // Entra Enterprise App overview for the agent identity (works with appId in the AAD blade).
  const entraAgentUrl = agentAppId
    ? `https://entra.microsoft.com/${tenantSeg}/#view/Microsoft_AAD_IAM/ManagedAppMenuBlade/~/Overview/objectId/${encodeURIComponent(agentObjId)}/appId/${encodeURIComponent(agentAppId)}`
    : `https://entra.microsoft.com/${tenantSeg}/#view/Microsoft_AAD_IAM/StartboardApplicationsMenuBlade`;
  const entraBlueprintUrl = blueprintAppId
    ? `https://entra.microsoft.com/${tenantSeg}/#view/Microsoft_AAD_IAM/ManagedAppMenuBlade/~/Overview/objectId/${encodeURIComponent(blueprintObjId)}/appId/${encodeURIComponent(blueprintAppId)}`
    : entraAgentUrl;
  const entraAuditUrl = `https://entra.microsoft.com/${tenantSeg}/#view/Microsoft_AAD_IAM/AuditLogsMenuBlade/~/AuditLogs`;
  const entraSignInsUrl = `https://entra.microsoft.com/${tenantSeg}/#view/Microsoft_AAD_IAM/SignInsBlade`;

  // Purview DSPM for AI — agents inventory + activity explorer.
  const purviewAgentsUrl = 'https://purview.microsoft.com/aibrowser/aiagents';
  const purviewActivityUrl = 'https://purview.microsoft.com/activityexplorer';
  const purviewDspmUrl = 'https://purview.microsoft.com/aibrowser/aihub';

  // Defender XDR — agent inventory + posture + threats.
  const defenderAgentsUrl = 'https://security.microsoft.com/agents';
  const defenderPostureUrl = 'https://security.microsoft.com/securityposture';

  // M365 Admin Center — Agent 365 console.
  const m365AgentsUrl = 'https://admin.microsoft.com/Adminportal/Home#/agents';
  const m365AgentMapUrl = 'https://admin.microsoft.com/Adminportal/Home#/copilot/agentmap';

  const surfaces = [
    {
      icon: '🪪', title: 'Entra — Agent identity', portal: 'entra.microsoft.com',
      url: entraAgentUrl,
      purpose: 'Sign-ins, audit, Conditional Access, access reviews — for this agent.',
    },
    {
      icon: '🛡️', title: 'Purview — DSPM for AI', portal: 'purview.microsoft.com',
      url: purviewDspmUrl,
      purpose: 'Sensitivity labels, prompt + response captures, DLP-for-AI.',
    },
    {
      icon: '🛰️', title: 'Defender — Agent security', portal: 'security.microsoft.com',
      url: defenderAgentsUrl,
      purpose: 'Agent posture, threat detection, shadow-AI discovery.',
    },
    {
      icon: '⚙️', title: 'M365 Admin — Agent 365 console', portal: 'admin.microsoft.com',
      url: m365AgentsUrl,
      purpose: 'Lifecycle, agent map, policy templates, governance actions.',
    },
    {
      icon: '🧬', title: 'Entra — Blueprint app (template)', portal: 'entra.microsoft.com',
      url: entraBlueprintUrl,
      purpose: 'Inheritable permissions for every per-user teammate.',
    },
    {
      icon: '📜', title: 'Entra — Directory audit log', portal: 'entra.microsoft.com',
      url: entraAuditUrl,
      purpose: 'Every kill-switch + provisioning event lands here.',
    },
    {
      icon: '🔍', title: 'Purview — Activity Explorer', portal: 'purview.microsoft.com',
      url: purviewActivityUrl,
      purpose: 'Per-run, per-tool I/O ledger with sensitivity classifications.',
    },
  ];

  grid.innerHTML = surfaces.map(s => `
    <a class="surface-card" href="${safeHref(s.url)}" target="_blank" rel="noopener noreferrer" title="Open ${escapeHtml(s.title)} in a new tab">
      <span class="surf-icon">${s.icon}</span>
      <span class="surf-body">
        <div class="surf-title">${escapeHtml(s.title)}</div>
        <div class="surf-portal">${escapeHtml(s.portal)}</div>
        <div class="surf-purpose">${escapeHtml(s.purpose)}</div>
      </span>
      <span class="surf-arrow">↗</span>
    </a>
  `).join('') + `<div class="surfaces-foot">Deep links scoped to this tenant. Sign in once; every tile opens the right blade for agent identity <code style="font-family:inherit">${escapeHtml((agentAppId || '').slice(0, 8))}…</code></div>`;
}

// ── Run scenario ──
async function runScenario(index, resumeText = '', parentRunId = null) {
  if (!window.autopilotAuth?.isAuthenticated()) return;
  const skill = skills[index];
  if (!skill) return;

  const title = skill.name.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  const meta = SCENARIO_META[skill.name];
  const basePrompt = skill.prompt;
  const prompt = resumeText
    ? `${basePrompt}\n\n## Manager response received via simulated Teams\n${resumeText}\n\nContinue the hiring pipeline using this manager-provided context. Make the relevant Workday and ServiceNow tool calls now.`
    : basePrompt;
  const run = {
    id: newRunId(),
    skillIndex: index,
    skillName: skill.name,
    title: resumeText ? `${title} · Manager Reply` : title,
    status: 'running',
    startedAt: Date.now(),
    completedAt: null,
    parentRunId,
    prompt,
    servers: meta && meta.tags ? meta.tags : [],
    toolData: {},
    serverCallCounts: {},
    agentEvents: [],
    loggedEvents: [],
    result: '',
    stats: null,
    humanRequest: null,
    error: '',
  };
  activeRunId = run.id;
  upsertRun(run);
  renderRun(run);
  // Stay on the dashboard so the user can watch the run land in the
  // "Now Running" strip and start more runs in parallel. They can click
  // any active card to drill into the per-run timeline.
  showToast(`Started: ${title}`);

  try {
    const payload = { prompt };
    if (meta && meta.tags && meta.tags.length) payload.servers = meta.tags;
    payload.runId = run.id;
    payload.title = run.title;
    payload.source = 'control-plane';

    const response = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!response.ok || !response.body || !response.headers.get('Content-Type')?.includes('text/event-stream')) {
      throw new Error(`Run could not start (HTTP ${response.status}).`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let eventType = null;

    while (true) {
      const { done, value } = await reader.read();
      if (done || !window.autopilotAuth.isAuthenticated()) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          eventType = line.slice(7).trim();
        } else if (line.startsWith('data: ') && eventType) {
          try {
            const data = JSON.parse(line.slice(6));
            handleRunEvent(run.id, eventType, data);
          } catch (e) { /* ignore */ }
          eventType = null;
        }
      }
    }
  } catch (e) {
    if (!window.autopilotAuth.isAuthenticated()) return;
    run.status = 'error';
    run.error = e.message;
    upsertRun(run);
    if (activeRunId === run.id) renderRun(run);
  }
}

function renderRun(run) {
  if (!run || !window.autopilotAuth?.isAuthenticated()) return;
  activeRunId = run.id;
  document.getElementById('runTitle').textContent = run.title;
  document.getElementById('topbarTitle').textContent = run.title;
  document.getElementById('runStatus').textContent = runStatusLabel(run.status);
  document.getElementById('runStatus').className = `run-status ${run.status === 'complete' ? 'complete' : 'running'}`;
  document.getElementById('runningBar').classList.toggle('hidden', run.status !== 'running');
  document.getElementById('runningText').textContent = run.error ? `Error: ${run.error}` : (run.runningText || 'Starting agent...');
  document.getElementById('runToolCount').textContent = Object.keys(run.toolData || {}).length;
  renderToolTimeline(run);
  renderServersUsed(run);
  renderEventStream('agentEventStream', run.agentEvents || []);
  renderEventStream('loggedEventStream', run.loggedEvents || []);
  document.getElementById('agentEventCount').textContent = (run.agentEvents || []).length;
  document.getElementById('loggedEventCount').textContent = (run.loggedEvents || []).length;

  document.getElementById('resultPanel').style.display = run.result ? '' : 'none';
  // Safe plain-text Markdown fallback: model output is never interpreted as HTML.
  document.getElementById('runResultContent').textContent = run.result || '';

  if (run.stats) {
    document.getElementById('statsPanel').style.display = '';
    document.getElementById('runStatDuration').textContent = run.stats.duration + 's';
    document.getElementById('runStatTurns').textContent = run.stats.turns;
    document.getElementById('runStatCalls').textContent = run.stats.tool_calls;
    document.getElementById('runStatPrompt').textContent = (run.stats.prompt_tokens || 0).toLocaleString();
    document.getElementById('runStatComp').textContent = (run.stats.completion_tokens || 0).toLocaleString();
    document.getElementById('runStatModel').textContent = run.stats.model;
  } else {
    document.getElementById('statsPanel').style.display = 'none';
  }

  renderHumanPanel(run);
  renderRunHistory();
}

function renderToolTimeline(run) {
  const timeline = document.getElementById('toolTimeline');
  const entries = Object.entries(run.toolData || {});
  if (!entries.length) {
    timeline.innerHTML = '<div class="timeline-empty">Waiting for agent to start calling tools...</div>';
    return;
  }
  timeline.innerHTML = entries.map(([id, data]) => {
    const argsPreview = JSON.stringify(data.arguments || {}).slice(0, 80);
    const state = data.result ? 'done' : 'pending';
    return `
      <div class="tool-entry" id="entry-${escapeHtml(id)}" onclick="showToolDetail(${jsString(id)})">
        <span class="entry-dot ${state}"></span>
        <div class="entry-body">
          <div class="entry-header">
            <span class="entry-server">${escapeHtml(data.server)}</span>
            <span class="entry-tool">${escapeHtml(data.tool)}</span>
            <span class="entry-index">#${escapeHtml(data.index || '')}</span>
          </div>
          <div class="entry-preview">${escapeHtml(argsPreview)}</div>
        </div>
      </div>`;
  }).join('');
}

function renderServersUsed(run) {
  const el = document.getElementById('serversUsed');
  const entries = Object.entries(run.serverCallCounts || {}).sort((a, b) => b[1] - a[1]);
  if (!entries.length) {
    el.innerHTML = '<div style="font-size:12px;color:var(--dim);padding:8px 0">No tool calls yet</div>';
    return;
  }
  el.innerHTML = entries.map(([name, count]) => `
    <div class="server-used-item">
      <span class="su-icon">${SERVER_ICONS[name] || '🔌'}</span>
      <span class="su-name">${escapeHtml(name)}</span>
      <span class="su-count">${escapeHtml(count)} call${count !== 1 ? 's' : ''}</span>
    </div>`).join('');
}

function renderHumanPanel(run) {
  const panel = document.getElementById('humanPanel');
  if (!run.humanRequest) {
    panel.style.display = 'none';
    return;
  }
  panel.style.display = '';
  const request = run.humanRequest;
  document.getElementById('humanMessage').textContent = request.message || 'The agent needs manager input before it can continue.';
  document.getElementById('teamsRecipient').textContent = request.recipient || 'Hiring Manager';
  document.getElementById('teamsThread').innerHTML = `
    <div class="teams-message"><div class="sender">Group Functions Autopilot</div>${escapeHtml(request.message || '')}</div>
    ${run.managerReply ? `<div class="teams-message manager"><div class="sender">${escapeHtml(request.recipient || 'Hiring Manager')}</div>${escapeHtml(run.managerReply)}</div>` : ''}`;
  document.getElementById('managerReply').value = run.managerReply || '';
}

function handleRunEvent(runId, type, data) {
  if (!window.autopilotAuth?.isAuthenticated()) return;
  const run = getRun(runId);
  if (!run) return;
  switch (type) {
    case 'status':
      run.runningText = data.message;
      break;

    case 'metadata':
      identity = data;
      renderIdentity();
      break;

    case 'turn':
      addAgentEvent(run, { event: `agent.llm.${data.phase}`, attributes: data });
      run.runningText = data.phase === 'starting'
        ? `Turn ${data.turn}: asking the model with ${data.tools} tools…`
        : `Turn ${data.turn}: model response received (${data.finish_reason || 'complete'})`;
      break;

    case 'agent_event':
      addAgentEvent(run, data);
      break;

    case 'agent365_event':
      addLoggedEvent(run, data);
      break;

    case 'policy_event': {
      // Surface a transient governance toast so audiences see the
      // control plane reacting in real time.
      const srv = data && data.server ? data.server : '';
      const tool = data && data.tool ? data.tool : '';
      const action = data && data.action ? data.action : 'policy';
      const reason = data && data.reason ? data.reason : '';
      const where = [srv, tool].filter(Boolean).join('/');
      showGovernanceToast(`⛔ ${action}${where ? ' · ' + where : ''}${reason ? ' — ' + reason : ''}`);
      // Also log it into the run's agent event timeline for auditors.
      addAgentEvent(run, { event: 'controlplane.policy_event', attributes: data || {} });
      // Refresh governance state so the ledger updates.
      try { refreshGovernance(); } catch (_) {}
      break;
    }

    case 'tool_call': {
      run.toolData[data.id] = { server: data.server, tool: data.tool, arguments: data.arguments, result: null, index: data.index };

      // Track server usage
      run.serverCallCounts[data.server] = (run.serverCallCounts[data.server] || 0) + 1;
      run.runningText = `Calling ${data.server}/${data.tool}…`;
      break;
    }

    case 'tool_result': {
      if (run.toolData[data.id]) {
        run.toolData[data.id].result = data.result;
      }
      break;
    }

    case 'result':
      run.result = data.content || '';
      break;

    case 'human_input_required':
      run.status = 'waiting';
      run.humanRequest = data;
      run.runningText = 'Waiting for manager reply in simulated Teams handoff';
      renderApprovals();
      break;

    case 'hitl_reply':
      if (data && data.reply) {
        run.managerReply = data.reply;
        run.status = 'running';
        renderApprovals();
      }
      break;

    case 'stats':
      run.stats = data;
      break;

    case 'error':
      run.status = 'error';
      run.error = data.message;
      run.runningText = 'Error: ' + data.message;
      break;

    case 'done':
      if (run.status === 'running') run.status = 'complete';
      run.completedAt = Date.now();
      break;
  }
  upsertRun(run);
  if (activeRunId === run.id) renderRun(run);
}

function eventPreview(record) {
  const attrs = record.attributes || record;
  const parts = [];
  if (attrs['mcp.server.name'] || attrs.server) parts.push(attrs['mcp.server.name'] || attrs.server);
  if (attrs['mcp.tool.name'] || attrs.tool) parts.push(attrs['mcp.tool.name'] || attrs.tool);
  if (attrs.phase) parts.push(attrs.phase);
  if (attrs['mcp.tool.call.success'] !== undefined) parts.push(attrs['mcp.tool.call.success'] ? 'success' : 'failed');
  if (attrs['mcp.tool.call.duration_ms']) parts.push(attrs['mcp.tool.call.duration_ms'] + 'ms');
  return parts.join(' · ') || JSON.stringify(attrs).slice(0, 120);
}

function addAgentEvent(run, record) {
  run.agentEvents.unshift(record);
  run.agentEvents = run.agentEvents.slice(0, 40);
}

function addLoggedEvent(run, record) {
  run.loggedEvents.unshift(record);
  run.loggedEvents = run.loggedEvents.slice(0, 40);
}

function renderEventStream(elementId, records) {
  const el = document.getElementById(elementId);
  if (!records.length) {
    el.innerHTML = elementId === 'agentEventStream'
      ? '<div class="event-empty">Waiting for LLM, tool, and telemetry events...</div>'
      : '<div class="event-empty">Tool-call observation records will appear here.</div>';
    return;
  }
  el.innerHTML = records.map((record, index) => {
    const name = record.event || 'event';
    const attrs = record.attributes || record;
    const time = record.timestamp ? new Date(record.timestamp * 1000).toLocaleTimeString() : new Date().toLocaleTimeString();
    return `
      <div class="event-item" onclick="showEventDetail(${jsString(elementId)}, ${index})">
        <div class="event-name">${escapeHtml(name)}</div>
        <div class="event-meta">${escapeHtml(time)}</div>
        <div class="event-preview">${escapeHtml(eventPreview(record))}</div>
      </div>`;
  }).join('');
}

function showEventDetail(elementId, index) {
  const run = getRun();
  if (!run) return;
  const source = elementId === 'agentEventStream' ? run.agentEvents : run.loggedEvents;
  const record = source[index];
  if (!record) return;
  document.getElementById('detailTitle').textContent = record.event || 'Agent event';
  document.getElementById('detailInput').textContent = JSON.stringify(record.attributes || {}, null, 2);
  document.getElementById('detailOutput').textContent = JSON.stringify(record, null, 2);
  document.getElementById('detailOverlay').classList.add('visible');
}

function updateServersUsed() {
  const run = getRun();
  if (!run) return;
  const el = document.getElementById('serversUsed');
  const entries = Object.entries(run.serverCallCounts || {}).sort((a, b) => b[1] - a[1]);
  el.innerHTML = entries.map(([name, count]) => `
    <div class="server-used-item">
      <span class="su-icon">${SERVER_ICONS[name] || '🔌'}</span>
      <span class="su-name">${escapeHtml(name)}</span>
      <span class="su-count">${escapeHtml(count)} call${count !== 1 ? 's' : ''}</span>
    </div>`).join('');
}

// ── Tool detail modal ──
function showToolDetail(id) {
  const run = getRun();
  const d = run && run.toolData[id];
  if (!d) return;
  document.getElementById('detailTitle').textContent = `${d.server} / ${d.tool}`;
  document.getElementById('detailInput').textContent = JSON.stringify(d.arguments, null, 2);
  document.getElementById('detailOutput').textContent = d.result || '(pending…)';
  document.getElementById('detailOverlay').classList.add('visible');
}

function closeDetail() {
  document.getElementById('detailOverlay').classList.remove('visible');
}

// ── Navigation ──
function showDashboard() {
  hideControlRoomViews();
  document.getElementById('dashboardView').classList.remove('hidden');
  document.getElementById('runView').classList.remove('active');
  document.getElementById('approvalsView').classList.remove('active');
  document.getElementById('topbarTitle').textContent = 'Platform';
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('navDashboard').classList.add('active');
  renderRunHistory();
}

function showRunView() {
  const run = getRun();
  if (run) renderRun(run);
  hideControlRoomViews();
  document.getElementById('dashboardView').classList.add('hidden');
  document.getElementById('runView').classList.add('active');
  document.getElementById('approvalsView').classList.remove('active');
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('navRunItem').classList.add('active');
}

function showApprovals() {
  hideControlRoomViews();
  document.getElementById('dashboardView').classList.add('hidden');
  document.getElementById('runView').classList.remove('active');
  document.getElementById('approvalsView').classList.add('active');
  document.getElementById('topbarTitle').textContent = 'Approvals';
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('navApprovals').classList.add('active');
  renderApprovals();
}

function pendingApprovals() {
  return runs.filter(r => r.humanRequest && !r.managerReply && isActiveStatus(r.status));
}
function completedApprovals() {
  return runs
    .filter(r => r.humanRequest && r.managerReply)
    .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
    .slice(0, 25);
}

function renderApprovalsBadge() {
  const n = pendingApprovals().length;
  const badge = document.getElementById('navApprovalsCount');
  if (badge) {
    badge.textContent = String(n);
    badge.style.background = n > 0 ? 'var(--orange-bg)' : '';
    badge.style.color = n > 0 ? 'var(--orange)' : '';
  }
}

function renderApprovals() {
  renderApprovalsBadge();
  const view = document.getElementById('approvalsView');
  if (!view || !view.classList.contains('active')) return;
  const pending = pendingApprovals();
  const completed = completedApprovals();
  document.getElementById('approvalsPendingCount').textContent = `(${pending.length})`;
  document.getElementById('approvalsCompletedCount').textContent = `(${completed.length})`;
  document.getElementById('approvalsSub').textContent = pending.length
    ? `${pending.length} approval${pending.length !== 1 ? 's' : ''} waiting on you. Reply here or via Teams chat — first reply wins.`
    : 'No pending approvals. Teams 1:1 chat replies are also accepted automatically.';

  const pendEl = document.getElementById('approvalsPending');
  if (!pending.length) {
    pendEl.innerHTML = '<div class="approval-empty">No agents are waiting on a human decision right now.</div>';
  } else {
    pendEl.innerHTML = pending.map(r => approvalCardHtml(r, false)).join('');
  }
  const compEl = document.getElementById('approvalsCompleted');
  if (!completed.length) {
    compEl.innerHTML = '<div class="approval-empty">Completed approvals will collapse here after the agent receives your reply.</div>';
  } else {
    compEl.innerHTML = completed.map(r => approvalCardHtml(r, true)).join('');
  }
}

function approvalCardHtml(run, isCompleted) {
  const req = run.humanRequest || {};
  const recipient = req.recipient || run.managerDisplayName || 'Manager';
  const instance = run.instanceLabel || run.instanceDisplayName || run.skillTitle || run.skillId || 'Agent';
  const scenario = run.skillId || run.scenario || '';
  const question = req.message || 'The agent needs manager input before it can continue.';
  const channelRaw = req.channel || req.deliveryChannel || '';
  const channelStatus = req.deliveryStatus || (req.deliveryError ? 'error' : '');
  let channelLabel = '';
  if (channelRaw === 'teams-chat' && channelStatus === 'error') {
    channelLabel = `<span class="ac-channel error">Teams chat delivery failed — reply here</span>`;
  } else if (channelRaw === 'teams-chat') {
    channelLabel = `<span class="ac-channel">Sent via Teams 1:1 chat</span>`;
  } else if (channelRaw) {
    channelLabel = `<span class="ac-channel">Channel: ${escapeHtml(channelRaw)}</span>`;
  }
  const askedAt = req.askedAt ? new Date(req.askedAt).toLocaleString() : '';
  if (isCompleted) {
    return `
      <div class="approval-card completed">
        <div class="ac-head">
          <span class="ac-instance">${escapeHtml(brandText(instance))}</span>
          <span class="ac-scenario">${escapeHtml(scenario)}</span>
          <span class="ac-recipient">${escapeHtml(recipient)}</span>
          ${askedAt ? `<span class="ac-time">asked ${escapeHtml(askedAt)}</span>` : ''}
          <button class="ac-open" onclick="openRun(${jsString(run.id)})">open run</button>
        </div>
        <div class="ac-question"><strong>Agent asked:</strong> ${escapeHtml(question)}</div>
        <div class="ac-reply"><strong>${escapeHtml(recipient)} replied:</strong> ${escapeHtml(run.managerReply)}</div>
      </div>`;
  }
  const safeId = escapeHtml(run.id);
  const jsId = jsString(run.id);
  return `
    <div class="approval-card" data-run-id="${safeId}">
      <div class="ac-head">
        <span class="ac-instance">${escapeHtml(brandText(instance))}</span>
        <span class="ac-scenario">${escapeHtml(scenario)}</span>
        <span class="ac-recipient">→ ${escapeHtml(recipient)}</span>
      </div>
      ${channelLabel}
      <div class="ac-question">${escapeHtml(question)}</div>
      <textarea id="ar-${safeId}" rows="3" placeholder="Reply to the agent here…"></textarea>
      <div class="ac-actions">
        <div class="ac-quick">
          <button onclick="quickApproval(${jsId},'yes')">yes</button>
          <button onclick="quickApproval(${jsId},'no')">no</button>
          <button onclick="quickApproval(${jsId},'hold')">hold</button>
        </div>
        <button class="ac-open" onclick="openRun(${jsId})">open run</button>
        <button class="ac-send" onclick="sendApprovalReply(${jsId})">Send reply &amp; resume</button>
      </div>
    </div>`;
}

function quickApproval(runId, value) {
  const ta = document.getElementById('ar-' + runId);
  if (ta) { ta.value = value; ta.focus(); }
}

function sendApprovalReply(runId) {
  if (!window.autopilotAuth?.isAuthenticated()) return;
  const run = getRun(runId);
  if (!run || !run.humanRequest) return;
  const ta = document.getElementById('ar-' + runId);
  const reply = (ta?.value || '').trim();
  if (!reply) { ta?.focus(); return; }
  const requestId = run.humanRequest.requestId || run.humanRequest.request_id;
  const btn = ta?.closest('.approval-card')?.querySelector('.ac-send');
  if (btn) { btn.disabled = true; btn.textContent = 'Sending…'; }
  // Preferred path: resolve the pending HITL future via the public form endpoint
  // (same path the Teams bot reply handler uses). The agent is awaiting that
  // future and will continue its current turn as soon as we POST a reply.
  const postForm = requestId
    ? fetch(`/api/hitl/${encodeURIComponent(requestId)}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'reply=' + encodeURIComponent(reply),
      }).then(r => ({ ok: r.ok }))
    : Promise.resolve({ ok: false, err: 'no request id' });
  postForm.then(res => {
    if (!window.autopilotAuth.isAuthenticated()) return;
    if (!res.ok) {
      // Fall back to the legacy resume-by-rerun path so the demo still works.
      run.managerReply = reply;
      run.status = 'complete';
      upsertRun(run);
      renderApprovals();
      try { renderDashboard(); } catch (_) {}
      runScenario(run.skillIndex, reply, run.id);
      showToast('Reply sent (legacy resume)', 'warn');
      return;
    }
    // Future was resolved. Clear waiting state locally so the Now Running
    // panel + instance card stop showing "awaiting manager reply". The
    // running run will continue emitting turn/result events over SSE.
    run.managerReply = reply;
    run.status = 'running';
    run.runningText = 'agent resuming with manager reply…';
    upsertRun(run);
    renderApprovals();
    try { renderDashboard(); } catch (_) {}
    // Re-sync run state from the server after a moment in case the SSE
    // stream had dropped (proxies idle out long-waiting connections).
    setTimeout(() => { try { refreshServerRuns(); } catch (_) {} }, 1500);
    setTimeout(() => { try { refreshServerRuns(); } catch (_) {} }, 6000);
    showToast('Reply sent — agent resuming', null);
  }).catch(() => {
    if (window.autopilotAuth.isAuthenticated()) showToast('Reply could not be sent. Please retry.', 'warn');
  }).finally(() => {
    if (btn) { btn.disabled = false; btn.textContent = 'Send reply & resume'; }
  });
}

function openRun(id) {
  const run = getRun(id);
  if (!run) return;
  activeRunId = id;
  renderRun(run);
  showRunView();
}

function showRunHistory() {
  expireStaleRunsNoSave();
  const active = runs.find(run => isActiveStatus(run.status)) || runs[0];
  if (active) openRun(active.id);
  else showDashboard();
}

function sendManagerReply() {
  const run = getRun();
  if (!run || !run.humanRequest) return;
  const reply = document.getElementById('managerReply').value.trim();
  if (!reply) return;
  run.managerReply = reply;
  run.status = 'complete';
  upsertRun(run);
  renderRun(run);
  renderApprovals();
  runScenario(run.skillIndex, reply, run.id);
}

document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDetail(); });

function showToast(message, kind) {
  if (!window.autopilotAuth?.isAuthenticated()) return;
  let host = document.getElementById('toastHost');
  if (!host) {
    host = document.createElement('div');
    host.id = 'toastHost';
    host.className = 'toast-host';
    document.body.appendChild(host);
  }
  const t = document.createElement('div');
  t.className = 'toast' + (kind === 'warn' ? ' warn' : '');
  t.textContent = message;
  host.appendChild(t);
  setTimeout(() => { t.style.transition = 'opacity .25s'; t.style.opacity = '0'; }, 2400);
  setTimeout(() => { t.remove(); }, 2750);
}

// ── Agent 365 value panel ─────────────────────────────────────────
let a365ValueData = null;
const A365_CAT_META = {
  'Entra':              { icon: '🪪', order: 1 },
  'Purview':            { icon: '🛡️', order: 2 },
  'Defender':           { icon: '🛰️', order: 3 },
  'M365 Admin Center':  { icon: '⚙️', order: 4 },
  'Intune':             { icon: '📱', order: 5 },
};

async function loadA365Value() {
  if (!window.autopilotAuth?.isAuthenticated()) return;
  try {
    a365ValueData = await fetchJson('/api/a365-value');
    renderA365Value();
  } catch (e) {
    const sub = document.getElementById('a365ValueSubtitle');
    if (sub && window.autopilotAuth.isAuthenticated()) sub.textContent = 'Capabilities could not be loaded.';
  }
}

function renderA365Value() {
  if (!a365ValueData) return;
  const sum = a365ValueData.statusSummary || {};
  const order = a365ValueData.statusOrder || ['active','configured','manual','roadmap'];
  const labels = a365ValueData.statusLabels || {};
  const total = (a365ValueData.features || []).length;

  const subEl = document.getElementById('a365ValueSubtitle');
  if (subEl) subEl.textContent = total + ' capabilities · ' + (sum.active || 0) + ' active';

  const summaryEl = document.getElementById('a365ValueSummary');
  if (summaryEl) {
    const parts = [`<span class="pill total">${total} total</span>`];
    for (const s of order) {
      const n = sum[s] || 0;
      if (!n) continue;
      parts.push(`<span class="a365-pill ${escapeHtml(s)}">${escapeHtml(n)} ${escapeHtml(labels[s] || s)}</span>`);
    }
    summaryEl.innerHTML = parts.join('');
  }

  const grouped = Object.create(null);
  for (const f of (a365ValueData.features || [])) {
    (grouped[f.category] = grouped[f.category] || []).push(f);
  }
  const cats = Object.keys(grouped).sort((a, b) =>
    ((A365_CAT_META[a] && A365_CAT_META[a].order) || 99) -
    ((A365_CAT_META[b] && A365_CAT_META[b].order) || 99)
  );

  const catsEl = document.getElementById('a365ValueCategories');
  if (!catsEl) return;
  catsEl.innerHTML = cats.map(cat => {
    const meta = A365_CAT_META[cat] || { icon: '•' };
    const feats = grouped[cat];
    const active = feats.filter(f => f.status === 'active').length;
    const isOpen = cat === 'Defender' || cat === 'Purview' || cat === 'Entra';
    return `
      <details class="a365-cat"${isOpen ? ' open' : ''}>
        <summary><span class="cat-icon">${meta.icon}</span>${escapeHtml(cat)}<span class="cat-count">${active}/${feats.length} active</span></summary>
        <div class="a365-feat-list">
          ${feats.map((f, i) => `
            <button class="a365-feat" type="button" onclick="openA365Feature(${jsString(f.id)})">
              <span class="feat-name">${escapeHtml(brandText(f.name))}</span>
              <span class="a365-pill ${escapeHtml(f.status)}">${escapeHtml(labels[f.status] || f.status)}</span>
              <span class="feat-summary">${escapeHtml(brandText(f.summary || ''))}</span>
            </button>
          `).join('')}
        </div>
      </details>
    `;
  }).join('');
}

function openA365Feature(id) {
  if (!a365ValueData) return;
  const f = (a365ValueData.features || []).find(x => x.id === id);
  if (!f) return;
  const labels = a365ValueData.statusLabels || {};
  const meta = A365_CAT_META[f.category] || { icon: '•' };

  const flowIn = (f.flow && f.flow.in) || [];
  const flowOut = (f.flow && f.flow.out) || [];
  const queries = f.queries || [];
  const portals = f.portals || [];
  const wired = f.wired || [];
  const docs = f.docs || [];

  const flowSection = (flowIn.length || flowOut.length) ? `
    <div class="feat-section">
      <h4>Data flow</h4>
      <div class="feat-flow">
        <div class="flow-col">
          <div class="flow-label">What goes in →</div>
          ${flowIn.map(s => `<div class="flow-item">${escapeHtml(brandText(s))}</div>`).join('') || '<div class="flow-item" style="color:var(--muted)">(none)</div>'}
        </div>
        <div class="flow-arrow">→</div>
        <div class="flow-col">
          <div class="flow-label">What comes out</div>
          ${flowOut.map(s => `<div class="flow-item">${escapeHtml(brandText(s))}</div>`).join('') || '<div class="flow-item" style="color:var(--muted)">(none)</div>'}
        </div>
      </div>
    </div>
  ` : '';

  const wiredSection = wired.length ? `
    <div class="feat-section">
      <h4>How this agent wires it</h4>
      <div class="feat-wired">
        ${wired.map(s => `<div>${linkifyCodePaths(escapeHtml(brandText(s)))}</div>`).join('')}
      </div>
    </div>
  ` : '';

  const portalsSection = portals.length ? `
    <div class="feat-section">
      <h4>Where to see it</h4>
      <div class="feat-portals">
        ${portals.map(p => `<a href="${safeHref(p.url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(brandText(p.label))} ↗</a>`).join('')}
      </div>
    </div>
  ` : '';

  const queriesSection = queries.length ? `
    <div class="feat-section">
      <h4>Copy-paste queries</h4>
      ${queries.map((q, idx) => `
        <div class="feat-query">
          <div class="q-head">
            <div><span class="q-label">${escapeHtml(brandText(q.label))}</span><span class="q-portal-tag">${escapeHtml(q.syntax || 'snippet')}</span></div>
            <div class="q-actions">
              <button onclick="copyA365Query(${jsString(f.id)},${idx})">Copy</button>
              ${q.portal === 'defender-hunting' ? `<button onclick="openInDefender(${idx},${jsString(f.id)})">Open in Defender</button>` : ''}
            </div>
          </div>
          <pre id="a365q-${escapeAttr(f.id)}-${idx}">${escapeHtml(q.code)}</pre>
        </div>
      `).join('')}
    </div>
  ` : '';

  const docsSection = docs.length ? `
    <div class="feat-section">
      <h4>Docs in this repo</h4>
      <div class="feat-wired">${docs.map(d => `<div><code>${escapeHtml(d)}</code></div>`).join('')}</div>
    </div>
  ` : '';

  const gaTag = f.ga ? `<span class="tag">GA: ${escapeHtml(f.ga)}</span>` : '';

  const html = `
    <div class="a365-modal" onclick="event.stopPropagation()">
      <button class="modal-close" onclick="closeA365Modal()" title="Close">×</button>
      <h3>${meta.icon} ${escapeHtml(brandText(f.name))} <span class="a365-pill ${escapeHtml(f.status)}">${escapeHtml(labels[f.status] || f.status)}</span></h3>
      <div class="feat-pitch">“${escapeHtml(brandText(f.pitch || f.summary || ''))}”</div>
      <div class="feat-meta">
        <span class="tag">${escapeHtml(f.category)}</span>
        <span class="tag">${escapeHtml(f.pillar)}</span>
        ${gaTag}
      </div>
      ${flowSection}
      ${wiredSection}
      ${portalsSection}
      ${queriesSection}
      ${docsSection}
    </div>
  `;

  const bg = document.getElementById('a365ModalBg');
  bg.innerHTML = html;
  bg.classList.add('open');
  document.addEventListener('keydown', _a365EscClose);
}

function _a365EscClose(ev) {
  if (ev.key === 'Escape') closeA365Modal();
}

function closeA365Modal() {
  const bg = document.getElementById('a365ModalBg');
  if (!bg) return;
  bg.classList.remove('open');
  bg.innerHTML = '';
  document.removeEventListener('keydown', _a365EscClose);
}

function copyA365Query(featureId, idx) {
  const el = document.getElementById('a365q-' + featureId + '-' + idx);
  if (!el) return;
  const text = el.textContent || '';
  navigator.clipboard.writeText(text).then(
    () => showToast('Copied to clipboard'),
    () => showToast('Copy failed — select + Ctrl+C manually')
  );
}

function openInDefender(idx, featureId) {
  const f = (a365ValueData.features || []).find(x => x.id === featureId);
  if (!f) return;
  const q = (f.queries || [])[idx];
  if (!q) return;
  const tid = (a365ValueData.agent && a365ValueData.agent.tenantId) || '';
  // Cache-bust the URL + unique window name so Defender's SPA opens a fresh
  // advanced-hunting tab instead of appending body= onto an existing editor.
  const stamp = Date.now().toString(36);
  const url = `https://security.microsoft.com/v2/advanced-hunting`
    + `?tid=${encodeURIComponent(tid)}`
    + `&body=${encodeURIComponent(q.code)}`
    + `&autopilotTab=${stamp}`;
  window.open(url, 'autopilotDefender_' + stamp, 'noopener,noreferrer');
}

function linkifyCodePaths(s) {
  // Wrap obvious code paths in <code>; leave already-escaped HTML alone.
  return s.replace(/((?:[a-zA-Z_]+\/)+[a-zA-Z0-9_.-]+\.[a-z]{2,4})/g, '<code>$1</code>')
          .replace(/(\/api\/[A-Za-z0-9_\/{}\-]+)/g, '<code>$1</code>');
}

function escapeAttr(s) { return escapeHtml(s); }

// ── Control room: the wall of digital colleagues ─────────────────
let controlRoom = null;
let crFeed = [];
let crRevision = 0;
let crFresh = new Set();
let crFeedFilter = 'all';
let crLastOk = 0;
let activeColleague = null;
let clFeed = [];
let clRevision = 0;
let clFresh = new Set();
let clFeedFilter = 'all';
let clPolicyDraft = null;
const openFeedIds = new Set();

const CR_TAGS = {
  notification: 'NOTICE', email: 'EMAIL', 'teams-in': 'TEAMS', 'teams-out': 'TEAMS', skill: 'SKILL',
  reasoning: 'THINK', tool: 'TOOL', case: 'CASE', issue: 'ISSUE', lifecycle: 'SYSTEM', policy: 'POLICY',
};
const CR_FILTERS = [
  ['all', 'All', null],
  ['conversations', 'Conversations', ['teams-in', 'teams-out', 'email', 'notification']],
  ['work', 'Skills & tools', ['skill', 'tool', 'reasoning', 'case']],
  ['issues', 'Issues', null],
];
const CR_STATE_LABEL = { working: 'WORKING', waiting: 'WAITING', issue: 'ATTENTION', idle: 'IDLE', isolated: 'ISOLATED' };
const CASE_STATUS_TEXT = {
  received: 'Received', creating: 'Creating case', investigating: 'Investigating', opening_private_chat: 'Opening chat',
  updating_case: 'Updating case', delivering_answer: 'Replying', waiting_for_requester: 'Waiting for requester',
  awaiting_confirmation: 'Awaiting confirmation', closing: 'Closing', verifying_close: 'Verifying close',
  notifying_closure: 'Confirming closure', needs_specialist_review: 'Specialist review', closed: 'Closed',
  write_outcome_unknown: 'Needs reconciliation',
};

function crTime(ms) {
  return new Date(ms).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
}

function crAgo(ms) {
  if (!ms) return '';
  const seconds = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `${hours}h ago` : `${Math.round(hours / 24)}d ago`;
}

function crTiles() { return controlRoom ? [...controlRoom.instances, controlRoom.template] : []; }
function crTile(key) { return crTiles().find(tile => tile.key === key) || null; }
function isViewActive(id) { return !!document.getElementById(id)?.classList.contains('active'); }
function instanceLabel(key) {
  const tile = crTile(key);
  return brandText(tile ? tile.name : (key === 'template' ? 'Group Functions Autopilot' : 'AI teammate'));
}

function hideControlRoomViews() {
  document.getElementById('controlRoomView')?.classList.remove('active');
  document.getElementById('colleagueView')?.classList.remove('active');
}

function activateControlRoomView(viewId, title) {
  document.getElementById('dashboardView').classList.add('hidden');
  document.getElementById('runView').classList.remove('active');
  document.getElementById('approvalsView').classList.remove('active');
  for (const id of ['controlRoomView', 'colleagueView']) document.getElementById(id).classList.toggle('active', id === viewId);
  document.querySelectorAll('.nav-item').forEach(n => n.classList.toggle('active', n.id === 'navControlRoom'));
  document.getElementById('topbarTitle').textContent = title;
}

function showControlRoom() {
  activeColleague = null;
  activateControlRoomView('controlRoomView', 'Control Room');
  renderControlRoom();
  renderFleetFeed();
}

async function refreshControlRoom() {
  if (!window.autopilotAuth?.isAuthenticated()) return;
  const data = await fetchJson('/api/control-room');
  if (!data || !Array.isArray(data.instances) || !data.template) throw new Error('The control room is unavailable.');
  controlRoom = data;
  crLastOk = Date.now();
  document.getElementById('navColleagueCount').textContent = String(data.instances.length);
  if (isViewActive('controlRoomView')) renderControlRoom();
  if (isViewActive('colleagueView')) {
    renderColleagueHeader();
    renderColleaguePolicy(false);
  }
}

function mergeFeed(list, incoming, max) {
  const byId = new Map(list.map(event => [event.id, event]));
  const fresh = new Set();
  for (const event of incoming) {
    if (!byId.has(event.id)) fresh.add(event.id);
    byId.set(event.id, event);
  }
  const merged = [...byId.values()].sort((a, b) => (b.at - a.at) || (b.rev - a.rev)).slice(0, max);
  return { merged, fresh };
}

async function refreshFleetFeed() {
  if (!window.autopilotAuth?.isAuthenticated()) return;
  const data = await fetchJson(`/api/control-room/activity?after=${crRevision}&limit=150`);
  if (!data || !Array.isArray(data.events)) return;
  if ((data.revision || 0) < crRevision) {  // The host restarted: start the stream again.
    crRevision = 0;
    crFeed = [];
    return;
  }
  const { merged, fresh } = mergeFeed(crFeed, data.events, 250);
  crFresh = crRevision ? fresh : new Set();
  crFeed = merged;
  crRevision = Math.max(crRevision, data.revision || 0);
  if (isViewActive('controlRoomView') && data.events.length) renderFleetFeed();
}

function presenceSentence(tile) {
  const presence = tile.presence || {};
  const last = tile.summary && tile.summary.last;
  if (presence.state === 'working') return presence.text || `Working on ${presence.title || 'a task'}`;
  if (presence.state === 'waiting') return presence.text || 'Waiting for a reply';
  if (presence.state === 'issue') return `Needs attention: ${presence.text}`;
  if (presence.state === 'isolated') return presence.text || 'Isolated by the control plane.';
  return last ? `Available. Last: ${last.title} (${crAgo(last.at)})` : 'Available. No activity yet.';
}

function renderControlRoom() {
  if (!controlRoom) return;
  const fleet = controlRoom.fleet || {};
  document.getElementById('crAnnunciators').innerHTML = [
    ['working', 'Working'], ['waiting', 'Waiting'], ['issue', 'Attention'], ['idle', 'Idle'], ['isolated', 'Isolated'],
  ].map(([key, label]) => `<div class="cr-ann ${key}${(fleet[key] || 0) > 0 ? ' lit' : ''}"><div class="n">${fleet[key] || 0}</div><div class="l">${label}</div></div>`).join('');
  const tiles = [...controlRoom.instances].sort((a, b) => String(a.name).localeCompare(String(b.name)));
  document.getElementById('crWall').innerHTML = [...tiles, controlRoom.template].map(crTileHtml).join('');
  renderSystems();
}

function crTileHtml(tile) {
  const presence = tile.presence || { state: 'idle' };
  const state = CR_STATE_LABEL[presence.state] ? presence.state : 'idle';
  const summary = tile.summary || {};
  const counts = summary.counts || {};
  const meter = summary.meter || [];
  const peak = Math.max(1, ...meter);
  const bars = meter.map(value => `<span class="${value ? '' : 'zero'}" style="height:${value ? Math.max(14, Math.round(value / peak * 100)) : 8}%"></span>`).join('');
  const isTemplate = tile.kind === 'template';
  const role = isTemplate
    ? `Agent template (blueprint) · ${tile.hiredCount || 0} hired`
    : [tile.manager && tile.manager.name ? `AI teammate · reports to ${tile.manager.name}` : 'AI teammate',
       tile.kind === 'configured' ? 'configured for compliance cases' : ''].filter(Boolean).join(' · ');
  const policy = tile.policy || { skills: [], servers: [] };
  const caps = (policy.servers || []).map(name => `<span class="cr-cap on" title="${escapeHtml(SERVER_LABELS[name] || name)} approved">${escapeHtml(SERVER_ICONS[name] || name)}</span>`).join('')
    + `<span class="cr-cap">${policy.skills.length} skill${policy.skills.length === 1 ? '' : 's'}</span>`
    + (tile.compliance ? `<span class="cr-cap on">${tile.cases.open} open case${tile.cases.open === 1 ? '' : 's'}</span>` : '');
  const callout = isTemplate && !tile.hiredCount
    ? '<div class="cr-callout">No colleagues hired yet. Once licences are applied, hire an instance named “Compliance Partner” from Microsoft 365 admin center → Agents. It lights up here automatically.</div>'
    : '';
  const key = jsString(tile.key);
  return `
    <div class="cr-tile state-${state}${isTemplate ? ' template' : ''}" tabindex="0" role="button" aria-label="${escapeHtml(tile.name)}: ${escapeHtml(CR_STATE_LABEL[state])}"
         onclick="showColleague(${key})" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();showColleague(${key});}">
      <div class="cr-tile-top">
        <span class="cr-lamp"></span>
        <div class="cr-avatar">${escapeHtml(actorInitials(tile.name))}</div>
        <div class="cr-ident"><div class="cr-name">${escapeHtml(brandText(tile.name))}</div><div class="cr-role">${escapeHtml(role)}</div></div>
        <span class="cr-state">${CR_STATE_LABEL[state]}</span>
      </div>
      <div class="cr-now">${escapeHtml(brandText(presenceSentence(tile)))}${presence.since && state !== 'idle' ? ` <span class="since">· ${escapeHtml(crAgo(presence.since))}</span>` : ''}</div>
      <div class="cr-meter" title="Activity in the last hour, five-minute slots">${bars}</div>
      <div class="cr-stats">
        <span>Teams <b>${counts.teams || 0}</b></span><span>Email <b>${counts.email || 0}</b></span>
        <span>Tools <b>${counts.tool || 0}</b></span><span>Skills <b>${counts.skill || 0}</b></span>
        <span class="${counts.issue ? 'bad' : ''}">Issues <b>${counts.issue || 0}</b></span>
      </div>
      <div class="cr-caps">${caps}</div>${callout}
    </div>`;
}

function renderSystems() {
  const rows = (controlRoom.servers || []).map(server => {
    const cls = server.delegated ? 'delegated' : server.connected ? 'on' : 'off';
    const description = server.delegated ? 'Delegated per AI teammate (agentic user)' : server.connected ? 'MCP server connected' : 'Not connected';
    const count = server.delegated ? 'M365' : server.connected ? `${server.tools} tools` : '—';
    return `<div class="cr-sys ${cls}"><span class="dot"></span><div><div class="nm">${escapeHtml(SERVER_LABELS[server.name] || server.name)}</div><div class="ds">${escapeHtml(description)}</div></div><span class="ct">${escapeHtml(count)}</span></div>`;
  });
  rows.push(`<div class="cr-sys ${controlRoom.persistence ? 'on' : 'delegated'}"><span class="dot"></span><div><div class="nm">Activity history</div><div class="ds">${controlRoom.persistence ? 'Kept in Azure Blob storage (managed identity)' : 'Kept in memory on this host'}</div></div><span class="ct"></span></div>`);
  if (identity) {
    rows.push(`<div class="cr-sys on"><span class="dot"></span><div><div class="nm">Reasoning model</div><div class="ds">${escapeHtml(`${identity.model || ''} · ${identity.llmBackend || ''}`)}</div></div><span class="ct"></span></div>`);
  }
  document.getElementById('crSystems').innerHTML = rows.join('');
}

function feedMatches(event, filter) {
  if (filter === 'all') return true;
  if (filter === 'issues') return event.status === 'error' || event.category === 'issue' || event.category === 'policy';
  const match = CR_FILTERS.find(item => item[0] === filter);
  return !match || !match[2] || match[2].includes(event.category);
}

function toggleFeed(element, id) {
  element.classList.toggle('open');
  if (element.classList.contains('open')) openFeedIds.add(id); else openFeedIds.delete(id);
}

function feedItemHtml(event, withWho, fresh) {
  const server = event.server && event.tool ? `<span class="srv">${escapeHtml(event.server)} · ${escapeHtml(event.tool)}</span>` : '';
  const mark = { ok: '✓', error: '!', waiting: '…' }[event.status] || '';
  const detail = event.detail ? `<div class="fe-detail">${escapeHtml(event.detail)}</div>` : '';
  const result = event.result ? `<div class="fe-result">${escapeHtml(event.result)}</div>` : '';
  const link = event.runId && getRun(event.runId)
    ? `<span class="fe-link" onclick="event.stopPropagation();openRun(${jsString(event.runId)})">Open the run</span>` : '';
  const who = withWho ? `<span class="who">${escapeHtml(instanceLabel(event.instance))}</span>` : '';
  return `
    <div class="fe st-${escapeHtml(event.status)} cat-${escapeHtml(event.category)}${fresh ? ' new' : ''}${openFeedIds.has(event.id) ? ' open' : ''}"
         onclick="toggleFeed(this, ${jsString(event.id)})" title="${escapeHtml(new Date(event.at).toLocaleString())}">
      <span class="fe-time">${crTime(event.at)}</span>
      <span class="fe-tag">${CR_TAGS[event.category] || 'EVENT'}</span>
      <div class="fe-body"><div class="fe-title">${who}${escapeHtml(brandText(event.title))}${server}</div>${detail}${result}${link}</div>
      <span class="fe-status">${mark}</span>
    </div>`;
}

function renderFilterChips(id, active, setter) {
  document.getElementById(id).innerHTML = CR_FILTERS.map(([key, label]) =>
    `<button class="cr-chip${key === active ? ' active' : ''}" onclick="${setter}('${key}')">${label}</button>`).join('');
}

function setFleetFilter(key) { crFeedFilter = key; renderFleetFeed(); }
function setColleagueFilter(key) { clFeedFilter = key; renderColleagueFeed(); }

function renderFleetFeed() {
  renderFilterChips('crFeedFilters', crFeedFilter, 'setFleetFilter');
  const items = crFeed.filter(event => feedMatches(event, crFeedFilter)).slice(0, 150);
  document.getElementById('crFleetFeed').innerHTML = items.length
    ? items.map(event => feedItemHtml(event, true, crFresh.has(event.id))).join('')
    : '<div class="cr-empty">Nothing here yet. Activity appears the moment a colleague receives a message, runs a skill or calls a tool.</div>';
}

// ── One colleague's desk ──
async function showColleague(key) {
  activeColleague = key;
  clFeed = [];
  clRevision = 0;
  clFresh = new Set();
  clPolicyDraft = null;
  clFeedFilter = 'all';
  const actions = document.getElementById('clActions');
  actions.dataset.sig = '';
  activateControlRoomView('colleagueView', instanceLabel(key));
  renderColleagueHeader();
  renderColleaguePolicy(true);
  renderColleagueFeed();
  try { await refreshColleagueFeed(); } catch (_) { /* The poller retries. */ }
}

async function refreshColleagueFeed() {
  if (!activeColleague || !isViewActive('colleagueView') || !window.autopilotAuth?.isAuthenticated()) return;
  const key = activeColleague;
  const data = await fetchJson(`/api/control-room/activity?instance=${encodeURIComponent(key)}&after=${clRevision}&limit=300`);
  if (key !== activeColleague || !data || !Array.isArray(data.events)) return;
  if ((data.revision || 0) < clRevision) {
    clRevision = 0;
    clFeed = [];
    return;
  }
  const { merged, fresh } = mergeFeed(clFeed, data.events, 400);
  clFresh = clRevision ? fresh : new Set();
  clFeed = merged;
  clRevision = Math.max(clRevision, data.revision || 0);
  if (data.events.length || !clFeed.length) renderColleagueFeed();
}

function renderColleagueHeader() {
  const tile = crTile(activeColleague);
  if (!tile) {
    document.getElementById('clName').textContent = 'This colleague is not listed right now';
    return;
  }
  const presence = tile.presence || {};
  document.querySelector('#colleagueView .cl-header').className = `cl-header state-${presence.state || 'idle'}`;
  document.getElementById('clAvatar').textContent = actorInitials(tile.name);
  document.getElementById('clName').textContent = brandText(tile.name);
  document.getElementById('topbarTitle').textContent = brandText(tile.name);
  const meta = tile.kind === 'template'
    ? ['Agent template (blueprint)', tile.blueprint && tile.blueprint.clientId ? `app ${tile.blueprint.clientId}` : '', `${tile.hiredCount || 0} hired`]
    : ['AI teammate', tile.user && tile.user.upn, tile.manager && tile.manager.name ? `reports to ${tile.manager.name}` : '',
       tile.kind === 'configured' ? 'configured for compliance cases' : ''];
  document.getElementById('clMeta').textContent = meta.filter(Boolean).join(' · ');
  document.getElementById('clPresence').innerHTML =
    `<span class="cr-state" style="color:var(--lamp);border-color:var(--lamp)">${CR_STATE_LABEL[presence.state] || 'IDLE'}</span>`
    + `<span>${escapeHtml(brandText(presenceSentence(tile)))}</span>`
    + (presence.since && presence.state !== 'idle' ? `<span class="cr-note">since ${escapeHtml(crAgo(presence.since))}</span>` : '');
  renderColleagueActions(tile);
  renderColleagueStats(tile);
  renderColleagueCases(tile);
}

function renderColleagueActions(tile) {
  const element = document.getElementById('clActions');
  const approved = (tile.policy && tile.policy.skills) || [];
  const isolated = tile.presence && tile.presence.state === 'isolated';
  const signature = [tile.key, tile.kind, approved.join(','), isolated].join('|');
  if (element.dataset.sig === signature) return;  // Keep the open skill picker stable while polling.
  const runnable = tile.kind === 'template' || (tile.kind === 'instance' && tile.instanceId);
  const options = approved.map(slug => `<option value="${escapeHtml(slug)}">${escapeHtml(titleCase(slug))}</option>`).join('');
  const governanceId = tile.instanceId || tile.key;
  element.innerHTML = (runnable && approved.length
      ? `<select class="cr-select" id="clSkillSelect" aria-label="Approved skill">${options}</select><button class="cr-button primary" onclick="runColleagueSkill()">Run skill</button>`
      : `<span class="cr-note">${runnable ? 'No approved skills to run.' : 'Runs start once this instance is discovered in Entra.'}</span>`)
    + (tile.kind === 'template' ? '' : isolated
      ? `<button class="cr-button" onclick="restoreColleague(${jsString(governanceId)})">Restore</button>`
      : `<button class="cr-button danger" onclick="isolateColleague(${jsString(governanceId)}, ${jsString(tile.name)})">Isolate</button>`);
  element.dataset.sig = signature;
}

function renderColleagueStats(tile) {
  const counts = (tile.summary && tile.summary.counts) || {};
  const items = [
    ['Teams messages', counts.teams], ['Emails', counts.email], ['Notifications', counts.notification],
    ['Tool calls', counts.tool], ['Skills run', counts.skill], ['Case steps', counts.case], ['Issues', counts.issue, true],
  ];
  document.getElementById('clStats').innerHTML = items.map(([label, value, bad]) =>
    `<div class="cl-stat${bad && value ? ' bad' : ''}"><div class="n">${value || 0}</div><div class="l">${label} · 24h</div></div>`).join('');
}

function renderColleagueCases(tile) {
  const items = (tile.cases && tile.cases.items) || [];
  document.getElementById('clCasesPanel').style.display = tile.compliance || items.length ? '' : 'none';
  document.getElementById('clCases').innerHTML = items.length ? items.map(item => {
    const open = item.status !== 'closed';
    const updated = item.updatedAt ? (item.updatedAt < 1e12 ? item.updatedAt * 1000 : item.updatedAt) : 0;
    return `
      <div class="cl-case" onclick="openCaseRun(${jsString(item.runId || '')})">
        <div class="h"><span class="num">#${escapeHtml(item.caseNumber || 'pending')}</span><span>${escapeHtml(item.subject || 'Compliance case')}</span>
          <span class="st ${open ? 'open' : 'closed'}">${escapeHtml(CASE_STATUS_TEXT[item.status] || item.status || '')}</span></div>
        <div class="s">${item.clarifications || 0} clarification${item.clarifications === 1 ? '' : 's'} · Salesforce ${escapeHtml(item.salesforceStatus || '—')}${updated ? ` · updated ${escapeHtml(crAgo(updated))}` : ''}</div>
      </div>`;
  }).join('') : '<div class="cr-note">No cases yet. An email to this colleague opens one in Salesforce.</div>';
}

function openCaseRun(runId) {
  if (runId && getRun(runId)) openRun(runId);
  else showToast('This case journey appears once this host has recorded activity for it.', 'warn');
}

function renderColleagueIssues() {
  const issues = clFeed.filter(event => event.status === 'error').slice(0, 12);
  document.getElementById('clIssues').innerHTML = issues.length ? issues.map(event => `
    <div class="cl-issue"><div class="w">${crTime(event.at)} · ${escapeHtml(crAgo(event.at))}</div>
      <div class="t">${escapeHtml(brandText(event.title))}</div>
      ${event.result || event.detail ? `<div class="d">${escapeHtml(event.result || event.detail)}</div>` : ''}</div>`).join('')
    : '<div class="cr-note">No issues. Rejected activities, failed tool calls and blocked actions appear here.</div>';
}

function renderColleagueFeed() {
  renderFilterChips('clFeedFilters', clFeedFilter, 'setColleagueFilter');
  const items = clFeed.filter(event => feedMatches(event, clFeedFilter));
  document.getElementById('clFeed').innerHTML = items.length
    ? items.map(event => feedItemHtml(event, false, clFresh.has(event.id))).join('')
    : `<div class="cr-empty">${clFeedFilter === 'all' ? 'No activity recorded for this colleague yet.' : 'Nothing matches this filter.'}</div>`;
  renderColleagueIssues();
}

function renderColleaguePolicy(force) {
  const tile = crTile(activeColleague);
  if (!tile || (!force && clPolicyDraft && clPolicyDraft.dirty)) return;
  const policy = tile.policy || { skills: [], servers: [], source: 'default' };
  const signature = JSON.stringify([tile.key, policy]);
  if (!force && clPolicyDraft && clPolicyDraft.signature === signature) return;
  clPolicyDraft = { key: tile.key, skills: new Set(policy.skills), servers: new Set(policy.servers), dirty: false, signature };
  document.getElementById('clSkills').innerHTML = (controlRoom.skills || []).map(skill => `
    <label class="cl-check"><input type="checkbox" ${clPolicyDraft.skills.has(skill.name) ? 'checked' : ''}
      onchange="togglePolicy('skills', ${jsString(skill.name)}, this.checked)">
      <span>${escapeHtml(skill.title)}<span class="d">${escapeHtml(skill.description || '')}</span></span></label>`).join('');
  document.getElementById('clServers').innerHTML = (controlRoom.servers || []).map(server => `
    <label class="cl-check"><input type="checkbox" ${clPolicyDraft.servers.has(server.name) ? 'checked' : ''}
      onchange="togglePolicy('servers', ${jsString(server.name)}, this.checked)">
      <span>${escapeHtml(SERVER_LABELS[server.name] || server.name)}<span class="d">${escapeHtml(server.delegated ? 'Delegated per instance' : server.connected ? `${server.tools} tools connected` : 'Not connected')}</span></span></label>`).join('');
  const who = String(policy.updatedBy || 'an operator').replace(/\s*\([^)]*\)$/, '');
  document.getElementById('clPolicySource').textContent = policy.source === 'operator'
    ? `(set by ${who})` : policy.source === 'role-preset' ? `(${policy.preset} role preset)` : '(default: everything)';
  document.getElementById('clPolicySave').disabled = true;
}

function togglePolicy(kind, name, checked) {
  if (!clPolicyDraft) return;
  clPolicyDraft[kind][checked ? 'add' : 'delete'](name);
  clPolicyDraft.dirty = true;
  document.getElementById('clPolicySave').disabled = false;
}

async function putColleaguePolicy(body) {
  const key = activeColleague;
  const response = await fetch(`/api/control-room/instances/${encodeURIComponent(key)}/policy`, {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  if (!window.autopilotAuth.isAuthenticated()) return null;
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function saveColleaguePolicy() {
  if (!clPolicyDraft || !activeColleague) return;
  try {
    const result = await putColleaguePolicy({ skills: [...clPolicyDraft.skills], servers: [...clPolicyDraft.servers] });
    if (!result) return;
    showToast(result.persisted === false ? 'Approvals applied (not yet saved to storage).' : 'Approvals saved and enforced.');
    await refreshControlRoom();
    renderColleaguePolicy(true);
    await refreshColleagueFeed();
  } catch (_) {
    showToast('Approvals could not be saved.', 'warn');
  }
}

async function resetColleaguePolicy() {
  if (!activeColleague) return;
  try {
    if (!(await putColleaguePolicy({ reset: true }))) return;
    showToast('Approvals reset to the default for this colleague.');
    await refreshControlRoom();
    renderColleaguePolicy(true);
    await refreshColleagueFeed();
  } catch (_) {
    showToast('Approvals could not be reset.', 'warn');
  }
}

async function runColleagueSkill() {
  const tile = crTile(activeColleague);
  const slug = document.getElementById('clSkillSelect')?.value;
  if (!tile || !slug) return;
  if (tile.kind === 'template') {
    const index = skills.findIndex(skill => skill.name === slug);
    if (index < 0) { showToast('That skill is not loaded on this host.', 'warn'); return; }
    runScenario(index);  // Streams into the run view.
    return;
  }
  try {
    const response = await fetch(`/api/agentic-instances/${encodeURIComponent(tile.instanceId)}/run`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ scenario: slug, prompt: slug.replace(/-/g, ' ') }),
    });
    if (!window.autopilotAuth.isAuthenticated()) return;
    if (response.status === 403) { showToast('That skill is not approved for this colleague.', 'warn'); return; }
    if (response.status === 423) { showToast('This colleague is isolated.', 'warn'); return; }
    if (!response.ok) { showToast(`The skill could not start (HTTP ${response.status}).`, 'warn'); return; }
    showToast(`${titleCase(slug)} started. Watch the activity feed.`);
    setTimeout(() => { refreshColleagueFeed().catch(() => {}); refreshServerRuns().catch(() => {}); }, 900);
  } catch (_) {
    showToast('The skill could not start.', 'warn');
  }
}

async function isolateColleague(id, name) {
  await isolateInstance(id, name);
  await refreshControlRoom().catch(() => {});
  await refreshColleagueFeed().catch(() => {});
}

async function restoreColleague(id) {
  await restoreInstance(id);
  await refreshControlRoom().catch(() => {});
  await refreshColleagueFeed().catch(() => {});
}

function crTick() {
  const clock = document.getElementById('crClock');
  if (clock) clock.textContent = crTime(Date.now());
  document.getElementById('crLive')?.classList.toggle('stale', !crLastOk || Date.now() - crLastOk > 15000);
}

// ── Boot ──
init();

