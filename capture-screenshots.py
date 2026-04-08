#!/usr/bin/env python3
"""Capture widget screenshots using Playwright.

Loads each widget HTML, injects sample data as window.openai.toolOutput,
and takes a screenshot matching the existing screenshot style.

Requires: pip install playwright && python -m playwright install chromium
"""

import json
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent
WIDGET_DIR = ROOT / "mcp_servers" / "src" / "mcp_servers" / "ui" / "widget"
OUTPUT_DIR = ROOT / "docs" / "images"

WIDGETS_TO_CAPTURE = [
    "learning-search",
    "inbox-tasks",
    "give-feedback",
    "goals-dashboard",
    "create-check-in-form",
    "development-items",
    "team-goals",
]

VIEWPORT_WIDTH = 520
VIEWPORT_HEIGHT = 1200  # Tall enough to capture content without scrolling

# Post-load actions: interact with the widget to show richer content
POST_ACTIONS = {
    "learning-search": [
        # Click first skill chip to select it, then click Search
        ("click", ".filter-chip[data-type='skill']"),
        ("wait", 200),
        ("click", "#searchBtn"),
        ("wait", 1500),  # Wait for async search to render
    ],
    "give-feedback": [
        # Focus input to open dropdown, then click first person -> step 2
        ("wait", 500),
        ("click", "#personSearch"),
        ("wait", 300),
        ("click", ".picker-item[data-idx='0']"),
        ("wait", 500),
    ],
    "create-check-in-form": [
        # Focus input to open dropdown, then click first person -> step 2
        ("wait", 500),
        ("click", "#personSearch"),
        ("wait", 300),
        ("click", ".picker-item[data-idx='0']"),
        ("wait", 500),
    ],
}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
            device_scale_factor=2,  # Retina-quality screenshots
            color_scheme="light",
        )

        for widget_name in WIDGETS_TO_CAPTURE:
            print(f"Capturing {widget_name}...")
            page = context.new_page()

            widget_html_path = WIDGET_DIR / f"{widget_name}.html"
            if not widget_html_path.exists():
                print(f"  SKIP: {widget_html_path} not found")
                page.close()
                continue

            html = widget_html_path.read_text(encoding="utf-8")

            # Load sample data
            sample_data = load_sample_data(widget_name)

            # Build injection script
            injection = build_injection(widget_name, sample_data)

            # Inject after <head> tag
            head_match = re.search(r"<head[^>]*>", html, re.IGNORECASE)
            if head_match:
                pos = head_match.end()
                html = html[:pos] + injection + html[pos:]
            else:
                html = injection + html

            # Set content and wait for rendering
            page.set_content(html, wait_until="networkidle")
            page.wait_for_timeout(1000)

            # Run post-load actions (click buttons, trigger search, etc.)
            actions = POST_ACTIONS.get(widget_name, [])
            for action in actions:
                if action[0] == "click":
                    try:
                        page.click(action[1], timeout=3000)
                    except Exception as e:
                        print(f"  Warning: click '{action[1]}' failed: {e}")
                elif action[0] == "wait":
                    page.wait_for_timeout(action[1])

            page.wait_for_timeout(500)  # Final settle

            # Measure actual content height by temporarily removing min-height
            clip_height = page.evaluate("""() => {
                const wrap = document.querySelector('.wrap');
                if (wrap) {
                    // Temporarily remove min-height to get real content size
                    const orig = wrap.style.minHeight;
                    wrap.style.minHeight = 'auto';
                    document.body.style.height = 'auto';
                    document.documentElement.style.height = 'auto';
                    const h = wrap.scrollHeight + 32;  // 16px padding top+bottom
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
            print(f"  Saved: {output_path} ({clip_height}px tall)")
            page.close()

        browser.close()
    print("\nDone! All screenshots captured.")


def load_sample_data(widget_name):
    """Parse the SAMPLE_DATA object from sample-data.js for a given widget."""
    # Execute sample-data.js in a minimal JS context via Playwright
    # Instead, just hardcode the Python dicts matching sample-data.js
    data_map = {
        "learning-search": {
            "skills": [
                {"id": "skill_001", "descriptor": "Project Management"},
                {"id": "skill_002", "descriptor": "Cloud Computing"},
                {"id": "skill_003", "descriptor": "Data Analysis"},
                {"id": "skill_004", "descriptor": "Leadership"},
                {"id": "skill_005", "descriptor": "Machine Learning"},
            ],
            "topics": [
                {"id": "topic_001", "descriptor": "Career Development"},
                {"id": "topic_002", "descriptor": "Technical Skills"},
                {"id": "topic_003", "descriptor": "Compliance"},
                {"id": "topic_004", "descriptor": "Management"},
                {"id": "topic_005", "descriptor": "Diversity & Inclusion"},
            ],
        },
        "inbox-tasks": {
            "tasks": [
                {"id": "task_3001", "descriptor": "Approve Time Off Request \u2013 Alex Rivera", "subject": "Time Off Request", "stepType": "Approval", "status": "Awaiting Action", "initiator": "Alex Rivera", "assigned": "2026-03-28", "due": "2026-04-05"},
                {"id": "task_3002", "descriptor": "Approve Expense Report \u2013 Maya Johnson", "subject": "Expense Report", "stepType": "Approval", "status": "Awaiting Action", "initiator": "Maya Johnson", "assigned": "2026-03-29", "due": "2026-04-06"},
                {"id": "task_3003", "descriptor": "Review Job Requisition \u2013 Engineering", "subject": "Job Requisition", "stepType": "To Do", "status": "In Progress", "initiator": "David Park", "assigned": "2026-03-25", "due": "2026-04-10"},
                {"id": "task_3004", "descriptor": "Approve Title Change \u2013 James Wilson", "subject": "Title Change", "stepType": "Approval", "status": "Awaiting Action", "initiator": "James Wilson", "assigned": "2026-03-30", "due": "2026-04-02"},
                {"id": "task_3005", "descriptor": "Complete Onboarding Checklist", "subject": "Onboarding", "stepType": "To Do", "status": "Not Started", "initiator": "HR System", "assigned": "2026-04-01", "due": "2026-04-15"},
            ]
        },
        "give-feedback": {
            "people": [
                {"descriptor": "Alex Rivera", "businessTitle": "Software Engineer", "workerId": "WD-204852"},
                {"descriptor": "Maya Johnson", "businessTitle": "Software Engineer", "workerId": "WD-204853"},
                {"descriptor": "James Wilson", "businessTitle": "Junior Developer", "workerId": "WD-204854"},
                {"descriptor": "Priya Sharma", "businessTitle": "DevOps Engineer", "workerId": "WD-204855"},
                {"descriptor": "David Park", "businessTitle": "VP of Engineering", "workerId": "WD-204856"},
            ],
            "badges": [
                {"id": "badge_001", "descriptor": "Innovation Champion"},
                {"id": "badge_002", "descriptor": "Team Player"},
                {"id": "badge_003", "descriptor": "Customer Focus"},
                {"id": "badge_004", "descriptor": "Going Above & Beyond"},
                {"id": "badge_005", "descriptor": "Mentorship"},
            ],
        },
        "goals-dashboard": {
            "goals": [
                {"id": "goal_001", "name": "Deliver Platform v2.0", "description": "Ship the next major platform release with OAuth 2.0 rotation and rate limiting.", "status": "On Track", "percentComplete": 72, "dueDate": "2026-06-30", "categories": ["Engineering", "Delivery"]},
                {"id": "goal_002", "name": "Reduce API Latency by 40%", "description": "Optimize database queries and caching layers to reduce p95 latency from 800ms to 480ms.", "status": "At Risk", "percentComplete": 45, "dueDate": "2026-05-15", "categories": ["Engineering", "Performance"]},
                {"id": "goal_003", "name": "Complete AWS Solutions Architect Cert", "description": "Obtain the AWS Solutions Architect Professional certification.", "status": "In Progress", "percentComplete": 60, "dueDate": "2026-07-31", "categories": ["Learning", "Career Development"]},
                {"id": "goal_004", "name": "Mentor 2 Junior Engineers", "description": "Provide structured mentorship program for two new team members.", "status": "On Track", "percentComplete": 50, "dueDate": "2026-12-31", "categories": ["Leadership", "Team"]},
                {"id": "goal_005", "name": "Improve Test Coverage to 85%", "description": "Increase unit and integration test coverage across the platform codebase.", "status": "Not Started", "percentComplete": 0, "dueDate": "2026-09-30", "categories": ["Engineering", "Quality"]},
            ]
        },
        "create-check-in-form": {
            "people": [
                {"descriptor": "Alex Rivera", "businessTitle": "Software Engineer", "workerId": "WD-204852"},
                {"descriptor": "Maya Johnson", "businessTitle": "Software Engineer", "workerId": "WD-204853"},
                {"descriptor": "James Wilson", "businessTitle": "Junior Developer", "workerId": "WD-204854"},
                {"descriptor": "Priya Sharma", "businessTitle": "DevOps Engineer", "workerId": "WD-204855"},
            ],
            "topics": [
                {"id": "topic_ci_001", "descriptor": "Career Development"},
                {"id": "topic_ci_002", "descriptor": "Performance Review"},
                {"id": "topic_ci_003", "descriptor": "Project Updates"},
                {"id": "topic_ci_004", "descriptor": "Work-Life Balance"},
                {"id": "topic_ci_005", "descriptor": "Skills Growth"},
                {"id": "topic_ci_006", "descriptor": "Feedback"},
            ],
        },
        "development-items": {
            "items": [
                {"name": "Complete AWS Solutions Architect Certification", "description": "Prepare for and pass the AWS SA Professional exam to deepen cloud architecture skills.", "status": "In Progress", "category": "Formal Education", "relatedSkills": ["Cloud Computing", "AWS", "Architecture"], "dueDate": "2026-07-31"},
                {"name": "Lead Cross-Team API Design Workshop", "description": "Design and facilitate a workshop on REST API best practices for the engineering department.", "status": "Not Started", "category": "Assignment", "relatedSkills": ["API Design", "Leadership", "Communication"], "dueDate": "2026-06-15"},
                {"name": "Advanced Kubernetes Training", "description": "Complete the CKA preparation course and hands-on labs.", "status": "In Progress", "category": "Training", "relatedSkills": ["Kubernetes", "DevOps", "Container Orchestration"], "dueDate": "2026-08-30"},
                {"name": "Contribute to Open Source MCP SDK", "description": "Make meaningful contributions to the MCP Python SDK open source project.", "status": "Active", "category": "Assignment", "relatedSkills": ["Python", "Open Source", "MCP"], "dueDate": "2026-09-30"},
                {"name": "Data Engineering Fundamentals Course", "description": "Complete the data engineering pathway covering ETL, data pipelines, and warehousing.", "status": "Completed", "category": "Training", "relatedSkills": ["Data Engineering", "SQL", "ETL"], "completionDate": "2026-03-15"},
            ]
        },
        "team-goals": {
            "team": [
                {"descriptor": "Alex Rivera", "businessTitle": "Software Engineer", "goals": [
                    {"name": "Implement Rate Limiting", "status": "On Track", "percentComplete": 80, "dueDate": "2026-05-30", "description": "Add rate limiting to all public API endpoints."},
                    {"name": "Reduce Bug Backlog by 50%", "status": "At Risk", "percentComplete": 35, "dueDate": "2026-06-30", "description": "Triage and resolve high-priority bugs in the backlog."},
                ]},
                {"descriptor": "Maya Johnson", "businessTitle": "Software Engineer", "goals": [
                    {"name": "Lead Frontend Redesign", "status": "On Track", "percentComplete": 65, "dueDate": "2026-07-15", "description": "Redesign the dashboard UI with accessibility improvements."},
                    {"name": "Improve Lighthouse Score to 95+", "status": "On Track", "percentComplete": 70, "dueDate": "2026-06-30", "description": "Optimize performance, accessibility, and SEO metrics."},
                    {"name": "Mentor Intern on React", "status": "In Progress", "percentComplete": 40, "dueDate": "2026-08-31", "description": "Provide weekly mentorship sessions on React patterns."},
                ]},
                {"descriptor": "James Wilson", "businessTitle": "Junior Developer", "goals": [
                    {"name": "Complete Onboarding Milestones", "status": "On Track", "percentComplete": 90, "dueDate": "2026-04-30", "description": "Finish all onboarding tasks and first contribution."},
                    {"name": "Learn CI/CD Pipeline", "status": "Behind", "percentComplete": 20, "dueDate": "2026-05-15", "description": "Understand and document the team's CI/CD pipeline."},
                ]},
                {"descriptor": "Priya Sharma", "businessTitle": "DevOps Engineer", "goals": [
                    {"name": "Migrate to Kubernetes 1.30", "status": "On Track", "percentComplete": 55, "dueDate": "2026-06-30", "description": "Upgrade all production clusters to Kubernetes 1.30."},
                    {"name": "Implement Zero-Downtime Deployments", "status": "Not Started", "percentComplete": 0, "dueDate": "2026-08-31", "description": "Set up blue-green deployments across all services."},
                ]},
            ]
        },
    }
    return data_map.get(widget_name, {})


def build_injection(widget_name, data):
    """Build a <script> tag that sets up window.openai with sample data."""
    data_json = json.dumps(data)
    return (
        '<script>'
        'document.documentElement.setAttribute("data-theme","light");'
        'window.matchMedia=function(){return{matches:false,addEventListener:function(){}}};'
        f'var __sampleData__={data_json};'
        'window.openai={'
        f'toolOutput:{data_json},'
        'toolInput:{},'
        'callTool:function(name, params){'
        '  if(name==="search_learning_content"){'
        '    return Promise.resolve({structuredContent:{'
        '      content:['
        '        {id:"lc1",descriptor:"Cloud Architecture Fundamentals",description:"Master cloud design patterns, scalability strategies, and multi-region deployment architectures.",contentType:"Course",deliveryMode:"Online",contentProvider:"AWS Training",skillLevel:"Intermediate",averageRating:4.7,ratingCount:342,popularity:92,skills:["Cloud Computing","Architecture","AWS"],topics:["Technical Skills"],lessons:[{descriptor:"Module 1: Cloud Design Patterns",contentType:"Video",duration:"45 min",required:true,order:1},{descriptor:"Module 2: Scalability Strategies",contentType:"Video",duration:"38 min",required:true,order:2},{descriptor:"Module 3: Multi-Region Deployment",contentType:"Lab",duration:"60 min",required:true,order:3}]},'
        '        {id:"lc2",descriptor:"Leadership in Tech Teams",description:"Develop essential leadership skills for managing high-performing engineering teams.",contentType:"Course",deliveryMode:"Blended",contentProvider:"LinkedIn Learning",skillLevel:"Advanced",averageRating:4.5,ratingCount:189,popularity:85,skills:["Leadership","Management"],topics:["Career Development","Management"],lessons:[{descriptor:"Lesson 1: Setting Vision",contentType:"Video",duration:"20 min",required:true,order:1},{descriptor:"Lesson 2: Effective 1:1s",contentType:"Video",duration:"25 min",required:true,order:2}]},'
        '        {id:"lc3",descriptor:"Data Analysis with Python",description:"Learn to analyze and visualize data using pandas, matplotlib, and Jupyter notebooks.",contentType:"Course",deliveryMode:"Online",contentProvider:"Coursera",skillLevel:"Beginner",averageRating:4.8,ratingCount:567,popularity:95,skills:["Data Analysis","Python"],topics:["Technical Skills"],lessons:[{descriptor:"Getting Started with Pandas",contentType:"Video",duration:"30 min",required:true,order:1},{descriptor:"Data Visualization",contentType:"Lab",duration:"45 min",required:true,order:2}]},'
        '        {id:"lc4",descriptor:"Machine Learning Foundations",description:"Introduction to supervised and unsupervised learning algorithms with hands-on projects.",contentType:"Learning Path",deliveryMode:"Online",contentProvider:"Internal",skillLevel:"Intermediate",averageRating:4.3,ratingCount:124,popularity:78,skills:["Machine Learning","Data Analysis"],topics:["Technical Skills"],lessons:[{descriptor:"Intro to ML Concepts",contentType:"Video",duration:"35 min",required:true,order:1}]},'
        '        {id:"lc5",descriptor:"Inclusive Leadership",description:"Build awareness and practical skills for fostering diverse and inclusive teams.",contentType:"Course",deliveryMode:"Online",contentProvider:"Internal",skillLevel:"All Levels",averageRating:4.6,ratingCount:210,popularity:88,skills:["Leadership"],topics:["Diversity & Inclusion","Management"],lessons:[{descriptor:"Understanding Bias",contentType:"Video",duration:"20 min",required:true,order:1},{descriptor:"Inclusive Practices Workshop",contentType:"Interactive",duration:"40 min",required:true,order:2}]}'
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


if __name__ == "__main__":
    main()
