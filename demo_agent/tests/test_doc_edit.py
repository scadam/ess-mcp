"""Word documents edited in place: tracked revisions by the colleague, threaded replies and a hardened parser."""

from __future__ import annotations

import asyncio
import io
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from lxml import etree

from demo_agent import case_work, doc_edit
from demo_agent.agent_comms import AgentComms, CommsError, FileConflict
from demo_agent.case_desk import CaseDesk, CaseEvent, DeskBinding
from demo_agent.case_work import CaseWork, DOC_TOOLS, tools_for, turn_prompt
from demo_agent.conversation_memory import SQLiteStore

W = doc_edit.W
W14 = doc_edit.W14
W15 = doc_edit.W15
MC = doc_edit.MC
TENANT = "17371818-07cb-47f2-9ca3-18f96f0125d7"
SCOTT = "3ef6fe2c-3605-4f77-aeff-fb9e084e3a0d"
URL = "https://caldova74201480-my.sharepoint.com/personal/admin_caldova74201480_onmicrosoft_com/Documents/Guidelines.docx"
HR = DeskBinding(function="hr", name="HR Agent", system="workday", skill="hr-second-line",
                 instance_app_id="ada46fdd-f531-40b0-82cf-4c904d33d022", agentic_user_id="f84f67e1-2e3d-4fe6-a2f8-01191bd74c5c")
HR_ASK = "please add our rules for working temporarily from another country"
COMPLIANCE_ASK = "can you review this section and add what we need to say about client data abroad"


def docx(*, extended: bool = True, main_type: str = doc_edit.MAIN_TYPE, doctype: str = "", done: bool = False) -> bytes:
    """A Word-shaped package: headings, body text, and two @mention comments anchored on sections 4 and 5."""
    paragraphs = [
        ("Title", "Hybrid and overseas working guidelines", None),
        ("Heading1", "4. Working temporarily from another country", None),
        ("", "Talk to your line manager before making any plans.", "0"),
        ("Heading1", "5. Equipment, data and conduct", None),
        ("", "Use your bank laptop. If the VPN is unavailable, you may email documents to a personal address.", "1"),
        ("", "Keep printed documents secure.", None),
    ]
    body = []
    for number, (style, text, cid) in enumerate(paragraphs, start=1):
        layout = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        run = f'<w:r><w:rPr><w:sz w:val="22"/></w:rPr><w:t xml:space="preserve">{text}</w:t></w:r>'
        if cid is not None:
            run = (f'<w:commentRangeStart w:id="{cid}"/>{run}<w:commentRangeEnd w:id="{cid}"/>'
                   f'<w:r><w:rPr><w:rStyle w:val="CommentReference"/></w:rPr><w:commentReference w:id="{cid}"/></w:r>')
        body.append(f'<w:p w14:paraId="1A2B{number:04X}" w14:textId="77777777">{layout}{run}</w:p>')
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>{doctype}'
                f'<w:document xmlns:w="{W}" xmlns:w14="{W14}" xmlns:mc="{MC}" mc:Ignorable="w14"><w:body>'
                + "".join(body) + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>')
    comments = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:comments xmlns:w="{W}" xmlns:w14="{W14}" '
                f'xmlns:mc="{MC}" mc:Ignorable="w14">'
                f'<w:comment w:id="0" w:author="Scott Adams" w:date="2026-09-26T10:00:00Z" w:initials="SA">'
                f'<w:p w14:paraId="5A000001"><w:r><w:annotationRef/></w:r><w:r><w:t>@HR Agent {HR_ASK}</w:t></w:r></w:p></w:comment>'
                f'<w:comment w:id="1" w:author="Scott Adams" w:date="2026-09-26T10:01:00Z" w:initials="SA">'
                f'<w:p w14:paraId="5A000002"><w:r><w:annotationRef/></w:r><w:r><w:t>@Compliance Agent {COMPLIANCE_ASK}</w:t></w:r></w:p>'
                f'</w:comment></w:comments>')
    parts = {
        "[Content_Types].xml": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/word/document.xml" ContentType="{main_type}"/>'
            '<Override PartName="/word/comments.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml"/>'
            + (f'<Override PartName="/word/commentsExtended.xml" ContentType="{doc_edit.EXTENDED_TYPE}"/>' if extended else "")
            + "</Types>"),
        "_rels/.rels": ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                        f'<Relationship Id="rId1" Type="{doc_edit.DOCUMENT_REL}" Target="word/document.xml"/></Relationships>'),
        "word/_rels/document.xml.rels": (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{doc_edit.COMMENTS_REL}" Target="comments.xml"/>'
            + (f'<Relationship Id="rId2" Type="{doc_edit.EXTENDED_REL}" Target="commentsExtended.xml"/>' if extended else "")
            + "</Relationships>"),
        "word/document.xml": document,
        "word/comments.xml": comments,
    }
    if extended:
        parts["word/commentsExtended.xml"] = (
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w15:commentsEx xmlns:w15="{W15}" xmlns:mc="{MC}" '
            f'mc:Ignorable="w15"><w15:commentEx w15:paraId="5A000001" w15:done="{1 if done else 0}"/>'
            f'<w15:commentEx w15:paraId="5A000002" w15:done="0"/></w15:commentsEx>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            archive.writestr(name, text.encode("utf-8"))
    return out.getvalue()


def part(data: bytes, name: str) -> etree._Element:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return etree.fromstring(archive.read(name))


def raw(data: bytes, name: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read(name).decode("utf-8")


def w(tag: str) -> str:
    return f"{{{W}}}{tag}"


class ReadTests(unittest.TestCase):
    def test_paragraphs_carry_stable_refs_styles_and_their_comments(self) -> None:
        view = doc_edit.read(docx(), hint=f"<at>HR Agent</at> {HR_ASK}\n", colleague="HR Agent", requester="Scott Adams")
        refs = [item["ref"] for item in view["paragraphs"]]
        self.assertEqual(refs[:3], ["p1A2B0001", "p1A2B0002", "p1A2B0003"])
        self.assertEqual(view["paragraphs"][1]["style"], "Heading1")
        self.assertEqual(view["paragraphs"][2]["comments"], ["0"])
        first = view["comments"][0]
        self.assertEqual((first["author"], first["paragraphs"]), ("Scott Adams", ["p1A2B0003"]))
        self.assertEqual(first["anchor"], "Talk to your line manager before making any plans.")
        self.assertEqual(view["target"], "0")

    def test_the_target_is_the_comment_naming_this_colleague(self) -> None:
        compliance = doc_edit.read(docx(), hint=COMPLIANCE_ASK, colleague="Compliance Agent")
        self.assertEqual(compliance["target"], "1")
        # No text in the notification: the latest comment naming the colleague.
        self.assertEqual(doc_edit.read(docx(), hint="", colleague="Compliance Agent")["target"], "1")
        self.assertIsNone(doc_edit.read(docx(), hint="something unrelated entirely", colleague="IT Service Agent")["target"])
        # A resolved thread is not a request any more.
        self.assertIsNone(doc_edit.read(docx(done=True), hint=HR_ASK, colleague="HR Agent")["target"])

    def test_hostile_or_foreign_packages_are_refused(self) -> None:
        with self.assertRaisesRegex(doc_edit.DocumentError, "DTD"):
            doc_edit.read(docx(doctype='<!DOCTYPE w [<!ENTITY x "boom">]>'))
        with self.assertRaisesRegex(doc_edit.DocumentError, "macro-enabled"):
            doc_edit.read(docx(main_type="application/vnd.ms-word.document.macroEnabled.main+xml"))
        with self.assertRaisesRegex(doc_edit.DocumentError, "not a Word"):
            doc_edit.read(b"not a zip at all")
        bomb = io.BytesIO()
        with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("word/document.xml", b"\0" * (doc_edit.MAX_PART + 1))
        with self.assertRaisesRegex(doc_edit.DocumentError, "too large"):
            doc_edit.read(bomb.getvalue())


class EditTests(unittest.TestCase):
    def test_insertions_are_tracked_paragraphs_in_the_body_style_by_the_colleague(self) -> None:
        data, summary = doc_edit.apply_changes(docx(), author="HR Agent", edits=[
            {"paragraph": "p1A2B0003", "mode": "insert_after", "text": "**Up to 20 working days:** agree it with your manager.\n\nLonger stays need a panel."},
            {"paragraph": "p1A2B0003", "mode": "insert_after", "text": "Check your right to work first."}])
        self.assertEqual([item["mode"] for item in summary["applied"]], ["insert_after", "insert_after"])
        body = part(data, "word/document.xml").find(w("body"))
        texts = [doc_edit._text(p) for p in body.iter(w("p"))]
        self.assertEqual(texts[2:6], ["Talk to your line manager before making any plans.",
                                      "Up to 20 working days: agree it with your manager.", "Longer stays need a panel.",
                                      "Check your right to work first."])
        new = [p for p in body.iter(w("p"))][3]
        mark = new.find(f"{w('pPr')}/{w('rPr')}/{w('ins')}")
        self.assertEqual((mark.get(w("author")), new.find(f"{w('pPr')}/{w('pStyle')}")), ("HR Agent", None))
        runs = new.find(w("ins")).findall(w("r"))
        self.assertIsNotNone(runs[0].find(f"{w('rPr')}/{w('b')}"))
        self.assertIsNone(runs[1].find(f"{w('rPr')}/{w('b')}"))
        self.assertRegex(new.get(f"{{{W14}}}paraId"), r"^[0-9A-F]{8}$")
        # Namespace prefixes and markup compatibility survive re-serialization.
        self.assertIn('mc:Ignorable="w14"', raw(data, "word/document.xml"))
        self.assertTrue(raw(data, "word/document.xml").split("?>", 1)[1].lstrip().startswith("<w:document"))

    def test_a_phrase_is_replaced_as_a_deletion_and_an_insertion(self) -> None:
        phrase = "If the VPN is unavailable, you may email documents to a personal address."
        data, _summary = doc_edit.apply_changes(docx(), author="Compliance Agent", edits=[
            {"paragraph": "p1A2B0005", "mode": "replace", "find": phrase,
             "text": "If the VPN is unavailable, stop and contact the IT Service Desk (rule D2)."}])
        paragraph = [p for p in part(data, "word/document.xml").iter(w("p"))][4]
        deleted = "".join(node.text for node in paragraph.iter(w("delText")))
        self.assertEqual(deleted, phrase)
        self.assertEqual(paragraph.find(w("del")).get(w("author")), "Compliance Agent")
        self.assertEqual(doc_edit._text(paragraph),
                         "Use your bank laptop. If the VPN is unavailable, stop and contact the IT Service Desk (rule D2).")
        # The comment still anchors the paragraph.
        self.assertIsNotNone(paragraph.find(w("commentRangeStart")))
        with self.assertRaisesRegex(doc_edit.DocumentError, "already has tracked changes"):
            doc_edit.apply_changes(data, author="HR Agent", edits=[
                {"paragraph": "p1A2B0005", "mode": "replace", "text": "Different."}])
        with self.assertRaisesRegex(doc_edit.DocumentError, "not found"):
            doc_edit.apply_changes(docx(), author="HR Agent", edits=[
                {"paragraph": "p1A2B0005", "mode": "replace", "find": "words that are not there", "text": "x"}])

    def test_two_colleagues_edits_accumulate_with_unique_revision_ids(self) -> None:
        first, _ = doc_edit.apply_changes(docx(), author="HR Agent", edits=[
            {"paragraph": "p1A2B0003", "mode": "insert_after", "text": "HR text."}])
        second, _ = doc_edit.apply_changes(first, author="Compliance Agent", edits=[
            {"paragraph": "p1A2B0006", "mode": "append", "text": "Shred them in a bank office (D4)."}])
        root = part(second, "word/document.xml")
        ids = [node.get(w("id")) for node in root.iter(w("ins"), w("del"))]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual({node.get(w("author")) for node in root.iter(w("ins"))}, {"HR Agent", "Compliance Agent"})
        self.assertIn("Keep printed documents secure. Shred them in a bank office (D4).",
                      [doc_edit._text(p) for p in root.iter(w("p"))])

    def test_a_reply_is_threaded_under_the_comment_that_asked(self) -> None:
        data, summary = doc_edit.apply_changes(docx(), author="HR Agent", reply_to="0",
                                               reply="Added the W1 to W9 rules after this paragraph.")
        comments = part(data, "word/comments.xml").findall(w("comment"))
        reply = comments[-1]
        self.assertEqual((reply.get(w("id")), reply.get(w("author")), reply.get(w("initials"))),
                         (summary["reply"], "HR Agent", "HA"))
        reply_para = reply.find(w("p")).get(f"{{{W14}}}paraId")
        entries = part(data, "word/commentsExtended.xml").findall(f"{{{W15}}}commentEx")
        self.assertIn((reply_para, "5A000001"), [(e.get(f"{{{W15}}}paraId"), e.get(f"{{{W15}}}paraIdParent")) for e in entries])
        document = part(data, "word/document.xml")
        for tag in ("commentRangeStart", "commentRangeEnd", "commentReference"):
            self.assertIn(summary["reply"], [node.get(w("id")) for node in document.iter(w(tag))])
        # A package without commentsExtended gets one, registered in the relationships and content types.
        bare, _ = doc_edit.apply_changes(docx(extended=False), author="HR Agent", reply_to="0", reply="Done.")
        self.assertIn("commentsExtended.xml", raw(bare, "word/_rels/document.xml.rels"))
        self.assertIn("/word/commentsExtended.xml", raw(bare, "[Content_Types].xml"))
        self.assertEqual(len(part(bare, "word/commentsExtended.xml")), 2)

    def test_edits_must_point_at_paragraphs_that_exist(self) -> None:
        for ref in ("pFFFFFFFF", "#99", "paragraph three"):
            with self.subTest(ref=ref), self.assertRaises(doc_edit.DocumentError):
                doc_edit.apply_changes(docx(), author="HR Agent", edits=[{"paragraph": ref, "mode": "append", "text": "x"}])
        with self.assertRaisesRegex(doc_edit.DocumentError, "no comment"):
            doc_edit.apply_changes(docx(), author="HR Agent", reply="Hello")


class FakeFiles:
    """Graph as the colleague sees one document: versions, eTags and an optional collision on save."""

    def __init__(self, data: bytes) -> None:
        self.data, self.version, self.collisions, self.saves = data, 1, 0, 0
        self.posted: list[tuple[str, str]] = []
        self.refuse_saves = False

    def available(self, binding: Any) -> bool:
        return True

    async def shared_item(self, binding: Any, url: str) -> dict[str, Any]:
        assert url == URL
        return {"id": "item-1", "driveId": "b!drive", "name": "Guidelines.docx", "webUrl": "https://example.sharepoint.com/doc"}

    async def file_content(self, binding: Any, drive: str, item: str, limit: int) -> tuple[bytes, str]:
        return self.data, f'"v{self.version}"'

    async def replace_file(self, binding: Any, drive: str, item: str, data: bytes, etag: str, content_type: str) -> dict[str, Any]:
        if self.refuse_saves:
            raise CommsError("Graph refused the upload (HTTP 403).")
        if self.collisions:
            self.collisions -= 1
            self.data, _ = doc_edit.apply_changes(self.data, author="Compliance Agent", edits=[
                {"paragraph": "p1A2B0006", "mode": "append", "text": "(D4)"}])
            self.version += 1
        if etag != f'"v{self.version}"':
            raise FileConflict("changed")
        self.data, self.version, self.saves = data, self.version + 1, self.saves + 1
        return {"eTag": f'"v{self.version}"', "webUrl": ""}

    async def user(self, binding: Any, who: str) -> dict[str, Any] | None:
        return {"aadObjectId": SCOTT, "name": "Scott Adams", "email": "admin@caldova.test", "enabled": True}

    async def direct_chat(self, binding: Any, user_id: str) -> str:
        return "19:chat"

    async def post(self, binding: Any, chat: str, text: str, **_: Any) -> str:
        self.posted.append((chat, text))
        return "m1"


def comment_event(comment: str = HR_ASK) -> CaseEvent:
    return CaseEvent(source="document", kind="mention", function="hr", title="Word comment on Guidelines.docx",
                     text=comment, actor={"name": "Scott Adams", "aadObjectId": SCOTT}, event_id="doc:c-1",
                     channel={"kind": "document", "document": "Guidelines.docx", "documentUrl": URL, "commentId": "c-1",
                              "threadId": "c-1", "documentId": "d-1", "comment": comment, "commenter": "Scott Adams"})


class DocumentCaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        self.store = SQLiteStore(self.root / "state.sqlite3")
        self.desk = CaseDesk(self.store, TENANT, [HR])

        async def idle(case: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
            return {}

        self.desk.work = idle
        self.files = FakeFiles(docx())
        self.work = CaseWork(object(), self.desk, self.files)  # type: ignore[arg-type]
        self.key = await self.desk.submit(comment_event())
        self.token = case_work.CURRENT_CASE.set({"key": self.key, "binding": HR})
        self.retry = patch.object(case_work, "DOC_RETRY_SECONDS", 0.0)
        self.retry.start()

    async def asyncTearDown(self) -> None:
        self.retry.stop()
        case_work.CURRENT_CASE.reset(self.token)
        await self.desk.close()
        await self.store.close()
        shutil.rmtree(self.root, ignore_errors=True)

    async def test_document_cases_get_the_document_tools_and_a_prompt_that_says_so(self) -> None:
        case = await self.desk.get(self.key)
        names = [tool["function"]["name"] for tool in tools_for(HR, case)]
        self.assertTrue({"doc__read_document", "doc__edit_document"} <= set(names))
        self.assertFalse({tool["function"]["name"] for tool in DOC_TOOLS} & {t["function"]["name"] for t in tools_for(HR)})
        self.assertIn("doc__read_document", turn_prompt(case, [], HR))

    async def test_read_edit_and_reply_in_the_document_even_when_someone_saves_in_between(self) -> None:
        view = await self.work.run_tool("read_document", {})
        self.assertEqual((view["document"], view["target"]), ("Guidelines.docx", "0"))
        self.files.collisions = 1
        with patch.object(case_work.asyncio, "sleep", AsyncMock()):
            saved = await self.work.run_tool("edit_document", {"edits": [
                {"paragraph": "p1A2B0003", "mode": "insert_after", "text": "Up to 20 working days (W1)."}]})
        self.assertTrue(saved["saved"])
        texts = [doc_edit._text(p) for p in part(self.files.data, "word/document.xml").iter(w("p"))]
        self.assertIn("Up to 20 working days (W1).", texts)
        self.assertIn("Keep printed documents secure. (D4)", texts)  # The other colleague's save was kept.
        result = await self.work.run_tool("resolve", {"resolution": "Added W1-W9.", "message_to_requester": "Added the rules.",
                                                      "confirm_within_hours": 24})
        self.assertEqual(result["told_requester_by"], "document")
        reply = part(self.files.data, "word/comments.xml").findall(w("comment"))[-1]
        self.assertEqual(reply.get(w("author")), "HR Agent")
        self.assertIn("@mention me", "".join(reply.itertext()))
        self.assertEqual(self.files.posted, [])

    async def test_a_reply_that_cannot_be_saved_reaches_the_requester_in_teams(self) -> None:
        self.files.refuse_saves = True
        sent = await self.work.run_tool("message_requester", {"message": "Which country?", "expects_reply": True})
        self.assertEqual(sent["channel"], "teams")
        self.assertEqual(self.files.posted, [("19:chat", "Which country?")])


class EventAndCommsTests(unittest.IsolatedAsyncioTestCase):
    def test_only_sharepoint_document_links_are_kept_and_a_thread_continues_its_case(self) -> None:
        event = comment_event()
        self.assertEqual(event.channel["documentUrl"], URL)  # Not scrubbed, though the host looks like a token.
        self.assertIn("doc:d-1:c-1", event.aliases())
        for bad in ("https://evil.example.com/Guidelines.docx", "http://caldova.sharepoint.com/a.docx",
                    "https://caldova.sharepoint.com.evil.test/a.docx", "https://caldova.sharepoint.com/a b.docx"):
            channel = {**event.channel, "documentUrl": bad}
            with self.subTest(url=bad):
                self.assertNotIn("documentUrl", CaseEvent(source="document", kind="mention", function="hr", channel=channel).channel)

    async def test_a_raised_by_name_resolves_only_to_exactly_one_person(self) -> None:
        comms = AgentComms(lambda: None, TENANT)
        calls: list[str] = []

        async def fake(binding: Any, method: str, path: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
            calls.append(path)
            if path.startswith("/users?$filter="):
                return {"value": [{"id": "af88f6b5-38d1-47ec-9ff6-faa08656f408"}]} if "Aadi" in path else {"value": [{"id": "a"}, {"id": "b"}]}
            return {"id": "af88f6b5-38d1-47ec-9ff6-faa08656f408", "displayName": "Aadi Kapoor", "mail": "AadiK@caldova.test"}

        comms._call = fake  # type: ignore[method-assign]
        person = await comms.user(HR, "Aadi Kapoor")
        self.assertEqual(person["email"], "aadik@caldova.test")
        self.assertIsNone(await comms.user(HR, "Sam Smith"))
        self.assertIsNone(await comms.user(HR, "x' or 1 eq 1"))
        self.assertIsNone(await comms.user(HR, "Siobhan O'Neill"))
        filters = [path for path in calls if path.startswith("/users?$filter=")]
        self.assertEqual(len(filters), 3)
        self.assertIn("O%27%27Neill", filters[-1])  # OData quotes are doubled, never closed.


class DryRunCueTests(unittest.TestCase):
    def test_a_dry_run_is_asked_for_in_the_requesters_own_words(self) -> None:
        from demo_agent.conversation import _DRY_RUN

        for text in ("Run the month-end close as a dry run", "Do a dry-run of my hiring backlog",
                     "Clear the backlog but don't change anything", "read-only please"):
            self.assertIsNotNone(_DRY_RUN.search(text), text)
        for text in ("Clear my hiring backlog", "Run the month-end close and fix what you can"):
            self.assertIsNone(_DRY_RUN.search(text), text)


if __name__ == "__main__":
    unittest.main()
