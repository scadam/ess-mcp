
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlencode

from fastmcp import Context

from ..auth import get_bearer_token
from ..http import create_async_client
from ..logging import get_logger
from .config import get_endpoints
from .helpers import build_worker_context_from_bearer
import httpx

LOGGER = get_logger(__name__)


class WorkdayApiNotAvailable(Exception):
    """Raised when a Workday REST API returns 404 (not enabled for this tenant)."""

    def __init__(self, api_name: str, status_code: int, detail: str = ""):
        self.api_name = api_name
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"{api_name} API is not available for this Workday tenant: {detail}")


def _get_auth_token(ctx: Optional[Context] = None) -> str:
    """Extract the OAuth 2.0 Bearer token from the Authorization request header."""
    return get_bearer_token(ctx)



def _transform_worker(worker_data: Dict[str, Any]) -> Dict[str, Any]:
    primary_job = worker_data.get("primaryJob", {})
    location = primary_job.get("location", {})
    country = location.get("country", {})

    # The staffing API provides primaryJob/person/workerType.
    # Fall back to the flat /workers/me shape for fields available there.
    return {
        "workdayId": worker_data.get("id"),
        "workerId": worker_data.get("workerId"),
        "name": worker_data.get("descriptor"),
        "email": worker_data.get("person", {}).get("email")
            or worker_data.get("primaryWorkEmail"),
        "workerType": worker_data.get("workerType", {}).get("descriptor"),
        "businessTitle": primary_job.get("businessTitle")
            or worker_data.get("businessTitle"),
        "location": location.get("descriptor")
            or worker_data.get("location", {}).get("descriptor"),
        "locationId": location.get("Location_ID"),
        "country": country.get("descriptor"),
        "countryCode": country.get("ISO_3166-1_Alpha-3_Code"),
        "supervisoryOrganization": primary_job.get("supervisoryOrganization", {}).get("descriptor")
            or worker_data.get("primarySupervisoryOrganization", {}).get("descriptor"),
        "jobType": primary_job.get("jobType", {}).get("descriptor"),
        "jobProfile": primary_job.get("jobProfile", {}).get("descriptor"),
        "primaryJobId": primary_job.get("id"),
        "primaryJobDescriptor": primary_job.get("descriptor"),
        "isManager": worker_data.get("isManager"),
        "yearsOfService": worker_data.get("yearsOfService"),
        "primaryWorkAddress": worker_data.get("primaryWorkAddressText"),
    }


async def _fetch_json(url: str, access_token: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    async with create_async_client() as client:
        response = await client.get(url, headers=headers)
        if response.status_code in (404, 400):
            try:
                body = response.json()
                detail = body.get("error", response.text[:200])
            except Exception:
                detail = response.text[:200]
            # Extract the API name from the URL path for a clear message
            api_name = url.split("/ccx/api/")[-1].split("/")[0] if "/ccx/api/" in url else url
            raise WorkdayApiNotAvailable(api_name, response.status_code, detail)
        response.raise_for_status()
        return response.json()


def _tool_response(summary: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return payload dict directly; fastmcp serialises it as structuredContent."""
    return payload


async def _fetch_json_with_params(
    url: str, access_token: str, params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fetch JSON from a Workday API endpoint with optional query parameters."""
    if params:
        url = f"{url}?{urlencode(params)}"
    return await _fetch_json(url, access_token)


async def tool_get_worker(ctx: Optional[Context] = None) -> Dict:
    """Get the current Workday worker profile using the provided OAuth 2.0 bearer token."""
    worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    worker = _transform_worker(worker_context.worker_data)
    worker["_widget_hint"] = "Worker profile is ready."
    return worker


async def _get_leave_balances(access_token: str, workday_id: str) -> List[Dict[str, Any]]:
    endpoints = get_endpoints()
    url = endpoints.full_url(
        "/ccx/api/absenceManagement/v1/{tenant}/balances?worker={workday_id}",
        workday_id=workday_id,
    )
    data = await _fetch_json(url, access_token)
    balances = []
    for balance in data.get("data", []):
        plan = balance.get("absencePlan", {})
        balances.append(
            {
                "planName": plan.get("descriptor"),
                "planId": plan.get("id"),
                "balance": balance.get("quantity", "0"),
                "unit": balance.get("unit", {}).get("descriptor"),
                "effectiveDate": balance.get("effectiveDate"),
                "timeOffTypes": plan.get("timeoffs", ""),
            }
        )
    return balances


async def _get_eligible_absence_types(access_token: str, workday_id: str) -> List[Dict[str, Any]]:
    endpoints = get_endpoints()
    url = endpoints.full_url(
        "/ccx/api/absenceManagement/v1/{tenant}/workers/{workday_id}/eligibleAbsenceTypes",
        workday_id=workday_id,
    )
    data = await _fetch_json(url, access_token)
    absence_types = []
    for item in data.get("data", []):
        absence_types.append(
            {
                "name": item.get("descriptor"),
                "id": item.get("id"),
                "unit": item.get("unitOfTime", {}).get("descriptor"),
                "category": item.get("category", {}).get("descriptor"),
                "group": item.get("absenceTypeGroup", {}).get("descriptor"),
            }
        )
    return absence_types


async def _get_leaves_of_absence(access_token: str, workday_id: str) -> List[Dict[str, Any]]:
    endpoints = get_endpoints()
    url = endpoints.full_url(
        "/ccx/api/absenceManagement/v1/{tenant}/workers/{workday_id}/leavesOfAbsence",
        workday_id=workday_id,
    )
    data = await _fetch_json(url, access_token)
    leaves = []
    for item in data.get("data", []):
        leaves.append(
            {
                "id": item.get("id"),
                "leaveType": item.get("leaveType", {}).get("descriptor"),
                "status": item.get("status", {}).get("descriptor"),
                "firstDayOfLeave": item.get("firstDayOfLeave"),
                "lastDayOfWork": item.get("lastDayOfWork"),
                "estimatedLastDay": item.get("estimatedLastDayOfLeave"),
                "comment": item.get("latestLeaveComment", ""),
            }
        )
    return leaves


async def _get_time_off_details(access_token: str, workday_id: str) -> List[Dict[str, Any]]:
    endpoints = get_endpoints()
    url = endpoints.full_url(
        "/ccx/api/absenceManagement/v1/{tenant}/workers/{workday_id}/timeOffDetails",
        workday_id=workday_id,
    )
    data = await _fetch_json(url, access_token)
    details = []
    for item in data.get("data", []):
        details.append(
            {
                "date": item.get("date"),
                "timeOffType": item.get("timeOffType", {}).get("descriptor"),
                "quantity": item.get("quantity"),
                "unit": item.get("unit", {}).get("descriptor"),
                "status": item.get("status", {}).get("descriptor"),
                "comment": item.get("comment", ""),
            }
        )
    return details


async def tool_get_leave_balances(ctx: Optional[Context] = None) -> Dict:
    worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    workday_id = worker_context.workday_id
    access_token = worker_context.workday_access_token
    leave_balances, eligible_absence_types, leaves_of_absence, booked_time_off = await asyncio.gather(
        _get_leave_balances(access_token, workday_id),
        _get_eligible_absence_types(access_token, workday_id),
        _get_leaves_of_absence(access_token, workday_id),
        _get_time_off_details(access_token, workday_id),
    )
    payload = {
        "success": True,
        "leaveBalances": leave_balances,
        "eligibleAbsenceTypes": eligible_absence_types,
        "leavesOfAbsence": leaves_of_absence,
        "bookedTimeOff": booked_time_off,
    }
    return _tool_response("Retrieve leave balances and related data.", payload)


async def _fetch_direct_reports(access_token: str, workday_id: str) -> List[Dict[str, Any]]:
    endpoints = get_endpoints()
    url = endpoints.full_url(
        "/ccx/api/common/v1/{tenant}/workers/{workday_id}/directReports",
        workday_id=workday_id,
    )
    data = await _fetch_json(url, access_token)
    reports = []
    for item in data.get("data", []):
        reports.append(
            {
                "isManager": item.get("isManager"),
                "primaryWorkPhone": item.get("primaryWorkPhone"),
                "primaryWorkEmail": item.get("primaryWorkEmail"),
                "primarySupervisoryOrganization": item.get("primarySupervisoryOrganization", {}).get(
                    "descriptor"
                ),
                "businessTitle": item.get("businessTitle"),
                "descriptor": item.get("descriptor"),
            }
        )
    return reports


async def tool_get_direct_reports(ctx: Optional[Context] = None) -> Dict:
    worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    reports = await _fetch_direct_reports(worker_context.workday_access_token, worker_context.workday_id)
    payload = {"success": True, "directReports": reports}
    return _tool_response("List direct reports for the current worker.", payload)


def _workday_inbox_url() -> str:
    """Return the Workday inbox home URL for this tenant."""
    endpoints = get_endpoints()
    return f"https://impl.workday.com/{endpoints.tenant}/d/home.htmld"


def _workday_learning_url(content_id: str) -> Optional[str]:
    """Return the Workday Learning course-detail URL for a given content ID."""
    if not content_id:
        return None
    endpoints = get_endpoints()
    return f"https://impl.workday.com/{endpoints.tenant}/learning/course-details/{content_id}"


async def _fetch_inbox_tasks(access_token: str, workday_id: str) -> List[Dict[str, Any]]:
    endpoints = get_endpoints()
    url = endpoints.full_url(
        "/ccx/api/common/v1/{tenant}/workers/{workday_id}/inboxTasks?limit=100",
        workday_id=workday_id,
    )
    data = await _fetch_json(url, access_token)
    tasks = []
    inbox_url = _workday_inbox_url()
    for item in data.get("data", []):
        tasks.append(
            {
                "id": item.get("id"),
                "href": item.get("href"),  # REST API URL (not UI URL)
                "link": inbox_url,  # Workday SPA has no per-task deep link
                "assigned": item.get("assigned"),
                "due": item.get("due"),
                "initiator": item.get("initiator", {}).get("descriptor"),
                "status": item.get("status", {}).get("descriptor"),
                "stepType": item.get("stepType", {}).get("descriptor"),
                "subject": item.get("subject", {}).get("descriptor"),
                "overallProcess": item.get("overallProcess", {}).get("descriptor"),
                "descriptor": item.get("descriptor"),
            }
        )
    return tasks


async def tool_get_inbox_tasks(ctx: Optional[Context] = None) -> Dict:
    worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    tasks = await _fetch_inbox_tasks(worker_context.workday_access_token, worker_context.workday_id)
    payload = {"success": True, "tasks": tasks}
    return _tool_response("List Workday inbox tasks for the current worker.", payload)


async def _fetch_learning_assignments(access_token: str, workday_id: str) -> List[Dict[str, Any]]:
    endpoints = get_endpoints()
    url = endpoints.learning_report_url(workday_id)
    data = await _fetch_json(url, access_token)
    assignments = []
    for item in data.get("Report_Entry", []):
        # learningContent is now a plain string in the report output
        content = item.get("learningContent", "")
        if isinstance(content, dict):
            # backward-compat: old format returned a {id, descriptor} object
            content_title = content.get("descriptor", "")
        else:
            content_title = str(content) if content else ""

        # Build human-readable duration string, e.g. "47 Minutes" or "2 Days"
        dur_num = item.get("Course_Duration", "")
        dur_unit = item.get("Course_Duration_Unit", "")
        if dur_num and str(dur_num) != "0" and dur_unit:
            course_duration = f"{dur_num} {dur_unit}"
        elif dur_num and str(dur_num) != "0":
            course_duration = str(dur_num)
        else:
            course_duration = None

        assignments.append(
            {
                "assignmentStatus": item.get("assignmentStatus"),
                "dueDate": item.get("dueDate"),
                "learningContentTitle": content_title,
                # contentURL from the report is the direct assignment launch URL
                "contentURL": item.get("contentURL"),
                "contentProvider": item.get("contentProvider"),
                "courseDuration": course_duration,
                "comments": item.get("Comments"),
                "overdue": item.get("overdue") == "1",
                "required": item.get("required") == "1",
                "workdayId": item.get("workdayId"),
            }
        )
    return assignments


async def tool_get_learning_assignments(ctx: Optional[Context] = None) -> Dict:
    worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    assignments = await _fetch_learning_assignments(
        worker_context.workday_access_token, worker_context.workday_id
    )
    payload = {"success": True, "assignments": assignments, "total": len(assignments)}
    return _tool_response("Learning assignments are ready.", payload)


async def _fetch_pay_slips(access_token: str, workday_id: str) -> List[Dict[str, Any]]:
    endpoints = get_endpoints()
    url = endpoints.full_url(
        "/ccx/api/common/v1/{tenant}/workers/{workday_id}/paySlips",
        workday_id=workday_id,
    )
    data = await _fetch_json(url, access_token)
    pay_slips = []
    for item in data.get("data", []):
        pay_slips.append(
            {
                "gross": item.get("gross"),
                "status": item.get("status", {}).get("descriptor"),
                "net": item.get("net"),
                "date": item.get("date"),
                "descriptor": item.get("descriptor"),
            }
        )
    return pay_slips


async def tool_get_pay_slips(ctx: Optional[Context] = None) -> Dict:
    worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    pay_slips = await _fetch_pay_slips(worker_context.workday_access_token, worker_context.workday_id)
    payload = {"success": True, "paySlips": pay_slips}
    return _tool_response("List recent Workday pay slips.", payload)


async def _fetch_time_off_entries(access_token: str, workday_id: str) -> List[Dict[str, Any]]:
    endpoints = get_endpoints()
    url = endpoints.full_url(
        "/ccx/api/common/v1/{tenant}/workers/{workday_id}/timeOffEntries",
        workday_id=workday_id,
    )
    data = await _fetch_json(url, access_token)
    entries = []
    for item in data.get("data", []):
        entries.append(
            {
                "employee": item.get("employee", {}).get("descriptor"),
                "timeOffRequestStatus": item.get("timeOffRequest", {}).get("status"),
                "timeOffRequestDescriptor": item.get("timeOffRequest", {}).get("descriptor"),
                "unitOfTime": item.get("unitOfTime", {}).get("descriptor"),
                "timeOffPlan": item.get("timeOff", {}).get("plan", {}).get("descriptor"),
                "timeOffDescriptor": item.get("timeOff", {}).get("descriptor"),
                "date": item.get("date"),
                "units": item.get("units"),
                "descriptor": item.get("descriptor"),
            }
        )
    return entries


async def tool_get_time_off_entries(ctx: Optional[Context] = None) -> Dict:
    worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    entries = await _fetch_time_off_entries(
        worker_context.workday_access_token, worker_context.workday_id
    )
    payload = {"success": True, "timeOffEntries": entries}
    return _tool_response("List time off entries for the current worker.", payload)


async def _get_default_dates() -> Dict[str, str]:
    tomorrow = datetime.utcnow().date() + timedelta(days=1)
    formatted = tomorrow.strftime("%Y-%m-%d")
    return {"startDate": formatted, "endDate": formatted}


async def tool_prepare_request_leave(
    ctx: Optional[Context] = None,
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
    quantity: Optional[str] = None,
    unit: Optional[str] = None,
    reason: Optional[str] = None,
    timeOffTypeId: Optional[str] = None,
) -> Dict:
    worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    default_dates = await _get_default_dates()
    request_params = {
        "startDate": startDate or default_dates["startDate"],
        "endDate": endDate or default_dates["endDate"],
        "quantity": quantity or "8",
        "unit": unit or "Hours",
        "reason": reason or "Time off request",
        "timeOffTypeId": timeOffTypeId or "",
    }
    access_token = worker_context.workday_access_token
    workday_id = worker_context.workday_id
    eligible_absence_types, leave_balances, booked_time_off = await asyncio.gather(
        _get_eligible_absence_types(access_token, workday_id),
        _get_leave_balances(access_token, workday_id),
        _get_time_off_details(access_token, workday_id),
    )
    payload = {
        "success": True,
        "_widget_hint": "The form is ready. Acknowledge with one short sentence (e.g. 'Here is your leave booking form.').",
        "requestParameters": request_params,
        "eligibleAbsenceTypes": eligible_absence_types,
        "leaveBalances": leave_balances,
        "bookedTimeOff": booked_time_off,
        "workdayId": workday_id,
        "bookingGuidance": {
            "timeFormat": "ISO 8601 with timezone (e.g., 2025-02-25T08:00:00.000Z)",
            "defaultWorkingHours": {"start": "08:00:00.000Z", "end": "17:00:00.000Z"},
            "quantityCalculation": {
                "forHours": "Use dailyDefaultQuantity * number of days",
                "forDays": "Use 1 per day requested",
            },
        },
    }
    return _tool_response("Prepare the data needed to submit a leave request.", payload)


def _generate_date_range(start_date: str, end_date: str) -> Iterable[str]:
    start = datetime.fromisoformat(start_date)
    end = datetime.fromisoformat(end_date)
    current = start
    while current <= end:
        yield current.date().isoformat()
        current += timedelta(days=1)


def _create_days_array(start_date: str, end_date: str, quantity: str, unit: str, reason: str, time_off_type_id: str) -> List[Dict[str, Any]]:
    days = []
    for day in _generate_date_range(start_date, end_date):
        # For Days unit Workday expects 1.0 per day; for Hours use the given quantity
        if unit.lower() == "days":
            daily_quantity = 1.0
        else:
            daily_quantity = float(quantity) if quantity else 8.0
        days.append(
            {
                "date": day,  # Workday expects plain YYYY-MM-DD
                "dailyQuantity": daily_quantity,
                "comment": reason,
                "timeOffType": {"id": time_off_type_id},
            }
        )
    return days


async def tool_book_leave(
    ctx: Optional[Context] = None,
    startDate: Optional[str] = None,
    endDate: Optional[str] = None,
    timeOffTypeId: Optional[str] = None,
    quantity: str = "8",
    unit: str = "Hours",
    reason: str = "Time off request",
) -> Dict:
    worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    
    if not startDate or not endDate or not timeOffTypeId:
        raise ValueError("startDate, endDate, and timeOffTypeId are required")
    
    days = _create_days_array(startDate, endDate, quantity, unit, reason, timeOffTypeId)
    endpoints = get_endpoints()
    url = endpoints.full_url(
        "/ccx/api/absenceManagement/v1/{tenant}/workers/{workday_id}/requestTimeOff",
        workday_id=worker_context.workday_id,
    )
    payload = {"days": days}
    headers = {
        "Authorization": f"Bearer {worker_context.workday_access_token}",
        "Content-Type": "application/json",
    }
    async with create_async_client() as client:
        response = await client.post(url, json=payload, headers=headers)
        content_type = response.headers.get("content-type", "")
        parsed_body: Any
        if "application/json" in content_type:
            parsed_body = response.json()
        else:
            parsed_body = {"message": response.text}
        if response.is_error:
            message = None
            if isinstance(parsed_body, dict):
                message = parsed_body.get("errors", [{}])[0].get("error") or parsed_body.get("error")
                if not message:
                    message = parsed_body.get("message")
            if not message:
                message = f"Workday API error {response.status_code}"
            LOGGER.error(
                "workday_book_leave_error",
                status=response.status_code,
                error=message,
                body=str(parsed_body)[:500],
            )
            response.raise_for_status()
    business_process = parsed_body.get("businessProcessParameters", {}).get(
        "overallBusinessProcess", {}
    ).get("descriptor")
    transaction_status = parsed_body.get("businessProcessParameters", {}).get(
        "transactionStatus", {}
    ).get("descriptor")
    days_booked = len(parsed_body.get("days", days))
    total_quantity = sum(float(day.get("dailyQuantity", 0)) for day in days)
    result: Dict[str, Any] = {
        "success": True,
        "message": "Time off request submitted successfully",
        "bookingDetails": {
            "businessProcess": business_process,
            "status": parsed_body.get("businessProcessParameters", {}).get("overallStatus"),
            "transactionStatus": transaction_status,
            "daysBooked": days_booked,
            "totalQuantity": total_quantity,
        },
        "workdayResponse": parsed_body,
    }
    return _tool_response("Submit a leave request to Workday for the current worker.", result)


async def tool_prepare_change_business_title(ctx: Optional[Context] = None) -> Dict:
    """Show a form to change the current worker's business title.

    Fetches the worker's current profile and renders the change-business-title
    widget so the user can enter a new title and submit. The widget handles
    submission via change_business_title.
    """
    worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    worker = _transform_worker(worker_context.worker_data)
    return {
        "success": True,
        "_widget_hint": "The form is ready. Acknowledge with one short sentence (e.g. 'Here is your business title change form.').",
        "worker": worker,
    }


async def tool_change_business_title(
    ctx: Optional[Context] = None, proposedBusinessTitle: Optional[str] = None
) -> Dict:
    if not proposedBusinessTitle:
        return {"success": False, "error": "proposedBusinessTitle is required"}
    try:
        worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/common/v1/{tenant}/workers/{workday_id}/businessTitleChanges",
            workday_id=worker_context.workday_id,
        )
        headers = {
            "Authorization": f"Bearer {worker_context.workday_access_token}",
            "Content-Type": "application/json",
        }
        payload = {"proposedBusinessTitle": proposedBusinessTitle}
        async with create_async_client() as client:
            response = await client.post(url, json=payload, headers=headers)
            if not response.is_success:
                body_text = response.text[:500]
                LOGGER.error(
                    "workday_change_business_title_http_error",
                    status_code=response.status_code,
                    body=body_text,
                )
                response.raise_for_status()
            data = response.json()
        result_payload = {
            "success": True,
            "message": "Business title change request submitted",
            "changeDetails": data,
        }
        return _tool_response("Request a business title change for the current worker.", result_payload)
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("workday_change_business_title_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def _search_learning_content(access_token: str, skills: Iterable[str], topics: Iterable[str]) -> Dict[str, Any]:
    endpoints = get_endpoints()
    url = endpoints.full_url("/ccx/api/learning/v1/{tenant}/content")
    params: List[tuple[str, str]] = [("limit", "100")]
    for skill in skills:
        params.append(("skills", str(skill)))
    for topic in topics:
        params.append(("topics", str(topic)))
    async with create_async_client() as client:
        response = await client.get(
            url,
            params=params,  # type: ignore[arg-type]
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        return response.json()


async def _get_lessons(access_token: str, content_id: str) -> Dict[str, Any]:
    endpoints = get_endpoints()
    url = endpoints.full_url(
        "/ccx/api/learning/v1/{tenant}/content/{content_id}/lessons",
        content_id=content_id,
    )
    async with create_async_client() as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {access_token}"})
        response.raise_for_status()
        return response.json()


def _flatten_lesson(lesson: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": lesson.get("id"),
        "descriptor": lesson.get("descriptor"),
        "description": lesson.get("description"),
        "order": lesson.get("order"),
        "required": lesson.get("required"),
        "contentType": lesson.get("contentType", {}).get("descriptor"),
        "duration": lesson.get("instructorLedData", {}).get("duration")
        or lesson.get("mediaData", {}).get("duration"),
        "contentURL": lesson.get("externalContentData", {}).get("contentURL"),
        "instructors": [i.get("descriptor") for i in lesson.get("instructorLedData", {}).get("instructors", [])],
        "materials": [m.get("descriptor") for m in lesson.get("trainingActivityData", {}).get("materials", [])],
        "activityType": lesson.get("trainingActivityData", {}).get("activityType", {}).get("descriptor"),
        "virtualClassroomURL": lesson.get("instructorLedData", {})
        .get("virtualClassroomData", {})
        .get("virtualClassroomURL"),
        "location": lesson.get("instructorLedData", {}).get("inPersonLedData", {}).get(
            "adhocLocationName"
        ),
        "trackAttendance": lesson.get("instructorLedData", {}).get("trackAttendance")
        or lesson.get("trainingActivityData", {}).get("trackAttendance"),
        "trackGrades": lesson.get("instructorLedData", {}).get("trackGrades")
        or lesson.get("trainingActivityData", {}).get("trackGrades"),
    }


def _flatten_content(content: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": content.get("id"),
        "descriptor": content.get("descriptor"),
        "description": content.get("description"),
        "contentNumber": content.get("contentNumber"),
        "contentURL": content.get("contentURL"),
        "version": content.get("version"),
        "createdOnDate": content.get("createdOnDate"),
        "averageRating": content.get("averageRating"),
        "ratingCount": content.get("ratingCount"),
        "popularity": content.get("popularity"),
        "contentType": content.get("contentType", {}).get("descriptor"),
        "contentProvider": content.get("contentProvider", {}).get("descriptor"),
        "accessType": content.get("accessType", {}).get("descriptor"),
        "deliveryMode": content.get("deliveryMode", {}).get("descriptor"),
        "skillLevel": content.get("skillLevel", {}).get("descriptor"),
        "lifecycleStatus": content.get("lifecycleStatus", {}).get("descriptor"),
        "availabilityStatus": content.get("availabilityStatus", {}).get("descriptor"),
        "excludeFromRecommendations": content.get("excludeFromRecommendations"),
        "excludeFromSearchAndBrowse": content.get("excludeFromSearchAndBrowse"),
        "learningCatalogs": [c.get("descriptor") for c in content.get("learningCatalogs", [])],
        "languages": [lang.get("descriptor") for lang in content.get("languages", [])],
        "skills": [{"id": s.get("id"), "descriptor": s.get("descriptor")} for s in content.get("skills", [])],
        "topics": [t.get("descriptor") for t in content.get("topics", [])],
        "securityCategories": [sc.get("descriptor") for sc in content.get("securityCategories", [])],
        "contactPersons": [cp.get("descriptor") for cp in content.get("contactPersons", [])],
        "imageURL": content.get("image", {}).get("publicURL"),
        "lessons": [],
    }


async def tool_search_learning_content(
    ctx: Optional[Context] = None,
    skills: Optional[List[str]] = None,
    category: Optional[str] = None,
) -> Dict:
    """Search Workday learning content filtered by skills and/or category.

    *category* – a skill-category name (e.g. "Cloud Computing").  When
    supplied, the widget will only show skills that belong to this
    category.  The name is resolved case-insensitively against the
    Workday Skills RaaS report.

    Each value in *skills* can be either a Workday skill ID or a
    human-readable skill name.  Names are resolved to their Workday IDs
    via the Skills RaaS report; any value that cannot be resolved is
    silently dropped so the search still runs.
    """
    access_token = _get_auth_token(ctx)

    def _normalize(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, Iterable):
            return [str(item) for item in value]
        return [str(value)]

    raw_skills = _normalize(skills)

    # -- Fetch the skills catalogue so we can map names → Workday IDs ----
    all_skills: list[dict] = []
    name_to_id: dict[str, str] = {}
    id_set: set[str] = set()
    categories_set: set[str] = set()
    try:
        endpoints = get_endpoints()
        skills_url = endpoints.skills_report_url()
        skills_data = await _fetch_json(skills_url, access_token)
        seen: set[str] = set()
        for entry in skills_data.get("Report_Entry", []):
            name = entry.get("skillName") or entry.get("Skills") or ""
            if not name or name in seen or entry.get("Inactive") == "1":
                continue
            seen.add(name)
            wid = entry.get("workdayID", name)
            cat = entry.get("Skill_Categories", "")
            usage = int(entry.get("Usage_Count", 0) or 0)
            name_to_id[name.lower()] = wid
            id_set.add(wid)
            if cat:
                categories_set.add(cat)
            all_skills.append({
                "id": wid,
                "descriptor": name,
                "category": cat,
                "usageCount": usage,
            })
        all_skills.sort(key=lambda x: (-x["usageCount"], x["descriptor"]))
    except Exception as exc:  # noqa: BLE001
        LOGGER.warning("skills_raas_fetch_failed", error=str(exc))

    # Resolve category name (case-insensitive)
    resolved_category: str = ""
    if category:
        cat_lower = category.strip().lower()
        for cat in categories_set:
            if cat.lower() == cat_lower:
                resolved_category = cat
                break
        if not resolved_category:
            LOGGER.info("category_filter_not_matched", category=category)

    # Filter skills list by category when one is selected
    if resolved_category:
        available_skills = [s for s in all_skills if s["category"] == resolved_category]
    else:
        available_skills = all_skills

    available_categories = sorted(categories_set)

    # Resolve each skill to a Workday ID; drop unknowns
    resolved_skills: list[str] = []
    for s in raw_skills:
        if s in id_set:
            resolved_skills.append(s)
        elif s.lower() in name_to_id:
            resolved_skills.append(name_to_id[s.lower()])
        else:
            LOGGER.info("skill_filter_dropped", skill=s, reason="not a valid Workday skill ID or name")

    content_response = await _search_learning_content(access_token, resolved_skills, [])
    items = content_response.get("data", [])
    enriched = []
    for item in items:
        flattened = _flatten_content(item)
        try:
            lessons_response = await _get_lessons(access_token, item.get("id"))
            flattened["lessons"] = [_flatten_lesson(lesson) for lesson in lessons_response.get("data", [])]
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("lesson_fetch_failed", content_id=item.get("id"), error=str(exc))
            flattened["lessons"] = []
        enriched.append(flattened)

    payload = {
        "success": True,
        "content": enriched,
        "total": len(enriched),
        "availableSkills": available_skills,
        "availableCategories": available_categories,
        "selectedCategory": resolved_category,
        "selectedSkills": resolved_skills,
    }
    return _tool_response("Search Workday learning content and fetch associated lessons.", payload)


# ── Provider functions for TaskServer integration ───────────────────


async def provider_list_tasks(ctx: Optional[Context] = None) -> List[Dict[str, Any]]:
    """List Workday inbox tasks that are NOT approvals.

    Returns raw inbox task data for TaskServer normalization.
    Non-approval inbox tasks are regular tasks (impl notes S3).
    """
    try:
        worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    except Exception:  # noqa: BLE001
        LOGGER.debug("workday_auth_not_available_for_tasks")
        return []
    tasks = await _fetch_inbox_tasks(
        worker_context.workday_access_token, worker_context.workday_id
    )
    return [t for t in tasks if t.get("stepType") != "Approval"]


async def provider_list_approvals(ctx: Optional[Context] = None) -> List[Dict[str, Any]]:
    """List Workday inbox tasks where stepType is Approval.

    Only inbox tasks with stepType == "Approval" are approvable
    (impl notes S3).
    """
    try:
        worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    except Exception:  # noqa: BLE001
        LOGGER.debug("workday_auth_not_available_for_approvals")
        return []
    tasks = await _fetch_inbox_tasks(
        worker_context.workday_access_token, worker_context.workday_id
    )
    return [t for t in tasks if t.get("stepType") == "Approval"]


async def provider_list_learning(ctx: Optional[Context] = None) -> List[Dict[str, Any]]:
    """List Workday required learning assignments for TaskServer normalization."""
    try:
        worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    except Exception:  # noqa: BLE001
        LOGGER.debug("workday_auth_not_available_for_learning")
        return []
    return await _fetch_learning_assignments(
        worker_context.workday_access_token, worker_context.workday_id
    )


async def provider_get_approval_detail(
    task_id: str, ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """Get detail for a specific Workday inbox task."""
    worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    endpoints = get_endpoints()
    url = endpoints.full_url(
        "/ccx/api/common/v1/{tenant}/workers/{workday_id}/inboxTasks/{task_id}",
        workday_id=worker_context.workday_id,
        task_id=task_id,
    )
    data = await _fetch_json(url, worker_context.workday_access_token)
    return {
        "title": data.get("descriptor", ""),
        "summary": data.get("overallProcess", {}).get("descriptor", ""),
        "status": data.get("status", {}).get("descriptor", ""),
        "stepType": data.get("stepType", {}).get("descriptor", ""),
        "initiator": data.get("initiator", {}).get("descriptor", ""),
        "assigned": data.get("assigned"),
        "due": data.get("due"),
        "taskId": task_id,
        "raw": data,
    }


async def provider_execute_approval(
    task_id: str, decision: str, comment: str = "", ctx: Optional[Context] = None
) -> Dict[str, Any]:
    """Approve or reject a Workday inbox task.

    Only works for tasks with stepType == Approval.  Approve/reject APIs
    will fail if stepType is not Approval (impl notes S3).
    """
    worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    action = "approve" if decision == "approve" else "deny"
    endpoints = get_endpoints()
    url = endpoints.full_url(
        "/ccx/api/common/v1/{tenant}/workers/{workday_id}/inboxTasks/{task_id}/{action}",
        workday_id=worker_context.workday_id,
        task_id=task_id,
        action=action,
    )
    headers = {
        "Authorization": f"Bearer {worker_context.workday_access_token}",
        "Content-Type": "application/json",
    }
    body: Dict[str, Any] = {}
    if comment:
        body["comment"] = comment

    async with create_async_client() as client:
        response = await client.post(url, json=body, headers=headers)
        response.raise_for_status()
        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type and response.content:
            result = response.json()
        else:
            result = {"status": "completed"}

    return {
        "success": True,
        "decision": decision,
        "taskId": task_id,
        "result": result,
    }











async def tool_get_org_chart(ctx: Optional[Context] = None) -> Dict:
    """Get the organizational chart for the current worker's supervisory organization."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        worker = _transform_worker(wctx.worker_data)
        current_id = wctx.workday_id

        sup_org = wctx.worker_data.get("primaryJob", {}).get("supervisoryOrganization", {})
        org_id = sup_org.get("id")
        if not org_id:
            # Fallback: /workers/me uses primarySupervisoryOrganization at top level
            sup_org = wctx.worker_data.get("primarySupervisoryOrganization", {})
            org_id = sup_org.get("id")
        if not org_id:
            return {"success": False, "error": "No supervisory organization found for worker."}
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/common/v1/{tenant}/supervisoryOrganizations/{org_id}/workers",
            org_id=org_id,
        )
        data = await _fetch_json(url, wctx.workday_access_token)

        # Separate members into manager(s), the current worker, and others
        manager_node = None
        direct_reports = []
        for item in data.get("data", []):
            member = {
                "name": item.get("descriptor"),
                "workerId": item.get("id"),
                "businessTitle": item.get("businessTitle"),
                "email": item.get("primaryWorkEmail"),
                "isManager": item.get("isManager"),
                "organization": item.get("primarySupervisoryOrganization", {}).get(
                    "descriptor"
                ),
            }
            if item.get("id") == current_id:
                continue  # skip self — we already have the worker node
            if item.get("isManager") and not manager_node:
                manager_node = member
            else:
                direct_reports.append(member)

        payload = {
            "success": True,
            "organization": sup_org.get("descriptor"),
            "organizationId": org_id,
            "manager": manager_node,
            "worker": {
                "name": worker.get("name"),
                "businessTitle": worker.get("businessTitle"),
                "email": worker.get("email"),
                "workerId": current_id,
            },
            "directReports": direct_reports,
            "total": len(direct_reports),
        }
        return _tool_response("Organization chart for the worker's supervisory org.", payload)
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_org_chart_error", error=str(exc))
        return {"success": False, "error": str(exc)}





async def tool_get_team_calendar(ctx: Optional[Context] = None) -> Dict:
    """Get the team time-off calendar showing who is out in the current worker's team."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        reports = await _fetch_direct_reports(wctx.workday_access_token, wctx.workday_id)
        team_time_off = []
        for report in reports:
            name = report.get("descriptor", "Unknown")
            email = report.get("primaryWorkEmail")
            title = report.get("businessTitle")
            team_time_off.append(
                {
                    "name": name,
                    "email": email,
                    "businessTitle": title,
                    "timeOff": [],
                }
            )
        # Fetch the current worker's own booked time off for context
        own_time_off = await _get_time_off_details(wctx.workday_access_token, wctx.workday_id)
        worker = _transform_worker(wctx.worker_data)
        payload = {
            "success": True,
            "worker": {
                "name": worker.get("name"),
                "timeOff": own_time_off,
            },
            "teamMembers": team_time_off,
            "totalTeamMembers": len(team_time_off),
        }
        return _tool_response("Team time-off calendar.", payload)
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_team_calendar_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_team_overview(ctx: Optional[Context] = None) -> Dict:
    """Team overview dashboard for managers showing headcount, role breakdown, and team member details."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        reports = await _fetch_direct_reports(wctx.workday_access_token, wctx.workday_id)
        title_counts: Dict[str, int] = {}
        org_counts: Dict[str, int] = {}
        members = []
        for r in reports:
            title = r.get("businessTitle") or "Unknown"
            org = r.get("primarySupervisoryOrganization") or "Unknown"
            title_counts[title] = title_counts.get(title, 0) + 1
            org_counts[org] = org_counts.get(org, 0) + 1
            members.append(
                {
                    "name": r.get("descriptor"),
                    "email": r.get("primaryWorkEmail"),
                    "businessTitle": title,
                    "organization": org,
                    "isManager": r.get("isManager"),
                }
            )
        payload = {
            "success": True,
            "totalHeadcount": len(reports),
            "byTitle": title_counts,
            "byOrganization": org_counts,
            "teamMembers": members,
        }
        return _tool_response("Team overview dashboard.", payload)
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_team_overview_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_team_performance_summary(ctx: Optional[Context] = None) -> Dict:
    """Team performance review status for managers with inbox tasks and absence overview."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        access_token = wctx.workday_access_token
        workday_id = wctx.workday_id

        endpoints = get_endpoints()
        dr_url = endpoints.full_url(
            "/ccx/api/common/v1/{tenant}/workers/{workday_id}/directReports",
            workday_id=workday_id,
        )
        inbox_tasks, dr_data = await asyncio.gather(
            _fetch_inbox_tasks(access_token, workday_id),
            _fetch_json(dr_url, access_token),
        )

        report_items = dr_data.get("data", [])
        report_lookup = []
        for item in report_items:
            wid = item.get("id")
            if wid:
                report_lookup.append(
                    {
                        "id": wid,
                        "name": item.get("descriptor", "Unknown"),
                        "title": item.get("businessTitle"),
                    }
                )

        time_off_results = await asyncio.gather(
            *[_get_time_off_details(access_token, r["id"]) for r in report_lookup]
        )

        pending_reviews = []
        pending_approvals = []
        other_tasks = []
        for t in inbox_tasks:
            step = (t.get("stepType") or "").lower()
            subject = (t.get("subject") or "").lower()
            if "review" in step or "review" in subject:
                pending_reviews.append(t)
            elif "approval" in step or "approval" in subject:
                pending_approvals.append(t)
            else:
                other_tasks.append(t)

        today = datetime.now().date().isoformat()
        currently_out: List[Dict[str, Any]] = []
        upcoming_absences: List[Dict[str, Any]] = []
        for report, time_offs in zip(report_lookup, time_off_results):
            for entry in time_offs:
                date = entry.get("date", "")
                status = (entry.get("status") or "").lower()
                if "cancel" in status:
                    continue
                absence_record = {"name": report["name"], **entry}
                if date == today:
                    currently_out.append(absence_record)
                elif date > today:
                    upcoming_absences.append(absence_record)

        payload = {
            "success": True,
            "inboxSummary": {
                "totalPending": len(inbox_tasks),
                "pendingReviews": len(pending_reviews),
                "pendingApprovals": len(pending_approvals),
                "otherTasks": len(other_tasks),
                "tasks": inbox_tasks,
            },
            "absenceOverview": {
                "currentlyOut": currently_out,
                "upcoming": upcoming_absences,
                "totalCurrentlyOut": len(currently_out),
                "totalUpcoming": len(upcoming_absences),
            },
            "openActionItems": len(inbox_tasks),
        }
        return _tool_response("Team performance and review status summary.", payload)
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_team_performance_summary_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_action_inbox_task(
    task_id: str,
    decision: str,
    comment: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict:
    """Approve or reject a Workday inbox task.

    Only works for tasks whose stepType is Approval.
    """
    try:
        worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
        action = "approve" if decision == "approve" else "deny"
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/common/v1/{tenant}/workers/{workday_id}/inboxTasks/{task_id}/{action}",
            workday_id=worker_context.workday_id,
            task_id=task_id,
            action=action,
        )
        headers = {
            "Authorization": f"Bearer {worker_context.workday_access_token}",
            "Content-Type": "application/json",
        }
        body: Dict[str, Any] = {}
        if comment:
            body["comment"] = comment

        async with create_async_client() as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type and response.content:
                result = response.json()
            else:
                result = {"status": "completed"}

        payload = {
            "success": True,
            "decision": decision,
            "taskId": task_id,
            "result": result,
        }
        return _tool_response("Approve or reject a Workday inbox task.", payload)
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_action_inbox_task_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_inbox_task_detail(
    task_id: str,
    ctx: Optional[Context] = None,
) -> Dict:
    """Get detailed information about a specific Workday inbox task by its task_id."""
    try:
        worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/common/v1/{tenant}/workers/{workday_id}/inboxTasks/{task_id}",
            workday_id=worker_context.workday_id,
            task_id=task_id,
        )
        data = await _fetch_json(url, worker_context.workday_access_token)
        payload = {
            "success": True,
            "title": data.get("descriptor", ""),
            "summary": data.get("overallProcess", {}).get("descriptor", ""),
            "status": data.get("status", {}).get("descriptor", ""),
            "stepType": data.get("stepType", {}).get("descriptor", ""),
            "initiator": data.get("initiator", {}).get("descriptor", ""),
            "assigned": data.get("assigned"),
            "due": data.get("due"),
            "taskId": task_id,
            "raw": data,
        }
        return _tool_response("Detailed information about a Workday inbox task.", payload)
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_inbox_task_detail_error", error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Performance Enablement tools ────────────────────────────────────


async def tool_get_goals(ctx: Optional[Context] = None) -> Dict:
    """Get performance goals for the current worker."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/performanceEnablement/v5/{tenant}/workers/{workday_id}/goals",
            workday_id=wctx.workday_id,
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        goals = []
        for item in data.get("data", []):
            goals.append({
                "id": item.get("id"),
                "name": item.get("name"),
                "description": item.get("description"),
                "status": item.get("status", {}).get("descriptor"),
                "state": item.get("state", {}).get("descriptor"),
                "dueDate": item.get("dueDate"),
                "completedOn": item.get("completedOn"),
                "category": [c.get("descriptor") for c in item.get("category", [])],
                "relatesTo": [r.get("descriptor") for r in item.get("relatesTo", [])],
                "supports": item.get("supports", {}).get("descriptor"),
            })
        payload = {"success": True, "goals": goals, "total": len(goals)}
        return _tool_response("Worker performance goals.", payload)
    except WorkdayApiNotAvailable:
        return {"success": False, "error": "Performance Enablement API is not available for this tenant."}
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_goals_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_feedback(ctx: Optional[Context] = None) -> Dict:
    """Get anytime feedback events received by the current worker."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/performanceEnablement/v5/{tenant}/workers/{workday_id}/anytimeFeedbackEvents",
            workday_id=wctx.workday_id,
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        events = []
        for item in data.get("data", []):
            events.append({
                "id": item.get("id"),
                "comment": item.get("comment"),
                "badge": item.get("badge", {}).get("descriptor"),
                "fromWorker": item.get("fromWorker", {}).get("descriptor"),
                "toWorker": item.get("toWorker", {}).get("descriptor"),
                "feedbackGivenDate": item.get("feedbackGivenDate"),
                "hiddenFromWorker": item.get("hiddenFromWorker"),
                "hiddenFromManager": item.get("hiddenFromManager"),
            })
        payload = {"success": True, "feedbackEvents": events, "total": len(events)}
        return _tool_response("Anytime feedback received.", payload)
    except WorkdayApiNotAvailable:
        return {"success": False, "error": "Performance Enablement API is not available for this tenant."}
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_feedback_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_give_feedback(
    worker_id: str,
    comment: str,
    badge: Optional[str] = None,
    hidden_from_worker: bool = False,
    hidden_from_manager: bool = False,
    ctx: Optional[Context] = None,
) -> Dict:
    """Give anytime feedback to a worker.

    Args:
        worker_id: The Workday ID of the worker to give feedback to.
        comment: The feedback comment text.
        badge: Optional feedback badge ID (use get_feedback_badges to see available badges).
        hidden_from_worker: If True, feedback is hidden from the worker.
        hidden_from_manager: If True, feedback is hidden from the worker's manager.
    """
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/performanceEnablement/v5/{tenant}/workers/{workday_id}/anytimeFeedbackEvents",
            workday_id=wctx.workday_id,
        )
        body: Dict[str, Any] = {
            "toWorker": {"id": worker_id},
            "comment": comment,
            "hiddenFromWorker": hidden_from_worker,
            "hiddenFromManager": hidden_from_manager,
        }
        if badge:
            body["badge"] = {"id": badge}
        headers = {
            "Authorization": f"Bearer {wctx.workday_access_token}",
            "Content-Type": "application/json",
        }
        async with create_async_client() as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type and response.content:
                result = response.json()
            else:
                result = {"status": "submitted"}
        payload = {
            "success": True,
            "message": "Feedback submitted successfully.",
            "result": result,
        }
        return _tool_response("Give anytime feedback.", payload)
    except WorkdayApiNotAvailable:
        return {"success": False, "error": "Performance Enablement API is not available for this tenant."}
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_give_feedback_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_feedback_badges(ctx: Optional[Context] = None) -> Dict:
    """Get available feedback badges that can be used when giving feedback."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/performanceEnablement/v5/{tenant}/feedbackBadges",
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        badges = []
        for item in data.get("data", []):
            badges.append({
                "id": item.get("workdayID") or item.get("id"),
                "descriptor": item.get("name") or item.get("descriptor"),
                "badgeId": item.get("feedbackBadgeID"),
            })
        payload = {"success": True, "badges": badges, "total": len(badges)}
        return _tool_response("Available feedback badges.", payload)
    except WorkdayApiNotAvailable:
        return {"success": False, "error": "Performance Enablement API is not available for this tenant."}
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_feedback_badges_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_development_items(ctx: Optional[Context] = None) -> Dict:
    """Get development items (individual development plan) for the current worker."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/performanceEnablement/v5/{tenant}/workers/{workday_id}/developmentItems",
            workday_id=wctx.workday_id,
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        items = []
        for item in data.get("data", []):
            items.append({
                "id": item.get("id"),
                "title": item.get("title") or item.get("descriptor"),
                "status": item.get("status", {}).get("descriptor"),
                "startDate": item.get("startDate"),
                "completionDate": item.get("completionDate"),
                "additionalInformation": item.get("additionalInformation"),
                "category": [c.get("descriptor") for c in item.get("category", [])],
                "skills": [s.get("descriptor") for s in item.get("relatedSkills", item.get("skills", []))],
            })
        payload = {"success": True, "developmentItems": items, "total": len(items)}
        return _tool_response("Worker development items.", payload)
    except WorkdayApiNotAvailable:
        return {"success": False, "error": "Performance Enablement API is not available for this tenant."}
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_development_items_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_request_feedback_on_self(
    comment: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict:
    """Request feedback on yourself from peers/managers.

    Args:
        comment: Optional message to include with the feedback request.
    """
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/performanceEnablement/v5/{tenant}/workers/{workday_id}/requestedFeedbackOnSelfEvents",
            workday_id=wctx.workday_id,
        )
        body: Dict[str, Any] = {}
        if comment:
            body["comment"] = comment
        headers = {
            "Authorization": f"Bearer {wctx.workday_access_token}",
            "Content-Type": "application/json",
        }
        async with create_async_client() as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type and response.content:
                result = response.json()
            else:
                result = {"status": "submitted"}
        payload = {
            "success": True,
            "message": "Feedback request submitted.",
            "result": result,
        }
        return _tool_response("Request feedback on self.", payload)
    except WorkdayApiNotAvailable:
        return {"success": False, "error": "Performance Enablement API is not available for this tenant."}
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_request_feedback_on_self_error", error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Learning tools ──────────────────────────────────────────────────


async def tool_get_learning_records(
    limit: int = 20,
    ctx: Optional[Context] = None,
) -> Dict:
    """Get learning history and completion records for the current worker.

    Args:
        limit: Maximum number of records to return (default: 20, max: 100).
    """
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        safe_limit = max(1, min(int(limit), 100))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/learning/v1/{tenant}/records?learner={workday_id}&limit={limit}",
            workday_id=wctx.workday_id,
            limit=str(safe_limit),
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        records = []
        for item in data.get("data", []):
            records.append({
                "id": item.get("id"),
                "content": item.get("content", {}).get("descriptor"),
                "contentId": item.get("content", {}).get("id"),
                "completionStatus": item.get("completionStatus", {}).get("descriptor"),
                "completionDate": item.get("completionDate"),
                "expirationDate": item.get("expirationDate"),
                "grade": item.get("grade"),
                "score": item.get("score"),
                "registrationDate": item.get("registrationDate"),
            })
        payload = {"success": True, "records": records, "total": len(records)}
        return _tool_response("Learning history records.", payload)
    except WorkdayApiNotAvailable:
        return {"success": False, "error": "Learning API is not available for this tenant."}
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_learning_records_error", error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Staffing / Check-in tools ──────────────────────────────────────


async def tool_get_check_ins(
    ctx: Optional[Context] = None,
) -> Dict:
    """Get 1:1 check-in records for the current worker (manager or employee)."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/staffing/v7/{tenant}/workers/{workday_id}/checkIns",
            workday_id=wctx.workday_id,
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        check_ins = []
        for item in data.get("data", []):
            check_ins.append({
                "id": item.get("id"),
                "description": item.get("description"),
                "date": item.get("date"),
                "participant": item.get("participant", {}).get("descriptor"),
                "archived": item.get("archived"),
                "associatedTopics": [t.get("descriptor") for t in item.get("associatedTopics", [])],
            })
        payload = {"success": True, "checkIns": check_ins, "total": len(check_ins)}
        return _tool_response("Check-in records.", payload)
    except WorkdayApiNotAvailable:
        return {"success": False, "error": "Staffing Check-ins API is not available for this tenant."}
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_check_ins_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_create_check_in(
    description: str,
    date: str,
    participant_id: str,
    topic_ids: Optional[List[str]] = None,
    ctx: Optional[Context] = None,
) -> Dict:
    """Create a 1:1 check-in record.

    Args:
        description: Description or notes for the check-in.
        date: Date of the check-in (YYYY-MM-DD).
        participant_id: Workday ID of the other participant (e.g. a direct report).
        topic_ids: Optional list of check-in topic IDs to associate.
    """
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/staffing/v7/{tenant}/workers/{workday_id}/checkIns",
            workday_id=wctx.workday_id,
        )
        body: Dict[str, Any] = {
            "description": description,
            "date": date,
            "participant": {"id": participant_id},
        }
        if topic_ids:
            body["associatedTopics"] = [{"id": tid} for tid in topic_ids]
        headers = {
            "Authorization": f"Bearer {wctx.workday_access_token}",
            "Content-Type": "application/json",
        }
        async with create_async_client() as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type and response.content:
                result = response.json()
            else:
                result = {"status": "created"}
        payload = {
            "success": True,
            "message": "Check-in created successfully.",
            "result": result,
        }
        return _tool_response("Create a check-in.", payload)
    except WorkdayApiNotAvailable:
        return {"success": False, "error": "Staffing Check-ins API is not available for this tenant."}
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_create_check_in_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_check_in_topics(
    ctx: Optional[Context] = None,
) -> Dict:
    """Get check-in topics for the current worker (used for creating check-ins)."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/staffing/v7/{tenant}/workers/{workday_id}/checkInTopics",
            workday_id=wctx.workday_id,
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        topics = []
        for item in data.get("data", []):
            topics.append({
                "id": item.get("id"),
                "descriptor": item.get("descriptor"),
            })
        payload = {"success": True, "topics": topics, "total": len(topics)}
        return _tool_response("Check-in topics.", payload)
    except WorkdayApiNotAvailable:
        return {"success": False, "error": "Staffing Check-in Topics API is not available for this tenant."}
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_check_in_topics_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_worker_skills(ctx: Optional[Context] = None) -> Dict:
    """Get skills for the current worker from their Workday profile."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/staffing/v7/{tenant}/workers/{workday_id}/skillItems",
            workday_id=wctx.workday_id,
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        skills = []
        for item in data.get("data", []):
            skills.append({
                "id": item.get("id"),
                "skillName": item.get("descriptor") or item.get("skillName"),
            })
        payload = {"success": True, "skills": skills, "total": len(skills)}
        return _tool_response("Worker skills.", payload)
    except WorkdayApiNotAvailable:
        return {"success": False, "error": "Staffing Skills API is not available for this tenant."}
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_worker_skills_error", error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Manager tools ──────────────────────────────────────────────────


async def tool_get_team_goals(ctx: Optional[Context] = None) -> Dict:
    """Get performance goals for all direct reports (manager tool)."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        access_token = wctx.workday_access_token
        endpoints = get_endpoints()
        # Get direct reports first
        reports_url = endpoints.full_url(
            "/ccx/api/common/v1/{tenant}/workers/{workday_id}/directReports",
            workday_id=wctx.workday_id,
        )
        reports_data = await _fetch_json(reports_url, access_token)
        report_items = reports_data.get("data", [])

        async def _fetch_goals(worker_id: str, name: str) -> Dict[str, Any]:
            goal_url = endpoints.full_url(
                "/ccx/api/performanceEnablement/v5/{tenant}/workers/{workday_id}/goals",
                workday_id=worker_id,
            )
            try:
                data = await _fetch_json(goal_url, access_token)
                goals = []
                for item in data.get("data", []):
                    goals.append({
                        "name": item.get("name"),
                        "status": item.get("status", {}).get("descriptor"),
                        "state": item.get("state", {}).get("descriptor"),
                        "dueDate": item.get("dueDate"),
                    })
                return {"worker": name, "workerId": worker_id, "goals": goals}
            except httpx.HTTPStatusError:
                raise
            except Exception:  # noqa: BLE001
                return {"worker": name, "workerId": worker_id, "goals": [], "error": "Could not fetch goals"}

        results = await asyncio.gather(*[
            _fetch_goals(item.get("id"), item.get("descriptor", ""))
            for item in report_items if item.get("id")
        ])
        payload = {
            "success": True,
            "teamGoals": list(results),
            "totalReports": len(report_items),
        }
        return _tool_response("Team goals summary.", payload)
    except WorkdayApiNotAvailable:
        return {"success": False, "error": "Performance Enablement API is not available for this tenant."}
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_team_goals_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_request_feedback_on_worker(
    worker_id: str,
    comment: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict:
    """Request feedback on a specific worker (manager tool for direct reports).

    Args:
        worker_id: The Workday ID of the worker to request feedback on.
        comment: Optional message to include with the feedback request.
    """
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/performanceEnablement/v5/{tenant}/workers/{workday_id}/requestedFeedbackOnWorkerEvents",
            workday_id=wctx.workday_id,
        )
        body: Dict[str, Any] = {"worker": {"id": worker_id}}
        if comment:
            body["comment"] = comment
        headers = {
            "Authorization": f"Bearer {wctx.workday_access_token}",
            "Content-Type": "application/json",
        }
        async with create_async_client() as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type and response.content:
                result = response.json()
            else:
                result = {"status": "submitted"}
        payload = {
            "success": True,
            "message": "Feedback request submitted for worker.",
            "workerId": worker_id,
            "result": result,
        }
        return _tool_response("Request feedback on worker.", payload)
    except WorkdayApiNotAvailable:
        return {"success": False, "error": "Performance Enablement API is not available for this tenant."}
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_request_feedback_on_worker_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_prepare_give_feedback(ctx: Optional[Context] = None) -> Dict:
    """Load colleagues and feedback badges for the interactive feedback widget."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        people: List[Dict[str, Any]] = []
        badges: List[Dict[str, Any]] = []

        # Fetch direct reports first
        try:
            dr_url = endpoints.full_url(
                "/ccx/api/v1/{tenant}/workers/{workday_id}/directReports",
                workday_id=wctx.workday_id,
            )
            dr_data = await _fetch_json(dr_url, wctx.workday_access_token)
            for r in dr_data.get("data", []):
                people.append({
                    "workerId": r.get("id"),
                    "descriptor": r.get("descriptor"),
                    "businessTitle": r.get("businessTitle"),
                    "primaryWorkEmail": r.get("primaryWorkEmail"),
                })
        except Exception:
            pass

        # Fetch org chart members as additional candidates
        try:
            org_url = endpoints.full_url(
                "/ccx/api/v1/{tenant}/workers/{workday_id}/organizationChain",
                workday_id=wctx.workday_id,
            )
            org_data = await _fetch_json(org_url, wctx.workday_access_token)
            existing_ids = {p["workerId"] for p in people}
            for member in org_data.get("data", []):
                mid = member.get("id")
                if mid and mid != wctx.workday_id and mid not in existing_ids:
                    people.append({
                        "workerId": mid,
                        "descriptor": member.get("descriptor"),
                        "businessTitle": member.get("businessTitle"),
                        "primaryWorkEmail": member.get("primaryWorkEmail"),
                    })
                    existing_ids.add(mid)
        except Exception:
            pass

        # Fetch feedback badges
        try:
            badges_url = endpoints.full_url(
                "/ccx/api/performanceEnablement/v5/{tenant}/feedbackBadges"
            )
            badges_data = await _fetch_json(badges_url, wctx.workday_access_token)
            for b in badges_data.get("data", []):
                badges.append({
                    "id": b.get("workdayID") or b.get("id"),
                    "descriptor": b.get("name") or b.get("descriptor"),
                    "badgeId": b.get("feedbackBadgeID"),
                })
        except Exception:
            pass

        return {
            "people": people,
            "badges": badges,
            "workerName": wctx.worker_data.get("descriptor"),
            "_widget_hint": "Give feedback widget ready.",
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("workday_prepare_give_feedback_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_prepare_create_check_in(ctx: Optional[Context] = None) -> Dict:
    """Load direct reports and check-in topics for the interactive check-in creation widget."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        people: List[Dict[str, Any]] = []
        topics: List[Dict[str, Any]] = []

        # Fetch direct reports
        try:
            dr_url = endpoints.full_url(
                "/ccx/api/v1/{tenant}/workers/{workday_id}/directReports",
                workday_id=wctx.workday_id,
            )
            dr_data = await _fetch_json(dr_url, wctx.workday_access_token)
            for r in dr_data.get("data", []):
                people.append({
                    "workerId": r.get("id"),
                    "descriptor": r.get("descriptor"),
                    "businessTitle": r.get("businessTitle"),
                    "primaryWorkEmail": r.get("primaryWorkEmail"),
                })
        except Exception:
            pass

        # Fetch check-in topics
        try:
            topics_url = endpoints.full_url(
                "/ccx/api/performanceEnablement/v5/{tenant}/checkInTopics"
            )
            topics_data = await _fetch_json(topics_url, wctx.workday_access_token)
            for t in topics_data.get("data", []):
                topics.append({
                    "id": t.get("id"),
                    "descriptor": t.get("descriptor"),
                })
        except Exception:
            pass

        return {
            "people": people,
            "topics": topics,
            "workerName": wctx.worker_data.get("descriptor"),
            "_widget_hint": "Check-in form ready.",
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:
        LOGGER.error("workday_prepare_create_check_in_error", error=str(exc))
        return {"success": False, "error": str(exc)}


# ── Staffing / Hiring tools ─────────────────────────────────────────


async def tool_get_job_profiles(
    ctx: Optional[Context] = None,
    search: Optional[str] = None,
    limit: int = 20,
) -> Dict:
    """List Workday job profiles. Uses Staffing REST API GET /jobProfiles."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url("/ccx/api/staffing/v6/{tenant}/jobProfiles")
        params: Dict[str, Any] = {"limit": min(limit, 100)}
        if search:
            params["search"] = search
        data = await _fetch_json_with_params(url, wctx.workday_access_token, params)
        profiles = []
        for item in data.get("data", []):
            profiles.append({
                "id": item.get("id"),
                "descriptor": item.get("descriptor"),
                "name": item.get("name"),
                "isActive": item.get("isActive"),
                "isPublic": item.get("isPublic"),
                "jobFamily": item.get("jobFamily", {}).get("descriptor") if item.get("jobFamily") else None,
                "managementLevel": item.get("managementLevel", {}).get("descriptor") if item.get("managementLevel") else None,
            })
        return {
            "success": True,
            "total": data.get("total", len(profiles)),
            "profiles": profiles,
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_job_profiles_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_job_profile(
    ctx: Optional[Context] = None,
    job_profile_id: str = "",
) -> Dict:
    """Get details of a single Workday job profile. Uses Staffing REST API GET /jobProfiles/{ID}."""
    if not job_profile_id:
        raise ValueError("job_profile_id is required")
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/staffing/v6/{tenant}/jobProfiles/{job_profile_id}",
            job_profile_id=job_profile_id,
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        profile = {
            "id": data.get("id"),
            "descriptor": data.get("descriptor"),
            "name": data.get("name"),
            "isActive": data.get("isActive"),
            "isPublic": data.get("isPublic"),
            "jobFamily": data.get("jobFamily", {}).get("descriptor") if data.get("jobFamily") else None,
            "managementLevel": data.get("managementLevel", {}).get("descriptor") if data.get("managementLevel") else None,
            "jobCategory": data.get("jobCategory", {}).get("descriptor") if data.get("jobCategory") else None,
        }
        return {"success": True, "profile": profile}
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_job_profile_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_job_families(
    ctx: Optional[Context] = None,
    search: Optional[str] = None,
    limit: int = 20,
) -> Dict:
    """List Workday job families. Uses Staffing REST API GET /jobFamilies."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url("/ccx/api/staffing/v6/{tenant}/jobFamilies")
        params: Dict[str, Any] = {"limit": min(limit, 100)}
        if search:
            params["search"] = search
        data = await _fetch_json_with_params(url, wctx.workday_access_token, params)
        families = []
        for item in data.get("data", []):
            families.append({
                "id": item.get("id"),
                "descriptor": item.get("descriptor"),
                "isActive": item.get("isActive"),
                "summary": item.get("summary"),
            })
        return {
            "success": True,
            "total": data.get("total", len(families)),
            "families": families,
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_job_families_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_jobs(
    ctx: Optional[Context] = None,
    search: Optional[str] = None,
    limit: int = 20,
) -> Dict:
    """List Workday jobs. Uses Staffing REST API GET /jobs."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url("/ccx/api/staffing/v6/{tenant}/jobs")
        params: Dict[str, Any] = {"limit": min(limit, 100)}
        if search:
            params["search"] = search
        data = await _fetch_json_with_params(url, wctx.workday_access_token, params)
        jobs = []
        for item in data.get("data", []):
            jobs.append({
                "id": item.get("id"),
                "descriptor": item.get("descriptor"),
            })
        return {
            "success": True,
            "total": data.get("total", len(jobs)),
            "jobs": jobs,
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_jobs_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_job_requisitions(
    ctx: Optional[Context] = None,
    search: Optional[str] = None,
    limit: int = 20,
) -> Dict:
    """List open job requisitions. Uses Staffing REST API GET /values/jobChangesGroup/jobRequisitions."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url("/ccx/api/staffing/v6/{tenant}/values/jobChangesGroup/jobRequisitions")
        params: Dict[str, Any] = {"limit": min(limit, 100)}
        if search:
            params["search"] = search
        data = await _fetch_json_with_params(url, wctx.workday_access_token, params)
        requisitions = []
        for item in data.get("data", []):
            requisitions.append({
                "id": item.get("id"),
                "descriptor": item.get("descriptor"),
            })
        return {
            "success": True,
            "total": data.get("total", len(requisitions)),
            "requisitions": requisitions,
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_job_requisitions_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_supervisory_orgs(
    ctx: Optional[Context] = None,
    search: Optional[str] = None,
    limit: int = 20,
) -> Dict:
    """List supervisory organizations. Uses Staffing REST API GET /supervisoryOrganizations."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url("/ccx/api/staffing/v6/{tenant}/supervisoryOrganizations")
        params: Dict[str, Any] = {"limit": min(limit, 100)}
        if search:
            params["search"] = search
        data = await _fetch_json_with_params(url, wctx.workday_access_token, params)
        orgs = []
        for item in data.get("data", []):
            orgs.append({
                "id": item.get("id"),
                "descriptor": item.get("descriptor"),
            })
        return {
            "success": True,
            "total": data.get("total", len(orgs)),
            "organizations": orgs,
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_supervisory_orgs_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_supervisory_org_members(
    ctx: Optional[Context] = None,
    org_id: str = "",
    limit: int = 50,
) -> Dict:
    """List members of a supervisory organization. Uses Staffing REST API GET /supervisoryOrganizations/{ID}/members."""
    if not org_id:
        raise ValueError("org_id is required")
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/staffing/v6/{tenant}/supervisoryOrganizations/{org_id}/members",
            org_id=org_id,
        )
        data = await _fetch_json_with_params(url, wctx.workday_access_token, {"limit": min(limit, 100)})
        members = []
        for item in data.get("data", []):
            members.append({
                "id": item.get("id"),
                "descriptor": item.get("descriptor"),
            })
        return {
            "success": True,
            "total": data.get("total", len(members)),
            "organizationId": org_id,
            "members": members,
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_supervisory_org_members_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_create_job_change(
    ctx: Optional[Context] = None,
    worker_id: str = "",
    reason_id: str = "",
    job_profile_id: Optional[str] = None,
    supervisory_org_id: Optional[str] = None,
    position_id: Optional[str] = None,
    job_requisition_id: Optional[str] = None,
) -> Dict:
    """Initiate a job change for a worker. Uses Staffing REST API POST /workers/{ID}/jobChanges.

    This is the Workday mechanism for hiring, promoting, or transferring a worker
    into a new position. Provide the worker_id, a change reason, and optionally
    a target job profile, supervisory org, position, or job requisition.
    Returns the job change event ID which can be further configured and then
    submitted with submit_job_change.
    """
    if not worker_id:
        raise ValueError("worker_id is required")
    if not reason_id:
        raise ValueError("reason_id is required. Use get_job_change_reasons to look up valid values.")
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/staffing/v6/{tenant}/workers/{worker_id}/jobChanges",
            worker_id=worker_id,
        )
        body: Dict[str, Any] = {
            "reason": {"id": reason_id},
        }
        if job_profile_id:
            body["jobProfile"] = {"id": job_profile_id}
        if supervisory_org_id:
            body["supervisoryOrganization"] = {"id": supervisory_org_id}
        if position_id:
            body["position"] = {"id": position_id}
        if job_requisition_id:
            body["jobRequisition"] = {"id": job_requisition_id}
        headers = {
            "Authorization": f"Bearer {wctx.workday_access_token}",
            "Content-Type": "application/json",
        }
        async with create_async_client() as client:
            response = await client.post(url, json=body, headers=headers)
            if response.is_error:
                error_body = response.text[:500]
                LOGGER.error("workday_create_job_change_error", status=response.status_code, body=error_body)
                response.raise_for_status()
            result = response.json()
        return {
            "success": True,
            "jobChangeId": result.get("id"),
            "descriptor": result.get("descriptor"),
            "message": "Job change initiated. Configure further details then call submit_job_change.",
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_create_job_change_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_job_change(
    ctx: Optional[Context] = None,
    job_change_id: str = "",
) -> Dict:
    """Get details of a job change event. Uses Staffing REST API GET /jobChanges/{ID}."""
    if not job_change_id:
        raise ValueError("job_change_id is required")
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/staffing/v6/{tenant}/jobChanges/{job_change_id}",
            job_change_id=job_change_id,
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        return {
            "success": True,
            "id": data.get("id"),
            "descriptor": data.get("descriptor"),
            "worker": data.get("worker", {}).get("descriptor"),
            "reason": data.get("reason", {}).get("descriptor"),
            "status": data.get("status", {}).get("descriptor") if data.get("status") else None,
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_job_change_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_submit_job_change(
    ctx: Optional[Context] = None,
    job_change_id: str = "",
) -> Dict:
    """Submit a job change for processing. Uses Staffing REST API POST /jobChanges/{ID}/submit."""
    if not job_change_id:
        raise ValueError("job_change_id is required")
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/staffing/v6/{tenant}/jobChanges/{job_change_id}/submit",
            job_change_id=job_change_id,
        )
        headers = {
            "Authorization": f"Bearer {wctx.workday_access_token}",
            "Content-Type": "application/json",
        }
        async with create_async_client() as client:
            response = await client.post(url, json={}, headers=headers)
            if response.is_error:
                error_body = response.text[:500]
                LOGGER.error("workday_submit_job_change_error", status=response.status_code, body=error_body)
                response.raise_for_status()
            result = response.json()
        return {
            "success": True,
            "jobChangeId": job_change_id,
            "descriptor": result.get("descriptor"),
            "message": "Job change submitted for approval.",
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_submit_job_change_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_job_change_reasons(
    ctx: Optional[Context] = None,
    search: Optional[str] = None,
    limit: int = 20,
) -> Dict:
    """List valid job change reasons (e.g. New Hire, Promotion, Transfer). Uses Staffing REST API GET /values/jobChangesGroup/reason."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url("/ccx/api/staffing/v6/{tenant}/values/jobChangesGroup/reason")
        params: Dict[str, Any] = {"limit": min(limit, 100)}
        if search:
            params["search"] = search
        data = await _fetch_json_with_params(url, wctx.workday_access_token, params)
        reasons = []
        for item in data.get("data", []):
            reasons.append({
                "id": item.get("id"),
                "descriptor": item.get("descriptor"),
            })
        return {
            "success": True,
            "total": data.get("total", len(reasons)),
            "reasons": reasons,
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_job_change_reasons_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_create_org_assignment_change(
    ctx: Optional[Context] = None,
    worker_id: str = "",
    company_id: Optional[str] = None,
    cost_center_id: Optional[str] = None,
    region_id: Optional[str] = None,
    business_unit_id: Optional[str] = None,
) -> Dict:
    """Initiate an organization assignment change for a worker. Uses Staffing REST API POST /workers/{ID}/organizationAssignmentChanges.

    Assigns the worker to organizational entities such as company, cost center,
    region, or business unit. Returns the change event ID for further
    configuration and submission.
    """
    if not worker_id:
        raise ValueError("worker_id is required")
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/staffing/v6/{tenant}/workers/{worker_id}/organizationAssignmentChanges",
            worker_id=worker_id,
        )
        body: Dict[str, Any] = {}
        if company_id:
            body["company"] = {"id": company_id}
        if cost_center_id:
            body["costCenter"] = {"id": cost_center_id}
        if region_id:
            body["region"] = {"id": region_id}
        if business_unit_id:
            body["businessUnit"] = {"id": business_unit_id}
        headers = {
            "Authorization": f"Bearer {wctx.workday_access_token}",
            "Content-Type": "application/json",
        }
        async with create_async_client() as client:
            response = await client.post(url, json=body, headers=headers)
            if response.is_error:
                error_body = response.text[:500]
                LOGGER.error("workday_create_org_assignment_change_error", status=response.status_code, body=error_body)
                response.raise_for_status()
            result = response.json()
        return {
            "success": True,
            "changeId": result.get("id"),
            "descriptor": result.get("descriptor"),
            "message": "Organization assignment change initiated. Call submit_org_assignment_change to finalize.",
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_create_org_assignment_change_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_submit_org_assignment_change(
    ctx: Optional[Context] = None,
    change_id: str = "",
) -> Dict:
    """Submit an organization assignment change for processing. Uses Staffing REST API POST /organizationAssignmentChanges/{ID}/submit."""
    if not change_id:
        raise ValueError("change_id is required")
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        endpoints = get_endpoints()
        url = endpoints.full_url(
            "/ccx/api/staffing/v6/{tenant}/organizationAssignmentChanges/{change_id}/submit",
            change_id=change_id,
        )
        headers = {
            "Authorization": f"Bearer {wctx.workday_access_token}",
            "Content-Type": "application/json",
        }
        async with create_async_client() as client:
            response = await client.post(url, json={}, headers=headers)
            if response.is_error:
                error_body = response.text[:500]
                LOGGER.error("workday_submit_org_assignment_change_error", status=response.status_code, body=error_body)
                response.raise_for_status()
            result = response.json()
        return {
            "success": True,
            "changeId": change_id,
            "descriptor": result.get("descriptor"),
            "message": "Organization assignment change submitted for approval.",
        }
    except httpx.HTTPStatusError:
        raise
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_submit_org_assignment_change_error", error=str(exc))
        return {"success": False, "error": str(exc)}


WORKDAY_TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "get_worker",
        "func": tool_get_worker,
        "summary": "Get the current Workday worker profile. Result is rendered as an interactive widget.",
        "annotations": {
            "readOnlyHint": True,
        },
        "meta": {
            "openai/outputTemplate": "ui://widget/worker-profile.html",
            "openai/toolInvocation/invoking": "Loading worker profile\u2026",
            "openai/toolInvocation/invoked": "Worker profile ready.",
        },
    },
    {"name": "get_leave_balances", "func": tool_get_leave_balances, "summary": "Retrieve leave balances and eligible absence types for the current worker. The response includes eligibleAbsenceTypes[].id -- use this ID as timeOffTypeId when calling prepare_request_leave."},
    {"name": "get_direct_reports", "func": tool_get_direct_reports, "summary": "List direct reports for the current worker."},
    {
        "name": "get_inbox_tasks",
        "func": tool_get_inbox_tasks,
        "summary": "List Workday inbox tasks for the current worker. Result is rendered as an interactive widget with inline approve/deny.",
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/inbox-tasks.html",
            "openai/toolInvocation/invoking": "Loading inbox tasks\u2026",
            "openai/toolInvocation/invoked": "Inbox tasks ready.",
        },
    },
    {
        "name": "get_learning_assignments",
        "func": tool_get_learning_assignments,
        "summary": "Retrieve required learning assignments. Result is rendered as an interactive widget.",
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/learning-assignments.html",
            "openai/toolInvocation/invoking": "Loading learning assignments\u2026",
            "openai/toolInvocation/invoked": "Learning assignments ready.",
        },
    },
    {"name": "get_pay_slips", "func": tool_get_pay_slips, "summary": "List recent Workday pay slips."},
    {"name": "get_time_off_entries", "func": tool_get_time_off_entries, "summary": "List time off entries for the current worker."},
    {
        "name": "prepare_request_leave",
        "func": tool_prepare_request_leave,
        "summary": (
            "Book time off — opens the interactive leave booking form for the "
            "user to review and confirm. Use this when the user asks to book "
            "leave, request PTO, or take time off. Pass startDate, endDate, "
            "quantity, unit, and timeOffTypeId (from get_leave_balances). "
            "The user confirms and submits via the widget."
        ),
        "meta": {
            "openai/outputTemplate": "ui://widget/leave-booking.html",
            "openai/toolInvocation/invoking": "Preparing leave request\u2026",
            "openai/toolInvocation/invoked": "Leave request ready.",
        },
    },
    {"name": "book_leave", "func": tool_book_leave, "summary": "Submit leave request to Workday. Widget callback — called automatically by the leave booking form after the user clicks Submit. To book leave, use prepare_request_leave instead."},
    {
        "name": "prepare_change_business_title",
        "func": tool_prepare_change_business_title,
        "summary": (
            "Change business title — opens the interactive title change form "
            "for the user to enter a new title and submit. Use this when the "
            "user asks to change their business title."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/change-business-title.html",
            "openai/toolInvocation/invoking": "Loading business title form\u2026",
            "openai/toolInvocation/invoked": "Business title form ready.",
        },
    },
    {
        "name": "change_business_title",
        "func": tool_change_business_title,
        "summary": (
            "Submit business title change to Workday. Widget callback — "
            "called automatically by the title change form after the user clicks Submit. "
            "To change a business title, use prepare_change_business_title instead."
        ),
    },
    {"name": "search_learning_content", "func": tool_search_learning_content, "summary": "Search Workday learning content filtered by skills and/or category. Accepts optional 'category' (e.g. 'Cloud Computing') to narrow available skills and optional 'skills' list. Resolves names to Workday IDs automatically; invalid values are dropped.",
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/learning-catalog.html",
            "openai/toolInvocation/invoking": "Searching learning catalog\u2026",
            "openai/toolInvocation/invoked": "Learning catalog ready.",
        },
    },
    {"name": "get_org_chart", "func": tool_get_org_chart, "summary": "Get the organizational chart for the current worker's supervisory organization.",
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/org-chart.html",
            "openai/toolInvocation/invoking": "Loading org chart\u2026",
            "openai/toolInvocation/invoked": "Org chart ready.",
        },
    },
    {"name": "get_team_calendar", "func": tool_get_team_calendar, "summary": "Get the team time-off calendar showing who is out in the current worker's team.",
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/team-calendar.html",
            "openai/toolInvocation/invoking": "Loading team calendar\u2026",
            "openai/toolInvocation/invoked": "Team calendar ready.",
        },
    },
    {
        "name": "get_team_overview",
        "func": tool_get_team_overview,
        "summary": "Get a team overview dashboard for managers showing headcount, role breakdown, and team member details.",
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/team-dashboard.html",
            "openai/toolInvocation/invoking": "Loading team overview\u2026",
            "openai/toolInvocation/invoked": "Team overview ready.",
        },
    },
    {"name": "get_team_performance_summary", "func": tool_get_team_performance_summary, "summary": "Get team performance review status for managers including pending inbox items and team absence overview."},
    {
        "name": "action_inbox_task",
        "func": tool_action_inbox_task,
        "summary": "Approve or reject a Workday inbox task. Provide the task_id from get_inbox_tasks and decision ('approve' or 'deny'). Optionally include a comment.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_inbox_task_detail",
        "func": tool_get_inbox_task_detail,
        "summary": "Get detailed information about a specific Workday inbox task by its task_id.",
        "annotations": {"readOnlyHint": True},
    },
    # ── Performance Enablement ──
    {
        "name": "get_goals",
        "func": tool_get_goals,
        "summary": "Get your performance goals including status, due dates, and categories. Result is rendered as an interactive dashboard.",
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/goals-dashboard.html",
            "openai/toolInvocation/invoking": "Loading goals\u2026",
            "openai/toolInvocation/invoked": "Goals dashboard ready.",
        },
    },
    {
        "name": "get_feedback",
        "func": tool_get_feedback,
        "summary": "Get anytime feedback you've received from colleagues and managers.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "give_feedback",
        "func": tool_give_feedback,
        "summary": "Give anytime feedback to a colleague. Provide worker_id, comment, and optional badge ID (from get_feedback_badges).",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_feedback_badges",
        "func": tool_get_feedback_badges,
        "summary": "List available feedback badges that can be used when giving anytime feedback.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_development_items",
        "func": tool_get_development_items,
        "summary": "Get your individual development plan items including skills, dates, and status. Result is rendered as an interactive widget.",
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/development-items.html",
            "openai/toolInvocation/invoking": "Loading development items\u2026",
            "openai/toolInvocation/invoked": "Development items ready.",
        },
    },
    {
        "name": "request_feedback_on_self",
        "func": tool_request_feedback_on_self,
        "summary": "Request feedback on yourself from peers and managers. Optionally include a message.",
        "annotations": {"readOnlyHint": True},
    },
    # ── Learning ──
    {
        "name": "get_learning_records",
        "func": tool_get_learning_records,
        "summary": "Get your learning history with completion status, grades, scores, and expiration dates.",
        "annotations": {"readOnlyHint": True},
    },
    # ── Check-ins ──
    {
        "name": "get_check_ins",
        "func": tool_get_check_ins,
        "summary": "Get 1:1 check-in records with topics and notes.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "create_check_in",
        "func": tool_create_check_in,
        "summary": "Create a 1:1 check-in record. Provide description, date, participant_id, and optional topic_ids.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_check_in_topics",
        "func": tool_get_check_in_topics,
        "summary": "List check-in topics available for creating check-ins.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_worker_skills",
        "func": tool_get_worker_skills,
        "summary": "Get skills listed on your Workday profile.",
        "annotations": {"readOnlyHint": True},
    },
    # ── Manager ──
    {
        "name": "get_team_goals",
        "func": tool_get_team_goals,
        "summary": "Get performance goals for all direct reports showing goal status and due dates (manager tool). Result is rendered as an interactive widget.",
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/team-goals.html",
            "openai/toolInvocation/invoking": "Loading team goals\u2026",
            "openai/toolInvocation/invoked": "Team goals ready.",
        },
    },
    {
        "name": "request_feedback_on_worker",
        "func": tool_request_feedback_on_worker,
        "summary": "Request feedback on a specific direct report. Provide worker_id and optional comment (manager tool).",
        "annotations": {"readOnlyHint": True},
    },
    # ── Prepare (Widget Launchers) ──
    {
        "name": "prepare_give_feedback",
        "func": tool_prepare_give_feedback,
        "summary": (
            "Open the give feedback widget — select a colleague, pick a badge, and "
            "write feedback. Use when the user wants to recognize or give feedback to someone."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/give-feedback.html",
            "openai/toolInvocation/invoking": "Loading feedback form\u2026",
            "openai/toolInvocation/invoked": "Feedback form ready.",
        },
    },
    {
        "name": "prepare_create_check_in",
        "func": tool_prepare_create_check_in,
        "summary": (
            "Open the check-in creation widget — select a team member, choose topics, "
            "set a date, and create a 1:1 check-in. Use when a manager wants to schedule or create a check-in."
        ),
        "annotations": {"readOnlyHint": True},
        "meta": {
            "openai/outputTemplate": "ui://widget/create-check-in-form.html",
            "openai/toolInvocation/invoking": "Loading check-in form\u2026",
            "openai/toolInvocation/invoked": "Check-in form ready.",
        },
    },
    # ── Staffing / Hiring ──
    {
        "name": "get_job_profiles",
        "func": tool_get_job_profiles,
        "summary": "List Workday job profiles with optional search filter. Use to find the right job profile for a hire.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_job_profile",
        "func": tool_get_job_profile,
        "summary": "Get details of a single Workday job profile by ID including job family and management level.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_job_families",
        "func": tool_get_job_families,
        "summary": "List Workday job families with optional search filter. Job families group related job profiles.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_jobs",
        "func": tool_get_jobs,
        "summary": "List Workday jobs (filled positions) with optional search filter.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_job_requisitions",
        "func": tool_get_job_requisitions,
        "summary": "List open job requisitions. Use to find requisitions available for hiring into.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_supervisory_orgs",
        "func": tool_get_supervisory_orgs,
        "summary": "List supervisory organizations with optional search filter. Use to find the target org for a hire.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_supervisory_org_members",
        "func": tool_get_supervisory_org_members,
        "summary": "List members of a supervisory organization by org_id. Use to review current team composition or find internal candidates.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "get_job_change_reasons",
        "func": tool_get_job_change_reasons,
        "summary": "List valid job change reasons (e.g. New Hire, Promotion, Transfer). Use to get a reason_id for create_job_change.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "create_job_change",
        "func": tool_create_job_change,
        "summary": (
            "Initiate a job change for a worker (hire, promote, or transfer). "
            "Provide worker_id and reason_id (from get_job_change_reasons). Optionally provide "
            "job_profile_id, supervisory_org_id, position_id, or job_requisition_id. "
            "Returns a job change event ID for submit_job_change."
        ),
    },
    {
        "name": "get_job_change",
        "func": tool_get_job_change,
        "summary": "Get details and status of a job change event by its ID.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "submit_job_change",
        "func": tool_submit_job_change,
        "summary": "Submit a job change event for approval. Provide the job_change_id from create_job_change.",
    },
    {
        "name": "create_org_assignment_change",
        "func": tool_create_org_assignment_change,
        "summary": (
            "Initiate an organization assignment change for a worker. Assign company, "
            "cost center, region, or business unit. Returns a change ID for submit_org_assignment_change."
        ),
    },
    {
        "name": "submit_org_assignment_change",
        "func": tool_submit_org_assignment_change,
        "summary": "Submit an organization assignment change for approval. Provide the change_id from create_org_assignment_change.",
    },
]
