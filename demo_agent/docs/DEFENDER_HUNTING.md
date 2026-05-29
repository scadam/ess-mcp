# Defender XDR — Hunting playbook for the ESS hosted agent

Audience: security analysts who already use Microsoft Defender XDR Advanced
Hunting (`security.microsoft.com → Hunting → Advanced hunting`) and need
to **see, investigate, and govern** the ESS Workday + ServiceNow Hosted
Demo Agent (the SDK-based Agent 365 workload deployed at
`https://ess-demo-agent.wittysand-460bf1d9.eastus.azurecontainerapps.io`).

The Defender XDR portal already populates several Advanced Hunting tables
about AI agents in the tenant. SDK-hosted agents like this one (where the
team owns the code) light up in those tables *as soon as* the agent runs;
no extra onboarding is required for hunting visibility.

Tenant identifiers you will reuse below:

| Concept | Value |
|---|---|
| Tenant id | `8030d928-e557-4a4c-ae1e-95c1c4125eaa` |
| Parent agent identity (app id) | `ed4046aa-a3ef-4685-a73d-ecda5a4f01da` |
| Blueprint app id | `3f028e66-44cf-4cee-81ee-03ade7717884` |
| Blueprint SP (object id) | `612885df-960e-4900-b065-cc3ff00287bf` |
| Host managed identity (object id) | `92983f30-a70d-4c86-8228-3d0b7f82488f` |
| Per-user teammates (HR / IT / PO) | `eb24d0bc-3806-4186-b459-e956394ca39f` · `c56422b7-a142-461a-a4f7-fbb79f5f9d83` · `2f1961ad-…` |
| ACA replica FQDN | `ess-demo-agent.wittysand-460bf1d9.eastus.azurecontainerapps.io` |

---

## 0. Open Advanced Hunting

`https://security.microsoft.com/v2/advanced-hunting?tid=8030d928-e557-4a4c-ae1e-95c1c4125eaa`

Pre-built launchers for every query in this file are also surfaced on the
control plane right-rail under **Microsoft 365 governance surfaces →
Defender hunting**.

---

## 1. Is our agent in the Defender registry yet? (`AIAgentsInfo`)

> The `AIAgentsInfo` table is Defender XDR's agent registry. Copilot
> Studio, Foundry, and Microsoft 1P agents are auto-discovered. SDK
> agents land here when the Agent 365 SDK calls `register-agent` against
> the A365 fabric (which our `observability.py` does on every
> `start_invoke_scope`). If the row is missing, the agent has not yet
> made a single run, or telemetry hasn't propagated (usually < 30 min).

```kql
AIAgentsInfo
| where AIAgentId in (
    "ed4046aa-a3ef-4685-a73d-ecda5a4f01da",   // parent identity
    "eb24d0bc-3806-4186-b459-e956394ca39f",   // HR teammate
    "c56422b7-a142-461a-a4f7-fbb79f5f9d83"    // IT teammate
  )
   or AIAgentName has "ESS"
   or CreatorAccountUpn has "svasireddy"
| project Timestamp, AIAgentId, AIAgentName, AgentStatus, CreatorAccountUpn,
          OwnerAccountUpns, AgentCreationTime, LastModifiedTime,
          AgentDescription, KnowledgeDetails, AgentActionTriggers
| sort by Timestamp desc
```

Expected: one row per identity, `AgentStatus = "Active"`,
`CreatorAccountUpn = "svasireddy@..."`. If empty, run [§6 below](#6-runtime-side-checks).

---

## 2. Every action our agent (or its teammates) took (`CloudAppEvents`)

`CloudAppEvents` is the universal action log for SaaS / agent activity.
Agent 365 SDK posts a `CloudAppEvents` row for every `invoke_agent` and
every tool call our control plane records.

```kql
CloudAppEvents
| where Timestamp > ago(7d)
| where AccountObjectId in (
    "ed4046aa-a3ef-4685-a73d-ecda5a4f01da",
    "eb24d0bc-3806-4186-b459-e956394ca39f",
    "c56422b7-a142-461a-a4f7-fbb79f5f9d83"
  )
   or AccountDisplayName has "ESS"
   or AppCategory == "Generative AI"
| project Timestamp, ActionType, AccountDisplayName, AccountObjectId,
          Application, ObjectName, ObjectType, IPAddress,
          ActivityType, RawEventData
| sort by Timestamp desc
| take 100
```

Filter rows by `ActionType` to find:
- `AgentRunStarted` / `AgentRunCompleted` — control-plane scenario launches
- `AgentToolInvoked` — every Workday / ServiceNow / human MCP tool call
- `AgentPromptCaptured` — user prompts (Purview policy applies)
- `AgentResponseCaptured` — agent responses with sensitivity labels

---

## 3. Risky agent behaviors (`BehaviorEntities` + `BehaviorInfo`)

```kql
BehaviorEntities
| where EntityType == "AIAgent"
| where EntityId == "ed4046aa-a3ef-4685-a73d-ecda5a4f01da"
   or EntityName startswith "ESS"
| join kind=inner (
    BehaviorInfo
    | project BehaviorId, ActionType, Categories, Severity, Description, Timestamp
  ) on BehaviorId
| project Timestamp, EntityName, ActionType, Severity, Description, Categories
| sort by Timestamp desc
```

Surfaces Defender-detected anomalies: unusual data exfil, atypical tool
mix, off-hours activity, prompt-injection attempts.

---

## 4. Agent-identity sign-ins (`AADSpnSignInEventsBeta` + `AADSignInEventsBeta`)

The agent runs as a **service principal** plus, for HITL flows, as the
**managed identity** of the host. Both should appear cleanly.

```kql
union AADSpnSignInEventsBeta, AADSignInEventsBeta
| where Timestamp > ago(7d)
| where AppId in (
    "ed4046aa-a3ef-4685-a73d-ecda5a4f01da",
    "3f028e66-44cf-4cee-81ee-03ade7717884",   // blueprint
    "eb24d0bc-3806-4186-b459-e956394ca39f",
    "c56422b7-a142-461a-a4f7-fbb79f5f9d83"
  )
| project Timestamp, AppDisplayName, AppId, ServicePrincipalId,
          ServicePrincipalName, ResourceDisplayName, ResourceTenantId,
          IPAddress, ErrorCode, RiskState, RiskLevel, AuthenticationProtocol
| sort by Timestamp desc
| take 200
```

What to look for:
- All `ErrorCode == 0` (clean) — anything else, follow the canonical
  AADSTS troubleshooting flow.
- `RiskState == "atRisk"` rows on the **managed identity** are a strong
  prompt-injection / credential-theft signal.
- `ResourceDisplayName` shows which downstream API the agent hit
  (Microsoft Graph, Work IQ Tools, Agent 365 Tools, Messaging Bot API,
  Workday/ServiceNow gateway).

---

## 5. Alerts and incidents involving the agent (`AlertInfo` + `AlertEvidence`)

```kql
AlertEvidence
| where Timestamp > ago(30d)
| where AccountObjectId in (
    "ed4046aa-a3ef-4685-a73d-ecda5a4f01da",
    "eb24d0bc-3806-4186-b459-e956394ca39f",
    "c56422b7-a142-461a-a4f7-fbb79f5f9d83"
  )
   or AdditionalFields has "ed4046aa-a3ef-4685-a73d-ecda5a4f01da"
| join kind=inner (
    AlertInfo
    | project AlertId, Title, Severity, Category, AttackTechniques, ServiceSource, DetectionSource
  ) on AlertId
| project Timestamp, Title, Severity, Category, AttackTechniques,
          ServiceSource, DetectionSource, EntityType, AccountUpn
| sort by Timestamp desc
```

Useful filters:
- `Category == "AI"` — Defender for AI specific alerts.
- `ServiceSource == "Microsoft Defender for Cloud Apps"` — DSPM-for-AI
  origin.
- `AttackTechniques has "T1059"` — prompt-injection / code execution.

---

## 6. Runtime-side checks

Before assuming Defender is broken, confirm the agent is actually
emitting telemetry:

```powershell
# Public identity payload — confirms A365 SDK loaded + Purview wired
Invoke-RestMethod "https://ess-demo-agent.wittysand-460bf1d9.eastus.azurecontainerapps.io/api/identity" |
    ConvertTo-Json -Depth 5
```

Expected `.observability`:

```json
{
  "sdkConfigured": true,
  "exporterEnabled": true,
  "tokenSource": "managed_identity",
  "events": ["execute_tool", "agent.tool_call.observed", ...],
  "purview": { "enabled": true, "configured": true, ... }
}
```

Then trigger one scenario from the control plane and re-run [§1](#1-is-our-agent-in-the-defender-registry-yet-aiagentsinfo)
in 10–15 minutes.

---

## 7. Hunting → Detection rule (turn a query into an alert)

For any of the queries above, hit **Create detection rule** in Advanced
Hunting. Suggested rules to ship:

| Query basis | Rule name | Severity | Frequency |
|---|---|---|---|
| §3 (BehaviorEntities anomalies) | `ESS agent — unusual behavior` | Medium | Continuous |
| §5 (any `Category == "AI"` alert on our identities) | `ESS agent — AI alert raised` | High | Continuous |
| §4 with `RiskState == "atRisk"` on `ed4046aa-…` | `ESS agent — risky identity sign-in` | High | Continuous |
| §2 with `ActionType == "AgentToolInvoked"` AND `ObjectName has "delete"` | `ESS agent — destructive tool invoked` | High | Continuous |

The destructive-tool rule complements our **control-plane tool deny-list**
(server-side, instant) by adding a tenant-side **detection-plus-alert**
trail for any tool the deny-list missed.

---

## 8. Pre-built Defender deep links

These open Defender XDR with the query pre-loaded — no copy/paste:

- [Advanced Hunting · AIAgentsInfo (our identities)](https://security.microsoft.com/v2/advanced-hunting?tid=8030d928-e557-4a4c-ae1e-95c1c4125eaa&body=AIAgentsInfo%20%7C%20where%20AIAgentId%20in%20(%22ed4046aa-a3ef-4685-a73d-ecda5a4f01da%22%2C%22eb24d0bc-3806-4186-b459-e956394ca39f%22%2C%22c56422b7-a142-461a-a4f7-fbb79f5f9d83%22)%20or%20AIAgentName%20has%20%22ESS%22)
- [Advanced Hunting · CloudAppEvents (our agent, 7 days)](https://security.microsoft.com/v2/advanced-hunting?tid=8030d928-e557-4a4c-ae1e-95c1c4125eaa&body=CloudAppEvents%20%7C%20where%20Timestamp%20%3E%20ago(7d)%20%7C%20where%20AccountObjectId%20%3D%3D%20%22ed4046aa-a3ef-4685-a73d-ecda5a4f01da%22%20or%20AccountDisplayName%20has%20%22ESS%22%20%7C%20sort%20by%20Timestamp%20desc)
- [Advanced Hunting · BehaviorEntities anomalies](https://security.microsoft.com/v2/advanced-hunting?tid=8030d928-e557-4a4c-ae1e-95c1c4125eaa&body=BehaviorEntities%20%7C%20where%20EntityType%20%3D%3D%20%22AIAgent%22%20%7C%20where%20EntityId%20%3D%3D%20%22ed4046aa-a3ef-4685-a73d-ecda5a4f01da%22%20or%20EntityName%20startswith%20%22ESS%22)
- [Advanced Hunting · SP sign-ins (errors)](https://security.microsoft.com/v2/advanced-hunting?tid=8030d928-e557-4a4c-ae1e-95c1c4125eaa&body=AADSpnSignInEventsBeta%20%7C%20where%20AppId%20%3D%3D%20%22ed4046aa-a3ef-4685-a73d-ecda5a4f01da%22%20%7C%20where%20ErrorCode%20%21%3D%200%20%7C%20take%20100)
- [Defender for Cloud Apps · Discover AI agents and assets](https://security.microsoft.com/discoveryReports?tid=8030d928-e557-4a4c-ae1e-95c1c4125eaa)
- [Defender XDR · Settings → AI Agents](https://security.microsoft.com/securitysettings?tid=8030d928-e557-4a4c-ae1e-95c1c4125eaa)
- [Security posture for AI](https://security.microsoft.com/securityposture?tid=8030d928-e557-4a4c-ae1e-95c1c4125eaa)

---

## 9. Onboarding the agent to Defender (one-time portal flow)

For SDK-hosted agents like ours, Defender XDR auto-discovers via two
pathways once the tenant has the right surfaces enabled:

1. **Defender for Cloud Apps "Discover AI agents and assets"**
   `security.microsoft.com → Cloud apps → Discovery → AI agents and assets`
   Toggle **Enable discovery** → wait ~24h. Our outbound `Agent 365 SDK`
   traffic to `agent365.svc.cloud.microsoft` is what MDA fingerprints.

2. **Defender XDR Agents inventory (preview)**
   `security.microsoft.com → Settings → Microsoft Defender XDR → AI Agents (preview)`
   Click **Onboard agent → Other (SDK)** and paste:
   - Tenant: `8030d928-e557-4a4c-ae1e-95c1c4125eaa`
   - Agent app id: `ed4046aa-a3ef-4685-a73d-ecda5a4f01da`
   - Blueprint app id: `3f028e66-44cf-4cee-81ee-03ade7717884`
   - Endpoint: `https://ess-demo-agent.wittysand-460bf1d9.eastus.azurecontainerapps.io`

The script `demo_agent/scripts/register-defender-ai-agent.ps1` automates
the MI permissions, prints the portal steps, and runs verification
hunting queries.

