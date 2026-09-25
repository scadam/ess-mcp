# Procure-to-pay policy (Caldova Group Accounts Payable)

## Three-way match
- Every order-backed invoice line is matched against the order line price and the received quantity.
- Price tolerance: **2%** or **100** (document currency) per line, whichever is smaller. Above it the invoice goes to
  AP hold for price variance.
- Quantity: billed quantity may not exceed received quantity. Above it the invoice waits for receipt.
- A matched invoice routes to its approval chain, then to payment on the supplier's terms (net 30 unless the
  contract says otherwise).

## Who may do what
| Action | Who | Evidence |
|---|---|---|
| Receipt goods | The requester, or the desk on the requester's written confirmation in the case | Requester's confirmation of quantity and date |
| Dispute an invoice | AP / the desk | The order and contract terms that the invoice departs from |
| Accept a price increase | The buyer, by amending the order | Contract amendment, signed quote or published index clause |
| Write off a variance | Not permitted below the approval chain; never by the desk | — |

## Dispute reason codes
INCORRECT_PRICE · INCORRECT_QUANTITY · NOT_RECEIVED · DUPLICATE · MISSING_PO · OTHER.
Always explain the reason in the supplier-visible comment with the figures.

## Contracts (demo)
| Contract | Supplier | Terms |
|---|---|---|
| CTR-IT-2026-01 | TechDirect UK Ltd | Standard Laptop fixed at 1,180.00 per unit to 31 March 2027; no surcharges |
| CTR-AV-2025-07 | Insight | Headsets 96.00 per unit; partial deliveries allowed; invoice on delivery |

## Supplier chases
Chase on day 3 and day 8 after the due date; after two unanswered chases escalate to the category manager.
