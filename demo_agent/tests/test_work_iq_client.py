"""Offline Work IQ production-contract regressions; no tenant calls or writes."""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from demo_agent.work_iq_client import (
    DEFAULT_AUTH_HANDLER,
    DEFAULT_TEAMS_MCP_SCOPE,
    DEFAULT_TEAMS_MCP_URL,
    WORK_IQ_RESOURCE_APP_ID,
    WorkIqTeamsClient,
    WorkIqTeamsConfig,
    _created_entity_id,
)

SENDER = "11111111-1111-4111-8111-111111111111"
RECIPIENT = "22222222-2222-4222-8222-222222222222"


def created(identifier: str, status: int = 201) -> SimpleNamespace:
    return SimpleNamespace(
        is_error=False, content=[], structured_content={"statusCode": status, "data": {"id": identifier}},
    )


class WorkIqConfigTests(unittest.TestCase):
    def test_manifest_matches_verified_production_identity(self) -> None:
        manifest = json.loads((Path(__file__).parents[1] / "ToolingManifest.json").read_text(encoding="utf-8"))
        self.assertEqual(len(manifest["mcpServers"]), 1)
        server = manifest["mcpServers"][0]
        self.assertEqual(server["url"], DEFAULT_TEAMS_MCP_URL)
        self.assertEqual(server["audience"], WORK_IQ_RESOURCE_APP_ID)
        self.assertEqual(server["scope"], "WorkIQAgent.Ask")
        self.assertEqual(server["mcpServerUniqueName"], "workiq")
        self.assertNotIn("McpServers.Teams.All", json.dumps(manifest))
        self.assertNotIn("mcp_TeamsServer", json.dumps(manifest))

    def test_defaults_require_fully_qualified_delegated_scope(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = WorkIqTeamsConfig.from_env()
        self.assertEqual(config.scope, "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask")
        self.assertEqual(config.auth_handler, "OBO")
        self.assertEqual(config.url, "https://workiq.svc.cloud.microsoft/mcp")

    def test_retired_or_redirectable_endpoint_is_rejected(self) -> None:
        for url in ("https://agent365.svc.cloud.microsoft/agents/servers/mcp_TeamsServerV1",
                    "https://workiq.svc.cloud.microsoft.attacker.invalid/mcp", "http://workiq.svc.cloud.microsoft/mcp"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                WorkIqTeamsConfig(url, DEFAULT_TEAMS_MCP_SCOPE, DEFAULT_AUTH_HANDLER, 60)

    def test_bare_legacy_and_app_only_scopes_are_rejected(self) -> None:
        for scope in ("McpServers.Teams.All", "WorkIQAgent.Ask", "https://graph.microsoft.com/.default",
                      "api://workiq.svc.cloud.microsoft/.default"):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                WorkIqTeamsConfig(DEFAULT_TEAMS_MCP_URL, scope, DEFAULT_AUTH_HANDLER, 60)

    def test_public_metadata_scope_form_is_accepted(self) -> None:
        config = WorkIqTeamsConfig(DEFAULT_TEAMS_MCP_URL, WORK_IQ_RESOURCE_APP_ID + "/WorkIQAgent.Ask", "OBO", 60)
        self.assertTrue(config.scope.endswith("/WorkIQAgent.Ask"))

    def test_only_confirmed_entity_results_count_as_success(self) -> None:
        self.assertEqual(_created_entity_id(created("known")), "known")
        for result in (None, created("", 201), created("private", 403), created("private", 500),
                       SimpleNamespace(is_error=True, structured_content=created("x").structured_content),
                       SimpleNamespace(content=[SimpleNamespace(text='{"id":"unconfirmed"}')] ),
                       SimpleNamespace(structured_content={"statusCode": True, "data": {"id": "x"}})):
            with self.subTest(result=result):
                self.assertEqual(_created_entity_id(result), "")

    def test_conflicting_results_do_not_report_success(self) -> None:
        result = created("one")
        result.content = [SimpleNamespace(text=json.dumps({"statusCode": 201, "data": {"id": "two"}}))]
        self.assertEqual(_created_entity_id(result), "")
        result.structured_content["statusCode"] = 403
        self.assertEqual(_created_entity_id(result), "")


class WorkIqClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.adapter = WorkIqTeamsClient(WorkIqTeamsConfig(DEFAULT_TEAMS_MCP_URL, DEFAULT_TEAMS_MCP_SCOPE, "OBO", 60))
        self.context = object()
        self.agent = SimpleNamespace(auth=SimpleNamespace(exchange_token=AsyncMock(return_value=SimpleNamespace(token="runtime-only-token"))))
        self.client = SimpleNamespace(
            list_tools=AsyncMock(return_value=[SimpleNamespace(name="create_entity")]),
            call_tool=AsyncMock(side_effect=[created("19:chat/a@thread.v2"), created("message-1")]),
            __aexit__=AsyncMock(),
        )

    async def send(self) -> dict:
        return await self.adapter.send_oneonone(
            agent_app=self.agent, context=self.context, sender_aad_id=SENDER,
            recipient_aad_id=RECIPIENT, body_text="Confirmed operator message.",
        )

    async def test_sdk_exchange_uses_current_scope_not_application_credentials(self) -> None:
        self.assertEqual(await self.adapter._exchange_token(self.agent, self.context), "runtime-only-token")
        self.agent.auth.exchange_token.assert_awaited_once_with(
            self.context, scopes=[DEFAULT_TEAMS_MCP_SCOPE], auth_handler_id="OBO",
        )
        with self.assertRaises(RuntimeError):
            await self.adapter._exchange_token(self.agent, None)
        self.agent.auth.exchange_token.return_value = SimpleNamespace(secret="DO-NOT-PRINT")
        with self.assertRaises(RuntimeError) as error:
            await self.adapter._exchange_token(self.agent, self.context)
        self.assertNotIn("DO-NOT-PRINT", str(error.exception))

    async def test_modern_entity_contract_and_encoded_chat_id(self) -> None:
        with patch.object(self.adapter, "_connect", AsyncMock(return_value=self.client)):
            result = await self.send()
        self.assertEqual(result["status"], "sent")
        calls = self.client.call_tool.await_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual([call.args[0] for call in calls], ["create_entity", "create_entity"])
        self.assertEqual(calls[0].args[1]["parentUrl"], "/chats")
        self.assertIsInstance(calls[0].args[1]["jsonBody"], str)
        self.assertEqual(json.loads(calls[0].args[1]["jsonBody"])["chatType"], "oneOnOne")
        self.assertEqual(calls[1].args[1]["parentUrl"], "/chats/19%3Achat%2Fa%40thread.v2/messages")
        self.assertEqual(json.loads(calls[1].args[1]["jsonBody"])["body"]["contentType"], "text")
        self.client.__aexit__.assert_awaited_once()

    async def test_policy_denial_never_posts_message_or_retries(self) -> None:
        self.client.call_tool.side_effect = [created("not-authorized", 403)]
        with patch.object(self.adapter, "_connect", AsyncMock(return_value=self.client)):
            result = await self.send()
        self.assertNotEqual(result["status"], "sent")
        self.assertEqual(self.client.call_tool.await_count, 1)
        self.assertNotIn("not-authorized", json.dumps(result))

    async def test_upstream_error_omits_sensitive_details_and_does_not_retry(self) -> None:
        self.client.call_tool.side_effect = RuntimeError("Bearer DO-NOT-LOG private message")
        with patch.object(self.adapter, "_connect", AsyncMock(return_value=self.client)), \
                self.assertLogs("demo_agent.work_iq_client", level="WARNING") as logs:
            result = await self.send()
        self.assertEqual(result["status"], "unknown")
        self.assertNotIn("DO-NOT-LOG", json.dumps(result) + str(logs.output))
        self.assertEqual(self.client.call_tool.await_count, 1)
        self.client.__aexit__.assert_awaited_once()

    async def test_missing_tool_never_executes(self) -> None:
        self.client.list_tools.return_value = [SimpleNamespace(name="fetch")]
        with patch.object(self.adapter, "_connect", AsyncMock(return_value=self.client)):
            result = await self.send()
        self.assertEqual(result["status"], "error")
        self.client.call_tool.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()