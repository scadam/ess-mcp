# 🖼️ Widget Gallery — 76 Interactive HTML+Skybridge Widgets

[← Back to main README](../README.md) · See also: [MCP Servers](mcp-servers.md)

ESS-MCP ships **76 interactive HTML + Skybridge widgets** that render directly inside AI assistant UIs (Microsoft 365 Copilot, ChatGPT, Claude). Every widget:

- Supports dark / light mode and fullscreen expansion
- Cross-navigates via `sendFollowUpMessage`
- Carries forms whose **submit buttons map to MCP tool callbacks** — the agent never has to compose JSON for create / update flows
- Includes **5 manager-specific team dashboards** for cross-system manager workflows

| Suite | Widgets | Manager dashboards |
|-------|---------|---------------------|
| Workday | 16 | Team Dashboard, Team Goals |
| ServiceNow | 12 | Team Incidents |
| Salesforce | 9 | Team Pipeline |
| Jira | 5 | Team Sprint Health |
| SAP SuccessFactors | 10 | – |
| SAP Ariba | 12 | – |
| Coupa | 12 | – |

---

## Workday – HR Widgets (16)

<table>
  <tr>
    <td align="center"><strong>Worker Profile</strong></td>
    <td align="center"><strong>Org Chart</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-worker-profile.png" width="400" alt="Worker Profile Widget"/></td>
    <td><img src="images/widget-org-chart.png" width="400" alt="Org Chart Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Leave Booking</strong></td>
    <td align="center"><strong>Team Calendar</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-leave-booking.png" width="400" alt="Leave Booking Widget"/></td>
    <td><img src="images/widget-team-calendar.png" width="400" alt="Team Calendar Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Team Dashboard</strong></td>
    <td align="center"><strong>Change Business Title</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-team-dashboard.png" width="400" alt="Team Dashboard Widget"/></td>
    <td><img src="images/widget-change-business-title.png" width="400" alt="Change Business Title Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Compensation Summary</strong></td>
    <td align="center"><strong>Learning Assignments</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-compensation-summary.png" width="400" alt="Compensation Summary Widget"/></td>
    <td><img src="images/widget-learning-assignments.png" width="400" alt="Learning Assignments Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Learning Catalog</strong></td>
    <td align="center"><strong>Learning Search</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-learning-catalog.png" width="400" alt="Learning Catalog Widget"/></td>
    <td><img src="images/widget-learning-search.png" width="400" alt="Learning Search Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Inbox Tasks</strong></td>
    <td align="center"><strong>Give Feedback</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-inbox-tasks.png" width="400" alt="Inbox Tasks Widget"/></td>
    <td><img src="images/widget-give-feedback.png" width="400" alt="Give Feedback Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Goals Dashboard</strong></td>
    <td align="center"><strong>Create Check-In</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-goals-dashboard.png" width="400" alt="Goals Dashboard Widget"/></td>
    <td><img src="images/widget-create-check-in-form.png" width="400" alt="Create Check-In Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Development Items</strong></td>
    <td align="center"><strong>Team Goals</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-development-items.png" width="400" alt="Development Items Widget"/></td>
    <td><img src="images/widget-team-goals.png" width="400" alt="Team Goals Widget"/></td>
  </tr>
</table>

## ServiceNow – ITSM Widgets (12)

<table>
  <tr>
    <td align="center"><strong>Incident List</strong></td>
    <td align="center"><strong>Create Incident</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-incident-list.png" width="400" alt="Incident List Widget"/></td>
    <td><img src="images/widget-create-incident.png" width="400" alt="Create Incident Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Update Incident</strong></td>
    <td align="center"><strong>Team Incidents</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-update-incident.png" width="400" alt="Update Incident Widget"/></td>
    <td><img src="images/widget-team-incidents.png" width="400" alt="Team Incidents Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Approval Review</strong></td>
    <td align="center"><strong>Task List</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-approval-review.png" width="400" alt="Approval Review Widget"/></td>
    <td><img src="images/widget-task-list.png" width="400" alt="Task List Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Update Task</strong></td>
    <td align="center"><strong>Cart Summary</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-update-task.png" width="400" alt="Update Task Widget"/></td>
    <td><img src="images/widget-cart-summary.png" width="400" alt="Cart Summary Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Catalog List</strong></td>
    <td align="center"><strong>Catalog Item</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-catalog-list.png" width="400" alt="Catalog List Widget"/></td>
    <td><img src="images/widget-catalog-item.png" width="400" alt="Catalog Item Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Create Change Request</strong></td>
    <td align="center"><strong>Create Problem</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-create-change-request.png" width="400" alt="Create Change Request Widget"/></td>
    <td><img src="images/widget-create-problem.png" width="400" alt="Create Problem Widget"/></td>
  </tr>
</table>

## Salesforce – CRM Widgets (9)

<table>
  <tr>
    <td align="center"><strong>Sales Pipeline</strong></td>
    <td align="center"><strong>Account 360°</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-crm-pipeline.png" width="400" alt="CRM Pipeline Widget"/></td>
    <td><img src="images/widget-crm-account-360.png" width="400" alt="CRM Account 360 Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Opportunity Form</strong></td>
    <td align="center"><strong>Lead Form</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-crm-opportunity.png" width="400" alt="CRM Opportunity Widget"/></td>
    <td><img src="images/widget-crm-lead.png" width="400" alt="CRM Lead Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Lead Pipeline</strong></td>
    <td align="center"><strong>Team Pipeline</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-lead-pipeline.png" width="400" alt="Lead Pipeline Widget"/></td>
    <td><img src="images/widget-team-pipeline.png" width="400" alt="Team Pipeline Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>CRM Event</strong></td>
    <td align="center"><strong>CRM Quote</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-crm-event.png" width="400" alt="CRM Event Widget"/></td>
    <td><img src="images/widget-crm-quote.png" width="400" alt="CRM Quote Widget"/></td>
  </tr>
  <tr>
    <td align="center" colspan="2"><strong>Compliance Case</strong></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><img src="images/widget-compliance-case.png" width="400" alt="Compliance Case Widget"/></td>
  </tr>
</table>

## Jira – Project Management Widgets (5)

<table>
  <tr>
    <td align="center"><strong>Issue Detail</strong></td>
    <td align="center"><strong>Sprint Board</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-jira-issue.png" width="400" alt="Jira Issue Widget"/></td>
    <td><img src="images/widget-sprint-board.png" width="400" alt="Sprint Board Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Create Issue</strong></td>
    <td align="center"><strong>Create Project</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-create-issue-jira.png" width="400" alt="Create Issue Widget"/></td>
    <td><img src="images/widget-create-project.png" width="400" alt="Create Project Widget"/></td>
  </tr>
  <tr>
    <td align="center" colspan="2"><strong>Team Sprint Health</strong></td>
  </tr>
  <tr>
    <td colspan="2" align="center"><img src="images/widget-team-sprint-health.png" width="400" alt="Team Sprint Health Widget"/></td>
  </tr>
</table>

## SAP SuccessFactors – HR Widgets (10)

<table>
  <tr>
    <td align="center"><strong>Employee Profile</strong></td>
    <td align="center"><strong>Leave Balance</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-sf-employee-profile.png" width="400" alt="SF Employee Profile Widget"/></td>
    <td><img src="images/widget-sf-leave-balance.png" width="400" alt="SF Leave Balance Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Time Off History</strong></td>
    <td align="center"><strong>Leave Booking</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-sf-time-off-history.png" width="400" alt="SF Time Off History Widget"/></td>
    <td><img src="images/widget-sf-leave-booking.png" width="400" alt="SF Leave Booking Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Personal Data Form</strong></td>
    <td align="center"><strong>Org Chart</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-sf-personal-data-form.png" width="400" alt="SF Personal Data Form Widget"/></td>
    <td><img src="images/widget-sf-org-chart.png" width="400" alt="SF Org Chart Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Payslip List</strong></td>
    <td align="center"><strong>Payslip Detail</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-sf-payslip-list.png" width="400" alt="SF Payslip List Widget"/></td>
    <td><img src="images/widget-sf-payslip-detail.png" width="400" alt="SF Payslip Detail Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Move Employee</strong></td>
    <td align="center"><strong>Document List</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-sf-move-employee.png" width="400" alt="SF Move Employee Widget"/></td>
    <td><img src="images/widget-sf-document-list.png" width="400" alt="SF Document List Widget"/></td>
  </tr>
</table>

## SAP Ariba – Procurement Widgets (12)

<table>
  <tr>
    <td align="center"><strong>Invoice Status</strong></td>
    <td align="center"><strong>PO Status</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-ariba-invoice-status.png" width="400" alt="Ariba Invoice Status Widget"/></td>
    <td><img src="images/widget-ariba-po-status.png" width="400" alt="Ariba PO Status Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Confirm Action</strong></td>
    <td align="center"><strong>Receipt List</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-ariba-confirm-action.png" width="400" alt="Ariba Confirm Action Widget"/></td>
    <td><img src="images/widget-ariba-receipt-list.png" width="400" alt="Ariba Receipt List Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Create Receipt</strong></td>
    <td align="center"><strong>Requisition List</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-ariba-create-receipt.png" width="400" alt="Ariba Create Receipt Widget"/></td>
    <td><img src="images/widget-ariba-requisition-list.png" width="400" alt="Ariba Requisition List Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Create Requisition</strong></td>
    <td align="center"><strong>Catalog Search</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-ariba-create-requisition.png" width="400" alt="Ariba Create Requisition Widget"/></td>
    <td><img src="images/widget-ariba-catalog-search.png" width="400" alt="Ariba Catalog Search Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Supplier List</strong></td>
    <td align="center"><strong>Supplier Profile</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-ariba-supplier-list.png" width="400" alt="Ariba Supplier List Widget"/></td>
    <td><img src="images/widget-ariba-supplier-profile.png" width="400" alt="Ariba Supplier Profile Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Supplier Registration</strong></td>
    <td align="center"><strong>Approval List</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-ariba-supplier-registration.png" width="400" alt="Ariba Supplier Registration Widget"/></td>
    <td><img src="images/widget-ariba-approval-list.png" width="400" alt="Ariba Approval List Widget"/></td>
  </tr>
</table>

## Coupa – Procurement Widgets (12)

<table>
  <tr>
    <td align="center"><strong>Invoice Status</strong></td>
    <td align="center"><strong>PO Status</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-coupa-invoice-status.png" width="400" alt="Coupa Invoice Status Widget"/></td>
    <td><img src="images/widget-coupa-po-status.png" width="400" alt="Coupa PO Status Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Confirm Action</strong></td>
    <td align="center"><strong>Receipt List</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-coupa-confirm-action.png" width="400" alt="Coupa Confirm Action Widget"/></td>
    <td><img src="images/widget-coupa-receipt-list.png" width="400" alt="Coupa Receipt List Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Create Receipt</strong></td>
    <td align="center"><strong>Requisition List</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-coupa-create-receipt.png" width="400" alt="Coupa Create Receipt Widget"/></td>
    <td><img src="images/widget-coupa-requisition-list.png" width="400" alt="Coupa Requisition List Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Create Requisition</strong></td>
    <td align="center"><strong>Catalog Search</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-coupa-create-requisition.png" width="400" alt="Coupa Create Requisition Widget"/></td>
    <td><img src="images/widget-coupa-catalog-search.png" width="400" alt="Coupa Catalog Search Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Supplier List</strong></td>
    <td align="center"><strong>Supplier Profile</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-coupa-supplier-list.png" width="400" alt="Coupa Supplier List Widget"/></td>
    <td><img src="images/widget-coupa-supplier-profile.png" width="400" alt="Coupa Supplier Profile Widget"/></td>
  </tr>
  <tr>
    <td align="center"><strong>Supplier Registration</strong></td>
    <td align="center"><strong>Approval List</strong></td>
  </tr>
  <tr>
    <td><img src="images/widget-coupa-supplier-registration.png" width="400" alt="Coupa Supplier Registration Widget"/></td>
    <td><img src="images/widget-coupa-approval-list.png" width="400" alt="Coupa Approval List Widget"/></td>
  </tr>
</table>

---

[← Back to main README](../README.md)
