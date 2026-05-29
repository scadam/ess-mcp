# Microsoft Agent 365 — Friendly Guide to the SDK and CLI

This guide explains the two tools Microsoft ships for working with Agent 365:

1. The **`a365` CLI** — `Microsoft.Agents.A365.DevTools.Cli`, the .NET tool you install with `dotnet tool install -g`. Sets up Entra apps, permissions, and Azure infrastructure for an agent.
2. The **Observability SDK** — the Python package `microsoft_agents_a365.observability.core`. Sends agent invocation and tool-call telemetry to Microsoft's Agent 365 service so the admin center shows your agent as Managed.

They are separate tools that solve different parts of the same problem. The CLI gets you set up. The SDK gets you observed.

---

## Part 1 — The `a365` CLI

### What it is

A cross-platform command-line tool that automates the Entra ID, Azure, and Microsoft 365 admin center provisioning steps you'd otherwise click through by hand. It's distributed as a .NET global tool.

### Install / update

```powershell
dotnet tool install -g Microsoft.Agents.A365.DevTools.Cli
dotnet tool update  -g Microsoft.Agents.A365.DevTools.Cli
a365 --version
```

### Command map

```
a365
├── setup            ← provision Entra + Azure + permissions
│   ├── requirements   check prerequisites only
│   ├── blueprint      create the Entra blueprint app
│   ├── permissions
│   │   ├── mcp        OAuth2 grants for MCP tools
│   │   └── bot        OAuth2 grants for bot endpoints
│   └── all            do everything in one shot
│
├── develop          ← run local MCP tool servers for dev
├── develop-mcp      ← manage MCP servers in Dataverse
│
├── query-entra      ← read-only inspection of what's configured
│   ├── blueprint-scopes   scopes + consent status on the blueprint
│   └── instance-scopes    scopes + consent status on an agent instance
│
├── cleanup          ← undo what setup created
│   ├── blueprint      delete Entra blueprint app + SP
│   ├── instance       delete agent instance identity + user
│   └── azure          delete Azure infra (App Service, plan, etc.)
│
└── publish          ← package + update manifest for upload to M365 admin center
```

### The two CLI flows you'll use most

#### Flow A — first-time setup (recommended order)

```powershell
a365 setup requirements        # optional, sanity check
a365 setup blueprint           # creates the Entra app + service principal
a365 setup permissions mcp     # grants MCP-related OAuth2 scopes
a365 setup permissions bot     # grants bot-related OAuth2 scopes
```

Or, if you have Global Administrator and want to do it all at once:

```powershell
a365 setup all --agent-name MyAgent
```

If you're not a Global Admin, `setup all` will print exactly what an admin needs to do to finish granting consent.

#### Flow B — inspect / clean up

```powershell
a365 query-entra blueprint-scopes      # what scopes are on the blueprint?
a365 query-entra instance-scopes       # ...and on the instance?

a365 cleanup --agent-name MyAgent -y   # blow it all away
```

### Permissions the CLI needs

| Step | Minimum role |
|---|---|
| `setup blueprint` | Agent ID Developer |
| `setup permissions ...` | Global Administrator |
| `setup all` (infrastructure) | Azure Subscription Contributor + the two above |
| `cleanup` | Same as the corresponding setup step |

### Tip: there's always a newer version
The CLI checks for updates on every run and prints a note at the top. If you see odd behavior, run `dotnet tool update -g Microsoft.Agents.A365.DevTools.Cli` before debugging anything else.

---

## Part 2 — The Observability SDK

### What it is

A Python package that wraps OpenTelemetry. You drop `with InvokeAgentScope(...)` and `with ExecuteToolScope(...)` blocks around your agent code; the SDK turns those into authenticated HTTP POSTs to Microsoft's Agent 365 service. Those traces are what light up the admin center, governance reports, and audit log.

### Install

```bash
pip install microsoft-agents-a365
```

Module path:

```
microsoft_agents_a365.observability.core
```

### The one-diagram picture

```
your code
   │
   ▼
configure(service_name, ..., exporter_options=Agent365ExporterOptions(...))
   │
   ├──► creates a TracerProvider
   │     ├──► EnrichingBatchSpanProcessor → _Agent365Exporter → HTTPS POST
   │     └──► SpanProcessor              (in-process listeners only)
   ▼
with InvokeAgentScope(...) as s:        ← starts a span, tags it
    with ExecuteToolScope(...) as t:    ← starts a child span
        result = call_a_tool()
        t.record_response(result)
    s.record_response(final_answer)
                                        ← spans end, get buffered
   ▼
TracerProvider.force_flush()            ← critical in serverless
   ▼
_Agent365Exporter.export(buffered_spans):
   1. filter spans by gen_ai.operation.name
   2. group by (tenant_id, agent_id)
   3. truncate any span over 250 KB
   4. chunk into HTTP bodies under 900 KB
   5. call token_resolver(agent_id, tenant_id)
   6. POST JSON OTLP envelope
   7. retry on 408/429/5xx
```

### The three environment variables that decide everything

The SDK looks like it's working even when it isn't, because two of its main behaviors are gated by env vars that default to off.

| Variable | If unset | If `true` |
|---|---|---|
| `ENABLE_A365_OBSERVABILITY` (or `ENABLE_OBSERVABILITY`) | Every `with InvokeAgentScope(...)` is a silent no-op. No spans created. | Scopes actually start OpenTelemetry spans. |
| `ENABLE_A365_OBSERVABILITY_EXPORTER` | Falls back to `ConsoleSpanExporter` — you'll see JSON in stdout, but Microsoft never receives anything. | Real `_Agent365Exporter` is wired up. |
| `A365_OBSERVABILITY_DOMAIN_OVERRIDE` | Uses production `agent365.svc.cloud.microsoft`. | Routes to a non-prod ring (Microsoft-internal). |

> **Silent failure #1:** if the SDK seems to do nothing, check these two env vars first. Both must be `true` for production export.

### Step 1: `configure()`

Called once per process at startup:

```python
from microsoft_agents_a365.observability.core import (
    configure, Agent365ExporterOptions,
)

configure(
    service_name="my-agent",
    service_namespace="my-namespace",
    exporter_options=Agent365ExporterOptions(
        token_resolver=my_token_resolver,   # callable: (agent_id, tenant_id) -> bare token
        use_s2s_endpoint=True,              # set True for service-to-service hosts
        cluster_category="prod",
    ),
)
```

What happens inside:
1. **Singleton check** — calling `configure()` twice is harmless; the second call returns immediately.
2. **TracerProvider** is created (or reused if your app already had OpenTelemetry set up).
3. **Exporter is chosen** based on what's in `exporter_options` and whether the env vars are set.
4. **Two span processors** are attached: a batching exporter that ships every 5 seconds, and an in-process listener for enrichers.

> **Gotcha:** if you pass `exporter_options=Agent365ExporterOptions(...)`, the top-level `token_resolver=` argument on `configure()` is **ignored**. Put `token_resolver` *inside* the options object.

### The token resolver contract

Your `token_resolver(agent_id, tenant_id)` is a function the exporter calls before every POST. It must return the **bare access token** — no `"Bearer "` prefix. The exporter prepends `"Bearer "` itself.

```python
def my_token_resolver(agent_id: str, tenant_id: str) -> str | None:
    token = acquire_token_somehow(...)
    return token   # NOT "Bearer " + token
```

> **Silent failure #2:** returning `"Bearer xxx"` produces a header of `"Bearer Bearer xxx"`. The server returns HTTP 400 with an oddly empty tenant id in the error body, which makes you suspect the URL is wrong when it's actually just the prefix.

### Step 2: scopes — wrap your work in `with` blocks

The SDK gives you two main scope classes. Both behave like Python context managers: enter starts an OpenTelemetry span, exit ends it (and records any exception that was raised).

#### `InvokeAgentScope` — wraps an entire agent call

```python
from microsoft_agents_a365.observability.core import (
    InvokeAgentScope, InvokeAgentScopeDetails,
    AgentDetails, Request,
)

with InvokeAgentScope(
    request=Request(session_id="...", content="user prompt"),
    scope_details=InvokeAgentScopeDetails(endpoint=None),
    agent_details=AgentDetails(
        agent_id="...",            # the Entra agent identity app id
        agent_name="MyAgent",
        tenant_id="...",
        agent_blueprint_id="...",  # the Entra blueprint app id
    ),
) as scope:
    answer = run_agent(...)
    scope.record_response(answer)
```

#### `ExecuteToolScope` — wraps each tool call inside the invocation

```python
from microsoft_agents_a365.observability.core import (
    ExecuteToolScope, ToolCallDetails,
)

with ExecuteToolScope(
    request=request,
    details=ToolCallDetails(tool_name="getUser", arguments={...}),
    agent_details=agent_details,
) as tool_scope:
    result = call_tool(...)
    tool_scope.record_response(result)
```

Both scopes automatically tag the span with the attributes Microsoft requires (see §"required attributes" below). You don't need to set them by hand.

### Step 3: export — what actually goes over the wire

After each scope ends, the span sits in the BatchSpanProcessor buffer for up to 5 seconds. When the exporter finally runs, it does seven things in order:

1. **Filter.** Keeps only spans whose `gen_ai.operation.name` is one of `invoke_agent`, `execute_tool`, `chat`, `output_messages`. Stray HTTP/DB spans from other libraries are silently dropped.
2. **Partition.** Groups spans by `(tenant_id, agent_id)`. Each group becomes one HTTP request.
3. **Truncate.** Any span larger than 250 KB has its biggest attributes replaced with `"TRUNCATED"` until it fits.
4. **Chunk.** Each group is split into bodies under ~900 KB (server limit is 1 MB).
5. **Auth.** Calls your `token_resolver(agent_id, tenant_id)` and sets `Authorization: Bearer <token>`.
6. **POST** the JSON OTLP envelope to:
   ```
   https://agent365.svc.cloud.microsoft/observabilityService/
     tenants/{tenant_id}/otlp/agents/{agent_id}/traces?api-version=1
   ```
   (or `/observability/...` without `use_s2s_endpoint=True`)
7. **Retry** on 408/429/5xx — up to 3 attempts with exponential backoff, honoring `Retry-After` on 429.

### What the JSON looks like on the wire

```jsonc
{
  "resourceSpans": [{
    "resource": {
      "attributes": {
        "service.name": "my-agent",
        "service.namespace": "my-namespace"
        // plus anything you set via OTEL_RESOURCE_ATTRIBUTES
      }
    },
    "scopeSpans": [{
      "scope": { "name": "Agent365Sdk" },
      "spans": [
        {
          "traceId": "...", "spanId": "...",
          "name": "invoke_agent MyAgent",
          "attributes": {
            "gen_ai.operation.name": "invoke_agent",
            "microsoft.tenant.id":   "...",
            "gen_ai.agent.id":       "...",
            ...
          }
        }
      ]
    }]
  }]
}
```

### Required span attributes

If any of these is missing, the exporter's filter step silently drops the span.

| Key | What it is | Set automatically? |
|---|---|---|
| `gen_ai.operation.name` | Must be `invoke_agent`, `execute_tool`, `chat`, or `output_messages` | Yes, by the scope classes |
| `microsoft.tenant.id` | Your Entra tenant id | Yes, from `AgentDetails.tenant_id` |
| `gen_ai.agent.id` | The Entra agent identity app id | Yes, from `AgentDetails.agent_id` |
| `microsoft.a365.agent.blueprint.id` | The Entra blueprint app id (recommended) | Yes, from `AgentDetails.agent_blueprint_id` |
| `gen_ai.agent.name` | Display name (optional but recommended) | Yes, from `AgentDetails.agent_name` |

### Serverless / Lambda: the `force_flush` trick

Serverless platforms freeze the container right after your handler returns. The BatchSpanProcessor's 5-second timer never fires, and spans get lost. Always flush in `finally`:

```python
from opentelemetry import trace as _otel_trace

def handler(event, context):
    try:
        # your scopes and work
        return response
    finally:
        _otel_trace.get_tracer_provider().force_flush(timeout_millis=10000)
```

### Other production tips

- **Set `use_s2s_endpoint=True`** for app-only (service-to-service) tokens. The default `/observability/...` route is for user-context tokens and will reject S2S tokens with 403.
- **AWS Lambda preinstalls a logging handler at INFO** — `logging.basicConfig` is a no-op. Use `logging.getLogger().setLevel(logging.DEBUG)` instead.
- **Use `OTEL_RESOURCE_ATTRIBUTES`** to add resource-level context (cloud provider, region, runtime identifiers). These ride at the resource level in the envelope, not on individual spans.

---

## Part 3 — Troubleshooting cheat sheet

| Symptom | Likely cause | Fix |
|---|---|---|
| No log lines after `Creating new TracerProvider` | `ENABLE_A365_OBSERVABILITY` not set | Set env var to `true` |
| Span JSON in stdout but never reaches the service | `ENABLE_A365_OBSERVABILITY_EXPORTER` not set — fell back to console | Set env var to `true` |
| `AADSTS7000215 Invalid client secret` | Blueprint secret expired or stale | Rotate the blueprint secret (Entra), update wherever it's stored, force-restart your process |
| `HTTP 400 EndpointInvalid / TenantIdInvalid` with empty tid | Token resolver returning `"Bearer xxx"` instead of bare token | Strip the prefix; the exporter adds it |
| HTTP 200 `rejectedSpans: 0` but admin center still shows Unmanaged | Server-side reconciler hasn't run yet, or required resource attributes missing | Verify `OTEL_RESOURCE_ATTRIBUTES`, wait 15–60 min for the M365 sync |
| First serverless invocation loses spans | No `force_flush()` before container freeze | Add the `finally` block shown above |
| 403 from the export endpoint | `use_s2s_endpoint=False` on a service-to-service host | Set `use_s2s_endpoint=True` in `Agent365ExporterOptions` |
| CLI commands behave oddly | Outdated CLI version | `dotnet tool update -g Microsoft.Agents.A365.DevTools.Cli` |

---

## Part 4 — File map (SDK source)

Installed under your Python site-packages at `microsoft_agents_a365/observability/core/`:

| File | What's in it |
|---|---|
| `__init__.py` | Public surface — these are the only names you should import |
| `config.py` | `configure()` and the singleton `TelemetryManager` |
| `opentelemetry_scope.py` | Base scope class — env-var gating and span creation live here |
| `invoke_agent_scope.py` | `InvokeAgentScope` — wraps an agent invocation |
| `execute_tool_scope.py` | `ExecuteToolScope` — wraps a tool call |
| `inference_scope.py` | `InferenceScope` — wraps an LLM inference call |
| `constants.py` | Every attribute key the service understands |
| `exporters/agent365_exporter.py` | The HTTPS exporter, with filter/partition/truncate/chunk/retry logic |
| `exporters/agent365_exporter_options.py` | `Agent365ExporterOptions` dataclass |
| `exporters/spectra_exporter_options.py` | `SpectraExporterOptions` for the sidecar (Spectra) alternative |
| `exporters/utils.py` | Filter, partition, truncate, chunk, URL build |
| `exporters/enriching_span_processor.py` | Batching processor with the `register_span_enricher` hook |
| `trace_processor/span_processor.py` | In-process listener fan-out (no export) |
| `models/` | Typed dataclasses: messages, response, caller details, user details |
