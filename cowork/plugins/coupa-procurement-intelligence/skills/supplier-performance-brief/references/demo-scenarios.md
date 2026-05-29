# Demo Scenarios

Use these scenarios when demonstrating Coupa Procurement Intelligence in Copilot Cowork.

## Scenario 1: Supplier Performance PowerPoint

Prompt:

```text
Create a PowerPoint supplier performance pack for IT hardware procurement using Coupa data. Focus on open order value, on-time delivery, supplier risk, delivery exceptions, and recommended actions for the procurement leadership team.
```

Why it works:

- Shows Cowork using procurement-system data, not generic model knowledge.
- Produces a familiar M365 asset for executives.
- Lets the demo move from data retrieval to analysis to presentation creation.

Expected tool path:

1. `get_category_manager_dashboard`
2. `get_supplier_performance`
3. `list_it_hardware_orders`
4. `get_item_demand`

Expected asset:

- 8-slide supplier performance deck.
- Scorecard table for suppliers.
- Open order risk slide.
- Demand and stock coverage slide.
- Recommended actions slide.

## Scenario 2: Category Manager Brief

Prompt:

```text
Build a category manager brief for IT hardware. Show spend, open order value, supplier mix, late orders, stock coverage risks, and the top actions I should take this week.
```

Why it works:

- Feels like a Monday-morning category manager workflow.
- Demonstrates that Cowork can synthesize supplier, order, demand, and fulfilment data.

Expected tool path:

1. `get_category_manager_dashboard`
2. `list_it_hardware_orders`
3. `get_item_demand`

Expected asset:

- One-page briefing or short deck.
- Priority action table with owner, risk, and next step.

## Scenario 3: ServiceNow-To-Coupa Flow

Prompt:

```text
Trace the flow of ServiceNow hardware requests into Coupa and create a process visibility slide that shows where requests become requisitions, POs, receipts, and invoices.
```

Why it works:

- Shows cross-system process visibility.
- Makes the value of connecting ServiceNow and Coupa obvious to procurement and IT stakeholders.

Expected tool path:

1. `get_servicenow_coupa_flow`
2. `list_it_hardware_orders`
3. `list_receipts`
4. `get_invoice_status` if a specific invoice appears in the flow.

Expected asset:

- Process timeline.
- Blocker summary.
- Exception list.

## Scenario 4: Procurement Risk Action Plan

Prompt:

```text
Create a procurement risk action plan for current Coupa IT hardware orders. Highlight late POs, supplier acknowledgement delays, invoice mismatches, stockout risks, and pending approvals.
```

Why it works:

- Shows that Cowork is not just reporting. It converts insight into an action plan.
- Gives procurement leaders a concrete work product.

Expected tool path:

1. `list_it_hardware_orders`
2. `list_approvals`
3. `get_item_demand`
4. `get_supplier_performance`

Expected asset:

- Action table with priority, issue, supplier, business impact, owner, and recommended next step.
