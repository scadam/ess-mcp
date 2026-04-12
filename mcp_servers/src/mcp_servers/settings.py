"""Central configuration loading utilities."""
from __future__ import annotations
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings


class BaseEnvSettings(BaseSettings):
    model_config = {"env_file": None, "case_sensitive": True, "extra": "ignore"}


class WorkdaySettings(BaseEnvSettings):
    """Settings for Workday API access."""
    base_url: str = Field(..., alias="WORKDAY_BASE_URL")
    tenant: str = Field(..., alias="WORKDAY_TENANT")
    skills_report: str = Field("svasireddy/ESSMCPSkills", alias="WORKDAY_SKILLS_REPORT")
    learning_report: str = Field("svasireddy/Required_Learning", alias="WORKDAY_LEARNING_REPORT")
    openapi_server_domain: Optional[str] = Field(None, alias="OPENAPI_SERVER_DOMAIN")


class ServiceNowSettings(BaseEnvSettings):
    """Settings for ServiceNow API access."""
    instance_url: str = Field(..., alias="SERVICENOW_INSTANCE_URL")
    openapi_server_domain: Optional[str] = Field(None, alias="OPENAPI_SERVER_DOMAIN")


class SalesforceSettings(BaseEnvSettings):
    """Settings for Salesforce API access."""
    domain: str = Field(..., alias="SALESFORCE_DOMAIN")
    openapi_server_domain: Optional[str] = Field(None, alias="OPENAPI_SERVER_DOMAIN")


class JiraSettings(BaseEnvSettings):
    """Settings for Jira API access."""
    base_url: str = Field(..., alias="JIRA_BASE_URL")
    project_key: Optional[str] = Field(None, alias="JIRA_PROJECT_KEY")
    openapi_server_domain: Optional[str] = Field(None, alias="OPENAPI_SERVER_DOMAIN")


def _resolve_env_file(explicit: Optional[str] = None, prefix: str = "workday") -> Optional[str]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    for env_var in ("MCP_SERVERS_ENV_FILE",):
        value = os.getenv(env_var)
        if value:
            candidates.append(Path(value).expanduser())
    project_root = Path(__file__).resolve().parents[2]
    env_dir = project_root / "env"
    candidates.extend([
        project_root / f".env.{prefix}",
        env_dir / f"{prefix}.env",
        env_dir / f"{prefix}.local.env",
        env_dir / f"{prefix}.example.env",
        project_root / ".env",
    ])
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


@lru_cache(maxsize=1)
def load_workday_settings(env_file: Optional[str] = None) -> WorkdaySettings:
    resolved = _resolve_env_file(env_file, "workday")
    return WorkdaySettings(_env_file=resolved)  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def load_servicenow_settings(env_file: Optional[str] = None) -> ServiceNowSettings:
    resolved = _resolve_env_file(env_file, "servicenow")
    return ServiceNowSettings(_env_file=resolved)  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def load_salesforce_settings(env_file: Optional[str] = None) -> SalesforceSettings:
    resolved = _resolve_env_file(env_file, "salesforce")
    return SalesforceSettings(_env_file=resolved)  # type: ignore[call-arg]


@lru_cache(maxsize=1)
def load_jira_settings(env_file: Optional[str] = None) -> JiraSettings:
    resolved = _resolve_env_file(env_file, "jira")
    return JiraSettings(_env_file=resolved)  # type: ignore[call-arg]


def reset_settings_cache() -> None:
    load_workday_settings.cache_clear()
    load_servicenow_settings.cache_clear()
    load_salesforce_settings.cache_clear()
    load_jira_settings.cache_clear()
