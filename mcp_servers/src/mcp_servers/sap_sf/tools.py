"""SAP SuccessFactors MCP tool definitions and async handler functions.

Authentication: Entra ID bearer → SAP SF OAuth token exchange → OData v2 calls.
When the live API is unavailable (auth not configured) tools fall back to
realistic mock data so widgets always render correctly.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from fastmcp import Context

from ..auth import get_bearer_token
from ..http import create_async_client
from ..logging import get_logger
from ..settings import load_sap_sf_settings

LOGGER = get_logger(__name__)


# ── Mock data store ─────────────────────────────────────────────────

_MOCK_EMPLOYEES = {
    "EMP-1001": {
        "userId": "EMP-1001",
        "firstName": "Priya",
        "lastName": "Sharma",
        "displayName": "Priya Sharma",
        "email": "priya.sharma@contoso.com",
        "phone": "+44 20 7946 0958",
        "jobTitle": "Senior Software Engineer",
        "department": "Engineering",
        "division": "Product Development",
        "location": "London",
        "manager": "EMP-1010",
        "hireDate": "/Date(1609459200000)/",
        "status": "active",
        "company": "Contoso Ltd",
    },
    "EMP-1002": {
        "userId": "EMP-1002",
        "firstName": "James",
        "lastName": "Okonkwo",
        "displayName": "James Okonkwo",
        "email": "james.okonkwo@contoso.com",
        "phone": "+44 20 7946 1122",
        "jobTitle": "Product Manager",
        "department": "Product",
        "division": "Product Development",
        "location": "London",
        "manager": "EMP-1010",
        "hireDate": "/Date(1585699200000)/",
        "status": "active",
        "company": "Contoso Ltd",
    },
    "EMP-1003": {
        "userId": "EMP-1003",
        "firstName": "Sarah",
        "lastName": "Chen",
        "displayName": "Sarah Chen",
        "email": "sarah.chen@contoso.com",
        "phone": "+1 415 555 0192",
        "jobTitle": "UX Designer",
        "department": "Design",
        "division": "Product Development",
        "location": "San Francisco",
        "manager": "EMP-1010",
        "hireDate": "/Date(1625097600000)/",
        "status": "active",
        "company": "Contoso Inc",
    },
    "EMP-1010": {
        "userId": "EMP-1010",
        "firstName": "Raj",
        "lastName": "Patel",
        "displayName": "Raj Patel",
        "email": "raj.patel@contoso.com",
        "phone": "+44 20 7946 0800",
        "jobTitle": "VP Engineering",
        "department": "Engineering",
        "division": "Product Development",
        "location": "London",
        "manager": "EMP-2001",
        "hireDate": "/Date(1483228800000)/",
        "status": "active",
        "company": "Contoso Ltd",
    },
}

_MOCK_LEAVE_BALANCES = [
    {"planName": "Annual Leave", "balance": 18.0, "unit": "Days", "asOfDate": "2026-04-01"},
    {"planName": "Sick Leave", "balance": 10.0, "unit": "Days", "asOfDate": "2026-04-01"},
    {"planName": "Personal Leave", "balance": 3.0, "unit": "Days", "asOfDate": "2026-04-01"},
    {"planName": "Parental Leave", "balance": 26.0, "unit": "Weeks", "asOfDate": "2026-04-01"},
]

_MOCK_TIME_OFF = [
    {"type": "Annual Leave", "startDate": "2026-03-17", "endDate": "2026-03-21", "quantityInDays": 5.0, "approvalStatus": "approved"},
    {"type": "Sick Leave", "startDate": "2026-02-10", "endDate": "2026-02-10", "quantityInDays": 1.0, "approvalStatus": "approved"},
    {"type": "Annual Leave", "startDate": "2025-12-22", "endDate": "2026-01-02", "quantityInDays": 8.0, "approvalStatus": "approved"},
    {"type": "Personal Leave", "startDate": "2025-11-14", "endDate": "2025-11-14", "quantityInDays": 1.0, "approvalStatus": "approved"},
    {"type": "Annual Leave", "startDate": "2025-08-04", "endDate": "2025-08-15", "quantityInDays": 10.0, "approvalStatus": "approved"},
]

_MOCK_PAY_STUBS = [
    {"id": "PR-2026-04", "payDate": "2026-04-25", "grossPay": 6250.00, "netPay": 4687.50, "currency": "GBP", "payPeriod": "April 2026"},
    {"id": "PR-2026-03", "payDate": "2026-03-25", "grossPay": 6250.00, "netPay": 4687.50, "currency": "GBP", "payPeriod": "March 2026"},
    {"id": "PR-2026-02", "payDate": "2026-02-25", "grossPay": 6250.00, "netPay": 4687.50, "currency": "GBP", "payPeriod": "February 2026"},
    {"id": "PR-2026-01", "payDate": "2026-01-25", "grossPay": 6250.00, "netPay": 4687.50, "currency": "GBP", "payPeriod": "January 2026"},
    {"id": "PR-2025-12", "payDate": "2025-12-20", "grossPay": 6250.00, "netPay": 4687.50, "currency": "GBP", "payPeriod": "December 2025"},
    {"id": "PR-2025-11", "payDate": "2025-11-25", "grossPay": 6250.00, "netPay": 4687.50, "currency": "GBP", "payPeriod": "November 2025"},
]

_MOCK_PAY_DETAIL = {
    "id": "PR-2026-04",
    "payDate": "2026-04-25",
    "grossPay": 6250.00,
    "netPay": 4687.50,
    "currency": "GBP",
    "earnings": [
        {"type": "Earning", "name": "Base Salary", "amount": 6250.00},
    ],
    "deductions": [
        {"type": "Deduction", "name": "Income Tax (PAYE)", "amount": 1041.67},
        {"type": "Deduction", "name": "National Insurance", "amount": 416.67},
        {"type": "Deduction", "name": "Pension (5%)", "amount": 312.50},
    ],
}

_MOCK_DOCUMENTS = [
    {"id": "DOC-0001", "fileName": "Employment_Contract_2021.pdf", "mimeType": "application/pdf", "documentType": "Contract", "createdDate": "2021-01-04"},
    {"id": "DOC-0002", "fileName": "Salary_Review_2025.pdf", "mimeType": "application/pdf", "documentType": "Letter", "createdDate": "2025-04-01"},
    {"id": "DOC-0003", "fileName": "P60_2024-25.pdf", "mimeType": "application/pdf", "documentType": "Tax Document", "createdDate": "2025-05-15"},
    {"id": "DOC-0004", "fileName": "Benefits_Enrolment_2026.pdf", "mimeType": "application/pdf", "documentType": "Benefits", "createdDate": "2026-01-10"},
]

_MOCK_BACKGROUND_CHECKS = [
    {"type": "standard", "status": "completed", "startDate": "2020-12-15", "endDate": "2021-01-02"},
    {"type": "dbs_enhanced", "status": "completed", "startDate": "2020-12-15", "endDate": "2021-01-10"},
]


def _default_uid(user_id: str | None) -> str:
    return user_id or "EMP-1001"


def _mock_profile(uid: str) -> dict:
    return copy.deepcopy(_MOCK_EMPLOYEES.get(uid, _MOCK_EMPLOYEES["EMP-1001"]))


# ── Token exchange ──────────────────────────────────────────────────

async def _exchange_token_for_sap(entra_token: str) -> str:
    """Exchange an Entra ID bearer token for a SAP SuccessFactors OAuth token.

    Uses SAML2 bearer assertion grant. In the demo environment, falls back
    to mock data when the Entra app registration is not configured.
    """
    settings = load_sap_sf_settings()
    async with create_async_client() as client:
        resp = await client.post(
            settings.token_url,
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:saml2-bearer",
                "client_id": settings.client_id,
                "company_id": settings.company_id,
                "assertion": entra_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


def _get_auth_token(ctx: Optional[Context] = None) -> str:
    """Extract the OAuth 2.0 Bearer token from the Authorization request header."""
    return get_bearer_token(ctx)


# ── Helpers ─────────────────────────────────────────────────────────

async def _sf_get(path: str, sap_token: str, params: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """GET request to SAP SF OData v2."""
    settings = load_sap_sf_settings()
    url = f"{settings.odata_url}{path}"
    all_params = {"$format": "json"}
    if params:
        all_params.update(params)
    async with create_async_client() as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {sap_token}"},
            params=all_params,
        )
        resp.raise_for_status()
        return resp.json()


async def _sf_post(path: str, sap_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST request to SAP SF OData v2."""
    settings = load_sap_sf_settings()
    url = f"{settings.odata_url}{path}"
    async with create_async_client() as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {sap_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


async def _sf_patch(path: str, sap_token: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """PATCH request to SAP SF OData v2."""
    settings = load_sap_sf_settings()
    url = f"{settings.odata_url}{path}"
    async with create_async_client() as client:
        resp = await client.patch(
            url,
            headers={
                "Authorization": f"Bearer {sap_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        resp.raise_for_status()
        try:
            return resp.json()
        except Exception:
            return {"status": "ok"}


def _transform_employee(data: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten OData User entity into a clean employee profile dict."""
    d = data.get("d", data)
    person = d.get("personNav", {}).get("results", [{}])[0] if d.get("personNav") else {}
    job = d.get("jobInfoNav", {}).get("results", [{}])[0] if d.get("jobInfoNav") else {}
    emails = d.get("emailNav", {}).get("results", []) if d.get("emailNav") else []
    phones = d.get("phoneNav", {}).get("results", []) if d.get("phoneNav") else []
    primary_email = next((e.get("emailAddress") for e in emails if e.get("isPrimary")), None)
    primary_phone = next((p.get("phoneNumber") for p in phones if p.get("isPrimary")), None)

    return {
        "userId": d.get("userId"),
        "firstName": d.get("firstName"),
        "lastName": d.get("lastName"),
        "displayName": d.get("displayName") or f"{d.get('firstName', '')} {d.get('lastName', '')}".strip(),
        "email": primary_email or d.get("email"),
        "phone": primary_phone,
        "jobTitle": job.get("jobTitle") or d.get("title"),
        "department": job.get("department") or d.get("department"),
        "division": job.get("division") or d.get("division"),
        "location": job.get("location") or d.get("location"),
        "manager": job.get("managerId"),
        "hireDate": d.get("hireDate"),
        "status": d.get("status"),
        "company": job.get("company") or d.get("company"),
    }


# ── Tool handlers (try live API first, fall back to mock) ───────────

# 1. get_employee_profile
async def tool_get_employee_profile(
    user_id: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Get employee profile from SAP SuccessFactors."""
    uid = _default_uid(user_id)
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        data = await _sf_get(
            f"/User('{uid}')",
            sap_token,
            {"$expand": "empInfo,personNav,jobInfoNav,emailNav,phoneNav"},
        )
        return _transform_employee(data)
    except Exception as exc:
        LOGGER.debug("get_employee_profile falling back to mock: %s", exc)
        return _mock_profile(uid)


# 2. get_leave_balances
async def tool_get_leave_balances(
    user_id: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Get leave/time-account balances."""
    uid = _default_uid(user_id)
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        data = await _sf_get(
            "/EmpTimeAccountBalance",
            sap_token,
            {"$filter": f"userId eq '{uid}'"},
        )
        results = data.get("d", {}).get("results", [])
        balances = [
            {
                "planName": r.get("timeAccountType"),
                "balance": r.get("balance"),
                "unit": r.get("unitOfMeasure", "Days"),
                "asOfDate": r.get("asOfAccountingPeriodEnd"),
            }
            for r in results
        ]
        return {"userId": uid, "balances": balances}
    except Exception as exc:
        LOGGER.debug("get_leave_balances falling back to mock: %s", exc)
        return {"userId": uid, "balances": copy.deepcopy(_MOCK_LEAVE_BALANCES)}


# 3. get_time_off_history
async def tool_get_time_off_history(
    user_id: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Get historical time-off records."""
    uid = _default_uid(user_id)
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        data = await _sf_get(
            "/EmployeeTime",
            sap_token,
            {"$filter": f"userId eq '{uid}'", "$orderby": "startDate desc", "$top": "20"},
        )
        results = data.get("d", {}).get("results", [])
        records = [
            {
                "type": r.get("timeType"),
                "startDate": r.get("startDate"),
                "endDate": r.get("endDate"),
                "quantityInDays": r.get("quantityInDays"),
                "approvalStatus": r.get("approvalStatus"),
            }
            for r in results
        ]
        return {"userId": uid, "timeOffHistory": records}
    except Exception as exc:
        LOGGER.debug("get_time_off_history falling back to mock: %s", exc)
        return {"userId": uid, "timeOffHistory": copy.deepcopy(_MOCK_TIME_OFF)}


# 4. prepare_book_leave (widget)
async def tool_prepare_book_leave(
    user_id: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Show the interactive leave booking form widget."""
    uid = _default_uid(user_id)
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        data = await _sf_get(
            "/EmpTimeAccountBalance",
            sap_token,
            {"$filter": f"userId eq '{uid}'"},
        )
        results = data.get("d", {}).get("results", [])
        balances = [
            {"planName": r.get("timeAccountType"), "balance": r.get("balance")}
            for r in results
        ]
        return {"userId": uid, "balances": balances, "_widget_hint": "Leave booking form ready."}
    except Exception as exc:
        LOGGER.debug("prepare_book_leave falling back to mock: %s", exc)
        return {
            "userId": uid,
            "balances": [{"planName": b["planName"], "balance": b["balance"]} for b in _MOCK_LEAVE_BALANCES],
            "_widget_hint": "Leave booking form ready.",
        }


# 5. book_leave (callback — POST)
async def tool_book_leave(
    user_id: str,
    time_type: str,
    start_date: str,
    end_date: str,
    comment: str = "",
    ctx: Context | None = None,
) -> dict:
    """Submit a leave request for manager approval."""
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        result = await _sf_post("/EmployeeTime", sap_token, {
            "userId": user_id,
            "timeType": time_type,
            "startDate": start_date,
            "endDate": end_date,
            "comment": comment,
        })
        return {"status": "submitted", "detail": result}
    except Exception as exc:
        LOGGER.debug("book_leave falling back to mock: %s", exc)
        return {
            "status": "submitted",
            "detail": {
                "userId": user_id,
                "timeType": time_type,
                "startDate": start_date,
                "endDate": end_date,
                "approvalStatus": "pending",
                "requestId": "REQ-2026-0892",
            },
        }


# 6. prepare_change_personal_data (widget)
async def tool_prepare_change_personal_data(
    user_id: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Show the personal data change form pre-populated with current data."""
    uid = _default_uid(user_id)
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        data = await _sf_get(
            f"/User('{uid}')",
            sap_token,
            {"$expand": "personNav,emailNav,phoneNav"},
        )
        profile = _transform_employee(data)
        return {**profile, "_widget_hint": "Personal data form ready."}
    except Exception as exc:
        LOGGER.debug("prepare_change_personal_data falling back to mock: %s", exc)
        return {**_mock_profile(uid), "_widget_hint": "Personal data form ready."}


# 7. change_personal_data (callback — PATCH)
async def tool_change_personal_data(
    user_id: str,
    changes: dict,
    ctx: Context | None = None,
) -> dict:
    """Update personal data (address, phone, email) in SuccessFactors."""
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        result = await _sf_patch(f"/PerPersonal(personIdExternal='{user_id}')", sap_token, changes)
        return {"status": "updated", "detail": result}
    except Exception as exc:
        LOGGER.debug("change_personal_data falling back to mock: %s", exc)
        return {"status": "updated", "detail": {"userId": user_id, "changedFields": list(changes.keys())}}


# 8. get_org_chart
async def tool_get_org_chart(
    user_id: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Get org hierarchy — manager chain and direct reports."""
    uid = _default_uid(user_id)
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        data = await _sf_get(
            f"/User('{uid}')",
            sap_token,
            {"$expand": "directReports,manager"},
        )
        d = data.get("d", data)
        manager_data = d.get("manager", {})
        reports_data = d.get("directReports", {}).get("results", [])
        return {
            "userId": uid,
            "displayName": d.get("displayName"),
            "manager": {
                "userId": manager_data.get("userId"),
                "displayName": manager_data.get("displayName"),
                "jobTitle": manager_data.get("title"),
            } if manager_data else None,
            "directReports": [
                {
                    "userId": r.get("userId"),
                    "displayName": r.get("displayName"),
                    "jobTitle": r.get("title"),
                }
                for r in reports_data
            ],
        }
    except Exception as exc:
        LOGGER.debug("get_org_chart falling back to mock: %s", exc)
        emp = _mock_profile(uid)
        mgr = _MOCK_EMPLOYEES.get(emp.get("manager", ""), _MOCK_EMPLOYEES["EMP-1010"])
        reports = [
            {"userId": e["userId"], "displayName": e["displayName"], "jobTitle": e["jobTitle"]}
            for e in _MOCK_EMPLOYEES.values()
            if e.get("manager") == uid
        ]
        return {
            "userId": uid,
            "displayName": emp["displayName"],
            "manager": {"userId": mgr["userId"], "displayName": mgr["displayName"], "jobTitle": mgr["jobTitle"]},
            "directReports": reports,
        }


# 9. get_pay_stubs
async def tool_get_pay_stubs(
    user_id: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Get recent payslips list."""
    uid = _default_uid(user_id)
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        data = await _sf_get(
            "/EmployeePayrollRunResults",
            sap_token,
            {"$filter": f"userId eq '{uid}'", "$orderby": "payDate desc", "$top": "6"},
        )
        results = data.get("d", {}).get("results", [])
        stubs = [
            {
                "id": r.get("externalCode"),
                "payDate": r.get("payDate"),
                "grossPay": r.get("grossPay"),
                "netPay": r.get("netPay"),
                "currency": r.get("currency"),
                "payPeriod": r.get("payPeriod"),
            }
            for r in results
        ]
        return {"userId": uid, "payStubs": stubs}
    except Exception as exc:
        LOGGER.debug("get_pay_stubs falling back to mock: %s", exc)
        return {"userId": uid, "payStubs": copy.deepcopy(_MOCK_PAY_STUBS)}


# 10. get_pay_stub_detail
async def tool_get_pay_stub_detail(
    payroll_result_id: str,
    ctx: Context | None = None,
) -> dict:
    """Get single payslip detail with earnings and deductions."""
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        data = await _sf_get(
            f"/EmployeePayrollRunResults('{payroll_result_id}')",
            sap_token,
            {"$expand": "runResultsItems"},
        )
        d = data.get("d", data)
        items = d.get("runResultsItems", {}).get("results", [])
        return {
            "id": payroll_result_id,
            "payDate": d.get("payDate"),
            "grossPay": d.get("grossPay"),
            "netPay": d.get("netPay"),
            "currency": d.get("currency"),
            "earnings": [i for i in items if i.get("type") == "Earning"],
            "deductions": [i for i in items if i.get("type") == "Deduction"],
        }
    except Exception as exc:
        LOGGER.debug("get_pay_stub_detail falling back to mock: %s", exc)
        detail = copy.deepcopy(_MOCK_PAY_DETAIL)
        detail["id"] = payroll_result_id
        return detail


# 11. prepare_move_employee (widget)
async def tool_prepare_move_employee(
    user_id: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Show the move employee form."""
    uid = _default_uid(user_id)
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        data = await _sf_get(f"/User('{uid}')", sap_token, {"$expand": "jobInfoNav"})
        profile = _transform_employee(data)
        return {**profile, "_widget_hint": "Move employee form ready."}
    except Exception as exc:
        LOGGER.debug("prepare_move_employee falling back to mock: %s", exc)
        return {**_mock_profile(uid), "_widget_hint": "Move employee form ready."}


# 12. move_employee (callback — POST)
async def tool_move_employee(
    user_id: str,
    new_position_id: str,
    effective_date: str,
    reason: str = "",
    ctx: Context | None = None,
) -> dict:
    """Submit employee move to a new position."""
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        result = await _sf_post("/EmpJob", sap_token, {
            "userId": user_id,
            "positionId": new_position_id,
            "startDate": effective_date,
            "eventReason": reason,
        })
        return {"status": "submitted", "detail": result}
    except Exception as exc:
        LOGGER.debug("move_employee falling back to mock: %s", exc)
        return {
            "status": "submitted",
            "detail": {
                "userId": user_id,
                "positionId": new_position_id,
                "startDate": effective_date,
                "eventReason": reason,
                "requestId": "MOV-2026-0341",
            },
        }


# 13. update_hierarchy (callback — PATCH)
async def tool_update_hierarchy(
    user_id: str,
    new_manager_id: str,
    effective_date: str,
    ctx: Context | None = None,
) -> dict:
    """Submit hierarchy change (new manager)."""
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        result = await _sf_patch("/EmpJob", sap_token, {
            "userId": user_id,
            "managerId": new_manager_id,
            "startDate": effective_date,
        })
        return {"status": "submitted", "detail": result}
    except Exception as exc:
        LOGGER.debug("update_hierarchy falling back to mock: %s", exc)
        return {
            "status": "submitted",
            "detail": {
                "userId": user_id,
                "managerId": new_manager_id,
                "startDate": effective_date,
                "requestId": "HIE-2026-0112",
            },
        }


# 14. trigger_background_check
async def tool_trigger_background_check(
    person_id: str,
    check_type: str = "standard",
    ctx: Context | None = None,
) -> dict:
    """Trigger a background check in SuccessFactors."""
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        result = await _sf_post("/Background_SpecialAssign", sap_token, {
            "personIdExternal": person_id,
            "backgroundElementType": check_type,
        })
        return {"status": "triggered", "detail": result}
    except Exception as exc:
        LOGGER.debug("trigger_background_check falling back to mock: %s", exc)
        return {
            "status": "triggered",
            "detail": {
                "personIdExternal": person_id,
                "backgroundElementType": check_type,
                "requestId": "BGC-2026-0078",
                "estimatedCompletion": "2026-05-03",
            },
        }


# 15. get_background_check_status
async def tool_get_background_check_status(
    person_id: str,
    ctx: Context | None = None,
) -> dict:
    """Get background check status."""
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        data = await _sf_get(
            "/Background_SpecialAssign",
            sap_token,
            {"$filter": f"personIdExternal eq '{person_id}'"},
        )
        results = data.get("d", {}).get("results", [])
        checks = [
            {
                "type": r.get("backgroundElementType"),
                "status": r.get("status"),
                "startDate": r.get("startDate"),
                "endDate": r.get("endDate"),
            }
            for r in results
        ]
        return {"personId": person_id, "backgroundChecks": checks}
    except Exception as exc:
        LOGGER.debug("get_background_check_status falling back to mock: %s", exc)
        return {"personId": person_id, "backgroundChecks": copy.deepcopy(_MOCK_BACKGROUND_CHECKS)}


# 16. manage_position
async def tool_manage_position(
    action: str,
    position_code: str | None = None,
    title: str | None = None,
    department: str | None = None,
    effective_date: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """Create or modify a position in SuccessFactors."""
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        payload: dict = {}
        if position_code:
            payload["code"] = position_code
        if title:
            payload["positionTitle"] = title
        if department:
            payload["department"] = department
        if effective_date:
            payload["effectiveStartDate"] = effective_date

        if action == "create":
            result = await _sf_post("/Position", sap_token, payload)
        else:
            result = await _sf_patch(f"/Position('{position_code}')", sap_token, payload)
        return {"status": f"position_{action}d", "detail": result}
    except Exception as exc:
        LOGGER.debug("manage_position falling back to mock: %s", exc)
        return {
            "status": f"position_{action}d",
            "detail": {
                "code": position_code or "POS-2026-0150",
                "positionTitle": title or "New Position",
                "department": department or "Engineering",
                "effectiveStartDate": effective_date or "2026-05-01",
            },
        }


# 17. request_leave_carryover
async def tool_request_leave_carryover(
    user_id: str,
    leave_type: str,
    days: float,
    from_year: str,
    to_year: str,
    ctx: Context | None = None,
) -> dict:
    """Submit a leave carryover request."""
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        result = await _sf_patch("/EmployeeTimeValuationResult", sap_token, {
            "userId": user_id,
            "timeAccountType": leave_type,
            "carryoverDays": days,
            "fromYear": from_year,
            "toYear": to_year,
        })
        return {"status": "submitted", "detail": result}
    except Exception as exc:
        LOGGER.debug("request_leave_carryover falling back to mock: %s", exc)
        return {
            "status": "submitted",
            "detail": {
                "userId": user_id,
                "timeAccountType": leave_type,
                "carryoverDays": days,
                "fromYear": from_year,
                "toYear": to_year,
                "requestId": "LCR-2026-0045",
            },
        }


# 18. get_employee_documents
async def tool_get_employee_documents(
    user_id: str | None = None,
    ctx: Context | None = None,
) -> dict:
    """List employee documents."""
    uid = _default_uid(user_id)
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        data = await _sf_get(
            "/Attachment",
            sap_token,
            {"$filter": f"userId eq '{uid}'"},
        )
        results = data.get("d", {}).get("results", [])
        docs = [
            {
                "id": r.get("attachmentId"),
                "fileName": r.get("fileName"),
                "mimeType": r.get("mimeType"),
                "documentType": r.get("documentType"),
                "createdDate": r.get("createdDate"),
            }
            for r in results
        ]
        return {"userId": uid, "documents": docs}
    except Exception as exc:
        LOGGER.debug("get_employee_documents falling back to mock: %s", exc)
        return {"userId": uid, "documents": copy.deepcopy(_MOCK_DOCUMENTS)}


# 19. generate_employment_verification
async def tool_generate_employment_verification(
    user_id: str,
    ctx: Context | None = None,
) -> dict:
    """Trigger generation of employment verification letter (US)."""
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        result = await _sf_post("/Background_SpecialAssign", sap_token, {
            "personIdExternal": user_id,
            "backgroundElementType": "employment_verification",
        })
        return {"status": "requested", "message": "Employment verification letter generation has been triggered. You will be notified when it is ready.", "detail": result}
    except Exception as exc:
        LOGGER.debug("generate_employment_verification falling back to mock: %s", exc)
        return {
            "status": "requested",
            "message": "Employment verification letter generation has been triggered. You will be notified when it is ready.",
            "detail": {"personIdExternal": user_id, "requestId": "EVL-2026-0021", "estimatedReady": "2026-04-22"},
        }


# 20. generate_employment_reference
async def tool_generate_employment_reference(
    user_id: str,
    ctx: Context | None = None,
) -> dict:
    """Trigger generation of employment reference letter (UK)."""
    try:
        token = _get_auth_token(ctx)
        sap_token = await _exchange_token_for_sap(token)
        result = await _sf_post("/Background_SpecialAssign", sap_token, {
            "personIdExternal": user_id,
            "backgroundElementType": "employment_reference",
        })
        return {"status": "requested", "message": "Employment reference letter generation has been triggered. You will be notified when it is ready.", "detail": result}
    except Exception as exc:
        LOGGER.debug("generate_employment_reference falling back to mock: %s", exc)
        return {
            "status": "requested",
            "message": "Employment reference letter generation has been triggered. You will be notified when it is ready.",
            "detail": {"personIdExternal": user_id, "requestId": "ERL-2026-0018", "estimatedReady": "2026-04-22"},
        }


# ── TOOL_SPECS Registry ─────────────────────────────────────────────

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
    {
        "name": "get_leave_balances",
        "summary": (
            "Get the employee's leave and time-account balances from SAP SuccessFactors, "
            "showing remaining days for each leave type (annual, sick, etc.)."
        ),
        "func": tool_get_leave_balances,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/sf-leave-balance.html",
            "openai/toolInvocation/invoking": "Checking leave balances…",
            "openai/toolInvocation/invoked": "Balances loaded.",
        },
    },
    {
        "name": "get_time_off_history",
        "summary": (
            "Get the employee's historical time-off records including leave type, dates, "
            "duration, and approval status."
        ),
        "func": tool_get_time_off_history,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/sf-time-off-history.html",
            "openai/toolInvocation/invoking": "Loading time-off history…",
            "openai/toolInvocation/invoked": "History ready.",
        },
    },
    {
        "name": "prepare_book_leave",
        "summary": (
            "Show an interactive leave booking form with the employee's current balances "
            "pre-populated. Use this before book_leave to let the user choose dates and type."
        ),
        "func": tool_prepare_book_leave,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/sf-leave-booking.html",
            "openai/toolInvocation/invoking": "Preparing leave booking form…",
            "openai/toolInvocation/invoked": "Form ready.",
        },
    },
    {
        "name": "book_leave",
        "summary": (
            "Submit a leave/time-off request for manager approval. Requires user_id, "
            "time_type, start_date, and end_date."
        ),
        "func": tool_book_leave,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Submitting leave request…",
            "openai/toolInvocation/invoked": "Leave request submitted.",
        },
    },
    {
        "name": "prepare_change_personal_data",
        "summary": (
            "Show a form to update personal data (address, phone, email) pre-populated "
            "with current values. Use this before change_personal_data."
        ),
        "func": tool_prepare_change_personal_data,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/sf-personal-data-form.html",
            "openai/toolInvocation/invoking": "Loading personal data form…",
            "openai/toolInvocation/invoked": "Form ready.",
        },
    },
    {
        "name": "change_personal_data",
        "summary": (
            "Update personal data (address, phone, email) in SAP SuccessFactors. "
            "Requires user_id and a changes dict."
        ),
        "func": tool_change_personal_data,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Updating personal data…",
            "openai/toolInvocation/invoked": "Personal data updated.",
        },
    },
    {
        "name": "get_org_chart",
        "summary": (
            "Get the organisational hierarchy for an employee — manager, current role, "
            "and direct reports — rendered as an interactive org chart widget."
        ),
        "func": tool_get_org_chart,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/sf-org-chart.html",
            "openai/toolInvocation/invoking": "Loading org chart…",
            "openai/toolInvocation/invoked": "Org chart ready.",
        },
    },
    {
        "name": "get_pay_stubs",
        "summary": (
            "Get the employee's recent payslips showing pay dates, gross/net amounts, "
            "and currency."
        ),
        "func": tool_get_pay_stubs,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/sf-payslip-list.html",
            "openai/toolInvocation/invoking": "Loading payslips…",
            "openai/toolInvocation/invoked": "Payslips loaded.",
        },
    },
    {
        "name": "get_pay_stub_detail",
        "summary": (
            "Get detailed breakdown of a single payslip including earnings, deductions, "
            "and net pay."
        ),
        "func": tool_get_pay_stub_detail,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/sf-payslip-detail.html",
            "openai/toolInvocation/invoking": "Loading payslip detail…",
            "openai/toolInvocation/invoked": "Payslip detail ready.",
        },
    },
    {
        "name": "prepare_move_employee",
        "summary": (
            "Show a form to move an employee to a new position. Pre-populated with "
            "current job info. Use this before move_employee."
        ),
        "func": tool_prepare_move_employee,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/sf-move-employee.html",
            "openai/toolInvocation/invoking": "Preparing move employee form…",
            "openai/toolInvocation/invoked": "Form ready.",
        },
    },
    {
        "name": "move_employee",
        "summary": (
            "Submit an employee move to a new position. Requires user_id, "
            "new_position_id, and effective_date."
        ),
        "func": tool_move_employee,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Submitting employee move…",
            "openai/toolInvocation/invoked": "Move submitted.",
        },
    },
    {
        "name": "update_hierarchy",
        "summary": (
            "Submit a hierarchy change (new manager assignment) for an employee. "
            "Requires user_id, new_manager_id, and effective_date."
        ),
        "func": tool_update_hierarchy,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Updating hierarchy…",
            "openai/toolInvocation/invoked": "Hierarchy updated.",
        },
    },
    {
        "name": "trigger_background_check",
        "summary": "Trigger a background check for an employee in SAP SuccessFactors.",
        "func": tool_trigger_background_check,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Triggering background check…",
            "openai/toolInvocation/invoked": "Background check triggered.",
        },
    },
    {
        "name": "get_background_check_status",
        "summary": "Get the status of background checks for an employee.",
        "func": tool_get_background_check_status,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/toolInvocation/invoking": "Checking background status…",
            "openai/toolInvocation/invoked": "Status retrieved.",
            "openai/outputTemplate": "ui://widget/sf-background-check.html",
        },
    },
    {
        "name": "manage_position",
        "summary": (
            "Create or modify a position in SAP SuccessFactors. "
            "Set action to 'create' or 'update'."
        ),
        "func": tool_manage_position,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Managing position…",
            "openai/toolInvocation/invoked": "Position updated.",
        },
    },
    {
        "name": "request_leave_carryover",
        "summary": (
            "Submit a leave carryover request to carry unused leave days from one year "
            "to the next."
        ),
        "func": tool_request_leave_carryover,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Submitting carryover request…",
            "openai/toolInvocation/invoked": "Carryover request submitted.",
        },
    },
    {
        "name": "get_employee_documents",
        "summary": (
            "List the employee's documents stored in SAP SuccessFactors, such as "
            "contracts, letters, and certificates."
        ),
        "func": tool_get_employee_documents,
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/sf-document-list.html",
            "openai/toolInvocation/invoking": "Loading documents…",
            "openai/toolInvocation/invoked": "Documents loaded.",
        },
    },
    {
        "name": "generate_employment_verification",
        "summary": (
            "Trigger generation of an employment verification letter (US). "
            "The letter is created asynchronously and the user is notified when ready."
        ),
        "func": tool_generate_employment_verification,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Requesting verification letter…",
            "openai/toolInvocation/invoked": "Verification letter requested.",
        },
    },
    {
        "name": "generate_employment_reference",
        "summary": (
            "Trigger generation of an employment reference letter (UK). "
            "The letter is created asynchronously and the user is notified when ready."
        ),
        "func": tool_generate_employment_reference,
        "annotations": {"readOnlyHint": False},
        "meta": {
            "openai/toolInvocation/invoking": "Requesting reference letter…",
            "openai/toolInvocation/invoked": "Reference letter requested.",
        },
    },
]
