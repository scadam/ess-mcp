// Preview-only stub: fakes a signed-in operator and serves mock control-room data.
(() => {
  const now = Date.now();
  const I1 = 'a1b2c3d4-0000-4000-8000-000000000001';
  const I2 = 'a1b2c3d4-0000-4000-8000-000000000002';
  const I3 = 'a1b2c3d4-0000-4000-8000-000000000003';
  const I4 = 'a1b2c3d4-0000-4000-8000-000000000004';
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
    ev('e0', 2, I4, 'tool', 'working', 'Checked the device record in ServiceNow', { server: 'servicenow', tool: 'get_cmdb_ci', runId: 'run-demo-1' }),
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
    fleet: { working: 2, waiting: 1, issue: 1, idle: 0, isolated: 0 },
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
      tile(I4, 'IT Service Agent', 'working', 'Diagnosing INC0010010 for Kian Lambert', { teams: 2, email: 0, notification: 0, tool: 14, skill: 1, case: 6, issue: 0 }, {
        manager: 'Kian Lambert', meter: [0, 0, 0, 0, 0, 0, 1, 0, 2, 5, 7, 4],
        policy: { skills: ['it-second-line'], servers: ['servicenow', 'workiq'], source: 'role-preset', preset: 'IT Service' },
      }),
    ],
    template: {
      key: 'template', kind: 'template', name: 'Group Functions Autopilot', hiredCount: 4,
      blueprint: { clientId: '7b3bf810-61f1-46f3-8e9c-89a61a761037' },
      presence: { state: 'idle', text: 'Available' }, compliance: false,
      summary: summary({ teams: 0, email: 0, notification: 0, tool: 0, skill: 0, case: 0, issue: 0 }, [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1], events[7], null),
      policy: { skills, servers: ['coupa', 'salesforce', 'servicenow', 'workday', 'workiq'], source: 'default' },
      cases: { open: 0, closed: 0, items: [] }, runs: 0,
    },
  };
  const call = (id, server, tool, args, result, start, took, agent = '') => [id, { server, tool, arguments: args, result, index: 0, agent, startedAt: start, endedAt: result === null ? undefined : start + took }];
  const t0 = now - 95000;
  const liveRun = {
    id: 'run-demo-1', title: 'INC0010010 · Laptop battery drains in two hours', status: 'running', source: 'case-desk', serverRun: true,
    actor: { name: 'Kian Lambert' }, agenticUser: { id: I4, name: 'IT Service Agent', actorName: 'Kian Lambert' }, instanceKey: I4,
    startedAt: t0, updatedAt: now - 1500, completedAt: null, runningText: 'Calling servicenow/get_cmdb_ci…',
    prompt: 'INC0010010 was assigned to you. Caller Kian Lambert: "My laptop battery only lasts two hours since the last update. Can you help?" Work the case to resolution and keep the requester informed.',
    toolData: Object.fromEntries([
      call('c1', 'case', 'get_case', { number: 'INC0010010' }, '{"number": "INC0010010", "state": "In Progress", "caller": "Kian Lambert"}', t0 + 4300, 420),
      call('c2', 'servicenow', 'get_incident', { number: 'INC0010010' }, '{"number": "INC0010010", "short_description": "Laptop battery drains in two hours", "priority": "3"}', t0 + 4800, 1300),
      call('c3', 'servicenow', 'search_knowledge', { query: 'battery drain after update' }, '{"results": [{"number": "KB0010042", "title": "Battery drain after BIOS 1.18"}]}', t0 + 11000, 2100, 'ServiceNow researcher'),
      call('c4', 'servicenow', 'list_incidents', { query: 'short_descriptionLIKEbattery' }, '{"count": 3}', t0 + 14000, 1700, 'ServiceNow researcher'),
      call('c5', 'workiq', 'ask', { question: 'Recent messages from Kian about his laptop' }, '{"answer": "Kian mentioned travelling on Thursday."}', t0 + 16500, 5200, 'Work IQ researcher'),
      call('c6', 'servicenow', 'create_request', { item: 'Replacement battery', for: 'kian.lambert' }, '{"number": "REQ0010005"}', t0 + 41000, 2400),
      call('c7', 'case', 'message_requester', { text: 'I have ordered a replacement battery (REQ0010005)…', expects_reply: false }, '{"sent": true}', t0 + 52000, 900),
      call('c8', 'servicenow', 'get_cmdb_ci', { name: 'CALDOVA-LT-0417' }, null, now - 2500, 0),
    ]),
    serverCallCounts: { servicenow: 5, case: 2, workiq: 1 },
    turns: [
      { turn: 1, model: 'gpt-5', tools: 34, start: t0 + 600, end: t0 + 4100, finish: 'tool_calls' },
      { turn: 2, model: 'gpt-5', tools: 34, start: t0 + 6300, end: t0 + 9800, finish: 'tool_calls' },
      { turn: 3, model: 'gpt-5', tools: 34, start: t0 + 33000, end: t0 + 40500, finish: 'tool_calls' },
      { turn: 4, model: 'gpt-5', tools: 34, start: t0 + 44000, end: t0 + 51500, finish: 'tool_calls' },
      { turn: 5, model: 'gpt-5', tools: 34, start: now - 9000, end: now - 2700, finish: 'tool_calls' },
    ],
    subagents: [
      { index: 0, name: 'ServiceNow researcher', status: 'complete', model: 'gpt-5-mini', startedAt: t0 + 10000, completedAt: t0 + 31000, turns: 4, summary: 'Three similar incidents since BIOS 1.18; KB0010042 recommends a battery recalibration or replacement.' },
      { index: 1, name: 'Work IQ researcher', status: 'complete', model: 'gpt-5-mini', startedAt: t0 + 10500, completedAt: t0 + 24000, turns: 2, summary: 'Kian travels on Thursday; a loaner is worth offering.' },
    ],
    guardrails: [
      { point: 'pre_tool_call', decision: 'allow', tool: 'servicenow.get_incident', at: t0 + 4750, version: 7 },
      { point: 'pre_tool_call', decision: 'allow', tool: 'servicenow.search_knowledge', at: t0 + 10950, version: 7 },
      { point: 'pre_tool_call', decision: 'transform', tool: 'workiq.ask', reason: 'scoped to requester', message: 'Question limited to the requester\'s own messages.', at: t0 + 16400, version: 7 },
      { point: 'pre_tool_call', decision: 'allow', tool: 'servicenow.create_request', at: t0 + 40900, version: 7 },
    ],
    scripts: [{ script: 'battery_health.py', kind: 'script', exitCode: 0, durationMs: 1800, files: ['out/battery.md'], at: t0 + 32000 }],
    agentEvents: [{ event: 'agent.llm.completed', timestamp: (now - 2700) / 1000, attributes: { turn: 5, model: 'gpt-5', finish_reason: 'tool_calls' } }],
    loggedEvents: [{ event: 'agent.tool.call', attributes: { 'mcp.server.name': 'servicenow', 'mcp.tool.name': 'create_request', 'mcp.tool.call.success': true, 'mcp.tool.call.duration_ms': 2400 } }],
    result: '', stats: { turns: 5, tool_calls: 8, prompt_tokens: 61240, completion_tokens: 2210, models: { 'gpt-5': { roles: ['orchestrator'], calls: 5, prompt_tokens: 52000, completion_tokens: 1800 }, 'gpt-5-mini': { roles: ['subagent'], calls: 6, prompt_tokens: 9240, completion_tokens: 410 } } },
  };
  const d0 = now - 9.5 * 60000;
  const doneRun = {
    id: 'run-demo-2', title: 'INC0010011 · Locked out of my account', status: 'complete', source: 'case-desk', serverRun: true,
    actor: { name: 'Aisha West' }, agenticUser: { id: I4, name: 'IT Service Agent', actorName: 'Aisha West' }, instanceKey: I4,
    startedAt: d0, updatedAt: d0 + 455000, completedAt: d0 + 455000,
    prompt: 'INC0010011 was assigned to you. Caller Aisha West: "I am locked out of my account."',
    toolData: Object.fromEntries([
      call('d1', 'servicenow', 'get_user', { user_name: 'aisha.west' }, '{"locked_out": true}', d0 + 3000, 1100),
      call('d2', 'case', 'message_requester', { text: 'Can you confirm the last four digits of your employee ID?', expects_reply: true }, '{"sent": true}', d0 + 12000, 800),
      call('d3', 'case', 'wait', { minutes: 30 }, '{"woke": "requester replied"}', d0 + 14000, 600),
      call('d4', 'servicenow', 'unlock_user', { user_name: 'aisha.west' }, '{"locked_out": false}', d0 + 425000, 1500),
      call('d5', 'servicenow', 'resolve_incident', { number: 'INC0010011', close_notes: 'Account unlocked after identity check.' }, '{"state": "Resolved"}', d0 + 440000, 1900),
    ]),
    serverCallCounts: { servicenow: 3, case: 2 },
    turns: [
      { turn: 1, model: 'gpt-5', tools: 34, start: d0 + 500, end: d0 + 2800, finish: 'tool_calls' },
      { turn: 2, model: 'gpt-5', tools: 34, start: d0 + 4300, end: d0 + 11500, finish: 'tool_calls' },
      { turn: 1, model: 'gpt-5', tools: 34, start: d0 + 418000, end: d0 + 424000, finish: 'tool_calls' },
      { turn: 2, model: 'gpt-5', tools: 34, start: d0 + 427000, end: d0 + 439000, finish: 'tool_calls' },
      { turn: 3, model: 'gpt-5', tools: 34, start: d0 + 442500, end: d0 + 454000, finish: 'stop' },
    ],
    guardrails: [{ point: 'pre_tool_call', decision: 'escalate', tool: 'servicenow.unlock_user', reason: 'identity check', message: 'Unlock needs a confirmed identity.', at: d0 + 424500, version: 7 }],
    agentEvents: [], loggedEvents: [],
    result: 'Unlocked Aisha West\'s account after she confirmed her employee ID, and resolved INC0010011.\n\nShe can sign in again now; I asked her to change her password at first sign-in.',
    stats: { duration: 455, turns: 5, tool_calls: 5, prompt_tokens: 38110, completion_tokens: 1420, models: { 'gpt-5': { roles: ['orchestrator'], calls: 5, prompt_tokens: 38110, completion_tokens: 1420 } } },
  };
  const data = {
    '/api/skills': skills.map(name => ({ name, prompt: '# ' + name })),
    '/api/servers': servers.filter(s => !s.delegated).map(s => ({ name: s.name, url: `https://essmcp-caldova-${s.name}.example/${s.name}/mcp`, tools: s.tools, gateway: false })),
    '/api/identity': { displayName: 'Group Functions Autopilot', model: 'gpt-5', llmBackend: 'Azure OpenAI', tenantId: '00000000-0000-4000-8000-00000000aaaa', modelRoutes: { tiers: { fast: 'gpt-5-mini', deep: 'gpt-5' } }, agentIdentity: { objectId: '00000000-0000-4000-8000-00000000bbbb', clientId: '00000000-0000-4000-8000-00000000cccc' }, blueprint: { clientId: '7b3bf810-61f1-46f3-8e9c-89a61a761037' }, foundry: {}, gateway: {}, observability: { sdkConfigured: true, exporterEnabled: true, serviceName: 'group-functions-autopilot', events: ['agent.llm', 'agent.tool'] }, headers: {} },
    '/api/runs': [liveRun, doneRun],
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
      const context = document.getElementById('autopilotContext');
      if (context) { context.textContent = 'Scott Adams'; context.title = 'Scott Adams · Browser · Tenant 17371818-07cb-47f2-9ca3-18f96f0125d7'; }
      return true;
    },
    showError: text => { document.getElementById('autopilotAuthMessage').textContent = text; },
    clearLegacyRunStorage: () => {},
  });
})();
