"""Score and rank IT hardware suppliers from Coupa performance metrics.

Usage: python score_suppliers.py input.json      (or pipe the JSON on stdin)

Input: {"as_of": "YYYY-MM-DD", "suppliers": [...], "items": [...]}. Each supplier needs name, on_time_rate (%),
defect_rate (%), avg_lead_days, risk (low|medium|high) and optionally category, tier, contract_expires, open_value.
The raw get_supplier_performance result (metrics and contract nested) is also accepted.
Weights: on-time 40%, quality 30%, lead time 15%, risk 15%. Standard library only.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date

WEIGHTS = {"on_time": 0.40, "quality": 0.30, "lead_time": 0.15, "risk": 0.15}
RISK_SCORE = {"low": 1.0, "medium": 0.6, "high": 0.2}
DEFECT_ZERO_AT = 5.0          # a 5% defect rate scores zero for quality
LEAD_BEST, LEAD_WORST = 3.0, 15.0
RENEWAL_WINDOW_DAYS = 90
LOW_COVER_MONTHS = 1.0


def number(value, default=0.0) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[^0-9.\-]", "", str(value or ""))
    try:
        return float(text) if text not in {"", "-", "."} else default
    except ValueError:
        return default


def flatten(supplier: dict) -> dict:
    metrics = supplier.get("metrics") or {}
    contract = supplier.get("contract") or {}
    return {
        "name": supplier.get("name"), "category": supplier.get("category"), "tier": supplier.get("tier"),
        "risk": str(supplier.get("risk") or "medium").lower(),
        "on_time_rate": supplier.get("on_time_rate", metrics.get("on_time_rate")),
        "defect_rate": supplier.get("defect_rate", metrics.get("defect_rate")),
        "avg_lead_days": supplier.get("avg_lead_days", metrics.get("avg_lead_days")),
        "open_value": supplier.get("open_value", metrics.get("open_value")),
        "contract": supplier.get("contract_id") or contract.get("id"),
        "contract_expires": supplier.get("contract_expires") or contract.get("expires"),
    }


def score(supplier: dict, as_of: date, items: list[dict]) -> dict:
    on_time = max(0.0, min(1.0, number(supplier["on_time_rate"]) / 100))
    quality = max(0.0, 1 - number(supplier["defect_rate"]) / DEFECT_ZERO_AT)
    lead = max(0.0, min(1.0, 1 - (number(supplier["avg_lead_days"], LEAD_WORST) - LEAD_BEST) / (LEAD_WORST - LEAD_BEST)))
    risk = RISK_SCORE.get(supplier["risk"], 0.6)
    total = 100 * (WEIGHTS["on_time"] * on_time + WEIGHTS["quality"] * quality + WEIGHTS["lead_time"] * lead
                   + WEIGHTS["risk"] * risk)
    flags = []
    try:
        expires = date.fromisoformat(str(supplier["contract_expires"])[:10]) if supplier["contract_expires"] else None
    except ValueError:
        expires = None
    if expires:
        days = (expires - as_of).days
        if days < 0:
            flags.append(f"Contract {supplier['contract'] or ''} expired {expires:%d %b %Y}".replace("  ", " "))
        elif days <= RENEWAL_WINDOW_DAYS:
            flags.append(f"Contract {supplier['contract'] or ''} expires {expires:%d %b %Y} ({days} days)".replace("  ", " "))
    if number(supplier["on_time_rate"], 100) < 90:
        flags.append(f"On-time delivery {number(supplier['on_time_rate']):g}% (below 90%)")
    if number(supplier["defect_rate"]) > 2:
        flags.append(f"Defect rate {number(supplier['defect_rate']):g}% (above 2%)")
    if supplier["risk"] == "high":
        flags.append("High supplier risk")
    for item in items:
        if str(item.get("supplier") or "") == str(supplier["name"]):
            cover = number(item.get("stock_coverage_months"), 99)
            if cover < LOW_COVER_MONTHS:
                lead_days = number(item.get("lead_time_days", item.get("lead-time-days")))
                flags.append(f"{item.get('name')}: {cover:g} months of stock" + (f", {lead_days:g}-day lead time" if lead_days else ""))
    band = "Strong" if total >= 85 else "Good" if total >= 75 else "Watch" if total >= 65 else "At risk"
    return {**supplier, "scores": {"on_time": round(on_time * 100), "quality": round(quality * 100),
                                   "lead_time": round(lead * 100), "risk": round(risk * 100)},
            "total": round(total, 1), "band": band, "flags": flags}


def main(argv: list[str]) -> int:
    try:
        raw = open(argv[0], encoding="utf-8").read() if argv else sys.stdin.read()
        data = json.loads(raw)
    except (OSError, ValueError) as error:
        print(json.dumps({"error": f"Could not read the input JSON: {error}"}))
        return 2
    if not isinstance(data, dict):
        data = {"suppliers": data}
    try:
        as_of = date.fromisoformat(str(data.get("as_of") or date.today().isoformat())[:10])
    except ValueError:
        print(json.dumps({"error": "as_of must be YYYY-MM-DD."}))
        return 2
    suppliers = [flatten(item) for item in data.get("suppliers") or [] if isinstance(item, dict) and item.get("name")]
    if not suppliers:
        print(json.dumps({"error": "No suppliers found in the input."}))
        return 2
    items = [item for item in data.get("items") or [] if isinstance(item, dict)]
    ranked = sorted((score(supplier, as_of, items) for supplier in suppliers), key=lambda item: -item["total"])
    for rank, item in enumerate(ranked, 1):
        item["rank"] = rank
    rows = ["| Rank | Supplier | Category | On-time | Quality | Lead time | Risk | Score | Band |",
            "|---|---|---|---|---|---|---|---|---|"]
    for item in ranked:
        rows.append(f"| {item['rank']} | {item['name']} | {item['category'] or ''} | {number(item['on_time_rate']):g}% | "
                    f"{number(item['defect_rate']):g}% defects | {number(item['avg_lead_days']):g} days | {item['risk']} | "
                    f"{item['total']:g} | {item['band']} |")
    print(json.dumps({"as_of": as_of.isoformat(), "weights": WEIGHTS, "suppliers": ranked,
                      "flagged": [item["name"] for item in ranked if item["flags"]], "table": "\n".join(rows)},
                     indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
