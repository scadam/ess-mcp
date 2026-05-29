"""Agent 365/OpenTelemetry tracing helpers."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator
from urllib.parse import urlencode, urlparse

import httpx

from .identity import AgentIdentityContext, RunPrincipal

logger = logging.getLogger("ess-mcp.demo_agent.observability")


_OTEL_CONFIGURED = False
_A365_CONFIGURED = False
_A365_STATUS: dict[str, object] = {
    "sdkInstalled": False,
    "sdkConfigured": False,
    "exporterEnabled": False,
    "tokenSource": "not configured",
    "tokenScope": "",
    "endpoint": "https://agent365.svc.cloud.microsoft",
    "lastError": "",
}

A365_OBSERVABILITY_RESOURCE_APP_ID = "9b975845-388f-4429-889e-eab1ef63949c"
A365_OBSERVABILITY_SCOPE = f"api://{A365_OBSERVABILITY_RESOURCE_APP_ID}/Agent365.Observability.OtelWrite"
A365_OBSERVABILITY_APP_SCOPE = f"api://{A365_OBSERVABILITY_RESOURCE_APP_ID}/.default"


def _otel_attributes(attributes: dict[str, object]) -> dict[str, str | bool | int | float]:
    return {
        key: value
        for key, value in attributes.items()
        if isinstance(value, (str, bool, int, float))
    }


def _a365_extra_attributes(attributes: dict[str, object]) -> dict[str, str | bool | int | float]:
    reserved = {
        "gen_ai.operation.name",
        "gen_ai.agent.id",
        "gen_ai.agent.name",
        "gen_ai.tool.name",
        "gen_ai.tool.call.id",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
        "gen_ai.tool.type",
        "microsoft.tenant.id",
    }
    return {key: value for key, value in _otel_attributes(attributes).items() if key not in reserved}


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _payload_enabled() -> bool:
    return os.getenv("ESS_OBSERVE_TOOL_PAYLOADS", "true").lower() not in {"0", "false", "no", "off"}


def _payload_limit() -> int:
    raw = os.getenv("ESS_OBSERVE_TOOL_PAYLOAD_MAX_CHARS", "0")
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _observed_payload(value: str) -> str:
    if not _payload_enabled():
        return ""
    limit = _payload_limit()
    if limit and len(value) > limit:
        return value[:limit] + "...(telemetry payload truncated by ESS_OBSERVE_TOOL_PAYLOAD_MAX_CHARS)"
    return value


def _configure_otel_if_requested() -> None:
    """Configure an OTLP exporter when env vars are present.

    Agent 365/Purview/Defender ingestion is tenant-controlled. The app emits
    OpenTelemetry with Agent ID attributes; the hosting environment decides where
    OTLP is sent by setting OTEL_EXPORTER_OTLP_ENDPOINT and related variables.
    """
    global _OTEL_CONFIGURED
    if _OTEL_CONFIGURED:
        return
    _OTEL_CONFIGURED = True
    if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    try:
        from opentelemetry import trace  # type: ignore
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter  # type: ignore
        from opentelemetry.sdk.resources import Resource  # type: ignore
        from opentelemetry.sdk.trace import TracerProvider  # type: ignore
        from opentelemetry.sdk.trace.export import BatchSpanProcessor  # type: ignore
    except Exception as exc:
        logger.warning("OTLP exporter requested but unavailable: %s", exc)
        return

    resource = Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "ess-demo-agent")})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


def _a365_token_scope() -> str:
    token_source = os.getenv("A365_OBSERVABILITY_TOKEN_SOURCE", "agent_identity_sidecar").strip().lower()
    if token_source in {"agent_identity_sidecar", "managed_identity"}:
        default_scope = A365_OBSERVABILITY_APP_SCOPE
    else:
        default_scope = A365_OBSERVABILITY_SCOPE
    return os.getenv(
        "A365_OBSERVABILITY_TOKEN_SCOPE",
        default_scope,
    )


def _a365_base_endpoint() -> str:
    override = os.getenv("A365_OBSERVABILITY_DOMAIN_OVERRIDE", "").strip()
    if not override:
        return "https://agent365.svc.cloud.microsoft"
    parsed = urlparse(override)
    if parsed.scheme:
        return override.rstrip("/")
    return f"https://{override.rstrip('/')}"


def _a365_agent_id(context: AgentIdentityContext) -> str:
    """The id Agent 365 expects in `gen_ai.agent.id` and the OTLP URL path.

    Per the Agent 365 SDK guide this is the **Entra agent identity app id**
    (client id), NOT the service principal object id. We fall back to the
    object id only when the client id env var is unset, to keep older deploys
    working.
    """
    return context.agent_identity_client_id or context.agent_identity_id


def _agent365_export_url(context: AgentIdentityContext) -> str:
    path_prefix = "observabilityService" if _safe_bool_env("A365_OBSERVABILITY_USE_S2S_ENDPOINT") else "observability"
    return (
        f"{_a365_base_endpoint()}/{path_prefix}/tenants/{context.tenant_id}"
        f"/otlp/agents/{_a365_agent_id(context)}/traces?api-version=1"
    )


def _safe_bool_env(name: str, default: str = "") -> bool:
    return os.getenv(name, default).lower() in {"true", "1", "yes", "on"}


_SIDECAR_TOKEN_LOCK = threading.Lock()
_SIDECAR_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


def _sidecar_token_resolver(context: AgentIdentityContext) -> tuple[Callable[[str, str], str | None], str]:
    """Acquire Agent-Identity-scoped tokens via the official Entra auth-sidecar.

    Reference: https://github.com/vj926/AgentID_using_EntraSDK and
    https://github.com/vj926/deploy-agent-id-app-service. The sidecar lives in
    the same pod and exposes
    GET {SIDECAR_URL}/AuthorizationHeaderUnauthenticated/{api}
        ?AgentIdentity={agentAppId}
        &optionsOverride.AcquireTokenOptions.ForceRefresh=true
        &optionsOverride.AcquireTokenOptions.CorrelationId={uuid}
    returning {"authorizationHeader": "Bearer <jwt>", "expiresOn": "..."}.
    The downstream API name (`a365` here) is configured on the sidecar via
    DownstreamApis__a365__BaseUrl / Scopes / RequestAppToken=true.
    """
    sidecar_url = os.getenv("A365_SIDECAR_URL", "http://localhost:5000").rstrip("/")
    downstream_api = os.getenv("A365_SIDECAR_DOWNSTREAM_API", "a365").strip() or "a365"
    timeout = float(os.getenv("A365_SIDECAR_TIMEOUT", "15"))
    agent_app_id = (
        os.getenv("A365_AGENT_APP_ID", "").strip()
        or context.agent_identity_client_id
        or context.agent_identity_id
    )
    if not agent_app_id:
        raise RuntimeError(
            "agent_identity_sidecar token source needs A365_AGENT_APP_ID or "
            "ENTRA_AGENT_IDENTITY_CLIENT_ID set."
        )

    endpoint = f"{sidecar_url}/AuthorizationHeaderUnauthenticated/{downstream_api}"
    source_name = f"Entra auth-sidecar ({sidecar_url}/{downstream_api}, AgentIdentity={agent_app_id})"

    def _fetch_fresh(correlation_id: str) -> tuple[str, float]:
        params = {
            "AgentIdentity": agent_app_id,
            "optionsOverride.AcquireTokenOptions.ForceRefresh": "true",
            "optionsOverride.AcquireTokenOptions.CorrelationId": correlation_id,
        }
        url = f"{endpoint}?{urlencode(params)}"
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"sidecar {endpoint} returned HTTP {resp.status_code}: {resp.text[:300]}"
                )
            data = resp.json() or {}
        header = (
            data.get("authorizationHeader")
            or data.get("AuthorizationHeader")
            or ""
        )
        if not header.lower().startswith("bearer "):
            raise RuntimeError(f"sidecar response missing Bearer authorizationHeader: {data}")
        token = header.split(" ", 1)[1].strip()
        # Cache for ~50 minutes by default; honor expiresOn when present.
        ttl = 50 * 60
        expires_on = data.get("expiresOn") or data.get("ExpiresOn")
        if isinstance(expires_on, (int, float)):
            ttl = max(60, int(expires_on) - int(time.time()) - 60)
        elif isinstance(expires_on, str):
            try:
                from datetime import datetime
                # ISO-8601 with optional Z
                normalized = expires_on.replace("Z", "+00:00")
                exp_ts = datetime.fromisoformat(normalized).timestamp()
                ttl = max(60, int(exp_ts) - int(time.time()) - 60)
            except Exception:
                pass
        return token, time.time() + ttl

    def resolve_token(agent_id: str, tenant_id: str) -> str | None:
        cache_key = f"{agent_app_id}|{downstream_api}"
        try:
            with _SIDECAR_TOKEN_LOCK:
                cached = _SIDECAR_TOKEN_CACHE.get(cache_key)
                if cached and cached[1] > time.time():
                    return cached[0]
            correlation_id = str(uuid.uuid4())
            token, expires_at = _fetch_fresh(correlation_id)
            with _SIDECAR_TOKEN_LOCK:
                _SIDECAR_TOKEN_CACHE[cache_key] = (token, expires_at)
            logger.info(
                "Agent 365 token acquired via sidecar correlation=%s expiresInSec=%d",
                correlation_id,
                int(expires_at - time.time()),
            )
            return token
        except Exception as exc:
            _A365_STATUS["lastError"] = (
                f"Agent 365 sidecar token acquisition failed for {agent_id}/{tenant_id}: {exc}"
            )
            logger.error("Agent 365 sidecar token acquisition failed: %s", exc)
            return None

    return resolve_token, source_name


def _managed_identity_token_resolver(context: AgentIdentityContext) -> tuple[Callable[[str, str], str | None], str]:
    from azure.identity import (  # type: ignore
        ClientAssertionCredential,
        DefaultAzureCredential,
        ManagedIdentityCredential,
    )

    managed_identity_client_id = os.getenv("A365_OBSERVABILITY_MANAGED_IDENTITY_CLIENT_ID", "").strip()
    token_source = os.getenv("A365_OBSERVABILITY_TOKEN_SOURCE", "managed_identity").strip().lower()
    scope = _a365_token_scope()
    if token_source in {"blueprint", "blueprint_assertion", "agent_blueprint"}:
        assertion_credential = ManagedIdentityCredential(client_id=managed_identity_client_id or None)

        def assertion() -> str:
            return assertion_credential.get_token("api://AzureADTokenExchange/.default").token

        credential = ClientAssertionCredential(context.tenant_id, context.blueprint_client_id, assertion)
        source_name = "Agent Blueprint via managed identity federation"
    else:
        credential = DefaultAzureCredential(
            exclude_interactive_browser_credential=True,
            managed_identity_client_id=managed_identity_client_id or None,
        )
        source_name = "DefaultAzureCredential"

    def resolve_token(agent_id: str, tenant_id: str) -> str | None:
        try:
            return credential.get_token(scope).token
        except Exception as exc:
            _A365_STATUS["lastError"] = f"Agent 365 token acquisition failed for {agent_id}/{tenant_id}: {exc}"
            logger.error("Agent 365 token acquisition failed: %s", exc)
            return None

    return resolve_token, source_name


def _configure_a365_if_requested(context: AgentIdentityContext) -> None:
    """Configure the Agent 365 observability SDK when available.

    The SDK exporter is enabled by setting ENABLE_A365_OBSERVABILITY_EXPORTER=true.
    Without that flag, the SDK still creates correctly shaped spans but falls back
    to console export, which is useful for local validation.
    """
    global _A365_CONFIGURED
    if _A365_CONFIGURED:
        return
    _A365_CONFIGURED = True

    os.environ.setdefault("ENABLE_OBSERVABILITY", "true")
    os.environ.setdefault("ENABLE_A365_OBSERVABILITY", "true")
    os.environ.setdefault("ENABLE_A365_OBSERVABILITY_EXPORTER", "true")
    os.environ.setdefault("A365_OBSERVABILITY_TOKEN_SOURCE", "agent_identity_sidecar")
    os.environ.setdefault("A365_OBSERVABILITY_USE_S2S_ENDPOINT", "true")

    _A365_STATUS["exporterEnabled"] = _safe_bool_env("ENABLE_A365_OBSERVABILITY_EXPORTER")
    _A365_STATUS["tokenScope"] = _a365_token_scope()
    _A365_STATUS["endpoint"] = _agent365_export_url(context) if context.enabled else _a365_base_endpoint()

    try:
        from microsoft_agents_a365.observability.core import (  # type: ignore
            Agent365ExporterOptions,
            configure,
            is_configured,
        )
    except Exception as exc:
        _A365_STATUS["lastError"] = f"Agent 365 observability SDK unavailable: {exc}"
        logger.warning(_A365_STATUS["lastError"])
        return

    _A365_STATUS["sdkInstalled"] = True

    token_resolver: Any = None
    if _safe_bool_env("ENABLE_A365_OBSERVABILITY_EXPORTER"):
        configured_source = os.getenv("A365_OBSERVABILITY_TOKEN_SOURCE", "agent_identity_sidecar").strip().lower()
        try:
            if configured_source == "agent_identity_sidecar":
                token_resolver, token_source = _sidecar_token_resolver(context)
            else:
                token_resolver, token_source = _managed_identity_token_resolver(context)
            _A365_STATUS["tokenSource"] = token_source
        except Exception as exc:
            _A365_STATUS["lastError"] = f"Agent 365 token resolver init failed: {exc}"
            logger.error(_A365_STATUS["lastError"])
            _A365_STATUS["tokenSource"] = f"failed: {exc}"
            return
    else:
        _A365_STATUS["tokenSource"] = "disabled; set ENABLE_A365_OBSERVABILITY_EXPORTER=true"

    try:
        configured = configure(
            service_name=os.getenv("OTEL_SERVICE_NAME", "ess-demo-agent"),
            service_namespace=os.getenv("A365_OBSERVABILITY_SERVICE_NAMESPACE", "ess-mcp"),
            logger_name="ess-mcp.demo_agent.observability",
            exporter_options=Agent365ExporterOptions(
                cluster_category=os.getenv("A365_OBSERVABILITY_CLUSTER_CATEGORY", "prod"),
                token_resolver=token_resolver,
                use_s2s_endpoint=_safe_bool_env("A365_OBSERVABILITY_USE_S2S_ENDPOINT"),
            ),
            suppress_invoke_agent_input=not _safe_bool_env("A365_CAPTURE_PROMPTS", "true")
            if os.getenv("A365_CAPTURE_PROMPTS") is not None
            else _safe_bool_env("A365_SUPPRESS_INVOKE_AGENT_INPUT", "false"),
        )
    except Exception as exc:
        _A365_STATUS["lastError"] = f"Agent 365 observability SDK configure failed: {exc}"
        logger.error(_A365_STATUS["lastError"])
        return

    _A365_STATUS["sdkConfigured"] = bool(configured and is_configured())
    if _A365_STATUS["sdkConfigured"]:
        logger.info(
            "Agent 365 observability configured; exporter=%s endpoint=%s",
            _A365_STATUS["exporterEnabled"],
            _A365_STATUS["endpoint"],
        )


def observability_status(context: AgentIdentityContext | None = None) -> dict[str, object]:
    ctx = context or AgentIdentityContext.from_env()
    status = dict(_A365_STATUS)
    status.update(
        {
            "otlpEndpointConfigured": bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")),
            "otlpEndpoint": os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
            "serviceName": os.getenv("OTEL_SERVICE_NAME", "ess-demo-agent"),
            "payloadsEnabled": _payload_enabled(),
            "payloadMaxChars": os.getenv("ESS_OBSERVE_TOOL_PAYLOAD_MAX_CHARS", "0"),
            "agentId": ctx.agent_identity_client_id or ctx.agent_identity_id,
            "tenantId": ctx.tenant_id,
            "events": [
                "execute_tool",
                "agent.tool_call.observed",
                "agent.web_run",
                "agent.llm",
                "agent.tool",
                "agent.invoke_agent",
                "agent.inference",
            ],
            "purview": _purview_status(),
        }
    )
    return status


def _purview_status() -> dict[str, object]:
    try:
        from .purview import _DEFAULT_POLICY_PATH, is_purview_enabled  # type: ignore
    except Exception as exc:
        return {"enabled": False, "configured": False, "error": str(exc)}
    return {
        "enabled": is_purview_enabled(),
        "configured": _DEFAULT_POLICY_PATH.exists(),
        "policyPath": str(_DEFAULT_POLICY_PATH),
        "graphTokenSource": os.getenv("PURVIEW_GRAPH_TOKEN_SOURCE", "managed_identity"),
    }


def _build_purview(context: AgentIdentityContext) -> dict[str, object] | None:
    """Instantiate the Purview client + policy; returns None when disabled."""
    try:
        from .purview import LabelPolicy, PurviewLabelClient, is_purview_enabled, load_default_policy
    except Exception as exc:
        logger.warning("Purview module unavailable: %s", exc)
        return None
    if not is_purview_enabled():
        return None

    token_provider = None
    source = os.getenv("PURVIEW_GRAPH_TOKEN_SOURCE", "managed_identity").strip().lower()
    if source == "managed_identity":
        try:
            from azure.identity import ManagedIdentityCredential  # type: ignore

            cred = ManagedIdentityCredential(
                client_id=os.getenv("AZURE_CLIENT_ID") or None,
            )

            def _provider() -> str:
                tok = cred.get_token("https://graph.microsoft.com/.default")
                return tok.token

            token_provider = _provider
        except Exception as exc:
            logger.info("Purview Graph MI token disabled: %s", exc)
    # source == "none" or anything else → fall back to heuristic-only

    policy: LabelPolicy = load_default_policy()
    client = PurviewLabelClient(graph_token_provider=token_provider, enabled=True)
    return {"client": client, "policy": policy, "context": context}


@dataclass(frozen=True)
class ObservedToolCall:
    call_id: str
    server: str
    tool: str
    arguments: object
    result: object
    duration_ms: int
    success: bool
    error: str = ""
    policy_attributes: dict[str, object] = field(default_factory=dict)
    policy_action: str = ""


class AgentTelemetry:
    """Small wrapper that emits useful spans when OpenTelemetry is installed."""

    def __init__(self, context: AgentIdentityContext | None = None) -> None:
        self.context = context or AgentIdentityContext.from_env()
        _configure_otel_if_requested()
        _configure_a365_if_requested(self.context)
        self._purview = _build_purview(self.context)
        try:
            from opentelemetry import trace  # type: ignore
        except Exception:
            self._tracer = None
        else:
            self._tracer = trace.get_tracer("ess-mcp.demo_agent")

        try:
            from microsoft_agents_a365.observability.core import (  # type: ignore
                AgentDetails,
                CallerDetails,
                Channel,
                ExecuteToolScope,
                InferenceCallDetails,
                InferenceOperationType,
                InferenceScope,
                InvokeAgentScope,
                InvokeAgentScopeDetails,
                Request,
                ToolCallDetails,
                ToolType,
                UserDetails,
            )
        except Exception:
            self._a365 = None
        else:
            self._a365 = {
                "AgentDetails": AgentDetails,
                "CallerDetails": CallerDetails,
                "Channel": Channel,
                "ExecuteToolScope": ExecuteToolScope,
                "InferenceCallDetails": InferenceCallDetails,
                "InferenceOperationType": InferenceOperationType,
                "InferenceScope": InferenceScope,
                "InvokeAgentScope": InvokeAgentScope,
                "InvokeAgentScopeDetails": InvokeAgentScopeDetails,
                "Request": Request,
                "ToolCallDetails": ToolCallDetails,
                "ToolType": ToolType,
                "UserDetails": UserDetails,
            }

    @property
    def purview_client(self):
        return (self._purview or {}).get("client") if self._purview else None

    @property
    def purview_policy(self):
        return (self._purview or {}).get("policy") if self._purview else None

    def force_flush(self, timeout_millis: int = 10000) -> None:
        """Flush any buffered spans. Call from request/run finally blocks.

        The Agent 365 SDK guide flags this as required for short-lived /
        serverless handlers — without it the BatchSpanProcessor may drop the
        last batch on request teardown, which manifests as missing spans in
        the control panel.
        """
        try:
            from opentelemetry import trace  # type: ignore

            provider = trace.get_tracer_provider()
            flush = getattr(provider, "force_flush", None)
            if callable(flush):
                flush(timeout_millis)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("force_flush failed: %s", exc)

    def _a365_agent_details(
        self,
        *,
        agent_id_override: str | None = None,
        agent_name_override: str | None = None,
        agentic_user_id_override: str | None = None,
    ) -> object | None:
        if not self._a365:
            return None
        AgentDetails = self._a365["AgentDetails"]
        # Per-instance teammates (HR/IT/PO) must report under their own
        # Entra Agent Identity client id so Purview Activity Explorer
        # breaks the rows out by AI teammate instead of collapsing them
        # under the parent hosted agent.
        default_agent_id = _a365_agent_id(self.context)
        a365_agent_id = (agent_id_override or "").strip() or default_agent_id
        a365_agent_name = (agent_name_override or "").strip() or self.context.display_name
        a365_agentic_user_id = (agentic_user_id_override or "").strip() or a365_agent_id
        return AgentDetails(
            agent_id=a365_agent_id,
            agent_name=a365_agent_name,
            agentic_user_id=a365_agentic_user_id,
            agent_blueprint_id=self.context.blueprint_client_id,
            agent_platform_id=self.context.foundry_agent_id,
            tenant_id=self.context.tenant_id,
            provider_name="Azure OpenAI" if os.getenv("AZURE_OPENAI_ENDPOINT") else "GitHub Models",
            agent_version=os.getenv("ESS_AGENT_VERSION", "demo"),
        )

    def _a365_user_details(self, principal: RunPrincipal | None) -> object | None:
        if not self._a365 or principal is None or principal.is_anonymous:
            return None
        UserDetails = self._a365["UserDetails"]
        # Purview's "User participant" column reads `user_id`. For Microsoft
        # 365 attribution the UPN is far more useful than the AAD object id,
        # so prefer UPN when available.
        return UserDetails(
            user_id=principal.upn or principal.aad_object_id or "",
            user_email=principal.upn or "",
            user_name=principal.display_name or principal.upn or "",
            user_client_ip=principal.client_ip or "",
        )

    def _a365_caller_details(self, principal: RunPrincipal | None) -> object | None:
        if not self._a365 or principal is None:
            return None
        CallerDetails = self._a365["CallerDetails"]
        user = self._a365_user_details(principal)
        if user is None:
            return None
        return CallerDetails(user_details=user, caller_agent_details=None)

    # Purview / DSPM-for-AI "App accessed in" column only renders for a
    # known set of M365 channel ids. Map our internal source labels onto
    # those well-known values so the column lights up consistently.
    _CHANNEL_NAME_MAP = {
        "teams-chat": "microsoftteams",
        "msteams": "microsoftteams",
        "teams": "microsoftteams",
        "control-plane": "agent365-control-plane",
        "instance-launch": "agent365-control-plane",
        "chat": "agent365-control-plane",
        "web": "agent365-control-plane",
        "copilot": "microsoftcopilot",
    }

    def _a365_channel(self, principal: RunPrincipal | None) -> object | None:
        if not self._a365 or principal is None:
            return None
        Channel = self._a365["Channel"]
        raw = (principal.channel_id or principal.source or "control-plane").strip().lower()
        normalized = self._CHANNEL_NAME_MAP.get(raw, raw)
        return Channel(name=normalized, link=None)

    @contextmanager
    def start_invoke_scope(
        self,
        *,
        run_id: str,
        conversation_id: str,
        principal: RunPrincipal | None,
        prompt: str = "",
        agent_identity_client_id: str | None = None,
        agent_display_name: str | None = None,
        agentic_user_id: str | None = None,
    ) -> Iterator[object | None]:
        """Open an Agent 365 InvokeAgentScope around a full run.

        Yields the scope (or None when the SDK is unavailable) so callers may
        attach `record_output_messages` / `record_attributes` later.

        Per-instance teammate overrides (``agent_identity_client_id``,
        ``agent_display_name``) let an agentic-instance run be attributed to
        the HR / IT / PO teammate instead of the parent hosted agent in
        Purview Activity Explorer.
        """
        if not self._a365:
            yield None
            return
        agent_details = self._a365_agent_details(
            agent_id_override=agent_identity_client_id,
            agent_name_override=agent_display_name,
            agentic_user_id_override=agentic_user_id,
        )
        if agent_details is None:
            yield None
            return
        InvokeAgentScope = self._a365["InvokeAgentScope"]
        InvokeAgentScopeDetails = self._a365["InvokeAgentScopeDetails"]
        Request = self._a365["Request"]
        capture_prompts = _safe_bool_env("A365_CAPTURE_PROMPTS", "true")
        request = Request(
            content=prompt if (prompt and capture_prompts) else None,
            session_id=run_id,
            conversation_id=conversation_id or run_id,
            channel=self._a365_channel(principal),
        )
        try:
            with InvokeAgentScope.start(
                request=request,
                scope_details=InvokeAgentScopeDetails(),
                agent_details=agent_details,
                caller_details=self._a365_caller_details(principal),
            ) as scope:
                yield scope
        except Exception as exc:
            _A365_STATUS["lastError"] = f"Agent 365 invoke scope failed: {exc}"
            logger.warning("Agent 365 invoke scope failed: %s", exc)
            yield None

    @contextmanager
    def start_inference_scope(
        self,
        *,
        run_id: str,
        conversation_id: str,
        model: str,
        provider: str,
        principal: RunPrincipal | None,
        input_messages: list[str] | None = None,
        agent_identity_client_id: str | None = None,
        agent_display_name: str | None = None,
        agentic_user_id: str | None = None,
    ) -> Iterator[object | None]:
        """Open an InferenceScope around one LLM call (chat completion)."""
        if not self._a365:
            yield None
            return
        agent_details = self._a365_agent_details(
            agent_id_override=agent_identity_client_id,
            agent_name_override=agent_display_name,
            agentic_user_id_override=agentic_user_id,
        )
        if agent_details is None:
            yield None
            return
        InferenceScope = self._a365["InferenceScope"]
        InferenceCallDetails = self._a365["InferenceCallDetails"]
        InferenceOperationType = self._a365["InferenceOperationType"]
        Request = self._a365["Request"]
        capture_prompts = _safe_bool_env("A365_CAPTURE_PROMPTS", "true")
        request = Request(
            content=input_messages if (input_messages and capture_prompts) else None,
            session_id=run_id,
            conversation_id=conversation_id or run_id,
            channel=self._a365_channel(principal),
        )
        details = InferenceCallDetails(
            operationName=InferenceOperationType.CHAT,
            model=model,
            providerName=provider,
        )
        try:
            with InferenceScope.start(
                request=request,
                details=details,
                agent_details=agent_details,
                user_details=self._a365_user_details(principal),
            ) as scope:
                yield scope
        except Exception as exc:
            _A365_STATUS["lastError"] = f"Agent 365 inference scope failed: {exc}"
            logger.warning("Agent 365 inference scope failed: %s", exc)
            yield None

    @contextmanager
    def span(self, name: str, **attributes: object) -> Iterator[None]:
        if self._tracer is None:
            yield
            return
        merged = {
            "gen_ai.agent.name": self.context.display_name,
            "microsoft.agent365.blueprint.client_id": self.context.blueprint_client_id,
            "microsoft.agent365.agent_identity.id": self.context.agent_identity_id,
            "microsoft.agent365.foundry.agent_id": self.context.foundry_agent_id,
            **_otel_attributes(attributes),
        }
        with self._tracer.start_as_current_span(name) as span:
            for key, value in merged.items():
                if value:
                    span.set_attribute(key, value)
            yield

    def event(self, name: str, **attributes: object) -> None:
        if self._tracer is None:
            return
        from opentelemetry import trace  # type: ignore

        span = trace.get_current_span()
        if span and span.is_recording():
            span.add_event(name, _otel_attributes(attributes))

    def tool_call_event(self, call: ObservedToolCall) -> dict[str, object]:
        arguments_json = _json_dumps(call.arguments)
        result_json = _json_dumps(call.result)
        attributes: dict[str, object] = {
            "gen_ai.operation.name": "tool_call",
            "gen_ai.tool.name": call.tool,
            "gen_ai.tool.call.id": call.call_id,
            "mcp.server.name": call.server,
            "mcp.tool.name": call.tool,
            "mcp.tool.call.success": call.success,
            "mcp.tool.call.duration_ms": call.duration_ms,
            "mcp.tool.arguments.sha256": _sha256(arguments_json),
            "mcp.tool.arguments.size": len(arguments_json),
            "mcp.tool.response.sha256": _sha256(result_json),
            "mcp.tool.response.size": len(result_json),
            "microsoft.agent365.blueprint.client_id": self.context.blueprint_client_id,
            "microsoft.agent365.agent_identity.id": self.context.agent_identity_id,
            "microsoft.agent365.foundry.agent_id": self.context.foundry_agent_id,
        }
        if call.error:
            attributes["mcp.tool.error"] = call.error
        if call.policy_attributes:
            attributes.update(call.policy_attributes)
        if _payload_enabled():
            attributes["mcp.tool.arguments"] = _observed_payload(arguments_json)
            attributes["mcp.tool.response"] = _observed_payload(result_json)

        return {
            "event": "agent.tool_call.observed",
            **attributes,
        }

    def apply_purview_policy(self, *, content: str, hint: str | None = None):
        """Classify `content` and run it through the bundled Purview policy.

        Returns a `purview.PolicyDecision` (or None when Purview is disabled).
        Callers should swap their tool-result text with `decision.content` and
        forward `decision.telemetry_attributes()` into ObservedToolCall so the
        sensitivity label and policy action propagate to OTel + Agent 365.
        """
        if not self._purview:
            return None
        client = self._purview["client"]
        policy = self._purview["policy"]
        try:
            label = client.classify(content or "", hint=hint)  # type: ignore[union-attr]
            return policy.evaluate(content=content or "", label=label)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("Purview policy evaluation failed: %s", exc)
            return None

    def observe_tool_call(self, call: ObservedToolCall) -> dict[str, object]:
        log_record = self.tool_call_event(call)
        log_line = _json_dumps(log_record)
        logger.info(log_line)
        print(_json_dumps({
            "event": "agent.tool_call.observed",
            "gen_ai.tool.name": log_record.get("gen_ai.tool.name"),
            "gen_ai.tool.call.id": log_record.get("gen_ai.tool.call.id"),
            "mcp.server.name": log_record.get("mcp.server.name"),
            "mcp.tool.name": log_record.get("mcp.tool.name"),
            "mcp.tool.call.success": log_record.get("mcp.tool.call.success"),
            "mcp.tool.call.duration_ms": log_record.get("mcp.tool.call.duration_ms"),
            "microsoft.agent365.blueprint.client_id": log_record.get("microsoft.agent365.blueprint.client_id"),
            "microsoft.agent365.agent_identity.id": log_record.get("microsoft.agent365.agent_identity.id"),
        }), flush=True)

        agent_details = self._a365_agent_details()
        if agent_details and self._a365:
            try:
                ExecuteToolScope = self._a365["ExecuteToolScope"]
                Request = self._a365["Request"]
                ToolCallDetails = self._a365["ToolCallDetails"]
                ToolType = self._a365["ToolType"]
                with ExecuteToolScope.start(
                    request=Request(session_id=call.call_id, conversation_id=call.call_id),
                    details=ToolCallDetails(
                        tool_name=f"{call.server}.{call.tool}",
                        arguments=call.arguments,
                        tool_call_id=call.call_id,
                        description=f"MCP tool call to {call.server}/{call.tool}",
                        tool_type=ToolType.EXTENSION.value,
                    ),
                    agent_details=agent_details,
                ) as scope:
                    scope.record_attributes(_a365_extra_attributes(log_record))
                    if call.error:
                        scope.record_error(RuntimeError(call.error))
                    else:
                        scope.record_response(_observed_payload(_json_dumps(call.result)))
            except Exception as exc:
                _A365_STATUS["lastError"] = f"Agent 365 tool scope failed: {exc}"
                logger.warning("Agent 365 tool scope failed: %s", exc)

        if self._tracer is None:
            return log_record
        with self._tracer.start_as_current_span("agent.tool_call.observed") as span:
            for key, value in _otel_attributes(log_record).items():
                if value not in (None, ""):
                    span.set_attribute(key, value)
            if _payload_enabled():
                span.add_event("mcp.tool.arguments", {"payload": str(log_record.get("mcp.tool.arguments", ""))})
                span.add_event("mcp.tool.response", {"payload": str(log_record.get("mcp.tool.response", ""))})
        return log_record


def now_ms() -> int:
    return int(time.perf_counter() * 1000)