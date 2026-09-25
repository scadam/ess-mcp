---
name: track-hardware-request
description: Trace IT hardware requests from ServiceNow through Coupa — the ServiceNow request and its approval stage, then the Coupa requisition, purchase order, supplier acknowledgement, delivery, goods receipt and invoice — and say plainly where each request is stuck, why, and who needs to act. Use when someone asks where their order or hardware request is, why it hasn't arrived, what is blocking requests, or to trace a REQ or RITM number into procurement.
---

# Track a hardware request

**Goal:** for each request, one line that says where it is, what's holding it up and who acts next.

`references/procurement-stages.md` explains each stage and blocked reason and who owns the next step. Read it before you explain a blocked request.

## Step 1 — Find the requests

- If the user gives a REQ number, use it.
- If they ask about **their** orders, call `list_my_requests` (limit 10). Open items give the ServiceNow view: `request_number`, `ritm_number`, `catalog_item`, `stage` (for example "Waiting for Approval", "Fulfillment") and `created_on`.
- If they ask about hardware requests in general or "all" requests, go to Step 2 without a number.

## Step 2 — Trace into Coupa

Call `get_servicenow_coupa_flow` — with `request_number` for one request, or with no arguments for every traced request. Each flow has `requisition`, `purchase_order` (status, expected-delivery, delivery-risk, lines with quantity and received), `receipts`, `invoices` and a `blocked-reason`.

A ServiceNow request with no Coupa flow hasn't reached procurement yet: report its ServiceNow `stage` (usually still waiting for approval or fulfilment) and don't call it lost.

## Step 3 — Explain each request

For each request work out:

- **Where it is:** the furthest stage reached (requisition approved → PO issued → supplier acknowledged → partly received → received → invoiced → paid/closed).
- **What's holding it:** the `blocked-reason`, plus anything late — `expected-delivery` in the past or `delivery-risk` of "late" or "at_risk". Coupa demo data is dated early May 2026, so compare dates with each other, not with today.
- **Who acts next:** from the reference.

## Output

| Request | For | Item | Stage | Holding it up | Next step (owner) |
|---|---|---|---|---|---|

Sort blocked or late requests first. Under the table, at most three bullets with the specific actions, for example "Chase Apple Business Reseller UK for the 4 outstanding iPhone 15 on PO-2026-1051 (Procurement)."

If the user asked about one request, answer in two or three sentences instead of a table.
