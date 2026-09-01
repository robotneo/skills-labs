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


def capability_bundle():
    return {
        "schema_version": "1",
        "capabilities": [{
            "schema_version": "1", "platform": "dingtalk",
            "provider": "native",
            "operations": [
                "auth_status", "login", "list_profiles",
                "resolve_recipient", "send_report", "delivery_status",
            ],
        }],
    }


def operation_result():
    return {
        "schema_version": "1", "action_id": "a" * 32,
        "report_id": envelope_payload()["report_id"],
        "platform": "dingtalk", "provider": "native",
        "operation": "auth_status", "status": "succeeded", "reason": "",
        "retryable": False, "data": {"authorization": "authorized"},
    }


class FakeService(object):
    def __init__(self):
        self.deliver_calls = []
        self.bind_calls = []
        self.retry_calls = []
        self.continue_calls = []

    def deliver(self, envelope, capabilities=None, request_host_summary=False):
        self.deliver_calls.append(
            (envelope, capabilities, request_host_summary)
        )
        return DeliveryBatchResult([ProviderResult("sent")])

    def bind(self, platform, capabilities=None):
        self.bind_calls.append((platform, capabilities))
        return ProviderResult("ok", data={"profile": "corp:user"})

    def retry(self, report_id, capabilities=None):
        self.retry_calls.append((report_id, capabilities))
        return DeliveryBatchResult([ProviderResult("sent")])

    def continue_operation(self, result):
        self.continue_calls.append(result)
        return DeliveryBatchResult([ProviderResult("sent")])


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

    def test_initialize_rejects_unsupported_protocol_version(self):
        response = self.request("initialize", {
            "protocolVersion": "2099-01-01", "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        })

        self.assertNotIn("result", response)
        self.assertEqual(response["error"]["code"], -32602)

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

    def test_invalid_or_unknown_notifications_never_receive_a_response(self):
        requests = (
            {"jsonrpc": "2.0", "method": "tools/list", "params": []},
            {"jsonrpc": "2.0", "method": "unknown", "params": {}},
            {"jsonrpc": "2.0", "params": {}},
            {
                "jsonrpc": "2.0", "method": "tools/call",
                "params": {"name": "unknown", "arguments": {}},
            },
        )
        for request in requests:
            with self.subTest(request=request):
                self.assertIsNone(handle_request(request, self.commands))

    def test_tools_list_exposes_six_bridge_tools_including_continuation(self):
        response = self.request("tools/list", {})

        names = [tool["name"] for tool in response["result"]["tools"]]
        self.assertEqual(names, list(EXPECTED_TOOLS))
        self.assertEqual(names, [
            "notification_status",
            "bind_notification_profile",
            "configure_notification_recipient",
            "deliver_enterprise_report",
            "retry_enterprise_report",
            "continue_enterprise_notification",
        ])

    def test_deliver_tool_returns_structured_content_from_shared_core(self):
        response = self.request("tools/call", {
            "name": "deliver_enterprise_report",
            "arguments": {
                "envelope": envelope_payload(),
                "capabilities": capability_bundle(),
                "requestHostSummary": True,
            },
        })

        result = response["result"]
        self.assertFalse(result["isError"])
        self.assertEqual(result["structuredContent"]["status"], "delivered")
        self.assertEqual(json.loads(result["content"][0]["text"])["status"],
                         "delivered")
        self.assertEqual(len(self.service.deliver_calls), 1)
        self.assertEqual(self.service.deliver_calls[0][1], capability_bundle())
        self.assertTrue(self.service.deliver_calls[0][2])

    def test_retry_tool_uses_same_delivery_service_method(self):
        response = self.request("tools/call", {
            "name": "retry_enterprise_report",
            "arguments": {
                "reportId": envelope_payload()["report_id"],
                "capabilities": capability_bundle(),
            },
        })

        self.assertEqual(response["result"]["structuredContent"]["status"],
                         "delivered")
        self.assertEqual(self.service.deliver_calls, [])
        self.assertEqual(self.service.retry_calls, [(
            envelope_payload()["report_id"], capability_bundle(),
        )])

    def test_continue_tool_passes_correlated_result_to_shared_service(self):
        current = operation_result()

        response = self.request("tools/call", {
            "name": "continue_enterprise_notification",
            "arguments": {"operationResult": current},
        })

        self.assertFalse(response["result"]["isError"])
        self.assertEqual(
            response["result"]["structuredContent"]["status"], "delivered"
        )
        self.assertEqual(self.service.continue_calls, [current])

    def test_bind_tool_uses_same_service_bind_method(self):
        response = self.request("tools/call", {
            "name": "bind_notification_profile",
            "arguments": {"platform": "dingtalk"},
        })

        self.assertEqual(response["result"]["structuredContent"]["status"], "ok")
        self.assertEqual(self.service.bind_calls, [("dingtalk", None)])

    def test_bind_tool_accepts_a_strict_capability_bundle(self):
        response = self.request("tools/call", {
            "name": "bind_notification_profile",
            "arguments": {
                "platform": "dingtalk",
                "capabilities": capability_bundle(),
            },
        })

        self.assertFalse(response["result"]["isError"])
        self.assertEqual(
            self.service.bind_calls, [("dingtalk", capability_bundle())]
        )

    def test_configure_recipient_rejects_a_fresh_unbound_configuration(self):
        self.config.enabled = False
        self.config.channels = []

        response = self.request("tools/call", {
            "name": "configure_notification_recipient",
            "arguments": {"platform": "dingtalk", "recipient": "ops"},
        })

        self.assertTrue(response["result"]["isError"])
        self.assertEqual(
            response["result"]["structuredContent"]["reason"],
            "profile_not_validated",
        )
        self.assertFalse(self.config.enabled)
        self.assertEqual(self.config.channels, [])

    def test_unknown_tool_is_a_json_rpc_error(self):
        response = self.request("tools/call", {
            "name": "unknown", "arguments": {},
        })

        self.assertNotIn("result", response)
        self.assertEqual(response["error"]["code"], -32602)

    def test_tool_arguments_enforce_required_types_and_additional_properties(self):
        cases = (
            ("notification_status", {"unexpected": True}),
            ("bind_notification_profile", {}),
            ("bind_notification_profile", {"platform": 42}),
            ("bind_notification_profile", {
                "platform": "dingtalk", "unexpected": True,
            }),
            ("configure_notification_recipient", {"platform": "dingtalk"}),
            ("configure_notification_recipient", {
                "platform": "dingtalk", "recipient": 42,
            }),
            ("configure_notification_recipient", {
                "platform": "dingtalk", "recipient": "network",
                "profile": "corp:user", "unexpected": True,
            }),
            ("deliver_enterprise_report", {"envelope": []}),
            ("deliver_enterprise_report", {
                "envelope": envelope_payload(), "unexpected": True,
            }),
            ("deliver_enterprise_report", {
                "envelope": envelope_payload(),
                "requestHostSummary": "yes",
            }),
            ("deliver_enterprise_report", {
                "envelope": envelope_payload(),
                "capabilities": {
                    "schema_version": "1", "capabilities": [{
                        "schema_version": "1", "platform": "slack",
                        "provider": "native", "operations": ["send_report"],
                    }],
                },
            }),
            ("retry_enterprise_report", {}),
            ("retry_enterprise_report", {"reportId": "short"}),
            ("continue_enterprise_notification", {}),
            ("continue_enterprise_notification", {
                "operationResult": dict(operation_result(), unexpected=True),
            }),
        )
        for name, arguments in cases:
            with self.subTest(name=name, arguments=arguments):
                self.service.bind_calls = []
                self.service.deliver_calls = []
                self.service.retry_calls = []
                self.service.continue_calls = []
                self.config.channels[0].recipients = ["ops"]

                response = self.request("tools/call", {
                    "name": name, "arguments": arguments,
                })

                self.assertNotIn("result", response)
                self.assertEqual(response["error"]["code"], -32602)
                self.assertEqual(self.service.bind_calls, [])
                self.assertEqual(self.service.deliver_calls, [])
                self.assertEqual(self.service.retry_calls, [])
                self.assertEqual(self.service.continue_calls, [])
                self.assertEqual(self.config.channels[0].recipients, ["ops"])

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
        self.assertEqual(error_stream.getvalue(), "invalid_json\n")


if __name__ == "__main__":
    unittest.main()
