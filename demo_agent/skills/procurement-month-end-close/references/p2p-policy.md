# IT hardware procure-to-pay policy (month-end extract)

Applies to IT hardware bought through Coupa from ServiceNow employee requests. Amounts are GBP. "Today" is the
`as_of` date Coupa reports.

## 1. Three-way match

- An invoice may be approved, and paid, only up to the value of goods received on its PO plus tolerance.
- Tolerance is the greater of **£250** or **2 %** of the invoice total.
- Billed above received value beyond tolerance:
  - **Pending approval** — reject the approval, asking the supplier for a credit note or a re-bill on delivery.
    The procurement colleague may do this on its own.
  - **Approved but not yet paid** (payment status Scheduled or Not Paid) — reject the invoice so the scheduled
    payment stops. The procurement colleague may do this on its own; Accounts Payable is informed in the brief.
  - **Already paid** — recovery case for Accounts Payable. Never automatic.

## 2. Receipts and deliveries

- A goods receipt is posted within **2 days** of delivery. Coupa shows "Goods receipt not posted" on every open
  PO; that is expected until the expected delivery date has passed.
- A PO past its expected delivery date with quantities outstanding is **late**: chase the supplier for the
  outstanding quantity and a firm date, and track the chase in the month-end follow-up ticket.
- A PO whose expected delivery is within 3 days: confirm the receipt plan with the requester or IT Asset
  Management in the follow-up ticket.

## 3. Supplier acknowledgement

- Suppliers acknowledge a PO within **2 days** of issue. Overdue: chase and track in the follow-up ticket.
- Still unacknowledged **5 days** after issue: the category manager decides whether to re-source.

## 4. Approval authority

| Value | Approver |
|---|---|
| up to £10,000 | Line manager |
| up to £50,000 | Category manager |
| above £50,000 | Finance Director |

- The procurement colleague is never an approver: it does not approve requisitions, POs or invoices.
- A PO issued or sent to the supplier while its requisition or PO approval is still pending is an
  **approval bypass**. Severity high above £50,000, otherwise medium. The approver named above decides whether to
  approve retrospectively or cancel; Compliance is told about every bypass.

## 5. Segregation of duties

- For POs above **£10,000** the goods receipt must be confirmed by someone other than the requester (IT Asset
  Management). A requester who receipted their own delivery is a control observation for Compliance.

## 6. Suppliers

- Watch list: contract expiring within **60 days**, on-time delivery below **85 %** or defect rate above **2 %**.
- A watch-list supplier needs a renew-or-re-source decision from the category manager before new orders are placed.

## 7. Replenishment

- Daily demand = monthly demand ÷ 30. Days of cover = stock ÷ daily demand.
- Reorder when days of cover fall below **lead time + 21 days**. Order up to **lead time + 40 days** of demand,
  rounded up to a multiple of 5.
- Source from the contracted catalogue supplier when it is eligible. An alternative supplier may be used when it
  supplied the same item on a PO in the last **90 days** at no more than the catalogue price.
- Eligible supplier: preferred, strategic or preferred tier; risk **low**; contract valid for at least **60 days**;
  on-time at least **85 %**; defects at most **2 %**.
- The procurement colleague may raise a replenishment requisition on its own when the item is contracted, the
  source is eligible and the requisition is at most **£15,000**. Anything else is proposed to the category manager.
- One requisition per item per month; never split a requirement to stay under a limit.

## 8. What the procurement colleague may do on its own

| Action | Limit |
|---|---|
| Reject an invoice billed above receipt (approved, unpaid) | Rule 1 |
| Reject a pending invoice approval billed above receipt | Rule 1 |
| Raise a replenishment requisition | Rule 7, £15,000 |
| Raise one month-end follow-up ticket in ServiceNow | One per close |

Everything else is a decision for a person. Deterministic checks in `scripts/authorise.py` enforce these limits
before any action runs; anything they decline becomes a proposal that waits for approval.
