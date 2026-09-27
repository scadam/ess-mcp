# AI colleagues in the flow of work — four-scene demo script

**The story:** employees ask for help where they already are: Microsoft 365 Copilot, Teams and Word. The
*Employee Self Service* agent in Copilot is the first line. When a problem needs a second line, the right AI
colleague takes the case the moment the record is created. It asks the person what it needs to know, fixes the
problem within its playbook and closes the case, and records every step. In Teams, people ask the colleagues to
run a showcase skill, in a 1:1 chat or a group chat. In Word, someone @mentions a colleague in a comment, and the
colleague edits the document in place as tracked changes for a human to accept.

Full run: about 25 minutes. Short version: 12 minutes (see the end). Everything in
[AUTONOMOUS_DESK_DEMO.md](AUTONOMOUS_DESK_DEMO.md) still works and can follow on.

Control plane: <https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io/control-plane#/cases>

---

## Cast and screens

| Who | Role in the demo | Signed in where |
|---|---|---|
| **Aadi Kapoor** (`AadiK@`) | Director, Compliance & Risk. His laptop keeps crashing (scene A); starts the group chat (scene C) | Edge profile "Aadi": Microsoft 365 Copilot, Teams |
| **Aisha West** (`AishaW@`) | Sales Manager. Wants to buy shares (scene B); in the group chat (scene C) | Edge profile "Aisha": Microsoft 365 Copilot, Teams |
| **You** (Scott Adams, `admin@`) | HR Business Partner, manager of the colleagues, operator. Runs the HR 1:1 (scene C) and writes the Word draft (scene D) | Control plane, Teams, Word for the web, ServiceNow (`admin`), Salesforce |

The colleagues (all Agent 365 instances with their own Entra identity, mailbox and Teams presence):

| Colleague | Works | Second-line playbook |
|---|---|---|
| **IT Service Agent** (`itsm-agent@`) | ServiceNow queue *Autopilot Service Desk* | `it-second-line` (Runbook E: crashes and memory errors) |
| **Compliance Agent** (`compliance-agent@`) | Salesforce compliance cases; Word compliance reviews | `compliance-second-line` |
| **HR Agent** (`hr-agent@`) | HR cases; Word HR drafting; the Workday backlog skill | `hr-second-line`, `hr-hiring-backlog-clearance` |
| **Supply Chain Agent** (`supply-agent@`) | Coupa exceptions; the month-end skill | `supply-second-line`, `procurement-month-end-close` |

Tabs to have open (your profile): the control plane on **Cases**, ServiceNow classic UI as `admin` (Incidents),
Salesforce (Cases), and the records library <https://caldova74201480.sharepoint.com/sites/autopilot-records>.

---

## One-time preparation

1. **ServiceNow crash scene.** `Reset-Demo.ps1` (below) runs ServiceNow setup, which now also creates:
   - Aadi as a ServiceNow user in *Autopilot Demo Users*, with his laptop *LT-AADIK-7440*. The CMDB note records
     graphics driver 31.0.101.5186.
   - The known-error problem *Latitude 7440: blue screens (MEMORY_MANAGEMENT)…* (PRB0040001) with its workaround.
   - The knowledge article *Laptop crashes, blue screens or 'out of memory' errors*. This instance's knowledge
     workflow keeps it in draft; publish it once in ServiceNow if you want the colleague's search to find it. The
     scene doesn't need it, because the known error carries the fix.
   - The catalog item *Remote remediation: graphics driver rollback*.
   - Two resolved precedent incidents (Kian and Colin).
   - The business rule *Autopilot self-service routing*: incidents that demo people raise for themselves, or that
     have no group, go to the *Autopilot Service Desk* queue.
2. **The Word draft.** Generate it once:

   ```powershell
   .\.venv\Scripts\python.exe infra\demo\make_demo_document.py
   ```

   The script writes `demo_agent/docs/assets/Hybrid and overseas working guidelines (draft).docx`. Upload a copy to
   your OneDrive (or any SharePoint library) before each run. Section 4 (working from another country) is
   deliberately thin. Section 5 contains a non-compliant sentence: "If the VPN is unavailable, you may email
   documents to a personal address…".
3. **Teams.** Optional: pin the colleagues' chats in each Edge profile so they're easy to find. The colleagues
   create a chat themselves when they first message someone.
4. **Rehearse scene D once in this tenant.** It relies on Word sending comment @mention notifications to Agent 365
   agents (see *Honest caveats*).

## 15 minutes before

1. Wake the ServiceNow instance (sign in at developer.servicenow.com); developer instances hibernate.
2. Reset without the seeded records, so the only live cases are the ones you raise:

   ```powershell
   .\infra\demo\Reset-Demo.ps1 -NoSeed
   ```

   This closes last run's demo incidents, Copilot-raised Salesforce cases and self-raised incidents; restarts
   Coupa; clears cases, runs and chat memory; and re-runs ServiceNow setup. (Without `-NoSeed` the desk also starts
   on Kian's battery incident and the seeded Salesforce cases, one of which is Aisha's Northbridge request. That
   would muddle scene B.)
3. Upload a fresh copy of the Word draft and open it in Word for the web in your profile.
4. In the control plane's **Control room**, check the four colleagues show with their photos, and that the
   latest *The case desk is listening* entry in the feed names *IT Service Agent (it)* alongside the other three.

---

## Scene A — "My laptop keeps crashing" (Copilot → ServiceNow → IT Service Agent, ~6 min)

**Aadi, in Microsoft 365 Copilot → Employee Self Service:**

> My laptop keeps crashing. Three blue screens today, and Excel keeps closing with an 'out of memory' error. It's
> really getting in the way of my work.

1. The agent's `it-self-help` skill suggests one or two quick checks, then offers to raise an incident. Say:

   > Yes please, raise it.

2. The incident form opens, pre-filled: short description, what was tried, assignment group *Autopilot Service
   Desk*, caller **Aadi Kapoor**. Check the Caller field shows *Aadi Kapoor* (type it if not), then **Create
   Incident**. *"The first line hands over without making Aadi repeat himself."*
3. **Control plane → Cases**: within seconds a new IT case appears, owned by the IT Service Agent. Open it and
   its first turn's run. The colleague reads the incident and Aadi's laptop record (with the graphics driver
   installed on 18 September), and finds the open known error and the two precedent incidents.
4. **Aadi's Teams** gets one message from the IT Service Agent with a few questions: the stop code on the blue
   screen, when it started and whether that was after an update, how often and with which apps, and whether the
   Dell ePSA diagnostic ran. Aadi replies:

   > It says MEMORY_MANAGEMENT. It started last Thursday after the update: three or four times a day, usually with
   > Excel, Teams and my external monitor. I ran the Dell test and it passed.

5. The colleague works the fix within its playbook, then messages Aadi. It links the incident to the known
   problem, orders *Remote remediation: graphics driver rollback* for Aadi's laptop, writes a work note and resolves
   the incident with a 24-hour confirmation window. In ServiceNow, show the incident: *Autopilot Service Desk*, the
   linked problem, the work notes and the resolved state, plus the requested item for the rollback.
6. Aadi replies in Teams:

   > That's fixed it, thanks.

   The case closes. *"Diagnosis, the known error, the remediation and the conversation: no human on the service
   desk touched it."*

*If Aadi's answers point to hardware instead (an ePSA 2000-012x memory error), Runbook B takes over and the
colleague offers a warranty repair and a loaner. That's a good second run.*

## Scene B — "Can I buy these shares?" (Copilot → Salesforce → Compliance Agent, ~5 min)

**Aisha, in Microsoft 365 Copilot → Employee Self Service:**

> I'd like to buy about £5,000 of Unilever shares in my ISA this week. Is that OK?

1. The agent explains that personal trades in listed shares need pre-clearance, and opens the compliance case
   form, pre-filled:
   - Type *Market Abuse / Insider Trading*.
   - A subject and description of the trade.
   - **Raised by** *Aisha West*, and her work email if Copilot knows it.

   Aisha checks the form and submits it. *"Same pattern: the first line gathers the facts and hands over."*
2. **Control plane → Cases**: a compliance case appears, owned by the Compliance Agent.
3. **Aisha's Teams**: one message asking only for what the records don't show. That's the number of shares, whether
   it's her own account or a connected person's, whether her desk trades Unilever for clients, and whether she's on
   any insider list. Aisha replies:

   > About 120 shares, my own ISA. My desk doesn't cover consumer staples and I'm not on any insider list.

4. The colleague writes the facts sheet, runs the policy screening script (the restricted list, insider lists,
   front-running, size and holding-period rules) and clears the trade within its authority. It notes the decision,
   rules and conditions on the Salesforce case and tells Aisha:
   - She's cleared to buy the shares in her ISA.
   - The clearance lapses at the end of the next business day.
   - She must hold the shares for at least 30 days.

   Show the Salesforce case (the resolution comment, the status) and the case timeline.
5. Aisha replies "Thanks" and the case closes.

**Optional contrast (1 min):** Aisha asks Copilot the same question for *Northbridge Renewables*. The Compliance
Agent declines it politely without saying why, because it's on the restricted list (rule P2) and the reason is
confidential.

## Scene C — Showcase skills in Teams (~6 min, run both at once)

**1:1 — you, in Teams, chat with HR Agent:**

> Clear my Workday inbox backlog as a dry run. Route what other teams should do and give me only the decisions that
> need me.

**Group chat — Aadi creates a group chat with Aisha, adds Supply Chain Agent, and posts:**

> @Supply Chain Agent close the IT hardware procurement month end as a dry run. Clear what you can within policy and
> tell us what needs a decision.

(Type `@Supply` and pick the colleague so the mention is real. In a group chat the colleagues answer only @mentions
and replies to their own messages.)

1. Both colleagues acknowledge straight away, then work in parallel. **Control plane → Runs** shows two live runs,
   each with a plan, parallel researcher sub-agents and tool calls to Workday, ServiceNow and Coupa.
2. *"Dry run" is taken from the requester's own words and can only reduce what a run may do: the colleagues read
   everything and report what they would change, and change nothing.*
3. In 2–4 minutes each posts its report where it was asked:
   - **HR Agent (1:1)** reports the backlog triaged by process, owner and age, the bulk work it would route to HRIS
     and HR Operations through ServiceNow, and a ranked decision pack for you.
   - **Supply Chain Agent (group chat)** reports every open request-to-pay chain three-way matched, the invoice
     and receipt exceptions it would act on within policy, replenishment for stock-out risks, and the items that
     need a decision.

   Both link the evidence files filed in the records library.
4. Open the records library and show the run folder: the reports, CSVs and a `run-manifest.json` with a hash of
   every file.

*To show real actions instead, leave out "as a dry run". Writes then follow each colleague's autonomy budget, and
anything beyond it comes to you for approval in Teams. Those changes are real, and a reset doesn't undo them.*

## Scene D — Colleagues in a Word document (~6 min)

**You, in Word for the web, with the draft *Hybrid and overseas working guidelines*:**

1. Select the paragraph under **4. Working temporarily from another country** → **New comment**:

   > @HR Agent please add our rules for working temporarily from another country: how many days, what needs a
   > panel and what to arrange.

   Pick the colleague from the @ list. Word offers to share the file with it: choose **Share** with **edit**
   access. Post the comment.
2. Select the paragraph under **5. Equipment, data and conduct** → **New comment**:

   > @Compliance Agent can you review this section and add what we need to say about client data and conduct when
   > working abroad?

   Share with edit access, and post.
3. Each colleague replies in its comment thread within seconds: *"On it. I'll make the change in the document as
   tracked edits…"*. **Control plane → Cases** shows two document cases.
4. **Close the document** (close the tab, or go back to the OneDrive folder) and keep **Control plane → Cases** on
   screen. *"Live co-authoring is something Office apps do with each other. The colleagues work through Microsoft
   Graph, which saves whole files, and Microsoft 365 won't let anything save over a document someone has open for
   editing. So they queue their tracked changes and save the moment I let go."* If a colleague finishes while the
   document is still open, its case timeline says it's waiting for Word, and it tells you in Teams.
5. In 1–3 minutes each colleague saves its tracked changes and its reply in the comment thread (if it had to wait,
   shortly after Microsoft 365 releases the closed document; it checks every 15 seconds):
   - **HR Agent** inserts the rules under section 4 as tracked changes, from the policy (W1–W9):
     - Up to 20 working days in 12 months with manager agreement.
     - 21–60 days needs the exception panel; over 60 days isn't permitted.
     - Countries that aren't permitted.
     - What to arrange: tax and social security (A1 certificate) and the right to work.
     - The contracting and client-data conditions.
   - **Compliance Agent** makes these tracked changes in section 5:
     - It replaces the personal-email sentence (a data-protection breach) with the compliant route.
     - It inserts the missing client data and conduct requirements, each citing its rule (D1–D9).
6. **Reopen** the document when both case timelines show *tracked change(s) in …*. Open **Review → Tracked
   changes**: the insertions and deletions are attributed to *HR Agent* and *Compliance Agent*, and each colleague
   has replied in its comment thread. Accept the HR changes, and accept or reject the compliance changes one by one.
   *"The human stays the author and the approver; the colleagues do the drafting and the checking."*

---

## Where it's all recorded

- **Control plane → Cases**: each case's timeline (the events, every message to and from people, notes, reviews
  and document reads and edits), with the linked ServiceNow, Salesforce or document record.
- **Control plane → Runs**: every turn as a run, with the model, tools, sub-agents, duration and outcome. Filed runs
  link to their evidence in the records library.
- **Control plane → Analytics**: what the work cost and what it saved. Cost per case and per interaction against what a
  case costs with people today; spend split into the fixed daily infrastructure (derived from Azure Cost Management),
  Copilot SDK AI credits, Work IQ credits and people-in-the-loop time. Also demand by channel, quality (resolved
  without a person, response and resolution times, escalations, approvals) and self-service: the ServiceNow demand
  mix, and the knowledge articles and catalog items the colleagues created, with their use since. Choose **Today**
  to show just this demo; the history is kept when you reset.
- **The systems of record**: ServiceNow work notes and resolution, Salesforce case comments, and Word tracked changes
  and comment replies.
- **Microsoft 365**: each colleague acts as its own Entra agent identity, so Entra sign-in logs, Purview and the
  Agent 365 admin views attribute the activity to the colleague, not a shared service account.

## Honest caveats

- **Word notifications are the newest path.** Scene D depends on Word delivering comment @mentions to Agent 365
  agents in this tenant. Rehearse it: if no "On it" reply arrives within a minute, check the comment used a real
  @mention (a name chip, not plain text) and that the file is shared with the colleague with edit access.
- **The colleagues can't save into a document that's open for editing.** Live co-authoring works between Office apps
  (Word for the web, desktop and mobile), which sync small changes with each other. The colleagues work through
  Microsoft Graph, which can only replace the whole file, and Microsoft 365 refuses that with *423 Locked* while
  anyone has the file open for editing. Reviewing mode is still editing, and switching to Viewing doesn't release
  the file straight away. The colleagues queue their changes and replies, check every 15 seconds (every minute after
  the first ten), save as soon as Microsoft 365 releases the file, and keep trying for two hours before telling you
  in Teams that they couldn't. The release is usually quick after you close the tab, but it can take a few minutes.
- **Pre-fill depends on the model.** Copilot usually pre-fills the incident caller and the "Raised by" field from the
  signed-in user; check them before submitting. With the current plugin settings (no user sign-in), a blank caller
  would default to the ServiceNow integration account, and the IT Service Agent then couldn't find Aadi in Teams.
- **Photos** set in the Microsoft 365 admin center can take a while to reach Graph and the control plane.
- **Timing** depends on Azure OpenAI load. Scene C's runs normally finish in 2–4 minutes.

## Troubleshooting

| Symptom | Check |
|---|---|
| Aadi's incident doesn't appear on Cases | In ServiceNow, open it: the assignment group must be *Autopilot Service Desk* and the caller *Aadi Kapoor*. Raise it again from Copilot if not (edits made as `admin` don't wake the desk). |
| The IT Service Agent writes on the ticket instead of Teams | The caller isn't *Aadi Kapoor*, so there was no one to find in the directory. (The colleague creates the Teams chat itself; none needs to exist.) |
| The Compliance Agent doesn't message Aisha | The form's *Raised by* and *Work email* were blank. Raise it again with them filled in. |
| No reply in the group chat | The message didn't contain a real @mention of the colleague. |
| Word: "On it" arrives but no changes | The document is still open for editing somewhere: another tab, Word desktop or another person. Close every copy; the case timeline says the colleague is waiting for Word until then, and it saves once Microsoft 365 releases the file. If it can't save at all (for example, the file was moved), it tells you in Teams. |

## Reset between runs

```powershell
.\infra\demo\Reset-Demo.ps1 -NoSeed
```

Then upload a fresh copy of the Word draft. Teams chats can stay; the colleagues' chat memory is cleared by the
reset. Analytics keep their history, so use the **Today** period to show only the current run.

## Short version (12 minutes)

1. Scene A to the Teams clarification and the fix (4 min).
2. Scene B to the clearance message (3 min).
3. Scene D with the HR comment only (4 min).
4. Close on the control plane's case timelines, **Analytics** (cost per case against people) and the records library
   (1 min).
