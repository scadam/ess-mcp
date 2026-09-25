# Procurement stages

| Stage | What it means | Next step | Owner |
|---|---|---|---|
| ServiceNow: Waiting for Approval | The employee's manager or the budget holder hasn't approved the request | Approve in ServiceNow | Approver |
| ServiceNow: Fulfillment, no Coupa flow | Approved; procurement hasn't raised the requisition yet | Raise the Coupa requisition | IT procurement |
| Requisition pending / pending_supplier_ack | The requisition or PO is waiting for the supplier to accept it | Chase the supplier for acknowledgement | Procurement |
| PO issued | The supplier has the order | Wait for delivery; chase if expected-delivery has passed | Procurement |
| supplier_acknowledged | The supplier confirmed the order and date | Wait for delivery | Supplier |
| partially_received | Some lines or quantities arrived | Chase the outstanding quantity | Procurement |
| Received, receipt posted | Everything arrived and the goods receipt is recorded | Nothing; invoice matching follows | — |
| Invoiced | The supplier billed; the invoice is matched to receipts | Approve the invoice if it matches | Accounts Payable |
| Paid / closed | Finished | Nothing | — |

## Blocked reasons

| blocked-reason | Explanation | Next step (owner) |
|---|---|---|
| Waiting for supplier acknowledgement | The supplier hasn't accepted the PO | Chase the supplier (Procurement) |
| Goods receipt not posted | Items may have arrived but nobody recorded the receipt, so the invoice can't be matched | Receiving site or requester posts the receipt in Coupa |
| Overdue delivery | The expected delivery date has passed with items outstanding | Chase the supplier for a new date (Procurement) |
| Progressing | No block; the request is moving | Nothing unless a date has passed |

## Late or at risk

- `delivery-risk` "late": the expected delivery date has passed.
- `delivery-risk` "at_risk": delivery is due within a few days and items are still outstanding.
- Outstanding quantity on a line = quantity − received.
