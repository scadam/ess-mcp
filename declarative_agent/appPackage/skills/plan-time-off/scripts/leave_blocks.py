"""Split a leave request into Monday-Friday blocks and give the Workday quantity for each.

Usage: python leave_blocks.py --start 2026-10-02 --end 2026-10-06 [--unit Hours|Days] [--hours-per-day 8] [--half-day]

Workday books the quantity on every date from start to end, so each block is a run of consecutive weekdays.
Prints JSON: blocks (startDate, endDate, workingDays, quantityPerDay, totalQuantity), totals and weekendDaysSkipped.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta

MAX_SPAN_DAYS = 62


def number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", required=True, help="First day, YYYY-MM-DD")
    parser.add_argument("--end", help="Last day, YYYY-MM-DD (defaults to the start date)")
    parser.add_argument("--unit", default="Hours", choices=["Hours", "Days"])
    parser.add_argument("--hours-per-day", type=float, default=8.0)
    parser.add_argument("--half-day", action="store_true")
    args = parser.parse_args(argv)
    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end or args.start)
    except ValueError:
        print(json.dumps({"error": "Dates must be YYYY-MM-DD."}))
        return 2
    if end < start:
        print(json.dumps({"error": "The end date is before the start date."}))
        return 2
    if (end - start).days > MAX_SPAN_DAYS:
        print(json.dumps({"error": f"That is more than {MAX_SPAN_DAYS} days: treat it as a leave of absence, not time off."}))
        return 2
    if not 0 < args.hours_per_day <= 24:
        print(json.dumps({"error": "hours-per-day must be between 0 and 24."}))
        return 2

    per_day = (args.hours_per_day if args.unit == "Hours" else 1.0) * (0.5 if args.half_day else 1.0)
    blocks: list[dict] = []
    skipped = 0
    day = start
    while day <= end:
        if day.weekday() < 5:
            if blocks and (day - date.fromisoformat(blocks[-1]["endDate"])).days == 1:
                blocks[-1]["endDate"] = day.isoformat()
                blocks[-1]["workingDays"] += 1
            else:
                blocks.append({"startDate": day.isoformat(), "endDate": day.isoformat(), "workingDays": 1})
        else:
            skipped += 1
        day += timedelta(days=1)
    for block in blocks:
        block["quantityPerDay"] = number(per_day)
        block["totalQuantity"] = number(per_day * block["workingDays"])
        block["unit"] = args.unit
        block["label"] = (date.fromisoformat(block["startDate"]).strftime("%a %d %b %Y")
                          + ("" if block["startDate"] == block["endDate"]
                             else " – " + date.fromisoformat(block["endDate"]).strftime("%a %d %b %Y")))
    working = sum(block["workingDays"] for block in blocks)
    result = {"blocks": blocks, "workingDays": working, "totalQuantity": number(per_day * working), "unit": args.unit,
              "weekendDaysSkipped": skipped}
    if not blocks:
        result["note"] = "Those dates fall on a weekend: no working time is needed."
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
