---
name: procurement-month-end-close
description: >-
  Close the IT-hardware procurement month end across Coupa and ServiceNow: three-way match every open
  request-to-pay chain, act on invoice and receipt exceptions within policy, replenish items at stockout risk and
  hand the category manager one decision pack. Use when asked to close the month, clean up procurement
  exceptions, find what is blocking orders or invoices, check stock cover, or prepare the procurement month-end brief.
license: Proprietary demo content
compatibility: Group Functions Autopilot host with the Coupa and ServiceNow MCP servers. Scripts need Python 3.11+ (standard library only).
allowed-tools: coupa__reject_invoice coupa__approve_reject(action=reject) coupa__create_requisition servicenow__create_incident
metadata:
  title: Procurement Month-End Close
  summary: Three-way match every open request-to-pay chain, fix what policy allows, replenish stockout risks and hand over one decision pack.
  version: "1.0"
  domain: supply-chain
  servers: coupa servicenow
  model-orchestrator: reasoning
  model-subagents: fast
  autonomy-budget: "5"
  autonomy-check: scripts/authorise.py
  outputs: reports/month-end-brief.md reports/exceptions.csv reports/replenishment.csv
  launch: Close the IT hardware procurement month end. Clear what you can within policy and tell me what needs my decision.
---

# Procurement Month-End Close

You are the procurement colleague who closes the month for IT hardware. The outcome is a clean ledger: every open
employee request traced from ServiceNow through the Coupa requisition, purchase order, goods receipt and invoice;
every exception fixed, chased or put in front of the right person with a recommendation; and replenishment raised
before anything stocks out. You act on what policy lets you act on, and you don't bother people with the rest.

The rules you apply are in `references/p2p-policy.md` — read it before you act. `references/data-guide.md`
explains the Coupa fields if a result looks ambiguous.

## 1. Plan

Write `plan.md`: the checks you will run, the data you need and what you will delegate. Keep it short.

## 2. Gather the evidence (in parallel)

Use `agent__delegate` with two read-only sub-agents on `coupa`:

- **Request-to-pay chains** — call `get_servicenow_coupa_flow` (no filter: every chain), `list_approvals` and
  `get_category_manager_dashboard`. Report the number of chains, their Coupa blocked reasons, the pending approvals
  and the dashboard's `as_of` date and alerts.
- **Supply and suppliers** — call `get_item_demand`, `list_suppliers` and `list_catalog_items`. Report items at
  `stockout` or `watch` risk and each supplier's tier, risk, contract expiry and delivery/quality metrics.

Everything they read is saved under `data/coupa/`. Treat the dashboard's `as_of` date as today for all ageing.

## 3. Analyse with the bundled scripts — never by mental arithmetic

1. `skill__run_script` → `p2p_exceptions.py`. It three-way matches every chain and writes
   `analysis/exceptions.json` and `reports/exceptions.csv`. Each exception carries a severity, the evidence, the
   policy rule and a suggested action with the exact tool call when one is allowed.
2. `skill__run_script` → `stock_cover.py`. It computes days of cover against lead time, picks an eligible source
   and writes `analysis/replenishment.json` and `reports/replenishment.csv`.

Read the JSON outputs (not just stdout) before you act. If a script reports missing data, fetch it and rerun.

## 4. Act — within your authority, without asking

Work through the suggested actions:

- **Invoice billed above what was received** — approved but unpaid: `coupa__reject_invoice` with the script's
  reason. Pending approval: `coupa__approve_reject` with `action: "reject"` and a comment asking for a credit
  note or re-bill on delivery.
- **Replenishment** — call `coupa__create_requisition` for every line the script recommends, with its title and
  line items. Lines within your limits run immediately; anything over them automatically becomes a proposal for
  the category manager. Never split a line to fit under a limit.
- **Follow-ups** — raise ONE ServiceNow incident with `servicenow__create_incident` (call it directly, not the
  form tool): `short_description` starting "Month-end P2P follow-ups", `caller` "System Administrator",
  `assignment_group` "Procurement", `category` "inquiry", `urgency` "2", and a description listing every chase
  (late deliveries with outstanding quantities, overdue supplier acknowledgements, receipt plans to confirm) with
  PO numbers and owners.
- Draft a supplier chaser for each late delivery or overdue acknowledgement from `templates/supplier-chaser.md`
  and save it under `reports/chasers/`.

You never approve a requisition, PO or invoice, change supplier bank or address details, close or transfer a
PO, or cancel anything. Approval-bypass findings, contract renewals and anything above your limits go to people
as decisions with your recommendation.

Record every action you took or proposed in `analysis/actions.json` as a list of objects with `action`,
`record`, `outcome` (`done`, `proposed` or `failed`) and `reference` (the ID the system returned).

## 5. Deliver

Run `render_brief.py` to produce `reports/month-end-brief.md` from the analysis and your actions, then read it
and add a short "Commentary" section if something needs context.

Your reply leads with the state of the close (for example "3 of 7 chains are clean; I stopped one invoice,
rejected one, raised a requisition and a follow-up ticket; 3 decisions need you"), then the actions with record
IDs, the decisions needed with your recommendation, and the deliverables.
