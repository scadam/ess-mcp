"""Pydantic models for Workday tool IO."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class WorkerSummary(BaseModel):
    workday_id: str = Field(..., alias="workdayId")
    worker_id: Optional[str] = Field(None, alias="workerId")
    name: Optional[str]
    email: Optional[str]
    worker_type: Optional[str] = Field(None, alias="workerType")
    business_title: Optional[str] = Field(None, alias="businessTitle")
    location: Optional[str]
    location_id: Optional[str] = Field(None, alias="locationId")
    country: Optional[str]
    country_code: Optional[str] = Field(None, alias="countryCode")
    supervisory_organization: Optional[str] = Field(None, alias="supervisoryOrganization")
    job_type: Optional[str] = Field(None, alias="jobType")
    job_profile: Optional[str] = Field(None, alias="jobProfile")
    primary_job_id: Optional[str] = Field(None, alias="primaryJobId")
    primary_job_descriptor: Optional[str] = Field(None, alias="primaryJobDescriptor")


class LeaveBalance(BaseModel):
    plan_name: str
    plan_id: str
    balance: str
    unit: str
    effective_date: Optional[str]
    time_off_types: Optional[str]


class AbsenceType(BaseModel):
    name: str
    id: str
    unit: str
    category: Optional[str]
    group: Optional[str]


class TimeOffEntry(BaseModel):
    date: str
    time_off_type: str
    quantity: str | int | float
    unit: str
    status: str
    comment: Optional[str]


class LeaveOfAbsence(BaseModel):
    id: str
    leave_type: str
    status: str
    first_day_of_leave: Optional[str]
    last_day_of_work: Optional[str]
    estimated_last_day: Optional[str]
    comment: Optional[str]


class TimeOffRequestDay(BaseModel):
    date: str
    start: str
    end: str
    daily_quantity: str
    comment: Optional[str]
    time_off_type_id: str = Field(..., alias="timeOffTypeId")


class BookingResult(BaseModel):
    success: bool
    message: str
    days_booked: int
    total_quantity: float
    business_process: Optional[str]
    status: Optional[str]
    transaction_status: Optional[str]


class InboxTask(BaseModel):
    assigned: Optional[str]
    due: Optional[str]
    initiator: Optional[str]
    status: Optional[str]
    step_type: Optional[str]
    subject: Optional[str]
    overall_process: Optional[str]
    descriptor: Optional[str]


class LearningAssignment(BaseModel):
    assignment_status: Optional[str]
    due_date: Optional[str]
    learning_content: Optional[str]
    overdue: bool
    required: bool
    workday_id: Optional[str]


class PaySlip(BaseModel):
    gross: Optional[str]
    status: Optional[str]
    net: Optional[str]
    date: Optional[str]
    descriptor: Optional[str]


class TimeOffEntryDetail(BaseModel):
    employee: Optional[str]
    time_off_request_status: Optional[str]
    time_off_request_descriptor: Optional[str]
    unit_of_time: Optional[str]
    time_off_plan: Optional[str]
    time_off_descriptor: Optional[str]
    date: Optional[str]
    units: Optional[str | float]
    descriptor: Optional[str]


class LearningLesson(BaseModel):
    id: Optional[str]
    descriptor: Optional[str]
    description: Optional[str]
    order: Optional[int]
    required: Optional[bool]
    content_type: Optional[str]
    duration: Optional[str]
    content_url: Optional[str] = Field(None, alias="contentURL")
    instructors: List[str] = []
    materials: List[str] = []
    activity_type: Optional[str]
    virtual_classroom_url: Optional[str] = Field(None, alias="virtualClassroomURL")
    location: Optional[str]
    track_attendance: Optional[bool]
    track_grades: Optional[bool]


class LearningContentItem(BaseModel):
    id: str
    descriptor: Optional[str]
    description: Optional[str]
    content_number: Optional[str] = Field(None, alias="contentNumber")
    content_url: Optional[str] = Field(None, alias="contentURL")
    version: Optional[str]
    created_on_date: Optional[str] = Field(None, alias="createdOnDate")
    average_rating: Optional[str] = Field(None, alias="averageRating")
    rating_count: Optional[str] = Field(None, alias="ratingCount")
    popularity: Optional[str]
    content_type: Optional[str]
    content_provider: Optional[str]
    access_type: Optional[str]
    delivery_mode: Optional[str]
    skill_level: Optional[str]
    lifecycle_status: Optional[str]
    availability_status: Optional[str]
    exclude_from_recommendations: Optional[bool]
    exclude_from_search_and_browse: Optional[bool]
    learning_catalogs: List[str] = []
    languages: List[str] = []
    skills: List[str] = []
    topics: List[str] = []
    security_categories: List[str] = []
    contact_persons: List[str] = []
    image_url: Optional[str] = Field(None, alias="imageURL")
    lessons: List[LearningLesson] = []


class RequestLeaveParameters(BaseModel):
    start_date: str = Field(..., alias="startDate")
    end_date: str = Field(..., alias="endDate")
    quantity: str
    unit: str
    reason: str
    time_off_type_id: str = Field(..., alias="timeOffTypeId")


class RequestLeavePreparation(BaseModel):
    request_parameters: RequestLeaveParameters = Field(..., alias="requestParameters")
    eligible_absence_types: list[dict] = Field(..., alias="eligibleAbsenceTypes")
    leave_balances: list[dict] = Field(..., alias="leaveBalances")
    booked_time_off: list[dict] = Field(..., alias="bookedTimeOff")
    workday_id: str = Field(..., alias="workdayId")
    booking_guidance: dict = Field(..., alias="bookingGuidance")
