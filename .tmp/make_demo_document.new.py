"""Writes the Word scene's draft policy: python infra/demo/make_demo_document.py [output.docx]

A two-page draft as HR would circulate it (document control, header and footer, tables and a bulleted list), with
a gap for HR to fill (section 4) and sentences that break the data-handling standard for Compliance to catch
(section 5). Every paragraph has a stable w14:paraId so the colleagues' tracked edits can point at it. The
presenter uploads it to OneDrive or SharePoint and adds the @mention comments live.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
DEFAULT = Path(__file__).resolve().parents[2] / "demo_agent" / "docs" / "assets" / "Hybrid and overseas working guidelines (draft).docx"

PAGE_WIDTH, PAGE_HEIGHT, MARGIN = 11906, 16838, 1418  # A4, 2.5 cm margins
TEXT_WIDTH = PAGE_WIDTH - 2 * MARGIN
NAVY, ACCENT, RULE, SHADE, CALLOUT = "1F3864", "C55A11", "BFBFBF", "EEF2F8", "FFF4E5"

CONTROL = [("Owner", "Scott Adams, HR Business Partner"),
           ("Status", "Draft for review. Not yet approved."),
           ("Applies to", "Employees of Caldova Group in the UK and Ireland"),
           ("Related policies", "Code of Conduct · Information Security Policy · Expenses Policy"),
           ("Approved by", "People Leadership Team (pending)"),
           ("Next review", "March 2027")]

BLOCKS: list[tuple] = [
    ("Title", "Hybrid and overseas working guidelines"),
    ("Subtitle", "Caldova Group · Draft v0.3 for review"),
    ("callout", "**For review.** Section 4 still needs our rules for working temporarily from another country, and "
                "section 5 needs a compliance review, before this draft goes to the People Leadership Team. Add a "
                "comment on the section and @mention the reviewer."),
    ("gap",),
    ("control", CONTROL),
    ("Heading1", "1. Purpose"),
    ("Normal", "These guidelines explain how colleagues combine office and remote working, and what to arrange before "
               "working temporarily from another country. They sit alongside the Code of Conduct, the Information "
               "Security Policy and the Expenses Policy, which apply wherever you work."),
    ("Heading1", "2. Who they cover"),
    ("Normal", "All permanent and fixed-term employees of Caldova Group in the UK and Ireland, including colleagues on "
               "secondment to other group companies. Contractors and agency workers follow the terms agreed with their "
               "agency."),
    ("Heading1", "3. Hybrid working"),
    ("Normal", "Most roles can combine office and home working. Agree your pattern with your line manager at the start "
               "of each quarter and record it in Workday."),
    ("table", [3000, 3870, TEXT_WIDTH - 6870], ("Role type", "Pattern", "Agreed by"), [
        ("**Office-based** (group functions, technology, operations)", "Up to three days a week from home",
         "Line manager"),
        ("**Client-facing** (relationship managers, advisers, sales)",
         "Up to two days a week from home; client calls on recorded lines only", "Line manager and desk head"),
        ("**Site-based** (branches, trading floors, data centres)", "A local rota", "Site manager")]),
    ("Normal", "Core hours are 10:00 to 16:00 UK time, whatever your pattern. Team days are set by each team and take "
               "priority over home working."),
    ("Heading1", "4. Working temporarily from another country"),
    ("Normal", "Colleagues sometimes ask to work from another country for a short period, for example to spend time "
               "with family abroad or to extend a holiday."),
    ("Normal", "Talk to your line manager before making any plans. Requests are considered case by case."),
    ("Heading1", "5. Equipment, data and conduct"),
    ("Normal", "Use your bank laptop and connect through the VPN. If the VPN is unavailable, you may email documents "
               "to a personal address so that you can keep working."),
    ("Normal", "Keep printed documents secure and shred them after use."),
    ("Normal", "Take calls somewhere you won't be interrupted, and lock your screen when you step away."),
    ("Heading1", "6. Equipment and expenses"),
    ("Normal", "Travel to and from another country for personal reasons is not reimbursed. Home-working equipment is "
               "ordered from the IT catalogue in ServiceNow:"),
    ("Bullet", "a second monitor and a headset for every hybrid worker"),
    ("Bullet", "a chair or desk after a workstation assessment"),
    ("Heading1", "7. Approvals and records"),
    ("Normal", "Requests go to your line manager first. HR confirms the outcome and records it in Workday."),
    ("table", [3400, 3470, TEXT_WIDTH - 6870], ("Request", "Who decides", "Recorded in"), [
        ("A hybrid working pattern", "Line manager", "Workday"),
        ("Working from another country", "Line manager, then HR", "Workday"),
        ("Home-working equipment", "Line manager", "ServiceNow")]),
    ("Heading1", "8. Questions"),
    ("Normal", "Most questions can be answered in Teams straight away."),
    ("table", [4200, TEXT_WIDTH - 4200], ("Topic", "Ask"), [
        ("Working patterns, requests and approvals", "HR Agent in Teams, or your HR Business Partner"),
        ("Laptops, the VPN and access", "IT Service Agent in Teams, or the IT Service Desk"),
        ("Client data, conduct and personal dealing", "Compliance Agent in Teams, or Compliance Advisory")]),
    ("Heading1", "Document history"),
    ("table", [1000, 1700, 1900, TEXT_WIDTH - 4600], ("Version", "Date", "Author", "Changes"), [
        ("0.1", "28 Aug 2026", "Scott Adams", "Outline agreed with the People Leadership Team"),
        ("0.2", "12 Sep 2026", "Scott Adams", "Sections 1 to 3 drafted"),
        ("0.3", "24 Sep 2026", "Scott Adams", "Sections 4 to 8 drafted for HR and Compliance review")]),
]


class _ParaIds:
    """Sequential w14 paragraph and text ids (below 0x80000000, as Word requires), unique across the parts."""

    def __init__(self) -> None:
        self.number = 0

    def __call__(self) -> str:
        self.number += 1
        return f'w14:paraId="1A2B{self.number:04X}" w14:textId="3C4D{self.number:04X}"'


def _runs(text: str, props: str = "") -> str:
    runs = []
    for number, chunk in enumerate(text.split("**")):
        if chunk:
            properties = ("<w:b/><w:bCs/>" if number % 2 else "") + props
            rpr = f"<w:rPr>{properties}</w:rPr>" if properties else ""
            runs.append(f'<w:r>{rpr}<w:t xml:space="preserve">{escape(chunk)}</w:t></w:r>')
    return "".join(runs)


def _p(ids: _ParaIds, text: str = "", style: str = "", layout: str = "", props: str = "") -> str:
    inner = (f'<w:pStyle w:val="{style}"/>' if style else "") + layout
    return f'<w:p {ids()}>{f"<w:pPr>{inner}</w:pPr>" if inner else ""}{_runs(text, props)}</w:p>'


def _borders(tag: str, sides: dict[str, str]) -> str:
    return f"<w:{tag}>" + "".join(f"<w:{side}{value}/>" for side, value in sides.items()) + f"</w:{tag}>"


def _grid_table(ids: _ParaIds, widths: list[int], rows: list[tuple[str, ...]], *, header: tuple[str, ...] = (),
                first_column: bool = False) -> str:
    line = f' w:val="single" w:sz="4" w:space="0" w:color="{RULE}"'
    borders = _borders("tblBorders", {side: line for side in ("top", "left", "bottom", "right", "insideH", "insideV")})
    table = [f'<w:tbl><w:tblPr><w:tblW w:w="{sum(widths)}" w:type="dxa"/>{borders}<w:tblLayout w:type="fixed"/>'
             '<w:tblCellMar><w:top w:w="57" w:type="dxa"/><w:left w:w="113" w:type="dxa"/><w:bottom w:w="57" '
             'w:type="dxa"/><w:right w:w="113" w:type="dxa"/></w:tblCellMar><w:tblLook w:val="04A0" w:firstRow="1" '
             'w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr><w:tblGrid>'
             + "".join(f'<w:gridCol w:w="{width}"/>' for width in widths) + "</w:tblGrid>"]
    for index, row in enumerate(([header] if header else []) + list(rows)):
        heading_row = bool(header) and index == 0
        cells = []
        for column, (width, text) in enumerate(zip(widths, row)):
            shaded = heading_row or (first_column and column == 0)
            shade = f'<w:shd w:val="clear" w:color="auto" w:fill="{SHADE}"/>' if shaded else ""
            text = f"**{text}**" if shaded and "**" not in text else text
            cells.append(f'<w:tc><w:tcPr><w:tcW w:w="{width}" w:type="dxa"/>{shade}</w:tcPr>'
                         f'{_p(ids, text, "TableText")}</w:tc>')
        row_props = "<w:trPr><w:cantSplit/><w:tblHeader/></w:trPr>" if heading_row else "<w:trPr><w:cantSplit/></w:trPr>"
        table.append(f"<w:tr>{row_props}{''.join(cells)}</w:tr>")
    return "".join(table) + "</w:tbl>"


def _callout(ids: _ParaIds, text: str) -> str:
    none = ' w:val="nil"'
    borders = _borders("tblBorders", {"top": none, "left": f' w:val="single" w:sz="24" w:space="0" w:color="{ACCENT}"',
                                      "bottom": none, "right": none, "insideH": none, "insideV": none})
    return (f'<w:tbl><w:tblPr><w:tblW w:w="{TEXT_WIDTH}" w:type="dxa"/>{borders}<w:tblLayout w:type="fixed"/>'
            '<w:tblCellMar><w:top w:w="85" w:type="dxa"/><w:left w:w="170" w:type="dxa"/><w:bottom w:w="85" '
            'w:type="dxa"/><w:right w:w="170" w:type="dxa"/></w:tblCellMar><w:tblLook w:val="0000" w:firstRow="0" '
            'w:lastRow="0" w:firstColumn="0" w:lastColumn="0" w:noHBand="1" w:noVBand="1"/></w:tblPr>'
            f'<w:tblGrid><w:gridCol w:w="{TEXT_WIDTH}"/></w:tblGrid><w:tr><w:tc><w:tcPr><w:tcW w:w="{TEXT_WIDTH}" '
            f'w:type="dxa"/><w:shd w:val="clear" w:color="auto" w:fill="{CALLOUT}"/></w:tcPr>'
            f'{_p(ids, text, "TableText")}</w:tc></w:tr></w:tbl>')


def _root(tag: str, inner: str) -> str:
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<w:{tag} xmlns:w="{W}" xmlns:w14="{W14}" '
            f'xmlns:r="{R}" xmlns:mc="{MC}" mc:Ignorable="w14">{inner}</w:{tag}>')


def document_xml(ids: _ParaIds) -> str:
    body = []
    for block in BLOCKS:
        kind = block[0]
        if kind == "callout":
            body.append(_callout(ids, block[1]))
        elif kind == "gap":
            body.append(_p(ids, layout='<w:spacing w:after="0"/>'))
        elif kind == "control":
            body.append(_grid_table(ids, [2400, TEXT_WIDTH - 2400], block[1], first_column=True))
        elif kind == "table":
            body.append(_grid_table(ids, block[1], block[3], header=block[2]))
            body.append(_p(ids, layout='<w:spacing w:after="0"/>'))  # Word needs a paragraph between blocks.
        elif kind == "Bullet":
            body.append(_p(ids, block[1], "ListParagraph", '<w:numPr><w:ilvl w:val="0"/><w:numId w:val="1"/></w:numPr>'))
        else:
            body.append(_p(ids, block[1], "" if kind == "Normal" else kind))
    section = ('<w:sectPr><w:headerReference w:type="default" r:id="rId4"/><w:footerReference w:type="default" '
               f'r:id="rId5"/><w:pgSz w:w="{PAGE_WIDTH}" w:h="{PAGE_HEIGHT}"/><w:pgMar w:top="{MARGIN}" '
               f'w:right="{MARGIN}" w:bottom="{MARGIN}" w:left="{MARGIN}" w:header="709" w:footer="709" w:gutter="0"/>'
               '<w:cols w:space="708"/><w:docGrid w:linePitch="360"/></w:sectPr>')
    return _root("document", f'<w:body>{"".join(body)}{section}</w:body>')


def header_xml(ids: _ParaIds) -> str:
    text = (f'{_runs("Caldova Group · HR Business Partnering")}<w:r><w:tab/></w:r>'
            f'{_runs("DRAFT v0.3 · for review", f"<w:b/><w:bCs/><w:color w:val=\"{ACCENT}\"/>")}')
    return _root("hdr", f'<w:p {ids()}><w:pPr><w:pStyle w:val="Header"/></w:pPr>{text}</w:p>')


def footer_xml(ids: _ParaIds) -> str:
    def field(name: str) -> str:
        return f'<w:fldSimple w:instr=" {name} "><w:r><w:t>1</w:t></w:r></w:fldSimple>'

    text = (f'{_runs("Internal · Hybrid and overseas working guidelines")}<w:r><w:tab/></w:r>{_runs("Page ")}'
            f'{field("PAGE")}{_runs(" of ")}{field("NUMPAGES")}')
    return _root("ftr", f'<w:p {ids()}><w:pPr><w:pStyle w:val="Footer"/></w:pPr>{text}</w:p>')


STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Aptos" w:hAnsi="Aptos" w:eastAsia="Aptos" w:cs="Aptos"/>
<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-GB" w:eastAsia="en-US" w:bidi="ar-SA"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="140" w:line="269" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="character" w:default="1" w:styleId="DefaultParagraphFont"><w:name w:val="Default Paragraph Font"/>
<w:uiPriority w:val="1"/><w:semiHidden/><w:unhideWhenUsed/></w:style>
<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:uiPriority w:val="99"/>
<w:semiHidden/><w:unhideWhenUsed/><w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/>
<w:left w:w="108" w:type="dxa"/><w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>
<w:style w:type="numbering" w:default="1" w:styleId="NoList"><w:name w:val="No List"/><w:uiPriority w:val="99"/>
<w:semiHidden/><w:unhideWhenUsed/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:uiPriority w:val="10"/><w:qFormat/><w:pPr><w:spacing w:after="40" w:line="240" w:lineRule="auto"/><w:contextualSpacing/></w:pPr>
<w:rPr><w:b/><w:bCs/><w:color w:val="{NAVY}"/><w:sz w:val="48"/><w:szCs w:val="48"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:uiPriority w:val="11"/><w:qFormat/><w:pPr><w:spacing w:after="240"/></w:pPr><w:rPr><w:color w:val="595959"/>
<w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:uiPriority w:val="9"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:pBdr><w:bottom w:val="single" w:sz="4" w:space="2"
w:color="D9D9D9"/></w:pBdr><w:spacing w:before="320" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr>
<w:rPr><w:b/><w:bCs/><w:color w:val="{NAVY}"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListParagraph"><w:name w:val="List Paragraph"/><w:basedOn w:val="Normal"/>
<w:uiPriority w:val="34"/><w:qFormat/><w:pPr><w:spacing w:after="60"/><w:ind w:left="720"/><w:contextualSpacing/></w:pPr></w:style>
<w:style w:type="paragraph" w:customStyle="1" w:styleId="TableText"><w:name w:val="Table Text"/><w:basedOn w:val="Normal"/>
<w:qFormat/><w:pPr><w:spacing w:after="0" w:line="252" w:lineRule="auto"/></w:pPr><w:rPr><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Header"><w:name w:val="header"/><w:basedOn w:val="Normal"/><w:uiPriority w:val="99"/>
<w:unhideWhenUsed/><w:pPr><w:tabs><w:tab w:val="right" w:pos="{TEXT_WIDTH}"/></w:tabs><w:spacing w:after="0" w:line="240"
w:lineRule="auto"/></w:pPr><w:rPr><w:color w:val="7F7F7F"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Footer"><w:name w:val="footer"/><w:basedOn w:val="Normal"/><w:uiPriority w:val="99"/>
<w:unhideWhenUsed/><w:pPr><w:tabs><w:tab w:val="right" w:pos="{TEXT_WIDTH}"/></w:tabs><w:spacing w:after="0" w:line="240"
w:lineRule="auto"/></w:pPr><w:rPr><w:color w:val="7F7F7F"/><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="CommentText"><w:name w:val="annotation text"/><w:basedOn w:val="Normal"/>
<w:uiPriority w:val="99"/><w:unhideWhenUsed/><w:pPr><w:spacing w:line="240" w:lineRule="auto"/></w:pPr>
<w:rPr><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>
<w:style w:type="character" w:styleId="CommentReference"><w:name w:val="annotation reference"/>
<w:basedOn w:val="DefaultParagraphFont"/><w:uiPriority w:val="99"/><w:semiHidden/><w:unhideWhenUsed/>
<w:rPr><w:sz w:val="16"/><w:szCs w:val="16"/></w:rPr></w:style>
</w:styles>"""

NUMBERING = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:numbering xmlns:w="{W}"><w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/>
<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="\u2022"/><w:lvlJc w:val="left"/>
<w:pPr><w:ind w:left="720" w:hanging="360"/></w:pPr><w:rPr><w:rFonts w:ascii="Aptos" w:hAnsi="Aptos" w:hint="default"/></w:rPr></w:lvl>
</w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>"""

SETTINGS = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="{W}"><w:defaultTabStop w:val="720"/><w:characterSpacingControl w:val="doNotCompress"/>
<w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat>
</w:settings>"""

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>
<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>
<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

DOCUMENT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>
<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>
<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>
<Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>
</Relationships>"""

CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>Hybrid and overseas working guidelines</dc:title>
<dc:subject>Draft v0.3 for review</dc:subject><dc:creator>Scott Adams</dc:creator><cp:lastModifiedBy>Scott Adams</cp:lastModifiedBy>
<dcterms:created xsi:type="dcterms:W3CDTF">2026-09-24T09:00:00Z</dcterms:created>
<dcterms:modified xsi:type="dcterms:W3CDTF">2026-09-24T09:00:00Z</dcterms:modified></cp:coreProperties>"""

APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Group Functions Autopilot demo</Application><Company>Caldova Group</Company></Properties>"""


def write(path: Path) -> Path:
    ids = _ParaIds()
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = {"[Content_Types].xml": CONTENT_TYPES, "_rels/.rels": ROOT_RELS, "docProps/core.xml": CORE,
             "docProps/app.xml": APP, "word/document.xml": document_xml(ids), "word/header1.xml": header_xml(ids),
             "word/footer1.xml": footer_xml(ids), "word/styles.xml": STYLES, "word/numbering.xml": NUMBERING,
             "word/settings.xml": SETTINGS, "word/_rels/document.xml.rels": DOCUMENT_RELS}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            archive.writestr(zipfile.ZipInfo(name, date_time=(2026, 9, 24, 9, 0, 0)), text.encode("utf-8"),
                             compress_type=zipfile.ZIP_DEFLATED)
    return path


if __name__ == "__main__":
    print(write(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT))
