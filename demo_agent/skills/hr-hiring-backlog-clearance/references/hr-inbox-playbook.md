# HR partner inbox playbook

How the HR colleague sorts an HR partner's Workday inbox. "Today" is the run date.

## Buckets, owners and routing

| Bucket | What it is | Owner | Handling |
|---|---|---|---|
| Account set-up | "Edit Workday Account" initiation steps of Hire processes | HRIS team | One ServiceNow ticket listing every hire |
| Unassigned | Tasks in status "Awaiting Assignment" | HR Operations | One ServiceNow ticket to route them |
| Test records | Integration or probe data in the live inbox ("Test", "Testing", "Probe", "MicrosoftApp…") | HRIS team | One ServiceNow ticket to remove them |
| Approvals | Steps of type Approval (HR Partner, Payroll Partner) | Named partner | Decision pack |
| Compensation | Requisition or offer compensation reviews | HR partner | Decision pack, urgent |
| Leave reviews | "Review Leave of Absence" | HR partner | Decision pack; urgent after 14 days |
| Background checks | Hire "Background Check" steps | Talent Acquisition | Decision pack, urgent: start dates depend on them |
| Job and org changes | Change job, edit position, org assignment, reorganisation reviews | HR partner | Decision pack |
| Mentoring | Hire "Manage Mentorship" steps | Hiring managers | Nudge in the brief |
| Drafts | Tasks "Saved for Later" | Whoever saved them | Nudge in the brief |

Test records are identified first: a test record is never a decision, whatever its step.

## Ranking decisions

1. Compensation and approvals — money or employment terms wait on them.
2. Background checks — a start date cannot be confirmed until they clear.
3. Leave reviews — urgent once waiting more than 14 days.
4. Job and org changes.

Within a rank, the longest-waiting item goes first. Flag any item whose worker or initiator is on leave: it may
need reassigning.

## Tickets

- Short description starts "HR backlog:" and says what and how many.
- Caller "System Administrator"; assignment group "Service Desk" (it dispatches to HRIS and HR Operations);
  category "inquiry"; urgency 2 (3 for test-record clean-up).
- The description lists the tasks or hires, the oldest date and why it matters, and says the ticket was raised
  by the HR colleague for the HR partner.
- One ticket per bucket per run; check for an open "HR backlog:" ticket first.

## What the HR colleague may do on its own

Raise the routing tickets above (at most three per run). It never approves, denies or reassigns Workday tasks,
changes worker data or books leave. Deterministic checks in `scripts/authorise.py` enforce this; anything else
becomes a proposal that waits for a person.
