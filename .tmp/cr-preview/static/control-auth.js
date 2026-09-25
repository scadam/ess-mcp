// Preview-only stub: fakes a signed-in operator and serves mock control-room data.
(() => {
  const now = Date.now();
  const I1 = 'a1b2c3d4-0000-4000-8000-000000000001';
  const I2 = 'a1b2c3d4-0000-4000-8000-000000000002';
  const I3 = 'a1b2c3d4-0000-4000-8000-000000000003';
  const skills = ['compliance-case-resolution', 'cross-system-overview', 'hiring-pipeline', 'incident-triage', 'manager-approval', 'onboarding-audit', 'procurement-to-invoice', 'requisition-approval-triage', 'sprint-readiness', 'team-review'];
  const skillRows = skills.map(name => ({ name, title: name.replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase()), description: 'Skill description for ' + name, servers: [] }));
  const servers = [
    { name: 'workday', connected: true, delegated: false, tools: 46 },
    { name: 'servicenow', connected: true, delegated: false, tools: 39 },
    { name: 'coupa', connected: true, delegated: false, tools: 26 },
    { name: 'salesforce', connected: true, delegated: false, tools: 44 },
    { name: 'workiq', connected: null, delegated: true, tools: null },
  ];
  const summary = (counts, meter, last, lastIssue) => ({ counts, meter, total: 40, last, lastIssue });
  const ev = (id, ago, instance, category, status, title, extra = {}) => ({ id, rev: 1000 - ago, at: now - ago * 1000, instance, category, status, title, detail: '', ...extra });
  const events = [
    ev('e1', 4, I1, 'tool', 'working', 'Read an evidence record through Work IQ', { server: 'workiq', tool: 'fetch', detail: '{"target": "/sites/caldova.../lists/ffb9.../items/3"}' }),
    ev('e2', 9, I1, 'case', 'working', 'Investigating against the approved evidence library', { runId: 'case-1' }),
    ev('e3', 14, I1, 'tool', 'ok', 'Opened a Salesforce case', { server: 'salesforce', tool: 'create_case', result: '{"created": true, "case": {"number": "00001071"}}' }),
    ev('e4', 20, I1, 'email', 'info', 'Received an email from Wonda Howard: “Seabrook disclosure to the Singapore analytics team”', { detail: 'Hi Compliance Partner, can we share the Seabrook data pack with the Singapore analytics team next week?' }),
    ev('e5', 65, I2, 'teams-out', 'waiting', 'Asked Adele Vance for a decision', { detail: 'Approve escalation of INC0012345 to P1?' }),
    ev('e6', 90, I3, 'issue', 'error', 'Couldn\'t connect to the Coupa MCP server', { detail: 'Gave up after 5 attempts.' }),
    ev('e7', 300, I2, 'teams-in', 'info', 'Adele Vance messaged me in our 1:1 chat', { detail: 'Can you triage the open P1 incidents?' }),
    ev('e8', 500, 'template', 'lifecycle', 'ok', 'Came online', { detail: 'Connected MCP servers: workday (46 tools), servicenow (39 tools), coupa (26 tools), salesforce (44 tools).' }),
    ev('e9', 700, I1, 'notification', 'info', 'Wonda Howard @mentioned me in a Word comment', { detail: 'On a document. Document comments are observed; no document skill is approved to act on them.' }),
    ev('e10', 800, I1, 'policy', 'info', 'Admin updated my approved skills and MCP servers', { detail: 'Skills: Compliance Case Resolution. MCP servers: salesforce, workiq.' }),
  ];
  const tile = (key, name, state, text, counts, extra = {}) => ({
    key, kind: 'instance', name, instanceId: key, appId: key,
    user: { name, upn: name.toLowerCase().replace(/ /g, '.') + '@caldova74201480.onmicrosoft.com' },
    manager: { name: extra.manager || 'Wonda Howard' },
    presence: { state, text, since: now - 120000 }, compliance: !!extra.compliance,
    summary: summary(counts, extra.meter || [0, 0, 1, 0, 2, 3, 0, 1, 4, 6, 3, 5], events.find(e => e.instance === key) || null, null),
    policy: extra.policy || { skills: ['compliance-case-resolution'], servers: ['salesforce', 'workiq'], source: 'role-preset', preset: 'Compliance Partner' },
    cases: extra.cases || { open: 0, closed: 0, items: [] }, runs: 2,
  });
  const room = {
    generatedAt: now, revision: 1000, persistence: true, skills: skillRows, servers,
    fleet: { working: 1, waiting: 1, issue: 1, idle: 1, isolated: 0 },
    instances: [
      tile(I1, 'Compliance Partner', 'working', 'Investigating against the approved evidence library', { teams: 6, email: 2, notification: 1, tool: 18, skill: 1, case: 9, issue: 0 }, {
        compliance: true,
        cases: { open: 1, closed: 1, items: [
          { key: 'k1', runId: 'case-1', caseNumber: '00001071', subject: 'Seabrook disclosure to the Singapore analytics team', status: 'investigating', salesforceStatus: 'Working', clarifications: 1, updatedAt: now / 1000 - 30 },
          { key: 'k0', runId: 'case-0', caseNumber: '00001070', subject: 'Supplier NDA coverage for Harbour Analytics', status: 'closed', salesforceStatus: 'Closed', clarifications: 2, updatedAt: now / 1000 - 86000 },
        ] },
      }),
      tile(I2, 'HR Partner', 'waiting', 'Waiting for Adele Vance to approve the escalation in Teams', { teams: 3, email: 0, notification: 0, tool: 7, skill: 2, case: 0, issue: 0 }, {
        manager: 'Adele Vance', meter: [0, 0, 0, 0, 0, 1, 2, 0, 0, 3, 1, 0],
        policy: { skills: ['incident-triage', 'manager-approval'], servers: ['servicenow', 'workday'], source: 'operator', updatedBy: 'Admin (3ef6fe2c)' },
      }),
      tile(I3, 'Procurement Partner', 'issue', "Couldn't connect to the Coupa MCP server", { teams: 0, email: 0, notification: 0, tool: 2, skill: 1, case: 0, issue: 2 }, {
        manager: 'Megan Bowen', meter: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 2, 1],
        policy: { skills: ['procurement-to-invoice'], servers: ['coupa', 'servicenow'], source: 'default' },
      }),
    ],
    template: {
      key: 'template', kind: 'template', name: 'Group Functions Autopilot', hiredCount: 3,
      blueprint: { clientId: '7b3bf810-61f1-46f3-8e9c-89a61a761037' },
      presence: { state: 'idle', text: 'Available' }, compliance: false,
      summary: summary({ teams: 0, email: 0, notification: 0, tool: 0, skill: 0, case: 0, issue: 0 }, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1], events[7], null),
      policy: { skills, servers: ['coupa', 'salesforce', 'servicenow', 'workday', 'workiq'], source: 'default' },
      cases: { open: 0, closed: 0, items: [] }, runs: 0,
    },
  };
  const data = {
    '/api/skills': skills.map(name => ({ name, prompt: '# ' + name })),
    '/api/servers': servers.filter(s => !s.delegated).map(s => ({ name: s.name, url: `https://essmcp-caldova-${s.name}.example/${s.name}/mcp`, tools: s.tools, gateway: false })),
    '/api/identity': { displayName: 'Group Functions Autopilot', model: 'gpt-4.1', llmBackend: 'Azure OpenAI', agentIdentity: {}, blueprint: { clientId: '7b3bf810' }, foundry: {}, gateway: {}, observability: {}, headers: {} },
    '/api/runs': [],
    '/api/agentic-instances': { prefix: 'Compliance Partner', count: 0, instances: [], pendingHitl: [], generatedAt: now },
    '/api/governance': { disabledInstances: {}, toolDenylist: [], audit: [] },
    '/api/a365-value': { features: [], statusSummary: {}, categorySummary: {}, statusOrder: [], statusLabels: {}, agent: {} },
    '/api/control-room': room,
  };
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (input, options) => {
    const url = new URL(typeof input === 'string' ? input : input.url, window.location.origin);
    if (!url.pathname.startsWith('/api/')) return nativeFetch(input, options);
    let body = data[url.pathname];
    if (url.pathname === '/api/control-room/activity') {
      const instance = url.searchParams.get('instance');
      const after = Number(url.searchParams.get('after') || 0);
      body = { revision: 1000, events: events.filter(e => (!instance || e.instance === instance) && e.rev > after) };
    }
    if (body === undefined) body = {};
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
  };
  let authenticated = true;
  window.autopilotAuth = Object.freeze({
    ready: async () => true,
    isAuthenticated: () => authenticated,
    getAppContext: () => ({}),
    showApp: () => {
      document.documentElement.dataset.auth = 'ready';
      document.querySelectorAll('[data-auth-protected]').forEach(element => { element.hidden = false; element.inert = false; });
      const panel = document.getElementById('autopilotAuthPanel');
      if (panel) panel.hidden = true;
      return true;
    },
    showError: text => { document.getElementById('autopilotAuthMessage').textContent = text; },
    clearLegacyRunStorage: () => {},
  });
})();
