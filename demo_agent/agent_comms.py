"""Microsoft Graph as a function's agentic user: private and group Teams chats, mail, and reading inbound items.

Every call uses the Agents SDK's agentic-user token for the bound colleague (delegated Graph, Chat.ReadWrite and
Mail.Send consented on the blueprint), so messages come from the colleague's own Teams/mailbox identity. Calls
are single-attempt with bounded responses; an unknown outcome is reported, never retried.
"""

from __future__ import annotations

import asyncio
import html
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote

import httpx

from .case_desk import DeskBinding
from .compliance_backend import _body_text, _json, _mail_address, _mail_headers
from .teams_format import to_html

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPE = "https://graph.microsoft.com/.default"
_TIMEOUT = 20
_GUID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_EMAIL = re.compile(r"[^\s<>@,;:\"]+@[^\s<>@,;:\"]+\.[^\s<>@,;:\"]+")
_MAIL_SELECT = ("$select=id,conversationId,receivedDateTime,from,sender,toRecipients,ccRecipients,subject,body,"
                "internetMessageHeaders,isDraft")


class CommsError(RuntimeError):
    """A payload-free failure; a write's outcome may be unknown."""


@dataclass(frozen=True)
class Colleague:
    """The agentic identity a Graph call acts as, when there is no desk binding (for example an instance run)."""

    name: str
    instance_app_id: str
    agentic_user_id: str


class AgentComms:
    def __init__(self, connections: Callable[[], Any], tenant_id: str) -> None:
        self._connections = connections
        self.tenant_id = tenant_id
        self._users: dict[str, dict[str, Any]] = {}

    def available(self, binding: DeskBinding | Colleague | None) -> bool:
        return bool(binding and binding.instance_app_id and binding.agentic_user_id and self._connections() is not None)

    async def _token(self, binding: DeskBinding | Colleague) -> str:
        manager = self._connections()
        if manager is None or not self.available(binding):
            raise CommsError(f"{binding.name} has no Teams or mailbox identity yet.")
        try:
            token = await asyncio.wait_for(manager.get_default_connection().get_agentic_user_token(
                self.tenant_id, binding.instance_app_id, binding.agentic_user_id, [SCOPE]), _TIMEOUT)
        except Exception:
            raise CommsError("The agentic-user token exchange did not succeed.") from None
        if not isinstance(token, str) or not token:
            raise CommsError("The agentic-user token exchange returned no token.")
        return token

    async def _call(self, binding: DeskBinding | Colleague, method: str, path: str, body: dict | None = None,
                    expected: tuple[int, ...] = (200,), headers: dict[str, str] | None = None,
                    content: bytes | None = None) -> dict[str, Any]:
        token = await self._token(binding)
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False, trust_env=False,
                                         transport=httpx.AsyncHTTPTransport(retries=0)) as client:
                response = await client.request(method, GRAPH + path, json=body if content is None else None,
                                                content=content, headers={
                    "Authorization": f"Bearer {token}", "Accept": "application/json", **(headers or {})})
        except Exception:
            raise CommsError("The Graph request failed or its outcome is unknown; it was not retried.") from None
        if response.status_code not in expected:
            raise CommsError(f"Graph refused the request (HTTP {response.status_code}).")
        if response.status_code == 202 or not response.content:
            return {}
        data = _json(response.content)
        if type(data) is not dict:
            raise CommsError("Graph returned no entity.")
        return data

    async def user(self, binding: DeskBinding, who: str) -> dict[str, Any] | None:
        """A tenant user by object id, UPN or email; None when not found."""
        who = (who or "").strip()
        if not (_GUID.fullmatch(who) or _EMAIL.fullmatch(who)):
            return None
        cached = self._users.get(who.lower())
        if cached is not None:
            return cached
        try:
            data = await self._call(binding, "GET", f"/users/{quote(who, safe='@')}?$select=id,displayName,mail,"
                                    "userPrincipalName,jobTitle,department,officeLocation,accountEnabled")
        except CommsError:
            return None
        person = {"aadObjectId": data.get("id", ""), "name": data.get("displayName", ""),
                  "email": (data.get("mail") or data.get("userPrincipalName") or "").lower(),
                  "jobTitle": data.get("jobTitle") or "", "department": data.get("department") or "",
                  "enabled": data.get("accountEnabled") is not False}
        for key in (who.lower(), person["aadObjectId"].lower(), person["email"]):
            if key:
                self._users[key] = person
        return person

    @staticmethod
    def _member(user_id: str) -> dict[str, Any]:
        return {"@odata.type": "#microsoft.graph.aadUserConversationMember", "roles": ["owner"],
                "user@odata.bind": f"{GRAPH}/users('{user_id}')"}

    async def direct_chat(self, binding: DeskBinding, user_id: str) -> str:
        created = await self._call(binding, "POST", "/chats", {
            "chatType": "oneOnOne", "members": [self._member(binding.agentic_user_id), self._member(user_id)]},
            expected=(200, 201))
        if not created.get("id"):
            raise CommsError("Teams did not return the private chat.")
        return created["id"]

    async def group_chat(self, binding: DeskBinding, user_ids: list[str], topic: str) -> str:
        members = [self._member(binding.agentic_user_id)] + [self._member(uid) for uid in dict.fromkeys(user_ids)
                                                             if uid.lower() != binding.agentic_user_id]
        if len(members) < 3:
            raise CommsError("A review chat needs at least two participants besides the colleague.")
        created = await self._call(binding, "POST", "/chats", {"chatType": "group", "topic": topic[:250],
                                                               "members": members}, expected=(200, 201))
        if not created.get("id"):
            raise CommsError("Teams did not return the group chat.")
        return created["id"]

    async def post(self, binding: DeskBinding, chat_id: str, text: str, *, mentions: list[dict[str, str]] = ()) -> str:
        content = to_html(text)
        body: dict[str, Any] = {"body": {"contentType": "html", "content": content}}
        if mentions:
            tags = []
            for index, person in enumerate(mentions):
                tags.append(f'<at id="{index}">{html.escape(person["name"])}</at>')
                body.setdefault("mentions", []).append({
                    "id": index, "mentionText": person["name"],
                    "mentioned": {"user": {"id": person["aadObjectId"], "displayName": person["name"],
                                           "userIdentityType": "aadUser"}}})
            body["body"]["content"] = f"<p>{' '.join(tags)}</p>" + content
        sent = await self._call(binding, "POST", f"/chats/{quote(chat_id, safe='')}/messages", body, expected=(200, 201))
        return sent.get("id", "")

    async def chat_message(self, binding: DeskBinding, chat_id: str, message_id: str) -> dict[str, Any]:
        """The authoritative text and sender of one chat message, read back from Graph."""
        data = await self._call(binding, "GET", f"/chats/{quote(chat_id, safe='')}/messages/{quote(message_id, safe='')}")
        sender = ((data.get("from") or {}).get("user") or {})
        return {"text": _body_text(data.get("body"), 4000), "senderId": (sender.get("id") or "").lower(),
                "sender": sender.get("displayName") or "", "at": data.get("createdDateTime") or ""}

    async def email(self, binding: DeskBinding, message_id: str) -> dict[str, Any]:
        """The authoritative inbound email, read from the colleague's own mailbox."""
        message = await self._call(binding, "GET", f"/me/messages/{quote(message_id, safe='')}?{_MAIL_SELECT}",
                                   headers={"Prefer": 'IdType="ImmutableId"'})
        _mail_headers(message)
        sender = _mail_address(message.get("from"))
        return {"id": message.get("id", ""), "conversationId": message.get("conversationId", ""),
                "subject": (message.get("subject") or "")[:240], "from": sender,
                "body": _body_text(message.get("body"), 6000), "receivedAt": message.get("receivedDateTime", "")}

    async def send_mail(self, binding: DeskBinding, to: list[str], subject: str, text: str, *,
                        reply_to: str = "") -> None:
        if reply_to:
            await self._call(binding, "POST", f"/me/messages/{quote(reply_to, safe='')}/reply",
                             {"comment": to_html(text)}, expected=(202,))
            return
        await self._call(binding, "POST", "/me/sendMail", {"message": {
            "subject": subject[:240], "body": {"contentType": "HTML", "content": to_html(text)},
            "toRecipients": [{"emailAddress": {"address": address}} for address in to]}, "saveToSentItems": True},
            expected=(202,))

    # ── files, written as the colleague so the audit log names it ──
    @staticmethod
    def _drive_path(drive_id: str, path: str) -> str:
        return f"/drives/{quote(drive_id, safe='!')}/root:/{quote(path.strip('/'), safe='/')}"

    async def upload(self, binding: DeskBinding | Colleague, drive_id: str, path: str, data: bytes,
                     content_type: str) -> dict[str, Any]:
        """Create or replace a small file (under 4 MB) at a path in a drive; returns the driveItem."""
        return await self._call(binding, "PUT", self._drive_path(drive_id, path) + ":/content", content=data,
                                headers={"Content-Type": content_type}, expected=(200, 201))

    async def item(self, binding: DeskBinding | Colleague, drive_id: str, path: str) -> dict[str, Any]:
        return await self._call(binding, "GET", self._drive_path(drive_id, path) + "?$select=id,name,webUrl")

    async def share(self, binding: DeskBinding | Colleague, drive_id: str, item_id: str, user_ids: list[str]) -> None:
        """Read access for named people only: sign-in required, no invitation email."""
        await self._call(binding, "POST", f"/drives/{quote(drive_id, safe='!')}/items/{quote(item_id, safe='')}/invite", {
            "recipients": [{"objectId": user_id} for user_id in dict.fromkeys(user_ids)], "roles": ["read"],
            "requireSignIn": True, "sendInvitation": False}, expected=(200,))
