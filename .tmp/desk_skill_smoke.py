"""Smoke-run the new desk skill scripts on realistic inputs and check the packages load."""
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "demo_agent" / "skills"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "mcp_servers" / "src"))

from demo_agent.skill_runtime import load_library  # noqa: E402
from mcp_servers.coupa import core  # noqa: E402

library = load_library(SKILLS)
for name in ("it-second-line", "compliance-second-line", "hr-second-line", "supply-second-line",
             "access-review-panel", "supplier-onboarding-panel"):
    package = library.get(name)
    assert package is not None, f"{name} did not load"
    print(f"{name}: mode={package.metadata.get('mode')} budget={package.budget} "
          f"grants={[g.label() for g in package.grants]} files={len(package.files())}")

CASES = {
    "it-second-line/scripts/diagnose_device.py": ("data/diagnostic.txt",
        "BATTERY REPORT\nSYSTEM PRODUCT NAME Latitude 7440\nSERIAL NUMBER 7GHX2Z3\n"
        "DESIGN CAPACITY 57,000 mWh\nFULL CHARGE CAPACITY 26,904 mWh\nCYCLE COUNT 912\n", "conclusion"),
    "compliance-second-line/scripts/screen_request.py": ("data/request.json", json.dumps({
        "type": "hospitality_received", "value": 420, "currency": "GBP", "counterparty": "TechDirect UK Ltd",
        "counterparty_type": "supplier", "active_tender": False, "requester_is_approver_for_counterparty": True,
        "description": "Two Wimbledon debenture tickets with lunch"}), "decision"),
    "hr-second-line/scripts/assess_exception.py": ("data/request.json", json.dumps({
        "type": "work_abroad", "home_country": "US", "host_country": "ES", "working_days": 30, "consecutive_days": 30,
        "role": {"sales_or_contracting": True}, "right_to_work_in_host": True}), "outcome"),
    "supplier-onboarding-panel/scripts/classify_supplier.py": ("data/supplier.json", json.dumps({
        "name": "Nimbus Ledger Ltd", "country": "IE", "service": "Cloud reconciliation SaaS",
        "critical_ict_service": True, "handles_personal_data": True}), "tier"),
}


def run(script: str, work: str, *args: str) -> dict:
    done = subprocess.run([sys.executable, "-I", "-S", str(SKILLS / script), *args], cwd=work,
                          capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, f"{script} failed: {done.stderr[-800:]}"
    return json.loads(done.stdout)


for script, (relative, content, key) in CASES.items():
    with tempfile.TemporaryDirectory() as work:
        target = Path(work, relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        data = run(script, work, relative)
        print(f"{Path(script).name}: {key}={data[key]}", json.dumps(data)[:500])

sources = {"invoice": core.tool_get_invoice("INV-TD-88213"), "order": core.tool_get_purchase_order("PO-2026-1082"),
           "receipts": core.tool_list_receiving_transactions("PO-2026-1082")}
with tempfile.TemporaryDirectory() as work:
    for name, coroutine in sources.items():
        Path(work, f"{name}.json").write_text(json.dumps(asyncio.run(coroutine)), encoding="utf-8")
    data = run("supply-second-line/scripts/match_invoice.py", work, "invoice.json", "order.json", "receipts.json")
    print("match_invoice.py:", [(item["type"], item["question"]) for item in data["exceptions"]])

groups = [{"found": True, "group": "CAB Approval", "members": [
    {"user_name": "beth.anglin", "name": "Beth Anglin", "active": "true", "last_login": "2026-09-20 10:00:00"},
    {"user_name": "old.user", "name": "Old User", "active": "false", "last_login": "2025-01-01 10:00:00"}]},
    {"found": True, "group": "Change Management", "members": [
        {"user_name": "beth.anglin", "name": "Beth Anglin", "active": "true", "last_login": "2026-09-20 10:00:00"}]}]
with tempfile.TemporaryDirectory() as work:
    Path(work, "groups.json").write_text(json.dumps(groups), encoding="utf-8")
    data = run("access-review-panel/scripts/review_pack.py", work, "groups.json")
    print("review_pack.py:", data["population"], "rows,", data["flagged"], "flagged:",
          [row["flags"] for row in data["flagged_rows"]])

sim = asyncio.run(core.tool_create_supplier_information("Nimbus Ledger Ltd", "IE", "Reconciliation SaaS", "Ana Byrne",
                                                         "ana@nimbus.example.com", critical_ict_service=True))
record = str(sim["supplier-information"]["id"])
for section in core.SIM_SECTIONS:
    asyncio.run(core.tool_record_due_diligence(record, section, "pass", "ok", "Reviewer"))
approved = asyncio.run(core.tool_approve_supplier_information(record, "All sections passed."))
print("supplier onboarding:", approved["status"], approved["supplier"]["number"])
print("ALL OK")
