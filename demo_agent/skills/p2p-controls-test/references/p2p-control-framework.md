# Procure-to-pay control framework (IT hardware)

Population-based testing over the Coupa data. "Today" is the `as_of` date the data reports. Amounts are GBP.

## Controls

| ID | Control | Objective | Test procedure | Exception |
|---|---|---|---|---|
| C1 | Three-way match | Invoices are approved and paid only for goods received | For every invoice compare the billed total with the PO's received value; tolerance is the greater of £250 or 2 % | Billed above received value plus tolerance on an approved or paid invoice |
| C2 | Approval before commitment | No PO is issued or sent before its requisition or PO approval completes, at the right authority | For every pending requisition or PO approval, check the status of the related PO | PO issued or sent to the supplier while its approval is pending |
| C3 | Segregation of duties at receipt | Receipts above £10,000 are confirmed by someone other than the requester | For every receipt compare the receiver with the requisition's requester | Requester receipted their own delivery above £10,000 |
| C4 | Third-party risk | Orders go only to suppliers with a valid contract and acceptable performance | For every supplier with open orders check contract expiry (60 days), on-time delivery (85 %) and defects (2 %) | Open orders with a supplier that breaches one or more thresholds |

An invoice held at approval because it did not match (C1) is the control **working**: record it as an
observation, not a finding. A self-receipt at or below £10,000 is an observation.

## Severity

| Severity | When |
|---|---|
| High | Money has left or is scheduled to leave without evidence (C1), or a commitment above £50,000 bypassed approval (C2) |
| Medium | Any other exception |
| Low | Observations |

Exposure: C1 the amount billed ahead of receipt; C2 the PO value; C3 the value of the self-receipted POs; C4 the
supplier's open order value.

## Cases

- Open a Salesforce compliance case for every **High** finding, and for **Medium** findings with exposure of
  **£25,000** or more. Group C3 exceptions for the period into one finding.
- Subject: `[finding ID] summary`. The finding ID makes cases idempotent: never open a second case for an ID.
- Case type and priority:

| Control | Compliance type | Priority |
|---|---|---|
| C1 | Operational Risk Event | High / Medium by severity |
| C2 | Policy Breach | High / Medium |
| C3 | Policy Breach | Medium |
| C4 | Third-Party / Vendor Risk | Medium |

## Owners and remediation

| Control | Owner | Remediation | Due |
|---|---|---|---|
| C1 | Accounts Payable lead | Stop or recover the payment; re-bill on receipt | 5 working days |
| C2 | Approver at the required authority | Approve retrospectively or cancel; root-cause the bypass | 10 working days |
| C3 | IT Asset Management | Independent confirmation of the receipts; enforce receiver ≠ requester | 10 working days |
| C4 | Category manager | Renew or re-source; no new orders until resolved | 20 working days |

## Autonomy

The compliance colleague opens the cases above on its own. It never closes or edits cases, approves anything or
contacts suppliers. `scripts/authorise.py` checks every case against the test results before it is created.
