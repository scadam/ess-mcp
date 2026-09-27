"""Writes the Word scene's draft policy: python infra/demo/make_demo_document.py [output.docx]

A clean Word document (modern paragraph ids, real heading styles) with a gap for HR to fill (section 4) and a
sentence that breaks the data-handling standard for Compliance to catch (section 5). The presenter uploads it to
OneDrive or SharePoint and adds the @mention comments live.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
DEFAULT = Path(__file__).resolve().parents[2] / "demo_agent" / "docs" / "assets" / "Hybrid and overseas working guidelines (draft).docx"

PARAGRAPHS = [
    ("Title", "Hybrid and overseas working guidelines"),
    ("Subtitle", "Draft v0.3 · Owner: HR Business Partnering · Not yet approved for publication"),
    ("Heading1", "1. Purpose"),
    ("Normal", "These guidelines explain how colleagues combine office and remote working, and what to arrange before "
               "working temporarily from another country. They apply alongside the Code of Conduct and the "
               "Information Security Policy."),
    ("Heading1", "2. Who they cover"),
    ("Normal", "All permanent and fixed-term employees of Caldova Group in the UK and Ireland. Contractors follow the "
               "terms agreed with their agency."),
    ("Heading1", "3. Hybrid working"),
    ("Normal", "Most roles can work up to three days a week from home by agreement with their line manager. Roles "
               "that must be on site, such as branches, trading floors and data centres, agree their pattern locally."),
    ("Heading1", "4. Working temporarily from another country"),
    ("Normal", "Colleagues sometimes ask to work from another country for a short period, for example to spend time "
               "with family abroad. Talk to your line manager before making any plans."),
    ("Heading1", "5. Equipment, data and conduct"),
    ("Normal", "Use your bank laptop and connect through the VPN. If the VPN is unavailable, you may email documents "
               "to a personal address so that you can keep working."),
    ("Normal", "Keep printed documents secure and shred them after use."),
    ("Heading1", "6. Expenses"),
    ("Normal", "Travel to and from another country for personal reasons is not reimbursed. Equipment for working at "
               "home follows the Expenses Policy."),
    ("Heading1", "7. Approvals"),
    ("Normal", "Requests go to your line manager first. HR confirms the outcome and records it in Workday."),
]

STYLES = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="{W}">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Aptos" w:hAnsi="Aptos" w:eastAsia="Aptos" w:cs="Aptos"/>
<w:sz w:val="22"/><w:szCs w:val="22"/><w:lang w:val="en-GB"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="264" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="character" w:default="1" w:styleId="DefaultParagraphFont"><w:name w:val="Default Paragraph Font"/>
<w:uiPriority w:val="1"/><w:semiHidden/><w:unhideWhenUsed/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:qFormat/><w:pPr><w:spacing w:after="60"/></w:pPr><w:rPr><w:b/><w:color w:val="1F3864"/><w:sz w:val="44"/><w:szCs w:val="44"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:qFormat/><w:rPr><w:color w:val="595959"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:qFormat/><w:pPr><w:keepNext/><w:spacing w:before="280" w:after="80"/><w:outlineLvl w:val="0"/></w:pPr>
<w:rPr><w:b/><w:color w:val="2F5496"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="CommentText"><w:name w:val="annotation text"/><w:basedOn w:val="Normal"/>
<w:rPr><w:sz w:val="20"/><w:szCs w:val="20"/></w:rPr></w:style>
<w:style w:type="character" w:styleId="CommentReference"><w:name w:val="annotation reference"/>
<w:basedOn w:val="DefaultParagraphFont"/><w:rPr><w:sz w:val="16"/><w:szCs w:val="16"/></w:rPr></w:style>
</w:styles>"""

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
</Relationships>"""

CORE = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"><dc:title>Hybrid and overseas working guidelines</dc:title>
<dc:creator>HR Business Partnering</dc:creator>
<dcterms:created xsi:type="dcterms:W3CDTF">2026-09-26T09:00:00Z</dcterms:created></cp:coreProperties>"""

APP = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"><Application>Group Functions Autopilot demo</Application></Properties>"""


def document_xml() -> str:
    body = []
    for number, (style, text) in enumerate(PARAGRAPHS, start=1):
        layout = "" if style == "Normal" else f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>'
        body.append(f'<w:p w14:paraId="1A2B{number:04X}" w14:textId="3C4D{number:04X}">{layout}'
                    f'<w:r><w:t xml:space="preserve">{escape(text)}</w:t></w:r></w:p>')
    section = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1440" w:right="1440" w:bottom="1440" '
               'w:left="1440" w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<w:document xmlns:w="{W}" xmlns:w14="{W14}" '
            f'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
            f'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" mc:Ignorable="w14">'
            f'<w:body>{"".join(body)}{section}</w:body></w:document>')


def write(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    parts = {"[Content_Types].xml": CONTENT_TYPES, "_rels/.rels": ROOT_RELS, "docProps/core.xml": CORE,
             "docProps/app.xml": APP, "word/document.xml": document_xml(), "word/styles.xml": STYLES,
             "word/settings.xml": SETTINGS, "word/_rels/document.xml.rels": DOCUMENT_RELS}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            archive.writestr(zipfile.ZipInfo(name, date_time=(2026, 9, 26, 9, 0, 0)), text.encode("utf-8"),
                             compress_type=zipfile.ZIP_DEFLATED)
    return path


if __name__ == "__main__":
    print(write(Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT))
