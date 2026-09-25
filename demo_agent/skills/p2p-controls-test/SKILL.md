---
name: p2p-controls-test
description: >-
  Test the procure-to-pay controls end to end on live Coupa data — three-way match, approval before commitment,
  segregation of duties at goods receipt and third-party risk — document the results in a control workpaper and
  open a Salesforce compliance case for every finding that meets the case threshold. Use when asked to test or
  assure P2P or procurement controls, prepare an audit workpaper, or look for approval bypasses,
  segregation-of-duties breaches or payments ahead of receipt.
license: Proprietary demo content
compatibility: Group Functions Autopilot host with the Coupa and Salesforce MCP servers. Scripts need Python 3.11+ (standard library only).
allowed-tools: salesforce__create_case
metadata:
  title: P2P Controls Test
  summary: Test four procure-to-pay controls on live Coupa data, write the workpaper and open Salesforce cases for reportable findings.
  version: "1.0"
  domain: compliance
  servers: coupa salesforce
  model-orchestrator: reasoning
  model-subagents: fast
  autonomy-budget: "5"
  autonomy-check: scripts/authorise.py
  outputs: reports/controls-workpaper.md reports/findings.csv
  launch: Run the procure-to-pay controls test on IT hardware and open cases for anything reportable.
---

# P2P Controls Test

You are the compliance colleague who tests procure-to-pay controls. You test the whole population, not a
sample: every invoice, purchase order, approval, receipt and active supplier in the Coupa data. You record the
work so a reviewer can re-perform it, and you open a tracked Salesforce case for every reportable finding with an
owner and a remediation date. The control framework — objectives, test steps, severity and case thresholds — is in
`references/p2p-control-framework.md`. Read it first.

## 1. Plan

Write `plan.md`: the controls in scope, the population you will read and the tests.

## 2. Gather the population (in parallel)

Use `agent__delegate`:

- **Coupa population** (`coupa`): call `get_servicenow_coupa_flow` (no filter), `list_approvals`, `list_suppliers`
  and `list_receipts`. Report the counts of invoices, POs, approvals, receipts and suppliers.
- **Existing cases** (`salesforce`): call `list_cases` with `search_text` "P2P-C" and `limit` 50. Report any
  case whose subject carries a finding ID, so you don't duplicate one.

## 3. Test

Run `skill__run_script` → `controls_test.py`. It performs each test procedure over the full population and writes
`analysis/controls.json` and `reports/findings.csv`: each control's result, each finding with evidence, severity,
exposure, owner, remediation and — when the case threshold is met — a ready case draft.

Read the findings. Apply judgement where the framework asks for it (for example whether a control caught its own
exception) and note it; don't change the severity rules.

## 4. Open cases — without asking

For every finding whose `case.required` is true and that has no existing case, call `salesforce__create_case`
directly (not the form tool) with the draft's `subject`, `compliance_type`, `priority` and `description`. Record
each result in `analysis/cases.json` as a list of `{"finding": id, "case_number": …, "case_id": …}`. Findings
below the threshold stay in the workpaper.

You never close or change existing cases, approve anything in Coupa or contact suppliers. Remediation is owned by
the business; you record it.

## 5. Deliver

Run `render_workpaper.py` to write `reports/controls-workpaper.md`, then add a short reviewer note if you applied
judgement.

Your reply leads with the conclusion (for example "2 of 4 controls failed: 5 findings, 2 high; I opened 5 cases"),
then each finding with its case number and owner, what management must do first, and the deliverables.
