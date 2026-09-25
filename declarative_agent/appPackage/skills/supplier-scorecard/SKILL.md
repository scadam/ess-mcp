---
name: supplier-scorecard
description: Score Coupa IT hardware suppliers on on-time delivery, quality, lead time and risk, rank them, and flag contracts that are due for renewal, suppliers to watch and items at risk of stock-out — with one recommended action per flagged supplier. Use when someone asks how suppliers are performing, for a supplier scorecard, ranking or review, which supplier contracts need attention, or who to use for a category.
---

# Supplier scorecard

**Goal:** a ranked, evidence-based scorecard the category manager can act on, calculated the same way every time.

## Step 1 — Gather the data

These calls are independent; make them together.

- `get_supplier_performance` — `suppliers[]` with `metrics` (on_time_rate, defect_rate, avg_lead_days, open_value), `risk`, `tier`, `preferred`, `category` and `contract` (id, expires, rebate).
- `get_item_demand` — `items[]` with `supplier`, `stock_coverage_months`, `lead-time-days` and `monthly-demand`.
- `get_category_manager_dashboard` — use its `as_of` date as today for contract dates (the Coupa demo data is dated), and its `alerts`.

## Step 2 — Score with the script

Build a JSON object and run `python scripts/score_suppliers.py input.json`:

```json
{"as_of": "2026-05-06",
 "suppliers": [{"name": "TechDirect UK Ltd", "category": "Laptop hardware", "tier": "strategic", "risk": "low",
                "on_time_rate": 94, "defect_rate": 1.1, "avg_lead_days": 6, "contract_expires": "2027-03-31",
                "open_value": 97840}],
 "items": [{"name": "iPhone 15 Pro 256GB", "supplier": "Apple Business Reseller UK", "stock_coverage_months": 0.8,
            "lead_time_days": 11}]}
```

You can also pass the raw `get_supplier_performance` result with the items added; the script reads either shape. It prints JSON with each supplier's component scores, total score (0–100), rank, band and `flags`, plus a Markdown `table`. **Use its scores; don't recalculate them.** The weights are: on-time delivery 40%, quality 30%, lead time 15%, risk 15%.

If you can't run scripts, say that scores are unavailable and show the raw metrics table instead — don't estimate scores.

## Step 3 — Present

1. The script's table, best first.
2. **Needs attention** — one bullet per flagged supplier with the flag and one action, for example:
   - Contract expired or expiring within 90 days → "Renew or re-tender CTR-ACC-2025-07 (expired 30 Jun 2026)."
   - On-time rate below 90% → "Agree a delivery improvement plan."
   - Defect rate above 2% → "Raise a quality review."
   - Items with under one month of stock → "Place replenishment early; lead time is 11 days."
3. One line naming the strongest supplier for new orders in each category.

Keep it to the table and at most six bullets.
