# WPP — Agent 365 demo script (cross-portal edition)

**Story:** *"Your agents are people now. Use the same Microsoft 365 tools you already use to secure and govern people — that's how you scale."*

**Duration:** 30 min demo + 10 min Q&A
**Tenant:** `M365CPI81302533.onmicrosoft.com` (id `8030d928-e557-4a4c-ae1e-95c1c4125eaa`)
**Surfaces we will switch between live:**

| # | Portal | Why it matters |
| - | ------ | -------------- |
| 0 | **Custom control plane** `https://ess-demo-agent.wittysand-460bf1d9.eastus.azurecontainerapps.io/control-plane` | The pane of glass we built **for the demo** — not a product. Proves the runtime emits first-class signals. |
| 1 | **Microsoft Entra admin center** `entra.microsoft.com` | Agent is a directory object with sign-ins, audit log, CA, access reviews. |
| 2 | **Microsoft Purview** `purview.microsoft.com` (AI Hub / DSPM-for-AI) | Sensitivity labels, prompts/responses captures, DLP-for-AI, communication compliance. |
| 3 | **Microsoft Defender** `security.microsoft.com` | Agent security posture, threat detection, shadow-AI discovery. |
| 4 | **M365 Admin Center → Agents** `admin.microsoft.com` | Lifecycle, agent map, per-tenant policy, license + provisioning. |

> Keep all five tabs pinned in the demo browser. Sign in as a tenant admin before the audience joins.

The control plane has a **Microsoft 365 governance surfaces** card in the right rail with one-click deep links into each portal. Use it as your navigation.

---

## 0. Pre-flight checklist (15 min before audience joins)

1. Sign into all five tabs as a Global Admin in the demo tenant.
2. In Entra → Identity → Applications → Enterprise applications, search `ESS` and confirm three things appear:
   - `ESS Workday ServiceNow Hosted Demo Agent` (agent identity `ed4046aa-…`)
   - `ESS AI Teammate Template` (blueprint `3f028e66-…`)
   - At least one `… AI Teammate for <user>` per-user teammate.
3. In Purview → AI Hub → "AI agents" panel, confirm the agent shows up (if not, run `demo_agent/scripts/setup-purview-dspm.ps1` and complete the manual portal step).
4. In Defender XDR, confirm `Agents` blade is visible (preview must be enabled in the tenant).
5. In M365 Admin → Agents, confirm the agent + teammates are listed.
6. In the control plane:
   - Click **Restore** on any isolated instance.
   - **Clear** the Tool deny-list.
   - Verify the **Microsoft 365 governance surfaces** card renders all four cards with working links.
7. Pre-stage two scenarios:
   - `Hiring pipeline` — will trigger Purview SSN/salary redaction.
   - `Workday terminate employee` — will be blocked by the deny-list later.

---

## 1. Open with the message, not the demo (2 min)

> "Every CISO I've talked to in the last six months has the same question: *'How do I govern a workforce of agents the same way I govern my workforce of people?'* The answer Microsoft is shipping is **Agent 365**: agents become first-class identities in your existing Entra / Purview / Defender / Admin Center stack. The same tools, the same operators, the same playbooks. We're not going to ask you to learn a new console. We're going to show you how the consoles you already pay for now see your agents."

Show the architecture image (the one we walked through). Trace the flow with your finger:
- Blueprint App → Per-user agent instances (panel 1).
- MI → FIC → blueprint → user_fic delegated token (panel 2).
- MAF runtime calls MCP tools and Teams as the *user* (panels 3 + 4a + 4b).
- **Panel 5 is the whole point** — everything that happens at runtime surfaces in Entra / Purview / Defender / Admin Center.

> "That panel 5 is what we're going to spend most of this demo in."

Switch to the control-plane tab.

---

## 2. Identity foundation — Entra (5 min)

### 2a. In our control plane (45s)
Right rail → **Entra Agent Identity** card. Read the IDs aloud:
- Tenant `8030d928-…`
- Blueprint app `3f028e66-…` (the *template* — like an HR role definition).
- Agent identity `ed4046aa-…` (the *agent* itself).
- Per-user teammates (HR, IT, PO) — each a distinct child agent identity.

> "All of these are real Entra directory objects. Let me prove it."

### 2b. Switch to Entra (3.5 min)
Click the **🪪 Microsoft Entra — Agent identity** card in the right rail. New tab opens directly at the agent's Enterprise App overview in `entra.microsoft.com`.

Walk through the left nav of the Enterprise App blade:
1. **Overview** — point at Application ID = `ed4046aa-…`. "This is the same shape as a service principal — but tagged as an *Agent Identity*."
2. **Sign-in logs** — show entries. Filter by user → you'll see entries where this agent signed in *as Hina's HR teammate*. "Your existing SOC alerting on anomalous sign-ins covers agents on day one."
3. **Audit logs** (top-level Entra → Identity → Monitoring → Audit logs) — show the recent `Update service principal` entries. "Every config change is in the standard Entra audit log."
4. **Conditional Access** (top-level → Identity → Protect & secure → Conditional Access) — filter policies by this app. Talk about: "You can require MFA for the *human* underneath, restrict the agent to compliant devices, geo-block, require a session lifetime — same policies you already author."
5. **Access reviews** — "Treat agent identities like a privileged role: quarterly access reviews, owner attestation, the works."
6. Click back to the **Blueprint app** sub-link in our right-rail card. Show that the blueprint has the *inheritable* permission set. "Provisioning a teammate is `New-User` for agents — issued from a template, inheriting permissions."

> "Bottom line: zero new tools for your identity team. They use the same blade they use for every other Enterprise App."

---

## 3. Tool governance — control plane → Defender story (5 min)

### 3a. In our control plane (3 min)
Right rail → **Control Plane Enforcement** card.

> "Now imagine a Workday vulnerability dropped overnight. You need to disable termination tools across every Agent 365 agent in the tenant — *right now*, not next sprint."

1. Paste into the **Tool deny-list** textarea:
   ```
   workday.terminate_*
   ```
2. Click **Apply deny-list**. The chip strip lights up, the audit ledger shows the new rule with actor + timestamp.
3. From the skill library, launch `Workday terminate employee`.
4. Watch the run timeline. The agent attempts the tool, gets back:
   ```
   [BLOCKED BY CONTROL PLANE POLICY: tool blocked by control plane policy (workday.terminate_*)]
   ```
   and a toast pops bottom-right: **⛔ blocked-by-control-plane · workday/terminate_user**.

> "Enforced by the runtime — not by prompt engineering. The LLM cannot talk the host out of refusing. Every block is timestamped, actor-attributed, rule-attributed, and run-attributed."

### 3b. Switch to Defender (2 min)
Click the **🛰️ Microsoft Defender — Agent security** card.

In Defender XDR → Assets → Agents:
- Find the agent. Show the **posture** view: tool inventory, abnormal call patterns, identity provenance.
- Show **threat detection** examples (or where they will appear): "Defender's signal is the same XDR data lake your SOC already lives in. Agent-related alerts route through your existing playbooks."
- Show the **Discovery of shadow AI on endpoints** view: "When developers spin up agents outside Agent 365, this is where you see it."

> "Your SOC didn't have to learn anything new. The same investigations panel that handled a compromised user yesterday handles a compromised agent today."

---

## 4. Compliance controls — control plane → Purview (5 min)

### 4a. In our control plane (2 min)
Run the `Hiring pipeline` scenario.

The scenario calls Workday + a candidate-tracking tool that returns SSNs and salaries.
- Tool result chips show **SSN**, **Salary**, **Address** with sensitivity labels.
- A `policy_event` arrives: **⛔ redacted · workday/get_candidate — Sensitive PII (SSN, comp)**.
- The redacted result is what the LLM sees — the raw value never reaches the model.

Open the **Logged Tool Observations** panel: each row shows the classifier verdict, the label, the redactions applied.

> "Sensitivity labels are computed *before* the data enters the LLM context. Your Purview investment now governs agents the same way it governs Copilot for M365."

### 4b. Switch to Purview (3 min)
Click the **🛡️ Microsoft Purview — DSPM for AI** card.

In Purview → AI Hub:
1. **DSPM for AI dashboard** — "AI applications in your tenant" tile. Find our agent listed alongside Copilot for M365 and any other registered apps.
2. **AI agents inventory** (sub-link) — drill into ESS Hosted Demo Agent. Show: prompt + response captures, sensitivity labels detected, DLP-for-AI policy matches, IRM honoring.
3. **Activity explorer** (sub-link) — filter by App = `ESS Hosted Demo Agent`. Show the tool-call ledger: every Workday/ServiceNow call with its label classification.
4. Open `demo_agent/purview-policy.yaml` briefly (in VS Code or a side tab). "This file declares 4 patterns + 7 rules; Purview portal-defined DLP-for-AI policies would augment it."
5. Optional: **Communication compliance** — show that the agent's communications (HITL Teams chats, emails sent) are subject to the same supervision policies as humans.

> "Same Compliance team. Same labels. Same policies. The agent doesn't get a free pass."

---

## 5. Kill switch + audit — control plane → Entra audit log (3 min)

### 5a. In our control plane (1.5 min)
> "Tool deny-lists are surgical. Sometimes you need to **kill an entire agent**."

1. On any per-user teammate card (right rail), click **🛑 Isolate**.
2. Type reason: `Compliance review — anomalous tool calls`.
3. Card grows a red banner; **Run** button is disabled.
4. From the dashboard, try to launch a run as that teammate. API returns HTTP **423 Locked**. Toast shows the block.
5. Show the audit ledger entry: `instance-disable · by control-plane-operator · target=<teammate id>`.
6. Click **Restore**. Banner clears. Re-run works.

### 5b. Switch to Entra audit log (1.5 min)
Click **Audit logs (directory)** sub-link in the Microsoft 365 surfaces card.

In Entra → Identity → Audit logs:
- Filter by **Service** = "Core Directory" and **Activity** = "Update service principal".
- Find the just-now timestamp. "Every kill-switch operation is also a directory write — your SIEM is already ingesting these via the standard Entra audit pipeline."

> "Two ledgers in sync: the agent runtime's audit ledger for sub-second forensics, and Entra's directory audit log for governance archival. Same actor, same timestamp."

---

## 6. Observability — control plane → Purview activity / Defender (3 min)

In the run timeline:
- Each turn shows **agent.llm.start / agent.llm.end** spans.
- Each tool call shows **mcp.tool.start / mcp.tool.end** with duration ms.
- Right-rail **Runtime signals** pill shows `A365 SDK: configured`, `A365 exporter: on`, payload logging state.

Click the A365 SDK pill — show the OTLP endpoint pointing at:
```
https://agent365.svc.cloud.microsoft/observabilityService/tenants/<tid>/otlp/agents/<agent>/traces
```

> "That endpoint feeds the same observability lake Purview Activity Explorer reads from and Defender posture management consumes. One emission, three consoles."

Switch to Purview Activity Explorer, then Defender Agents, and show the same run surfacing in both.

---

## 7. Evidence pack — investigation in 30 seconds (3 min)

> "Imagine your General Counsel walks in: *'A candidate is alleging discriminatory screening on October 3rd. Show me everything our HR agent did.'*"

1. Click into the completed hiring run.
2. Click **⬇ Evidence pack** in the run header.
3. JSON downloads: `ess-evidence-<run_id>.json`.
4. Open it. Walk through:
   ```json
   {
     "schema": "ess-agent365-run-evidence/1.0",
     "run": { "actor": "...", "prompt": "...", "toolCalls": [...], "loggedEvents": [...] },
     "agentIdentity": { "tenantId": "...", "blueprint": {...}, "agentIdentity": {...} },
     "observability": { "endpoint": "...", "sdkConfigured": true, ... },
     "governance": {
       "snapshot": { "toolDenylist": [...], "disabledInstances": {...} },
       "audit": [ "...every enforcement event for this agent..." ]
     },
     "policyEvents": [ "...every Purview redaction + control-plane block..." ]
   }
   ```

> "One file. Identity, prompt, tool calls, redactions, control-plane decisions, timestamps. Investigation in 30 seconds, not 30 days. And this file cross-references the *same Run IDs* you can pivot on in Purview Activity Explorer and Defender."

---

## 8. M365 Admin lifecycle — the closing surface (2 min)

Click the **⚙️ M365 Admin — Agent 365 console** card.

In Admin Center → Agents:
- Show the **Agent map** sub-link: every agent in the tenant + its license + its owner.
- Click into ESS Hosted Demo Agent — show provisioning status, license assignment, owner, last-used.
- Show **Policy templates**: "This is where you say *'no Procurement agent may call destructive Workday tools'* in plain English, and it flows down to every per-user teammate."
- Show **Agent governance actions**: deactivate, transfer ownership, retire.

> "This is where your IT admins live. Adding an agent is `New-MgUser`. Retiring an agent is offboarding. The motion is muscle memory."

---

## 9. Close — recap the message (2 min)

Bring all five tabs into view (or screenshot the right-rail Microsoft 365 surfaces card).

> "Five surfaces. Zero new consoles. One identity that walks through all five — born in Entra, governed in Purview, monitored in Defender, lifecycled in Admin Center, instrumented at runtime by the Agent 365 SDK."

Tap each one:
- ✅ **Entra** — your identity team already has this.
- ✅ **Purview** — your compliance team already has this.
- ✅ **Defender** — your SOC already has this.
- ✅ **Admin Center** — your IT admins already have this.
- ✅ **Agent 365 runtime** — emits the signals; no new motion to learn.

> "WPP's question was: *how do we scale governance to a workforce of agents?* The answer is: **you don't scale**. You **reuse**. The leverage you've built into your existing Microsoft 365 stack now extends to agents — automatically — the day you turn on Agent 365 in your tenant."

---

## Backup demos (Q&A)

| If asked… | Show… |
| --- | --- |
| "What about Conditional Access for the human behind an agent?" | Entra → Conditional Access → New policy. Show app filter targeting the per-user teammate. Talk through MFA-step-up for agent-initiated sensitive ops. |
| "Can we restrict where the agent can run from?" | Entra → Identity Protection → User risk + Sign-in risk. The agent and the user both feed the risk engine. |
| "What about non-Microsoft agents (LangChain, OpenAI Agents SDK)?" | Defender → Discovery of Shadow AI. Show how those surface even without Agent 365 — and how registering them in Purview AI Hub brings them under the same governance. |
| "Where does the data residency live?" | Open `observability.py` — show the OTLP endpoint is regional (`agent365.svc.cloud.microsoft` → tenant region). Purview + Defender stay in customer geo. |
| "Can we use customer-managed keys?" | Yes — Purview CMK, Defender CMK, M365 Customer Key all apply unchanged. Agents inherit. |
| "What about HITL when the manager hasn't installed the bot?" | Trigger `Manager approval`. Show the Teams chat from the agent identity → fallback email → web form. Manager replies, agent resumes. |
| "Where's the gateway?" | Show APIM `essmcp-gw-8030d928`. Bearer + Agent-ID/Blueprint headers enforced at the edge. |

---

## Cross-portal pivot cheat sheet

After each control-plane action, here's the *one* Microsoft portal page that proves the action surfaced:

| Control-plane action | Pivot to | What proves it |
| --- | --- | --- |
| `POST /api/run` (any scenario) | Entra → Sign-in logs → filter by app | New sign-in entry as the agent identity. |
| Tool deny-list rule blocks a call | Defender → Agents → Threat detection | (When wired) anomalous call event for this agent. |
| Purview-policy redacts SSN | Purview → Activity Explorer → filter app | Tool I/O with sensitivity label applied. |
| Isolate instance | Entra → Audit logs | `Update service principal` entry. |
| Run completes | M365 Admin → Agents → ESS Hosted Demo Agent | Last-used timestamp updates. |
| Download evidence pack | Purview → Activity Explorer | Same run id, same prompt, same tool list. |

---

## Demo endpoints (for incognito browser bookmarks)

```
Control plane:    https://ess-demo-agent.wittysand-460bf1d9.eastus.azurecontainerapps.io/control-plane
Identity API:     https://ess-demo-agent.wittysand-460bf1d9.eastus.azurecontainerapps.io/api/identity
Governance API:   https://ess-demo-agent.wittysand-460bf1d9.eastus.azurecontainerapps.io/api/governance

Entra (agent):    https://entra.microsoft.com/<tid>/#view/Microsoft_AAD_IAM/ManagedAppMenuBlade/.../appId/ed4046aa-...
Purview AI Hub:   https://purview.microsoft.com/aibrowser/aihub
Defender Agents:  https://security.microsoft.com/agents
M365 Admin:       https://admin.microsoft.com/Adminportal/Home#/agents
```

The control plane's **Microsoft 365 governance surfaces** rail card has all of these as click-through cards — use that as your nav during the demo so the audience sees the connective tissue between the runtime and the M365 stack on every pivot.

---

## Operator pre-staged deny-list patterns (paste-ready)

```
# Surgical — block a single risky tool
workday.terminate_user

# Family — block all destructive Workday ops
workday.terminate_*

# Server-wide — quarantine a whole MCP server
salesforce.*

# Cross-server pattern — block any "delete" anywhere
*.delete_*
```

Paste, **Apply**, watch the audit ledger record the rule and actor — then pivot to Entra audit logs to show the same write landing there.
