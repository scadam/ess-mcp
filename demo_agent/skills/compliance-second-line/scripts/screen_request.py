"""Screen a compliance request against the gifts, personal dealing and conflicts policies.

Usage: screen_request.py <facts json path>
Prints and writes analysis/screening.json: rule outcomes, decision, authority, approvers and conditions.
Optional fields beyond the SKILL.md example: renewal_within_90_days, events_12m (gifts); instrument_name, notional,
requester_on_insider_list, desk_trading_for_clients, at_a_loss (pad); hours_per_week, regulated_role (obi).
Standard library only.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RATES = {"GBP": 1.0, "USD": 0.79, "EUR": 0.86}
RESTRICTED = {"NBR": "Northbridge Renewables plc", "SBG": "Seabrook Grid Holdings", "ALB": "Alderbridge Bank plc",
              "HWM": "Harwell Minerals"}
INSIDER_PARTIES = {"northbridge renewables", "seabrook grid"}


def _gbp(facts: dict, key: str = "value") -> float:
    currency = str(facts.get("currency") or "GBP").upper()
    return round(float(facts.get(key) or 0) * RATES.get(currency, 1.0), 2)


MANAGER, ADVISORY, CCO = "line manager", "Head of Compliance Advisory", "Chief Compliance Officer"


def _hit(rules: list, code: str, text: str, outcome: str, approvers: tuple[str, ...] = ()) -> None:
    rules.append({"rule": code, "finding": text, "outcome": outcome, "approvers": list(approvers)})


def gifts(facts: dict) -> dict:
    rules: list[dict] = []
    value = _gbp(facts)
    if facts.get("spouse_or_guest"):
        value *= 2
        _hit(rules, "G9", "Extended to a spouse or guest: value doubled and reviewed.", "review", (MANAGER, ADVISORY))
    cumulative = value + _gbp(facts, "prior_12m_value")
    kind = str(facts.get("type", ""))
    description = str(facts.get("description", "")).casefold()
    if any(word in description for word in ("cash", "voucher", "gift card", "loan")):
        _hit(rules, "G7", "Cash or cash equivalent.", "decline")
    if facts.get("counterparty_type") == "public_official":
        _hit(rules, "G5", "Counterparty is a public official.", "escalate", (CCO,))
    if facts.get("active_tender") or (facts.get("requester_is_approver_for_counterparty")
                                      and facts.get("renewal_within_90_days")):
        if kind.startswith("hospitality") or value > 50:
            _hit(rules, "G6", "Counterparty is in an active tender or renewal the requester influences.", "decline")
    if value > 500 or cumulative > 1000:
        _hit(rules, "G4", f"Value £{value:,.2f} (12-month total £{cumulative:,.2f}) is above CCO thresholds.",
             "escalate", (CCO,))
    elif value > 250 or facts.get("includes_travel_or_accommodation"):
        _hit(rules, "G3", f"Value £{value:,.2f} or travel/accommodation: compliance pre-approval.", "approve")
    if value > 100:
        _hit(rules, "G2", "Above £100: line manager approval needed.", "review", (MANAGER,))
    if int(facts.get("events_12m") or 0) >= 4 and kind.startswith("hospitality"):
        _hit(rules, "G8", "Five or more hospitality events from this counterparty in 12 months.", "review",
             (MANAGER, ADVISORY))
    register = value > 50
    conditions = ["Attend with a clear business purpose.", "No commercial discussion of live negotiations."]
    if facts.get("includes_travel_or_accommodation"):
        conditions.append("The bank pays for any travel and accommodation.")
    return {"value_gbp": value, "cumulative_12m_gbp": cumulative, "rules": rules, "register": register,
            "conditions": conditions}


def pad(facts: dict) -> dict:
    rules: list[dict] = []
    ticker = str(facts.get("instrument") or "").upper().strip()
    name = str(facts.get("instrument_name") or "").casefold()
    if ticker in RESTRICTED or any(item.casefold() in name for item in RESTRICTED.values() if name):
        _hit(rules, "P2", "Instrument is on the restricted list (do not disclose why).", "decline")
    if facts.get("requester_on_insider_list") or any(party in name for party in INSIDER_PARTIES if name):
        _hit(rules, "P3", "Instrument of a party to a live insider project (do not disclose why).", "decline")
    if facts.get("desk_trading_for_clients"):
        _hit(rules, "P6", "The requester's desk is trading this instrument for clients.", "decline")
    notional = _gbp(facts, "notional")
    if notional > 100_000:
        _hit(rules, "P7", f"Notional £{notional:,.0f} is above £100,000.", "escalate", (CCO,))
    early = 0 < int(facts.get("holding_days") or 0) < 30
    if str(facts.get("direction", "")).lower() == "sell" and early and not facts.get("at_a_loss"):
        _hit(rules, "P4", "Selling inside the 30-day holding period at a gain.", "escalate", (CCO,))
    return {"notional_gbp": notional, "rules": rules, "register": False,
            "conditions": ["Clearance lapses at the end of the next business day.",
                           "Hold for at least 30 days."]}


def conflicts(facts: dict) -> dict:
    rules: list[dict] = []
    kind = facts.get("counterparty_type")
    if facts.get("type") == "obi":
        if kind in ("client", "supplier", "competitor"):
            _hit(rules, "C3", f"Outside interest in a {kind}.", "decline")
        elif float(facts.get("hours_per_week") or 0) > 5:
            _hit(rules, "C3", "More than 5 hours a week.", "decline")
        elif facts.get("regulated_role"):
            _hit(rules, "C5", "Regulated (SM&CR) role.", "escalate", (CCO,))
        else:
            _hit(rules, "C3", "Outside interest needs manager approval and compliance review.", "review",
                 (MANAGER, ADVISORY))
    elif facts.get("requester_is_approver_for_counterparty"):
        _hit(rules, "C2", "Declared interest: remove from the approval chain for the counterparty and record.",
             "review", (MANAGER, ADVISORY))
    else:
        _hit(rules, "C2", "Declared interest with no decision role over the counterparty: record it.", "approve")
    return {"rules": rules, "register": False,
            "conditions": ["Recorded on the conflicts register.", "Re-declare if circumstances change."]}


def screen(facts: dict) -> dict:
    kind = str(facts.get("type", ""))
    if kind.startswith(("gift", "hospitality")):
        result = gifts(facts)
    elif kind == "pad":
        result = pad(facts)
    elif kind in ("obi", "conflict"):
        result = conflicts(facts)
    else:
        return {"error": "type must be gift_*, hospitality_*, pad, obi or conflict."}
    outcomes = {rule["outcome"] for rule in result["rules"]}
    if "decline" in outcomes:
        decision = "decline"
    elif "escalate" in outcomes:
        decision = "escalate_cco"
    elif "review" in outcomes:
        decision = "review_required"
    else:
        decision = "approve"
    wanted = {"review_required": "review", "escalate_cco": "escalate"}.get(decision)
    approvers = list(dict.fromkeys(name for rule in result["rules"] if rule["outcome"] == wanted
                                   for name in rule["approvers"]))
    return {**result, "decision": decision, "within_authority": decision in ("approve", "decline"),
            "approvers": approvers}


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: screen_request.py <facts json>")
        sys.exit(2)
    path = Path(sys.argv[1])
    if not path.is_file():
        print(json.dumps({"error": f"{path} is not in the workspace; write the facts first."}))
        sys.exit(1)
    result = screen(json.loads(path.read_text(encoding="utf-8")))
    Path("analysis").mkdir(exist_ok=True)
    Path("analysis/screening.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
