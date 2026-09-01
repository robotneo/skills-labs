from __future__ import absolute_import

import io
import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.cli import BridgeCommands
from notification_bridge.config import BridgeConfig, ChannelConfig
from notification_bridge.contract import build_envelope
from notification_bridge.mcp_server import EXPECTED_TOOLS, handle_request, serve
from notification_bridge.providers.base import ProviderResult
from notification_bridge.service import DeliveryBatchResult


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
with open(os.path.join(FIXTURES, "standard-report.md"), "r") as handle:
    STANDARD_MARKDOWN = handle.read()
with open(os.path.join(FIXTURES, "standard-report.json"), "r") as handle:
    STANDARD_REPORT = json.load(handle)


def envelope_payload():
    return build_envelope(
        STANDARD_MARKDOWN, STANDARD_REPORT, "AI summary", "host_agent", "2.4.0"
    ).to_dict()


class FakeService(object):
    def __init__(self):
        self.deliver_calls = []
        self.bind_calls = []

    def deliver(self, envelope):
        self.deliver_calls.append(envelope)
        return DeliveryBatchResult([ProviderResult("sent")])

    def bind(self, platform):
        self.bind_calls.append(platform)
        return ProviderResult("ok", data={"profile": "corp:user"})


class McpServerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.directory.name, "config.json")
        self.config = BridgeConfig(
            enabled=True,
            channels=[ChannelConfig(
                "dingtalk", provider="native", profile="corp:user",
                recipients=["ops"],
            )],
        )
        self.service = FakeService()
        self.commands = BridgeCommands(
            self.service, self.config, self.config_path
        )

    def tearDown(self):
        self.directory.cleanup()

    def request(self, method, params=None, request_id=1):
        request = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            request["params"] = params
        return handle_request(request, self.commands)

    def test_initialize_advertises_tools_capability(self):
        response = self.request("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        })

        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["protocolVersion"], "2024-11-05")
        self.assertEqual(response["result"]["capabilities"], {"tools": {}})

    def test_initialized_notification_has_no_response(self):
        response = handle_request({
            "jsonrpc": "2.0", "method": "notifications/initialized",
        }, self.commands)

        self.assertIsNone(response)

    def test_request_without_id_never_receives_a_response(self):
        response = handle_request({
            "jsonrpc": "2.0", "method": "initialize", "params": {},
        }, self.commands)

        self.assertIsNone(response)

    def test_tools_list_exposes_exactly_five_bridge_tools(self):
        response = self.request("tools/list", {})

        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertEqual(names, list(EXPECTED_TOOLS))
        self.assertEqual(names, [
            "notification_status",
            "bind_notification_profile",
            "configure_notification_recipient",
            "deliver_enterprise_report",
            "retry_enterprise_report",
        ])

    def test_deliver_tool_returns_structured_content_from_shared_core(self):
        response = self.request("tools/call", {
            "name": "deliver_enterprise_report",
            "arguments": {"envelope": envelope_payload()},
        })

        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["status"], "delivered")
        self.assertEqual(json.loads(result["content"][0]["text"])["status"],
                         "delivered")
        self.assertEqual(len(self.service.deliver_calls), 1)

    def test_retry_tool_uses_same_delivery_service_method(self):
        response = self.request("tools/call", {
            "name": "retry_enterprise_report",
            "arguments": {"envelope": envelope_payload()},
        })

        self.assertEqual(response["result"]["structuredContent"]["status"],
                         "delivered")
        self.assertEqual(len(self.service.deliver_calls), 1)

    def test_bind_tool_uses_same_service_bind_method(self):
        response = self.request("tools/call", {
            "name": "bind_notification_profile",
            "arguments": {"platform": "dingtalk"},
        })

        self.assertEqual(response["result"]["structuredContent"]["status"], "ok")
        self.assertEqual(self.service.bind_calls, ["dingtalk"])

    def test_unknown_tool_is_a_structured_tool_error(self):
        response = self.request("tools/call", {
            "name": "unknown", "arguments": {},
        })

        self.assertTrue(response["result"]["isError"])
        self.assertEqual(response["result"]["structuredContent"]["reason"],
                         "tool_not_found")

    def test_internal_tool_failure_is_structured_content(self):
        class RaisingService(FakeService):
            def deliver(self, envelope):
                raise RuntimeError("database unavailable")

        commands = BridgeCommands(
            RaisingService(), self.config, self.config_path
        )

        response = handle_request({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {
                "name": "deliver_enterprise_report",
                "arguments": {"envelope": envelope_payload()},
            },
        }, commands)

        self.assertTrue(response["result"]["isError"])
        self.assertEqual(response["result"]["structuredContent"]["reason"],
                         "internal_error")

    def test_serve_uses_one_json_response_per_line_and_skips_notifications(self):
        input_stream = io.StringIO("\n".join([
            json.dumps({
                "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
            }),
            json.dumps({
                "jsonrpc": "2.0", "method": "notifications/initialized",
            }),
            "{broken",
            "",
        ]))
        output_stream = io.StringIO()
        error_stream = io.StringIO()

        code = serve(
            self.commands, input_stream=input_stream, output_stream=output_stream,
            error_stream=error_stream,
        )

        responses = [json.loads(line) for line in output_stream.getvalue().splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual(len(responses), 2)
        self.assertIn("result", responses[0])
        self.assertEqual(responses[1]["error"]["code"], -32700)
        self.assertIn("invalid JSON-RPC", error_stream.getvalue())


if __name__ == "__main__":
    unittest.main()
