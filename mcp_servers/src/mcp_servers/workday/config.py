"""Workday-specific configuration models."""

from __future__ import annotations

from pydantic import BaseModel


class WorkdayApiEndpoints(BaseModel):
    tenant: str
    base_url: str
    workers_path: str = "/ccx/api/workday/v3/workers"
    leave_balances_path: str = "/ccx/api/absenceManagement/v1/{tenant}/balances"
    eligible_absence_path: str = (
        "/ccx/api/absenceManagement/v1/{tenant}/workers/{worker_id}/eligibleAbsenceTypes"
    )
    time_off_details_path: str = (
        "/ccx/api/absenceManagement/v1/{tenant}/workers/{worker_id}/timeOffDetails"
    )
    request_time_off_path: str = (
        "/ccx/api/absenceManagement/v1/{tenant}/workers/{worker_id}/requestTimeOff"
    )

    def full_url(self, path_template: str, **kwargs: str) -> str:
        path = path_template.format(tenant=self.tenant, **kwargs)
        return f"{self.base_url}{path}"


DEFAULT_ENDPOINTS = WorkdayApiEndpoints(
    tenant="microsoft_dpt6",
    base_url="https://wd2-impl-services1.workday.com",
    workers_path="/ccx/api/workday/v3/workers",
)
