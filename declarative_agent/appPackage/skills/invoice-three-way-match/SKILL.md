---
name: invoice-three-way-match
description: Three-way match Coupa supplier invoices against the purchase order and the goods actually received, flag invoices that bill more than was delivered or ordered, and prepare a rejection with a clear reason for the user to confirm. Use when someone asks to check, match or review invoices, find invoice mismatches or overbilling, resolve an invoice exception, or reject a wrong invoice in Coupa.
---

# Invoice three-way match

**Goal:** every invoice is either confirmed as matching, or has a specific, evidenced reason and a prepared action. Nothing is rejected until the user says so.

`references/matching-policy.md` holds the matching rules and tolerance. The bundled script applies them exactly.

## Step 1 — Gather the evidence

- **All invoices:** call `get_servicenow_coupa_flow` with no arguments. Each flow includes the `purchase_order` (with `lines`: quantity, unit-price, received), `receipts` and `invoices`.
- **One invoice:** call `get_invoice_status` with the `invoice_number`, then `get_po_status` with its `po-number` and `list_receipts` with the same `po_number`.

Only invoices that exist in the results are in scope; say so if the user names one that isn't found.

## Step 2 — Match with the script

Build a JSON list with one entry per invoice and run `python scripts/three_way_match.py input.json`:

```json
[{"invoice": "INV-2026-0412", "invoice_id": "50412", "status": "approved", "payment_status": "Scheduled",
  "billed": 24642.00, "currency": "GBP", "po": "PO-2026-1048", "supplier": "TechDirect UK Ltd",
  "lines": [{"item": "Standard Laptop", "ordered_qty": 18, "received_qty": 12, "unit_price": 1180.00}]}]
```

Take `lines` from the purchase order (quantity → ordered_qty, received → received_qty, unit-price → unit_price). You can also pass the whole `get_servicenow_coupa_flow` result instead; the script accepts it as is.

The script prints JSON with, per invoice: `ordered`, `received`, `variance`, `tolerance`, `verdict`, `action`, `reason` and `outstanding` lines, plus a ready-made Markdown `table`. **Use its numbers; don't recalculate them.** If you can't run scripts, apply the rules in the policy yourself and show your working.

## Step 3 — Present

Show the script's table, then for each invoice that doesn't match, one bullet with the reason in plain words, for example: "INV-2026-0412 bills £24,642.00 but only £16,428.00 has been received — 6 laptops and 6 docks are still outstanding."

## Step 4 — Prepare the rejection

For each invoice whose `action` is **reject**:

- Show the rejection you would send: invoice number, supplier and the script's `reason`.
- Ask: "Shall I reject INV-… in Coupa with this reason?"
- Only when the user clearly says yes, call `reject_invoice` with `invoice_id` and `reason`, then confirm the result.

Never reject an invoice whose status is **paid** — the policy routes those to Accounts Payable for recovery. Never approve invoices in this skill.

## Before you answer

Check that each flagged invoice has a number, an amount, a reason and an owner, and that you asked before rejecting anything.
