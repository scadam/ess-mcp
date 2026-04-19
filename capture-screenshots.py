#!/usr/bin/env python3
"""Capture widget screenshots using Playwright.

Loads each widget HTML, injects sample data from widget-preview/sample-data.js,
and takes a screenshot of every widget.

Requires: pip install playwright && python -m playwright install chromium
"""

import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
WIDGET_DIR = ROOT / "mcp_servers" / "src" / "mcp_servers" / "ui" / "widget"
OUTPUT_DIR = ROOT / "docs" / "images"
SAMPLE_DATA_JS = ROOT / "widget-preview" / "sample-data.js"

# Ordered list of all widgets, grouped by platform (matches index.html)
PLATFORMS = [
    ("Workday", [
        "worker-profile", "org-chart", "leave-booking",
        "team-calendar", "team-dashboard", "change-business-title",
        "learning-assignments", "learning-catalog", "learning-search",
        "inbox-tasks", "give-feedback", "goals-dashboard",
        "create-check-in-form", "development-items", "team-goals",
        "compensation-summary",
    ]),
    ("ServiceNow", [
        "incident-list", "create-incident", "update-incident",
        "team-incidents", "approval-review", "task-list",
        "update-task", "cart-summary", "catalog-list",
        "catalog-item", "create-change-request", "create-problem",
    ]),
    ("Salesforce", [
        "crm-pipeline", "crm-account-360", "crm-opportunity",
        "crm-lead", "lead-pipeline", "team-pipeline",
        "crm-event", "crm-quote", "compliance-case",
    ]),
    ("Jira", [
        "jira-issue", "sprint-board", "create-issue-jira",
        "create-project", "team-sprint-health",
    ]),
    ("SAP SuccessFactors", [
        "sf-employee-profile", "sf-leave-balance", "sf-time-off-history",
        "sf-leave-booking", "sf-personal-data-form", "sf-org-chart",
        "sf-payslip-list", "sf-payslip-detail", "sf-move-employee",
        "sf-document-list",
    ]),
    ("SAP Ariba", [
        "ariba-invoice-status", "ariba-po-status", "ariba-confirm-action",
        "ariba-receipt-list", "ariba-create-receipt", "ariba-requisition-list",
        "ariba-create-requisition", "ariba-catalog-search", "ariba-supplier-list",
        "ariba-supplier-profile", "ariba-supplier-registration", "ariba-approval-list",
    ]),
    ("Coupa", [
        "coupa-invoice-status", "coupa-po-status", "coupa-confirm-action",
        "coupa-receipt-list", "coupa-create-receipt", "coupa-requisition-list",
        "coupa-create-requisition", "coupa-catalog-search", "coupa-supplier-list",
        "coupa-supplier-profile", "coupa-supplier-registration", "coupa-approval-list",
    ]),
]

VIEWPORT_WIDTH = 520
VIEWPORT_HEIGHT = 1200

# STRING_WIDGETS need JSON.parse internally — toolOutput is a JSON string
STRING_WIDGETS = {"update-incident", "update-task"}

# Post-load actions: interact with the widget to show richer content
POST_ACTIONS = {
    "learning-search": [
        ("click", ".filter-chip[data-type='skill']"),
        ("wait", 200),
        ("click", "#searchBtn"),
        ("wait", 1500),
    ],
    "give-feedback": [
        ("wait", 500),
        ("click", "#personSearch"),
        ("wait", 300),
        ("click", ".picker-item[data-idx='0']"),
        ("wait", 500),
    ],
    "create-check-in-form": [
        ("wait", 500),
        ("click", "#personSearch"),
        ("wait", 300),
        ("click", ".picker-item[data-idx='0']"),
        ("wait", 500),
    ],
}


def load_sample_data_from_js():
    """Evaluate sample-data.js in a Playwright page to get Python dicts."""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        js_source = SAMPLE_DATA_JS.read_text(encoding="utf-8")
        # Execute the JS to define the variables, then return them
        result = page.evaluate(f"""() => {{
            {js_source}
            return {{
                data: SAMPLE_DATA,
                input: SAMPLE_INPUT,
                stringWidgets: STRING_WIDGETS
            }};
        }}""")
        browser.close()
    return result["data"], result["input"]


def build_injection(widget_name, data, input_data):
    """Build a <script> tag that sets up window.openai with sample data."""
    is_string = widget_name in STRING_WIDGETS
    if is_string:
        tool_output_expr = json.dumps(json.dumps(data))
    else:
        tool_output_expr = json.dumps(data)
    data_json = json.dumps(data)
    input_json = json.dumps(input_data)

    # Build a rich callTool mock that handles learning search
    return (
        '<script>'
        'document.documentElement.setAttribute("data-theme","light");'
        'window.matchMedia=function(){return{matches:false,addEventListener:function(){}}};'
        f'var __sampleData__={data_json};'
        'window.openai={'
        f'toolOutput:{tool_output_expr},'
        f'toolInput:{input_json},'
        'callTool:function(name, params){'
        '  if(name==="search_learning_content"){'
        '    return Promise.resolve({structuredContent:{'
        '      content:['
        '        {id:"lc1",descriptor:"Cloud Architecture Fundamentals",description:'
        '"Master cloud design patterns and multi-region deployment.",'
        'contentType:"Course",deliveryMode:"Online",contentProvider:"AWS Training",'
        'skillLevel:"Intermediate",averageRating:4.7,ratingCount:342,popularity:92,'
        'skills:["Cloud Computing","Architecture","AWS"],topics:["Technical Skills"],'
        'lessons:[{descriptor:"Module 1: Cloud Design Patterns",contentType:"Video",'
        'duration:"45 min",required:true,order:1}]},'
        '        {id:"lc2",descriptor:"Leadership in Tech Teams",description:'
        '"Develop leadership skills for managing engineering teams.",'
        'contentType:"Course",deliveryMode:"Blended",contentProvider:"LinkedIn Learning",'
        'skillLevel:"Advanced",averageRating:4.5,ratingCount:189,popularity:85,'
        'skills:["Leadership","Management"],topics:["Career Development","Management"],'
        'lessons:[{descriptor:"Lesson 1: Setting Vision",contentType:"Video",'
        'duration:"20 min",required:true,order:1}]},'
        '        {id:"lc3",descriptor:"Data Analysis with Python",description:'
        '"Learn to analyze data using pandas and Jupyter notebooks.",'
        'contentType:"Course",deliveryMode:"Online",contentProvider:"Coursera",'
        'skillLevel:"Beginner",averageRating:4.8,ratingCount:567,popularity:95,'
        'skills:["Data Analysis","Python"],topics:["Technical Skills"],'
        'lessons:[{descriptor:"Getting Started with Pandas",contentType:"Video",'
        'duration:"30 min",required:true,order:1}]}'
        '      ]'
        '    }});'
        '  }'
        '  return Promise.resolve({structuredContent:__sampleData__});'
        '},'
        'sendFollowUpMessage:function(){},'
        'requestDisplayMode:function(){return Promise.resolve()},'
        'notifyIntrinsicHeight:function(){}'
        '};'
        '</script>'
        '<style>html,body{color-scheme:light!important;}</style>'
    )


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("Loading sample data from sample-data.js...")
    sample_data, sample_input = load_sample_data_from_js()

    all_widgets = []
    for _, widgets in PLATFORMS:
        all_widgets.extend(widgets)

    print(f"Capturing {len(all_widgets)} widgets...\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            device_scale_factor=2,
            color_scheme="light",
        )

        for widget_name in all_widgets:
            print(f"  Capturing {widget_name}...")
            page = context.new_page()

            widget_html_path = WIDGET_DIR / f"{widget_name}.html"
            if not widget_html_path.exists():
                print(f"    SKIP: {widget_html_path} not found")
                page.close()
                continue

            html = widget_html_path.read_text(encoding="utf-8")

            data = sample_data.get(widget_name, {})
            input_data = sample_input.get(widget_name, {})
            injection = build_injection(widget_name, data, input_data)

            # Inject after <head> tag
            head_match = re.search(r"<head[^>]*>", html, re.IGNORECASE)
            if head_match:
                pos = head_match.end()
                html = html[:pos] + injection + html[pos:]
            else:
                html = injection + html

            page.set_content(html, wait_until="networkidle")
            page.wait_for_timeout(1000)

            # Run post-load actions
            actions = POST_ACTIONS.get(widget_name, [])
            for action in actions:
                if action[0] == "click":
                    try:
                        page.click(action[1], timeout=3000)
                    except Exception as e:
                        print(f"    Warning: click '{action[1]}' failed: {e}")
                elif action[0] == "wait":
                    page.wait_for_timeout(action[1])

            page.wait_for_timeout(500)

            # Measure actual content height
            clip_height = page.evaluate("""() => {
                const wrap = document.querySelector('.wrap');
                if (wrap) {
                    const orig = wrap.style.minHeight;
                    wrap.style.minHeight = 'auto';
                    document.body.style.height = 'auto';
                    document.documentElement.style.height = 'auto';
                    const h = wrap.scrollHeight + 32;
                    wrap.style.minHeight = orig;
                    return Math.min(h, 1100);
                }
                return Math.min(document.body.scrollHeight, 1100);
            }""")

            output_path = OUTPUT_DIR / f"widget-{widget_name}.png"
            page.screenshot(
                path=str(output_path),
                clip={"x": 0, "y": 0, "width": VIEWPORT_WIDTH, "height": clip_height},
            )
            print(f"    Saved: {output_path} ({clip_height}px tall)")
            page.close()

        browser.close()
    print(f"\nDone! All {len(all_widgets)} screenshots captured.")


if __name__ == "__main__":
    main()
