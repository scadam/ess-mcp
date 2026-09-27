"""Word documents a colleague was asked to work on: read the text and comments, write changes as tracked revisions.

A comment that @mentions a colleague says what is wanted. The colleague's edits land as real Word revisions (w:ins
and w:del authored by the colleague) and its answer as a threaded reply to that comment, so the person who asked
accepts or rejects each change in Word. Only the package's XML parts are parsed, with DTDs, entity expansion and
network access disabled, and the package is size-bounded before anything is decompressed.
"""

from __future__ import annotations

import datetime as _dt
import io
import posixpath
import re
import secrets
import zipfile
from copy import deepcopy
from typing import Any, Iterable, Iterator

from lxml import etree

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
W15 = "http://schemas.microsoft.com/office/word/2012/wordml"
W16CID = "http://schemas.microsoft.com/office/word/2016/wordml/cid"
W16CEX = "http://schemas.microsoft.com/office/word/2018/wordml/cex"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
PR = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
DOCUMENT_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
COMMENTS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments"
EXTENDED_REL = "http://schemas.microsoft.com/office/2011/relationships/commentsExtended"
IDS_REL = "http://schemas.microsoft.com/office/2016/09/relationships/commentsIds"
EXTENSIBLE_REL = "http://schemas.microsoft.com/office/2018/08/relationships/commentsExtensible"
MAIN_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
EXTENDED_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.commentsExtended+xml"
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

MAX_PACKAGE = 25 * 1024 * 1024
MAX_PART = 40 * 1024 * 1024
MAX_TOTAL = 120 * 1024 * 1024
MAX_ENTRIES = 1500
MAX_EDITS = 12
MAX_EDIT_TEXT = 4000
MAX_PARAGRAPHS = 400
PARAGRAPH_TEXT = 1200

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False, huge_tree=False,
                          remove_blank_text=False)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
_TOKEN = re.compile(r"[0-9a-z]+")
_HEADING = re.compile(r"^(?:heading\s?\d|title|subtitle)$", re.IGNORECASE)
_PARA_REF = re.compile(r"^(?:p([0-9A-F]{8})|#(\d{1,5}))$")
# Content a replacement would mangle: fields, drawings, embedded objects, notes and equations.
_COMPLEX = ("fldChar", "fldSimple", "instrText", "drawing", "pict", "object", "txbxContent", "footnoteReference",
            "endnoteReference")


def w(tag: str) -> str:
    return f"{{{W}}}{tag}"


def _q(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}"


class DocumentError(ValueError):
    """The document cannot be read or changed as asked; the message is safe to show the model and the requester."""


def _parse(data: bytes) -> etree._Element:
    if b"<!DOCTYPE" in data[:65536].upper():
        raise DocumentError("A part of the document declares a DTD, which is not allowed.")
    try:
        root = etree.fromstring(data, _PARSER)
    except etree.XMLSyntaxError:
        raise DocumentError("A part of the document is not well-formed XML.") from None
    info = root.getroottree().docinfo
    if info.internalDTD is not None or info.doctype:
        raise DocumentError("A part of the document declares a DTD, which is not allowed.")
    return root


class _Package:
    """An OOXML zip held in memory: parts are parsed on demand and only changed parts are re-serialized."""

    def __init__(self, data: bytes) -> None:
        if len(data) > MAX_PACKAGE:
            raise DocumentError("The document is larger than 25 MB, too large to edit here.")
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
            infos = archive.infolist()
            if (len(infos) > MAX_ENTRIES or any(info.file_size > MAX_PART for info in infos)
                    or sum(info.file_size for info in infos) > MAX_TOTAL):
                raise DocumentError("The document package is too large to edit safely.")
            self._raw = {info.filename: archive.read(info) for info in infos}
        except (zipfile.BadZipFile, EOFError, NotImplementedError):
            raise DocumentError("The file is not a Word (.docx) document.") from None
        self._infos = infos
        self._xml: dict[str, etree._Element] = {}
        self._dirty: set[str] = set()
        self._new: list[str] = []
        self.main = self._main_part()

    def has(self, name: str) -> bool:
        return name in self._raw or name in self._new

    def xml(self, name: str) -> etree._Element:
        if name not in self._xml:
            if name not in self._raw:
                raise DocumentError(f"The document has no {name} part.")
            self._xml[name] = _parse(self._raw[name])
        return self._xml[name]

    def touch(self, name: str) -> None:
        self._dirty.add(name)

    def add(self, name: str, root: etree._Element) -> None:
        self._xml[name] = root
        self._new.append(name)
        self._dirty.add(name)

    @staticmethod
    def _rels_name(part: str) -> str:
        folder, file = posixpath.split(part)
        return posixpath.join(folder, "_rels", file + ".rels")

    def _main_part(self) -> str:
        if not self.has("_rels/.rels") or not self.has("[Content_Types].xml"):
            raise DocumentError("The file is not a Word (.docx) document.")
        target = next((rel.get("Target") for rel in self.xml("_rels/.rels").iter(_q(PR, "Relationship"))
                       if rel.get("Type") == DOCUMENT_REL), None)
        name = posixpath.normpath((target or "").lstrip("/"))
        overrides = {item.get("PartName"): item.get("ContentType")
                     for item in self.xml("[Content_Types].xml").iter(_q(CT, "Override"))}
        if not name.endswith(".xml") or overrides.get("/" + name) != MAIN_TYPE or not self.has(name):
            raise DocumentError("The file is not a Word (.docx) document (macro-enabled files are not edited).")
        return name

    def related(self, rel_type: str) -> str | None:
        rels = self._rels_name(self.main)
        if not self.has(rels):
            return None
        for rel in self.xml(rels).iter(_q(PR, "Relationship")):
            if rel.get("Type") == rel_type and rel.get("TargetMode") != "External":
                name = posixpath.normpath(posixpath.join(posixpath.dirname(self.main), rel.get("Target") or ""))
                return name if self.has(name) else None
        return None

    def create_related(self, rel_type: str, file: str, content_type: str, root: etree._Element) -> str:
        name = posixpath.join(posixpath.dirname(self.main), file)
        rels = self._rels_name(self.main)
        if not self.has(rels):
            raise DocumentError("The document has no relationships part.")
        relations = self.xml(rels)
        used = {rel.get("Id") for rel in relations}
        number = 1
        while f"rIdAutopilot{number}" in used:
            number += 1
        etree.SubElement(relations, _q(PR, "Relationship"),
                         {"Id": f"rIdAutopilot{number}", "Type": rel_type, "Target": file})
        self.touch(rels)
        if self.has(name):
            return name  # The part exists but was unreferenced: link it rather than write a duplicate entry.
        types = self.xml("[Content_Types].xml")
        etree.SubElement(types, _q(CT, "Override"), {"PartName": "/" + name, "ContentType": content_type})
        self.touch("[Content_Types].xml")
        self.add(name, root)
        return name

    def save(self) -> bytes:
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
            for name in [info.filename for info in self._infos] + self._new:
                info = next((item for item in self._infos if item.filename == name), None)
                entry = zipfile.ZipInfo(name, date_time=info.date_time if info else _dt.datetime.now().timetuple()[:6])
                entry.compress_type = zipfile.ZIP_DEFLATED
                if info is not None:
                    entry.external_attr = info.external_attr
                data = (etree.tostring(self._xml[name], xml_declaration=True, encoding="UTF-8", standalone=True)
                        if name in self._dirty else self._raw[name])
                archive.writestr(entry, data)
        return out.getvalue()


# ── reading ──

def _inside(node: etree._Element, stop: etree._Element, tags: frozenset[str]) -> bool:
    for ancestor in node.iterancestors():
        if ancestor is stop:
            return False
        if ancestor.tag in tags:
            return True
    return False


_HIDDEN = frozenset({w("del"), w("moveFrom"), w("txbxContent")})


def _runs(paragraph: etree._Element) -> Iterator[etree._Element]:
    for run in paragraph.iter(w("r")):
        if not _inside(run, paragraph, _HIDDEN):
            yield run


def _run_text(run: etree._Element) -> str:
    parts = []
    for child in run:
        if child.tag == w("t"):
            parts.append(child.text or "")
        elif child.tag == w("tab"):
            parts.append("\t")
        elif child.tag in (w("br"), w("cr")):
            parts.append("\n")
        elif child.tag == w("noBreakHyphen"):
            parts.append("-")
    return "".join(parts)


def _text(paragraph: etree._Element) -> str:
    return "".join(_run_text(run) for run in _runs(paragraph))


def _paragraphs(body: etree._Element) -> list[etree._Element]:
    return [p for p in body.iter(w("p")) if not _inside(p, body, frozenset({w("txbxContent")}))]


def _style(paragraph: etree._Element) -> str:
    style = paragraph.find(f"{w('pPr')}/{w('pStyle')}")
    return (style.get(w("val")) or "") if style is not None else ""


def _is_heading(paragraph: etree._Element) -> bool:
    return bool(_HEADING.match(_style(paragraph))) or paragraph.find(f"{w('pPr')}/{w('outlineLvl')}") is not None


def _tracked(paragraph: etree._Element) -> bool:
    return any(True for _ in paragraph.iter(w("ins"), w("del"), w("moveFrom"), w("moveTo")))


def _ref(paragraph: etree._Element, index: int, unique: set[str]) -> str:
    para_id = (paragraph.get(_q(W14, "paraId")) or "").upper()
    return f"p{para_id}" if para_id in unique else f"#{index}"


def _unique_para_ids(paragraphs: list[etree._Element]) -> set[str]:
    seen: dict[str, int] = {}
    for paragraph in paragraphs:
        value = (paragraph.get(_q(W14, "paraId")) or "").upper()
        if re.fullmatch(r"[0-9A-F]{8}", value):
            seen[value] = seen.get(value, 0) + 1
    return {value for value, count in seen.items() if count == 1}


def _comment_nodes(package: _Package) -> tuple[str | None, list[etree._Element]]:
    name = package.related(COMMENTS_REL)
    return (name, package.xml(name).findall(w("comment"))) if name else (None, [])


def _comments(package: _Package, body: etree._Element, paragraphs: list[etree._Element],
              refs: list[str]) -> list[dict[str, Any]]:
    _name, nodes = _comment_nodes(package)
    if not nodes:
        return []
    items: dict[str, dict[str, Any]] = {}
    by_para: dict[str, str] = {}
    for node in nodes:
        cid = node.get(w("id")) or ""
        texts = [_text(p) for p in node.iter(w("p"))]
        last = [p for p in node.iter(w("p"))][-1:] or [None]
        para = (last[0].get(_q(W14, "paraId")) or "").upper() if last[0] is not None else ""
        if para:
            by_para[para] = cid
        items[cid] = {"id": cid, "author": node.get(w("author")) or "", "date": node.get(w("date")) or "",
                      "text": "\n".join(text for text in texts if text).strip()[:2000], "parent": None,
                      "done": False, "paragraphs": [], "anchor": "", "replies": []}
    extended = package.related(EXTENDED_REL)
    if extended:
        for entry in package.xml(extended).iter(_q(W15, "commentEx")):
            cid = by_para.get((entry.get(_q(W15, "paraId")) or "").upper())
            if cid is None:
                continue
            items[cid]["done"] = entry.get(_q(W15, "done")) == "1"
            parent = by_para.get((entry.get(_q(W15, "paraIdParent")) or "").upper())
            if parent and parent != cid:
                items[cid]["parent"] = parent
                items[parent]["replies"].append(cid)
    index = {paragraph: position for position, paragraph in enumerate(paragraphs)}
    open_ranges: dict[str, list[str]] = {}
    current = 0
    for node in body.iter():
        if node.tag == w("p") and node in index:
            current = index[node]
        cid = node.get(w("id")) if node.tag in (w("commentRangeStart"), w("commentRangeEnd"),
                                               w("commentReference")) else None
        if cid in items:
            item = items[cid]
            if node.tag == w("commentRangeStart"):
                open_ranges[cid] = []
                item["paragraphs"] = [refs[current]] if refs else []
            elif node.tag == w("commentRangeEnd"):
                start = refs.index(item["paragraphs"][0]) if item["paragraphs"] else current
                item["paragraphs"] = refs[start:current + 1]
                item["anchor"] = "".join(open_ranges.pop(cid, []))[:600]
            elif not item["paragraphs"] and refs:
                item["paragraphs"] = [refs[current]]
        elif node.tag == w("t") and open_ranges and not _inside(node, body, _HIDDEN):
            for buffer in open_ranges.values():
                buffer.append(node.text or "")
    return list(items.values())


def _tokens(text: str) -> set[str]:
    return {token for token in _TOKEN.findall((text or "").lower()) if len(token) > 1}


def strip_mentions(text: str) -> str:
    """The comment text as posted, without the notification's <at>mention</at> markup or other tags."""
    text = re.sub(r"<at>.*?</at>", " ", text or "", flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]{0,200}>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def match_comment(comments: list[dict[str, Any]], hint: str, colleague: str, requester: str = "") -> str | None:
    """The comment that asked this colleague for the work: best text match to the notification, naming it."""
    wanted = _tokens(strip_mentions(hint)) - _tokens(colleague)
    names = _tokens(colleague)
    best: tuple[float, str, str] | None = None
    for item in comments:
        if item["author"].strip().casefold() == colleague.strip().casefold() or item["done"]:
            continue
        have = _tokens(item["text"])
        if not have:
            continue
        overlap = len(wanted & have) / len(wanted) if wanted else 0.0
        named = bool(names) and names <= have
        score = overlap + (0.3 if named else 0.0) + (0.1 if requester and item["author"].casefold() == requester.casefold() else 0.0)
        if not wanted and not named:
            continue
        if best is None or (score, item["date"]) > (best[0], best[1]):
            best = (score, item["date"], item["id"])
    threshold = 0.6 if wanted else 0.3
    return best[2] if best is not None and best[0] >= threshold else None


def read(data: bytes, *, hint: str = "", colleague: str = "", requester: str = "") -> dict[str, Any]:
    """Paragraphs (each with a ref to point edits at) and comments, and which comment asked this colleague."""
    package = _Package(data)
    body = package.xml(package.main).find(w("body"))
    if body is None:
        raise DocumentError("The document has no body.")
    paragraphs = _paragraphs(body)
    unique = _unique_para_ids(paragraphs)
    refs = [_ref(paragraph, index, unique) for index, paragraph in enumerate(paragraphs)]
    comments = _comments(package, body, paragraphs, refs)
    anchored: dict[str, list[str]] = {}
    for item in comments:
        for ref in item["paragraphs"]:
            anchored.setdefault(ref, []).append(item["id"])
    shown = []
    for index, paragraph in enumerate(paragraphs[:MAX_PARAGRAPHS]):
        text = _text(paragraph)
        entry: dict[str, Any] = {"ref": refs[index], "text": text[:PARAGRAPH_TEXT]}
        if _style(paragraph):
            entry["style"] = _style(paragraph)
        if _tracked(paragraph):
            entry["trackedChanges"] = True
        if refs[index] in anchored:
            entry["comments"] = anchored[refs[index]]
        shown.append(entry)
    return {"paragraphs": shown, "truncated": len(paragraphs) > MAX_PARAGRAPHS, "comments": comments,
            "target": match_comment(comments, hint, colleague, requester) if colleague else None}


# ── writing ──

class _Ids:
    """Fresh w:id values above every id already used for revisions, comments and bookmarks."""

    def __init__(self, *roots: etree._Element) -> None:
        values = [int(value) for root in roots for element in root.iter()
                  if (value := element.get(w("id"))) is not None and re.fullmatch(r"\d{1,9}", value)]
        self._next = max(values, default=0) + 1

    def __call__(self) -> str:
        value, self._next = self._next, self._next + 1
        return str(value)


def _para_id(used: set[str]) -> str:
    while True:
        value = f"{secrets.randbelow(0x7FFFFFFE) + 1:08X}"
        if value not in used:
            used.add(value)
            return value


def _clean(text: str) -> str:
    return _CONTROL.sub("", (text or "").replace("\r\n", "\n").replace("\r", "\n"))


def _t(parent: etree._Element, text: str, tag: str = "t") -> etree._Element:
    node = etree.SubElement(parent, w(tag))
    node.text = text
    node.set(XML_SPACE, "preserve")
    return node


def _template_rpr(paragraph: etree._Element | None) -> etree._Element | None:
    if paragraph is None:
        return None
    for run in _runs(paragraph):
        if run.find(w("t")) is None:
            continue
        properties = run.find(w("rPr"))
        if properties is None:
            return None
        style = properties.find(w("rStyle"))
        if style is not None and style.get(w("val")) in {"CommentReference", "Hyperlink"}:
            continue
        clone = deepcopy(properties)
        for tag in ("ins", "del", "moveFrom", "moveTo", "rPrChange"):
            for node in clone.findall(w(tag)):
                clone.remove(node)
        return clone
    return None


def _bold(properties: etree._Element | None, maker: etree._Element) -> etree._Element:
    clone = deepcopy(properties) if properties is not None else maker.makeelement(w("rPr"))
    if clone.find(w("b")) is None:
        position = sum(1 for child in clone if child.tag in (w("rStyle"), w("rFonts")))
        clone.insert(position, clone.makeelement(w("bCs")))
        clone.insert(position, clone.makeelement(w("b")))
    return clone


def _new_runs(text: str, properties: etree._Element | None, maker: etree._Element) -> list[etree._Element]:
    runs = []
    for number, chunk in enumerate(re.split(r"\*\*", _clean(text))):
        bold = number % 2 == 1
        for line_number, line in enumerate(chunk.split("\n")):
            if line_number:
                run = maker.makeelement(w("r"))
                etree.SubElement(run, w("br"))
                runs.append(run)
            if not line:
                continue
            run = maker.makeelement(w("r"))
            chosen = _bold(properties, maker) if bold else (deepcopy(properties) if properties is not None else None)
            if chosen is not None:
                run.append(chosen)
            _t(run, line)
            runs.append(run)
    return runs


def _revision(maker: etree._Element, tag: str, ids: _Ids, author: str, stamp: str) -> etree._Element:
    return maker.makeelement(w(tag), {w("id"): ids(), w("author"): author, w("date"): stamp})


def _body_template(anchor: etree._Element, paragraphs: list[etree._Element]) -> etree._Element | None:
    """New text after a heading takes the look of the body text below it, not of the heading."""
    if not _is_heading(anchor):
        return anchor
    start = paragraphs.index(anchor) + 1 if anchor in paragraphs else len(paragraphs)
    return next((p for p in paragraphs[start:] if not _is_heading(p) and _text(p).strip()), None)


def _insert_after(after: etree._Element, template: etree._Element | None, text: str, author: str, stamp: str,
                  ids: _Ids, para_ids: set[str] | None) -> list[etree._Element]:
    blocks = [block.strip("\n") for block in re.split(r"\n[ \t]*\n", _clean(text)) if block.strip()]
    if not blocks:
        raise DocumentError("There is no text to insert.")
    source = template.find(w("pPr")) if template is not None else None
    properties = _template_rpr(template)
    created = []
    for block in blocks:
        paragraph = after.makeelement(w("p"))
        if para_ids is not None:
            paragraph.set(_q(W14, "paraId"), _para_id(para_ids))
            paragraph.set(_q(W14, "textId"), "77777777")
        layout = deepcopy(source) if source is not None else paragraph.makeelement(w("pPr"))
        for tag in ("sectPr", "pPrChange"):
            for node in layout.findall(w(tag)):
                layout.remove(node)
        mark = layout.find(w("rPr"))
        if mark is None:
            mark = etree.SubElement(layout, w("rPr"))
        for node in [child for child in mark if child.tag in (w("ins"), w("del"), w("moveFrom"), w("moveTo"))]:
            mark.remove(node)
        mark.insert(0, _revision(mark, "ins", ids, author, stamp))
        paragraph.append(layout)
        inserted = _revision(paragraph, "ins", ids, author, stamp)
        for run in _new_runs(block, properties, paragraph):
            inserted.append(run)
        paragraph.append(inserted)
        after.addnext(paragraph)
        after = paragraph
        created.append(paragraph)
    return created


_RUN_HOSTS = frozenset({w("hyperlink"), w("smartTag")})


def _text_runs(paragraph: etree._Element) -> list[etree._Element]:
    """Runs a replacement can delete: direct (or inside a hyperlink), carrying text, never comment anchors."""
    runs = []
    for run in paragraph.iter(w("r")):
        parent = run.getparent()
        if parent is not paragraph and not (parent.tag in _RUN_HOSTS and parent.getparent() is paragraph):
            continue
        if run.find(w("commentReference")) is not None or run.find(w("annotationRef")) is not None:
            continue
        if _run_text(run):
            runs.append(run)
    return runs


def _simple(run: etree._Element) -> etree._Element:
    content = [child for child in run if child.tag != w("rPr")]
    if len(content) != 1 or content[0].tag != w("t"):
        raise DocumentError("The phrase starts or ends inside formatted content; replace the whole paragraph instead.")
    return content[0]


def _split(run: etree._Element, at: int) -> etree._Element:
    """Split a single-text run at a character offset; returns the new right-hand run (left stays in place)."""
    text = _simple(run)
    value = text.text or ""
    right = deepcopy(run)
    right_text = _simple(right)
    right_text.text = value[at:]
    right_text.set(XML_SPACE, "preserve")
    text.text = value[:at]
    text.set(XML_SPACE, "preserve")
    run.addnext(right)
    return right


def _phrase_runs(paragraph: etree._Element, find: str) -> list[etree._Element]:
    runs = _text_runs(paragraph)
    texts = [_run_text(run) for run in runs]
    full = "".join(texts)
    start = full.find(find)
    if start < 0:
        squeezed = re.sub(r"\s+", " ", find).strip()
        start = full.find(squeezed)
        find = squeezed
    if start < 0:
        raise DocumentError("The text to replace was not found in that paragraph; quote it exactly.")
    if full.find(find, start + 1) >= 0:
        raise DocumentError("That text appears more than once in the paragraph; quote more of the sentence.")
    end = start + len(find)
    chosen, position = [], 0
    for run, text in zip(runs, texts):
        first, last = position, position + len(text)
        position = last
        if last <= start or first >= end:
            continue
        target = run
        if end < last:
            _split(target, end - first)
        if start > first:
            target = _split(target, start - first)
        chosen.append(target)
    return chosen


def _replace(paragraph: etree._Element, find: str, text: str, author: str, stamp: str, ids: _Ids) -> None:
    if _tracked(paragraph):
        raise DocumentError("That paragraph already has tracked changes waiting to be accepted; add your text after "
                            "it (insert_after) instead of replacing it.")
    if any(True for _ in paragraph.iter(*(w(tag) for tag in _COMPLEX))):
        raise DocumentError("That paragraph holds fields, pictures or notes; add your text after it (insert_after) "
                            "instead of replacing it.")
    runs = _phrase_runs(paragraph, find) if find else _text_runs(paragraph)
    if not runs:
        raise DocumentError("That paragraph has no text to replace; use insert_after or append.")
    properties = _template_rpr(paragraph)
    for run in runs:
        for node in run.findall(w("t")):
            node.tag = w("delText")
            node.set(XML_SPACE, "preserve")
        wrapper = _revision(run, "del", ids, author, stamp)
        run.addprevious(wrapper)
        wrapper.append(run)
    container = runs[-1].getparent()
    while container.getparent() is not paragraph:
        container = container.getparent()
    inserted = _revision(paragraph, "ins", ids, author, stamp)
    for run in _new_runs(text, properties, paragraph):
        inserted.append(run)
    container.addnext(inserted)


def _append(paragraph: etree._Element, text: str, author: str, stamp: str, ids: _Ids) -> None:
    existing = _text(paragraph)
    prefix = " " if existing and not existing[-1].isspace() and not text[:1].isspace() else ""
    inserted = _revision(paragraph, "ins", ids, author, stamp)
    for run in _new_runs(prefix + text, _template_rpr(paragraph), paragraph):
        inserted.append(run)
    paragraph.append(inserted)


def _resolve(paragraphs: list[etree._Element], unique: set[str], edit: dict[str, Any]) -> etree._Element:
    match = _PARA_REF.match(str(edit.get("paragraph") or "").strip())
    if not match:
        raise DocumentError("Point each edit at a paragraph ref from the document you read (for example p1A2B3C4D).")
    if match.group(1):
        found = [p for p in paragraphs if (p.get(_q(W14, "paraId")) or "").upper() == match.group(1)]
        if len(found) != 1 or match.group(1) not in unique:
            raise DocumentError(f"Paragraph {edit['paragraph']} is no longer in the document; read it again.")
        return found[0]
    index = int(match.group(2))
    if index >= len(paragraphs):
        raise DocumentError(f"Paragraph {edit['paragraph']} is no longer in the document; read it again.")
    return paragraphs[index]


def _initials(name: str) -> str:
    return "".join(part[0] for part in name.split() if part[:1].isalnum()).upper()[:4] or "AI"


def _find(body: etree._Element, tag: str, cid: str) -> etree._Element | None:
    return next((node for node in body.iter(w(tag)) if node.get(w("id")) == cid), None)


def _reply(package: _Package, body: etree._Element, parent_id: str, author: str, text: str, stamp: str,
           ids: _Ids, para_ids: set[str]) -> str:
    name, nodes = _comment_nodes(package)
    parent = next((node for node in nodes if node.get(w("id")) == parent_id), None)
    if name is None or parent is None:
        raise DocumentError("The comment to reply to is no longer in the document.")
    root = package.xml(name)
    threaded = W14 in root.nsmap.values()
    cid = ids()
    comment = etree.SubElement(root, w("comment"), {w("id"): cid, w("author"): author, w("date"): stamp,
                                                    w("initials"): _initials(author)})
    lines = [line.strip() for line in _clean(text).split("\n") if line.strip()] or ["Done."]
    last_para = ""
    for number, line in enumerate(lines):
        paragraph = etree.SubElement(comment, w("p"))
        if threaded:
            last_para = _para_id(para_ids)
            paragraph.set(_q(W14, "paraId"), last_para)
            paragraph.set(_q(W14, "textId"), "77777777")
        layout = etree.SubElement(paragraph, w("pPr"))
        etree.SubElement(layout, w("pStyle"), {w("val"): "CommentText"})
        if number == 0:
            anchor = etree.SubElement(paragraph, w("r"))
            etree.SubElement(etree.SubElement(anchor, w("rPr")), w("rStyle"), {w("val"): "CommentReference"})
            etree.SubElement(anchor, w("annotationRef"))
        for run in _new_runs(line, None, paragraph):
            paragraph.append(run)
    package.touch(name)
    start, end = _find(body, "commentRangeStart", parent_id), _find(body, "commentRangeEnd", parent_id)
    if start is not None:
        start.addnext(start.makeelement(w("commentRangeStart"), {w("id"): cid}))
    if end is not None:
        end.addnext(end.makeelement(w("commentRangeEnd"), {w("id"): cid}))
    reference = _find(body, "commentReference", parent_id)
    host = reference.getparent() if reference is not None else None
    if host is None and end is not None and end.getparent().tag == w("p"):
        host = end.getnext()
    if host is not None:
        run = host.makeelement(w("r"))
        etree.SubElement(etree.SubElement(run, w("rPr")), w("rStyle"), {w("val"): "CommentReference"})
        etree.SubElement(run, w("commentReference"), {w("id"): cid})
        host.addnext(run)
    if threaded:
        _thread(package, parent, last_para, stamp, para_ids)
    return cid


def _thread(package: _Package, parent: etree._Element, child_para: str, stamp: str, para_ids: set[str]) -> None:
    """Link the reply under its parent (commentsExtended) and, when present, the modern-comment id parts."""
    last = [p for p in parent.iter(w("p"))][-1]
    parent_para = (last.get(_q(W14, "paraId")) or "").upper()
    if not parent_para:
        parent_para = _para_id(para_ids)
        last.set(_q(W14, "paraId"), parent_para)
    name = package.related(EXTENDED_REL)
    if name is None:
        root = etree.Element(_q(W15, "commentsEx"), nsmap={"mc": MC, "w15": W15})
        root.set(_q(MC, "Ignorable"), "w15")
        name = package.create_related(EXTENDED_REL, "commentsExtended.xml", EXTENDED_TYPE, root)
    extended = package.xml(name)
    if not any((entry.get(_q(W15, "paraId")) or "").upper() == parent_para for entry in extended):
        etree.SubElement(extended, _q(W15, "commentEx"), {_q(W15, "paraId"): parent_para, _q(W15, "done"): "0"})
    etree.SubElement(extended, _q(W15, "commentEx"), {_q(W15, "paraId"): child_para,
                                                      _q(W15, "paraIdParent"): parent_para, _q(W15, "done"): "0"})
    package.touch(name)
    durable = f"{secrets.randbelow(0x7FFFFFFE) + 1:08X}"
    ids_part = package.related(IDS_REL)
    if ids_part is not None:
        etree.SubElement(package.xml(ids_part), _q(W16CID, "commentId"),
                         {_q(W16CID, "paraId"): child_para, _q(W16CID, "durableId"): durable})
        package.touch(ids_part)
    extensible = package.related(EXTENSIBLE_REL)
    if extensible is not None:
        etree.SubElement(package.xml(extensible), _q(W16CEX, "commentExtensible"),
                         {_q(W16CEX, "durableId"): durable, _q(W16CEX, "dateUtc"): stamp})
        package.touch(extensible)


def apply_changes(data: bytes, *, author: str, edits: Iterable[dict[str, Any]] = (), reply_to: str | None = None,
                  reply: str = "", now: _dt.datetime | None = None) -> tuple[bytes, dict[str, Any]]:
    """Apply edits as tracked revisions by `author` and optionally reply under a comment; returns the new file."""
    edits = list(edits)
    if len(edits) > MAX_EDITS:
        raise DocumentError(f"At most {MAX_EDITS} edits at a time.")
    if not author.strip():
        raise DocumentError("An author is required for tracked changes.")
    package = _Package(data)
    document = package.xml(package.main)
    body = document.find(w("body"))
    if body is None:
        raise DocumentError("The document has no body.")
    comments_name = package.related(COMMENTS_REL)
    roots = [document] + ([package.xml(comments_name)] if comments_name else [])
    ids = _Ids(*roots)
    para_ids = {(node.get(_q(W14, "paraId")) or "").upper() for root in roots for node in root.iter(w("p"))}
    stamp = (now or _dt.datetime.now(_dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    paragraphs = _paragraphs(body)
    unique = _unique_para_ids(paragraphs)
    targets = [(_resolve(paragraphs, unique, edit), edit) for edit in edits]
    threaded = W14 in document.nsmap.values()
    last_inserted: dict[int, etree._Element] = {}
    applied = []
    for paragraph, edit in targets:
        mode, text = edit.get("mode"), str(edit.get("text") or "")
        if not text.strip() or len(text) > MAX_EDIT_TEXT:
            raise DocumentError(f"Each edit needs 1 to {MAX_EDIT_TEXT} characters of text.")
        if mode == "insert_after":
            after = last_inserted.get(id(paragraph), paragraph)
            created = _insert_after(after, _body_template(paragraph, paragraphs), text, author, stamp, ids,
                                    para_ids if threaded else None)
            last_inserted[id(paragraph)] = created[-1]
        elif mode == "replace":
            _replace(paragraph, str(edit.get("find") or ""), text, author, stamp, ids)
        elif mode == "append":
            _append(paragraph, text, author, stamp, ids)
        else:
            raise DocumentError("Each edit's mode is insert_after, replace or append.")
        applied.append({"paragraph": edit["paragraph"], "mode": mode, "characters": len(text)})
    package.touch(package.main)
    replied = ""
    if reply.strip() and reply_to:
        replied = _reply(package, body, reply_to, author, reply, stamp, ids, para_ids)
    elif reply.strip():
        raise DocumentError("There is no comment to reply to.")
    return package.save(), {"applied": applied, "reply": replied}
