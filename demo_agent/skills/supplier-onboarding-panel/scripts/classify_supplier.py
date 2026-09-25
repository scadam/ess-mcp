"""Classify a prospective supplier into a risk tier and list the due-diligence sections, reviewers and questions.

Usage: classify_supplier.py <supplier json>
Supplier json: {"name": "...", "country": "GB", "service": "...", "annual_spend_gbp": 120000,
 "critical_ict_service": false, "regulated_outsourcing": false, "handles_personal_data": true,
 "access_to_bank_network": false}
Prints and writes analysis/classification.json. Standard library only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HIGH_RISK = {"IR", "KP", "MM", "RU", "BY", "SY", "CU", "VE", "AF", "YE", "HT", "SS", "ML", "BF", "NG", "ZA", "CM",
             "CD", "MZ", "TZ", "VN", "LA", "BG", "MC", "KE", "NA", "DZ", "LB"}  # Demo snapshot; keep in step with FATF.
REVIEWERS = {
    "information_security": ("Kadji Bell", "KadjiB@Caldova74201480.OnMicrosoft.com",
                             ["ISO 27001 or SOC 2 Type II report current?", "Penetration test in the last 12 months?",
                              "What access to the bank's network or data?", "Incident notification within 24 hours?"]),
    "data_protection": ("Kenvin Sturis", "KenvinS@Caldova74201480.OnMicrosoft.com",
                        ["What personal or client data, and where is it processed and stored?",
                         "International transfers and the mechanism?", "Sub-processors?", "DPA terms agreed?"]),
    "financial_crime": ("Aadi Kapoor", "AadiK@Caldova74201480.OnMicrosoft.com",
                        ["Sanctions and PEP screening of the entity and its owners", "Anti-bribery controls",
                         "Adverse media"]),
    "financial_standing": ("Charlotte Waltson", "CharlotteW@Caldova74201480.OnMicrosoft.com",
                           ["Latest accounts and credit rating", "Dependency on the bank", "Payment terms"]),
    "operational_resilience": ("Elvia Atkins", "ElviaA@Caldova74201480.OnMicrosoft.com",
                               ["Exit plan and substitutability", "Concentration risk", "Business continuity testing",
                                "Sub-outsourcing chain", "Audit and access rights (DORA Art. 30)"]),
}


def classify(facts: dict) -> dict:
    country = str(facts.get("country") or "").upper()
    reasons = []
    if facts.get("critical_ict_service") or facts.get("regulated_outsourcing"):
        tier = 1
        reasons.append("Supports a critical or important function / regulated outsourcing.")
    else:
        if facts.get("handles_personal_data"):
            reasons.append("Processes personal or client data.")
        if float(facts.get("annual_spend_gbp") or 0) > 250_000:
            reasons.append("Annual spend above £250,000.")
        if country in HIGH_RISK:
            reasons.append(f"{country} is a high-risk jurisdiction.")
        if facts.get("access_to_bank_network"):
            reasons.append("Access to the bank's network.")
        tier = 2 if reasons else 3
    required = {1: list(REVIEWERS), 2: ["information_security", "data_protection", "financial_crime",
                                        "financial_standing"], 3: ["financial_crime", "financial_standing"]}[tier]
    sections = []
    for name, (reviewer, email, questions) in REVIEWERS.items():
        applies = name in required
        sections.append({"section": name, "applies": applies, "reviewer": reviewer if applies else "",
                         "email": email if applies else "", "questions": questions if applies else [],
                         "not_applicable_reason": "" if applies else f"Not required for tier {tier}."})
    follow_ups = ["Add to the DORA register of information.", "Check regulator notification requirements."] if tier == 1 else []
    return {"tier": tier, "reasons": reasons or ["Standard supplier."], "sections": sections,
            "reviewers": sorted({item["email"] for item in sections if item["applies"]}), "follow_ups": follow_ups}


def main() -> None:
    if len(sys.argv) != 2 or not Path(sys.argv[1]).is_file():
        print("usage: classify_supplier.py <supplier json in the workspace>")
        sys.exit(2)
    result = classify(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    Path("analysis").mkdir(exist_ok=True)
    Path("analysis/classification.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
