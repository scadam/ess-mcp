"""SDK-only wiring for Group Functions Autopilot's scoped conversation service.

No clients, stores, credentials or jobs are created on import. The host constructs
this runtime after SDK/MCP initialization. Models may suggest tasks, but cannot
grant task permission, confirm effects, choose a reply endpoint or change scope.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator
from urllib.parse import urlsplit

from .conversation import ConversationService, _activity_text, _field, _group, _invocation, _RUN_INSTRUCTIONS
from .conversation_memory import ChatScope, Store, claim_activity, create_conversation_store
from .copilot_harness import parse_json_reply
from .teams_format import is_structured, summary, to_card
from .tool_approvals import ToolApprovalGate, tool_call_digest

DISPLAY_NAME = "Group Functions Autopilot"
CURRENT_CHAT_SCOPE: ContextVar[ChatScope | None] = ContextVar("autopilot_chat_scope", default=None)
APPROVED_TOOL_DIGEST: ContextVar[str | None] = ContextVar("autopilot_approved_tool_digest", default=None)
CURRENT_SCOPE_GENERATION: ContextVar[int | None] = ContextVar("autopilot_scope_generation", default=None)
_APPROVAL_COMMAND = re.compile(r"(?:approve|reject) [0-9a-fA-F]{12}")
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_YES = re.compile(r"(?:yes|yep|yeah|sure|ok|okay|approved?|go ahead|do it|go for it|please do|sounds good)"
                  r"(?:[,.!]*\s*(?:please|thanks|thank you))?[.!]*", re.IGNORECASE)
_NO = re.compile(r"(?:no|nope|don['’]?t|do not|reject(?:ed)?|cancel|stop|hold off)"
                 r"(?:[,.!]*\s*(?:thanks|thank you))?[.!]*", re.IGNORECASE)


def _natural_decision(text: str) -> str | None:
    """A bare yes/no answers the single waiting approval; anything longer is a normal message."""
    value = text.strip()
    if _YES.fullmatch(value):
        return "approve"
    if _NO.fullmatch(value):
        return "reject"
    return None


def guid(value: Any) -> str:
    if not isinstance(value, str) or _GUID.fullmatch(value) is None or not uuid.UUID(value).int:
        raise ValueError("A configured nonzero GUID is required.")
    return str(uuid.UUID(value))


def configured_tenant() -> str:
    return guid(os.environ.get("AZURE_TENANT_ID", "").strip())


def configured_app_id() -> str:
    return guid((os.environ.get("CONNECTIONS__SERVICE_CONNECTION__SETTINGS__CLIENTID")
                 or os.environ.get("ENTRA_AGENT_BLUEPRINT_CLIENT_ID") or "").strip())


def max_tasks() -> int:
    try:
        value = int(os.environ.get("AUTOPILOT_MAX_TASKS", "4"))
    except ValueError:
        raise ValueError("AUTOPILOT_MAX_TASKS must be an integer from 1 to 20.") from None
    if not 1 <= value <= 20:
        raise ValueError("AUTOPILOT_MAX_TASKS must be an integer from 1 to 20.")
    return value


def _task_users() -> frozenset[str]:
    return frozenset(
        guid(item)
        for name in ("AUTOPILOT_TASK_USER_IDS", "AUTOPILOT_OPERATOR_IDS")
        for item in re.split(r"[,;\s]+", os.environ.get(name, "").strip()) if item
    )


class ServiceUrlPolicy:
    """Public Teams endpoints only; an optional exact-host list can only narrow it."""

    _SUFFIXES = ("botframework.com", "teams.microsoft.com")
    _SMBA = "smba.trafficmanager.net"

    def __init__(self) -> None:
        raw = os.environ.get("AUTOPILOT_SERVICE_URL_HOSTS", "").strip()
        self._exact: frozenset[str] | None = None
        if raw:
            hosts = [item.strip().lower() for item in raw.split(",")]
            if any(not self._public_host(host) for host in hosts):
                raise ValueError("Service URL configuration must contain exact public Teams hostnames.")
            self._exact = frozenset(hosts)

    @classmethod
    def _public_host(cls, host: str) -> bool:
        if re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", host) is None:
            return False
        # trafficmanager.net is shared infrastructure, NOT a trusted suffix.
        return host == cls._SMBA or any(host == suffix or host.endswith("." + suffix) for suffix in cls._SUFFIXES)

    def is_allowed(self, value: Any) -> bool:
        if not isinstance(value, str) or len(value) > 2048 or not value.isascii():
            return False
        if any(character.isspace() for character in value) or "\\" in value:
            return False
        try:
            uri = urlsplit(value)
            host = (uri.hostname or "").lower()
            return bool(
                uri.scheme == "https" and uri.port in (None, 443)
                and uri.username is None and uri.password is None and not uri.query and not uri.fragment
                and self._public_host(host) and (self._exact is None or host in self._exact)
            )
        except ValueError:
            return False

    def validate(self, value: Any) -> None:
        if not self.is_allowed(value):
            raise ValueError("The SDK service URL is not an approved HTTPS Teams endpoint.")


def build_outbound_validator() -> Any:
    """Keep the SDK's outbound check enabled, including HTTPS/port restrictions."""
    from microsoft_agents.hosting.core import OutboundHostValidator

    policy = ServiceUrlPolicy()

    class TeamsHostValidator(OutboundHostValidator):
        def __init__(self) -> None:
            super().__init__(enabled=True, include_default_microsoft_hosts=False)

        def is_allowed(self, url: Any) -> bool:
            return policy.is_allowed(str(url))

    return TeamsHostValidator()


def activity_scope(activity: Any) -> ChatScope:
    scope = ConversationService.scope_from_activity(activity, configured_tenant(), configured_app_id())
    channel = _field(activity, "channel_id", "channelId")
    if getattr(channel, "value", channel) != "msteams":
        raise ValueError("Only configured-tenant Teams activities are accepted.")
    ServiceUrlPolicy().validate(_field(activity, "service_url", "serviceUrl"))
    return scope


def notification_scope(activity: Any) -> ChatScope:
    """Agent 365 notifications are tenant-scoped; the host never replies to their service URL."""
    channel = _field(activity, "channel_id", "channelId")
    if str(getattr(channel, "channel", channel) or "").split(":", 1)[0] != "agents":
        raise ValueError("Only configured-tenant Agent 365 notifications are accepted.")
    return ConversationService.scope_from_activity(activity, configured_tenant(), configured_app_id())


def teams_message(payload: Any) -> Any:
    """Structured Markdown goes to Teams as an Adaptive Card (bot text shows headings and tables literally)."""
    if not isinstance(payload, str) or not is_structured(payload):
        return payload
    from microsoft_agents.activity import Activity, ActivityTypes, Attachment

    return Activity(type=ActivityTypes.message, summary=summary(payload) or None, attachments=[
        Attachment(content_type="application/vnd.microsoft.card.adaptive", content=to_card(payload))])


def sdk_actor(activity: Any, scope: ChatScope) -> dict[str, Any]:
    """Project only authenticated SDK routing/sender fields, never activity.value."""
    source = _field(activity, "from_property", "from", "from_")
    recipient = _field(activity, "recipient")
    aad = _field(source, "aad_object_id", "aadObjectId")
    sender = _field(source, "id") or ""
    if not isinstance(sender, str) or not sender or not sender.isprintable() or len(sender) > 512:
        raise ValueError("A verified SDK sender is required.")
    app_id = _field(recipient, "agentic_app_id", "agenticAppId")
    user_id = _field(recipient, "agentic_user_id", "agenticUserId")
    return {
        "id": sender, "aadObjectId": guid(aad) if aad else "",
        "name": _field(source, "name") or sender,
        "tenantId": scope.tenant_id, "conversationId": scope.conversation_id,
        "agentId": scope.agent_id, "channelId": "msteams",
        "agenticAppId": guid(app_id) if app_id else "",
        "agenticAppClientId": guid(app_id) if app_id else "",
        "agenticUserId": guid(user_id) if user_id else "",
        "agenticAppName": _field(recipient, "name") or DISPLAY_NAME,
    }


def task_prompt_data(prompt: str) -> tuple[str, dict[str, Any] | None]:
    """Read the service envelope to select a skill without dropping its memory.

    This is parsing, never authentication. The entire envelope remains a user
    message; even a user who copies its syntax gains no instruction priority.
    """
    if prompt.startswith(_RUN_INSTRUCTIONS):
        try:
            data = json.loads(prompt[len(_RUN_INSTRUCTIONS):])
            original = data["originalRequest"]["text"]
            if type(data) is dict and isinstance(original, str) and original.strip():
                return original, data
        except (ValueError, TypeError, KeyError):
            pass
        raise ValueError("Invalid conversation task envelope.")
    return prompt, None


class AutopilotRuntime:
    def __init__(self, host: Any, store: Store) -> None:
        self.host = host
        self.store = store
        self.tenant = configured_tenant()
        self.app_id = configured_app_id()
        self.policy = ServiceUrlPolicy()
        self.users = _task_users()
        self.limit = max_tasks()
        self.closing = False
        self._generations: dict[ChatScope, int] = {}
        self._decisions: set[asyncio.Task[Any]] = set()
        self._decision_scopes: dict[asyncio.Task[Any], ChatScope] = {}
        self.gate = ToolApprovalGate(store, self._execute_approved)
        self.service = ConversationService(
            store, self.plan, self.run, self.send, self.summarize, max_tasks=self.limit,
        )

    def authorized(self, actor: dict[str, Any]) -> bool:
        try:
            return guid(actor.get("aadObjectId")) in self.users and guid(actor.get("tenantId")) == self.tenant
        except ValueError:
            return False

    @contextmanager
    def scope_context(self, scope: ChatScope) -> Iterator[None]:
        if scope.tenant_id != self.tenant or self.closing:
            raise PermissionError("This conversation is unavailable.")
        scope_token = CURRENT_CHAT_SCOPE.set(scope)
        generation_token = CURRENT_SCOPE_GENERATION.set(self._generations.get(scope, 0))
        try:
            yield
        finally:
            CURRENT_SCOPE_GENERATION.reset(generation_token)
            CURRENT_CHAT_SCOPE.reset(scope_token)

    async def ensure_effect_scope(self, scope: ChatScope, actor: dict[str, Any], source: str) -> None:
        if source == "case-desk":
            # The desk's authority is its operator-configured binding, scoped to one case (or its own sweep).
            if (self.closing or scope.tenant_id != self.tenant or actor.get("caseDesk") is not True
                    or not scope.conversation_id.startswith("case:")
                    or actor.get("conversationId") != scope.conversation_id or actor.get("agentId") != scope.agent_id
                    or self.host._desk is None):
                raise PermissionError("The case desk no longer has a valid scope for this case.")
            task = asyncio.current_task()
            if task is not None and task.cancelling():
                raise asyncio.CancelledError
            return
        if (source not in {"teams-chat", "control-plane", "instance-launch"}
            or self.closing or scope.tenant_id != self.tenant or not self.authorized(actor)
                or actor.get("conversationId") != scope.conversation_id
                or actor.get("agentId") != scope.agent_id):
            raise PermissionError("The task no longer has a valid authorized chat scope.")
        task = asyncio.current_task()
        if task is not None and task.cancelling():
            raise asyncio.CancelledError
        if source == "teams-chat":
            generation = CURRENT_SCOPE_GENERATION.get()
            if generation is None or generation != self._generations.get(scope, 0):
                raise PermissionError("The conversation has been invalidated.")
            state = await self.store.read(scope)
            if (not state["active"] or state["tasks"].get("__conversation_service__", {}).get("removed")
                    or generation != self._generations.get(scope, 0) or self.closing):
                raise PermissionError("The conversation is no longer active.")

    def _colleague_name(self) -> str:
        """Name from the verified chat scope's instance, never from message text."""
        scope = CURRENT_CHAT_SCOPE.get()
        if scope is None:
            return DISPLAY_NAME
        try:
            name = self.host._colleague_name_for(scope.agent_id)
        except Exception:
            return DISPLAY_NAME
        return name if isinstance(name, str) and name else DISPLAY_NAME

    async def plan(self, messages: list[dict[str, str]], allow_tasks: bool) -> dict[str, Any]:
        scope = CURRENT_CHAT_SCOPE.get()
        if scope is not None:
            await self.host._refresh_colleagues(scope.agent_id)
        skills = [
            {"name": slug, "title": self.host._skill_title(slug), "description": self.host._skill_description(slug)}
            for slug in self.host._list_skill_slugs()
        ]
        name = self._colleague_name()
        persona = name if name == DISPLAY_NAME else f"{name}, an instance of {DISPLAY_NAME}"
        policy = (
            f"You are {persona}, an AI teammate, never a human. Be brief unless asked for detail. "
            "Respond with only a JSON object with mode 'reply' or 'task', text, optional task, optional skill and "
            "optional delegated. "
            "You have no tools here. Do not claim any work or human confirmation happened. Current user intent, "
            "not old memory, determines a task; use the conversation only to understand what the user refers to. "
            "The following allow_tasks boolean is external permission, not user data: "
            f"{json.dumps(bool(allow_tasks))}. When false, never choose task. "
            "When a task clearly matches one of these existing workflows, set skill to its name; otherwise omit it. "
            "Offer them naturally when relevant; do not display a menu: "
            + json.dumps(skills, ensure_ascii=False)
        )
        text = await asyncio.wait_for(self.host._answer([{"role": "system", "content": policy}, *messages]), timeout=40)
        result = parse_json_reply(text)
        if type(result) is not dict or result.get("mode") not in {"reply", "task"}:
            raise ValueError("Invalid planner response.")
        if result["mode"] == "task" and not allow_tasks:
            return {"mode": "reply", "text": "I can discuss this, but an authorized operator must request the task."}
        return result

    async def summarize(self, messages: list[dict[str, str]]) -> str:
        return await asyncio.wait_for(self.host._answer(messages, timeout=30), timeout=30)

    def reference(self, data: dict[str, Any], expected: ChatScope | None = None) -> tuple[Any, ChatScope]:
        from microsoft_agents.activity import ConversationReference

        if type(data) is not dict:
            raise ValueError("An SDK conversation reference is required.")
        data = copy.deepcopy(data)
        for aliases in (("bot", "agent"), ("serviceUrl", "service_url"), ("channelId", "channel_id")):
            values = [data[key] for key in aliases if data.get(key) is not None]
            if len(values) > 1 and values[0] != values[1]:
                raise ValueError("Conflicting SDK conversation reference fields.")
        agent = data.get("bot") or data.get("agent") or {}
        conversation = data.get("conversation") or {}
        if type(agent) is not dict or type(conversation) is not dict or type(data.get("user", {})) is not dict:
            raise ValueError("Conversation reference accounts must be SDK dictionaries.")
        scope = ChatScope(self.tenant, agent.get("id", ""), conversation.get("id", ""))
        if expected is not None and scope != expected:
            raise ValueError("The reference does not belong to this conversation.")
        for account in (agent, conversation, data.get("user") or {}):
            for alias in ("tenantId", "tenant_id"):
                if account.get(alias) and guid(account[alias]) != self.tenant:
                    raise ValueError("A conversation reference crosses the configured tenant.")
        model = ConversationReference.model_validate(data)
        self.policy.validate(model.service_url)
        if getattr(model.channel_id, "value", model.channel_id) != "msteams":
            raise ValueError("Only a Teams conversation can be continued.")
        return model, scope

    async def send(self, reference: dict[str, Any], payload: Any) -> Any:
        """Continue the exact captured SDK reference, never a user-ID lookup."""
        if self.closing:
            raise RuntimeError("The conversation runtime is closing.")
        expected = CURRENT_CHAT_SCOPE.get()
        model, scope = self.reference(reference, expected)
        generation = self._generations.get(scope, 0)
        inherited_generation = CURRENT_SCOPE_GENERATION.get()
        if expected is not None and inherited_generation is not None and inherited_generation != generation:
            raise RuntimeError("The original conversation generation is no longer active.")
        responses: list[Any] = []

        async def require_active() -> None:
            state = await self.store.read(scope)
            if (self.closing or generation != self._generations.get(scope, 0) or not state["active"]
                    or state["tasks"].get("__conversation_service__", {}).get("removed")):
                raise RuntimeError("The conversation was removed or forgotten.")

        async def callback(context: Any) -> None:
            await require_active()
            watch = getattr(self.host, "_watch_outbound", None)
            if callable(watch):
                watch(context)  # Display-only narration of the proactive message.
            responses.append(await context.send_activity(teams_message(payload)))

        await require_active()
        # SDK 1.7: exactly (agent_app_id, continuation_activity, callback).
        await self.host._cloud_adapter.continue_conversation(
            self.app_id, model.get_continuation_activity(), callback,
        )
        return responses

    async def run(self, prompt: str, actor: dict[str, Any]) -> str:
        actor = copy.deepcopy(actor)
        scope = ChatScope(actor["tenantId"], actor["agentId"], actor["conversationId"])
        if CURRENT_CHAT_SCOPE.get() != scope:
            raise PermissionError("The admitted job lost its original chat scope.")
        await self.ensure_effect_scope(scope, actor, "teams-chat")
        with self.host._run_context(scope, actor, source="teams-chat", run_id=actor["runId"]):
            return await self.host.run_text_task(prompt, source="teams-chat", actor=actor)

    async def _execute_approved(self, server: str, tool: str, args: dict[str, Any], identity: dict[str, Any]) -> str:
        scope = CURRENT_CHAT_SCOPE.get()
        previous = self.host._current_run_ctx.get() or {}
        actor = copy.deepcopy(previous.get("actor") or {})
        if (scope is None or any(actor.get(key) != identity.get(key)
                                 for key in ("aadObjectId", "tenantId", "conversationId"))):
            raise PermissionError("An approval lost its verified requester scope.")
        digest = tool_call_digest(server, tool, args)
        source = previous.get("source") or "teams-chat"
        await self.ensure_effect_scope(scope, actor, source)
        origin = self.host._approval_origin(scope, identity, digest, previous.get("run_id"))
        run_id = origin["id"] if origin else ""
        call_id = "approved-" + uuid.uuid4().hex
        with self.host._run_context(scope, actor, source=source, run_id=run_id):
            token = APPROVED_TOOL_DIGEST.set(digest)
            started = self.host.now_ms()
            try:
                # No planner, retries, spawned work or further approval decisions.
                self.host._publish_run_event(run_id, "tool_call", {
                    "id": call_id, "server": server, "tool": tool, "arguments": args, "approved": True,
                })
                with self.host._telemetry.start_invoke_scope(
                    run_id=run_id or call_id, conversation_id=scope.conversation_id,
                    principal=self.host.RunPrincipal.from_actor(actor, source=source, tenant_id=scope.tenant_id),
                    prompt="Execute only the exact human-confirmed tool call.",
                ), self.host._telemetry.span("agent.tool.approved", server=server, tool=tool):
                    result = await self.host._call_tool_safe(server, tool, args)
                    decision = self.host._telemetry.apply_purview_policy(content=result)
                    result = decision.content if decision is not None else result
                    event = self.host._telemetry.observe_tool_call(self.host.ObservedToolCall(
                        call_id=call_id, server=server, tool=tool, arguments=args, result=result,
                        duration_ms=self.host.now_ms() - started, success=True,
                        policy_attributes=decision.telemetry_attributes() if decision is not None else {},
                        policy_action=decision.action if decision is not None else "",
                    ))
                self.host._publish_run_event(run_id, "agent365_event", event)
                self.host._publish_run_event(run_id, "tool_result", {
                    "id": call_id, "server": server, "tool": tool, "result": result,
                })
                return result
            except BaseException:
                event = self.host._telemetry.observe_tool_call(self.host.ObservedToolCall(
                    call_id=call_id, server=server, tool=tool, arguments=args, result="",
                    duration_ms=self.host.now_ms() - started, success=False,
                    error="The approved tool failed or its outcome is unknown.",
                ))
                self.host._publish_run_event(run_id, "agent365_event", event)
                raise
            finally:
                APPROVED_TOOL_DIGEST.reset(token)
                await asyncio.to_thread(self.host._telemetry.force_flush)

    async def _record_decision(self, scope: ChatScope, actor: dict[str, Any], text: str,
                               response: str | None, source: str, run_id: str) -> None:
        """Reflect a saved gate outcome, never resume the planner or other effects."""
        if response is None or _APPROVAL_COMMAND.fullmatch(text) is None:
            return
        request_id = text.split(" ")[1].lower()
        approval_scope = ChatScope(scope.tenant_id, scope.agent_id, "tool-approvals:" + scope.storage_key)
        receipt = (await self.store.read(approval_scope))["tasks"].get(request_id, {})
        status = receipt.get("status")
        if (receipt.get("scope") != scope.to_dict() or receipt.get("requesterId") != actor.get("aadObjectId")
            or not isinstance(status, str) or status not in {"completed", "rejected", "unknown", "executing"}):
            return
        origin = self.host._approval_origin(scope, actor, receipt.get("digest", ""), run_id)
        if origin is None:
            return  # Receipts still survive an in-memory operator-ledger restart.
        await self.ensure_effect_scope(scope, actor, source)
        if status == "executing" and origin.get("approvalStatus") in {"completed", "rejected", "unknown"}:
            return  # An older in-flight snapshot cannot downgrade a saved outcome.
        if origin.get("skillRun"):
            # A skill run already reported its whole outcome; mark only this proposal as decided.
            self.host._settle_skill_approval(origin, request_id, status, response)
            return
        notice = response + "\n\nThis records only the requested tool decision; no additional workflow steps were run."
        origin["approvalStatus"] = status
        origin["status"] = "complete" if status == "completed" else status
        self.host._publish_run_event(origin["id"], "result", {"content": notice})
        self.host._publish_run_event(origin["id"], "done", {})
        if source == "teams-chat":
            generation = CURRENT_SCOPE_GENERATION.get()

            def saved_result(state: dict[str, Any]) -> None:
                record = state["tasks"].get(origin["id"])
                if (record and state["active"] and generation == self._generations.get(scope, 0)
                        and record.get("requesterId") == actor.get("aadObjectId")):
                    record["toolApproval"] = {"requestId": request_id, "status": status}
                    record["result"] = notice

            await self.store.update(scope, saved_result)

    async def decide(self, scope: ChatScope, actor: dict[str, Any], text: str, *,
                     source: str = "teams-chat", run_id: str = "") -> str | None:
        if not self.authorized(actor):
            return "Tool approval requires an authorized, verified requester in this chat."
        task = asyncio.current_task()
        if task is not None:
            self._decisions.add(task)
            self._decision_scopes[task] = scope
        try:
            with self.scope_context(scope), self.host._run_context(scope, actor, source=source, run_id=run_id):
                await self.ensure_effect_scope(scope, actor, source)
                self.host._assert_instance_enabled(actor)
                response = await self.gate.decide(scope, actor, text)
                await self.ensure_effect_scope(scope, actor, source)
                await self._record_decision(scope, actor, text, response, source, run_id)
                await self.ensure_effect_scope(scope, actor, source)
                return response
        finally:
            if task is not None:
                self._decisions.discard(task)
                self._decision_scopes.pop(task, None)

    async def handle_message(self, context: Any) -> None:
        activity = context.activity
        source = _field(activity, "from_property", "from", "from_")
        recipient = _field(activity, "recipient")
        role = _field(source, "role") or ""
        role = str(getattr(role, "value", role)).casefold()
        data = _field(activity, "channel_data", "channelData")
        event_type = _field(data, "eventType", "event_type") or ""
        if (role in {"bot", "agenticidentity", "agenticuser"}
                or _field(source, "id") == _field(recipient, "id")
                or _field(activity, "subtype") or not isinstance(event_type, str) or event_type not in {"", "message"}):
            return
        scope = activity_scope(activity)
        actor = sdk_actor(activity, scope)
        self.host._assert_instance_enabled(actor)
        state = await self.store.read(scope)
        if self.closing or state["tasks"].get("__conversation_service__", {}).get("removed"):
            return
        reply_generation = self._generations.get(scope, 0)
        snapshot = activity.get_conversation_reference().model_dump(by_alias=True, mode="json", exclude_none=True)
        self.reference(snapshot, scope)
        actor["conversationReference"] = copy.deepcopy(snapshot)
        self.host._capture_personal_reference(activity, scope, actor, snapshot)
        text, mentioned = _activity_text(activity, scope.agent_id)
        text, invoked = _invocation(text)
        value = _field(activity, "value")
        event_id = _field(activity, "id")

        async def reply(message: str) -> Any:
            # Returning ResourceResponse IDs lets the service recognize replies.
            if self.closing or reply_generation != self._generations.get(scope, 0):
                return None
            return await context.send_activity(teams_message(message))

        with self.scope_context(scope):
            decision = (_natural_decision(text)
                        if self.authorized(actor) and (not _group(activity) or mentioned or invoked) else None)
            if decision is not None:
                pending = await self.gate.sole_pending(scope, actor)
                if pending is not None:
                    text = f"{decision} {pending}"
            if _APPROVAL_COMMAND.fullmatch(text):
                if not self.authorized(actor):
                    await reply("Only an authorized requester can confirm a tool action. Nothing was run.")
                    return
                if not event_id or not await claim_activity(self.store, scope, event_id):
                    return
                try:
                    response = await self.decide(scope, actor, text)
                except PermissionError:
                    response = "This conversation is no longer active. Nothing was approved."
                if response:
                    await reply(response)
                return
            # Cards and explicit request-ID commands, never FIFO/free-text replies.
            hitl = self.host._hitl_response_from_activity(value, text)
            if hitl is not None:
                if not self.authorized(actor):
                    await reply("You are not authorized to answer this request.")
                    return
                if not event_id or not await claim_activity(self.store, scope, event_id):
                    return
                await reply(await self.host._resolve_sdk_hitl(scope, actor, *hitl))
                return
            if text.casefold() in {"forget this chat", "forget our conversation"}:
                addressed = not _group(activity) or mentioned or invoked
                if not addressed:
                    state = await self.store.read(scope)
                    ids = state["tasks"].get("__conversation_service__", {}).get("assistantMessageIds", [])
                    addressed = _field(activity, "reply_to_id", "replyToId") in ids
                if addressed:
                    state = await self.store.read(scope)
                    if event_id and event_id in state["seen"]:
                        return
                    self._generations[scope] = self._generations.get(scope, 0) + 1
                    reply_generation = self._generations[scope]
                    self._cancel_decisions(scope)
                    await self.gate.clear(scope)
            if not _group(activity):
                await self._typing(context)
            await self.service.handle_message(activity, actor, snapshot, reply)

    @staticmethod
    async def _typing(context: Any) -> None:
        """Show 'typing…' while the reply is prepared; purely cosmetic, so failures are ignored."""
        try:
            from microsoft_agents.activity import Activity, ActivityTypes

            await context.send_activity(Activity(type=ActivityTypes.typing))
        except Exception:
            pass

    async def welcome(self, context: Any) -> None:
        scope = activity_scope(context.activity)
        actor = sdk_actor(context.activity, scope)
        self.host._assert_instance_enabled(actor)
        event_id = _field(context.activity, "id")
        if event_id and not await claim_activity(self.store, scope, event_id):
            return
        identifiers = (scope.agent_id, actor.get("agenticAppId") or "", actor.get("agenticUserId") or "")
        await self.host._refresh_colleagues(*identifiers)
        await self.service.welcome(scope, context.send_activity, name=self.host._colleague_name_for(*identifiers),
                                   text=self.host._colleague_welcome(*identifiers))
        snapshot = context.activity.get_conversation_reference().model_dump(by_alias=True, mode="json", exclude_none=True)
        self.reference(snapshot, scope)
        self.host._capture_personal_reference(context.activity, scope, actor, snapshot)

    async def remove(self, context: Any) -> None:
        scope = activity_scope(context.activity)
        event_id = _field(context.activity, "id")
        if event_id and not await claim_activity(self.store, scope, event_id):
            return
        self._generations[scope] = self._generations.get(scope, 0) + 1
        decisions = self._cancel_decisions(scope)
        try:
            # Invalidate/cancel jobs first. Removal retains redacted memory to TTL.
            await self.service.remove(scope)
        finally:
            try:
                await self.gate.clear(scope)
                self.host._forget_personal_reference(scope)
            finally:
                if decisions:
                    await asyncio.gather(*decisions, return_exceptions=True)

    def _cancel_decisions(self, scope: ChatScope) -> list[asyncio.Task[Any]]:
        pending = [task for task, owner in tuple(self._decision_scopes.items())
                   if owner == scope and task is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        return pending

    async def close(self) -> None:
        self.closing = True
        try:
            await self.service.close()
        finally:
            try:
                try:
                    await self.host._drain_background_tasks()
                finally:
                    pending = [task for task in self._decisions if task is not asyncio.current_task()]
                    for task in pending:
                        task.cancel()
                    if pending:
                        await asyncio.gather(*pending, return_exceptions=True)
            finally:
                await self.store.close()


def create_autopilot_runtime(host: Any) -> AutopilotRuntime:
    if not host._initialized or host._agent_app is None or host._cloud_adapter is None:
        raise RuntimeError("Initialize the authenticated SDK host before the conversation runtime.")
    # All constructors are lazy: there is no storage/network I/O at this point.
    return AutopilotRuntime(host, create_conversation_store())