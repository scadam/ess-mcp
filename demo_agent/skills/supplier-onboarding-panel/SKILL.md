---
name: supplier-onboarding-panel
description: >-
  Onboard a new supplier as a tracked assignment from a manager, the way a regulated bank must: open the Coupa
  supplier onboarding request, classify the service (critical ICT third party under DORA, personal or client data,
  jurisdiction), convene information security, data protection, financial crime and finance reviewers in a Teams
  group chat, collect and record each due-diligence section, chase until all are in, then approve (the approval goes
  to the manager) or reject, and report back to the manager with the decision and conditions. Use when a manager
  asks to onboard, set up or approve a new supplier or vendor.
license: Proprietary demo content
compatibility: Group Functions Autopilot case desk with the Coupa MCP server. Scripts need Python 3.11+ (standard library only).
allowed-tools: coupa__create_supplier_information coupa__record_due_diligence
metadata:
  title: Supplier Onboarding Panel
  summary: Run supplier due diligence with the specialist reviewers in Teams, then approve or reject in Coupa.
  version: "1.0"
  domain: supply chain
  servers: coupa
  model-orchestrator: standard
  model-subagents: fast
  autonomy-budget: "8"
  max-turns: "40"
  mode: assignment
  outputs: reports/due-diligence.md
  launch: Onboard the supplier I name as a new supplier, run the due diligence with the reviewers, and report back to me.
---

# Supplier Onboarding Panel

A manager has asked you to onboard a supplier. Banks are accountable to regulators for their third parties (EBA
outsourcing guidelines, DORA for ICT services), so no supplier is set up until each specialist has signed off their
part. The outcome: a Coupa onboarding request with every due-diligence section recorded by the named reviewer, a
decision, and a clear report to the manager.

Read `references/third-party-standard.md` first.

## First turn — open and classify

1. From the manager's instruction take the supplier's legal name, country, what the bank will buy and why, and the
   supplier contact. If anything essential is missing, ask the manager in one message and wait.
2. Check it is new: `coupa__list_suppliers` with the name. If it exists, tell the manager and resolve.
3. Write `data/supplier.json` (fields in the script's docstring) and run `skill__run_script` →
   `classify_supplier.py data/supplier.json`. It returns the tier, which sections apply and the questions for each
   reviewer.
4. `coupa__create_supplier_information` with the facts and the classification flags.
5. `case__start_review` with the reviewers the script names (emails in the standard), topic
   "Onboarding: <supplier>", and a brief giving the service, the tier and why, and each reviewer's questions, asking
   each to reply with **pass**, **pass with conditions** (and the conditions) or **fail** and their reasons, within
   three working days.
6. Tell the manager the review is under way (`case__message_requester`, expects_reply false).

## Later turns — collect and record

- Each reply wakes you. When a reviewer gives an outcome, record it with `coupa__record_due_diligence` (their
  section, outcome, a faithful summary, reviewer name) and acknowledge briefly in the chat. Sections the script marks
  not applicable are recorded as pass with "not applicable: <reason>" by you.
- Answer reviewers' questions from the facts; if only the manager or the supplier knows, ask the manager.
- On the follow-up timer, chase whoever is outstanding with `case__post_to_review` (mention_all). After two chases,
  tell the manager who is holding it up.

## Decide and report

- Any **fail**: `coupa__reject_supplier_information` with the reasons (goes to the manager for approval), then
  report.
- All pass: `coupa__approve_supplier_information` with the combined conditions (goes to the manager for approval).
  Post the outcome in the review chat.
- Write `reports/due-diligence.md` (supplier, tier, each section with reviewer, outcome and conditions, decision)
  and `case__resolve` with a summary for the manager: decision, supplier number if created, conditions to put in the
  contract, and anything to track (for example a SOC 2 report due, register of information entry for DORA).
