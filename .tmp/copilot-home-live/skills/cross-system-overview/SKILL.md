---
name: cross-system-overview
description: >-
  Cross-system snapshot of Workday and ServiceNow for a person or team. Use when someone asks for an overview of
  their profile, time off, learning, tasks and open IT items in one place.
license: Proprietary demo content
metadata:
  title: Cross-System Overview
  version: "1.1"
  domain: hr
  servers: workday servicenow
  launch: Give me a cross-system overview of my Workday and ServiceNow items.
---
You are an autonomous agent performing a Workday and ServiceNow employee
self-service overview.

## Steps

1. Call `get_worker` to retrieve the employee's Workday profile.
2. Call `get_leave_balances` for remaining PTO and eligible absence types.
3. Call `get_pay_slips` for recent pay slip availability.
4. Call `get_inbox_tasks` for pending Workday tasks.
5. Call `list_incidents` filtering to open incidents assigned to the current
   user when possible.
6. Call `list_my_requests` and `list_tasks` for ServiceNow requests and tasks.
7. For each high or critical incident, call `get_incident` and `get_sla_status`
   for full context.

## Output

### Employee Profile
Name, title, department, manager, location, and hire date from Workday.

### Time-Off Balances
Remaining PTO, sick leave, and other leave balances.

### Pay and HR Tasks
Recent pay slip availability and Workday inbox actions.

### Open IT Items
Table of open incidents, requests, and tasks from ServiceNow.

### Summary
- Total open incidents by priority
- Upcoming SLA deadlines
- Key action items across both systems