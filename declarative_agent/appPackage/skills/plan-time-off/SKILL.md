---
name: plan-time-off
description: Plan a Workday time-off request end to end. Checks the employee's balances and already-booked time off, checks who on their team is out, works out the working days and hours, and opens the Workday leave form pre-filled so the employee only has to confirm. Use when someone wants a day off, vacation, PTO, sick time or other leave, or asks whether they can take time off on certain dates.
---

# Plan time off

**Goal:** the employee ends with a pre-filled Workday leave form they only need to check and submit, and they know about any balance shortfall, double booking or team clash before they do.

## Step 1 — Understand the request

- Work out the exact dates. Turn relative dates ("next Friday", "the week after next") into calendar dates and state them back, for example "Friday 2 October 2026".
- Work out the kind of leave: vacation / paid time off, sick, or another type the employee names.
- A day means a full working day unless the employee says half day.
- If the dates or the kind of leave are unclear, ask **one** short question, then continue.

## Step 2 — Gather Workday data

These calls are independent; make them together.

- `get_leave_balances` returns `leaveBalances` (planName, balance, unit), `eligibleAbsenceTypes` (name, id, unit) and `bookedTimeOff` (date, timeOffType, quantity, status).
- `get_team_calendar` returns `teamMembers[]` with each person's `timeOff` entries.

## Step 3 — Work out the booking

1. **Split into working-day blocks.** Workday books the quantity on *every* date from start to end, weekends included, so a request that spans a weekend must become one request per Monday–Friday block. Run:
   `python scripts/leave_blocks.py --start 2026-10-02 --end 2026-10-06 --unit Hours`
   (add `--half-day` for half days, `--unit Days` for day-based types). It prints JSON with `blocks` (startDate, endDate, workingDays, quantityPerDay, totalQuantity) and `weekendDaysSkipped`. If you can't run scripts, list the Monday–Friday dates yourself and group consecutive ones.
2. **Choose the absence type.** From `eligibleAbsenceTypes`, pick the type whose name matches the kind of leave: for vacation, a name containing "Vacation", then "Paid Time Off" or "PTO"; for sick leave, a name containing "Sick". Use its `id` as `timeOffTypeId` and its `unit`. If nothing matches clearly, leave `timeOffTypeId` empty — the employee picks the type in the form.
3. **Check the balance.** Compare the total with the matching plan in `leaveBalances`. If the balance is lower, say so plainly, for example "You have 4 hours of Paid Time Off; this request is 8 hours."
4. **Check for double booking.** If `bookedTimeOff` already has an entry on any of the dates, name it and ask whether to continue.
5. **Check the team.** List anyone in `teamMembers[].timeOff` who is out on the same dates (names only).

## Step 4 — Open the form

For each block, call `prepare_request_leave` with:

- `startDate` and `endDate` as YYYY-MM-DD
- `quantity` = the block's **quantityPerDay** as a string (for example "8" hours, or "1" day) — it is per day, not the total
- `unit`, `timeOffTypeId` (or empty) and a short `reason` in the employee's words

**Never call `book_leave` yourself.** The form submits the request when the employee confirms.

## Output

Before the form, three short lines:

- **Dates:** for example "Fri 2 Oct 2026 · 8 hours of Vacation" (one line per block)
- **Balance:** what remains afterwards, or the shortfall
- **Team:** who is out on those dates, or "Nobody on your team is out then."

Then one sentence: "Check the details in the form and submit when you're happy."

## Before you answer

Confirm that the dates you stated match the dates in the form, that no weekend date is inside a block, and that you did not submit anything.
