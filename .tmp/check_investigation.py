"""Local live-model check of LiveComplianceBackend.investigate with the demo evidence records.

Work IQ is replaced by a fake that returns Graph-shaped list items built from the
exact records provisioned by infra/autopilot-caldova/evidence-setup. The model call
is REAL (Azure OpenAI, Entra auth via the signed-in Azure CLI user; no keys).
"""

import asyncio
import copy
import importlib.util
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from azure.identity import AzureCliCredential, get_bearer_token_provider
from openai import AsyncAzureOpenAI

from demo_agent import compliance_backend as cb
from demo_agent.compliance_service import ComplianceBinding

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("prov", ROOT / "infra/autopilot-caldova/evidence-setup/provision_evidence.py")
prov = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prov)

SITE = "caldova74201480.sharepoint.com,11111111-1111-4111-8111-111111111111,22222222-2222-4222-8222-222222222222"
LIST = "33333333-3333-4333-8333-333333333333"
PATHS = tuple(f"/sites/{SITE}/lists/{LIST}/items/{i + 1}?$expand=fields" for i in range(len(prov.RECORDS)))
ITEMS = {}
for index, record in enumerate(prov.RECORDS):
    etag = f'"aaaaaaaa-0000-4000-8000-00000000000{index},1"'
    ITEMS[PATHS[index]] = {"id": str(index + 1), "eTag": etag, "lastModifiedDateTime": "2026-09-23T05:00:00Z",
                           "fields": {"@odata.etag": etag, "Approved": True, **record}}

T, B, I, A, M, R = ("17371818-07cb-47f2-9ca3-18f96f0125d7", "7b3bf810-61f1-46f3-8e9c-89a61a761037",
                    "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222",
                    "3ef6fe2c-3605-4f77-aeff-fb9e084e3a0d", "44444444-4444-4444-8444-444444444444")
BINDING = ComplianceBinding(T, B, I, A, M, (R,), PATHS)
EMAIL = {"subject": "Project Seabrook - can we share the diligence pack with the Singapore advisory team today?",
         "body": ("We are finalising Northbridge Renewables' refinancing. Our external adviser wants the diligence pack for its "
                  "Singapore team before tomorrow's lender call. The supplier dashboard is green and we have an NDA, but I am "
                  "not sure whether those cover this team. The pack includes revised forecasts and some KYC documents. Can you "
                  "establish what we can share, with whom, and what needs changing?")}
REPLY = ("The Singapore analysts would download the full pack; the UK partner is only coordinating. If needed we can use "
         "Harbourline's UK-only wall-crossed team instead, and they only need the aggregate forecast summary and the draft "
         "lender presentation - no identity documents.")


class FakeWorkIQ:
    async def call(self, name, path, body=None):
        assert name == "fetch" and body is None
        return copy.deepcopy(ITEMS[path])


def llm():
    token = get_bearer_token_provider(AzureCliCredential(), "https://cognitiveservices.azure.com/.default")
    return AsyncAzureOpenAI(azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"], azure_ad_token_provider=token,
                            api_version="2025-03-01-preview")


async def main() -> None:
    backend = cb.LiveComplianceBackend(type("C", (), {"get_default_connection": lambda self: None})(),
                                       lambda *a: None, llm, lambda binding: True)

    @asynccontextmanager
    async def workiq(_binding):
        yield FakeWorkIQ()

    async def verified(_binding):
        return None

    backend._workiq = workiq
    backend.verify_binding = verified
    record = {"authority": {"tenantId": T, "blueprintId": B, "instanceAppId": I, "agenticUserId": A,
                            "managerId": M, "requesterId": R},
              "inputComplete": True, "email": EMAIL, "replyHistory": []}
    first = await backend.investigate(BINDING, copy.deepcopy(record), "")
    print("TURN 1 ready:", first.resolution_ready)
    print(" questions:", first.questions)
    print(" blockers:", first.blockers)
    print(" answer:", first.answer[:900])
    record["replyHistory"] = [{"text": REPLY, "generation": 1}]
    second = await backend.investigate(BINDING, copy.deepcopy(record), REPLY)
    print("\nTURN 2 ready:", second.resolution_ready)
    print(" questions:", second.questions)
    print(" blockers:", second.blockers)
    print(" answer:", second.answer[:1500])
    confirm = ("Yes - the UK-only wall-crossed Harbourline team working through the Seabrook data room with just the "
               "aggregate forecast summary and the draft lender presentation meets our need. No identity documents.")
    record["replyHistory"].append({"text": confirm, "generation": 2})
    third = await backend.investigate(BINDING, copy.deepcopy(record), confirm)
    print("\nTURN 3 ready:", third.resolution_ready)
    print(" questions:", third.questions)
    print(" blockers:", third.blockers)
    print(" answer:", third.answer[:1800])


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

