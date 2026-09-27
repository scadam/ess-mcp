"""Microsoft Graph as a function's agentic user: private and group Teams chats, mail, and reading inbound items.

Every call uses the Agents SDK's agentic-user token for the bound colleague (delegated Graph, Chat.ReadWrite and
Mail.Send consented on the blueprint), so messages come from the colleague's own Teams/mailbox identity. Calls
are single-attempt with bounded responses; an unknown outcome is reported, never retried.
"""

from __future__ import annotations

import asyncio
import base64
import html
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote, urlsplit

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


class FileConflict(CommsError):
    """The file changed after it was read (its eTag moved on); nothing was written."""


class FileLocked(CommsError):
    """The file is open for editing in Word (a co-authoring session holds it) or checked out; nothing was written."""


def _download_url(location: str) -> bool:
    parts = urlsplit(location)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and not parts.username and host.endswith(".sharepoint.com")


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

    async def _send(self, binding: DeskBinding | Colleague, method: str, path: str, body: dict | None = None,
                    headers: dict[str, str] | None = None, content: bytes | None = None) -> httpx.Response:
        token = await self._token(binding)
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False, trust_env=False,
                                         transport=httpx.AsyncHTTPTransport(retries=0)) as client:
                return await client.request(method, GRAPH + path, json=body if content is None else None,
                                            content=content, headers={
                    "Authorization": f"Bearer {token}", "Accept": "application/json", **(headers or {})})
        except Exception:
            raise CommsError("The Graph request failed or its outcome is unknown; it was not retried.") from None

    async def _call(self, binding: DeskBinding | Colleague, method: str, path: str, body: dict | None = None,
                    expected: tuple[int, ...] = (200,), headers: dict[str, str] | None = None,
                    content: bytes | None = None) -> dict[str, Any]:
        response = await self._send(binding, method, path, body, headers, content)
        if response.status_code not in expected:
            raise CommsError(f"Graph refused the request (HTTP {response.status_code}).")
        if response.status_code == 202 or not response.content:
            return {}
        data = _json(response.content)
        if type(data) is not dict:
            raise CommsError("Graph returned no entity.")
        return data

    async def user(self, binding: DeskBinding, who: str) -> dict[str, Any] | None:
        """A tenant user by object id, UPN, email or exact unique display name; None when not found."""
        who = (who or "").strip()
        if not (_GUID.fullmatch(who) or _EMAIL.fullmatch(who)):
            return await self._user_by_name(binding, who)
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

    async def _user_by_name(self, binding: DeskBinding, name: str) -> dict[str, Any] | None:
        """Only an exact display name that matches exactly one account (a form's "raised by" field)."""
        name = " ".join(name.split())
        if not 3 <= len(name) <= 120 or not re.fullmatch(r"[^\W\d_](?:[^\W\d_]|[ .'-])*", name):
            return None
        cached = self._users.get("name:" + name.casefold())
        if cached is not None:
            return cached
        query = quote("displayName eq '" + name.replace("'", "''") + "'", safe="")
        try:
            data = await self._call(binding, "GET", f"/users?$filter={query}&$select=id&$top=2")
        except CommsError:
            return None
        matches = [item.get("id", "") for item in (data.get("value") or []) if isinstance(item, dict)]
        if len(matches) != 1 or not _GUID.fullmatch(matches[0]):
            return None
        person = await self.user(binding, matches[0])
        if person is not None:
            self._users["name:" + name.casefold()] = person
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

    async def shared_item(self, binding: DeskBinding | Colleague, url: str) -> dict[str, Any]:
        """The drive item behind a SharePoint or OneDrive document address the colleague can open."""
        share = "u!" + base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")
        data = await self._call(binding, "GET", f"/shares/{share}/driveItem?$select=id,name,eTag,webUrl,size,file,"
                                                "parentReference")
        drive = (data.get("parentReference") or {}).get("driveId") or ""
        if not data.get("id") or not drive or "file" not in data:
            raise CommsError("That link is not a file this colleague can open.")
        return {"id": data["id"], "driveId": drive, "name": data.get("name") or "", "webUrl": data.get("webUrl") or ""}

    async def file_content(self, binding: DeskBinding | Colleague, drive_id: str, item_id: str,
                           limit: int) -> tuple[bytes, str]:
        """The file's bytes and the eTag they belong to (read first, so a race can only make the save refuse)."""
        path = f"/drives/{quote(drive_id, safe='!')}/items/{quote(item_id, safe='')}"
        meta = await self._call(binding, "GET", path + "?$select=id,eTag,size")
        if int(meta.get("size") or 0) > limit:
            raise CommsError("The file is too large to edit here.")
        response = await self._send(binding, "GET", path + "/content")
        if response.status_code in (301, 302, 303, 307, 308):
            location = response.headers.get("Location", "")
            if not _download_url(location):
                raise CommsError("Graph redirected the download somewhere unexpected.")
            try:
                # The redirect target is a short-lived pre-authenticated URL: no bearer token is sent there.
                async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False, trust_env=False) as client:
                    response = await client.get(location)
            except Exception:
                raise CommsError("The file download failed.") from None
        if response.status_code != 200 or len(response.content) > limit:
            raise CommsError(f"The file could not be downloaded (HTTP {response.status_code}).")
        return response.content, meta.get("eTag") or ""

    async def replace_file(self, binding: DeskBinding | Colleague, drive_id: str, item_id: str, data: bytes,
                           etag: str, content_type: str) -> dict[str, Any]:
        """Save new content only over the exact version that was read (If-Match).

        Graph can only replace the whole file. While anyone has the document open for editing in Word, its
        co-authoring session holds a shared lock and SharePoint refuses the upload with 423 until the session
        ends. Graph documents `Prefer: bypass-shared-lock` for deletes only; it does not let an upload through.
        """
        if not etag:
            raise CommsError("The file's version is unknown, so it was not overwritten.")
        response = await self._send(
            binding, "PUT", f"/drives/{quote(drive_id, safe='!')}/items/{quote(item_id, safe='')}/content",
            content=data, headers={"Content-Type": content_type, "If-Match": etag})
        if response.status_code == 412:
            raise FileConflict("The document changed after it was read; nothing was saved.")
        if response.status_code == 423:
            raise FileLocked("The document is open for editing in Word, which holds it until it is closed, so the "
                             "change was not saved yet.")
        if response.status_code not in (200, 201):
            raise CommsError(f"Graph refused the upload (HTTP {response.status_code}).")
        item = _json(response.content) if response.content else {}
        item = item if type(item) is dict else {}
        return {"eTag": item.get("eTag") or "", "webUrl": item.get("webUrl") or ""}
