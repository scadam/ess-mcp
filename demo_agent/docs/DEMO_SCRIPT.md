# Group Functions Autopilot — Demo Script

Control plane: <https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io/control-plane>

## 0. Before you start (2 minutes)

1. Open the control plane → **Control Room** → press **Reset** and confirm.
   It stops anything running and clears activity, runs, chat memory, approvals waiting on people and compliance cases.
   Approved skills and systems, isolation and the tool deny-list are kept. Salesforce records are **not** deleted
   (remove old demo cases in Salesforce if you want a clean list).
2. Arrange three windows side by side: **Outlook**, **Teams** (your chat with *Compliance Agent*) and the **Control Room**.

---

## Demo 1 — Compliance Agent: an emailed question becomes a resolved case

**Story:** an employee emails a compliance question. The agent opens a Salesforce case, checks the approved
evidence through Work IQ, clarifies what it needs to know in Teams, answers within policy, confirms the outcome
and closes the case. It acts as tier-1 support — beyond self-service, a domain expert.

### Step 1 — Send the email

Send from **your** mailbox (or Wonda's — only configured requesters are accepted).

- **To:** `compliance-agent@caldova74201480.onmicrosoft.com`
- **Subject:** `Project Seabrook — can we share the diligence pack with the Singapore advisory team today?`
- **Body:**

> Hi,
>
> We are finalising Northbridge Renewables' refinancing. Our external adviser wants the diligence pack for its
> Singapore team before tomorrow's lender call. The supplier dashboard is green and we have an NDA, but I am not
> sure whether those cover this team. The pack includes revised forecasts and some KYC documents. Can you
> establish what we can share, with whom, and what needs changing? The files are in the internal Seabrook deal
> workspace.
>
> Thanks

**Watch the Control Room light up:** *Received an email* → *Salesforce case #… created* → Work IQ evidence reads →
the investigation → *Messaged you privately in Teams*.

### Step 2 — The agent asks clarifying questions (Teams)

Expect: *“Case #… · Project Seabrook… Thanks for your email. I've opened this case and I'm checking it against our
records… To make sure I give you the right answer, could you tell me: 1. … 2. …”*

### Step 3 — Answer the questions

> The Singapore analysts would download the full pack themselves, including the KYC documents. Our UK contact is only coordinating.

Expect *“Thanks, let me check that against the records.”* followed by the answer: what is **not** permitted
(Singapore team, full pack, KYC documents), what **is** permitted (the approved UK-only team, aggregate forecasts,
no identity documents) with its conditions, the sources checked, and:
*“Does this answer your question? If it does, would you like me to email you a confirmation of the outcome before I close the case?”*

If it asks one more question, answer it briefly.

### Step 4 — Close it

- **With email:** `Yes, that answers it — please email me the confirmation.`
  → Salesforce closes the case (read back as *Closed*), Outlook receives *“RE: Project Seabrook… (case #… resolved)”*,
  Teams confirms.
- **Without email:** `That answers it, thanks — no need for an email.`
  → a summary in Teams, then the case closes.

### Step 5 — Show the evidence trail

Open the Salesforce case: the email, every Teams exchange and the resolution are logged as comments and
activity history. In the Control Room, open the case journey.

**If something goes wrong:** the tile shows **ATTENTION** with the exact reason (for example, an email from a
mailbox that isn't a configured requester).

---

## Demo 2 — HR Agent: a colleague, not a chatbot

In Teams, message *HR Agent*:

> We need to hire a software engineer for the team — just go ahead and do what you need to and tell me when there's a shortlist.

Expect one natural reply (or just *typing…*) and then the result — no confirmation loop. The go-ahead
pre-approves a bounded number of changes for that task only; deletes and similar actions still ask. A plain
**yes** or **no** answers a single waiting approval.

> Note: the Workday tenant lets the agent read requisitions, jobs and organisations, but has no tool to create a
> requisition or return candidates, so the agent says so plainly and proposes the next step.

---

## Skills: the colleague does whole jobs

Each flagship skill is a package: a playbook (`SKILL.md`), policy references, deterministic scripts, and report
templates. When you run one, point out:

- **Sub-agents** gather evidence in parallel (read-only) on the fast model; the orchestrator plans and acts on the
  reasoning model. The run view shows the model used at each step (gpt-5.4, gpt-4.1-mini).
- **Scripts do the maths** — matching, ageing and clustering run as bundled Python, not model arithmetic.
- **Pre-approved autonomy**: each skill lists the changes it may make alone, with a budget. A policy script checks
  every one against the evidence first. Anything else becomes an approval; the run carries on without waiting.
- **Deliverables**: download the reports from the run view's **Workspace files** panel.

**How to run one:** Control Room → open the colleague → pick the skill under *Approved skill* → **Run skill**
(it starts with the prompt quoted below). Tick **Dry run** to show the plan with nothing changed or queued. Open
the run to watch **Sub-agents**, **Skill scripts**, the models used, **Waiting for a go-ahead** and **Workspace files**.

> Live runs change real demo records in ServiceNow, Coupa and Salesforce, and **Reset does not undo them**. Use a
> dry run to rehearse; do the live run once.

### Demo 3 — Supply Chain Agent: Procurement Month-End Close

**Say:** “Close the IT hardware procurement month end. Clear what you can within policy and tell me what needs my decision.”

Watch for:
- Two sub-agents read every request-to-pay chain, approvals, demand and suppliers from Coupa.
- The three-way match finds **11 exceptions (2 high)** and **£11,010 billed ahead of receipt**.
- Done on its own: rejects invoice **INV-2026-0412** and approval **APR-602** (billed above receipt), raises a
  requisition for **70 USB-C docks from Dell (£13,230)**, and opens one ServiceNow follow-up ticket for the Procurement group.
- Proposed for approval: **30 iPhone 15 Pro (£29,970)** — above its limit, so it waits for you. Approve or reject
  it under **Waiting for a go-ahead** in the run view.
- Download `reports/month-end-brief.md`.

### Demo 4 — HR Agent: Hiring Backlog Clearance

**Say:** “Clear my Workday inbox backlog. Route what other teams should do and give me only the decisions that need me.”

Watch for:
- The triage script sorts **100 inbox tasks**: **82** bulk tasks are routed into **3 ServiceNow tickets** (account
  set-up, unassigned work, test data) instead of 82 manual clicks.
- **11 decisions** only a manager can make are ranked for you, compensation first. The agent never approves them.
- Download `reports/backlog-brief.md`.

### Demo 5 — Compliance Agent: P2P Controls Test

**Say:** “Run the procure-to-pay controls test on IT hardware and open cases for anything reportable.”

Watch for:
- Four controls tested across Coupa: **5 findings, 2 high** (invoice over receipt, PO issued before approval,
  requester who also receipted, supplier risk).
- Salesforce compliance cases open for reportable findings on their own; a finding that already has a case links to
  it rather than duplicating it.
- Download `reports/controls-workpaper.md`.

### Demo 6 — IT Agent: Zero-Touch Service Desk

**Story:** Self-service and Copilot avoid most cases, but when one is raised no person touches it. The IT Agent
works the whole ServiceNow queue as tier 1 and 2, and fixes the causes: it builds the catalog item people kept
raising incidents for and drafts the knowledge that was missing.

**Set-up (during the demo):** create the new instance and name it **IT Agent**. A name starting with “IT” gives it
the IT role: *Zero-Touch Service Desk*, *Incident Triage* and *Manager Approval* on ServiceNow and Workday. Open
its tile in the Control Room to show those approvals.

**Say (Control Room, or in Teams to IT Agent):** “Work the service desk queue. Resolve everything you can without a
person, and show me what still needs one.”

Watch for (from a dry run against today's queue of 40 active incidents):
- Three sub-agents read the queue and SLAs, problems and catalog, and knowledge in parallel. The triage script
  classifies and clusters every incident.
- **36 of 40 handled without a person:**
  - three automated test records cancelled;
  - outage clusters linked to their open problems (email → PRB0007601, Wi-Fi → PRB0001002, SAP → PRB0000011, SFA →
    PRB0000006), with a new problem for the website defect. Engineers work five problems instead of 17 incidents;
  - a replacement **Apple iPhone 13** ordered for David Loo, and INC0000020 resolved by the request;
  - how-tos and known fixes answered and resolved with steps for the caller, and years-stale tickets closed with a
    reopen invitation;
  - one vague request put on hold with the questions the caller needs to answer.
- **4 need a person, and the diagnosis is already done:** water leaking on the DNS server (dispatched to Hardware,
  urgent), a laptop memory upgrade, a request to change the Remedy UI, and the payroll server outage.
- **Fixing the causes:**
  - **7 knowledge drafts** for fixes that had no article;
  - a new **“Shared drive access”** catalog item, because three people raised incidents for it. It's built
    inactive, and publishing it is the one decision left to a person. Approve it under **Waiting for a go-ahead**
    in the run view (or reply in Teams) and the item goes live for self-service.
- Download `reports/service-desk-report.md`. In ServiceNow, show a linked problem, a resolved incident's comment and
  the draft item in the catalog.

**Point to make:** every change the agent made alone was checked by the skill's policy script against the triage
plan. It can't close an incident without telling the caller, order for anyone but the caller, or publish anything.
