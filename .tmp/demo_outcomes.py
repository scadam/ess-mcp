"""Run the skills' deterministic scripts on the demo scenarios to confirm the outcomes the demo script promises."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "demo_agent" / "skills"
CASES = {
    "wimbledon-just-colin": ("compliance-second-line/scripts/screen_request.py", {
        "type": "hospitality_received", "value": 420, "currency": "GBP", "counterparty": "TechDirect UK Ltd",
        "counterparty_type": "supplier", "active_tender": False, "event_date": "2027-07-03", "prior_12m_value": 0,
        "includes_travel_or_accommodation": False, "spouse_or_guest": False,
        "requester_role": "Sourcing and Procurement Manager", "requester_is_approver_for_counterparty": True,
        "renewal_within_90_days": False, "events_12m": 0,
        "description": "Two Centre Court debenture seats with lunch at Wimbledon; the second seat is for a TechDirect colleague"}),
    "wimbledon-with-wife": ("compliance-second-line/scripts/screen_request.py", {
        "type": "hospitality_received", "value": 420, "currency": "GBP", "counterparty": "TechDirect UK Ltd",
        "counterparty_type": "supplier", "active_tender": False, "prior_12m_value": 0,
        "includes_travel_or_accommodation": False, "spouse_or_guest": True,
        "requester_role": "Sourcing and Procurement Manager", "requester_is_approver_for_counterparty": True,
        "renewal_within_90_days": False, "description": "Two Centre Court debenture seats with lunch"}),
    "wimbledon-renewal": ("compliance-second-line/scripts/screen_request.py", {
        "type": "hospitality_received", "value": 420, "currency": "GBP", "counterparty": "TechDirect UK Ltd",
        "counterparty_type": "supplier", "active_tender": False, "prior_12m_value": 0,
        "includes_travel_or_accommodation": False, "spouse_or_guest": False,
        "requester_role": "Sourcing and Procurement Manager", "requester_is_approver_for_counterparty": True,
        "renewal_within_90_days": True, "description": "Two Centre Court debenture seats with lunch"}),
    "nbr-pad": ("compliance-second-line/scripts/screen_request.py", {
        "type": "pad", "instrument": "NBR", "instrument_name": "Northbridge Renewables plc", "direction": "buy",
        "quantity": 500, "notional": 6200, "currency": "GBP", "holding_days": 30}),
    "karin-carry-over": ("hr-second-line/scripts/assess_exception.py", {
        "type": "carry_over", "home_country": "GB", "carry_over_days": 9, "reason": "business",
        "manager_confirms_business_reason": False, "service_years": 6,
        "role": {"client_facing_regulated": False, "sales_or_contracting": False, "client_data_booking_centre": ""}}),
    "daisy-lisbon": ("hr-second-line/scripts/assess_exception.py", {
        "type": "work_abroad", "home_country": "GB", "host_country": "PT", "working_days": 30,
        "consecutive_days": 30, "days_abroad_12m": 0,
        "role": {"client_facing_regulated": False, "sales_or_contracting": False, "client_data_booking_centre": ""},
        "right_to_work_in_host": True}),
    "nimbus-onboarding": ("supplier-onboarding-panel/scripts/classify_supplier.py", {
        "name": "Nimbus Analytics Ltd", "country": "GB",
        "service": "Customer churn modelling on pseudonymised retail account data", "annual_spend_gbp": 180000,
        "critical_ict_service": False, "regulated_outsourcing": False, "handles_personal_data": True,
        "access_to_bank_network": False}),
}

for name, (script, facts) in CASES.items():
    with tempfile.TemporaryDirectory() as work:
        Path(work, "facts.json").write_text(json.dumps(facts), encoding="utf-8")
        result = subprocess.run([sys.executable, "-I", "-S", "-X", "utf8", str(ROOT / script), "facts.json"],
                                cwd=work, capture_output=True, text=True, encoding="utf-8")
        print(f"=== {name} (exit {result.returncode})")
        print((result.stdout or result.stderr).strip()[:1800])
