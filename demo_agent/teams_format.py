"""Model Markdown rendered for Teams: HTML for Graph chat messages and mail, Adaptive Cards for bot messages.

Graph chat messages render headings, lists, tables and code as HTML. Bot text messages only reliably render
bold, italic and links, so structured answers go to bots as an Adaptive Card (TextBlock Markdown plus Table).
Everything from the model is escaped; only http(s) and mailto links become anchors.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from typing import Any

_FENCE = re.compile(r"^\s*(`{3,}|~{3,})\s*([\w+#.-]*)\s*$")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_ITEM = re.compile(r"^(\s*)(?:([-*+•])|(\d{1,3})[.)])\s+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
_BOLD_LINE = re.compile(r"^\s*(\*\*|__)([^*_].*?)\1\s*:?\s*$")
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_LINK = re.compile(r"\[([^\]\n]{1,300})\]\(\s*((?:https?://|mailto:)[^\s()<>]{1,2000})\s*\)")
_BOLD = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__")
_ITALIC = re.compile(r"(?<![\w*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?![\w*])|(?<![\w_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\w_])")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
MAX_TABLE_ROWS = 60
MAX_TABLE_COLUMNS = 8


@dataclass
class Block:
    kind: str  # heading, paragraph, list, table, code, quote, rule
    text: str = ""
    level: int = 0
    ordered: bool = False
    items: list[tuple[str, "Block | None"]] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)
    align: list[str] = field(default_factory=list)
    children: list["Block"] = field(default_factory=list)


def _cells(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    return [cell.strip().replace("\\|", "|") for cell in re.split(r"(?<!\\)\|", line)]


def _list_block(entries: list[tuple[int, bool, str]]) -> Block:
    """Nest items by indentation: deeper than the first item's indent belongs to the previous item."""
    base = entries[0][0]
    block = Block("list", ordered=entries[0][1])
    index = 0
    while index < len(entries):
        indent, _ordered, text = entries[index]
        index += 1
        nested: list[tuple[int, bool, str]] = []
        while index < len(entries) and entries[index][0] > base:
            nested.append(entries[index])
            index += 1
        block.items.append((text, _list_block(nested) if nested else None))
    return block


def parse(text: str) -> list[Block]:
    lines = (text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[Block] = []
    paragraph: list[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append(Block("paragraph", "\n".join(line.strip() for line in paragraph)))
            paragraph.clear()

    index = 0
    while index < len(lines):
        line = lines[index]
        fence = _FENCE.match(line)
        if fence:
            flush()
            marker, body = fence.group(1), []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(marker[0] * len(marker)):
                body.append(lines[index])
                index += 1
            blocks.append(Block("code", "\n".join(body), level=0, align=[fence.group(2)]))
            index += 1
            continue
        if not line.strip():
            flush()
            index += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            blocks.append(Block("heading", heading.group(2), level=len(heading.group(1))))
            index += 1
            continue
        if _RULE.match(line):
            flush()
            blocks.append(Block("rule"))
            index += 1
            continue
        if "|" in line and index + 1 < len(lines) and _TABLE_SEP.match(lines[index + 1]):
            flush()
            header = _cells(line)
            align = ["center" if cell.strip().startswith(":") and cell.strip().endswith(":") else
                     "right" if cell.strip().endswith(":") else "left" for cell in _cells(lines[index + 1])]
            rows = [header]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_cells(lines[index]))
                index += 1
            width = min(max(len(row) for row in rows), MAX_TABLE_COLUMNS)
            rows = [(row + [""] * width)[:width] for row in rows[:MAX_TABLE_ROWS + 1]]
            blocks.append(Block("table", rows=rows, align=(align + ["left"] * width)[:width]))
            continue
        quote = _QUOTE.match(line)
        if quote:
            flush()
            inner = []
            while index < len(lines) and _QUOTE.match(lines[index]):
                inner.append(_QUOTE.match(lines[index]).group(1))
                index += 1
            blocks.append(Block("quote", children=parse("\n".join(inner))))
            continue
        item = _ITEM.match(line)
        if item:
            flush()
            entries: list[tuple[int, bool, str]] = []
            while index < len(lines):
                current = _ITEM.match(lines[index])
                if current:
                    indent = len(current.group(1).replace("\t", "    "))
                    entries.append((indent, current.group(3) is not None, current.group(4).strip()))
                elif lines[index].strip() and entries and lines[index][:1] in " \t":
                    indent, ordered, text = entries[-1]
                    entries[-1] = (indent, ordered, text + " " + lines[index].strip())
                else:
                    break
                index += 1
            blocks.append(_list_block(entries))
            continue
        bold = _BOLD_LINE.match(line)
        if bold and not paragraph:
            blocks.append(Block("heading", bold.group(2).strip().rstrip(":"), level=3))
            index += 1
            continue
        paragraph.append(line)
        index += 1
    flush()
    return blocks


# ── HTML (Graph chat messages and mail) ──
def _emphasis(escaped: str) -> str:
    escaped = _BOLD.sub(lambda m: f"<strong>{m.group(1) or m.group(2)}</strong>", escaped)
    escaped = _ITALIC.sub(lambda m: f"<em>{m.group(1) or m.group(2)}</em>", escaped)
    return _STRIKE.sub(lambda m: f"<s>{m.group(1)}</s>", escaped)


def _inline_html(text: str) -> str:
    codes: list[str] = []

    def keep(match: re.Match[str]) -> str:
        codes.append(match.group(1))
        return f"\x00{len(codes) - 1}\x00"

    text = _CODE_SPAN.sub(keep, text)
    links: list[tuple[str, str]] = []

    def link(match: re.Match[str]) -> str:
        links.append((match.group(1), match.group(2)))
        return f"\x01{len(links) - 1}\x01"

    text = _emphasis(html.escape(_LINK.sub(link, text), quote=False))
    text = re.sub("\x01(\\d+)\x01", lambda m: '<a href="{}">{}</a>'.format(
        html.escape(links[int(m.group(1))][1], quote=True),
        _emphasis(html.escape(links[int(m.group(1))][0], quote=False))), text)
    return re.sub("\x00(\\d+)\x00", lambda m: f"<code>{html.escape(codes[int(m.group(1))], quote=False)}</code>", text)


def _list_html(block: Block) -> str:
    tag = "ol" if block.ordered else "ul"
    items = "".join(f"<li>{_inline_html(text)}{_list_html(child) if child else ''}</li>" for text, child in block.items)
    return f"<{tag}>{items}</{tag}>"


def _blocks_html(blocks: list[Block]) -> str:
    parts: list[str] = []
    for block in blocks:
        if block.kind == "heading":
            level = 2 if block.level <= 2 else 3
            parts.append(f"<h{level}>{_inline_html(block.text)}</h{level}>")
        elif block.kind == "paragraph":
            parts.append("<p>" + "<br>".join(_inline_html(line) for line in block.text.split("\n")) + "</p>")
        elif block.kind == "list":
            parts.append(_list_html(block))
        elif block.kind == "table":
            head = "".join(f"<th>{_inline_html(cell)}</th>" for cell in block.rows[0])
            body = "".join("<tr>" + "".join(f"<td>{_inline_html(cell)}</td>" for cell in row) + "</tr>"
                           for row in block.rows[1:])
            parts.append(f"<table><tr>{head}</tr>{body}</table>")
        elif block.kind == "code":
            parts.append(f"<pre>{html.escape(block.text, quote=False)}</pre>")
        elif block.kind == "quote":
            parts.append(f"<blockquote>{_blocks_html(block.children)}</blockquote>")
        elif block.kind == "rule":
            parts.append("<hr>")
    return "".join(parts)


def to_html(text: str) -> str:
    """Teams chat-message / mail HTML for model Markdown."""
    return _blocks_html(parse(text)) or "<p></p>"


# ── Adaptive Card (bot messages) ──
def _inline_card(text: str) -> str:
    """Keep the TextBlock Markdown subset (bold, italic, links); drop what Teams would show literally."""
    text = _CODE_SPAN.sub(lambda m: m.group(1), text)
    text = _STRIKE.sub(lambda m: m.group(1), text)
    text = _ITALIC.sub(lambda m: f"_{m.group(1) or m.group(2)}_", text)
    return re.sub(r"__(?=\S)(.+?)(?<=\S)__", r"**\1**", text)


def _text_block(text: str, **style: Any) -> dict[str, Any]:
    return {"type": "TextBlock", "text": text, "wrap": True, **style}


def _list_lines(block: Block, depth: int = 0) -> list[str]:
    lines = []
    for number, (text, child) in enumerate(block.items, start=1):
        marker = f"{number}." if block.ordered else "-"
        lines.append((f"{marker} " if depth == 0 else "\u2003" * depth + "◦ ") + _inline_card(text))
        if child:
            lines += _list_lines(child, depth + 1)
    return lines


def _card_elements(blocks: list[Block]) -> list[dict[str, Any]]:
    elements: list[dict[str, Any]] = []
    separate = False
    for block in blocks:
        element: dict[str, Any] | None = None
        if block.kind == "heading":
            element = _text_block(_inline_card(block.text), weight="Bolder",
                                  size="Medium" if block.level <= 2 else "Default", spacing="Medium")
        elif block.kind == "paragraph":
            element = _text_block("\n\n".join(_inline_card(line) for line in block.text.split("\n")))
        elif block.kind == "list":
            element = _text_block("\r".join(_list_lines(block)))
        elif block.kind == "table":
            rows = [{"type": "TableRow", "cells": [
                {"type": "TableCell", "items": [_text_block(_inline_card(cell), **({"weight": "Bolder"} if row_index == 0 else {}))]}
                for cell in row]} for row_index, row in enumerate(block.rows)]
            element = {"type": "Table", "firstRowAsHeaders": True, "showGridLines": True, "gridStyle": "accent",
                       "columns": [{"width": 1} for _ in block.rows[0]], "rows": rows}
        elif block.kind == "code":
            element = _text_block(block.text, fontType="Monospace")
        elif block.kind == "quote":
            element = {"type": "Container", "style": "emphasis", "items": _card_elements(block.children) or [_text_block(" ")]}
        elif block.kind == "rule":
            separate = True
            continue
        if element is not None:
            if separate:
                element["separator"] = True
                separate = False
            elements.append(element)
    return elements


def to_card(text: str, *, title: str = "", footer: str = "") -> dict[str, Any]:
    body = [_text_block(title, weight="Bolder", size="Medium")] if title else []
    body += _card_elements(parse(text)) or [_text_block(" ")]
    if footer:
        body.append(_text_block(footer, isSubtle=True, size="Small", spacing="Medium"))
    return {"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.5", "msteams": {"width": "Full"}, "body": body}


def is_structured(text: str) -> bool:
    """True when plain bot text would show Markdown literally (headings, tables, lists, code or rules)."""
    blocks = parse(text)
    lists = sum(len(block.items) for block in blocks if block.kind == "list")
    return any(block.kind in {"heading", "table", "code", "quote", "rule"} for block in blocks) or lists >= 2


def summary(text: str, limit: int = 140) -> str:
    """First meaningful line as plain text, for notification previews."""
    for block in parse(text):
        raw = block.text if block.kind in {"heading", "paragraph"} else (block.items[0][0] if block.items else "")
        plain = re.sub(r"[*_`~]", "", _LINK.sub(lambda m: m.group(1), raw.split("\n")[0])).strip()
        if plain:
            return plain[:limit]
    return ""
