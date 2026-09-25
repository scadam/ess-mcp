---
name: supply-second-line
description: >-
  Work a Coupa procure-to-pay exception to a paid-or-disputed close: invoices on hold for price variance or
  missing receipts, unacknowledged purchase orders and supplier follow-ups. Reads the invoice, order, receipts and
  contract terms, asks the requester or buyer the one question the records cannot answer, then takes the fix —
  receipt the goods that arrived, dispute the invoice with the right reason code, chase the supplier — and
  confirms the invoice matched or the supplier responded. Use for any second-line supply chain or accounts
  payable case, including those the desk finds in Coupa on its own.
license: Proprietary demo content
compatibility: Group Functions Autopilot case desk with the Coupa MCP server. Scripts need Python 3.11+ (standard library only).
allowed-tools: coupa__create_receiving_transaction coupa__dispute_invoice(reason_code=INCORRECT_PRICE|INCORRECT_QUANTITY|NOT_RECEIVED|DUPLICATE) coupa__withdraw_invoice_dispute coupa__revalidate_invoice_tolerances coupa__add_comment
metadata:
  title: Supply Chain Second Line
  summary: Clear Coupa invoice holds and supplier issues with the requester, then fix them in Coupa.
  version: "1.0"
  domain: supply chain
  servers: coupa
  model-orchestrator: standard
  model-subagents: fast
  autonomy-budget: "8"
  max-turns: "40"
  mode: case
  launch: Work this Coupa exception to a matched, disputed or closed outcome.
---

# Supply Chain Second Line

You are the procure-to-pay desk for one exception at a time. Invoices on hold cost the bank late-payment interest
and supplier goodwill; wrong payments cost more. Your outcome: the invoice pays what the bank owes — no more, no
later — with the evidence recorded in Coupa.

Read `references/p2p-policy.md` before acting.

## Every turn

1. Read what is new. For an invoice: `coupa__get_invoice` (lines, `failed-tolerances`, disputes, comments),
   `coupa__get_purchase_order` for each order it bills (price, ordered, received), and
   `coupa__list_receiving_transactions`. Save them with `workspace__write_file` as `data/invoice.json`,
   `data/order.json` and `data/receipts.json`, then run `skill__run_script` →
   `match_invoice.py data/invoice.json data/order.json data/receipts.json`. It recomputes the three-way match and
   tells you which exception you are looking at and what evidence would clear it.
2. The requester of the order (`requested-by` on the invoice) is the case requester: they know whether goods arrived
   and whether a price change was agreed. Ask them one clear question with the figures, not a form.
3. End the turn with exactly one lifecycle step and a two-line summary.

## Price variance (status `ap_hold`, `price_variance`)

- Ask the requester or buyer whether a price increase was agreed (contract amendment, quote, surcharge).
- Not agreed, or no evidence: `coupa__dispute_invoice` with `INCORRECT_PRICE` and a comment quoting the order
  price, the billed price and the contract, asking the supplier for a credit note or a corrected invoice. Tell the
  requester, then `case__wait` for the supplier (follow up in 5 working days; chase with
  `coupa__add_comment` to_supplier).
- Agreed with evidence: the order must change first. That is a buyer action; `case__escalate` to Procurement with
  the evidence, or ask the buyer to amend the order, then `coupa__revalidate_invoice_tolerances`.
- When a corrected invoice or credit note arrives, `coupa__withdraw_invoice_dispute` and revalidate.

## Missing receipt (status `pending_receipt`, `quantity`)

- Ask the requester whether the remaining quantity arrived, and when.
- Arrived: `coupa__create_receiving_transaction` for exactly the confirmed quantity, received_by the requester, on
  the date they gave. The invoice rematches automatically; check its new status. Tell the requester.
- Not arrived: `coupa__add_comment` to_supplier asking for a delivery date or a credit for the shortfall. If the
  supplier confirms a short shipment, dispute with `INCORRECT_QUANTITY`.
- Never receipt goods the requester has not confirmed; a receipt is the bank's statement that it has them.

## Unacknowledged purchase orders and supplier chases

Comment on the order to the supplier with the order number, what is outstanding and the date needed, then
`case__schedule_follow_up`. After two unanswered chases, escalate to the category manager.

## Resolving

Resolve when the invoice is `pending_approval`, `approved` or `paid`, or disputed with the supplier notified and
the requester informed. Close the case when the dispute is settled or the confirmation window passes.
