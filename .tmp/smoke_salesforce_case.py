"""Live smoke test: Salesforce MCP case create/read/update through the compliance host adapter.

Creates one clearly labelled smoke-test case in the demo Salesforce org and closes it.
"""

import asyncio
import json

from demo_agent.compliance_backend import LiveComplianceBackend, _read_result
from demo_agent.compliance_host import ComplianceHost, load_bindings
from demo_agent.conversation_memory import SQLiteStore

URL = "https://essmcp-caldova-salesforce.livelysky-91807d17.eastus2.azurecontainerapps.io/salesforce/mcp"
T, B, I, A, M, R = ("17371818-07cb-47f2-9ca3-18f96f0125d7", "7b3bf810-61f1-46f3-8e9c-89a61a761037",
                    "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222",
                    "3ef6fe2c-3605-4f77-aeff-fb9e084e3a0d", "3ef6fe2c-3605-4f77-aeff-fb9e084e3a0d")


class _Conn:
    def get_default_connection(self):
        raise AssertionError


async def main() -> None:
    config = json.dumps([{"instanceAppId": I, "agenticUserId": A, "managerId": M, "requesterIds": [R]}])
    host = ComplianceHost(bindings=load_bindings(config, T, B), store=SQLiteStore(__import__("os").path.abspath(".tmp/smoke.db")),
                          connection_manager=_Conn(), salesforce_url=URL, llm_factory=lambda: None,
                          instance_enabled=lambda _b: None, ensure_run=lambda *a: None,
                          publish=lambda *a: None, set_state=lambda *a: None, spawn=lambda c: c.close())
    binding = host.bindings()[0][0]
    live = host.live
    created = _read_result(await host._salesforce_call(binding, "create_case", {
        "subject": "[Autopilot smoke test] adapter verification", "compliance_type": "Data Privacy (GDPR / CCPA)",
        "origin": "Email", "description": "Automated adapter smoke test; safe to ignore.",
    }))
    case = LiveComplianceBackend._case(created)
    number = LiveComplianceBackend._case_number(case)
    print("created", created.get("created"), case["id"], number, case.get("status"))
    comment = _read_result(await host._salesforce_call(binding, "update_case", {"case_id": case["id"], "comment": "smoke comment"}))
    print("comment ack", comment.get("success"))
    closed = _read_result(await host._salesforce_call(binding, "update_case", {"case_id": case["id"], "status": "Closed"}))
    print("closed", closed.get("success"), LiveComplianceBackend._case(closed, case["id"]).get("status"))
    read = _read_result(await host._salesforce_call(binding, "get_case", {"case_id": case["id"]}))
    print("readback", LiveComplianceBackend._case(read, case["id"]).get("status"), "comments", read.get("comment_count"))
    await host.close()


asyncio.run(main())

