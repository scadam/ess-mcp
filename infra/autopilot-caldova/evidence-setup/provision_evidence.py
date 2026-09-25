"""One-shot job: provision the Compliance Partner demo evidence list through Microsoft Graph.

Runs as a Container Apps job with a TEMPORARY user-assigned managed identity that
holds only Graph Sites.Manage.All; the orchestrating script deletes that identity
afterwards. It creates (idempotently) a list on the tenant root site with the
exact column names demo_agent.compliance_backend validates, upserts seven approved
FICTIONAL demonstration records, and prints the Graph evidence paths as one JSON line.
"""

from __future__ import annotations

import json
import os
import sys

import httpx
from azure.identity import ManagedIdentityCredential

GRAPH = "https://graph.microsoft.com/v1.0"
LIST_NAME = "Compliance Evidence Library"
COLUMNS = [
    {"name": "Category", "text": {"maxLength": 64}},
    {"name": "Approved", "boolean": {}},
    {"name": "Version", "text": {"maxLength": 80}},
    {"name": "Content", "text": {"allowMultipleLines": True, "textType": "plain", "linesForEditing": 12}},
    {"name": "AdviceClosureAllowed", "boolean": {}},
    {"name": "RequiresSpecialist", "boolean": {}},
    {"name": "ApprovedRoute", "text": {"allowMultipleLines": True, "textType": "plain", "linesForEditing": 6}},
]
ROUTE = {
    "recipientEntity": "Harbourline Advisory LLP (UK)",
    "location": "United Kingdom",
    "purpose": "Advisory support for the Northbridge Renewables refinancing lender call",
    "documentSet": ["Aggregate forecast summary", "Draft lender presentation"],
    "channel": "Seabrook secure data room with named UK wall-crossed users",
    "excludedData": ["Revised liquidity and covenant forecasts", "Beneficial ownership register",
                     "Directors' identity documents"],
    "conditions": ["Recipients limited to the named wall-crossed UK team",
                   "No onward sharing to affiliates, including the Singapore team",
                   "Data room access ends after the lender call and is logged"],
}
# Fictional demonstration data only: not legal advice or any real bank's rules.
RECORDS = [
    {"Title": "Executed NDA and entity schedule - Harbourline Advisory", "Category": "nda", "Version": "NDA-HBL-2026-07 v3",
     "Content": ("Fictional demo record. Alderbridge Bank and Harbourline Advisory LLP, the UK contracting entity, executed a "
                 "mutual NDA for evaluating the Northbridge Renewables refinancing (Project Seabrook). Covered recipients are "
                 "Harbourline Advisory LLP and its UK employees named on the schedule. Affiliates, including Harbourline "
                 "Advisory Pte Ltd in Singapore, are not covered recipients. No schedule amendment adding an affiliate is recorded.")},
    {"Title": "Borrower consent to adviser disclosure - Northbridge Renewables", "Category": "borrower_consent",
     "Version": "CONSENT-NBR-2026-08 v2",
     "Content": ("Fictional demo record. Northbridge Renewables plc consents to Alderbridge Bank sharing refinancing information "
                 "with its appointed financing adviser for the lender process. The consent covers aggregate financial "
                 "information and the draft lender presentation only. Personal data, the beneficial ownership register and "
                 "directors' identity documents are excluded. The receiving entity must be bound by the executed NDA.")},
    {"Title": "Supplier assurance record - Harbourline Advisory", "Category": "supplier", "Version": "TPRM-4471 v5",
     "Content": ("Fictional demo record. Approved legal entity: Harbourline Advisory LLP (UK). Approved service: transaction "
                 "advisory. Approved delivery location: United Kingdom only. Approved subprocessors: none. The group-level "
                 "green status does not extend to affiliates; Harbourline Advisory Pte Ltd (Singapore) has no assurance "
                 "record. Assurance is current until 31 March 2027.")},
    {"Title": "Project Seabrook restricted information record", "Category": "restrictions", "Version": "WL-SEABROOK v4",
     "Content": ("Fictional demo record. Project Seabrook is on the watch list. Revised liquidity and covenant forecasts are "
                 "inside information and remain restricted to individuals on the Seabrook insider list. The aggregate "
                 "forecast summary prepared by Deal Control may be shared with wall-crossed adviser staff. Distribution is "
                 "only through the Seabrook secure data room.")},
    {"Title": "Seabrook diligence pack inventory and classification", "Category": "inventory", "Version": "INV-SEABROOK v7",
     "Content": ("Fictional demo record. The pack contains: revised liquidity and covenant forecasts (highly confidential, "
                 "inside information); aggregate forecast summary (confidential, approved for wall-crossed advisers); "
                 "beneficial ownership register (personal data); directors' identity documents (personal data, KYC); draft "
                 "lender presentation (confidential). The advisory purpose needs only the aggregate forecast summary and the "
                 "draft lender presentation.")},
    {"Title": "Third-party disclosure standard", "Category": "policy", "Version": "POL-TPD-2026 v2",
     "AdviceClosureAllowed": True, "RequiresSpecialist": False, "ApprovedRoute": json.dumps(ROUTE, separators=(",", ":")),
     "Content": ("Fictional demo record. Confidential client information may be disclosed to a third party only when the "
                 "receiving legal entity is covered by an executed NDA, the client's consent covers the purpose and data, the "
                 "receiving entity and delivery location are approved in supplier assurance, inside information goes only to "
                 "wall-crossed recipients, and only the minimum necessary data is shared through the approved secure data "
                 "room. Personal data and KYC documents are not disclosed to advisers for advisory purposes. Where an "
                 "already-authorized route meets every condition, the Compliance Partner may give that route as advice and "
                 "close the case after the requester confirms the question is resolved.")},
    {"Title": "Approved alternative - Harbourline UK-only team", "Category": "alternative", "Version": "ALT-SEABROOK-UK v2",
     "Content": ("Fictional demo record. A named four-person Harbourline Advisory LLP team in London is already wall-crossed for "
                 "Project Seabrook, is on the insider list and has named access to the Seabrook secure data room. This route "
                 "was used for the previous lender update and remains authorized for adviser work on the refinancing.")},
]


def _ok(response: httpx.Response, action: str) -> dict:
    if response.status_code >= 400:
        raise SystemExit(f"{action} failed with HTTP {response.status_code}: {response.text[:300]}")
    return response.json() if response.content else {}


def main() -> None:
    token = ManagedIdentityCredential(client_id=os.environ["AZURE_CLIENT_ID"]).get_token(
        "https://graph.microsoft.com/.default").token
    with httpx.Client(headers={"Authorization": f"Bearer {token}"}, timeout=60) as client:
        site = _ok(client.get(f"{GRAPH}/sites/root", params={"$select": "id,webUrl"}), "Root site lookup")
        site_id = site["id"]
        lists = _ok(client.get(f"{GRAPH}/sites/{site_id}/lists", params={"$select": "id,displayName"}), "List lookup")
        match = [item for item in lists.get("value", []) if item.get("displayName") == LIST_NAME]
        if match:
            list_id = match[0]["id"]
        else:
            list_id = _ok(client.post(f"{GRAPH}/sites/{site_id}/lists", json={
                "displayName": LIST_NAME, "columns": COLUMNS, "list": {"template": "genericList"},
                "description": "Fictional, approved demonstration evidence for the Compliance Partner.",
            }), "List creation")["id"]
        columns = {column["name"] for column in _ok(
            client.get(f"{GRAPH}/sites/{site_id}/lists/{list_id}/columns", params={"$select": "name"}),
            "Column lookup").get("value", [])}
        for column in COLUMNS:
            if column["name"] not in columns:
                _ok(client.post(f"{GRAPH}/sites/{site_id}/lists/{list_id}/columns", json=column), "Column creation")
        items = _ok(client.get(f"{GRAPH}/sites/{site_id}/lists/{list_id}/items",
                               params={"$expand": "fields($select=Title)", "$top": "100"}), "Item lookup")
        by_title = {item["fields"].get("Title"): item["id"] for item in items.get("value", [])}
        ids = []
        for record in RECORDS:
            fields = {"Approved": True, **record}
            if record["Title"] in by_title:
                item_id = by_title[record["Title"]]
                _ok(client.patch(f"{GRAPH}/sites/{site_id}/lists/{list_id}/items/{item_id}/fields", json=fields),
                    "Item update")
            else:
                item_id = _ok(client.post(f"{GRAPH}/sites/{site_id}/lists/{list_id}/items", json={"fields": fields}),
                              "Item creation")["id"]
            ids.append(item_id)
        check = _ok(client.get(f"{GRAPH}/sites/{site_id}/lists/{list_id}/items/{ids[5]}", params={"$expand": "fields"}),
                    "Readback")["fields"]
        missing = [name for name in ("Category", "Approved", "Version", "Content", "AdviceClosureAllowed",
                                     "RequiresSpecialist", "ApprovedRoute") if name not in check]
        if missing:
            raise SystemExit("Readback is missing exact field names: " + ", ".join(missing))
    paths = [f"/sites/{site_id}/lists/{list_id}/items/{item}?$expand=fields" for item in ids]
    print("EVIDENCE_RESULT " + json.dumps({"site": site.get("webUrl"), "listId": list_id, "evidencePaths": paths}))


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        print(f"EVIDENCE_ERROR {exc}", file=sys.stderr)
        raise
