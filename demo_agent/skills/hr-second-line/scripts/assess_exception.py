"""Assess an HR exception request against the bank's policy and the statutory rules of the countries involved.

Usage: assess_exception.py <facts json path>
Facts: {"type": "work_abroad | carry_over | unpaid_leave | family_leave", "home_country": "US", "host_country": "ES",
 "working_days": 30, "consecutive_days": 30, "days_abroad_12m": 0, "carry_over_days": 0,
 "reason": "sickness | family_leave | business | personal", "manager_confirms_business_reason": false,
 "service_years": 0, "role": {"client_facing_regulated": false, "sales_or_contracting": false,
 "client_data_booking_centre": ""}, "right_to_work_in_host": true}
Countries are ISO 3166 alpha-2 codes. Prints and writes analysis/assessment.json. Standard library only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

EU_EEA_CH = set("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE IS LI NO CH".split())
US_TOTALISATION = set("AT BE CZ DK FI FR DE GR HU IE IT LU NL PL PT SK SI ES SE NO IS CH GB JP KR CA AU CL BR UY".split())
BLOCKED = {"RU", "BY", "IR", "KP", "SY", "CU", "CN"}
SECRECY = {"CH", "LU", "SG", "HK"}
STATUTORY_CARRY = {
    "GB": "The 4 EU-derived weeks carry over up to 18 months when sickness or family leave prevented them.",
    "DE": "Carry to 31 March; if sick, leave lapses only 15 months after the leave year.",
    "FR": "Leave lost to sickness or family leave is carried (up to 15 months for sickness).",
    "NL": "Statutory days last 6 months after year end, longer if the employee could not reasonably take them.",
    "IE": "Up to 15 months when sickness prevented the leave.",
    "CH": "Claims last 5 years.",
    "US": "No federal rule; California and Montana prohibit forfeiting accrued vacation.",
    "SG": "Per contract, commonly 12 months.",
    "HK": "Must be granted within 12 months after the leave year.",
    "IN": "State accumulation caps apply (for example 45 days in Maharashtra).",
}
PANEL_WORK = ["HR Business Partner", "Tax & Global Mobility", "Employment Counsel", "line manager"]


def work_abroad(facts: dict) -> dict:
    home, host = str(facts.get("home_country", "")).upper(), str(facts.get("host_country", "")).upper()
    days = int(facts.get("working_days") or 0) + int(facts.get("days_abroad_12m") or 0)
    consecutive = int(facts.get("consecutive_days") or facts.get("working_days") or 0)
    role = facts.get("role") or {}
    risks, conditions, blocks, panel_reasons = [], [], [], []
    if host in BLOCKED:
        blocks.append(f"W4: {host} is not an approved country for remote work.")
    if facts.get("right_to_work_in_host") is False:
        blocks.append("W9: no right to work in the host country; business-visitor status does not cover it.")
    if days > 60:
        blocks.append(f"W3: {days} working days in 12 months is over the 60-day maximum.")
    if role.get("sales_or_contracting"):
        risks.append("Permanent establishment: a sales or deal role working in the host country could create a "
                     "taxable presence for the bank.")
        conditions.append("Do not negotiate or conclude contracts while abroad.")
        panel_reasons.append("W6: sales or contracting role.")
        if consecutive > 30:
            blocks.append("W3: more than 30 consecutive days in a country with a permanent-establishment risk.")
    if role.get("client_facing_regulated"):
        conditions.append("Internal work only: no regulated activity with clients from the host country.")
    centre = str(role.get("client_data_booking_centre") or "").upper()
    if centre in SECRECY and host != centre:
        risks.append(f"Client confidentiality: {centre} booking-centre client data may not be accessed from {host}.")
        conditions.append(f"No access to {centre} client-identifying data while abroad.")
        panel_reasons.append("W7: secrecy-jurisdiction client data.")
    if host in EU_EEA_CH:
        conditions.append("Apply for an A1 certificate before travelling." if home in EU_EEA_CH else
                          (f"Obtain a US certificate of coverage for {host}." if home == "US" and host in US_TOTALISATION
                           else f"Social security in {host} must be checked by Tax & Global Mobility."))
    elif home == "US" and host in US_TOTALISATION:
        conditions.append(f"Obtain a US certificate of coverage for {host}.")
    else:
        risks.append(f"No social security agreement is assumed between {home} and {host}; host contributions may be due.")
        panel_reasons.append("Social security position needs Tax & Global Mobility.")
    if days > 20:
        panel_reasons.append(f"W2: {days} working days in 12 months is above the 20-day allowance.")
    conditions.append("Register the trip with Travel and keep a record of the working days.")
    if blocks:
        outcome, panel = "not_permitted", []
    elif panel_reasons:
        outcome, panel = "panel", PANEL_WORK
    else:
        outcome, panel = "within_policy", []
    return {"outcome": outcome, "working_days_12m": days, "blocks": blocks, "panel_reasons": panel_reasons,
            "risks": risks, "conditions": conditions, "panel": panel,
            "alternative": "An international assignment or a transfer, assessed by Global Mobility." if blocks else ""}


def carry_over(facts: dict) -> dict:
    home = str(facts.get("home_country", "")).upper()
    days = float(facts.get("carry_over_days") or 0)
    reason = str(facts.get("reason", ""))
    law = STATUTORY_CARRY.get(home, "Check the local statutory rule with the HR Business Partner.")
    if reason in ("sickness", "family_leave"):
        return {"outcome": "statutory_right", "rule": "L2", "law": law, "panel": [],
                "conditions": ["Carry the statutory days the employee could not take, within the statutory window."]}
    if days <= 5:
        return {"outcome": "within_policy", "rule": "L1", "law": law, "panel": [],
                "conditions": ["Take the carried days by 31 March."]}
    if reason == "business" and facts.get("manager_confirms_business_reason") and days <= 10:
        return {"outcome": "panel", "rule": "L3", "law": law, "panel": ["HR Business Partner", "line manager"],
                "conditions": ["Take the carried days by 30 June."]}
    return {"outcome": "not_permitted", "rule": "L4", "law": law, "panel": [],
            "conditions": [], "alternative": "Carry 5 days; pay in lieu only where the country's law allows it."}


def unpaid(facts: dict) -> dict:
    days = int(facts.get("working_days") or 0)
    if facts.get("type") == "family_leave":
        return {"outcome": "statutory_right", "rule": "U3", "panel": [],
                "conditions": ["Book the statutory absence type in Workday."]}
    if days <= 20:
        return {"outcome": "within_policy", "rule": "U1", "panel": [], "conditions": ["Manager agreement recorded."]}
    if days <= 130 and float(facts.get("service_years") or 0) >= 5:
        return {"outcome": "panel", "rule": "U2", "panel": ["HR Business Partner", "line manager"],
                "conditions": ["Benefits and pension continuity confirmed before the leave starts."]}
    return {"outcome": "not_permitted", "rule": "U2", "panel": [], "conditions": [],
            "alternative": "Up to 20 days unpaid leave, or a sabbatical after 5 years' service."}


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: assess_exception.py <facts json>")
        sys.exit(2)
    path = Path(sys.argv[1])
    if not path.is_file():
        print(json.dumps({"error": f"{path} is not in the workspace; write the facts first."}))
        sys.exit(1)
    facts = json.loads(path.read_text(encoding="utf-8"))
    handler = {"work_abroad": work_abroad, "carry_over": carry_over, "unpaid_leave": unpaid,
               "family_leave": unpaid}.get(facts.get("type"))
    result = handler(facts) if handler else {"error": "type must be work_abroad, carry_over, unpaid_leave or family_leave."}
    Path("analysis").mkdir(exist_ok=True)
    Path("analysis/assessment.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
