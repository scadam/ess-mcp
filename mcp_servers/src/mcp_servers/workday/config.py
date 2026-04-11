"""Workday-specific configuration models."""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel

from ..settings import load_workday_settings


class WorkdayApiEndpoints(BaseModel):
    tenant: str
    base_url: str
    skills_report: str
    learning_report: str

    def full_url(self, path_template: str, **kwargs: str) -> str:
        path = path_template.format(tenant=self.tenant, **kwargs)
        return f"{self.base_url}{path}"

    def skills_report_url(self) -> str:
        return f"{self.base_url}/ccx/service/customreport2/{self.tenant}/{self.skills_report}?format=json"

    def learning_report_url(self, workday_id: str) -> str:
        return (
            f"{self.base_url}/ccx/service/customreport2/{self.tenant}/{self.learning_report}"
            f"?Worker_s__for_Learning_Assignment%21WID={workday_id}&format=json"
        )


@lru_cache(maxsize=1)
def get_endpoints() -> WorkdayApiEndpoints:
    """Build endpoints from environment settings (cached)."""
    settings = load_workday_settings()
    return WorkdayApiEndpoints(
        tenant=settings.tenant,
        base_url=settings.base_url,
        skills_report=settings.skills_report,
        learning_report=settings.learning_report,
    )
