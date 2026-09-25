"""Model Markdown rendered for Teams chat HTML and Adaptive Cards."""

from __future__ import annotations

import json
import unittest

from demo_agent.teams_format import is_structured, parse, summary, to_card, to_html

REPORT = """Your team review shows the biggest pressure points are **operational backlog**.

**Team Overview**
- Headcount: 3 direct reports in **HR Services Department**
- Roles:
  - Director, Payroll Operations
  - Director, Recruiting Services

### IT Health
| Priority | Open | Breached |
|---|---:|---:|
| P1 | 17 | 13 |
| P2 | 27 | 4 |

1. Clear the `P1` queue
2. See [the dashboard](https://example.com/d?a=1&b=2)
"""


class TeamsFormatTests(unittest.TestCase):
    def test_html_renders_headings_lists_tables_links_and_code(self) -> None:
        rendered = to_html(REPORT)
        self.assertIn("<p>Your team review shows the biggest pressure points are <strong>operational backlog</strong>.</p>", rendered)
        self.assertIn("<h3>Team Overview</h3>", rendered)
        self.assertIn("<ul><li>Headcount: 3 direct reports in <strong>HR Services Department</strong></li>"
                      "<li>Roles:<ul><li>Director, Payroll Operations</li><li>Director, Recruiting Services</li></ul></li></ul>",
                      rendered)
        self.assertIn("<h3>IT Health</h3>", rendered)
        self.assertIn("<table><tr><th>Priority</th><th>Open</th><th>Breached</th></tr><tr><td>P1</td><td>17</td>", rendered)
        self.assertIn("<ol><li>Clear the <code>P1</code> queue</li>", rendered)
        self.assertIn('<a href="https://example.com/d?a=1&amp;b=2">the dashboard</a>', rendered)
        self.assertNotIn("**", rendered)
        self.assertNotIn("|", rendered)

    def test_untrusted_markup_is_escaped_and_only_safe_links_render(self) -> None:
        rendered = to_html("<script>alert(1)</script> [x](javascript:alert(1)) *ok* snake_case_name 2 * 3 * 4")
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<a ", rendered)
        self.assertIn("<em>ok</em>", rendered)
        self.assertIn("snake_case_name 2 * 3 * 4", rendered)

    def test_card_uses_table_elements_and_the_textblock_markdown_subset(self) -> None:
        card = to_card(REPORT, title="HR Agent finished Team Review", footer="Run run-1")
        self.assertEqual((card["version"], card["msteams"]), ("1.5", {"width": "Full"}))
        types = [element["type"] for element in card["body"]]
        self.assertIn("Table", types)
        table = next(element for element in card["body"] if element["type"] == "Table")
        self.assertTrue(table["firstRowAsHeaders"])
        self.assertEqual(len(table["columns"]), 3)
        self.assertEqual(table["rows"][1]["cells"][0]["items"][0]["text"], "P1")
        heading = next(element for element in card["body"] if element.get("text") == "Team Overview")
        self.assertEqual(heading["weight"], "Bolder")
        bullets = next(element for element in card["body"] if element.get("text", "").startswith("- Headcount"))
        self.assertIn("\r", bullets["text"])
        self.assertNotIn("`", json.dumps(card))

    def test_structure_detection_and_summary(self) -> None:
        self.assertFalse(is_structured("I've opened a case for this and I'm on it now."))
        self.assertFalse(is_structured("Done — **INC0010023** is resolved."))
        self.assertTrue(is_structured(REPORT))
        self.assertTrue(is_structured("- one\n- two"))
        self.assertEqual(summary("**Team Overview**\n- a"), "Team Overview")
        self.assertEqual([block.kind for block in parse("```\ncode | x\n---\n```")], ["code"])


if __name__ == "__main__":
    unittest.main()
