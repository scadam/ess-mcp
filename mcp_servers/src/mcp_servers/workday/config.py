"""Workday-specific configuration models."""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel

from ..settings import load_workday_settings


class WorkdayApiEndpoints(BaseModel):
    tenant: str
    base_url: str

    def full_url(self, path_template: str, **kwargs: str) -> str:
        path = path_template.format(tenant=self.tenant, **kwargs)
        return f"{self.base_url}{path}"


@lru_cache(maxsize=1)
def get_endpoints() -> WorkdayApiEndpoints:
    """Build endpoints from environment settings (cached)."""
    settings = load_workday_settings()
    return WorkdayApiEndpoints(
        tenant=settings.tenant,
        base_url=settings.base_url,
    )
