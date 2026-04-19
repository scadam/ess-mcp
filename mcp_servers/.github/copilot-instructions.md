# ESS-MCP — Copilot Instructions

> **Purpose** — Extend the ESS-MCP repository with three new MCP servers (**SAP SuccessFactors**, **SAP Ariba**, **Coupa**) and enhance the existing **ServiceNow** server. Together with the existing Workday, Salesforce, and Jira servers, these form the backend for a **Single Front Door (SFD)** — an M365 Copilot declarative agent with `remoteMCPServer` plugins — covering 49 use cases across ALL, IT, ERP, OTC, P2P, and People service lines.

---

## 1 — Project Overview

| Item | Detail |
|---|---|
| Language | Python 3.11+ |
| Framework | Model Context Protocol (MCP) via [FastMCP](https://github.com/jlowin/fastmcp) over SSE / Streamable HTTP |
| Gateway | ASGI (Starlette) at `:8080` with per-server mount points |
| Existing servers | `workday`, `servicenow`, `salesforce`, `jira` |
| Servers to add | `sap_sf` (SAP SuccessFactors), `ariba` (SAP Ariba), `coupa` (Coupa — **fully mocked**) |
| SFD agent | M365 Copilot declarative agent with `remoteMCPServer` plugin pointing at each gateway endpoint |
| Auth pattern | OAuth 2.0 bearer-token passthrough — the declarative agent sends an Entra ID token; each MCP server either uses it directly or exchanges it for a target-system token |
| Widget pattern | HTML + Skybridge interactive widgets with dark/light mode, fullscreen, and `sendFollowUpMessage` cross-widget navigation |

### 1.1 — Key Design Decisions

| Decision | Rationale |
|---|---|
| **Knowledge articles are NOT MCP tools** | The declarative agent natively supports knowledge sources (SharePoint, ServiceNow KB, Unily). The agent handles KB search/summarisation — no dedicated MCP tool needed. |
| **Password reset is a service catalog item** | UC#4 ("reset my password") submits a ServiceNow service catalog request via the existing `order_catalog_item` tool — same as any other service request. It is NOT a custom scripted REST endpoint. |
| **Coupa is fully mocked** | No sandbox or developer instance is available. All Coupa tools return realistic mock data. The mock responses follow real Coupa REST API shapes from the [Coupa API docs](https://docs.coupa.com/en/developer-documentation/the-coupa-core-api). |
| **Ariba uses sandbox + API key** | Ariba Sandbox at `sandbox.api.sap.com` with a static API key stored in `.env`. No OAuth flow needed — the API key is sent as a header on every request. |
| **SAP SF uses Entra → SAP token exchange** | The declarative agent passes an Entra ID bearer token. The SAP SF MCP server exchanges it for an SAP SuccessFactors OAuth token using the SAP token endpoint, then calls OData v2 APIs. |
| **No "SFD MCP server"** | The SFD *is* the declarative agent — there is no separate MCP server called "SFD". Routing between service lines is handled by the agent's instructions/prompts. |

### 1.2 — Directory Convention (follow exactly)

New servers follow the **same structure** as existing ones (`servicenow/`, `workday/`, etc.):

```text
mcp_servers/src/mcp_servers/
├── sap_sf/
│   ├── __init__.py       # exports build_sap_sf_server()
│   ├── server.py         # FastMCP registration (tools + resources)
│   ├── tools.py          # SAP_SF_TOOL_SPECS list + async handler functions
│   └── resources.py      # SAP_SF_RESOURCES dict (widget HTML refs)
├── ariba/
│   ├── __init__.py       # exports build_ariba_server()
│   ├── server.py
│   ├── tools.py          # ARIBA_TOOL_SPECS list
│   └── resources.py
├── coupa/
│   ├── __init__.py       # exports build_coupa_server()
│   ├── server.py
│   ├── tools.py          # COUPA_TOOL_SPECS list (all mocked)
│   └── resources.py
```

Widgets go in the shared `mcp_servers/src/mcp_servers/ui/widget/` directory.

### 1.3 — Gateway Mount Points

| Server | MCP | SSE |
|---|---|---|
| SAP SuccessFactors | `/sap_sf/mcp` | `/sap_sf/sse` |
| SAP Ariba | `/ariba/mcp` | `/ariba/sse` |
| Coupa | `/coupa/mcp` | `/coupa/sse` |

Update `cli.py` `SERVER_BUILDERS` dict to register these three alongside the existing four.

---

## 2 — SFD Use Case Registry (49 Use Cases)

The table below maps every use case from the requirements sheet to the MCP server(s) and tool(s) that implement it.

### Key

- **Type**: Read / Transact / Proactive
- **OOTB**: Can the base M365 Copilot declarative agent handle this without MCP tools? (knowledge articles = Yes)
- **Server**: Which MCP server(s) implement this

### 2.1 — ALL Service Line

| # | Use Case | Type | Platform | Server | Implementation | OOTB |
|---|---|---|---|---|---|---|
| 1 | Knowledge article search & summarisation | Read | ServiceNow | *declarative agent* | Native knowledge source — no MCP tool needed. Agent searches SN KB, SharePoint, Unily directly. | ✅ |

### 2.2 — IT Service Line

| # | Use Case | Type | Platform | Server | Implementation | OOTB |
|---|---|---|---|---|---|---|
| 2 | Coupa Access Requests | Transact | ServiceNow | `servicenow` | `order_catalog_item` — submits access request as SN catalog item → approval → integration activates Coupa account | ✅ |
| 3 | New software request | Transact | ServiceNow | `servicenow` | `list_catalog_items` + `order_catalog_item` — user browses IT software catalog and orders | ✅ |
| 4 | Password reset | Transact | ServiceNow | `servicenow` | `order_catalog_item` — password reset is a **service catalog item** (not a custom API). The catalog item triggers the actual AD/Azure AD reset via SN workflow. | ❌ |
| 5 | Password change info | Read | ServiceNow | *declarative agent* | Knowledge article — handled natively by agent | ✅ |
| 6 | Software ordering policy & process | Read | ServiceNow | *declarative agent* | Knowledge article — handled natively by agent | ✅ |
| 7 | Password change — proactive prompt | Proactive | ServiceNow | `servicenow` | Future: scheduled check for users with leave in 1 week. Out of scope for initial build. | ❌ |
| 8 | IT software usage — proactive prompt | Proactive | ServiceNow | `servicenow` | Future: scheduled check for unused software >3 months. Out of scope for initial build. | ❌ |

### 2.3 — OTC Service Line

| # | Use Case | Type | Platform | Server | Implementation | OOTB |
|---|---|---|---|---|---|---|
| 9 | BSOC Invoice Template | Transact | TBC | `servicenow` | Future: custom SN form → S4 integration. Out of scope for initial build. | ❌ |

### 2.4 — P2P Service Line

| # | Use Case | Type | Platform | Server | Implementation | OOTB |
|---|---|---|---|---|---|---|
| 10 | Supplier Invoice/Payment Status | Read | Ariba/Coupa | `ariba` + `coupa` | `get_invoice_status` — takes invoice number, returns status | ❌ |
| 11 | Supplier PO Status | Read | Ariba/Coupa | `ariba` + `coupa` | `get_po_status` — takes PO number, returns status | ❌ |
| 12 | Supplier Reject Invoice | Transact | Ariba/Coupa | `ariba` + `coupa` | `reject_invoice` — takes invoice number, rejects it | ❌ |
| 13 | Procurement Close PO | Transact | Ariba/Coupa | `ariba` + `coupa` | `close_purchase_order` — takes PO number, closes it | ❌ |
| 14 | Payment Status — Coupa | Read | Coupa | `coupa` | `get_invoice_status` (same tool, Coupa-specific) | ❌ |
| 15 | Reject Invoice — Coupa | Transact | Coupa | `coupa` | `reject_invoice` | ❌ |
| 16 | Payment Status — Ariba | Read | Ariba | `ariba` | `get_invoice_status` | ❌ |
| 17 | Reject Invoice — Ariba | Transact | Ariba | `ariba` | `reject_invoice` | ❌ |
| 18 | Goods receipt — Ariba | Transact | Ariba | `ariba` | `list_receipts` + `create_receipt` | ❌ |
| 19 | Goods receipt — Coupa | Transact | Coupa | `coupa` | `list_receipts` + `create_receipt` | ❌ |
| 20 | Requisitions — Ariba | Transact | Ariba | `ariba` | `list_requisitions` + `create_requisition` + `update_requisition` | ❌ |
| 21 | Requisitions — Coupa | Transact | Coupa | `coupa` | `list_requisitions` + `create_requisition` + `update_requisition` | ❌ |
| 22 | Order catalogue item | Transact | Ariba/Coupa | `ariba` + `coupa` | `list_catalog_items` + `order_catalog_item` | ❌ |
| 23 | Procurement policy enquiry | Read | ServiceNow | *declarative agent* | Knowledge article — handled natively by agent | ✅ |
| 24 | Receive item — proactive prompt | Proactive | Ariba/Coupa | `ariba` + `coupa` | Future: scheduled check for POs >2 weeks without receipt. Out of scope for initial build. | ❌ |

### 2.5 — People Service Line

| # | Use Case | Type | Platform | Server | Implementation | OOTB |
|---|---|---|---|---|---|---|
| 25 | Absence / Leave Query | Read | SuccessFactors | `sap_sf` | `get_leave_balances` + `get_time_off_history` | ❌ |
| 26 | Hierarchy Update Request | Transact | SuccessFactors | `sap_sf` + `servicenow` | `get_org_chart` → `order_catalog_item` (SN approval) → `update_hierarchy` (SF) | ❌ |
| 27 | Background check — result | Read | SuccessFactors | `sap_sf` | `get_background_check_status` | ❌ |
| 28 | Background check — trigger | Transact | SuccessFactors | `sap_sf` | `trigger_background_check` | ❌ |
| 29 | Position Management | Transact | SuccessFactors | `sap_sf` + `servicenow` | `order_catalog_item` (SN approval) → `manage_position` (SF) | ❌ |
| 30 | Personal Data Change (Alumni) | Transact | SuccessFactors | `sap_sf` | `change_personal_data` | ❌ |
| 31 | Leave/Vacation Carryover | Transact | SuccessFactors | `sap_sf` + `servicenow` | `order_catalog_item` (SN approval) → `request_leave_carryover` (SF) | ❌ |
| 32 | Summarise personal data | Read | SuccessFactors | `sap_sf` | `get_employee_profile` | ❌ |
| 33 | Annual leave policy enquiry | Read | SuccessFactors | *agent* + `sap_sf` | Policy = knowledge article (native). Days remaining = `get_leave_balances`. | Partial |
| 34 | HR process enquiry | Read | ServiceNow | *declarative agent* | Knowledge article — handled natively by agent | ✅ |
| 35 | Change personal data | Transact | SuccessFactors | `sap_sf` | `prepare_change_personal_data` → `change_personal_data` | ❌ |
| 36 | Book annual leave | Transact | SuccessFactors | `sap_sf` | `prepare_book_leave` → `book_leave` | ❌ |
| 37 | Move employee | Transact | SuccessFactors | `sap_sf` | `prepare_move_employee` → `move_employee` | ❌ |
| 38 | Personal data — proactive prompt | Proactive | SuccessFactors | `sap_sf` | Future: scheduled anniversary check. Out of scope for initial build. | ❌ |
| 39 | Annual leave — proactive prompt | Proactive | SuccessFactors | `sap_sf` | Future: scheduled leave balance check. Out of scope for initial build. | ❌ |
| 40 | Pay Query | Read | SuccessFactors | `sap_sf` | `get_pay_stubs` + `get_pay_stub_detail` | ❌ |
| 41 | Personal Data Change Request | Transact | SuccessFactors | `sap_sf` + `servicenow` | `order_catalog_item` (SN approval) → `change_personal_data` (SF) | ❌ |
| 42 | Employee Info/Document Request (US) | Transact | SuccessFactors | `sap_sf` | `get_employee_documents` + `generate_employment_verification` | ❌ |
| 43 | Reference/Employee Info (UK) | Transact | SuccessFactors | `sap_sf` | `get_employee_documents` + `generate_employment_reference` | ❌ |

### 2.6 — P2P — EY Automation Items

| # | Use Case | Type | Platform | Server | Implementation | OOTB |
|---|---|---|---|---|---|---|
| 44 | Procurement Registration | Transact | Ariba/Coupa | `ariba` + `coupa` | `register_supplier` | ❌ |
| 45 | Procurement Address Update | Transact | Ariba/Coupa | `ariba` + `coupa` | `update_supplier_address` | ❌ |
| 46 | Procurement Transfer PO | Transact | Ariba/Coupa | `ariba` + `coupa` | `transfer_purchase_order` | ❌ |
| 47 | Supplier Address Update | Transact | Ariba/Coupa | `ariba` + `coupa` | `update_supplier_address` | ❌ |
| 48 | Supplier Bank Update | Transact | Ariba/Coupa | `ariba` + `coupa` | `update_supplier_bank` | ❌ |
| 49 | Supplier Registration Onboarding | Transact | Ariba/Coupa | `ariba` + `coupa` | `register_supplier` | ❌ |

---

## 3 — SAP SuccessFactors MCP Server (`sap_sf`) — NEW

### 3.1 — Authentication

The M365 Copilot declarative agent sends an **Entra ID bearer token**. The SAP SF MCP server **exchanges** this for a SAP SuccessFactors OAuth token using the SAP token endpoint.

```
Agent → [Entra token] → sap_sf MCP server → [exchange for SAP token] → SAP SF OData API
```

**Token exchange flow:**
1. Extract Entra bearer token from MCP request `Authorization` header
2. POST to SAP SF token endpoint with `grant_type=urn:ietf:params:oauth:grant-type:saml2-bearer` (or client_credentials for demo)
3. Use returned SAP access token for all OData v2 calls

**Credentials (demo environment):**

| Parameter | Value |
|---|---|
| OData Base URI | `https://apisalesdemo8.successfactors.com/odata/v2` |
| Resource URI | `api://32e5479e-d82d-4241-943b-4d42279547f4` |
| Company ID | `SFCPART001804` |
| Client ID | `MWVmMjcxZTM2OTlmYzM3ZjFhODk3MGU1ZGEyOA` |
| Token Endpoint | `https://apisalesdemo8.successfactors.com/oauth/token` |
| Admin User | `SFADMIN1@EmployeeHub.onmicrosoft.com` |

### 3.2 — Tools

| # | Tool | Type | Use Cases | Description | OData/REST Endpoint | Widget |
|---|---|---|---|---|---|---|
| 1 | `get_employee_profile` | Read | UC#32 | Employee personal + job + contact info | `GET /odata/v2/User('{uid}')?$expand=empInfo,personNav,jobInfoNav,emailNav,phoneNav` | `sf-employee-profile` |
| 2 | `get_leave_balances` | Read | UC#25, 33, 39 | Leave / time-account balances | `GET /odata/v2/EmpTimeAccountBalance?$filter=userId eq '{uid}'` | `sf-leave-balance` |
| 3 | `get_time_off_history` | Read | UC#25 | Historical time-off records | `GET /odata/v2/EmployeeTime?$filter=userId eq '{uid}'&$orderby=startDate desc` | `sf-time-off-history` |
| 4 | `prepare_book_leave` | Widget | UC#36 | Interactive leave booking form | *(client-side — no API call)* | `sf-leave-booking` |
| 5 | `book_leave` | Callback | UC#36 | Submit leave request → manager approval | `POST /odata/v2/EmployeeTime` | — |
| 6 | `prepare_change_personal_data` | Widget | UC#35, 30 | Form to update address/phone/email | *(client-side)* | `sf-personal-data-form` |
| 7 | `change_personal_data` | Callback | UC#35, 30, 41 | Update personal data in SF | `PATCH /odata/v2/PerPersonal(...)` | — |
| 8 | `get_org_chart` | Read | UC#26, 37 | Manager chain + direct reports | `GET /odata/v2/User('{uid}')?$expand=directReports,manager` | `sf-org-chart` |
| 9 | `get_pay_stubs` | Read | UC#40 | Recent payslips list | `GET /odata/v2/EmployeePayrollRunResults?$filter=userId eq '{uid}'&$orderby=payDate desc&$top=6` | `sf-payslip-list` |
| 10 | `get_pay_stub_detail` | Read | UC#40 | Single payslip: earnings, deductions, net | `GET /odata/v2/EmployeePayrollRunResults('{id}')?$expand=runResultsItems` | `sf-payslip-detail` |
| 11 | `prepare_move_employee` | Widget | UC#37 | Form to move employee to new position | *(client-side)* | `sf-move-employee` |
| 12 | `move_employee` | Callback | UC#37 | Submit employee move | `POST /odata/v2/EmpJob` | — |
| 13 | `update_hierarchy` | Callback | UC#26 | Submit hierarchy change (new manager/CC) | `PATCH /odata/v2/EmpJob` | — |
| 14 | `trigger_background_check` | Action | UC#28 | Trigger background check in SF | `POST /odata/v2/Background_SpecialAssign` | — |
| 15 | `get_background_check_status` | Read | UC#27 | Poll background check result | `GET /odata/v2/Background_SpecialAssign?$filter=personIdExternal eq '{id}'` | — |
| 16 | `manage_position` | Callback | UC#29 | Create/modify position | `POST /odata/v2/Position` | — |
| 17 | `request_leave_carryover` | Callback | UC#31 | Submit leave carryover | `PATCH /odata/v2/EmployeeTimeValuationResult` | — |
| 18 | `get_employee_documents` | Read | UC#42, 43 | List employee documents | `GET /odata/v2/Attachment?$filter=userId eq '{uid}'` | `sf-document-list` |
| 19 | `generate_employment_verification` | Action | UC#42 | Trigger verification letter (US) | Triggers SF workflow | — |
| 20 | `generate_employment_reference` | Action | UC#43 | Trigger reference letter (UK) | Triggers SF workflow | — |

### 3.3 — Widgets (8)

`sf-employee-profile`, `sf-leave-balance`, `sf-time-off-history`, `sf-leave-booking`, `sf-personal-data-form`, `sf-org-chart`, `sf-payslip-list`, `sf-payslip-detail`, `sf-move-employee`, `sf-document-list`

### 3.4 — Environment File (`env/sap_sf.env`)

```env
SAP_SF_ODATA_URL=https://apisalesdemo8.successfactors.com/odata/v2
SAP_SF_TOKEN_URL=https://apisalesdemo8.successfactors.com/oauth/token
SAP_SF_COMPANY_ID=SFCPART001804
SAP_SF_CLIENT_ID=MWVmMjcxZTM2OTlmYzM3ZjFhODk3MGU1ZGEyOA
SAP_SF_RESOURCE_URI=api://32e5479e-d82d-4241-943b-4d42279547f4
```

---

## 4 — SAP Ariba MCP Server (`ariba`) — NEW

### 4.1 — Authentication

**No OAuth flow.** The Ariba Sandbox uses a static API key passed as a header on every request. The key is configured via `.env` — it cannot be passed from the declarative agent.

```
Agent → [Entra token — ignored for Ariba] → ariba MCP server → [API key header] → Ariba Sandbox
```

**Sandbox:** `https://sandbox.api.sap.com/ariba/api/`

### 4.2 — Tools

| # | Tool | Type | Use Cases | Description | API Endpoint | Widget |
|---|---|---|---|---|---|---|
| 1 | `get_invoice_status` | Read | UC#10, 16 | Invoice payment status | `GET /procurement/v2/invoices?realm={realm}` | `ariba-invoice-status` |
| 2 | `get_po_status` | Read | UC#11 | PO status | `GET /procurement/v2/purchaseOrders?realm={realm}` | `ariba-po-status` |
| 3 | `reject_invoice` | Action | UC#12, 17 | Reject an invoice | `POST /procurement/v2/invoices/{id}/reject` | `ariba-confirm-action` |
| 4 | `close_purchase_order` | Action | UC#13 | Close a PO | `POST /procurement/v2/purchaseOrders/{id}/close` | `ariba-confirm-action` |
| 5 | `list_receipts` | Read | UC#18 | Goods receipts for a PO | `GET /procurement/v2/receipts?realm={realm}` | `ariba-receipt-list` |
| 6 | `prepare_create_receipt` | Widget | UC#18 | Goods receipt form | *(client-side)* | `ariba-create-receipt` |
| 7 | `create_receipt` | Callback | UC#18 | Post goods receipt | `POST /procurement/v2/receipts` | — |
| 8 | `list_requisitions` | Read | UC#20 | Purchase requisitions | `GET /procurement/v2/requisitions?realm={realm}` | `ariba-requisition-list` |
| 9 | `prepare_create_requisition` | Widget | UC#20 | PR creation form | *(client-side)* | `ariba-create-requisition` |
| 10 | `create_requisition` | Callback | UC#20 | Submit PR | `POST /procurement/v2/requisitions` | — |
| 11 | `update_requisition` | Action | UC#20 | Update existing PR | `PATCH /procurement/v2/requisitions/{id}` | — |
| 12 | `list_catalog_items` | Read | UC#22 | Search procurement catalog | `GET /procurement/v2/catalogItems?realm={realm}` | `ariba-catalog-search` |
| 13 | `order_catalog_item` | Callback | UC#22 | Create PR from catalog item | `POST /procurement/v2/requisitions` | — |
| 14 | `list_suppliers` | Read | UC#44, 49 | Search supplier master | `GET /sourcing/v1/suppliers?realm={realm}` | `ariba-supplier-list` |
| 15 | `get_supplier` | Read | UC#47-49 | Supplier detail | `GET /sourcing/v1/suppliers/{id}` | `ariba-supplier-profile` |
| 16 | `update_supplier_address` | Action | UC#45, 47 | Update supplier address | `PATCH /sourcing/v1/suppliers/{id}` | — |
| 17 | `update_supplier_bank` | Action | UC#48 | Update supplier bank | `PATCH /sourcing/v1/suppliers/{id}` | — |
| 18 | `register_supplier` | Callback | UC#44, 49 | Register/onboard supplier | `POST /sourcing/v1/suppliers` | `ariba-supplier-registration` |
| 19 | `transfer_purchase_order` | Action | UC#46 | Transfer PO to new owner | `POST /procurement/v2/purchaseOrders/{id}/transfer` | — |
| 20 | `list_approvals` | Read | — | Pending approvals | `GET /approve/v1/pendingApprovables?realm={realm}` | `ariba-approval-list` |
| 21 | `approve_reject` | Action | — | Approve or reject | `POST /approve/v1/approve` or `/reject` | — |

### 4.3 — Widgets (10)

`ariba-invoice-status`, `ariba-po-status`, `ariba-confirm-action`, `ariba-receipt-list`, `ariba-create-receipt`, `ariba-requisition-list`, `ariba-create-requisition`, `ariba-catalog-search`, `ariba-supplier-list`, `ariba-supplier-profile`, `ariba-supplier-registration`, `ariba-approval-list`

### 4.4 — Environment File (`env/ariba.env`)

```env
ARIBA_API_URL=https://sandbox.api.sap.com/ariba/api
ARIBA_API_KEY=PjD4inBW67Em4fc5rw8fQs9hAXzyRmTQ
ARIBA_REALM=mytestrealm
```

---

## 5 — Coupa MCP Server (`coupa`) — NEW (Fully Mocked)

### 5.1 — Authentication & Mocking

**All tools return mock data.** There is no Coupa sandbox available. Each tool function returns realistic sample data matching the real Coupa REST API response shapes documented at [docs.coupa.com](https://docs.coupa.com/en/developer-documentation/the-coupa-core-api).

The mock layer should be clearly structured so it can be swapped for real API calls if a Coupa instance becomes available. Use a `_mock_response(endpoint, params)` helper that returns canned JSON.

### 5.2 — Tools

The Coupa tools **mirror the Ariba tools exactly** (same names, same parameters, same widgets) so the declarative agent can route P2P queries to either platform:

| # | Tool | Type | Use Cases | Description | Widget |
|---|---|---|---|---|---|
| 1 | `get_invoice_status` | Read | UC#10, 14 | Invoice payment status (mocked) | `coupa-invoice-status` |
| 2 | `get_po_status` | Read | UC#11 | PO status (mocked) | `coupa-po-status` |
| 3 | `reject_invoice` | Action | UC#12, 15 | Reject invoice (mocked) | `coupa-confirm-action` |
| 4 | `close_purchase_order` | Action | UC#13 | Close PO (mocked) | `coupa-confirm-action` |
| 5 | `list_receipts` | Read | UC#19 | Goods receipts (mocked) | `coupa-receipt-list` |
| 6 | `prepare_create_receipt` | Widget | UC#19 | Goods receipt form | `coupa-create-receipt` |
| 7 | `create_receipt` | Callback | UC#19 | Post goods receipt (mocked) | — |
| 8 | `list_requisitions` | Read | UC#21 | Purchase requisitions (mocked) | `coupa-requisition-list` |
| 9 | `prepare_create_requisition` | Widget | UC#21 | PR creation form | `coupa-create-requisition` |
| 10 | `create_requisition` | Callback | UC#21 | Submit PR (mocked) | — |
| 11 | `update_requisition` | Action | UC#21 | Update PR (mocked) | — |
| 12 | `list_catalog_items` | Read | UC#22 | Search catalog (mocked) | `coupa-catalog-search` |
| 13 | `order_catalog_item` | Callback | UC#22 | Create PR from catalog (mocked) | — |
| 14 | `list_suppliers` | Read | UC#44, 49 | Search suppliers (mocked) | `coupa-supplier-list` |
| 15 | `get_supplier` | Read | UC#47-49 | Supplier detail (mocked) | `coupa-supplier-profile` |
| 16 | `update_supplier_address` | Action | UC#45, 47 | Update supplier address (mocked) | — |
| 17 | `update_supplier_bank` | Action | UC#48 | Update supplier bank (mocked) | — |
| 18 | `register_supplier` | Callback | UC#44, 49 | Register supplier (mocked) | `coupa-supplier-registration` |
| 19 | `transfer_purchase_order` | Action | UC#46 | Transfer PO (mocked) | — |
| 20 | `list_approvals` | Read | — | Pending approvals (mocked) | `coupa-approval-list` |
| 21 | `approve_reject` | Action | — | Approve or reject (mocked) | — |

### 5.3 — Widgets (10)

Same layout as Ariba but with Coupa branding: `coupa-invoice-status`, `coupa-po-status`, `coupa-confirm-action`, `coupa-receipt-list`, `coupa-create-receipt`, `coupa-requisition-list`, `coupa-create-requisition`, `coupa-catalog-search`, `coupa-supplier-list`, `coupa-supplier-profile`, `coupa-supplier-registration`, `coupa-approval-list`

### 5.4 — Environment File (`env/coupa.env`)

```env
# Coupa is fully mocked — no real credentials needed
COUPA_INSTANCE_URL=https://mock.coupahost.com
COUPA_MOCK=true
```

---

## 6 — ServiceNow Server — Enhancements

### 6.1 — No New Tools Needed for Knowledge Articles

Knowledge articles (UC#1, 5, 6, 23, 33, 34) are handled **natively** by the M365 Copilot declarative agent's knowledge source feature. The existing `search_knowledge` tool remains available for edge cases but the agent's instructions will prefer the native approach.

### 6.2 — Password Reset = Catalog Item

UC#4 (password reset) uses the **existing** `order_catalog_item` tool to submit a service catalog request. The catalog item in ServiceNow is pre-configured with a workflow that triggers the actual AD/Azure AD password reset. No custom REST endpoint needed.

### 6.3 — Existing Tools Already Cover Most IT/ERP Use Cases

| Use Case | Existing Tool |
|---|---|
| UC#2 — Coupa Access Request | `list_catalog_items` → `order_catalog_item` |
| UC#3 — New Software Request | `list_catalog_items` → `order_catalog_item` |
| UC#4 — Password Reset | `order_catalog_item` (specific catalog item) |

### 6.4 — ServiceNow No Code Changes Needed

The existing ServiceNow MCP server already provides comprehensive catalog, incident, change, problem, approval, and KB tools. The SFD use cases for ServiceNow map cleanly to existing tools. **No new ServiceNow tools or widgets are required.**

---

## 7 — Cross-Server Orchestration Patterns

These patterns describe how the declarative agent combines tools from multiple MCP servers for complex use cases:

### Pattern A: ServiceNow Approval → SuccessFactors Write

**Use cases:** UC#26, 29, 31, 41

```
User → Agent → servicenow.order_catalog_item()  → [SN approval workflow]
                                                        ↓ (approved)
               Agent → sap_sf.update_hierarchy() / manage_position() / change_personal_data()
```

### Pattern B: Knowledge + Data Blend

**Use case:** UC#33 (Annual leave policy + remaining days)

```
User: "What is the leave policy and how many days do I have left?"
Agent → [native KB search: "annual leave policy"]  → policy text
Agent → sap_sf.get_leave_balances()                 → remaining days
Agent → blended response to user
```

### Pattern C: Dual P2P Platform

**Use cases:** UC#10-13, 22

```
User: "What is the status of invoice INV-12345?"
Agent → determine platform (ask user if unclear: "Is this an Ariba or Coupa invoice?")
Agent → ariba.get_invoice_status(number="INV-12345")
   OR → coupa.get_invoice_status(number="INV-12345")
```

---

## 8 — Coding Conventions

### 8.1 — TOOL_SPECS Format (match existing pattern exactly)

```python
SAP_SF_TOOL_SPECS: list[dict] = [
    {
        "name": "get_employee_profile",
        "summary": (
            "Get the current employee's personal and employment details from "
            "SAP SuccessFactors, including name, job title, department, location, "
            "contact info, and hire date. Results are rendered as an interactive widget."
        ),
        "func": tool_get_employee_profile,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/sf-employee-profile.html",
            "openai/toolInvocation/invoking": "Loading employee profile…",
            "openai/toolInvocation/invoked": "Profile ready.",
        },
    },
    # ...
]
```

### 8.2 — Tool Handler Pattern

```python
async def tool_get_employee_profile(
    user_id: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Get employee profile from SAP SuccessFactors."""
    token = get_bearer_token(ctx)
    sap_token = await exchange_token_for_sap(token)  # Entra → SAP exchange
    settings = load_sap_sf_settings()

    url = f"{settings.odata_url}/User('{user_id or 'me'}')"
    params = {
        "$expand": "empInfo,personNav,jobInfoNav,emailNav,phoneNav",
        "$format": "json",
    }

    async with create_async_client() as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {sap_token}"},
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

    return _transform_employee(data)
```

### 8.3 — Ariba Tool Handler Pattern (API key)

```python
async def tool_get_invoice_status(
    invoice_number: str,
    ctx: Context | None = None,
) -> dict:
    """Get invoice payment status from SAP Ariba."""
    settings = load_ariba_settings()

    async with create_async_client() as client:
        resp = await client.get(
            f"{settings.api_url}/procurement/v2/invoices",
            headers={"apiKey": settings.api_key},
            params={"realm": settings.realm, "$filter": f"invoiceNumber eq '{invoice_number}'"},
        )
        resp.raise_for_status()
        return resp.json()
```

### 8.4 — Coupa Mock Handler Pattern

```python
async def tool_get_invoice_status(
    invoice_number: str,
    ctx: Context | None = None,
) -> dict:
    """Get invoice payment status from Coupa (mocked)."""
    return _mock_response("invoices", {
        "id": 50412,
        "invoice-number": invoice_number,
        "status": "pending_approval",
        "total": "12,450.00",
        "currency": {"code": "GBP"},
        "supplier": {"name": "Acme Industrial Ltd", "number": "SUP-1042"},
        "invoice-date": "2026-03-15",
        "due-date": "2026-04-14",
        "payment-status": "Not Paid",
        "po-number": "PO-2026-0847",
    })
```

### 8.5 — Widget Pattern

All widgets go in `mcp_servers/src/mcp_servers/ui/widget/`. Follow the existing pattern:
- Dark/light mode via CSS custom properties + `data-theme` attribute
- Skybridge integration: `window.openai.toolOutput`, `sendFollowUpMessage()`
- Responsive layout, 14px base font, Segoe UI font stack
- Platform-specific accent colours (e.g., SAP orange `#f0ab00`, Ariba teal `#00b4d8`, Coupa blue `#0066cc`)

### 8.6 — server.py Pattern

```python
def build_sap_sf_server() -> FastMCP:
    mcp = FastMCP("sap_sf", instructions="SAP SuccessFactors employee self-service...")
    for spec in SAP_SF_TOOL_SPECS:
        kwargs = {"name": spec["name"], "description": spec["summary"]}
        if annotations := spec.get("annotations"):
            kwargs["annotations"] = annotations
        if meta := spec.get("meta"):
            kwargs["meta"] = meta
        mcp.tool(**kwargs)(spec["func"])
    for name, res in SAP_SF_RESOURCES.items():
        resource_kwargs = {
            "uri": f"ui://widget/{name}.html",
            "name": name,
            "description": res["description"],
            "mime_type": res["mime_type"],
            "text": res["content"],
        }
        if meta := res.get("meta"):
            resource_kwargs["meta"] = meta
        mcp.add_resource(TextResource(**resource_kwargs))
    return mcp
```

### 8.7 — General Rules

- **Bearer passthrough** — Never store tokens. Extract from MCP request headers, exchange/forward as needed.
- **Error handling** — Let httpx exceptions propagate; the AuthErrorPassthroughMiddleware in cli.py rewrites 401/403 for the declarative agent to trigger re-auth.
- **OData (SAP SF)** — Always `$format=json`. Use `$expand`, `$filter`, `$orderby`, `$top`, `$skip`.
- **Ariba** — Always include `realm={realm}` param and `apiKey` header.
- **Coupa** — All mocked. Return canned data matching Coupa REST API shapes.
- **Pagination** — Default 20-50 results. Support `$top/$skip` (OData) or `offset/limit` (REST).
- **Widget prefixes** — `sf-` for SAP SF, `ariba-` for Ariba, `coupa-` for Coupa (avoid collisions with existing widgets).

---

## 9 — Implementation Summary

| Server | Read | Widget | Callback | Action | Total |
|---|---|---|---|---|---|
| SAP SuccessFactors | 9 | 4 | 5 | 4 | **20** |
| SAP Ariba | 7 | 2 | 3 | 7 | **21** (2 sandboxed, rest may need mocking if sandbox limited) |
| Coupa (mocked) | 7 | 2 | 3 | 7 | **21** (all mocked) |
| ServiceNow | — | — | — | — | **0 changes** (existing tools cover SFD use cases) |
| **Totals** | **23** | **8** | **11** | **18** | **62 new tools** |

All 49 SFD use cases are covered across:
- 7 MCP servers (workday, servicenow, salesforce, jira, sap_sf, ariba, coupa)
- ~30 new interactive widgets
- The M365 Copilot declarative agent handles knowledge articles and routing natively
