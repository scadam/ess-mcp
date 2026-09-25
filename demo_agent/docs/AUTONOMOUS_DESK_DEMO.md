# Group Functions Autopilot — The autonomous back office (demo script)

**The story:** a bank's group functions run a second line of AI colleagues. Nobody hands them work: ServiceNow,
Salesforce and Coupa ring a doorbell the moment something changes, and the colleague on that queue picks the case
up, works it with the real systems, talks to the people involved in Teams or on the ticket, makes the fix itself
where its playbook allows, asks a manager where it doesn't, and keeps going until the case is closed. Every step is
governed and every file it creates is filed as evidence.

Full run: about 25 minutes. Short version: 12 minutes (see the end).

Control plane: <https://ca-autopilot-caldova-78f0.livelysky-91807d17.eastus2.azurecontainerapps.io/control-plane#/cases>

---

## Cast and screens

| Who | Role in the demo | Signed in where |
|---|---|---|
| **You** (Scott Adams, `admin@`) | Manager of the colleagues, HR Business Partner, operator | Control plane, Teams, ServiceNow (`admin`) |
| **Colin Ballinger** (`ColinB@`) | Asked Compliance about Wimbledon seats; his TechDirect invoice is on hold | Edge profile "Colin": Teams |
| **Karin Blair** (`KarinB@`) | Her headset invoice is short-received | Edge profile "Karin": Teams |
| **Aisha West** (`AishaW@`) | Locked out of the TradeSupport Console | Edge profile "Aisha": Outlook |
| **Isaac Fielder** (`IsaacF@`) | Colin's and Karin's line manager | Edge profile "Isaac": Teams |
| **Daisy Phillips** (`DaisyP@`) | Wants to work from Lisbon for six weeks (optional act) | Edge profile "Daisy": Teams |

The colleagues: **IT Agent** works the ServiceNow queue *Autopilot Service Desk* (until an IT Agent instance is
hired it has no Teams identity, so it talks to callers on the ticket and by ServiceNow email, like a real desk);
**Compliance Agent** works Salesforce compliance cases; **Supply Chain Agent** works Coupa exceptions;
**HR Agent** works HR cases raised in Teams or by email.

Tabs to have open: the control plane on **Cases**, ServiceNow (classic UI as `admin`), Salesforce (Cases), and the
records library <https://caldova74201480.sharepoint.com/sites/autopilot-records>.

### ServiceNow sign-ins for the demo people

`infra/demo/New-ServiceNowInstance.ps1` (or a setup run) gives these ServiceNow users one demo password and the roles
every MCP tool's REST calls need (`itil`, `approver_user`, `knowledge`, `catalog_admin`, `asset`), through the group
*Autopilot Demo Users*. None is privileged, so the IT desk will still reset them and the access review ignores them.

`kian.lambert`, `aisha.west`, `colin.ballinger`, `karin.blair`, `daisy.phillips`, `elvia.atkins`, `kadji.bell`,
`kenvin.sturis`. The password is printed by `New-ServiceNowInstance.ps1` and kept in Key Vault as
`servicenow-demo-user-password`.

- `aisha.west` is **locked out on purpose** (it doubles as her TradeSupport Console account). She can sign in only
  after the IT colleague resets it in Act 2, with the temporary password from her email.
- Use these accounts when the declarative agent's ServiceNow plugin signs users in with OAuth. Don't sign the
  declarative agent in as `admin`: the desk ignores changes made by the integration account, so nothing would wake.

---

## If the ServiceNow instance was reclaimed (about 10 minutes)

1. Create a new developer instance at developer.servicenow.com and note its name (`dev123456`) and `admin` password.
2. Run:

   ```powershell
   .\infra\demo\New-ServiceNowInstance.ps1 -Instance dev123456
   ```

   It asks for the admin password and a password for the demo people (Enter generates one), then:
   creates the OAuth client (password grant for the MCP server, authorization code for the declarative agent in
   Teams), stores the credentials in Key Vault, points the ServiceNow MCP server at the new instance, and runs the
   provisioning job: support groups and owners, the demo people with sign-in passwords and roles, Kian's and Aisha's
   laptops with warranty data, the loaner catalog item, outbound email, and the signed webhook business rule.
   It ends by listing the sign-ins and the OAuth details for the declarative agent (`-RevealOAuthSecret` prints the
   client secret once, if you register the plugin with OAuth).
3. If the declarative agent's ServiceNow plugin uses OAuth, update its registration in the Teams Developer Portal
   with the new client ID, secret and URLs.

## 15 minutes before

1. Wake the ServiceNow instance (sign in at developer.servicenow.com); developer instances hibernate.
2. Run:

   ```powershell
   .\infra\demo\Reset-Demo.ps1
   ```

   About ten minutes. It restarts Coupa's simulated data, resets the control room (cases, runs, activity, approvals;
   approved skills stay), closes last run's demo incidents and cases, restores the ServiceNow people, lock-out and
   laptops, and raises fresh records. The colleagues start at once.
3. Open **Cases**. Before you start you should see, all worked with nobody touching them:

   | Case | Colleague | Where it should be |
   |---|---|---|
   | *Laptop shuts down on battery after about 20 minutes* (Kian) | IT Agent | Waiting for the vendor: replacement ordered, deskside swap booked |
   | *Pre-approval: Wimbledon debenture seats from TechDirect* (Colin) | Compliance Agent | Waiting for Colin: four questions sent in Teams |
   | *Pre-clearance: buy 500 Northbridge Renewables shares* (Aisha) | Compliance Agent | Resolved: declined, Aisha told |
   | *Invoice INV-TD-88213 from TechDirect UK Ltd is ap_hold…* (Colin) | Supply Chain Agent | Waiting for Colin: was the price rise agreed? |
   | *Invoice INV-INS-4471 from Insight Enterprise Technology is pending_receipt…* (Karin) | Supply Chain Agent | Waiting for Karin: did the other 8 arrive? |

   The two invoices appear about 30 seconds after the reset: the desk's own sweep found them in Coupa.

---

## Act 1 — The desk has been at work (3 min)

**Say:** "Nobody assigned any of this. Each system rang a doorbell the moment a record changed, and the colleague
on that queue picked it up. Let's look at one."

**Do:** open Kian's case.

**Expect** in the timeline: *servicenow.created* a few seconds after the ticket was raised, then the IT Agent's work
notes. It read the attached battery report and ran its diagnostic script: full-charge capacity 26,904 mWh against a
57,000 mWh design (47.2%), 912 cycles, a critical shutdown at 4%. It matched the serial number (7GHX2Z3) to Kian's
Dell Latitude 7440, found the warranty ended on 30 June 2026, so policy says replace rather than repair. It ordered
the standard laptop through the ServiceNow catalog, booked a deskside swap with data transfer, told Kian on the
ticket, and set itself a 48-hour follow-up.

**Do:** open the incident in ServiceNow: the work notes, Kian's update, the request (REQ…) and the task (TASK…).

**Point:** the colleague works the real systems with the bank's policy and deterministic scripts, not model
guesswork. The case is one durable session: when the vendor updates the order or the timer fires, it resumes with
everything it knew.

## Act 2 — A ticket arrives, live (4 min)

**Say:** "Aisha is locked out of a legacy trading application the self-service reset doesn't cover. She calls the
service desk, and first line logs it to the Autopilot queue."

**Do** (ServiceNow, classic UI as `admin`): **Incident > Create New** — Caller *Aisha West*, Short description
*Locked out of the TradeSupport Console*, Assignment group *Autopilot Service Desk* — **Submit**.
(Or run `.\infra\demo\Invoke-Provisioning.ps1 -System servicenow -Mode demo -Scenario lockout`, which takes a minute
longer to start.)

**Expect:** the case appears on **Cases** within seconds. Within about two minutes: the IT Agent checks Aisha's
profile (local application account, not privileged, six failed attempts, no sign of compromise), confirms the
account's registered email is hers, resets and unlocks it, and resolves the incident with a plain-English comment
and a four-hour confirmation window. The temporary password goes from ServiceNow straight to Aisha's mailbox; the
colleague never sees it.

**Do:** show Aisha's Outlook (*Your temporary TradeSupport Console password*) and the incident's activity.

**Point:** policy is built in. It won't reset an account for someone else, never resets a privileged account, and
treats a lock-out from an unknown location as a possible compromise for Security Operations.

## Act 3 — Judgement, with a person in the loop (5 min)

**Say:** "Colin manages the TechDirect relationship and approves their invoices. They've offered him Centre Court
seats worth about £420. The Compliance Agent checked Coupa, found TechDirect is an active supplier with a contract
to March 2027, and asked Colin only what the records couldn't tell it."

**Do:** in Colin's Teams, show the Compliance Agent's four questions, then reply:

> It's just me: the second seat is for TechDirect's account director. Only the seats and lunch, no travel or hotel.
> Nothing else from TechDirect in the last 12 months, and they're not in any live tender.

**Expect:** the colleague screens the facts with its script: above £250 is within its own pre-approval authority,
but above £100 needs Colin's line manager. It opens a Teams review chat with **Isaac Fielder** and posts a brief.

**Do:** in Isaac's Teams, reply in the review chat:

> Approve. Colin has a genuine account review with TechDirect that week.

**Expect:** approved with conditions (a clear business purpose, no discussion of live negotiations, registered
within five days). The colleague writes the decision on the Salesforce case, creates the gifts and hospitality
register task, tells Colin in Teams and resolves the case.

**Point:** it decides only what its delegated authority allows, convenes exactly the approvers the rules name, and
records everything on the system of record. (Aisha's share pre-clearance, already resolved, shows the other side: a
restricted instrument is declined without saying why, as the policy requires.)

## Act 4 — Money nobody chased (4 min)

**Say:** "Nobody raised these two. The Supply Chain Agent's sweep found them on hold in Coupa: TechDirect billed
20 laptops at £1,212 against a £1,180 order, £640 over tolerance; Insight billed 40 headsets when only 32 were
received."

**Do:** in Karin's Teams, reply to the Supply Chain Agent:

> Yes, the other 8 headsets arrived yesterday.

**Expect:** it receipts exactly 8 in Coupa, received by Karin on the date she gave; the invoice re-matches and
moves on to approval; Karin is told and the case resolves.

**Do:** in Colin's Teams, reply about the TechDirect invoice:

> No, we never agreed an increase. The contract price is £1,180.

**Expect:** it disputes the invoice for incorrect price, with a comment to TechDirect quoting the order and billed
prices and asking for a credit note, tells Colin, and waits five working days for the supplier.

**Point:** the invoice pays what the bank owes, no more and no later. Receipting and disputing with those reason
codes are pre-approved in its playbook; it never receipts goods the requester hasn't confirmed.

## Act 5 — A cross-border request and an exception panel (optional, 4 min)

**Do:** in Daisy's Teams, message **HR Agent**:

> I'd like to work from Lisbon for six weeks from 2 November, fully remote. I'm a British citizen. Is that OK?

**Expect:** "I've opened a case for this…". It may ask one question (exact dates, for example). Its script puts 30
working days abroad above the 20-day allowance, so policy needs an exception panel: it opens a Teams review chat with
you (HR Business Partner), Charlotte Waltson (Tax & Global Mobility), Aadi Kapoor (Employment Counsel) and Kat
Larsson (Daisy's manager), with the conditions to weigh (social security cover in Portugal, registering the trip).

**Do:** reply in the review chat as yourself: `Approve.`

**Point:** the colleague decides only when every panel member has answered, chases the others on a timer, and then
records and explains the decision to Daisy.

## Act 6 — A manager's instruction becomes a tracked assignment (optional, 4 min)

**Do:** in your Teams, message **Supply Chain Agent**:

> Onboard Nimbus Analytics Ltd (UK) as a new supplier. They'll build churn models on pseudonymised retail account
> data, about £180k a year. Contact: Priya Shah, priya.shah@nimbusanalytics.co.uk.

**Expect:** "I've taken this on as a tracked assignment…". It opens the Coupa onboarding request, classifies Nimbus
as tier 2 (it processes personal data), records operational resilience as not applicable with the reason, and
convenes Kadji Bell (information security), Kenvin Sturis (data protection), Aadi Kapoor (financial crime) and
Charlotte Waltson (financial standing) in a Teams chat, each with their own questions. The final approval in Coupa
will come to you.

## Act 7 — Control and evidence (3 min)

- **The trail:** on **Cases**, each timeline shows every event, message, tool result and decision.
- **The files:** open the records library, *Supply Chain Agent > Cases > INV-INS-4471*: the Coupa data the colleague
  saved, its analysis, and `run-manifest.json` with a SHA-256 for every file. They were uploaded by the colleague's
  own identity, so Purview's audit log shows *Supply Chain Agent* as the actor, and retention and eDiscovery apply.
- **The brakes:** anything outside a playbook's pre-approved changes waits for you under **Approvals** (and you're
  told in Teams). You can isolate any colleague from the control room in one click.

---

## Short version (12 minutes)

Act 1 (Kian's case, 2 min) → Act 2 (Aisha's live ticket, 3 min) → Act 3, Colin's reply only (3 min) →
Act 4, Karin's reply only (2 min) → Act 7 (2 min).

## Between runs

Run `.\infra\demo\Reset-Demo.ps1` again. It closes the previous run's demo incidents and cases, so nothing
duplicates. Records the colleagues created (orders, tasks, register entries) stay in the systems as history.

## If something goes wrong

- **A new ServiceNow ticket opens no case:** check the assignment group is *Autopilot Service Desk* and the ticket
  was *created* (the desk ignores updates made by `admin`, the integration account). A hibernating instance sends
  nothing: wake it. If the instance is new, run `Invoke-Provisioning.ps1 -System servicenow -Mode setup` again.
- **A Teams reply doesn't wake the case:** reply in the colleague's own chat (or the review chat), from the person
  it is waiting for.
- **The invoice cases didn't appear:** the desk sweeps Coupa every 15 minutes; a reset makes it sweep within 30
  seconds.
- **A case shows escalated after errors:** three failed turns in a row hand the case to a person; the timeline
  says why.
