"""Web UI for the hosted ESS-MCP autonomous agent.

Streams tool-call progress to the browser via Server-Sent Events (SSE).
Supports **Azure OpenAI** (managed identity) or **GitHub Models** (PAT).
Run with:  python -m demo_agent.web
"""

from __future__ import annotations

import asyncio
import json
import contextvars
import html as html_module
import logging
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from aiohttp import web

logging.basicConfig(level=os.getenv("ESS_LOG_LEVEL", "INFO"), format="%(message)s", force=True)
logging.getLogger("ess-mcp.demo_agent.observability").setLevel(logging.INFO)
_logger = logging.getLogger("ess-mcp.demo_agent.web")

# Suppress noisy background SSE tracebacks from fastmcp/mcp internals.
# These are keep-alive connection failures (logger.exception at ERROR level),
# not user-facing errors.  Set to CRITICAL to hide them entirely.
for _noisy in ("mcp.client.streamable_http", "httpcore", "httpx"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)
from dotenv import load_dotenv
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from openai import AsyncAzureOpenAI, AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

from .agent import mcp_url_for
from . import a365_value
from .identity import AgentIdentityContext, RunPrincipal, agent_headers
from .observability import AgentTelemetry, ObservedToolCall, now_ms, observability_status
from .oauth import EnvOrOAuthTokenProvider, ServerTokenProvider
from .instances import build_default_directory, AgenticInstance
from .teams_refs import ConversationReferenceStore, conversation_reference_from_dict, conversation_reference_to_dict
from .work_iq_client import WorkIqTeamsClient
from .hitl import HitlCoordinator
from .graph_chat import GraphChatClient
from .governance import governance_state

try:
    from microsoft_agents.activity import (
        Activity,
        ActivityTypes,
        load_configuration_from_env,
    )
    from microsoft_agents.authentication.msal import MsalConnectionManager
    from microsoft_agents.hosting.aiohttp import (
        CloudAdapter,
        jwt_authorization_middleware,
        start_agent_process,
    )
    from microsoft_agents.hosting.core import (
        AgentApplication,
        AgentAuthConfiguration,
        Authorization,
        MemoryStorage,
        TurnContext,
        TurnState,
    )
    _AGENTS_SDK_AVAILABLE = True
except Exception as _agents_sdk_import_exc:  # pragma: no cover - import-time fallback
    AgentApplication = None  # type: ignore[assignment]
    AgentAuthConfiguration = None  # type: ignore[assignment]
    Authorization = None  # type: ignore[assignment]
    Activity = None  # type: ignore[assignment]
    ActivityTypes = None  # type: ignore[assignment]
    CloudAdapter = None  # type: ignore[assignment]
    MemoryStorage = None  # type: ignore[assignment]
    MsalConnectionManager = None  # type: ignore[assignment]
    TurnContext = None  # type: ignore[assignment]
    TurnState = None  # type: ignore[assignment]
    jwt_authorization_middleware = None  # type: ignore[assignment]
    load_configuration_from_env = None  # type: ignore[assignment]
    start_agent_process = None  # type: ignore[assignment]
    _AGENTS_SDK_AVAILABLE = False
    _AGENTS_SDK_IMPORT_ERROR = _agents_sdk_import_exc

STATIC_DIR = Path(__file__).parent / "static"
SKILLS_DIR = Path(__file__).parent / "skills"
SERVER_NAMES = ("workday", "servicenow", "coupa")

# Token budget constants (GitHub Models free-tier limit)
# Only enforced when using GitHub Models; Azure OpenAI has 128K context.
MAX_REQUEST_TOKENS = 8000
COMPLETION_RESERVE = 600

# ── LLM backend ────────────────────────────────────────────────────

GITHUB_MODELS_URL = "https://models.inference.ai.azure.com"

# Resolved once at startup
_use_azure_openai = False


def _create_llm_client() -> AsyncOpenAI:
    """Create an OpenAI-compatible client.

    Priority:
      1. AZURE_OPENAI_ENDPOINT → Azure OpenAI with DefaultAzureCredential
      2. GITHUB_TOKEN          → GitHub Models (8 000-token cap)
    """
    global _use_azure_openai

    azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
    if azure_endpoint:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider

        credential = DefaultAzureCredential(exclude_interactive_browser_credential=True)
        token_provider = get_bearer_token_provider(
            credential, "https://cognitiveservices.azure.com/.default"
        )
        _use_azure_openai = True
        print(f"  🔑 Using Azure OpenAI at {azure_endpoint} (managed identity)")
        return AsyncAzureOpenAI(
            azure_endpoint=azure_endpoint,
            azure_ad_token_provider=token_provider,
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2025-03-01-preview"),
            max_retries=3,
        )

    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        sys.exit(
            "Either AZURE_OPENAI_ENDPOINT or GITHUB_TOKEN is required.\n"
            "  • Azure OpenAI: set AZURE_OPENAI_ENDPOINT (uses managed identity)\n"
            "  • GitHub Models: set GITHUB_TOKEN (8 000-token limit)\n"
        )
    print("  🔑 Using GitHub Models (8 000-token cap)")
    return AsyncOpenAI(base_url=GITHUB_MODELS_URL, api_key=token)


# ── MCP connections (module-level, populated on startup) ───────────

_servers: dict[str, Client] = {}
_server_configs: dict[str, str] = {}  # name -> URL for reconnect
_all_tools: list[ChatCompletionToolParam] = []
_runtime_context = AgentIdentityContext.from_env()
_token_provider: ServerTokenProvider = EnvOrOAuthTokenProvider()
_telemetry = AgentTelemetry(_runtime_context)
_agent_app: Any | None = None
_cloud_adapter: Any | None = None
_connection_manager: Any | None = None
_auth_handler_name: str | None = None
_agents_sdk_config: dict[str, Any] | None = None
_run_ledger: dict[str, dict[str, Any]] = {}
_run_order: list[str] = []
# Run + instance context propagated to ``_call_tool_safe`` so the governance
# enforcement layer can record blocks against the right run/instance without
# changing the function signature (which is called from multiple paths).
_current_run_id: contextvars.ContextVar[str] = contextvars.ContextVar("ess_run_id", default="")
_current_instance_id: contextvars.ContextVar[str] = contextvars.ContextVar("ess_instance_id", default="")
_current_actor: contextvars.ContextVar[str] = contextvars.ContextVar("ess_actor", default="control-plane")
# In-memory ConversationReference SDK objects keyed by AAD object id of the
# remote user. Populated on every inbound activity. Lost on container restart;
# users only need to send one message to repopulate.
_conversation_refs: dict[str, Any] = {}
_conversation_ref_store = ConversationReferenceStore()


def _hydrate_conversation_refs_from_disk() -> int:
    """Repopulate ``_conversation_refs`` from the persisted JSON store.

    Without this, every container restart wipes the in-memory dict and the
    /api/agentic-instances endpoint reports ``managerHasInstalledBot=false``
    until each manager DMs the bot again. The persisted store on disk
    (``/tmp/ess-teams-refs.json``) already has the references; we just need
    to deserialize them back into SDK objects.
    """
    rehydrated = 0
    for key, record in _conversation_ref_store.all().items():
        ref_dict = (record or {}).get("reference") or {}
        if not ref_dict:
            continue
        ref = conversation_reference_from_dict(ref_dict)
        if ref is not None:
            _conversation_refs[key] = ref
            rehydrated += 1
    if rehydrated:
        _logger.info("Hydrated %d conversation reference(s) from disk", rehydrated)
    return rehydrated
_instance_directory = build_default_directory()
_work_iq_teams = WorkIqTeamsClient()
_hitl = HitlCoordinator()
_graph_chat = GraphChatClient()
# Pending HITL requests delivered via the headless web-form path. Maps
# request_id -> instance metadata so /api/hitl/<id> can render context.
_hitl_form_meta: dict[str, dict[str, Any]] = {}


def _public_base_url(request: web.Request | None = None) -> str:
    """Best-guess public origin for self-referencing links (HITL form)."""
    explicit = os.getenv("ESS_PUBLIC_BASE_URL", "").rstrip("/")
    if explicit:
        return explicit
    if request is not None:
        # Honour the proxy headers the Container Apps ingress sets.
        proto = request.headers.get("X-Forwarded-Proto", request.scheme)
        host = request.headers.get("X-Forwarded-Host", request.host)
        if proto and host:
            return f"{proto}://{host}".rstrip("/")
    return ""

# Per-run context for synthetic tools (e.g. human__ask_manager) that need to
# know which manager to message and which run is asking.
_current_run_ctx: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "ess_current_run_ctx", default=None
)

# Synthetic tool description injected into every run so the LLM can invoke
# human-in-the-loop without an MCP server.
_HUMAN_ASK_MANAGER_TOOL: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "human__ask_manager",
        "description": (
            "Send a question to the human manager of the current AI Teammate user via "
            "Microsoft Teams and pause until they reply. Use this for human-in-the-loop "
            "approvals, clarifying business decisions, or escalations that require a "
            "human judgement before continuing. The reply text is returned as the tool result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The concise question to ask the manager. Include any specific options (e.g. 'Approve / Reject / Hold') if relevant.",
                },
                "context": {
                    "type": "string",
                    "description": "Optional short context the manager needs to make the decision (1-3 sentences).",
                },
            },
            "required": ["question"],
        },
    },
}
_run_limit = 40
_run_stale_after_seconds = int(os.getenv("ESS_RUN_STALE_AFTER_SECONDS", "1200"))


SCENARIO_SERVER_HINTS: dict[str, list[str]] = {
    "incident-triage": ["servicenow", "workday"],
    "team-review": ["workday", "servicenow"],
    "onboarding-audit": ["workday", "servicenow"],
    "sprint-readiness": ["workday", "servicenow"],
    "hiring-pipeline": ["workday", "servicenow"],
    "cross-system-overview": ["workday", "servicenow"],
    "manager-approval": ["servicenow", "workday"],
    "procurement-to-invoice": ["coupa", "servicenow"],
    "requisition-approval-triage": ["coupa", "servicenow"],
}

# Short, user-facing one-liner for each skill. Anything not listed here falls
# back to the first non-empty line of the skill markdown.
SKILL_DESCRIPTIONS: dict[str, str] = {
    "incident-triage": "Triage active ServiceNow incidents with Workday availability context.",
    "team-review": "Summarize a team's Workday roster, performance signals and ServiceNow workload.",
    "onboarding-audit": "Audit recent Workday hires for missing ServiceNow access and pending tasks.",
    "sprint-readiness": "Assess sprint-team readiness from Workday capacity and open ServiceNow work.",
    "hiring-pipeline": "Walk a hiring pipeline across Workday requisitions and ServiceNow tasks.",
    "cross-system-overview": "Cross-system snapshot of Workday and ServiceNow for a person or team.",
    "manager-approval": "Triage the top P1 incident, then ask the manager for a yes/no escalation decision via Teams.",
    "procurement-to-invoice": "Reconcile recent Coupa invoices and POs against ServiceNow receiving/IT tickets to surface pay-but-not-received discrepancies.",
    "requisition-approval-triage": "Find Coupa requisitions stuck in approval, cross-reference the requester's ServiceNow tickets, then ask the manager to approve, reject, or hold.",
}

GREETING_PATTERNS = (
    "hi", "hello", "hey", "hiya", "yo", "howdy", "hola",
    "good morning", "good afternoon", "good evening",
)
HELP_PATTERNS = (
    "help", "?", "skills", "list skills", "what can you do",
    "what can you help with", "menu", "commands",
)


def _safe_bool_env(name: str, default: str = "") -> bool:
    return os.getenv(name, default).lower() not in {"", "0", "false", "no", "off"}


def _detect_human_input_request(content: str) -> dict[str, object] | None:
    """Recognize model responses that are really a human handoff request."""
    text = content.strip()
    if not text:
        return None
    lowered = text.lower()
    handoff_markers = (
        "please provide",
        "need the following information",
        "i need the following",
        "requires manager input",
        "hiring manager should provide",
        "human-in-the-loop",
        "escalate to a human",
    )
    hiring_markers = ("role title", "team / org", "hire type", "hiring manager", "job profile")
    if not any(marker in lowered for marker in handoff_markers):
        return None
    if not any(marker in lowered for marker in hiring_markers):
        return None

    questions = re.findall(r"(?:^|\n)\s*(?:\d+[.)]|[-*])\s*(.+?)(?=\n\s*(?:\d+[.)]|[-*])|$)", text, flags=re.S)
    clean_questions = [" ".join(q.split()).strip(" -") for q in questions if q.strip()]
    if not clean_questions:
        clean_questions = [
            "Role title or job profile",
            "Team, org, or manager context",
            "Hire type: new hire, internal transfer, or promotion",
        ]

    return {
        "kind": "manager_input",
        "channel": "teams",
        "mode": "simulated",
        "recipient": os.getenv("ESS_DEMO_MANAGER_DISPLAY_NAME", "Hiring Manager"),
        "message": text,
        "questions": clean_questions[:6],
        "note": "Simulated Teams handoff for demo-agent control-plane runs.",
    }


def _public_identity_metadata() -> dict[str, Any]:
    return {
        "displayName": _runtime_context.display_name,
        "tenantId": _runtime_context.tenant_id,
        "enabled": _runtime_context.enabled,
        "agentIdentity": {
            "objectId": _runtime_context.agent_identity_id,
            "clientId": _runtime_context.agent_identity_client_id,
        },
        "blueprint": {
            "clientId": _runtime_context.blueprint_client_id,
            "objectId": _runtime_context.blueprint_object_id,
            "principalId": _runtime_context.blueprint_principal_id,
        },
        "foundry": {
            "projectEndpoint": _runtime_context.foundry_project_endpoint,
            "agentId": _runtime_context.foundry_agent_id,
        },
        "gateway": {
            "baseUrl": _runtime_context.gateway_base_url,
            "enabled": bool(_runtime_context.gateway_base_url),
        },
        "observability": observability_status(_runtime_context),
        "headers": agent_headers(_runtime_context),
        "model": os.getenv("ESS_MODEL", "gpt-4.1"),
        "llmBackend": "Azure OpenAI" if os.getenv("AZURE_OPENAI_ENDPOINT") else "GitHub Models",
    }


def _title_from_slug(value: str) -> str:
    return value.replace("-", " ").title()


def _list_skill_slugs() -> list[str]:
    return sorted(p.stem for p in SKILLS_DIR.glob("*.md"))


def _skill_description(slug: str) -> str:
    """Return the short user-facing description for a skill.

    Falls back to the first non-empty markdown line so newly added skills
    are surfaced even before SKILL_DESCRIPTIONS is updated.
    """
    if slug in SKILL_DESCRIPTIONS:
        return SKILL_DESCRIPTIONS[slug]
    path = SKILLS_DIR / f"{slug}.md"
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip().lstrip("#").strip()
            if stripped:
                return stripped[:160]
    return _title_from_slug(slug)


def _render_skills_list(intro: str | None = None) -> str:
    lines: list[str] = []
    if intro:
        lines.append(intro)
        lines.append("")
    lines.append("**Available skills** (type the name to run, e.g. `incident triage`):")
    lines.append("")
    for slug in _list_skill_slugs():
        lines.append(f"- **{_title_from_slug(slug)}** \u2014 {_skill_description(slug)}")
    lines.append("")
    lines.append("You can also send any free-form Workday or ServiceNow task "
                 "and I'll figure out which tools to call.")
    return "\n".join(lines)


def _classify_message(prompt: str) -> str:
    """Classify a Teams message into greeting / help / scenario / freeform."""
    text = re.sub(r"\s+", " ", prompt.strip().lower()).rstrip("?!.")
    if not text:
        return "freeform"
    if text in HELP_PATTERNS or text.startswith("help"):
        return "help"
    if text in GREETING_PATTERNS:
        return "greeting"
    # Short greetings like "hello there" / "hi siva"
    first_token = text.split()[0]
    if first_token in GREETING_PATTERNS and len(text) <= 30:
        return "greeting"
    return "freeform"


def _start_run_record(
    *,
    title: str,
    prompt: str,
    servers: list[str] | None,
    source: str,
    actor: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or f"run-{uuid.uuid4().hex[:12]}"
    actor = actor or {}
    actor_name = actor.get("name") or actor.get("id") or "Control Plane Operator"
    actor_id = actor.get("id") or ("control-plane" if source == "control-plane" else f"{source}-{uuid.uuid4().hex[:8]}")
    # For Teams runs, group sessions by the per-user AI Teammate instance app
    # (e.g. "ESS AI Teammate for Siva") rather than the underlying Teams
    # actor id, so the control plane shows one card per agentic instance.
    agentic_app_id = actor.get("agenticAppId") or ""
    agentic_app_name = actor.get("agenticAppName") or ""
    if source in {"teams-chat", "instance-launch"} and agentic_app_id:
        session_id = agentic_app_id
        session_name = agentic_app_name or (
            f"AI Teammate for {actor_name}" if actor_name else "AI Teammate Instance"
        )
    else:
        session_id = actor_id
        session_name = actor_name
    agentic_user = {
        "id": session_id,
        "name": session_name,
        "actorName": actor_name,
        "actorId": actor_id,
        "agenticAppId": agentic_app_id,
        "agenticAppName": agentic_app_name,
        "source": source,
        "templateId": _runtime_context.agent_identity_id,
        "blueprintId": _runtime_context.blueprint_client_id,
        "runtimeAgentIdentityId": _runtime_context.agent_identity_id,
        "mode": "teams-agentic-user" if source == "teams-chat" else "hosted-control-plane",
    }
    run = {
        "id": run_id,
        "title": title,
        "status": "running",
        "source": source,
        "actor": actor,
        "agenticUser": agentic_user,
        "startedAt": int(time.time() * 1000),
        "updatedAt": int(time.time() * 1000),
        "completedAt": None,
        "prompt": prompt,
        "servers": servers or [],
        "toolData": {},
        "serverCallCounts": {},
        "agentEvents": [],
        "loggedEvents": [],
        "result": "",
        "stats": None,
        "humanRequest": None,
        "error": "",
        "serverRun": True,
    }
    _run_ledger[run_id] = run
    if run_id not in _run_order:
        _run_order.insert(0, run_id)
    del _run_order[_run_limit:]
    for old_id in list(_run_ledger):
        if old_id not in _run_order:
            _run_ledger.pop(old_id, None)
    return run


def _publish_run_event(run_id: str | None, event_type: str, data: dict[str, Any]) -> None:
    if not run_id or run_id not in _run_ledger:
        return
    run = _run_ledger[run_id]
    run["updatedAt"] = int(time.time() * 1000)
    if event_type == "status":
        run["runningText"] = data.get("message", "")
    elif event_type == "metadata":
        run["metadata"] = data
    elif event_type == "turn":
        attrs = dict(data)
        event_name = f"agent.llm.{attrs.get('phase', 'event')}"
        run["agentEvents"].insert(0, {"event": event_name, "timestamp": time.time(), "attributes": attrs})
        run["agentEvents"] = run["agentEvents"][:40]
        phase = attrs.get("phase")
        if phase == "starting":
            run["runningText"] = f"Turn {attrs.get('turn')}: asking the model with {attrs.get('tools')} tools..."
        else:
            run["runningText"] = f"Turn {attrs.get('turn')}: model response received ({attrs.get('finish_reason', 'complete')})"
    elif event_type == "agent_event":
        run["agentEvents"].insert(0, data)
        run["agentEvents"] = run["agentEvents"][:40]
    elif event_type == "agent365_event":
        run["loggedEvents"].insert(0, data)
        run["loggedEvents"] = run["loggedEvents"][:40]
    elif event_type == "tool_call":
        call_id = data.get("id")
        if call_id:
            run["toolData"][call_id] = {
                "server": data.get("server"),
                "tool": data.get("tool"),
                "arguments": data.get("arguments"),
                "result": None,
                "index": data.get("index"),
            }
        server = data.get("server")
        if server:
            run["serverCallCounts"][server] = run["serverCallCounts"].get(server, 0) + 1
        run["runningText"] = f"Calling {data.get('server')}/{data.get('tool')}..."
    elif event_type == "tool_result":
        call_id = data.get("id")
        if call_id and call_id in run["toolData"]:
            run["toolData"][call_id]["result"] = data.get("result")
    elif event_type == "result":
        run["result"] = data.get("content", "")
    elif event_type == "human_input_required":
        run["status"] = "waiting"
        run["humanRequest"] = data
        run["runningText"] = "Waiting for manager reply in Teams handoff"
    elif event_type == "hitl_reply":
        # Manager has replied (via Teams chat, Adaptive Card, or web form) and
        # `_call_human_tool` published the resolved reply. Clear the waiting
        # state so the Approvals tab / run view no longer shows this request
        # as pending. The run continues executing; subsequent `turn`/`done`
        # events will update status to "running"/"complete" naturally, but
        # flip back to "running" immediately so the UI reflects progress
        # without waiting for the next event.
        if run.get("status") == "waiting":
            run["status"] = "running"
        prior_req = run.get("humanRequest") or {}
        prior_req = dict(prior_req) if isinstance(prior_req, dict) else {}
        prior_req["resolved"] = True
        prior_req["reply"] = data.get("reply", "")
        prior_req["repliedAt"] = data.get("repliedAt")
        run["humanRequest"] = prior_req
        run["humanReply"] = {
            "requestId": data.get("requestId"),
            "managerAadId": data.get("managerAadId"),
            "managerName": data.get("managerName"),
            "reply": data.get("reply", ""),
            "repliedAt": data.get("repliedAt"),
        }
        # The dashboard JS (`control-plane.html`) reads `run.managerReply`
        # to decide whether a HITL request is still pending in the Approvals
        # tab (`runs.filter(r => r.humanRequest && !r.managerReply && ...)`).
        # When the page polls `/api/runs` after a Teams-side reply, we need
        # this field populated so the request moves from Pending to Completed
        # without requiring the manager to also reply in the dashboard form.
        run["managerReply"] = data.get("reply", "")
        run["runningText"] = (
            f"{data.get('managerName') or 'Manager'} replied — resuming run."
        )
    elif event_type == "stats":
        run["stats"] = data
    elif event_type == "error":
        run["status"] = "error"
        run["error"] = data.get("message", "")
        run["runningText"] = f"Error: {run['error']}"
    elif event_type == "done":
        if run["status"] == "running":
            run["status"] = "complete"
        run["completedAt"] = int(time.time() * 1000)


def _expire_stale_runs() -> None:
    now = int(time.time() * 1000)
    stale_after_ms = _run_stale_after_seconds * 1000
    for run in _run_ledger.values():
        if run.get("status") not in {"running", "waiting"}:
            continue
        last_update = int(run.get("updatedAt") or run.get("startedAt") or now)
        if now - last_update > stale_after_ms:
            run["status"] = "error"
            run["error"] = f"Marked stale after {_run_stale_after_seconds // 60} minutes without updates."
            run["runningText"] = run["error"]
            run["completedAt"] = now
            run["updatedAt"] = now


def _resolve_scenario_prompt(prompt: str) -> tuple[str, str, list[str] | None, str | None]:
    text = prompt.strip()
    lowered = re.sub(r"\s+", " ", text.lower())
    aliases = {
        "incident triage": "incident-triage",
        "triage incidents": "incident-triage",
        "incident-triage": "incident-triage",
        "team review": "team-review",
        "onboarding audit": "onboarding-audit",
        "sprint readiness": "sprint-readiness",
        "hiring pipeline": "hiring-pipeline",
        "cross system overview": "cross-system-overview",
        "cross-system overview": "cross-system-overview",
    }
    slug = aliases.get(lowered)
    if slug is None and "triage" in lowered and "incident" in lowered:
        slug = "incident-triage"
    if slug is None:
        for path in SKILLS_DIR.glob("*.md"):
            if path.stem in lowered or path.stem.replace("-", " ") in lowered:
                slug = path.stem
                break
    if slug:
        path = SKILLS_DIR / f"{slug}.md"
        if path.exists():
            return path.read_text(encoding="utf-8"), _title_from_slug(slug), SCENARIO_SERVER_HINTS.get(slug), slug
    return text, "Chat Task", None, None


def _estimate_tokens(obj: Any) -> int:
    """Rough token estimate: ~4 chars per token for JSON-serialised content."""
    return len(json.dumps(obj, default=str)) // 4


def _trim_messages(
    messages: list[ChatCompletionMessageParam],
    tool_tokens: int,
) -> list[ChatCompletionMessageParam]:
    """Prune / compress messages so total request fits in MAX_REQUEST_TOKENS.

    Skipped entirely when using Azure OpenAI (128K context).

    Strategy (applied in order until the budget fits):
      1. Truncate tool-result messages to 300 chars
      2. Drop complete assistant+tool groups from the middle
    """
    if _use_azure_openai:
        return messages  # 128K context — no trimming needed

    budget = MAX_REQUEST_TOKENS - tool_tokens - COMPLETION_RESERVE

    if _estimate_tokens(messages) <= budget:
        return messages

    # Pass 1 – compress tool results
    msgs = []
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "tool":
            content = m.get("content", "")
            if isinstance(content, str) and len(content) > 300:
                m = {**m, "content": content[:300] + "…(trimmed)"}
        msgs.append(m)

    if _estimate_tokens(msgs) <= budget:
        return msgs

    # Pass 2 – keep system + user (first 2) and the last complete
    # assistant→tool group.  We walk backwards to find a safe cut point
    # (never orphan tool messages from their assistant message).
    keep_tail = []
    i = len(msgs) - 1
    while i >= 2:
        m = msgs[i]
        keep_tail.insert(0, m)
        # If we just added an assistant message, that's a complete group
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        if role == "assistant":
            break
        i -= 1
    msgs = msgs[:2] + keep_tail

    return msgs


def _slim_schema(schema: dict | None) -> dict:
    """Strip verbose descriptions from parameter schemas to save tokens."""
    if not schema:
        return {"type": "object", "properties": {}}
    out: dict = {"type": schema.get("type", "object")}
    props = schema.get("properties", {})
    out["properties"] = {
        k: {kk: vv for kk, vv in v.items() if kk != "description"}
        for k, v in props.items()
    }
    req = schema.get("required")
    if req:
        out["required"] = req
    return out


def _resilient_httpx_factory(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
    **_kwargs: object,
) -> httpx.AsyncClient:
    """httpx client with transport-level retries for flaky ACA shared-IP TLS."""
    transport = httpx.AsyncHTTPTransport(retries=3)
    return httpx.AsyncClient(
        transport=transport,
        follow_redirects=True,
        timeout=timeout or httpx.Timeout(30.0, read=300.0),
        headers=headers,
        auth=auth,
    )


async def connect(
    name: str,
    url: str,
    token_provider: ServerTokenProvider,
    context: AgentIdentityContext,
) -> tuple[Client, list[ChatCompletionToolParam]]:
    """Return a connected Client and its tools in OpenAI format."""
    token = await token_provider.get_token(name)
    transport = StreamableHttpTransport(
        url,
        headers={"Authorization": f"Bearer {token}", **agent_headers(context)},
        httpx_client_factory=_resilient_httpx_factory,
    )
    client = Client(transport, name=name)
    await client.__aenter__()
    tools: list[ChatCompletionToolParam] = [
        {
            "type": "function",
            "function": {
                "name": f"{name}__{t.name}",
                "description": (t.description or "")[:100],
                "parameters": _slim_schema(t.inputSchema),
            },
        }
        for t in await client.list_tools()
    ]
    return client, tools


# ── API routes ─────────────────────────────────────────────────────


async def handle_skills(request: web.Request) -> web.Response:
    """Return the list of available skills with their content."""
    skills = []
    for p in sorted(SKILLS_DIR.glob("*.md")):
        skills.append({"name": p.stem, "prompt": p.read_text(encoding="utf-8")})
    return web.json_response(skills)


async def handle_servers(request: web.Request) -> web.Response:
    """Return connected server names and tool counts."""
    info = []
    for name, client in _servers.items():
        url = _server_configs.get(name, "")
        tool_count = sum(
            1 for t in _all_tools if t["function"]["name"].startswith(f"{name}__")
        )
        info.append({
            "name": name,
            "url": url,
            "tools": tool_count,
            "gateway": bool(os.getenv(f"ESS_{name.upper()}_AI_GATEWAY_MCP_URL") or _runtime_context.gateway_base_url),
            "agentIdentity": _runtime_context.agent_identity_id,
            "blueprint": _runtime_context.blueprint_client_id,
        })
    return web.json_response(info)


async def handle_identity(request: web.Request) -> web.Response:
    """Return public Agent 365 / gateway metadata with no secrets or tokens."""
    return web.json_response(_public_identity_metadata())


async def handle_a365_value(request: web.Request) -> web.Response:
    """Return the Agent 365 value catalog for this SDK-hosted agent.

    Each feature includes data-flow context, the operator pitch, links to
    the Microsoft 365 portal that owns it, and copy-paste KQL /
    PowerShell queries ready for that portal. Consumed by the control
    plane "Agent 365 value" panel.
    """
    features = a365_value.feature_catalog()
    return web.json_response({
        "generatedAt": int(time.time() * 1000),
        "agent": {
            "displayName": _runtime_context.display_name,
            "tenantId": _runtime_context.tenant_id,
            "agentAppId": _runtime_context.agent_identity_client_id,
            "agentObjectId": _runtime_context.agent_identity_id,
            "endpoint": f"https://{a365_value.AGENT_FQDN}",
        },
        "statusOrder": list(a365_value.STATUS_ORDER),
        "statusLabels": a365_value.STATUS_LABEL,
        "statusSummary": a365_value.status_summary(features),
        "categorySummary": a365_value.category_summary(features),
        "features": features,
    })


async def handle_runs(request: web.Request) -> web.Response:
    """Return recent hosted/chat/control-plane runs for the fleet view."""
    _expire_stale_runs()
    runs = [_run_ledger[run_id] for run_id in _run_order if run_id in _run_ledger]
    return web.json_response(runs)


async def handle_runs_reset(request: web.Request) -> web.Response:
    """Clear the in-memory demo run ledger."""
    _run_ledger.clear()
    _run_order.clear()
    return web.json_response({"cleared": True})


async def _reconnect(name: str) -> None:
    """Reconnect a dropped MCP client using stored config."""
    url = _server_configs[name]
    token = await _token_provider.get_token(name)
    try:
        await _servers[name].__aexit__(None, None, None)
    except Exception:
        pass
    transport = StreamableHttpTransport(
        url,
        headers={"Authorization": f"Bearer {token}", **agent_headers(_runtime_context)},
        httpx_client_factory=_resilient_httpx_factory,
    )
    client = Client(transport, name=name)
    await asyncio.wait_for(client.__aenter__(), timeout=45)
    _servers[name] = client
    print(f"  🔄 {name}: reconnected")


async def _call_tool_safe(srv: str, tool_name: str, args: dict) -> str:
    """Call an MCP tool with timeout and auto-reconnect on disconnection."""
    if srv == "human":
        return await _call_human_tool(tool_name, args)
    # ── Control-plane enforcement: tool deny-list ─────────────────
    # Centralised, per-fleet policy. Operator can block any server/tool
    # pattern at runtime from the control plane UI; the agent sees the
    # block as a synthetic tool result so the LLM keeps reasoning but
    # never reaches the real upstream system.
    decision = governance_state.is_tool_blocked(srv, tool_name)
    if decision.blocked:
        run_id = _current_run_id.get("")
        actor = _current_actor.get("control-plane")
        governance_state.record_tool_block(
            server=srv, tool=tool_name, decision=decision, run_id=run_id, actor=actor,
        )
        _publish_run_event(run_id or None, "policy_event", {
            "server": srv,
            "tool": tool_name,
            "action": "blocked-by-control-plane",
            "rule": decision.rule,
            "reason": decision.reason,
            "source": "governance",
        })
        return f"[BLOCKED BY CONTROL PLANE POLICY: {decision.reason}]"
    for attempt in range(3):
        try:
            result: Any = await asyncio.wait_for(
                _servers[srv].call_tool(tool_name, args), timeout=60
            )
            # Extract just the text content; str() triplicates data
            if hasattr(result, "content") and result.content:
                parts = [c.text for c in result.content if hasattr(c, "text")]
                return "\n".join(parts) if parts else str(result)
            return str(result)
        except asyncio.TimeoutError:
            print(f"  ⚠ {srv}__{tool_name}: timed out (60s)")
            return "Error: tool call timed out after 60s"
        except Exception as exc:
            error_text = str(exc).lower()
            # Upstream SaaS token expired / was revoked. Drop the cached
            # bearer, reconnect (which mints a fresh OAuth token via the
            # token provider), and retry the same tool call.
            auth_expired = any(
                marker in error_text
                for marker in (
                    "401",
                    "unauthorized",
                    "invalid_token",
                    "token expired",
                    "token has expired",
                    "access token has expired",
                    "expired token",
                )
            )
            reconnectable = auth_expired or any(
                marker in error_text
                for marker in (
                    "not connected",
                    "session terminated",
                    "session not found",
                    "404",
                    "mcp-session-id",
                )
            )
            if attempt < 2 and reconnectable:
                if auth_expired:
                    print(f"  \U0001f511 {srv}: upstream auth expired \u2014 refreshing token & reconnecting\u2026")
                    try:
                        invalidate = getattr(_token_provider, "invalidate", None)
                        if callable(invalidate):
                            invalidate(srv)
                    except Exception:  # noqa: BLE001 - best-effort cache flush
                        pass
                else:
                    print(f"  \u26a0 {srv}: MCP session dropped \u2014 reconnecting\u2026")
                try:
                    await _reconnect(srv)
                    continue  # retry the tool call
                except Exception as re_exc:
                    return f"Error: reconnect failed: {re_exc}"
            return f"Error: {exc}"
    return "Error: tool call failed after retry"


async def _find_instance_for_manager(manager_aad_id: str) -> AgenticInstance | None:
    """Look up the AgenticInstance whose owning user reports to `manager_aad_id`."""
    if not manager_aad_id:
        return None
    try:
        instances = await _instance_directory.list_instances()
    except Exception as exc:  # pragma: no cover - defensive
        _logger.warning("instance directory list failed: %s", exc)
        return None
    for inst in instances:
        if inst.manager_id == manager_aad_id:
            return inst
    return None


async def _deliver_hitl_via_graph(
    *,
    manager_id: str,
    manager_name: str,
    asker_name: str,
    question: str,
    extra_context: str,
    request_id: str,
    run_id: str,
    base_url: str,
) -> dict[str, Any]:
    """Headless HITL delivery via Microsoft Graph: 1:1 Teams chat → email fallback.

    The chat message asks the manager to reply with free text in the same
    Teams thread; the agent's `on_message` handler resolves the pending HITL
    request from whatever they type (yes/no/approve/reject with optional
    notes). No web form, no buttons.
    """
    if not _graph_chat.available:
        return {"status": "unavailable", "reason": "managed identity not available"}
    instance = await _find_instance_for_manager(manager_id)
    if instance is None:
        return {
            "status": "no_instance",
            "reason": f"no AgenticInstance found for manager_id={manager_id}",
        }
    safe_question = html_module.escape(question)
    safe_context = html_module.escape(extra_context) if extra_context else ""
    pieces: list[str] = [
        f"<p>\U0001F916 <strong>{html_module.escape(asker_name)}</strong> needs your input:</p>",
        f"<blockquote>{safe_question}</blockquote>",
    ]
    if safe_context:
        pieces.append(f"<p><em>Context:</em> {safe_context}</p>")
    pieces.append(
        "<p>Reply in this chat with <strong>yes</strong>, <strong>no</strong>, "
        "<strong>approve</strong>, or <strong>reject</strong> \u2014 add any notes "
        "you want the agent to use.</p>"
    )
    body_html = "\n".join(pieces)
    # The "from" user for the Teams 1:1 chat is the teammate's own agentic
    # user (e.g. `hraiteammate-sivav2@<tenant>` for the HR v2 teammate). Do
    # NOT override to a generic primary agent SP \u2014 those are app service
    # principals, not Graph users, so `/users/{oid}` returns 404 and chat
    # creation silently demotes to email-self. The agentic user IS a real
    # AAD user and is the natural sender for messages from this teammate.
    agent_oid = instance.user_id
    agent_upn = instance.user_upn
    # PRIMARY path: mint a delegated Graph token AS the per-user teammate
    # user via the Agents SDK's agentic federated user_fic flow, then post
    # a 1:1 Teams chat between [teammate_user, manager]. This is the only
    # path that delivers a real Teams message (the agent-identity SP and
    # blueprint-app paths fail at roster check / 401 respectively).
    if (
        _connection_manager is not None
        and instance.instance_app_id
        and agent_oid
        and manager_id
    ):
        try:
            tenant_id = os.getenv("AZURE_TENANT_ID", "") or instance.tenant_id  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            tenant_id = os.getenv("AZURE_TENANT_ID", "")
        result = await _graph_chat.deliver_hitl_as_agentic_user(
            connection_manager=_connection_manager,
            tenant_id=tenant_id,
            instance_app_id=instance.instance_app_id,
            agentic_user_id=agent_oid,
            manager_user_id=manager_id,
            html=body_html,
        )
        if result.get("status") == "sent":
            return result
        _logger.warning(
            "agentic-user HITL delivery failed instance=%s reason=%s; falling back",
            instance.instance_app_id, result.get("reason"),
        )
    # FALLBACK path (legacy): graph_chat.deliver_hitl tries Teams 1:1 chat
    # via the host MI / agent-identity sidecar token, then surfaces failure.
    # Retained as a safety net for instances where the agentic-user federation
    # path is unavailable (e.g. SDK not initialised in test harness).
    return await _graph_chat.deliver_hitl(
        agent_user_id=agent_oid,
        agent_user_upn=agent_upn,
        manager_aad_id=manager_id,
        manager_upn=instance.manager_upn,
        manager_email=instance.manager_email or instance.manager_upn,
        subject=f"[{instance.display_name}] needs your input",
        html=body_html,
    )


async def _call_human_tool(tool_name: str, args: dict) -> str:
    """Synthetic tool: ask the manager via Teams and pause until they reply.

    Delivery path:
      1. Bot Framework proactive (if manager has installed the bot).
      2. Microsoft Graph 1:1 Teams chat (if manager has not).
      3. Email fallback (if Graph chat is unavailable).
    The reply arrives either via the bot's on_message handler (path 1) or via
    the public web form mounted at ``/api/hitl/<request_id>`` (paths 2 & 3).
    """
    if tool_name != "ask_manager":
        return f"Error: unknown human tool '{tool_name}'"
    ctx = _current_run_ctx.get() or {}
    manager_id = ctx.get("manager_id") or ""
    manager_name = ctx.get("manager_name") or "the manager"
    asker_name = ctx.get("asker_name") or _runtime_context.display_name
    run_id = ctx.get("run_id") or ""
    base_url = _public_base_url(None)
    question = (args.get("question") or "").strip()
    extra_context = (args.get("context") or "").strip()
    if not question:
        return "Error: ask_manager requires a 'question' argument."
    if not manager_id:
        return (
            "Error: no manager is configured for this run, so the agent cannot ask a human. "
            "Proceed with your best judgement and clearly state any assumptions."
        )

    timeout_seconds = float(os.getenv("ESS_HITL_TIMEOUT_SECONDS", "600"))
    req, fut = await _hitl.request(
        run_id=run_id,
        manager_aad_id=manager_id,
        manager_name=manager_name,
        question=question,
        asker_name=asker_name,
        asker_aad_id=ctx.get("asker_aad_id", ""),
        timeout=timeout_seconds,
    )
    _hitl_form_meta[req.request_id] = {
        "managerName": manager_name,
        "askerName": asker_name,
        "question": question,
        "context": extra_context,
        "runId": run_id,
    }

    body_lines = [
        f"🤖 **{asker_name}** is asking for your input on a run in progress:",
        "",
        f"> {question}",
    ]
    if extra_context:
        body_lines += ["", f"_Context:_ {extra_context}"]
    form_url = (base_url.rstrip("/") + f"/api/hitl/{req.request_id}") if base_url else ""
    if form_url:
        body_lines += ["", f"Reply via this link: {form_url}"]
    body_lines += [
        "",
        "Or reply in this chat to continue the run. "
        f"(Run id: `{run_id or 'n/a'}` · request `{req.request_id[:8]}`)",
    ]
    bot_text = "\n".join(body_lines)

    # 1) Try Bot Framework proactive (works if manager has installed the bot).
    delivery: dict[str, Any] = {"status": "skipped", "reason": "no bot delivery attempted"}
    _logger.info(
        "hitl proactive guard rid=%s adapter=%s manager_id=%s direct_ref=%s known_refs=%d",
        req.request_id,
        _cloud_adapter is not None,
        manager_id,
        manager_id in _conversation_refs,
        len(_conversation_refs),
    )
    if _cloud_adapter is not None and manager_id:
        hitl_card = _build_hitl_adaptive_card(
            asker_name=asker_name,
            question=question,
            extra_context=extra_context,
            request_id=req.request_id,
            run_id=run_id,
            form_url=form_url,
        )
        delivery = await _proactive_send_to_user(
            manager_id,
            card=hitl_card,
            summary_text=f"{asker_name} needs your input",
        )
        _logger.info(
            "hitl bot delivery rid=%s status=%s reason=%s",
            req.request_id, delivery.get("status"), delivery.get("reason", ""),
        )

    # 2) Fall back to Graph chat / email if the bot could not deliver.
    if delivery.get("status") != "sent":
        graph_delivery = await _deliver_hitl_via_graph(
            manager_id=manager_id,
            manager_name=manager_name,
            asker_name=asker_name,
            question=question,
            extra_context=extra_context,
            request_id=req.request_id,
            run_id=run_id,
            base_url=base_url,
        )
        _logger.info(
            "hitl graph delivery rid=%s status=%s channel=%s reason=%s",
            req.request_id,
            graph_delivery.get("status"),
            graph_delivery.get("channel", ""),
            graph_delivery.get("reason", ""),
        )
        if graph_delivery.get("status") == "sent":
            delivery = graph_delivery
        else:
            # Both push channels failed. We do NOT abort — the Approvals tab in the
            # control plane is a first-class HITL channel that can resolve the same
            # request_id via POST /api/hitl/<id>/respond. Record the delivery
            # failure on the request so the dashboard card can surface it, then
            # continue to wait on the future just like the success path.
            reason = graph_delivery.get("reason") or delivery.get("reason") or "unknown"
            delivery = {
                "status": "error",
                "channel": graph_delivery.get("channel") or delivery.get("channel") or "teams-chat",
                "reason": reason,
            }
            _logger.warning(
                "hitl push delivery failed rid=%s reason=%s — falling back to Approvals tab",
                req.request_id, reason,
            )

    if run_id:
        summary = req.to_summary()
        summary["deliveryChannel"] = delivery.get("channel", "teams-bot")
        summary["deliveryStatus"] = delivery.get("status", "sent")
        if delivery.get("reason"):
            summary["deliveryError"] = delivery.get("reason")
        if form_url:
            summary["formUrl"] = form_url
        # Legacy event for older dashboards.
        _publish_run_event(run_id, "hitl_request", summary)
        # Modern dashboard event — what the Approvals tab and run-view human panel listen for.
        _publish_run_event(run_id, "human_input_required", {
            "requestId": req.request_id,
            "runId": run_id,
            "recipient": manager_name,
            "managerAadId": manager_id,
            "message": question,
            "context": extra_context,
            "channel": summary["deliveryChannel"],
            "deliveryStatus": summary["deliveryStatus"],
            "deliveryError": summary.get("deliveryError", ""),
            "formUrl": form_url,
            "askedAt": summary.get("askedAt"),
        })
    try:
        reply: str = await asyncio.wait_for(fut, timeout=timeout_seconds)
    except asyncio.TimeoutError:
        _hitl_form_meta.pop(req.request_id, None)
        return (
            f"Error: timed out waiting for {manager_name} to reply after {int(timeout_seconds)}s. "
            "Proceed with your best judgement and note that approval is still pending."
        )
    _hitl_form_meta.pop(req.request_id, None)
    reply = (reply or "").strip() or "(no reply text)"
    if run_id:
        _publish_run_event(run_id, "hitl_reply", {
            "requestId": req.request_id,
            "managerAadId": manager_id,
            "managerName": manager_name,
            "reply": reply,
            "repliedAt": int(time.time() * 1000),
        })
    return f"{manager_name} replied: {reply}"


async def handle_run(request: web.Request) -> web.StreamResponse:
    """Run the agentic loop, streaming progress as SSE."""
    body = await request.json()
    prompt = body.get("prompt", "").strip()
    server_filter = body.get("servers")  # optional list of server names
    run_id = body.get("runId")
    run_title = body.get("title") or "Control Plane Run"
    print(f"▶ /api/run  prompt={prompt[:80]}…" if len(prompt) > 80 else f"▶ /api/run  prompt={prompt}")
    if not prompt:
        return web.json_response({"error": "prompt is required"}, status=400)

    run_record = _start_run_record(
        title=run_title,
        prompt=prompt,
        servers=list(server_filter or []),
        source=body.get("source") or "control-plane",
        run_id=run_id,
    )
    run_id = run_record["id"]

    # Propagate run context so governance enforcement (_call_tool_safe) can
    # attribute blocked tool calls to this run in the audit ledger.
    _current_run_id.set(run_id)
    _current_actor.set((run_record.get("actor") or {}).get("name") or "control-plane")

    # Filter tools to requested servers (avoids exceeding token limits)
    if server_filter:
        allowed = set(server_filter)
        tools = [t for t in _all_tools if t["function"]["name"].split("__")[0] in allowed]
    else:
        tools = list(_all_tools)
    # Always offer the human-in-the-loop synthetic tool; the LLM will only call
    # it when a scenario explicitly asks for human approval/judgement.
    tools.append(_HUMAN_ASK_MANAGER_TOOL)
    _current_run_ctx.set({
        "run_id": run_id,
        "actor": run_record.get("actor") or {},
        "manager_id": (run_record.get("actor") or {}).get("managerId", ""),
        "manager_name": (run_record.get("actor") or {}).get("managerName", ""),
        "manager_email": (run_record.get("actor") or {}).get("managerEmail", ""),
        "asker_name": (run_record.get("actor") or {}).get("name") or _runtime_context.display_name,
        "asker_aad_id": (run_record.get("actor") or {}).get("aadObjectId", ""),
    })

    resp = web.StreamResponse(
        status=200,
        reason="OK",
        headers={
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
    await resp.prepare(request)

    async def send_event(event: str, data: dict) -> None:
        _publish_run_event(run_id, event, data)
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        await resp.write(payload.encode())

    async def send_observed_event(name: str, **attributes: object) -> None:
        await send_event("agent_event", {
            "event": name,
            "timestamp": time.time(),
            "attributes": {
                "gen_ai.agent.name": _runtime_context.display_name,
                "microsoft.agent365.blueprint.client_id": _runtime_context.blueprint_client_id,
                "microsoft.agent365.agent_identity.id": _runtime_context.agent_identity_id,
                "microsoft.agent365.foundry.agent_id": _runtime_context.foundry_agent_id,
                **attributes,
            },
        })

    model = os.getenv("ESS_MODEL", "gpt-4.1")
    max_turns = int(os.getenv("ESS_MAX_TURNS", "25"))
    llm = _create_llm_client()

    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": prompt + _runtime_context.system_prompt_preamble()},
        {"role": "user", "content": "Execute the task described above."},
    ]

    # Track which servers were actually called (for progressive pruning on GitHub Models)
    used_servers: set[str] = set()

    stats = {
        "model": model,
        "agent": _runtime_context.display_name,
        "agentIdentity": _runtime_context.agent_identity_id,
        "blueprint": _runtime_context.blueprint_client_id,
        "gateway": bool(_runtime_context.gateway_base_url),
        "turns": 0,
        "tool_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "start_time": time.time(),
    }

    backend = "Azure OpenAI" if _use_azure_openai else "GitHub Models"
    gateway_note = " through AI Gateway" if stats["gateway"] else ""
    await send_event("status", {"message": f"Starting{gateway_note} with {len(tools)} tools on {model} ({backend})"})
    await send_event("metadata", _public_identity_metadata())
    await send_observed_event("agent.web_run", model=model, tool_count=len(tools), llm_backend=backend)

    client_ip = (
        request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
        or (request.remote or "")
    )
    principal = RunPrincipal.anonymous(
        source=body.get("source") or "control-plane",
        client_ip=client_ip,
    )

    try:
        with _telemetry.start_invoke_scope(
            run_id=run_id,
            conversation_id=run_id,
            principal=principal,
            prompt=prompt,
        ) as invoke_scope, _telemetry.span("agent.web_run", model=model, tool_count=len(tools)):
            final_content_for_scope = ""
            for turn in range(max_turns):
                stats["turns"] = turn + 1
                await send_event("turn", {"turn": turn + 1, "phase": "starting", "tools": len(tools), "messages": len(messages)})
                await send_observed_event("agent.llm", turn=turn + 1, phase="request", tool_count=len(tools))

                # ── Progressive tool pruning (GitHub Models only) ──
                if not _use_azure_openai and turn > 0 and used_servers:
                    tools = [t for t in tools if t["function"]["name"].split("__")[0] in used_servers]

                # ── Token budget: trim messages (GitHub Models only) ──
                tool_tokens = _estimate_tokens(tools)
                messages = _trim_messages(messages, tool_tokens)

                print(f"  ↳ turn {turn+1}: calling {model} with {len(messages)} msgs, {len(tools)} tools (~{tool_tokens + _estimate_tokens(messages)} tok)")
                try:
                    with _telemetry.start_inference_scope(
                        run_id=run_id,
                        conversation_id=run_id,
                        model=model,
                        provider=backend,
                        principal=principal,
                        input_messages=[prompt] if turn == 0 else None,
                    ) as inference_scope, _telemetry.span("agent.llm", turn=turn + 1):
                        if tools:
                            completion = await llm.chat.completions.create(
                                model=model,
                                messages=messages,
                                tools=tools,
                            )
                        else:
                            completion = await llm.chat.completions.create(
                                model=model,
                                messages=messages,
                            )
                        if inference_scope is not None:
                            try:
                                if completion.usage:
                                    inference_scope.record_input_tokens(completion.usage.prompt_tokens)  # type: ignore[attr-defined]
                                    inference_scope.record_output_tokens(completion.usage.completion_tokens)  # type: ignore[attr-defined]
                                inference_scope.record_finish_reasons([completion.choices[0].finish_reason or "stop"])  # type: ignore[attr-defined]
                                if completion.choices[0].message.content:
                                    inference_scope.record_output_messages([completion.choices[0].message.content])  # type: ignore[attr-defined]
                            except Exception:
                                pass
                except Exception as api_err:
                    err_str = str(api_err)
                    if not _use_azure_openai and ("413" in err_str or "tokens_limit_reached" in err_str):
                        # GitHub Models: too many tools — reduce to mentioned servers
                        mentioned = [s for s in _servers if s in prompt.lower()]
                        if mentioned and len(mentioned) < len(_servers):
                            allowed = set(mentioned)
                            tools = [t for t in tools if t["function"]["name"].split("__")[0] in allowed]
                            tool_tokens = _estimate_tokens(tools)
                            messages = _trim_messages(messages, tool_tokens)
                            print(f"  ↳ 413 hit — retrying with {len(tools)} tools (servers: {mentioned})")
                            await send_event("status", {"message": f"Too many tools — retrying with {', '.join(mentioned)} ({len(tools)} tools)"})
                            with _telemetry.span("agent.llm.retry", turn=turn + 1):
                                if tools:
                                    completion = await llm.chat.completions.create(
                                        model=model,
                                        messages=messages,
                                        tools=tools,
                                    )
                                else:
                                    completion = await llm.chat.completions.create(
                                        model=model,
                                        messages=messages,
                                    )
                        else:
                            raise
                    else:
                        raise

                print(f"  ↳ turn {turn+1}: got response (finish_reason={completion.choices[0].finish_reason})")
                await send_event("turn", {"turn": turn + 1, "phase": "completed", "finish_reason": completion.choices[0].finish_reason})
                await send_observed_event("agent.llm", turn=turn + 1, phase="response", finish_reason=completion.choices[0].finish_reason)
                msg = completion.choices[0].message

                # Accumulate token usage
                if completion.usage:
                    stats["prompt_tokens"] += completion.usage.prompt_tokens
                    stats["completion_tokens"] += completion.usage.completion_tokens
                    stats["total_tokens"] += completion.usage.total_tokens

                if not msg.tool_calls:
                    # Final answer
                    final_content = msg.content or ""
                    final_content_for_scope = final_content
                    if invoke_scope is not None and final_content:
                        try:
                            invoke_scope.record_output_messages([final_content])  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    stats["duration"] = round(time.time() - stats["start_time"], 2)
                    await send_event("result", {"content": final_content})
                    handoff = _detect_human_input_request(final_content)
                    if handoff:
                        handoff_questions = handoff.get("questions", [])
                        await send_observed_event(
                            "agent.human_input.requested",
                            channel=handoff["channel"],
                            mode=handoff["mode"],
                            recipient=handoff["recipient"],
                            question_count=len(handoff_questions) if isinstance(handoff_questions, list) else 0,
                        )
                        await send_event("human_input_required", handoff)
                    await send_event("stats", stats)
                    await send_event("done", {})
                    return resp

                messages.append(msg)  # type: ignore[arg-type]

                for tc in msg.tool_calls:
                    if tc.type != "function":
                        continue
                    fn = tc.function
                    srv, tool_name = fn.name.split("__", 1)
                    args = json.loads(fn.arguments)
                    stats["tool_calls"] += 1
                    used_servers.add(srv)

                    await send_event("tool_call", {
                        "id": tc.id,
                        "server": srv,
                        "tool": tool_name,
                        "arguments": args,
                        "index": stats["tool_calls"],
                    })
                    await send_observed_event("agent.tool", server=srv, tool=tool_name, call_id=tc.id, phase="request")

                    started_ms = now_ms()
                    with _telemetry.span("agent.tool", server=srv, tool=tool_name):
                        result_str = await _call_tool_safe(srv, tool_name, args)

                    # Apply Purview Information Protection policy to the tool result.
                    policy_attrs: dict[str, object] = {}
                    policy_action = ""
                    decision = _telemetry.apply_purview_policy(content=result_str)
                    if decision is not None:
                        result_str = decision.content
                        policy_attrs = decision.telemetry_attributes()
                        policy_action = decision.action

                    observed_event = _telemetry.observe_tool_call(
                        ObservedToolCall(
                            call_id=tc.id,
                            server=srv,
                            tool=tool_name,
                            arguments=args,
                            result=result_str,
                            duration_ms=now_ms() - started_ms,
                            success=not result_str.startswith("Error:"),
                            error=result_str if result_str.startswith("Error:") else "",
                            policy_attributes=policy_attrs,
                            policy_action=policy_action,
                        )
                    )
                    await send_event("agent365_event", observed_event)
                    if policy_action and policy_action != "allow":
                        await send_event("policy_event", {
                            "tool_call_id": tc.id,
                            "server": srv,
                            "tool": tool_name,
                            "action": policy_action,
                            "label_name": policy_attrs.get("microsoft.purview.sensitivity_label_name"),
                            "label_id": policy_attrs.get("microsoft.purview.sensitivity_label_id"),
                            "reason": policy_attrs.get("agent.tool_result.policy_reason"),
                        })
                    await send_observed_event(
                        "agent.tool",
                        server=srv,
                        tool=tool_name,
                        call_id=tc.id,
                        phase="response",
                        success=not result_str.startswith("Error:"),
                        duration_ms=now_ms() - started_ms,
                    )

                    # Cap result length (generous on Azure OpenAI, tight on GitHub Models)
                    max_result = 4000 if _use_azure_openai else 800
                    if len(result_str) > max_result:
                        result_str = result_str[:max_result] + "…(truncated)"

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result_str,
                    })

                    await send_event("tool_result", {
                        "id": tc.id,
                        "server": srv,
                        "tool": tool_name,
                        "result": result_str[:4000],  # cap for SSE
                    })

            # Reached turn limit
            stats["duration"] = round(time.time() - stats["start_time"], 2)
            await send_event("result", {"content": "⚠️ Reached maximum turn limit."})
            await send_event("stats", stats)
            await send_event("done", {})

    except Exception as exc:
        import traceback
        traceback.print_exc()
        await send_event("error", {"message": f"Agent error: {exc}"})
        await send_event("done", {})

    return resp


async def run_text_task(
    prompt: str,
    *,
    max_turns: int | None = None,
    source: str = "chat",
    actor: dict[str, Any] | None = None,
) -> str:
    """Run the autonomous loop for non-SSE callers such as Teams chat."""
    if not prompt.strip():
        return "Please send a task for the Workday and ServiceNow agent."
    if not _all_tools:
        return "The Workday and ServiceNow MCP tools are not connected yet."

    resolved_prompt, title, server_filter, skill_name = _resolve_scenario_prompt(prompt)
    run = _start_run_record(title=title, prompt=resolved_prompt, servers=server_filter, source=source, actor=actor)
    run_id = run["id"]
    # Propagate run + instance context so the governance enforcement layer
    # (`_call_tool_safe`) can record blocks against the right run.
    _current_run_id.set(run_id)
    _current_instance_id.set((actor or {}).get("agenticAppId", ""))
    _current_actor.set((actor or {}).get("name") or source)
    # Establish run context so synthetic human-in-the-loop tool calls can
    # resolve the manager AAD id and surface the right run in the UI.
    _current_run_ctx.set({
        "run_id": run_id,
        "actor": actor or {},
        "manager_id": (actor or {}).get("managerId", ""),
        "manager_name": (actor or {}).get("managerName", ""),
        "manager_email": (actor or {}).get("managerEmail", ""),
        "asker_name": (actor or {}).get("agenticAppName") or (actor or {}).get("name", ""),
        "asker_aad_id": (actor or {}).get("aadObjectId", ""),
    })
    model = os.getenv("ESS_MODEL", "gpt-4.1")
    llm = _create_llm_client()
    if server_filter:
        allowed = set(server_filter)
        tools = [t for t in _all_tools if t["function"]["name"].split("__")[0] in allowed]
    else:
        tools = list(_all_tools)
    # Inject the synthetic human-in-the-loop tool. It carries no MCP cost and
    # is gated by the per-scenario prompt explicitly asking for approval.
    tools.append(_HUMAN_ASK_MANAGER_TOOL)
    messages: list[ChatCompletionMessageParam] = [
        {
            "role": "system",
            "content": (
                "You are the ESS Workday ServiceNow hosted autonomous agent. "
                "Use only the connected Workday and ServiceNow MCP tools when tools are needed."
                + _runtime_context.system_prompt_preamble()
            ),
        },
        {"role": "user", "content": resolved_prompt},
    ]

    stats = {
        "model": model,
        "agent": _runtime_context.display_name,
        "agentIdentity": _runtime_context.agent_identity_id,
        "blueprint": _runtime_context.blueprint_client_id,
        "gateway": bool(_runtime_context.gateway_base_url),
        "source": source,
        "skill": skill_name,
        "turns": 0,
        "tool_calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "start_time": time.time(),
    }

    _publish_run_event(run_id, "status", {"message": f"Starting chat-triggered run with {len(tools)} tools on {model}"})
    _publish_run_event(run_id, "metadata", _public_identity_metadata())
    _publish_run_event(run_id, "agent_event", {
        "event": "agent.chat_run",
        "timestamp": time.time(),
        "attributes": {
            "source": source,
            "skill": skill_name or "ad-hoc",
            "tool_count": len(tools),
            "actor": actor or {},
        },
    })

    try:
        principal = RunPrincipal.from_actor(actor, source=source)
        # Per-instance teammate (HR/IT/PO) — when this run is launched on
        # behalf of an agentic instance we override the Agent 365
        # AgentDetails so Purview Activity Explorer reports the row under
        # the per-user teammate identity instead of the parent hosted agent.
        instance_agent_client_id = (actor or {}).get("agenticAppClientId", "") or ""
        instance_agent_object_id = (actor or {}).get("agenticAppId", "") or ""
        instance_agent_name = (actor or {}).get("agenticAppName", "") or ""
        backend = "Azure OpenAI" if _use_azure_openai else "GitHub Models"
        with _telemetry.start_invoke_scope(
            run_id=run_id,
            conversation_id=principal.conversation_id or run_id,
            principal=principal,
            prompt=resolved_prompt,
            agent_identity_client_id=instance_agent_client_id or None,
            agent_display_name=instance_agent_name or None,
            agentic_user_id=instance_agent_object_id or None,
        ) as invoke_scope, _telemetry.span("agent.teams_run", model=model, tool_count=len(tools), source=source):
            for turn in range(max_turns or int(os.getenv("ESS_TEAMS_MAX_TURNS", "12"))):
                stats["turns"] = turn + 1
                _publish_run_event(run_id, "turn", {"turn": turn + 1, "phase": "starting", "tools": len(tools), "messages": len(messages)})
                tool_tokens = _estimate_tokens(tools)
                messages = _trim_messages(messages, tool_tokens)
                with _telemetry.start_inference_scope(
                    run_id=run_id,
                    conversation_id=principal.conversation_id or run_id,
                    model=model,
                    provider=backend,
                    principal=principal,
                    input_messages=[resolved_prompt] if turn == 0 else None,
                    agent_identity_client_id=instance_agent_client_id or None,
                    agent_display_name=instance_agent_name or None,
                    agentic_user_id=instance_agent_object_id or None,
                ) as inference_scope, _telemetry.span("agent.llm", turn=turn + 1):
                    if tools:
                        completion = await llm.chat.completions.create(model=model, messages=messages, tools=tools)
                    else:
                        completion = await llm.chat.completions.create(model=model, messages=messages)
                    if inference_scope is not None:
                        try:
                            if completion.usage:
                                inference_scope.record_input_tokens(completion.usage.prompt_tokens)  # type: ignore[attr-defined]
                                inference_scope.record_output_tokens(completion.usage.completion_tokens)  # type: ignore[attr-defined]
                            inference_scope.record_finish_reasons([completion.choices[0].finish_reason or "stop"])  # type: ignore[attr-defined]
                            if completion.choices[0].message.content:
                                inference_scope.record_output_messages([completion.choices[0].message.content])  # type: ignore[attr-defined]
                        except Exception:
                            pass
                msg = completion.choices[0].message
                if completion.usage:
                    stats["prompt_tokens"] += completion.usage.prompt_tokens
                    stats["completion_tokens"] += completion.usage.completion_tokens
                    stats["total_tokens"] += completion.usage.total_tokens
                _publish_run_event(run_id, "turn", {"turn": turn + 1, "phase": "completed", "finish_reason": completion.choices[0].finish_reason})
                if not msg.tool_calls:
                    answer = msg.content or "Done."
                    if invoke_scope is not None and answer:
                        try:
                            invoke_scope.record_output_messages([answer])  # type: ignore[attr-defined]
                        except Exception:
                            pass
                    stats["duration"] = round(time.time() - stats["start_time"], 2)
                    _publish_run_event(run_id, "result", {"content": answer})
                    _publish_run_event(run_id, "stats", stats)
                    _publish_run_event(run_id, "done", {})
                    return answer
                messages.append(msg)  # type: ignore[arg-type]
                for tc in msg.tool_calls:
                    if tc.type != "function":
                        continue
                    fn = tc.function
                    srv, tool_name = fn.name.split("__", 1)
                    args = json.loads(fn.arguments)
                    stats["tool_calls"] += 1
                    _publish_run_event(run_id, "tool_call", {
                        "id": tc.id,
                        "server": srv,
                        "tool": tool_name,
                        "arguments": args,
                        "index": stats["tool_calls"],
                    })
                    started_ms = now_ms()
                    with _telemetry.span("agent.tool", server=srv, tool=tool_name):
                        result_str = await _call_tool_safe(srv, tool_name, args)
                    policy_attrs: dict[str, object] = {}
                    policy_action = ""
                    decision = _telemetry.apply_purview_policy(content=result_str)
                    if decision is not None:
                        result_str = decision.content
                        policy_attrs = decision.telemetry_attributes()
                        policy_action = decision.action
                    observed_event = _telemetry.observe_tool_call(
                        ObservedToolCall(
                            call_id=tc.id,
                            server=srv,
                            tool=tool_name,
                            arguments=args,
                            result=result_str,
                            duration_ms=now_ms() - started_ms,
                            success=not result_str.startswith("Error:"),
                            error=result_str if result_str.startswith("Error:") else "",
                            policy_attributes=policy_attrs,
                            policy_action=policy_action,
                        )
                    )
                    _publish_run_event(run_id, "agent365_event", observed_event)
                    if policy_action and policy_action != "allow":
                        _publish_run_event(run_id, "policy_event", {
                            "tool_call_id": tc.id,
                            "server": srv,
                            "tool": tool_name,
                            "action": policy_action,
                            "label_name": policy_attrs.get("microsoft.purview.sensitivity_label_name"),
                            "label_id": policy_attrs.get("microsoft.purview.sensitivity_label_id"),
                            "reason": policy_attrs.get("agent.tool_result.policy_reason"),
                        })
                    _publish_run_event(run_id, "agent_event", {
                        "event": "agent.tool",
                        "timestamp": time.time(),
                        "attributes": {
                            "server": srv,
                            "tool": tool_name,
                            "call_id": tc.id,
                            "success": not result_str.startswith("Error:"),
                            "duration_ms": now_ms() - started_ms,
                        },
                    })
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str[:4000]})
                    _publish_run_event(run_id, "tool_result", {
                        "id": tc.id,
                        "server": srv,
                        "tool": tool_name,
                        "result": result_str[:4000],
                    })
    except Exception as exc:
        _publish_run_event(run_id, "error", {"message": f"Agent error: {exc}"})
        _publish_run_event(run_id, "done", {})
        raise
    answer = "I reached the Teams turn limit before a final answer was produced."
    stats["duration"] = round(time.time() - stats["start_time"], 2)
    _publish_run_event(run_id, "result", {"content": answer})
    _publish_run_event(run_id, "stats", stats)
    _publish_run_event(run_id, "done", {})
    return answer


def _build_agent_app() -> Any | None:
    """Construct the Microsoft 365 Agents SDK AgentApplication.

    Follows the Agent 365 canonical pattern: a single SERVICE_CONNECTION wired to
    the agent identity blueprint app credentials lets the adapter accept inbound
    activities for any derived per-user agent identity instance, and an AGENTIC
    AgenticUserAuthorization handler exchanges the inbound JWT for downstream
    Graph/MCP tokens scoped to the calling agent identity.

    Required env vars (canonical schema, see Agent365-Samples Python sample):
      CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID    = <blueprint app id>
      CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTSECRET= <blueprint secret>
      CONNECTIONS__SERVICE_CONNECTION__SETTINGS__TENANTID    = <tenant id>
      CONNECTIONS__SERVICE_CONNECTION__SETTINGS__SCOPES      = https://api.botframework.com/.default
      AGENTAPPLICATION__USERAUTHORIZATION__HANDLERS__AGENTIC__SETTINGS__TYPE=AgenticUserAuthorization
      AGENTAPPLICATION__USERAUTHORIZATION__HANDLERS__AGENTIC__SETTINGS__SCOPES=https://graph.microsoft.com/.default
      CONNECTIONSMAP_0_SERVICEURL=*
      CONNECTIONSMAP_0_CONNECTION=SERVICE_CONNECTION
      AUTH_HANDLER_NAME=AGENTIC
    """
    global _agent_app, _cloud_adapter, _connection_manager, _auth_handler_name

    if not _AGENTS_SDK_AVAILABLE:
        print("  \u26a0\ufe0f  microsoft-agents-* packages not installed; /api/messages will return 503")
        return None

    if not os.getenv("CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID"):
        print("  \u26a0\ufe0f  Agents SDK env vars not configured; /api/messages will return 503")
        return None

    agents_sdk_config = load_configuration_from_env(os.environ)
    global _agents_sdk_config
    _agents_sdk_config = agents_sdk_config
    storage = MemoryStorage()
    _connection_manager = MsalConnectionManager(**agents_sdk_config)
    _cloud_adapter = CloudAdapter(connection_manager=_connection_manager)
    # Now that the SDK is loaded, rehydrate any persisted conversation refs
    # so HITL/proactive messaging survives container restarts.
    try:
        _hydrate_conversation_refs_from_disk()
    except Exception as exc:  # pragma: no cover - defensive
        _logger.warning("hydrate_conversation_refs_from_disk failed: %s", exc)
    authorization = Authorization(storage, _connection_manager, **agents_sdk_config)
    _agent_app = AgentApplication[TurnState](
        storage=storage,
        adapter=_cloud_adapter,
        authorization=authorization,
        **agents_sdk_config,
    )
    _auth_handler_name = os.getenv("AUTH_HANDLER_NAME", "AGENTIC") or None
    handler_config: dict[str, Any] = (
        {"auth_handlers": [_auth_handler_name]} if _auth_handler_name else {}
    )

    async def _safe_send(context: Any, payload: Any) -> None:
        try:
            await context.send_activity(payload)
        except Exception as exc:  # pragma: no cover - downstream channel error
            _logger.error("send_activity failed: %s", exc)

    def _capture_conversation_reference(context: Any) -> None:
        """Persist the inbound conversation so we can proactively reply later.

        We index the reference under *every* identifier we can extract from
        the activity (AAD object id, Teams user id, sender UPN) because the
        upstream caller invoking `_proactive_send_to_user` may know the user
        by any of those. Without this, an HITL request whose `manager_id` is
        an AAD GUID silently fails to match a reference captured only under
        a Teams user id like `8:orgid:<uuid>` and the proactive delivery is
        skipped entirely.
        """
        try:
            activity = context.activity
            from_prop = getattr(activity, "from_property", None)
            recipient = getattr(activity, "recipient", None)
            aad_id = (getattr(from_prop, "aad_object_id", "") if from_prop else "") or ""
            user_id = (getattr(from_prop, "id", "") if from_prop else "") or ""
            user_name = (getattr(from_prop, "name", "") if from_prop else "") or ""
            keys = {k for k in (aad_id, user_id) if k}
            if not keys:
                return
            ref = TurnContext.get_conversation_reference(activity)
            ref_dict = conversation_reference_to_dict(ref)
            extra = {
                "user_aad_object_id": aad_id,
                "user_id": user_id,
                "user_name": user_name,
                "agentic_app_id": getattr(recipient, "agentic_app_id", "") if recipient else "",
                "agentic_app_name": getattr(recipient, "name", "") if recipient else "",
                "tenant_id": getattr(recipient, "tenant_id", "") if recipient else "",
                "channel_id": getattr(activity, "channel_id", ""),
            }
            for key in keys:
                _conversation_refs[key] = ref
                _conversation_ref_store.upsert(key, ref_dict, extra=extra)
        except Exception as exc:  # pragma: no cover - defensive
            _logger.debug("capture_conversation_reference failed: %s", exc)

    @_agent_app.activity("installationUpdate")
    async def on_installation_update(context: Any, _state: Any) -> None:
        _capture_conversation_reference(context)
        action = (getattr(context.activity, "action", "") or "").lower()
        if action == "add":
            await _safe_send(
                context,
                _render_skills_list(
                    intro="Hi, I am the **ESS Workday/ServiceNow hosted agent**. "
                          "I can run autonomous cross-system tasks against Workday and ServiceNow.",
                ),
            )
        elif action == "remove":
            await _safe_send(context, "Thanks for the time \u2014 goodbye for now.")

    @_agent_app.conversation_update("membersAdded", **handler_config)
    async def on_members_added(context: Any, _state: Any) -> None:
        _capture_conversation_reference(context)
        recipient_id = getattr(getattr(context.activity, "recipient", None), "id", "")
        for member in getattr(context.activity, "members_added", None) or []:
            if getattr(member, "id", "") != recipient_id:
                await _safe_send(
                    context,
                    _render_skills_list(
                        intro="Hi, I am the **ESS Workday/ServiceNow hosted agent**. "
                              "I can run autonomous cross-system tasks against Workday and ServiceNow.",
                    ),
                )

    @_agent_app.activity("message", **handler_config)
    async def on_message(context: Any, _state: Any) -> None:
        _capture_conversation_reference(context)
        recipient = getattr(context.activity, "recipient", None)
        from_prop = getattr(context.activity, "from_property", None)
        actor = {
            "name": getattr(from_prop, "name", "") if from_prop else "",
            "id": getattr(from_prop, "id", "") if from_prop else "",
            "aadObjectId": getattr(from_prop, "aad_object_id", "") if from_prop else "",
            "channelId": getattr(context.activity, "channel_id", ""),
            "conversationId": getattr(getattr(context.activity, "conversation", None), "id", ""),
            "agenticAppId": getattr(recipient, "agentic_app_id", "") if recipient else "",
            "agenticAppName": getattr(recipient, "name", "") if recipient else "",
            "tenantId": getattr(recipient, "tenant_id", "") if recipient else "",
        }
        prompt = (getattr(context.activity, "text", "") or "").strip()
        sender_aad = actor.get("aadObjectId") or ""

        # If the inbound is an Adaptive Card Action.Submit from a HITL card,
        # `activity.value` carries the submit data and `activity.text` is
        # typically empty. Detect the card payload and resolve the pending
        # HITL request before any other routing.
        submit_value = getattr(context.activity, "value", None)
        if isinstance(submit_value, dict) and submit_value.get("hitlAction"):
            action = str(submit_value.get("hitlAction") or "").strip().lower()
            comment = str(submit_value.get("comment") or "").strip()
            req_id = str(submit_value.get("requestId") or "").strip()
            reply_text = action.capitalize() if action else "Acknowledged"
            if comment:
                reply_text = f"{reply_text}: {comment}"
            resolved_req = None
            if req_id and hasattr(_hitl, "resolve_by_request_id"):
                try:
                    resolved_req = await _hitl.resolve_by_request_id(req_id, reply_text)
                except Exception as exc:  # noqa: BLE001
                    _logger.warning("hitl.resolve_by_request_id raised: %s", exc)
            if resolved_req is None and sender_aad:
                resolved_req = await _hitl.resolve(sender_aad, reply_text)
            if resolved_req is not None:
                emoji = "\u2705" if action == "approve" else (
                    "\u274c" if action == "reject" else "\u2714\ufe0f"
                )
                ack = f"{emoji} **{action.capitalize() or 'Recorded'}** \u2014 the agent is continuing the run."
                if comment:
                    ack += f"\n\n_Your note:_ {comment}"
                await _safe_send(context, ack)
            else:
                await _safe_send(
                    context,
                    "\u26a0\ufe0f Could not match that response to a pending request \u2014 the run may have already moved on or timed out.",
                )
            return

        if not prompt:
            return

        # If this user has a pending human-in-the-loop request, treat the
        # message as a reply and resume the suspended run instead of starting
        # a brand new task.
        if sender_aad and _hitl.has_pending(sender_aad):
            req = await _hitl.resolve(sender_aad, prompt)
            if req is not None:
                await _safe_send(
                    context,
                    f"✅ Got it — the agent is continuing the run "
                    f"(`{req.request_id[:8]}`).",
                )
                return

        # `/wiq test` — exercise the real proactive Bot Framework HITL path.
        #
        # When `_call_human_tool` (synthetic `ask_manager`) fires during a run,
        # the first delivery attempt is `_proactive_send_to_user` which calls
        # `cloud_adapter.continue_conversation` against the manager's cached
        # conversation reference. That mints an `APX_PRODUCTION_SCOPE`
        # (Messaging Bot API) token for the teammate's agentic user and posts
        # an out-of-turn 1:1 message *from the teammate*. The legacy probe
        # that used to live here bypassed the SDK and posted as the primary
        # agent identity in a separate chat — useful when the SDK reply path
        # was broken, but not a real test of the production HITL path.
        if prompt.strip().lower().startswith("/wiq test"):
            extra = prompt.strip()[len("/wiq test"):].strip().strip("-—– ").strip()
            await _safe_send(
                context,
                "🔬 Probing the proactive Bot Framework HITL path "
                "(`cloud_adapter.continue_conversation` → "
                "`APX_PRODUCTION_SCOPE`/Messaging Bot API)…",
            )

            if not sender_aad:
                await _safe_send(
                    context,
                    "❌ Cannot resolve your AAD object id from the activity — the probe "
                    "needs `from_property.aad_object_id`. Try from a Teams 1:1 chat.",
                )
                return

            ref_present = sender_aad in _conversation_refs
            await _safe_send(
                context,
                f"Conversation reference cached for sender: `{ref_present}` "
                f"(known refs: `{len(_conversation_refs)}`).",
            )
            if not ref_present:
                await _safe_send(
                    context,
                    "❌ No conversation reference cached for you yet. Send any plain "
                    "message first so `_capture_conversation_reference` fires, then "
                    "retry `/wiq test`.",
                )
                return

            probe_text = (
                f"🤖 **HITL probe** — simulated `ask_manager` from "
                f"**{actor.get('name') or 'this teammate'}**.\n\n"
                "> Pretend this is a request that needs your approval to proceed.\n\n"
                "This message was delivered via the proactive Bot Framework path "
                "(`cloud_adapter.continue_conversation`), i.e. exactly the route "
                "`_call_human_tool` takes when an autonomous run pauses for HITL."
            )
            if extra:
                probe_text += f"\n\n_Extra:_ {extra}"

            delivery = await _proactive_send_to_user(sender_aad, probe_text)
            status = delivery.get("status", "?")
            reason = delivery.get("reason", "")
            channel = delivery.get("channel", "")
            if status == "sent":
                await _safe_send(
                    context,
                    f"✅ Proactive HITL delivery succeeded via `{channel or 'teams-bot'}`. "
                    "You should see a second message from this teammate appear in this "
                    "chat (out-of-turn). When a real run calls `ask_manager`, that is "
                    "exactly what you will see — no more email fallback.",
                )
            else:
                await _safe_send(
                    context,
                    f"❌ Proactive HITL delivery `{status}` — `{reason or 'unknown'}`. "
                    "Check container logs for the `_proactive_send_to_user` line; if "
                    "the SDK raised on token acquisition the AllPrincipals grant for "
                    "Messaging Bot API (`5a807f24-…`) may not have propagated yet.",
                )
            return

        # Lightweight intent classification so simple greetings / help requests
        # don't kick off an LLM run or emit the chatty "running the agent now"
        # preamble.
        intent = _classify_message(prompt)
        actor_name = actor.get("name") or "there"
        if intent == "greeting":
            await _safe_send(
                context,
                f"Hi {actor_name}! Type **help** to see my skills, or send a "
                "Workday/ServiceNow task and I'll get to work.",
            )
            return
        if intent == "help":
            await _safe_send(context, _render_skills_list())
            return

        # Real task: discrete acknowledgement before the long-running LLM/MCP work.
        # NOTE: streaming is buffered into a single Teams message for agentic
        # identities, so we use multiple send_activity calls for progress.
        await _safe_send(
            context,
            "Running the Workday/ServiceNow hosted agent now. "
            "You can watch it in the control plane.",
        )
        await _safe_send(context, Activity(type=ActivityTypes.typing))

        async def _typing_loop() -> None:
            try:
                while True:
                    await asyncio.sleep(4)
                    await _safe_send(context, Activity(type=ActivityTypes.typing))
            except asyncio.CancelledError:  # pragma: no cover - cancel on completion
                pass

        typing_task = asyncio.create_task(_typing_loop())
        try:
            answer = await run_text_task(prompt, source="teams-chat", actor=actor)
        except Exception as exc:
            answer = f"Agent error: {exc}"
        finally:
            typing_task.cancel()
            try:
                await typing_task
            except asyncio.CancelledError:
                pass
        await _safe_send(context, answer)

    print("  \u2705 bot: Agents SDK AgentApplication wired at /api/messages (handler=%s)"
          % (_auth_handler_name or "none",))
    return _agent_app


async def handle_bot_messages(request: web.Request) -> web.Response:
    if _agent_app is None or _cloud_adapter is None or start_agent_process is None:
        return web.json_response(
            {"error": "Agents SDK is not installed or not configured."},
            status=503,
        )

    # Log a compact summary of every inbound activity for diagnostic purposes.
    # We previously had a `/wiq test` pre-flight short-circuit here that
    # bypassed the SDK entirely (because per-user teammate instances 500'd on
    # AADSTS65001 when minting `APX_PRODUCTION_SCOPE`). The platform-side fix
    # — adding an AllPrincipals oauth2PermissionGrant for resource
    # `5a807f24-c9de-44ee-a3a7-329e88a00ffc` (Messaging Bot API) with scopes
    # `Authorization.ReadWrite user_impersonation` on each teammate SP —
    # restored the SDK reply path, so we now let `/wiq test` flow through to
    # the bot handler where it exercises the real proactive Bot Framework
    # HITL path instead.
    try:
        body_bytes = await request.read()  # cached by aiohttp; SDK can re-read
        body = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
    except Exception:  # noqa: BLE001
        body = {}
    raw_text = (body.get("text") or "")
    stripped_text = re.sub(r"<at>.*?</at>", "", raw_text, flags=re.IGNORECASE).strip()
    recipient_obj = body.get("recipient") or {}
    from_obj = body.get("from") or {}
    _logger.info(
        "bot.in activity type=%s recipient=%s/%s from=%s text=%r",
        body.get("type"),
        recipient_obj.get("id"),
        recipient_obj.get("name"),
        from_obj.get("aadObjectId"),
        stripped_text[:200],
    )

    # The SDK calls `_get_agentic_token` to authenticate the outbound reply
    # through api.botframework.com. For per-user teammate apps that lack
    # explicit oauth2PermissionGrants (the M365 admin UI does not propagate
    # the blueprint's inheritablePermissions to per-user instances), this
    # fails with AADSTS65001 and the SDK raises ValueError("Failed to
    # obtain token for agentic activity"), 500ing the inbound POST. As a
    # stopgap we catch that specific exception and email the user a reply
    # via the primary agent identity (see _graph_chat_fallback_reply).
    try:
        return await start_agent_process(request, _agent_app, _cloud_adapter)
    except ValueError as exc:
        msg = str(exc)
        if "Failed to obtain token for agentic activity" not in msg:
            raise
        _logger.warning(
            "bot.in falling back to Graph email reply (SDK agentic token failure): %s",
            msg,
        )
        return await _graph_chat_fallback_reply(body, stripped_text)


async def _wiq_test_via_graph_chat(activity: dict[str, Any], extra: str) -> web.Response:
    """Run the `/wiq test` probe entirely via Microsoft Graph.

    Avoids the Bot Framework reply path (which 500s on per-user teammate
    instances due to the AADSTS65001 platform bug). The probe still verifies
    exactly what we care about: that the sidecar mints a Graph token AS the
    primary agent identity user and we can use it to drive `/chats` +
    `/chats/{id}/messages`. The user sees a brand-new 1:1 chat appear from
    "ESS Workday ServiceNow Hosted Demo Agent" instead of a reply inside the
    HR AI Teammate chat — that is expected and demonstrates the working path.
    """
    import base64 as _b64

    def _decode_jwt(tok: str) -> dict[str, Any]:
        try:
            parts = tok.split(".")
            if len(parts) < 2:
                return {}
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            return json.loads(_b64.urlsafe_b64decode(payload).decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    from_obj = activity.get("from") or {}
    recipient_obj = activity.get("recipient") or {}
    sender_aad = from_obj.get("aadObjectId") or ""
    sender_name = from_obj.get("name") or "you"
    teammate_name = recipient_obj.get("name") or ""
    teammate_app_id = recipient_obj.get("agenticAppId") or recipient_obj.get("id") or ""

    notes: list[str] = []
    notes.append(
        f"<p><strong>/wiq test</strong> probe (intercepted before SDK pre-flight to dodge "
        f"AADSTS65001 on per-instance app <code>{html_module.escape(teammate_app_id)}</code>).</p>"
    )
    notes.append(
        f"<p>Sender: <code>{html_module.escape(sender_name)}</code> "
        f"(<code>{html_module.escape(sender_aad)}</code>)<br/>"
        f"Teammate (recipient): <code>{html_module.escape(teammate_name)}</code></p>"
    )

    if not sender_aad:
        return web.json_response(
            {"ok": False, "reason": "activity.from.aadObjectId missing"}, status=200
        )

    # 1) Acquire Graph token via the Entra agent-identity sidecar.
    try:
        agent_token = await _graph_chat._agent_identity_graph_token()
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"ok": False, "reason": f"sidecar raised {type(exc).__name__}: {exc}"},
            status=200,
        )
    if not agent_token:
        return web.json_response(
            {"ok": False, "reason": "sidecar returned no Graph token"}, status=200
        )

    claims = _decode_jwt(agent_token)
    notes.append(
        f"<p>Sidecar token (<code>{len(agent_token)}</code> chars): "
        f"appid=<code>{html_module.escape(str(claims.get('appid') or claims.get('azp') or '—'))}</code>, "
        f"oid=<code>{html_module.escape(str(claims.get('oid') or '—'))}</code>, "
        f"aud=<code>{html_module.escape(str(claims.get('aud') or '—'))}</code>, "
        f"scp=<code>{html_module.escape(str(claims.get('scp') or claims.get('roles') or '—'))}</code></p>"
    )

    # 2) Resolve the agent identity user id (from = primary agent identity).
    agent_user_id = (
        os.getenv("ENTRA_AGENT_IDENTITY_OBJECT_ID")
        or str(claims.get("oid") or "")
    )
    if not agent_user_id:
        return web.json_response(
            {"ok": False, "reason": "ENTRA_AGENT_IDENTITY_OBJECT_ID unset and no oid claim"},
            status=200,
        )

    # 3) Ensure a 1:1 chat between the agent identity and the sender.
    _graph_chat.last_token_source = ""
    chat_id: str | None = None
    try:
        chat_id = await _graph_chat.ensure_one_on_one_chat(agent_user_id, sender_aad)
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"ok": False, "reason": f"ensure_one_on_one_chat raised {type(exc).__name__}: {exc}"},
            status=200,
        )
    if not chat_id:
        return web.json_response(
            {
                "ok": False,
                "reason": "Graph chat creation failed",
                "tokenSource": _graph_chat.last_token_source or "<unknown>",
            },
            status=200,
        )

    notes.append(
        f"<p>Chat: <code>{html_module.escape(chat_id)}</code> "
        f"(token source: <code>{_graph_chat.last_token_source}</code>)</p>"
    )
    if extra:
        notes.append(f"<p><em>{html_module.escape(extra)}</em></p>")

    msg_html = "".join(notes)
    ok, reason = await _graph_chat.post_chat_message(chat_id, msg_html)

    return web.json_response(
        {
            "ok": ok,
            "reason": reason,
            "chatId": chat_id,
            "tokenSource": _graph_chat.last_token_source,
            "agentUserId": agent_user_id,
            "recipientAad": sender_aad,
            "teammateAppId": teammate_app_id,
        },
        status=200,
    )


async def _graph_chat_fallback_reply(activity: dict[str, Any], user_text: str) -> web.Response:
    """Reply to a per-user-teammate message via Microsoft Graph.

    Used when ``start_agent_process`` raises the AADSTS65001 / consent_required
    ``ValueError`` (which it does for every per-user teammate instance until
    the Microsoft platform consent bug is resolved). Without this fallback the
    user gets no reply at all, just a 500.

    Delivery strategy (mirrors HITL): try Teams 1:1 chat from the primary
    agent identity → fall back to mail-as-agent → fall back to mail-as-self.
    Today only the email paths work because the agent-identity sidecar that
    would mint a delegated token is not configured on this container
    (``ENTRA_AGENT_ID_SDK_TOKEN_URL`` unset), so chat creation via host MI
    app-only token returns 403 / not allowed. The user gets an email instead.
    """
    if _graph_chat is None or not _graph_chat.available:
        _logger.warning("bot.in fallback abort: graph-chat sidecar unavailable")
        return web.json_response(
            {"ok": False, "reason": "graph-chat sidecar unavailable for fallback"},
            status=200,
        )

    from_obj = activity.get("from") or {}
    recipient_obj = activity.get("recipient") or {}
    sender_aad = from_obj.get("aadObjectId") or ""
    sender_name = from_obj.get("name") or "you"
    teammate_name = recipient_obj.get("name") or ""
    teammate_app_id = recipient_obj.get("agenticAppId") or recipient_obj.get("id") or ""
    # Bot Framework activities from per-user teammates often carry recipient.name=None
    # and recipient.id="8:orgid:<agenticUserId>". Resolve a friendly name AND the
    # teammate's agentic-user identity (object id + UPN) via the instance directory.
    # The agentic user IS a real Entra user with a mailbox (e.g.
    # hraiteammate-sivav2@…); sending mail-as-that-user makes the email arrive
    # from the teammate (matching the working HITL email pattern) instead of
    # falling through to mail-as-self where the sender shows as the recipient.
    teammate_user_id = ""
    teammate_user_upn = ""
    recipient_id = (recipient_obj.get("id") or "").lower()
    agentic_user_id_from_recipient = (
        recipient_id.split(":orgid:")[-1] if ":orgid:" in recipient_id else ""
    )
    try:
        for inst in await _instance_directory.list_instances():
            if (
                (inst.instance_app_id and teammate_app_id and inst.instance_app_id.lower() == teammate_app_id.lower())
                or (inst.user_id and agentic_user_id_from_recipient and inst.user_id.lower() == agentic_user_id_from_recipient)
            ):
                teammate_name = teammate_name or inst.display_name or ""
                if not teammate_app_id:
                    teammate_app_id = inst.instance_app_id or ""
                teammate_user_id = inst.user_id or ""
                teammate_user_upn = inst.user_upn or ""
                break
    except Exception as exc:  # noqa: BLE001
        _logger.warning("bot.in fallback teammate lookup raised %s: %s", type(exc).__name__, exc)
    if not teammate_user_id and agentic_user_id_from_recipient:
        teammate_user_id = agentic_user_id_from_recipient
    if not teammate_name:
        teammate_name = "AI Teammate"

    if not sender_aad:
        _logger.warning("bot.in fallback abort: missing from.aadObjectId")
        return web.json_response(
            {"ok": False, "reason": "fallback: missing from.aadObjectId"},
            status=200,
        )

    # Look up the sender's UPN/mail via Graph so we can email them.
    sender_upn = ""
    sender_email = ""
    try:
        status, body = await _graph_chat._request("GET", f"/users/{sender_aad}")
        if status == 200 and isinstance(body, dict):
            sender_upn = body.get("userPrincipalName") or ""
            sender_email = body.get("mail") or sender_upn
    except Exception as exc:  # noqa: BLE001
        _logger.warning("bot.in fallback Graph /users lookup raised %s: %s", type(exc).__name__, exc)

    safe_text = html_module.escape(user_text or "(empty message)")
    safe_teammate = html_module.escape(teammate_name)
    safe_sender = html_module.escape(sender_name)
    html = (
        f"<p>Hi {safe_sender} — I'm <strong>{safe_teammate}</strong> and I received your message:</p>"
        f"<blockquote>{safe_text}</blockquote>"
        f"<p>I'm replying by email because my Teams 1:1 chat reply path is "
        f"currently blocked by an Entra consent issue on my per-user app. "
        f"You can keep driving the demo from the control plane in the meantime.</p>"
    )
    subject = f"[{teammate_name}] Re: your message"

    _logger.info(
        "bot.in fallback delivering teammate_user=%s teammate_upn=%s sender_aad=%s sender_email=%s teammate=%s",
        teammate_user_id, teammate_user_upn, sender_aad, sender_email, teammate_app_id,
    )
    # Pass the TEAMMATE's agentic user as the sender (agent_user_id) so the
    # email arrives from e.g. hraiteammate-sivav2@…, matching the prior
    # working HITL email pattern. The primary agent identity (ed4046aa-…) is
    # a ServiceIdentity SP with no mailbox so /users/{id}/sendMail 404s.
    result = await _graph_chat.deliver_hitl(
        agent_user_id=teammate_user_id,
        agent_user_upn=teammate_user_upn,
        manager_aad_id=sender_aad,
        manager_upn=sender_upn,
        manager_email=sender_email,
        subject=subject,
        html=html,
    )
    _logger.info("bot.in fallback delivery result=%s", result)

    return web.json_response(
        {
            "ok": result.get("status") == "sent",
            "delivery": result,
            "recipientAad": sender_aad,
            "recipientEmail": sender_email,
            "teammateAppId": teammate_app_id,
            "fallback": True,
        },
        status=200,
    )


@web.middleware
async def _scoped_jwt_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    """Apply Agents SDK JWT validation only to the bot messages endpoint.

    Everything else (control plane UI, /api/runs, /api/skills, health probes)
    must remain reachable without a Bot Framework JWT.
    """
    if jwt_authorization_middleware is None or request.path != "/api/messages" or request.method != "POST":
        return await handler(request)
    return await jwt_authorization_middleware(request, handler)


# ── Static file serving ────────────────────────────────────────────


async def handle_index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC_DIR / "index.html")


async def handle_control_plane(request: web.Request) -> web.FileResponse:
    """Serve the control plane UI."""
    return web.FileResponse(
        STATIC_DIR / "control-plane.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


# ── AI Teammate instance directory + proactive Teams delivery ───────


def _build_hitl_adaptive_card(
    *,
    asker_name: str,
    question: str,
    extra_context: str,
    request_id: str,
    run_id: str,
    form_url: str = "",
) -> dict[str, Any]:
    """Build an Adaptive Card for an HITL approval request.

    The card has Approve / Reject Action.Submit buttons plus an optional
    multiline comment field. When the manager submits, Teams sends a
    ``message`` activity back to the bot with ``activity.value`` populated
    with ``{hitlAction, comment, requestId}``. The bot's on_message handler
    looks for that shape and resolves the pending HITL request accordingly.
    """
    body: list[dict[str, Any]] = [
        {
            "type": "TextBlock",
            "text": f"\U0001f916 {asker_name} needs your input",
            "weight": "Bolder",
            "size": "Medium",
            "wrap": True,
        },
        {
            "type": "TextBlock",
            "text": question or "(no question text)",
            "wrap": True,
            "spacing": "Small",
        },
    ]
    if extra_context:
        body.append(
            {
                "type": "TextBlock",
                "text": f"_Context:_ {extra_context}",
                "wrap": True,
                "isSubtle": True,
                "spacing": "Small",
            }
        )
    body.append(
        {
            "type": "Input.Text",
            "id": "comment",
            "placeholder": "Optional notes or guidance for the agent\u2026",
            "isMultiline": True,
        }
    )
    meta_text = f"Run `{run_id or 'n/a'}` \u00b7 request `{(request_id or '')[:8]}`"
    if form_url:
        meta_text += f"  \u00b7  [Open web form]({form_url})"
    body.append(
        {
            "type": "TextBlock",
            "text": meta_text,
            "wrap": True,
            "isSubtle": True,
            "size": "Small",
            "spacing": "Small",
        }
    )
    data_common = {"requestId": request_id, "runId": run_id}
    return {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": body,
        "actions": [
            {
                "type": "Action.Submit",
                "title": "Approve",
                "style": "positive",
                "data": {**data_common, "hitlAction": "approve"},
            },
            {
                "type": "Action.Submit",
                "title": "Reject",
                "style": "destructive",
                "data": {**data_common, "hitlAction": "reject"},
            },
        ],
    }


async def _proactive_send_to_user(
    aad_object_id: str,
    text: str = "",
    *,
    card: dict[str, Any] | None = None,
    summary_text: str = "",
) -> dict[str, Any]:
    """Push a Teams message (text or Adaptive Card) using a stored ConversationReference."""
    if not aad_object_id:
        _logger.warning("_proactive_send_to_user called with empty aad_object_id")
        return {"status": "no_reference", "reason": "missing aad_object_id"}
    if _cloud_adapter is None:
        _logger.warning("_proactive_send_to_user: cloud adapter not configured")
        return {"status": "disabled", "reason": "agents SDK adapter not configured"}

    # Lookup chain:
    #   1. Direct key match in the in-memory dict.
    #   2. Case-insensitive key match.
    #   3. Scan the persisted store for any record whose ``user_aad_object_id``
    #      matches — covers the case where the inbound activity captured the
    #      reference under a Teams user id like ``8:orgid:<guid>`` but the
    #      caller (e.g. `_call_human_tool`) knows the manager only by AAD
    #      object id. Without this, HITL silently falls through to email.
    ref = _conversation_refs.get(aad_object_id)
    matched_key = aad_object_id if ref is not None else ""
    if ref is None:
        target = aad_object_id.lower()
        for k, v in _conversation_refs.items():
            if k.lower() == target:
                ref = v
                matched_key = k
                break
    if ref is None:
        try:
            store_all = _conversation_ref_store.all()
        except Exception:  # noqa: BLE001
            store_all = {}
        for key, record in store_all.items():
            stored_aad = (record.get("user_aad_object_id") or "").lower()
            if stored_aad and stored_aad == aad_object_id.lower():
                hydrated = conversation_reference_from_dict(record.get("reference") or {})
                if hydrated is not None:
                    ref = hydrated
                    matched_key = key
                    # Re-cache under both the requested AAD and the original key.
                    _conversation_refs[aad_object_id] = ref
                    _conversation_refs[key] = ref
                    break
    _logger.info(
        "_proactive_send_to_user aad=%s ref_found=%s matched_key=%s known_refs=%d kind=%s",
        aad_object_id,
        ref is not None,
        matched_key,
        len(_conversation_refs),
        "card" if card else "text",
    )
    if ref is None:
        return {
            "status": "no_reference",
            "reason": (
                "user has not interacted with the bot yet (no conversation reference "
                f"captured for aad={aad_object_id}; known keys={list(_conversation_refs.keys())[:5]})"
            ),
        }

    async def _callback(turn_context: Any) -> None:
        try:
            if card is not None and Activity is not None:
                # Build the attachment as an explicit Attachment model when the
                # SDK class is importable so Pydantic serialization is bypassed
                # for any dict-coercion edge case. Falls back to a plain dict
                # (which the SDK normally accepts via field aliasing).
                attachment_payload: Any
                try:
                    from microsoft_agents.activity import Attachment as _Attachment  # type: ignore
                    attachment_payload = _Attachment(
                        content_type="application/vnd.microsoft.card.adaptive",
                        content=card,
                    )
                except Exception:  # noqa: BLE001
                    attachment_payload = {
                        "content_type": "application/vnd.microsoft.card.adaptive",
                        "content": card,
                    }
                payload = Activity(
                    type=ActivityTypes.message if ActivityTypes is not None else "message",
                    text=summary_text or None,
                    attachments=[attachment_payload],
                )
                _logger.info(
                    "_proactive_send_to_user sending card payload (summary=%r attachments=1)",
                    summary_text,
                )
                await turn_context.send_activity(payload)
            else:
                _logger.info(
                    "_proactive_send_to_user sending text payload (len=%d)", len(text)
                )
                await turn_context.send_activity(text)
        except Exception as cb_exc:  # noqa: BLE001 - surface inner failure
            _logger.exception("_proactive_send_to_user callback raised: %s", cb_exc)
            raise

    try:
        await _cloud_adapter.continue_conversation(reference=ref, callback=_callback)
        return {"status": "sent", "channel": "teams-bot-card" if card else "teams-bot"}
    except TypeError:
        try:
            await _cloud_adapter.continue_conversation(ref, _callback)
            return {"status": "sent", "channel": "teams-bot-card" if card else "teams-bot"}
        except Exception as exc:
            return {"status": "error", "reason": str(exc)}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


async def _deliver_run_to_manager(
    instance: AgenticInstance, run_id: str, scenario: str, answer: str
) -> dict[str, Any]:
    """Send the run output to the instance user's manager via Microsoft Graph.

    Primary path: 1:1 Teams chat from the primary agent-identity user to the
    manager (same path HITL uses). Falls back to Graph email if the chat
    cannot be created. The legacy Bot Framework proactive path is no longer
    used here — it required the manager to have installed the bot first,
    which produced the misleading "manager has not installed the bot yet"
    note on the AI Teammate instance cards.
    """
    title = scenario or "Scenario run"
    safe_title = html_module.escape(title)
    safe_name = html_module.escape(instance.display_name)
    safe_answer = html_module.escape((answer or "(no output)").strip()).replace("\n", "<br/>")
    safe_run = html_module.escape(run_id or "")
    body_html = (
        f"<p>\u2705 <strong>{safe_name}</strong> finished <strong>{safe_title}</strong>.</p>"
        f"<blockquote>{safe_answer}</blockquote>"
        f"<p>Run id: <code>{safe_run}</code></p>"
    )
    record: dict[str, Any] = {
        "instance_id": instance.instance_id,
        "instance_name": instance.display_name,
        "run_id": run_id,
        "scenario": scenario,
        "channel": "graph-chat",
        "manager": {
            "id": instance.manager_id,
            "name": instance.manager_display_name,
            "email": instance.manager_email,
            "upn": instance.manager_upn,
        },
        "user": {
            "id": instance.user_id,
            "name": instance.user_display_name,
            "upn": instance.user_upn,
        },
    }
    if not (instance.manager_id or instance.manager_email or instance.manager_upn):
        record["status"] = "no_recipients"
        record["reason"] = "instance has no resolved manager"
        return record
    if _graph_chat is None or not getattr(_graph_chat, "available", False):
        record["status"] = "disabled"
        record["channel"] = "none"
        record["reason"] = "Microsoft Graph delivery not configured"
        return record
    # PRIMARY path: post AS the per-user teammate user via the Agents SDK
    # federated user_fic flow. This is the same path HITL uses and is the
    # only one that gets past the Teams roster check (the Entra Agent ID SP
    # is not a Teams-licensed user, so it can't be a 1:1 roster member).
    if (
        _connection_manager is not None
        and instance.instance_app_id
        and instance.user_id
        and instance.manager_id
    ):
        tenant_id = os.getenv("AZURE_TENANT_ID", "") or getattr(
            _runtime_context, "tenant_id", ""
        )
        delivery = await _graph_chat.deliver_hitl_as_agentic_user(
            connection_manager=_connection_manager,
            tenant_id=tenant_id,
            instance_app_id=instance.instance_app_id,
            agentic_user_id=instance.user_id,
            manager_user_id=instance.manager_id,
            html=body_html,
        )
        if delivery.get("status") == "sent":
            record.update(delivery)
            record["status"] = "sent"
            record["channel"] = delivery.get("channel") or "teams-chat-agentic-user"
            record["delivered_to"] = "manager"
            return record
        _logger.warning(
            "scenario delivery (agentic-user) failed instance=%s reason=%s; falling back",
            instance.instance_app_id, delivery.get("reason"),
        )
    # FALLBACK path (legacy): app-only / agent-identity sidecar token. Kept
    # so dev/test environments without the SDK connection manager still emit
    # a delivery record, even if it cannot post a 1:1 message in production.
    primary_agent_oid = (
        os.getenv("ENTRA_AGENT_IDENTITY_OBJECT_ID")
        or os.getenv("AGENT_IDENTITY_OBJECT_ID")
        or instance.user_id
    )
    primary_agent_upn = (
        os.getenv("ENTRA_AGENT_IDENTITY_UPN")
        or os.getenv("AGENT_IDENTITY_UPN")
        or instance.user_upn
    )
    delivery = await _graph_chat.deliver_hitl(
        agent_user_id=primary_agent_oid,
        agent_user_upn=primary_agent_upn,
        manager_aad_id=instance.manager_id,
        manager_upn=instance.manager_upn,
        manager_email=instance.manager_email or instance.manager_upn,
        subject=f"[{instance.display_name}] {title}",
        html=body_html,
    )
    record.update(delivery)
    record.setdefault("status", delivery.get("status", "unknown"))
    if delivery.get("status") == "sent":
        record["channel"] = delivery.get("channel") or "graph-chat"
        record["delivered_to"] = "manager"
    return record


async def handle_agentic_instances(request: web.Request) -> web.Response:
    force = request.query.get("refresh", "").lower() in {"1", "true", "yes"}
    instances = await _instance_directory.list_instances(force_refresh=force)
    # HITL delivery now flows through Microsoft Graph (1:1 chat via the
    # agent-identity sidecar, with Graph Mail.Send as the email fallback).
    # The legacy Bot Framework proactive path required the manager to have
    # installed the bot first — we no longer rely on it, so the readiness
    # signal is just "can we reach the manager via Graph at all?".
    graph_chat_ok = _graph_chat is not None
    bot_ready = _cloud_adapter is not None
    result = []
    for inst in instances:
        d = inst.to_dict()
        # Primary: 1:1 Graph chat from the agent-identity user to the manager.
        # Requires the manager's AAD object id. Falls back to Graph email if
        # only an SMTP address is known.
        if graph_chat_ok and inst.manager_id:
            channel = "graph-chat"
            ready = True
        elif graph_chat_ok and inst.manager_email:
            channel = "email"
            ready = True
        else:
            channel = "none"
            ready = False
        manager_installed = bool(inst.manager_id and inst.manager_id in _conversation_refs)
        d["notificationChannel"] = channel
        d["notificationReady"] = ready
        d["managerHasInstalledBot"] = manager_installed  # legacy; informational only
        d["botProactiveReady"] = bool(bot_ready and manager_installed)
        d["hitlSupported"] = ready
        result.append(d)
    return web.json_response({
        "prefix": _instance_directory.prefix,
        "count": len(instances),
        "instances": result,
        "pendingHitl": _hitl.snapshot(),
        "generatedAt": int(time.time() * 1000),
    })


async def handle_agentic_instance_run(request: web.Request) -> web.Response:
    instance_id = request.match_info.get("instance_id", "")
    instance = await _instance_directory.get_instance(instance_id)
    if instance is None:
        return web.json_response({"error": f"Unknown instance {instance_id}"}, status=404)
    payload: dict[str, Any] = {}
    if request.body_exists:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
    scenario = (payload.get("scenario") or payload.get("skill") or "").strip()
    prompt = (payload.get("prompt") or scenario or "").strip()
    if not prompt:
        return web.json_response({"error": "Provide `scenario` or `prompt`."}, status=400)

    # Control-plane kill switch: if a compliance officer has isolated this
    # agent identity instance, refuse to start any run and record the
    # attempt in the governance audit ledger.
    kill = governance_state.is_instance_disabled(instance_id)
    if kill.blocked:
        governance_state.record_run_blocked(
            instance_id=instance_id,
            decision=kill,
            actor="control-plane",
            scenario=scenario,
        )
        return web.json_response(
            {
                "error": "instance_disabled",
                "reason": kill.reason,
                "instanceId": instance_id,
            },
            status=423,  # Locked
        )

    # Purview / DSPM-for-AI "User participant" column resolves the
    # `user_id` to a recognised M365 user. The per-teammate synthetic UPN
    # (hraiteammate-sivav2@…) is a ServiceIdentity, so Activity Explorer
    # collapses it to "Guest". Use the MANAGER (the human who installed
    # this teammate) as the user participant — the agentic teammate is
    # still attributed in the AgentDetails via agenticAppClientId/Name.
    manager_upn = (instance.manager_upn or instance.manager_email or "").strip()
    manager_id = (instance.manager_id or "").strip()
    manager_name = (instance.manager_display_name or "").strip()
    if manager_upn:
        user_upn = manager_upn
        user_aad = manager_id
        user_display = manager_name or manager_upn
    else:
        user_upn = (instance.user_upn or "").strip()
        user_aad = (instance.user_aad_object_id or "").strip()
        user_display = (instance.user_display_name or instance.display_name or "").strip()

    actor = {
        "name": user_display or instance.display_name,
        "id": user_aad or instance.instance_id,
        "aadObjectId": user_aad,
        "upn": user_upn,
        "channelId": "agentic-instance",
        "agenticAppId": instance.instance_id,
        "agenticAppClientId": instance.instance_app_id,
        "agenticAppName": instance.display_name,
        # Keep the agentic-user attribution side-by-side for the run
        # ledger and any auditor that wants to see the synthetic identity
        # that actually executed the request.
        "agenticUserUpn": instance.user_upn,
        "agenticUserId": instance.user_aad_object_id,
        "agenticUserName": instance.user_display_name,
        "tenantId": _runtime_context.tenant_id,
        "managerId": instance.manager_id,
        "managerName": instance.manager_display_name,
        "managerEmail": instance.manager_email,
        "managerUpn": instance.manager_upn,
    }
    run_started_at = int(time.time() * 1000)

    async def _runner() -> None:
        try:
            answer = await run_text_task(prompt, source="instance-launch", actor=actor)
        except Exception as exc:
            _logger.exception("instance run failed: %s", exc)
            answer = f"Run error: {exc}"
        target_run_id = ""
        for rid in reversed(_run_order):
            run = _run_ledger.get(rid)
            if (
                run
                and run.get("startedAt", 0) >= run_started_at
                and run.get("agenticUser", {}).get("id") == instance.instance_id
            ):
                target_run_id = rid
                break
        delivery = await _deliver_run_to_manager(instance, target_run_id, scenario, answer)
        if target_run_id:
            run = _run_ledger.get(target_run_id)
            if run is not None:
                run["delivery"] = delivery
                _publish_run_event(target_run_id, "delivery", delivery)

    asyncio.create_task(_runner())
    return web.json_response({
        "status": "accepted",
        "instance": instance.to_dict(),
        "scenario": scenario,
        "prompt": prompt,
    }, status=202)


async def handle_privacy(request: web.Request) -> web.Response:
    return web.Response(
        text=(
            "ESS Hosted Agent uses tenant-configured Workday and ServiceNow MCP tools, "
            "AI Gateway routing, and Entra Agent ID metadata for governance and audit correlation."
        ),
        content_type="text/plain",
    )


async def handle_terms(request: web.Request) -> web.Response:
    return web.Response(
        text="Use of this demo agent is limited to the configured demo tenant and approved test data.",
        content_type="text/plain",
    )


async def handle_diag_purview_labels(request: web.Request) -> web.Response:
    """Diagnostic: report the live Purview sensitivity-label catalogue.

    Returns the cached catalogue, the source (graph/heuristic), the last
    Graph fetch error (if any), and the current cache age. Pass
    ``?refresh=1`` to bust the cache and re-fetch from Microsoft Graph
    before returning. Used to verify that a tenant's real IP policy is
    being picked up by the agent's managed identity.
    """
    refresh = request.query.get("refresh", "").lower() in ("1", "true", "yes")
    info: dict[str, object] = {
        "purview_enabled": os.getenv("PURVIEW_ENABLED", "").lower() in ("1", "true", "yes"),
        "graph_token_source": os.getenv("PURVIEW_GRAPH_TOKEN_SOURCE", "managed_identity"),
        "azure_client_id": os.getenv("AZURE_CLIENT_ID", ""),
        "graph_endpoint": "https://graph.microsoft.com/v1.0/security/informationProtection/sensitivityLabels",
    }
    client = getattr(_telemetry, "purview_client", None)
    if client is None:
        info["error"] = "Purview client not configured (PURVIEW_ENABLED not true or module load failed)"
        return web.json_response(info, status=200)
    try:
        labels = client.reload() if refresh else client._labels()  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        info["error"] = f"label fetch raised: {exc}"
        info["last_graph_error"] = getattr(client, "last_graph_error", None)
        return web.json_response(info, status=200)
    info["last_graph_error"] = getattr(client, "last_graph_error", None)
    info["last_graph_endpoint"] = getattr(client, "last_graph_endpoint", None)
    info["cached_at"] = getattr(client, "cached_at", 0.0)
    info["label_count"] = len(labels)
    info["any_graph_sourced"] = any(getattr(l, "source", "") == "graph" for l in labels)
    info["using_heuristic_fallback"] = not info["any_graph_sourced"]
    info["labels"] = [
        {
            "id": l.id,
            "name": l.name,
            "priority": l.priority,
            "color": l.color,
            "source": l.source,
        }
        for l in labels
    ]
    # Surface which policy rules would match each Graph label so the operator
    # can see if the tenant's real labels are wired into purview-policy.yaml.
    policy = getattr(_telemetry, "purview_policy", None)
    if policy is not None:
        rule_hits: list[dict[str, object]] = []
        for l in labels:
            try:
                decision = policy.evaluate(label=l, content="sample content")
                rule_hits.append({"label": l.name, "action": decision.action, "reason": decision.reason})
            except Exception:
                rule_hits.append({"label": l.name, "action": "?", "reason": "policy eval failed"})
        info["policy_match_preview"] = rule_hits
    return web.json_response(info, status=200)


async def handle_diag_agent_graph_token(request: web.Request) -> web.Response:
    """Mint a Graph token via the agent-identity sidecar and decode its claims.

    Used to verify the Entra auth-sidecar is wired correctly. Surface key
    JWT claims (aud, appid, oid, idtyp, scp, roles) without leaking the
    token itself unless ``?reveal=1`` is supplied.

    Query parameters:
      - ``api`` (default ``graph``) — downstream API name in the sidecar.
      - ``agent_user`` — if set, sidecar is called with ``AgentUser=<oid>``
        instead of (or alongside) ``AgentIdentity`` to attempt a per-user
        teammate user token.
      - ``instance_id`` — optional ``AgentInstance`` query param for the
        sidecar (the per-user teammate's instance app ID).
      - ``raw=1`` — bypass the graph_chat helper and probe the sidecar
        directly using these params (returns the sidecar response body).
      - ``reveal=1`` — include the raw bearer in the response.
    """
    import base64 as _b64

    def _decode(tok: str) -> dict[str, Any]:
        try:
            parts = tok.split(".")
            if len(parts) < 2:
                return {}
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            return json.loads(_b64.urlsafe_b64decode(payload).decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    # Raw sidecar probe mode — bypass graph_chat caching and surface whatever
    # the sidecar returns for arbitrary query params.
    if request.query.get("raw") == "1":
        import uuid as _uuid
        import urllib.parse as _urlp
        import httpx as _httpx

        sidecar_url = os.getenv("A365_SIDECAR_URL", "http://localhost:5000").rstrip("/")
        api = request.query.get("api", "graph")
        params: dict[str, str] = {
            "optionsOverride.AcquireTokenOptions.ForceRefresh": "true",
            "optionsOverride.AcquireTokenOptions.CorrelationId": str(_uuid.uuid4()),
        }
        agent_identity = request.query.get("agent_identity")
        if agent_identity:
            params["AgentIdentity"] = agent_identity
        agent_user = request.query.get("agent_user")
        if agent_user:
            params["AgentUser"] = agent_user
        instance_id = request.query.get("instance_id")
        if instance_id:
            params["AgentInstance"] = instance_id
        url = (
            f"{sidecar_url}/AuthorizationHeaderUnauthenticated/{api}"
            f"?{_urlp.urlencode(params)}"
        )
        try:
            async with _httpx.AsyncClient(timeout=15.0) as c:
                r = await c.get(url)
            body_text = r.text[:1200]
            body_json: Any = None
            try:
                body_json = r.json()
            except Exception:  # noqa: BLE001
                pass
            out: dict[str, Any] = {
                "ok": r.status_code == 200,
                "status": r.status_code,
                "url": url,
                "body": body_json if body_json is not None else body_text,
            }
            if body_json and isinstance(body_json, dict):
                header = body_json.get("authorizationHeader") or ""
                if header.lower().startswith("bearer "):
                    tok = header.split(" ", 1)[1]
                    out["claims"] = _decode(tok)
                    if request.query.get("reveal") == "1":
                        out["token"] = tok
            return web.json_response(out, status=200)
        except Exception as exc:  # noqa: BLE001
            return web.json_response(
                {"ok": False, "reason": f"{type(exc).__name__}: {exc}", "url": url},
                status=200,
            )

    if _graph_chat is None:
        return web.json_response({"ok": False, "reason": "graph_chat unavailable"}, status=200)
    try:
        token = await _graph_chat._agent_identity_graph_token()
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"ok": False, "reason": f"sidecar raised {type(exc).__name__}: {exc}"},
            status=200,
        )
    if not token:
        return web.json_response(
            {
                "ok": False,
                "reason": "sidecar returned no token (check A365_SIDECAR_URL, A365_SIDECAR_GRAPH_API, A365_AGENT_APP_ID)",
                "env": {
                    "A365_SIDECAR_URL": os.getenv("A365_SIDECAR_URL", ""),
                    "A365_SIDECAR_GRAPH_API": os.getenv("A365_SIDECAR_GRAPH_API", ""),
                    "A365_AGENT_APP_ID": os.getenv("A365_AGENT_APP_ID", ""),
                    "ENTRA_AGENT_IDENTITY_CLIENT_ID": os.getenv("ENTRA_AGENT_IDENTITY_CLIENT_ID", ""),
                },
            },
            status=200,
        )
    claims = _decode(token)
    keep = ("aud", "iss", "appid", "azp", "oid", "sub", "tid", "idtyp", "scp", "roles", "exp", "iat")
    out = {k: claims.get(k) for k in keep if k in claims}
    body: dict[str, Any] = {"ok": True, "claims": out, "tokenLen": len(token)}
    if request.query.get("reveal") == "1":
        body["token"] = token
    return web.json_response(body, status=200)


async def handle_diag_sdk_source(request: web.Request) -> web.Response:
    """Return the source of a Microsoft Agents SDK callable by dotted path.

    Example: ``?path=microsoft_agents.authentication.msal.msal_auth.MsalAuth.get_agentic_user_token``
    """
    import importlib
    import inspect as _inspect

    dotted = request.query.get("path", "")
    if not dotted:
        return web.json_response({"ok": False, "reason": "missing ?path"}, status=200)
    parts = dotted.split(".")
    # Walk from longest module prefix down.
    obj = None
    err: str = ""
    for split in range(len(parts) - 1, 0, -1):
        modpath = ".".join(parts[:split])
        try:
            mod = importlib.import_module(modpath)
        except Exception as exc:  # noqa: BLE001
            err = f"import {modpath}: {type(exc).__name__}: {exc}"
            continue
        obj = mod
        try:
            for attr in parts[split:]:
                obj = getattr(obj, attr)
            err = ""
            break
        except Exception as exc:  # noqa: BLE001
            err = f"resolve attr {attr}: {type(exc).__name__}: {exc}"
            obj = None
    if obj is None:
        return web.json_response({"ok": False, "reason": err}, status=200)
    try:
        src = _inspect.getsource(obj)
    except Exception as exc:  # noqa: BLE001
        try:
            members = [n for n in dir(obj) if not n.startswith("_")]
        except Exception:  # noqa: BLE001
            members = []
        return web.json_response(
            {"ok": False, "reason": f"getsource: {exc}", "members": members},
            status=200,
        )
    return web.Response(text=src, content_type="text/plain")


async def handle_diag_agent_user_token(request: web.Request) -> web.Response:
    """Mint a delegated Graph token AS a per-user teammate user.

    Uses the Microsoft Agents SDK's ``MsalAuth.get_agentic_user_token`` via the
    process-wide ``_connection_manager``. Query params:

      - ``instance_id`` (required) \u2014 per-user teammate's ``instance_app_id``.
      - ``user_id`` (required) \u2014 per-user teammate user's AAD object ID.
      - ``scope`` \u2014 single scope to request (default
        ``https://graph.microsoft.com/.default``). Multiple scopes can be
        comma-separated.
      - ``reveal=1`` to dump the raw token.
    """
    import base64 as _b64

    def _decode(tok: str) -> dict[str, Any]:
        try:
            parts = tok.split(".")
            if len(parts) < 2:
                return {}
            payload = parts[1] + "=" * (-len(parts[1]) % 4)
            return json.loads(_b64.urlsafe_b64decode(payload).decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    if _connection_manager is None:
        return web.json_response(
            {"ok": False, "reason": "_connection_manager unavailable"}, status=200
        )
    instance_id = request.query.get("instance_id", "").strip()
    user_id = request.query.get("user_id", "").strip()
    if not instance_id or not user_id:
        return web.json_response(
            {"ok": False, "reason": "instance_id and user_id required"}, status=200
        )
    scope_str = request.query.get("scope", "https://graph.microsoft.com/.default")
    scopes = [s.strip() for s in scope_str.split(",") if s.strip()]
    tenant_id = os.getenv("AZURE_TENANT_ID", "")
    try:
        conn = _connection_manager.get_default_connection()
        # MsalAuth.get_agentic_user_token
        token = await conn.get_agentic_user_token(
            tenant_id, instance_id, user_id, scopes
        )
    except Exception as exc:  # noqa: BLE001
        return web.json_response(
            {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}, status=200
        )
    if not token:
        return web.json_response(
            {"ok": False, "reason": "SDK returned no access_token"}, status=200
        )
    claims = _decode(token)
    keep = ("aud", "iss", "appid", "azp", "oid", "sub", "tid", "idtyp", "scp", "roles", "upn", "preferred_username", "name", "exp", "iat")
    body: dict[str, Any] = {
        "ok": True,
        "claims": {k: claims.get(k) for k in keep if k in claims},
        "tokenLen": len(token),
    }
    if request.query.get("reveal") == "1":
        body["token"] = token
    return web.json_response(body, status=200)


async def handle_diag_hitl_agentic_user(request: web.Request) -> web.Response:
    """Smoke test of the production HITL agentic-user delivery path.

    POST JSON body: ``{"instance_id": ..., "user_id": ..., "manager_id": ...,
    "html": "<p>...</p>"}``. Calls
    :func:`graph_chat.GraphChatClient.deliver_hitl_as_agentic_user` directly
    using the live ``_connection_manager`` and returns the result dict.
    """
    if _connection_manager is None:
        return web.json_response({"ok": False, "reason": "_connection_manager unavailable"})
    try:
        payload = await request.json()
    except Exception as exc:  # noqa: BLE001
        return web.json_response({"ok": False, "reason": f"json: {exc}"})
    instance_id = (payload.get("instance_id") or "").strip()
    user_id = (payload.get("user_id") or "").strip()
    manager_id = (payload.get("manager_id") or "").strip()
    html = payload.get("html") or "<p>HITL agentic-user smoke test.</p>"
    if not (instance_id and user_id and manager_id):
        return web.json_response(
            {"ok": False, "reason": "instance_id, user_id, manager_id required"}
        )
    tenant_id = os.getenv("AZURE_TENANT_ID", "")
    result = await _graph_chat.deliver_hitl_as_agentic_user(
        connection_manager=_connection_manager,
        tenant_id=tenant_id,
        instance_app_id=instance_id,
        agentic_user_id=user_id,
        manager_user_id=manager_id,
        html=html,
    )
    return web.json_response({"ok": result.get("status") == "sent", **result})


async def handle_hitl_form(request: web.Request) -> web.Response:
    """Render a tiny form so a manager can answer a HITL prompt from a link."""
    request_id = request.match_info.get("request_id", "")
    req_obj = _hitl.get(request_id)
    meta = _hitl_form_meta.get(request_id) or {}
    if req_obj is None:
        body = (
            "<!doctype html><html><body style='font-family:system-ui;padding:2rem'>"
            "<h2>This request is no longer pending</h2>"
            "<p>It may have already been answered, expired, or never existed.</p>"
            "</body></html>"
        )
        return web.Response(text=body, content_type="text/html", status=404)

    question = html_module.escape(meta.get("question") or req_obj.question)
    asker = html_module.escape(meta.get("askerName") or req_obj.asker_name or "the agent")
    context = html_module.escape(meta.get("context") or "")
    run_id = html_module.escape(meta.get("runId") or req_obj.run_id or "")
    short_id = html_module.escape(req_obj.request_id[:8])
    context_html = f"<p><em>Context:</em> {context}</p>" if context else ""
    body = f"""<!doctype html>
<html><head><meta charset='utf-8'><title>Human-in-the-loop reply</title>
<style>
  body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1.25rem; color:#1f2328; }}
  blockquote {{ border-left: 3px solid #6366f1; padding: 0.25rem 0.75rem; color:#374151; background:#f9fafb; }}
  textarea {{ width:100%; min-height:160px; font:inherit; padding:0.6rem; border:1px solid #d0d7de; border-radius:6px; }}
  button {{ margin-top:0.75rem; background:#6366f1; color:#fff; border:0; padding:0.6rem 1.1rem; border-radius:6px; font-weight:600; cursor:pointer; }}
  button:disabled {{ opacity:0.6; cursor:wait; }}
  .meta {{ color:#6b7280; font-size:0.85rem; margin-top:1.25rem; }}
</style></head>
<body>
  <h2>{asker} needs your input</h2>
  <blockquote>{question}</blockquote>
  {context_html}
  <form method='POST' action='/api/hitl/{request_id}/respond' onsubmit="this.querySelector('button').disabled=true;this.querySelector('button').textContent='Sending…';">
    <label for='reply'><strong>Your reply</strong></label>
    <textarea id='reply' name='reply' required autofocus></textarea>
    <button type='submit'>Send reply</button>
  </form>
  <p class='meta'>Run <code>{run_id or 'n/a'}</code> · request <code>{short_id}</code></p>
</body></html>"""
    return web.Response(text=body, content_type="text/html")


async def handle_hitl_respond(request: web.Request) -> web.Response:
    request_id = request.match_info.get("request_id", "")
    req_obj = _hitl.get(request_id)
    if req_obj is None:
        return web.Response(
            text="<!doctype html><body style='font-family:system-ui;padding:2rem'><h2>This request is no longer pending.</h2></body>",
            content_type="text/html",
            status=404,
        )
    reply_text = ""
    ct = (request.headers.get("content-type") or "").lower()
    if "application/json" in ct:
        try:
            payload = await request.json()
            reply_text = (payload.get("reply") or "").strip()
        except Exception:
            reply_text = ""
    else:
        form = await request.post()
        raw_reply = form.get("reply") or ""
        if isinstance(raw_reply, bytes):
            raw_reply = raw_reply.decode("utf-8", "replace")
        reply_text = str(raw_reply).strip()
    if not reply_text:
        return web.Response(text="reply is required", status=400)
    resolved = await _hitl.resolve_by_request_id(request_id, reply_text)
    if resolved is None:
        return web.Response(text="request already resolved", status=409)
    _hitl_form_meta.pop(request_id, None)
    if "application/json" in ct:
        return web.json_response({"status": "ok", "requestId": request_id})
    body = (
        "<!doctype html><html><body style='font-family:system-ui;padding:2rem;max-width:640px;margin:auto'>"
        "<h2>Thanks — your reply was sent.</h2>"
        f"<p>The agent will resume the run.</p></body></html>"
    )
    return web.Response(text=body, content_type="text/html")


# ── App setup ──────────────────────────────────────────────────────


def _governance_actor(request: web.Request) -> str:
    """Best-effort identification of the operator driving a governance action."""
    for header in ("x-ms-client-principal-name", "x-user-principal-name", "x-actor"):
        val = request.headers.get(header, "").strip()
        if val:
            return val
    return "control-plane"


async def handle_governance_get(request: web.Request) -> web.Response:
    snapshot = governance_state.snapshot()
    snapshot["audit"] = governance_state.audit_log(limit=50)
    return web.json_response(snapshot)


async def handle_governance_disable_instance(request: web.Request) -> web.Response:
    instance_id = request.match_info.get("instance_id", "")
    if not instance_id:
        return web.json_response({"error": "instance_id is required"}, status=400)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    reason = (payload.get("reason") or "Isolated by control plane operator").strip()
    actor = (payload.get("actor") or "").strip() or _governance_actor(request)
    event = governance_state.disable_instance(instance_id, reason=reason, actor=actor)
    return web.json_response({"status": "disabled", "event": event.to_dict()})


async def handle_governance_enable_instance(request: web.Request) -> web.Response:
    instance_id = request.match_info.get("instance_id", "")
    if not instance_id:
        return web.json_response({"error": "instance_id is required"}, status=400)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    actor = (payload.get("actor") or "").strip() or _governance_actor(request)
    event = governance_state.enable_instance(instance_id, actor=actor)
    if event is None:
        return web.json_response({"status": "not-disabled", "instanceId": instance_id})
    return web.json_response({"status": "enabled", "event": event.to_dict()})


async def handle_governance_set_denylist(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    raw_patterns = payload.get("patterns")
    if isinstance(raw_patterns, str):
        raw_patterns = [p.strip() for p in raw_patterns.split(",")]
    elif not isinstance(raw_patterns, list):
        return web.json_response({"error": "patterns must be a list"}, status=400)
    actor = (payload.get("actor") or "").strip() or _governance_actor(request)
    event = governance_state.set_tool_denylist([str(p) for p in raw_patterns], actor=actor)
    return web.json_response({
        "status": "ok",
        "patterns": governance_state.tool_denylist(),
        "event": event.to_dict(),
    })


async def handle_run_evidence(request: web.Request) -> web.Response:
    """Produce a single-file evidence pack for one run.

    The pack contains every input, every tool call, every Purview policy
    decision, every governance enforcement event for the relevant instance,
    and the agent identity / blueprint metadata in effect at execution time.
    It is the "evidence for investigations" deliverable: a compliance officer
    can download this JSON and reconstruct exactly what the agent did.
    """
    run_id = request.match_info.get("run_id", "")
    run = _run_ledger.get(run_id)
    if not run:
        return web.json_response({"error": f"Unknown run {run_id}"}, status=404)

    agentic_user = run.get("agenticUser") or {}
    instance_id = agentic_user.get("agenticAppId") or ""
    # Filter governance audit entries for this instance + run
    instance_audit = [
        entry for entry in governance_state.audit_log(limit=200)
        if entry.get("target") == instance_id
        or (entry.get("detail") or {}).get("runId") == run_id
    ]

    evidence = {
        "schema": "ess-agent365-run-evidence/1.0",
        "generatedAt": int(time.time() * 1000),
        "run": run,
        "agentIdentity": _public_identity_metadata(),
        "observability": observability_status(),
        "governance": {
            "snapshot": governance_state.snapshot(),
            "audit": instance_audit,
        },
        "policyEvents": [
            evt for evt in (run.get("loggedEvents") or [])
            if "policy" in json.dumps(evt, default=str).lower()
        ],
    }

    response = web.json_response(evidence)
    safe_id = re.sub(r"[^a-zA-Z0-9._-]", "_", run_id)
    response.headers["Content-Disposition"] = (
        f"attachment; filename=ess-evidence-{safe_id}.json"
    )
    return response


def create_app() -> web.Application:
    middlewares: list[Any] = []
    if _AGENTS_SDK_AVAILABLE and _agent_app is not None:
        middlewares.append(_scoped_jwt_middleware)
    app = web.Application(middlewares=middlewares)
    if _AGENTS_SDK_AVAILABLE and _agent_app is not None and AgentAuthConfiguration is not None and _agents_sdk_config is not None:
        # Required by jwt_authorization_middleware (reads request.app["agent_configuration"]).
        try:
            app["agent_configuration"] = AgentAuthConfiguration(**_agents_sdk_config)
        except Exception as _exc:
            _logger.error("failed to build AgentAuthConfiguration: %s", _exc)
    app.router.add_get("/", handle_index)
    app.router.add_get("/control-plane", handle_control_plane)
    app.router.add_get("/privacy", handle_privacy)
    app.router.add_get("/terms", handle_terms)
    app.router.add_get("/api/diag/agent-graph-token", handle_diag_agent_graph_token)
    app.router.add_get("/api/diag/sdk-source", handle_diag_sdk_source)
    app.router.add_get("/api/diag/agent-user-token", handle_diag_agent_user_token)
    app.router.add_post("/api/diag/hitl-agentic-user", handle_diag_hitl_agentic_user)
    app.router.add_get("/api/diag/purview-labels", handle_diag_purview_labels)
    app.router.add_get("/api/skills", handle_skills)
    app.router.add_get("/api/servers", handle_servers)
    app.router.add_get("/api/identity", handle_identity)
    app.router.add_get("/api/a365-value", handle_a365_value)
    app.router.add_get("/api/runs", handle_runs)
    app.router.add_post("/api/runs/reset", handle_runs_reset)
    app.router.add_post("/api/run", handle_run)
    app.router.add_get("/api/agentic-instances", handle_agentic_instances)
    app.router.add_post("/api/agentic-instances/{instance_id}/run", handle_agentic_instance_run)
    app.router.add_get("/api/governance", handle_governance_get)
    app.router.add_post("/api/governance/instance/{instance_id}/disable", handle_governance_disable_instance)
    app.router.add_post("/api/governance/instance/{instance_id}/enable", handle_governance_enable_instance)
    app.router.add_post("/api/governance/tool-denylist", handle_governance_set_denylist)
    app.router.add_get("/api/runs/{run_id}/evidence", handle_run_evidence)
    app.router.add_get("/api/hitl/{request_id}", handle_hitl_form)
    app.router.add_post("/api/hitl/{request_id}/respond", handle_hitl_respond)
    app.router.add_post("/api/messages", handle_bot_messages)

    async def _bot_messages_get(_r: web.Request) -> web.Response:
        return web.Response(status=200)
    app.router.add_get("/api/messages", _bot_messages_get)
    if _agent_app is not None:
        app["agent_app"] = _agent_app
        app["adapter"] = _cloud_adapter
    return app


async def _connect_with_retry(name: str, url: str, retries: int = 5, timeout: int = 45) -> None:
    """Try to connect to an MCP server with retries.

    The httpx transport already retries connection-level errors (retries=3),
    so each attempt here is already quite resilient.  The outer retry handles
    higher-level failures (session negotiation, timeouts).
    """
    for attempt in range(1, retries + 1):
        try:
            client, tools = await asyncio.wait_for(
                connect(name, url, _token_provider, _runtime_context), timeout=timeout
            )
            _servers[name] = client
            _all_tools.extend(tools)
            print(f"  ✅ {name}: {len(tools)} tools")
            return
        except asyncio.TimeoutError:
            print(f"  ⏳ {name}: attempt {attempt}/{retries} timed out ({timeout}s)")
        except Exception as exc:
            print(f"  ⏳ {name}: attempt {attempt}/{retries} failed ({exc})")
        if attempt < retries:
            await asyncio.sleep(3)
    print(f"  ❌ {name}: gave up after {retries} attempts")


async def init_mcp() -> None:
    """Connect to MCP servers sequentially (same-IP TLS contention with parallel)."""
    global _runtime_context, _token_provider, _telemetry
    load_dotenv()
    _runtime_context = AgentIdentityContext.from_env()
    _token_provider = EnvOrOAuthTokenProvider()
    _telemetry = AgentTelemetry(_runtime_context)
    _build_agent_app()
    for name in SERVER_NAMES:
        url = mcp_url_for(name, _runtime_context)
        if url:
            _server_configs[name] = url
            retries = int(os.getenv("ESS_MCP_CONNECT_RETRIES", "5"))
            timeout = int(os.getenv("ESS_MCP_CONNECT_TIMEOUT", "45"))
            await _connect_with_retry(name, url, retries=retries, timeout=timeout)

    if not _servers:
        print("⚠️  No MCP servers configured — will run in demo-only mode")
        print("   Set ESS_<SERVER>_AI_GATEWAY_MCP_URL or ESS_<SERVER>_MCP_URL in .env")


async def cleanup_mcp(app: web.Application) -> None:
    for c in _servers.values():
        await c.__aexit__(None, None, None)


def main() -> None:
    port = int(os.getenv("ESS_WEB_PORT", "8091"))
    host = os.getenv("ESS_WEB_HOST", "127.0.0.1")
    app = create_app()
    app.on_cleanup.append(cleanup_mcp)

    async def start():
        await init_mcp()
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        print()
        url = f"http://localhost:{port}"
        inner_w = max(len("ESS-MCP Demo Agent — Web UI"), len(f"→ {url}"), len("Press Ctrl+C to stop")) + 6

        def pad(s: str) -> str:
            return s + " " * (inner_w - len(s))
        print(f"  ╭{'─' * inner_w}╮")
        print(f"  │{' ' * inner_w}│")
        print(f"  │{pad('   ESS-MCP Demo Agent — Web UI')}│")
        print(f"  │{' ' * inner_w}│")
        print(f"  │{pad(f'   → {url}')}│")
        print(f"  │{' ' * inner_w}│")
        print(f"  │{pad('   Press Ctrl+C to stop')}│")
        print(f"  │{' ' * inner_w}│")
        print(f"  ╰{'─' * inner_w}╯")
        print()
        # Keep running
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            pass
        finally:
            await runner.cleanup()

    try:
        asyncio.run(start())
    except KeyboardInterrupt:
        print("\nShutting down.")


if __name__ == "__main__":
    main()
