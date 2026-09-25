"""Days of stock cover against lead time; recommends replenishment from an eligible source.

Usage: stock_cover.py [--as-of YYYY-MM-DD]
Reads item demand, suppliers and request-to-pay chains saved under data/coupa/ and writes
analysis/replenishment.json and reports/replenishment.csv. Standard library only; amounts are GBP.
"""

from __future__ import annotations

import csv
import glob
import json
import math
import os
import sys
from datetime import date, timedelta

SAFETY_DAYS, TARGET_DAYS, PACK = 21, 40, 5
AUTONOMY_LIMIT = 15_000.0
ALTERNATIVE_WINDOW_DAYS = 90
CONTRACT_MIN_DAYS, MIN_ON_TIME, MAX_DEFECTS = 60, 85.0, 2.0
AUTHORITY = ((10_000.0, "Line manager"), (50_000.0, "Category manager"), (float("inf"), "Finance Director"))


def money(value) -> float:
    try:
        return float(str(value).replace(",", "").replace("£", "").strip() or 0)
    except ValueError:
        return 0.0


def gbp(value: float) -> str:
    return f"£{value:,.2f}"


def load(pattern: str) -> list:
    docs = []
    for path in sorted(glob.glob(pattern)):
        try:
            with open(path, encoding="utf-8") as handle:
                docs.append(json.load(handle))
        except (OSError, ValueError):
            print(f"warning: {path} is not JSON; skipped", file=sys.stderr)
    return docs


def records(docs: list, *keys: str) -> list[dict]:
    found = []
    for doc in docs:
        for key in keys:
            value = doc.get(key) if isinstance(doc, dict) else None
            if isinstance(value, list):
                found.extend(item for item in value if isinstance(item, dict))
    return found


def unique(items: list[dict], key: str) -> list[dict]:
    seen: dict = {}
    for item in items:
        if item.get(key):
            seen.setdefault(item[key], item)
    return list(seen.values())


def parse_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def as_of_date(argv: list[str], dashboards: list, flows: list[dict]) -> date:
    if "--as-of" in argv:
        return date.fromisoformat(argv[argv.index("--as-of") + 1])
    for doc in dashboards:
        if isinstance(doc, dict) and parse_date(doc.get("as_of")):
            return parse_date(doc["as_of"])
    for flow in flows:
        order = flow.get("purchase_order") or {}
        expected, days = parse_date(order.get("expected-delivery")), order.get("days-to-delivery")
        if expected and isinstance(days, int):
            return expected - timedelta(days=days)
    return date.today()


def ineligible(supplier: dict | None, today: date) -> list[str]:
    """Why a supplier may not be used for a requisition raised without approval (empty means eligible)."""
    if not supplier:
        return ["supplier not found in the saved Coupa data"]
    reasons = []
    if not (supplier.get("preferred") or supplier.get("tier") in {"strategic", "preferred"}):
        reasons.append("not a preferred or strategic supplier")
    if supplier.get("risk") != "low":
        reasons.append(f"risk {supplier.get('risk')}")
    expires = parse_date((supplier.get("contract") or {}).get("expires"))
    if not expires or (expires - today).days < CONTRACT_MIN_DAYS:
        reasons.append(f"contract expires {expires} (under {CONTRACT_MIN_DAYS} days)" if expires else "no contract")
    metrics = supplier.get("metrics") or {}
    if not isinstance(metrics.get("on_time_rate"), (int, float)) or metrics["on_time_rate"] < MIN_ON_TIME:
        reasons.append(f"on-time {metrics.get('on_time_rate')}%")
    if not isinstance(metrics.get("defect_rate"), (int, float)) or metrics["defect_rate"] > MAX_DEFECTS:
        reasons.append(f"defects {metrics.get('defect_rate')}%")
    return reasons


def alternative_sources(item: dict, flows: list[dict], today: date) -> list[tuple[str, float, str]]:
    """(supplier id, unit price, evidence) for other suppliers of the same item on a recent PO at no more than list price."""
    price, found = money(item.get("unit-price")), {}
    for flow in flows:
        order = flow.get("purchase_order") or {}
        created = parse_date(order.get("created-at"))
        supplier_id = order.get("supplier-id") or (order.get("supplier") or {}).get("number")
        if not created or (today - created).days > ALTERNATIVE_WINDOW_DAYS or supplier_id == item.get("supplier-id"):
            continue
        for line in order.get("lines") or []:
            if line.get("item-id") == item.get("id") and money(line.get("unit-price")) <= price:
                found.setdefault(supplier_id, (supplier_id, money(line.get("unit-price")),
                                               f"{order.get('po-number')} on {created} at {gbp(money(line.get('unit-price')))}"))
    return list(found.values())


def main(argv: list[str]) -> int:
    dashboards = load("data/coupa/get_category_manager_dashboard*.json")
    items = unique(records(load("data/coupa/get_item_demand*.json"), "items") + records(dashboards, "demand")
                   + records(load("data/coupa/list_catalog_items*.json"), "demand", "results"), "id")
    if not items:
        print("No item demand in the workspace: call coupa get_item_demand first, then rerun.")
        return 2
    suppliers = {item["id"]: item for item in unique(
        records(load("data/coupa/list_suppliers*.json"), "results")
        + records(load("data/coupa/get_supplier_performance*.json"), "suppliers")
        + records(dashboards, "supplier_performance"), "id")}
    flows = unique(records(load("data/coupa/get_servicenow_coupa_flow*.json"), "flows"), "service-now-request")
    today = as_of_date(argv, dashboards, flows)
    rows = []
    for item in items:
        monthly = int(item.get("monthly-demand") or 0)
        if monthly <= 0:
            continue
        daily, stock, lead = monthly / 30, int(item.get("stock") or 0), int(item.get("lead-time-days") or 0)
        cover, reorder_at = stock / daily, lead + SAFETY_DAYS
        row = {"item": item.get("id"), "name": item.get("name"), "stock": stock, "monthly_demand": monthly,
               "lead_time_days": lead, "cover_days": round(cover, 1), "reorder_below_days": reorder_at,
               "status": "ok" if cover >= reorder_at else "reorder"}
        if cover >= reorder_at:
            rows.append(row)
            continue
        quantity = math.ceil(math.ceil((lead + TARGET_DAYS) * daily - stock) / PACK) * PACK
        candidates = [(item.get("supplier-id"), money(item.get("unit-price")), "contracted catalogue supplier")]
        candidates += sorted(alternative_sources(item, flows, today),
                             key=lambda source: (source[1], -((suppliers.get(source[0]) or {}).get("metrics") or {}).get("on_time_rate", 0)))
        checked = [(source, ineligible(suppliers.get(source[0]), today)) for source in candidates]
        chosen = next((source for source, reasons in checked if not reasons), None)
        default_reasons = checked[0][1]
        supplier_id, price, evidence = chosen or candidates[0]
        supplier = suppliers.get(supplier_id) or {}
        value = quantity * price
        if chosen and item.get("contracted") and value <= AUTONOMY_LIMIT:
            mode, owner = "autonomous", "procurement colleague"
        else:
            mode, owner = "approval", next(name for limit, name in AUTHORITY if value <= limit)
        why = []
        if default_reasons:
            why.append(f"{item.get('supplier')} is not eligible ({'; '.join(default_reasons)})")
        if chosen and chosen != candidates[0]:
            why.append(f"sourced from {supplier.get('name')} ({evidence})")
        if not chosen:
            why.append("no source meets the autonomy rules, so the contracted supplier is proposed")
        if chosen and value > AUTONOMY_LIMIT:
            why.append(f"{gbp(value)} is above the £15,000 limit")
        row.update({
            "quantity": quantity, "supplier_id": supplier_id, "supplier": supplier.get("name") or item.get("supplier"),
            "unit_price": price, "value": round(value, 2), "mode": mode, "owner": owner, "why": "; ".join(why),
            "call": {"server": "coupa", "tool": "create_requisition", "args": {
                "title": f"Replenishment: {item.get('name')} x {quantity}",
                "requester": "IT Asset Management",
                "line_items": [{"item-id": item.get("id"), "description": item.get("name"), "quantity": quantity,
                                "unit-price": f"{price:.2f}", "supplier-id": supplier_id,
                                "supplier": supplier.get("name") or item.get("supplier")}],
            }},
        })
        rows.append(row)
    reorder = [row for row in rows if row["status"] == "reorder"]
    os.makedirs("analysis", exist_ok=True)
    os.makedirs("reports", exist_ok=True)
    with open("analysis/replenishment.json", "w", encoding="utf-8") as handle:
        json.dump({"as_of": today.isoformat(), "items": rows, "reorder": len(reorder),
                   "autonomous_value": round(sum(row["value"] for row in reorder if row["mode"] == "autonomous"), 2)},
                  handle, indent=2)
    with open("reports/replenishment.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["item", "name", "stock", "monthly demand", "lead time days", "cover days", "status",
                         "quantity", "supplier", "unit price", "value", "mode", "why"])
        for row in rows:
            writer.writerow([row["item"], row["name"], row["stock"], row["monthly_demand"], row["lead_time_days"],
                             row["cover_days"], row["status"], row.get("quantity", ""), row.get("supplier", ""),
                             row.get("unit_price", ""), row.get("value", ""), row.get("mode", ""), row.get("why", "")])
    print(f"As of {today}: {len(rows)} items checked, {len(reorder)} below lead time + {SAFETY_DAYS} days of cover.")
    for row in reorder:
        print(f"{row['item']}: {row['cover_days']} days of cover vs {row['reorder_below_days']} needed -> "
              f"{row['quantity']} from {row['supplier']} = {gbp(row['value'])} [{row['mode']}]. {row['why']}")
    print("Wrote analysis/replenishment.json and reports/replenishment.csv.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
