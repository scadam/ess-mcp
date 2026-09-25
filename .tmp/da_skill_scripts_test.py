"""Run the declarative agent skill scripts on real tool results and check the key outcomes."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path("declarative_agent/appPackage/skills")
data = Path(os.environ["TEMP"]) / "da-tests"
report = open(Path(os.environ["TEMP"]) / "ap-da-scripts.txt", "w", encoding="utf-8")
failures = 0


def run(script: str, *args: str, stdin: str | None = None) -> dict:
    done = subprocess.run([sys.executable, "-I", "-X", "utf8", str(root / script), *args], input=stdin,
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    try:
        return {"exit": done.returncode, **json.loads(done.stdout)}
    except ValueError:
        return {"exit": done.returncode, "stdout": done.stdout[:500], "stderr": done.stderr[:500]}


def check(label: str, condition: bool, detail) -> None:
    global failures
    failures += 0 if condition else 1
    report.write(f"{'PASS' if condition else 'FAIL'} {label}: {json.dumps(detail, ensure_ascii=False)[:400]}\n")


blocks = run("plan-time-off/scripts/leave_blocks.py", "--start", "2026-10-02", "--end", "2026-10-06")
check("leave: Fri + Mon-Tue split around the weekend",
      [(b["startDate"], b["endDate"], b["quantityPerDay"]) for b in blocks.get("blocks", [])]
      == [("2026-10-02", "2026-10-02", "8"), ("2026-10-05", "2026-10-06", "8")] and blocks.get("totalQuantity") == "24", blocks)
half = run("plan-time-off/scripts/leave_blocks.py", "--start", "2026-10-02", "--half-day")
check("leave: half day = 4 hours", half.get("totalQuantity") == "4", half)
weekend = run("plan-time-off/scripts/leave_blocks.py", "--start", "2026-10-03", "--end", "2026-10-04", "--unit", "Days")
check("leave: weekend only", weekend.get("blocks") == [] and "weekend" in weekend.get("note", ""), weekend)
bad = run("plan-time-off/scripts/leave_blocks.py", "--start", "2026-10-06", "--end", "2026-10-02")
check("leave: end before start rejected", bad["exit"] == 2 and "error" in bad, bad)

flows = (data / "coupa.get_servicenow_coupa_flow.json").read_text(encoding="utf-8")
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
    handle.write(flows)
matched = run("invoice-three-way-match/scripts/three_way_match.py", handle.name)
by_invoice = {item["invoice"]: item for item in matched.get("results", [])}
check("match: three invoices", sorted(by_invoice) == ["INV-2026-0398", "INV-2026-0412", "INV-2026-0417"], matched.get("summary"))
check("match: 0412 billed ahead of receipt",
      by_invoice.get("INV-2026-0412", {}).get("verdict") == "Billed ahead of receipt"
      and by_invoice["INV-2026-0412"]["received"] == 16428.0 and by_invoice["INV-2026-0412"]["action"] == "reject",
      by_invoice.get("INV-2026-0412"))
check("match: 0417 short by 4 iPhones", by_invoice.get("INV-2026-0417", {}).get("action") == "reject"
      and by_invoice["INV-2026-0417"]["outstanding"] == [{"item": "iPhone 15 128GB", "quantity": 4.0, "value": 2796.0}],
      by_invoice.get("INV-2026-0417"))
check("match: 0398 paid and matching", by_invoice.get("INV-2026-0398", {}).get("verdict") == "Matches", by_invoice.get("INV-2026-0398"))
compact = json.dumps([{"invoice": "INV-1", "invoice_id": "1", "status": "paid", "billed": "10,000.00", "po": "PO-1",
                       "lines": [{"item": "Laptop", "ordered_qty": 10, "received_qty": 5, "unit_price": 1000}]}])
paid = run("invoice-three-way-match/scripts/three_way_match.py", stdin=compact)
check("match: paid ahead of receipt is recovered, not rejected",
      paid.get("results", [{}])[0].get("verdict") == "Paid ahead of receipt" and paid["results"][0]["action"] == "recover", paid.get("results"))

suppliers = json.loads((data / "coupa.get_supplier_performance.json").read_text(encoding="utf-8"))
demand = json.loads((data / "coupa.get_item_demand.json").read_text(encoding="utf-8"))
payload = {"as_of": "2026-05-06", "suppliers": suppliers["suppliers"], "items": demand["items"]}
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as handle:
    json.dump(payload, handle)
scored = run("supplier-scorecard/scripts/score_suppliers.py", handle.name)
ranked = [(item["name"], item["total"], item["band"], item["flags"]) for item in scored.get("suppliers", [])]
check("scorecard: five ranked, Dell first", len(ranked) == 5 and ranked[0][0] == "Dell Premier Solutions", ranked)
insight = next((item for item in scored.get("suppliers", []) if item["name"].startswith("Insight")), {})
check("scorecard: Insight flagged for contract, delivery and quality",
      any("Contract" in flag for flag in insight.get("flags", [])) and any("On-time" in flag for flag in insight.get("flags", []))
      and any("Defect" in flag for flag in insight.get("flags", [])), insight.get("flags"))
apple = next((item for item in scored.get("suppliers", []) if item["name"].startswith("Apple")), {})
check("scorecard: Apple low-stock item flagged", any("iPhone 15 Pro" in flag for flag in apple.get("flags", [])), apple.get("flags"))
report.write("\n" + scored.get("table", "") + "\n\n" + matched.get("table", "") + "\n")
report.write(f"\n{failures} failure(s)\n")
report.close()
sys.exit(1 if failures else 0)
