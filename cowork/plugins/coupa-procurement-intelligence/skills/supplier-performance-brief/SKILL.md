---
name: supplier-performance-brief
description: |
  Creates procurement leadership assets from Coupa data, especially supplier performance PowerPoint decks,
  category manager briefs, IT hardware order reviews, demand risk summaries, and ServiceNow-to-Coupa flow analysis.
  Use when the user asks to "create a supplier performance deck", "prepare a procurement review",
  "show category manager insights", "make a Coupa PowerPoint", "brief LSEG procurement",
  "analyze IT hardware suppliers", "review open hardware orders", or "turn Coupa data into an executive presentation".
license: MIT
compatibility: Copilot Cowork Frontier with a remote MCP connector for Coupa.
metadata: {author: ESS MCP Demo, version: "1.0.2", demo-audience: LSEG procurement team}
cowork.category: Procurement
cowork.icon: Briefcase
---

# Supplier Performance Brief

## What This Skill Does

Use this skill to help procurement teams turn Coupa operational data into boardroom-ready assets. The best default asset is a PowerPoint-style supplier performance pack for IT hardware procurement, but the same workflow can produce a category manager one-pager, executive narrative, demand risk heatmap, supplier scorecard, or ServiceNow-to-Coupa fulfilment walkthrough.

The Coupa MCP server in this plugin serves the demo dataset through live connector tools and requires no authentication. Always gather procurement data by calling the Coupa connector tools from this package; do not invent offline sample data or continue with generic sample data if those tools are unavailable.

If the Coupa connector tools are not visible in the task's available functions, stop and report that the package skill loaded but the Coupa MCP connector did not bind. Do not create the procurement asset until the connector tools are available.

## Recommended Asset Ideas

When the user asks what to create, offer one of these high-impact procurement assets:

1. Supplier Performance PowerPoint
   - Best for executive and procurement leadership demos.
   - Compares strategic IT hardware suppliers on on-time delivery, open order value, risk, lead time, defects, and current PO exposure.
   - Uses `get_supplier_performance`, `get_category_manager_dashboard`, and `list_it_hardware_orders`.

2. IT Hardware Category Manager Brief
   - Best for category managers and sourcing leads.
   - Summarizes spend, open order value, delivery risk, supplier mix, demand, and stock coverage for laptops, phones, monitors, docks, and accessories.
   - Uses `get_category_manager_dashboard` and `get_item_demand`.

3. ServiceNow-to-Coupa Fulfilment Flow Walkthrough
   - Best for showing end-to-end process visibility.
   - Traces employee hardware requests from ServiceNow into Coupa requisitions, POs, receipts, and invoices.
   - Uses `get_servicenow_coupa_flow`, `get_po_status`, `list_receipts`, and `get_invoice_status`.

4. Procurement Risk Action Plan
   - Best for showing Copilot turning insight into action.
   - Identifies late POs, quantity mismatches, supplier acknowledgement delays, stockout risks, and pending approvals.
   - Uses `list_it_hardware_orders`, `list_approvals`, `get_item_demand`, and `get_supplier_performance`.

## Default Workflow

When creating a supplier performance PowerPoint or briefing asset, follow this workflow:

1. Clarify the audience and format only if the user has not specified them.
   - Default audience: procurement leadership and category managers.
   - Default format: 8-slide PowerPoint outline with speaker notes and action recommendations.
   - Default category: IT hardware.
   - Default region/currency: UK / GBP.

2. Gather the Coupa data using connector tools.
   - First confirm that the Coupa connector tools are available in the task. If none of the tools below are available, stop and report the connector binding issue instead of using sample data.
   - Call `get_category_manager_dashboard` for overall spend, open value, delivery risk, demand, supplier rollups, and alerts.
   - Call `get_supplier_performance` for supplier scorecard details.
   - Call `list_it_hardware_orders` to identify late, at-risk, partially received, high-value, or blocked orders.
   - Call `get_item_demand` to identify stockout and watch-list items.
   - Call `get_servicenow_coupa_flow` when the user wants end-to-end process storytelling.

3. Analyze the results as a procurement category manager.
   - Segment suppliers by strategic, preferred, approved, and at-risk.
   - Compare on-time rate, defect rate, lead time, open order count, open value, and risk.
   - Identify delivery exceptions and explain the operational implication.
   - Link demand and stock coverage to procurement actions.
   - Highlight where ServiceNow demand is creating Coupa fulfilment pressure.

4. Create the asset.
   - If Cowork can create a PowerPoint directly, create the deck.
   - Otherwise, provide a slide-by-slide PowerPoint plan with titles, bullets, suggested visual, speaker notes, and source data table.
   - Keep slide text concise and executive-ready.
   - Put detailed evidence and tool output in an appendix section.

5. End with actions.
   - Recommend supplier follow-ups, expedited POs, approval actions, demand planning changes, contract review points, and stakeholder messages.
   - Include owners and urgency where possible.

## PowerPoint Output Format

Use this structure for the default supplier performance PowerPoint:

| Slide | Title | Purpose |
| --- | --- | --- |
| 1 | IT Hardware Procurement Snapshot | Executive summary of spend, open value, and current risk. |
| 2 | Supplier Scorecard | Compare suppliers by on-time delivery, defects, lead time, open orders, and risk. |
| 3 | Open Order Risk | Show late, at-risk, partially received, and high-value purchase orders. |
| 4 | Demand And Stock Coverage | Show demand pressure for laptops, phones, monitors, docks, and accessories. |
| 5 | ServiceNow-To-Coupa Flow | Explain how employee requests become requisitions, POs, receipts, and invoices. |
| 6 | Supplier Deep Dive | Focus on the supplier with the most important risk or value exposure. |
| 7 | Recommended Actions | Prioritized procurement actions for category managers. |
| 8 | Appendix: Source Data | Key records and assumptions from Coupa MCP tools. |

For each slide, include:

- Slide title
- Three to five concise bullets
- Suggested visual, such as scorecard table, risk heatmap, funnel, timeline, or bar chart
- Speaker notes written for a procurement leader
- Source tool names used

## Procurement Analysis Rules

Use these rules when interpreting Coupa data:

- Late or at-risk orders should be called out before healthy orders.
- High open value plus medium supplier risk should be treated as leadership-relevant.
- Stock coverage under one month is a stockout risk.
- Stock coverage under two months is a watch item.
- Partially received POs should be checked against receipts and invoices.
- Pending supplier acknowledgement should become a supplier follow-up action.
- Quantity mismatch or invoice mismatch should become an accounts payable and supplier resolution action.
- Supplier performance should be framed as operational impact, not only metrics.

## Tone For LSEG Procurement Demo

Use a polished, enterprise procurement tone. Emphasize that Microsoft 365 Copilot and Cowork can connect natural language, live procurement systems, and Microsoft 365 asset creation into one workflow. Keep the story concrete: employee demand starts in ServiceNow, procurement execution happens in Coupa, and the procurement team gets an asset they can present or act on immediately.

## Additional Resources

- `references/demo-scenarios.md` - Demo storylines, suggested prompts, and procurement asset ideas.
- `references/slide-patterns.md` - Reusable slide layouts and narrative patterns for supplier performance assets.
