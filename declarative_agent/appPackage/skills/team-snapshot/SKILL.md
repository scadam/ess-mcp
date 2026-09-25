---
name: team-snapshot
description: Give a people manager a one-screen snapshot of their team from Workday — who is on the team and in which roles, who is out now or soon, what is waiting in the manager's Workday inbox, and the few things they should act on first. Use when a manager asks how their team is doing, who is out, what needs their attention, for a team dashboard or overview, or to prepare for a team meeting or one-to-ones.
---

# Team snapshot

**Goal:** in one short answer, the manager knows the state of their team and the two or three things to act on first. Everything comes from Workday; nothing is guessed.

## Step 1 — Gather the data

These calls are independent; make them together.

- `get_team_overview` — `totalHeadcount`, `byTitle`, `byOrganization` and `teamMembers` (name, businessTitle, isManager). A name ending in "(On Leave)" means that person is on a leave of absence.
- `get_team_calendar` — each team member's `timeOff` entries (date, timeOffType, quantity, status).
- `get_team_performance_summary` — `inboxSummary` (totalPending, pendingApprovals, pendingReviews, otherTasks) and `absenceOverview` (currentlyOut, upcoming).
- `get_inbox_tasks` — the manager's own pending tasks: `overallProcess` (for example "Hire: Alex Clark", "Absence Request: Betty Liu"), `descriptor`, `status`, `assigned` and `due`.

Don't call the goal or check-in tools: this Workday tenant doesn't grant access to them. If the manager asks about goals, say goals aren't available from Workday here and offer the snapshot instead.

If `get_team_overview` returns no team members, say the employee has no direct reports in Workday and stop.

## Step 2 — Work it out

- **Out now and soon:** people with time off today or in the next 14 days, from `get_team_calendar` and `absenceOverview`, plus anyone marked "(On Leave)".
- **Inbox by process:** group `get_inbox_tasks` by the text before the colon in `overallProcess` (Hire, Absence Request, Data Change…) and count each group.
- **Needs attention:** tasks whose `due` date has passed, absence requests from the manager's own team, and approvals. Pick the three that matter most: overdue first, then absence requests for the team, then the oldest `assigned` dates.

## Output

Use this shape and keep it short:

**Your team — {date}**

| Headcount | Out now | Out in next 14 days | Inbox tasks | Overdue |
|---|---|---|---|---|

- **Roles:** one line from `byTitle`.
- **Out:** names with dates, or "Nobody is out."
- **Inbox:** the top three process groups with counts, for example "Hire 78 · Absence Request 12 · Data Change 2".

**For you to act on** — at most three bullets, each naming a person or task and the action ("Approve Betty Liu's absence request due 22 Jul").

Offer one follow-up: "Want me to open your Workday inbox so you can approve these?" If they say yes, call `get_inbox_tasks` again to show the inbox widget.

## Before you answer

Check every number against the tool results, and that each "act on" bullet names a real task from `get_inbox_tasks`.
