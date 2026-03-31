
import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from fastmcp import Context

from ..auth import get_bearer_token, TokenValidationError
from ..http import create_async_client
from ..logging import get_logger
from .helpers import build_worker_context_from_bearer

LOGGER = get_logger(__name__)


def _get_auth_token(ctx: Optional[Context] = None) -> str:
    """Extract the OAuth 2.0 Bearer token from the Authorization request header."""
    return get_bearer_token(ctx)



def _transform_worker(worker_data: Dict[str, Any]) -> Dict[str, Any]:
    primary_job = worker_data.get("primaryJob", {})
    location = primary_job.get("location", {})
    country = location.get("country", {})
    return {
        "workdayId": worker_data.get("id"),
        "workerId": worker_data.get("workerId"),
        "name": worker_data.get("descriptor"),
        "email": worker_data.get("person", {}).get("email"),
        "workerType": worker_data.get("workerType", {}).get("descriptor"),
        "businessTitle": primary_job.get("businessTitle"),
        "location": location.get("descriptor"),
        "locationId": location.get("Location_ID"),
        "country": country.get("descriptor"),
        "countryCode": country.get("ISO_3166-1_Alpha-3_Code"),
        "supervisoryOrganization": primary_job.get("supervisoryOrganization", {}).get(
            "descriptor"
        ),
        "jobType": primary_job.get("jobType", {}).get("descriptor"),
        "jobProfile": primary_job.get("jobProfile", {}).get("descriptor"),
        "primaryJobId": primary_job.get("id"),
        "primaryJobDescriptor": primary_job.get("descriptor"),
    }


async def _fetch_json(url: str, access_token: str) -> Dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    async with create_async_client() as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.json()


def _tool_response(summary: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return payload dict directly; fastmcp serialises it as structuredContent."""
    return payload


async def tool_get_worker(ctx: Optional[Context] = None) -> Dict:
    """Get the current Workday worker profile using the provided OAuth 2.0 bearer token."""
    worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    worker = _transform_worker(worker_context.worker_data)
    worker["_widget_hint"] = "Worker profile is ready."
    return worker


async def _get_leave_balances(access_token: str, workday_id: str) -> List[Dict[str, Any]]:
    url = (
        "https://wd2-impl-services1.workday.com/ccx/api/absenceManagement/v1/microsoft_dpt6/"
        f"balances?worker={workday_id}"
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
    url = (
        "https://wd2-impl-services1.workday.com/ccx/api/absenceManagement/v1/microsoft_dpt6/"
        f"workers/{workday_id}/eligibleAbsenceTypes"
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
    url = (
        "https://wd2-impl-services1.workday.com/ccx/api/absenceManagement/v1/microsoft_dpt6/"
        f"workers/{workday_id}/leavesOfAbsence"
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
    url = (
        "https://wd2-impl-services1.workday.com/ccx/api/absenceManagement/v1/microsoft_dpt6/"
        f"workers/{workday_id}/timeOffDetails"
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
    url = (
        "https://wd2-impl-services1.workday.com/ccx/api/common/v1/microsoft_dpt6/"
        f"workers/{workday_id}/directReports"
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


# Workday implementation tenant UI base -- derived from the API host pattern.
# wd2-impl-services1.workday.com -> impl.workday.com/{tenant}
_WORKDAY_TENANT = "microsoft_dpt6"
_WORKDAY_UI_BASE = f"https://impl.workday.com/{_WORKDAY_TENANT}"


def _workday_inbox_url() -> str:
    """Return the Workday inbox home URL for this tenant."""
    return f"{_WORKDAY_UI_BASE}/d/home.htmld"


def _workday_learning_url(content_id: str) -> Optional[str]:
    """Return the Workday Learning course-detail URL for a given content ID."""
    if not content_id:
        return None
    return f"{_WORKDAY_UI_BASE}/learning/course-details/{content_id}"


async def _fetch_inbox_tasks(access_token: str, workday_id: str) -> List[Dict[str, Any]]:
    url = (
        "https://wd2-impl-services1.workday.com/ccx/api/common/v1/microsoft_dpt6/"
        f"workers/{workday_id}/inboxTasks"
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
    url = (
        "https://wd2-impl-services1.workday.com/ccx/service/customreport2/"
        "microsoft_dpt6/svasireddy/Required_Learning"
        f"?Worker_s__for_Learning_Assignment%21WID={workday_id}&format=json"
    )
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
    url = (
        "https://wd2-impl-services1.workday.com/ccx/api/common/v1/microsoft_dpt6/"
        f"workers/{workday_id}/paySlips"
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
    url = (
        "https://wd2-impl-services1.workday.com/ccx/api/common/v1/microsoft_dpt6/"
        f"workers/{workday_id}/timeOffEntries"
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
    startDate: str = None,
    endDate: str = None,
    timeOffTypeId: str = None,
    quantity: str = "8",
    unit: str = "Hours",
    reason: str = "Time off request",
) -> Dict:
    worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
    
    if not startDate or not endDate or not timeOffTypeId:
        raise ValueError("startDate, endDate, and timeOffTypeId are required")
    
    days = _create_days_array(startDate, endDate, quantity, unit, reason, timeOffTypeId)
    url = (
        "https://wd2-impl-services1.workday.com/ccx/api/absenceManagement/v1/microsoft_dpt6/"
        f"workers/{worker_context.workday_id}/requestTimeOff"
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
            return {"success": False, "error": message}
    business_process = parsed_body.get("businessProcessParameters", {}).get(
        "overallBusinessProcess", {}
    ).get("descriptor")
    transaction_status = parsed_body.get("businessProcessParameters", {}).get(
        "transactionStatus", {}
    ).get("descriptor")
    days_booked = len(parsed_body.get("days", days))
    total_quantity = sum(float(day.get("dailyQuantity", 0)) for day in days)
    payload = {
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
    return _tool_response("Submit a leave request to Workday for the current worker.", payload)


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
    ctx: Optional[Context] = None, proposedBusinessTitle: str = None
) -> Dict:
    if not proposedBusinessTitle:
        return {"success": False, "error": "proposedBusinessTitle is required"}
    try:
        worker_context = await build_worker_context_from_bearer(_get_auth_token(ctx))
        url = (
            "https://wd2-impl-services1.workday.com/ccx/api/common/v1/microsoft_dpt6/"
            f"workers/{worker_context.workday_id}/businessTitleChanges?type=me"
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
                return {"success": False, "error": f"HTTP {response.status_code}: {body_text}"}
            data = response.json()
        result_payload = {
            "success": True,
            "message": "Business title change request submitted",
            "changeDetails": data,
        }
        return _tool_response("Request a business title change for the current worker.", result_payload)
    except Exception as exc:
        LOGGER.error("workday_change_business_title_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def _search_learning_content(access_token: str, skills: Iterable[str], topics: Iterable[str]) -> Dict[str, Any]:
    url = "https://wd2-impl-services1.workday.com/ccx/api/learning/v1/microsoft_dpt6/content"
    params: List[tuple[str, str]] = []
    for skill in skills:
        params.append(("skills", str(skill)))
    for topic in topics:
        params.append(("topics", str(topic)))
    async with create_async_client() as client:
        response = await client.get(url, params=params, headers={"Authorization": f"Bearer {access_token}"})
        response.raise_for_status()
        return response.json()


async def _get_lessons(access_token: str, content_id: str) -> Dict[str, Any]:
    url = f"https://wd2-impl-services1.workday.com/ccx/api/learning/v1/microsoft_dpt6/content/{content_id}/lessons"
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
        "skills": [s.get("descriptor") for s in content.get("skills", [])],
        "topics": [t.get("descriptor") for t in content.get("topics", [])],
        "securityCategories": [sc.get("descriptor") for sc in content.get("securityCategories", [])],
        "contactPersons": [cp.get("descriptor") for cp in content.get("contactPersons", [])],
        "imageURL": content.get("image", {}).get("publicURL"),
        "lessons": [],
    }


async def tool_search_learning_content(
    ctx: Optional[Context] = None,
    skills: Optional[List[str]] = None,
    topics: Optional[List[str]] = None,
) -> Dict:
    access_token = _get_auth_token(ctx)

    def _normalize(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, Iterable):
            return [str(item) for item in value]
        return [str(value)]

    skills = _normalize(skills)
    topics = _normalize(topics)
    content_response = await _search_learning_content(access_token, skills, topics)
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
    payload = {"success": True, "content": enriched, "total": len(enriched)}
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
    url = (
        "https://wd2-impl-services1.workday.com/ccx/api/common/v1/microsoft_dpt6/"
        f"workers/{worker_context.workday_id}/inboxTasks/{task_id}"
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
    url = (
        "https://wd2-impl-services1.workday.com/ccx/api/common/v1/microsoft_dpt6/"
        f"workers/{worker_context.workday_id}/inboxTasks/{task_id}/{action}"
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


async def tool_get_compensation(ctx: Optional[Context] = None) -> Dict:
    """Get compensation details for the current worker including salary, bonuses, and total compensation."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        url = (
            "https://wd2-impl-services1.workday.com/ccx/api/compensation/v3/microsoft_dpt6/"
            f"workers/{wctx.workday_id}/compensationHistory"
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        entries = []
        for item in data.get("data", []):
            entries.append(
                {
                    "effectiveDate": item.get("effectiveDate"),
                    "reason": item.get("reason", {}).get("descriptor"),
                    "basePay": item.get("basePay"),
                    "totalBasePay": item.get("totalBasePay"),
                    "totalSalaryAndAllowances": item.get("totalSalaryAndAllowances"),
                    "currency": item.get("currency", {}).get("descriptor"),
                    "frequency": item.get("frequency", {}).get("descriptor"),
                    "compensationPlanAssignments": [
                        {
                            "plan": a.get("compensationPlan", {}).get("descriptor"),
                            "amount": a.get("amount"),
                            "percentage": a.get("percentage"),
                            "currency": a.get("currency", {}).get("descriptor"),
                        }
                        for a in item.get("compensationPlanAssignments", [])
                    ],
                }
            )
        payload = {"success": True, "compensationHistory": entries, "total": len(entries)}
        return _tool_response("Compensation details for the current worker.", payload)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_compensation_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_benefits(ctx: Optional[Context] = None) -> Dict:
    """Get benefit elections for the current worker including health, dental, vision, and retirement plans."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        url = (
            "https://wd2-impl-services1.workday.com/ccx/api/benefits/v1/microsoft_dpt6/"
            f"workers/{wctx.workday_id}/benefitElections"
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        elections = []
        for item in data.get("data", []):
            elections.append(
                {
                    "benefitPlan": item.get("benefitPlan", {}).get("descriptor"),
                    "benefitPlanId": item.get("benefitPlan", {}).get("id"),
                    "coverageLevel": item.get("coverageLevel", {}).get("descriptor"),
                    "coverageBeginDate": item.get("coverageBeginDate"),
                    "deductionBeginDate": item.get("deductionBeginDate"),
                    "electionStatus": item.get("electionStatus", {}).get("descriptor"),
                    "benefitType": item.get("benefitType", {}).get("descriptor"),
                    "employeeCost": item.get("employeeCost"),
                    "employerContribution": item.get("employerContribution"),
                    "dependents": [
                        {
                            "name": d.get("descriptor"),
                            "relationship": d.get("relationship", {}).get("descriptor"),
                        }
                        for d in item.get("dependents", [])
                    ],
                }
            )
        payload = {"success": True, "benefitElections": elections, "total": len(elections)}
        return _tool_response("Benefit elections for the current worker.", payload)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_benefits_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_job_history(ctx: Optional[Context] = None) -> Dict:
    """Get job change history for the current worker including promotions, transfers, and title changes."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        url = (
            "https://wd2-impl-services1.workday.com/ccx/api/staffing/v6/microsoft_dpt6/"
            f"workers/{wctx.workday_id}/jobChanges"
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        changes = []
        for item in data.get("data", []):
            changes.append(
                {
                    "effectiveDate": item.get("effectiveDate"),
                    "reason": item.get("reason", {}).get("descriptor"),
                    "jobChangeType": item.get("jobChangeType", {}).get("descriptor"),
                    "previousJobProfile": item.get("previousJobProfile", {}).get("descriptor"),
                    "newJobProfile": item.get("newJobProfile", {}).get("descriptor"),
                    "previousBusinessTitle": item.get("previousBusinessTitle"),
                    "newBusinessTitle": item.get("newBusinessTitle"),
                    "previousLocation": item.get("previousLocation", {}).get("descriptor"),
                    "newLocation": item.get("newLocation", {}).get("descriptor"),
                    "previousSupervisoryOrg": item.get("previousSupervisoryOrganization", {}).get(
                        "descriptor"
                    ),
                    "newSupervisoryOrg": item.get("newSupervisoryOrganization", {}).get(
                        "descriptor"
                    ),
                    "status": item.get("status", {}).get("descriptor"),
                }
            )
        payload = {"success": True, "jobChanges": changes, "total": len(changes)}
        return _tool_response("Job change history for the current worker.", payload)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_job_history_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_org_chart(ctx: Optional[Context] = None) -> Dict:
    """Get the organizational chart for the current worker's supervisory organization."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        sup_org = wctx.worker_data.get("primaryJob", {}).get("supervisoryOrganization", {})
        org_id = sup_org.get("id")
        if not org_id:
            return {"success": False, "error": "No supervisory organization found for worker."}
        url = (
            "https://wd2-impl-services1.workday.com/ccx/api/workday/v3/microsoft_dpt6/"
            f"organizationCharts/{org_id}"
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        members = []
        for item in data.get("workers", []):
            members.append(
                {
                    "name": item.get("descriptor"),
                    "workerId": item.get("workerId"),
                    "businessTitle": item.get("primaryJob", {}).get("businessTitle"),
                    "jobProfile": item.get("primaryJob", {}).get("jobProfile", {}).get(
                        "descriptor"
                    ),
                    "isManager": item.get("isManager"),
                }
            )
        payload = {
            "success": True,
            "organization": sup_org.get("descriptor"),
            "organizationId": org_id,
            "members": members,
            "total": len(members),
        }
        return _tool_response("Organization chart for the worker's supervisory org.", payload)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_org_chart_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_worker_documents(ctx: Optional[Context] = None) -> Dict:
    """List personal documents for the current worker such as tax forms, offer letters, and policies."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        url = (
            "https://wd2-impl-services1.workday.com/ccx/api/documentManagement/v1/microsoft_dpt6/"
            f"workers/{wctx.workday_id}/documents"
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        documents = []
        for item in data.get("data", []):
            documents.append(
                {
                    "id": item.get("id"),
                    "name": item.get("descriptor"),
                    "category": item.get("documentCategory", {}).get("descriptor"),
                    "uploadDate": item.get("uploadDate"),
                    "fileSize": item.get("fileSize"),
                    "contentType": item.get("contentType"),
                    "fileName": item.get("fileName"),
                    "comment": item.get("comment", ""),
                }
            )
        payload = {"success": True, "documents": documents, "total": len(documents)}
        return _tool_response("Worker documents for the current worker.", payload)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_worker_documents_error", error=str(exc))
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
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_team_overview_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_team_compensation_summary(ctx: Optional[Context] = None) -> Dict:
    """Team compensation overview for managers with aggregate salary statistics."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        access_token = wctx.workday_access_token
        url = (
            "https://wd2-impl-services1.workday.com/ccx/api/common/v1/microsoft_dpt6/"
            f"workers/{wctx.workday_id}/directReports"
        )
        data = await _fetch_json(url, access_token)
        report_items = data.get("data", [])
        worker_ids = [item.get("id") for item in report_items if item.get("id")]

        async def _fetch_comp(worker_id: str) -> Dict[str, Any]:
            comp_url = (
                "https://wd2-impl-services1.workday.com/ccx/api/compensation/v3/microsoft_dpt6/"
                f"workers/{worker_id}/compensationHistory"
            )
            return await _fetch_json(comp_url, access_token)

        comp_results = await asyncio.gather(*[_fetch_comp(wid) for wid in worker_ids])

        base_pays: List[float] = []
        currency_counts: Dict[str, int] = {}
        band_counts: Dict[str, int] = {}
        for comp_data in comp_results:
            entries = comp_data.get("data", [])
            if not entries:
                continue
            latest = entries[0]
            total_base = latest.get("totalBasePay")
            if total_base is not None:
                try:
                    base_pays.append(float(total_base))
                except (ValueError, TypeError):
                    pass
            currency = latest.get("currency", {}).get("descriptor", "Unknown")
            currency_counts[currency] = currency_counts.get(currency, 0) + 1
            frequency = latest.get("frequency", {}).get("descriptor", "Unknown")
            band_counts[frequency] = band_counts.get(frequency, 0) + 1

        comp_stats: Dict[str, Any] = {}
        if base_pays:
            sorted_pays = sorted(base_pays)
            n = len(sorted_pays)
            median_val = (
                sorted_pays[n // 2]
                if n % 2 == 1
                else (sorted_pays[n // 2 - 1] + sorted_pays[n // 2]) / 2
            )
            comp_stats = {
                "min": min(base_pays),
                "max": max(base_pays),
                "median": median_val,
                "average": round(sum(base_pays) / len(base_pays), 2),
            }

        payload = {
            "success": True,
            "totalReports": len(worker_ids),
            "compensationRange": comp_stats,
            "byCurrency": currency_counts,
            "byFrequency": band_counts,
        }
        return _tool_response("Team compensation summary.", payload)
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_team_compensation_summary_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_team_performance_summary(ctx: Optional[Context] = None) -> Dict:
    """Team performance review status for managers with inbox tasks and absence overview."""
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        access_token = wctx.workday_access_token
        workday_id = wctx.workday_id

        dr_url = (
            "https://wd2-impl-services1.workday.com/ccx/api/common/v1/microsoft_dpt6/"
            f"workers/{workday_id}/directReports"
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
        url = (
            "https://wd2-impl-services1.workday.com/ccx/api/common/v1/microsoft_dpt6/"
            f"workers/{worker_context.workday_id}/inboxTasks/{task_id}/{action}"
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
        url = (
            "https://wd2-impl-services1.workday.com/ccx/api/common/v1/microsoft_dpt6/"
            f"workers/{worker_context.workday_id}/inboxTasks/{task_id}"
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
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_inbox_task_detail_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_submit_time_entry(
    date: str,
    hours: str,
    time_type: str = "Regular",
    comment: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict:
    """Submit a time entry to Workday for the current worker.

    Args:
        date: Date for the time entry (YYYY-MM-DD).
        hours: Number of hours worked (e.g. '8' or '4.5').
        time_type: Type of time entry (e.g. 'Regular', 'Overtime'). Defaults to 'Regular'.
        comment: Optional comment or description for the time entry.
    """
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        url = (
            "https://wd2-impl-services1.workday.com/ccx/api/time/v2/microsoft_dpt6/"
            f"workers/{wctx.workday_id}/timeEntries"
        )
        body: Dict[str, Any] = {
            "date": date,
            "hours": float(hours),
            "timeType": time_type,
        }
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

        return {
            "success": True,
            "message": f"Time entry of {hours}h submitted for {date}",
            "date": date,
            "hours": hours,
            "timeType": time_type,
            "result": result,
        }
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_submit_time_entry_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_time_entries(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict:
    """Get time entries for the current worker within a date range.

    Args:
        start_date: Start date for the range (YYYY-MM-DD). Defaults to start of current week.
        end_date: End date for the range (YYYY-MM-DD). Defaults to end of current week.
    """
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        if not start_date:
            today = datetime.now()
            start_date = (today - timedelta(days=today.weekday())).strftime("%Y-%m-%d")
        if not end_date:
            today = datetime.now()
            end_date = (today + timedelta(days=6 - today.weekday())).strftime("%Y-%m-%d")

        url = (
            "https://wd2-impl-services1.workday.com/ccx/api/time/v2/microsoft_dpt6/"
            f"workers/{wctx.workday_id}/timeEntries"
            f"?from={start_date}&to={end_date}"
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        entries = []
        for item in data.get("data", data.get("timeEntries", [])):
            entries.append({
                "date": item.get("date"),
                "hours": item.get("hours"),
                "timeType": item.get("timeType", {}).get("descriptor", ""),
                "status": item.get("status", {}).get("descriptor", ""),
                "comment": item.get("comment"),
            })
        return {
            "success": True,
            "startDate": start_date,
            "endDate": end_date,
            "entries": entries,
            "totalHours": sum(float(e.get("hours", 0) or 0) for e in entries),
            "total": len(entries),
        }
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_time_entries_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_create_expense_report(
    description: str,
    expense_date: str,
    amount: str,
    currency: str = "USD",
    expense_type: str = "Business Expense",
    memo: Optional[str] = None,
    ctx: Optional[Context] = None,
) -> Dict:
    """Create and submit an expense report entry in Workday.

    Args:
        description: Short description of the expense.
        expense_date: Date the expense was incurred (YYYY-MM-DD).
        amount: Expense amount (e.g. '125.50').
        currency: Currency code (default: USD).
        expense_type: Type of expense (e.g. 'Business Expense', 'Travel', 'Meals').
        memo: Additional notes or justification for the expense.
    """
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        url = (
            "https://wd2-impl-services1.workday.com/ccx/api/expenses/v1/microsoft_dpt6/"
            f"workers/{wctx.workday_id}/expenseReports"
        )
        body: Dict[str, Any] = {
            "description": description,
            "expenseLines": [
                {
                    "date": expense_date,
                    "amount": float(amount),
                    "currency": currency,
                    "expenseType": expense_type,
                    "memo": memo or description,
                }
            ],
        }
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

        return {
            "success": True,
            "message": f"Expense report created for {amount} {currency}",
            "description": description,
            "amount": amount,
            "currency": currency,
            "result": result,
        }
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_create_expense_report_error", error=str(exc))
        return {"success": False, "error": str(exc)}


async def tool_get_expense_reports(
    limit: int = 20,
    ctx: Optional[Context] = None,
) -> Dict:
    """Get expense reports for the current worker.

    Args:
        limit: Maximum number of expense reports to return (default: 20, max: 100).
    """
    try:
        wctx = await build_worker_context_from_bearer(_get_auth_token(ctx))
        safe_limit = max(1, min(int(limit), 100))
        url = (
            "https://wd2-impl-services1.workday.com/ccx/api/expenses/v1/microsoft_dpt6/"
            f"workers/{wctx.workday_id}/expenseReports?limit={safe_limit}"
        )
        data = await _fetch_json(url, wctx.workday_access_token)
        reports = []
        for item in data.get("data", data.get("expenseReports", [])):
            reports.append({
                "id": item.get("id"),
                "description": item.get("descriptor") or item.get("description"),
                "status": item.get("status", {}).get("descriptor", ""),
                "totalAmount": item.get("totalAmount"),
                "currency": item.get("currency", {}).get("descriptor", ""),
                "createdDate": item.get("createdDate"),
                "submittedDate": item.get("submittedDate"),
            })
        return {
            "success": True,
            "expenseReports": reports,
            "total": len(reports),
        }
    except Exception as exc:  # noqa: BLE001
        LOGGER.error("workday_get_expense_reports_error", error=str(exc))
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
    {"name": "get_inbox_tasks", "func": tool_get_inbox_tasks, "summary": "List Workday inbox tasks for the current worker."},
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
        "summary": "Prepare the data needed to submit a leave request. Pass startDate (YYYY-MM-DD), endDate (YYYY-MM-DD), quantity (number of hours or days), unit ('Hours' or 'Days'), and timeOffTypeId from eligibleAbsenceTypes[].id (from get_leave_balances). The widget renders and lets the user confirm before submitting.",
        "meta": {
            "openai/outputTemplate": "ui://widget/leave-booking.html",
            "openai/toolInvocation/invoking": "Preparing leave request\u2026",
            "openai/toolInvocation/invoked": "Leave request ready.",
        },
    },
    {"name": "book_leave", "func": tool_book_leave, "summary": "Submit a leave request to Workday. Called by the leave-booking widget when the user clicks Submit. Use prepare_request_leave first to display the booking form."},
    {
        "name": "prepare_change_business_title",
        "func": tool_prepare_change_business_title,
        "summary": (
            "Show the business title change form for the current worker. "
            "The widget handles submission."
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
            "Submit a business title change request to Workday. "
            "Called by the change-business-title widget when the user clicks Submit. "
            "Use prepare_change_business_title first."
        ),
    },
    {"name": "search_learning_content", "func": tool_search_learning_content, "summary": "Search Workday learning content and fetch associated lessons."},
    {"name": "get_compensation", "func": tool_get_compensation, "summary": "Get compensation details for the current worker including salary, bonuses, and total compensation history."},
    {"name": "get_benefits", "func": tool_get_benefits, "summary": "Get benefit elections for the current worker including health, dental, vision, and retirement plans."},
    {"name": "get_job_history", "func": tool_get_job_history, "summary": "Get job change history for the current worker including promotions, transfers, and title changes."},
    {"name": "get_org_chart", "func": tool_get_org_chart, "summary": "Get the organizational chart for the current worker's supervisory organization."},
    {"name": "get_worker_documents", "func": tool_get_worker_documents, "summary": "List personal documents for the current worker such as tax forms, offer letters, and policies."},
    {"name": "get_team_calendar", "func": tool_get_team_calendar, "summary": "Get the team time-off calendar showing who is out in the current worker's team."},
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
    {"name": "get_team_compensation_summary", "func": tool_get_team_compensation_summary, "summary": "Get team compensation overview for managers with aggregate salary statistics and currency breakdown."},
    {"name": "get_team_performance_summary", "func": tool_get_team_performance_summary, "summary": "Get team performance review status for managers including pending inbox items and team absence overview."},
    {
        "name": "action_inbox_task",
        "func": tool_action_inbox_task,
        "summary": "Approve or reject a Workday inbox task. Provide the task_id from get_inbox_tasks and decision ('approve' or 'deny'). Optionally include a comment.",
        "annotations": {"readOnlyHint": False},
    },
    {
        "name": "get_inbox_task_detail",
        "func": tool_get_inbox_task_detail,
        "summary": "Get detailed information about a specific Workday inbox task by its task_id.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "submit_time_entry",
        "func": tool_submit_time_entry,
        "summary": "Submit a time entry to Workday. Provide date (YYYY-MM-DD), hours worked, and optional time type and comment.",
        "annotations": {"readOnlyHint": False},
    },
    {
        "name": "get_time_entries",
        "func": tool_get_time_entries,
        "summary": "Get time entries for the current worker within a date range. Defaults to the current week.",
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "create_expense_report",
        "func": tool_create_expense_report,
        "summary": "Create and submit an expense report in Workday with description, date, amount, currency, and expense type.",
        "annotations": {"readOnlyHint": False},
    },
    {
        "name": "get_expense_reports",
        "func": tool_get_expense_reports,
        "summary": "List expense reports for the current worker with status, amounts, and submission dates.",
        "annotations": {"readOnlyHint": True},
    },
]
