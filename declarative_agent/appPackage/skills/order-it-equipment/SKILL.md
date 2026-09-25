---
name: order-it-equipment
description: Help an employee get the right IT equipment from the ServiceNow service catalog — understand their role and what they need, check what they already have on order, recommend the catalog item that fits with a one-line reason and price, and open the ServiceNow order form for them to confirm. Use when someone needs a new or replacement laptop, monitor, phone, tablet, headset, keyboard, mouse or other IT equipment, or asks which device they should get.
---

# Order IT equipment

**Goal:** the employee sees one clear recommendation from the live ServiceNow catalog and an order form ready to submit. Equipment is ordered through ServiceNow only — **never use Coupa** for an employee's equipment request.

`references/device-guide.md` explains which catalog item suits which role. Read it before recommending.

## Step 1 — Understand the need

- What device, and what for: role (developer, sales, general office work), operating system preference, travel, or a temporary replacement while theirs is repaired.
- If the employee has already given their role and device, don't ask; otherwise ask **one** question.

## Step 2 — Check existing orders

Call `list_my_requests` (limit 10). If an open requested item already covers the same kind of device (for example a laptop that is "Waiting for Approval"), tell the employee its RITM number, item and stage, and ask whether they still want another before continuing.

## Step 3 — Find the options

Call `list_catalog_items` with `search` set to **one** device word: laptop, monitor, iphone, ipad, headset, keyboard or mouse. If it returns nothing, call `list_catalog_categories` and then `list_catalog_items` with the matching `category_sys_id` (for example Hardware).

## Step 4 — Recommend

Pick the item that fits using the device guide. Present:

| Recommended | Why it fits | Price |
|---|---|---|

Then one line with the next-best alternative and its price. Use the names and prices exactly as the catalog returned them.

## Step 5 — Open the order form

Call `get_catalog_item` with the recommended item's `sys_id`. The widget shows the order form; the employee fills in any questions and orders it themselves.

**Never call `order_catalog_item`, `add_to_cart` or `checkout_cart` yourself** — the widget does that when the employee clicks.

## Output

Keep it to the recommendation table, the alternative, and one sentence: "Here's the order form — check the options and order when you're ready."
