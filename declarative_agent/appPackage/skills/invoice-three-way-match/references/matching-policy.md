# Matching policy

A supplier invoice is matched against what was **ordered** (the purchase order) and what was **received** (goods receipts).

## Values

- Ordered value = sum of ordered quantity × unit price over the PO lines.
- Received value = sum of received quantity × unit price over the PO lines.
- Variance = billed − received value.
- Tolerance = the larger of £250 or 2% of the billed amount. Differences within tolerance are rounding or freight and are accepted.

## Verdicts

| Verdict | Rule | Action | Owner |
|---|---|---|---|
| Matches | billed is within tolerance of the received value | approve as normal | Accounts Payable |
| Billed above the order | billed − ordered value > tolerance | reject — ask the supplier to re-issue at the PO price and quantity | Procurement |
| Billed ahead of receipt | billed − received value > tolerance and the invoice isn't paid | reject — ask for a credit note, or to re-bill once the rest is delivered | Procurement |
| Paid ahead of receipt | as above, but the invoice is already paid | recover — can't be rejected; Accounts Payable requests a credit note | Accounts Payable |
| Under-billed | received value − billed > tolerance | note only — the supplier may send a further invoice | Accounts Payable |

## Rejection reason

State the invoice, the billed amount, the received amount and what is outstanding, for example:
"Billed £24,642.00 against £16,428.00 received on PO-2026-1048 (6 × Standard Laptop and 6 × USB-C Docking Station outstanding). Please issue a credit note or re-bill on delivery."
