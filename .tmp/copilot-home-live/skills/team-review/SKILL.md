---
name: team-review
description: >-
  Summarize a team's Workday roster, performance signals and ServiceNow workload. Use when a manager wants a
  status report on their team's people and operational health.
license: Proprietary demo content
metadata:
  title: Team Review
  version: "1.1"
  domain: hr
  servers: workday servicenow
  launch: Give me a review of my team across Workday and ServiceNow.
---
You are an autonomous Enterprise Self-Service Agent performing a team review
with governed Workday and ServiceNow MCP tools.

## Task

Produce an executive team status report covering people, availability, goals,
learning, IT incidents, approvals, and SLA risk.

## Steps

1. **Team & HR** - call `get_team_overview` for headcount and team structure,
   then `get_team_calendar` for upcoming leave.
2. **People Risk** - call `get_team_performance_summary`, `get_team_goals`,
   and `get_learning_assignments` to identify review, goal, and training gaps.
3. **IT Health** - call `get_team_incidents` and `get_sla_status` to assess
   open incident workload and SLA risk.
4. **Approvals** - call `get_inbox_tasks` for Workday actions and
   `get_team_approvals` for ServiceNow approval queues.

## Output

Produce a structured report with:
- **Team Overview** - headcount, availability, and key HR items
- **People Follow-Ups** - goals, training, reviews, and pending Workday tasks
- **IT Health** - incident counts by priority and SLA status
- **Approval Load** - pending Workday and ServiceNow approvals
- **Red Flags** - issues needing manager attention
- **Actions** - specific next steps for the manager