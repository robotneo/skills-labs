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

from notification_bridge.cli import BridgeCommands, build_commands, main
from notification_bridge.config import BridgeConfig, ChannelConfig, load_config, save_config
from notification_bridge.contract import build_envelope
from notification_bridge.ledger import DeliveryLedger
from notification_bridge.providers.base import Provider
from notification_bridge.providers.base import ProviderResult
from notification_bridge.service import BridgeService
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


class FakeService(object):
    def __init__(self):
        self.deliver_result = DeliveryBatchResult([
            ProviderResult("sent", data={"external_id": "message-1"})
        ])
        self.deliver_calls = []
        self.bind_calls = []
        self.retry_calls = []
        self.continue_calls = []

    def deliver(self, envelope, capabilities=None, request_host_summary=False):
        self.deliver_calls.append(
            (envelope, capabilities, request_host_summary)
        )
        return self.deliver_result

    def bind(self, platform, capabilities=None):
        self.bind_calls.append((platform, capabilities))
        return ProviderResult("ok", data={"profile": "corp:user"})

    def retry(self, report_id, capabilities=None):
        self.retry_calls.append((report_id, capabilities))
        return self.deliver_result

    def continue_operation(self, result):
        self.continue_calls.append(result)
        return self.deliver_result


class ActivationProvider(Provider):
    platform = "dingtalk"
    name = "native"
    priority = 100

    def capabilities(self):
        return {"available": True}

    def auth_status(self, profile=None):
        return ProviderResult("authorized")

    def login(self):
        return ProviderResult("authorized")

    def list_profiles(self):
        return ProviderResult("ok", data={"profile": "corp:user"})

    def resolve_recipient(self, profile, selector):
        return ProviderResult("resolved", data={"recipient": selector})

    def send_report(self, profile, recipient, envelope):
        return ProviderResult("sent", data={"external_id": "fake-message"})


class CliTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.directory.name, "config.json")
        save_config(BridgeConfig(
            enabled=True,
            channels=[ChannelConfig(
                "dingtalk", provider="native", profile="corp:user",
                recipients=["ops"],
            )],
        ), self.config_path)
        self.envelope_path = os.path.join(self.directory.name, "envelope.json")
        with open(self.envelope_path, "w", encoding="utf-8") as handle:
            json.dump(envelope_payload(), handle)
        self.capabilities_path = os.path.join(
            self.directory.name, "capabilities.json"
        )
        with open(self.capabilities_path, "w", encoding="utf-8") as handle:
            json.dump(capability_bundle(), handle)
        self.service = FakeService()

    def tearDown(self):
        self.directory.cleanup()

    def run_cli(self, arguments):
        stdout = io.StringIO()
        stderr = io.StringIO()
        commands = BridgeCommands(
            self.service, load_config(self.config_path), self.config_path
        )
        code = main(arguments, commands=commands, stdout=stdout, stderr=stderr)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_deliver_prints_exactly_one_json_document(self):
        code, stdout, stderr = self.run_cli([
            "deliver", "--envelope", self.envelope_path,
        ])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "delivered")
        self.assertEqual(len(stdout.strip().splitlines()), 1)
        self.assertEqual(stderr, "")
        self.assertEqual(self.service.deliver_calls[0][0].report_id,
                         envelope_payload()["report_id"])

    def test_notification_failure_keeps_cli_success(self):
        self.service.deliver_result = DeliveryBatchResult([
            ProviderResult("failed", "timeout", retryable=True)
        ])

        code, stdout, stderr = self.run_cli([
            "deliver", "--envelope", self.envelope_path,
        ])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "notification_failed")
        self.assertEqual(stderr, "")

    def test_malformed_envelope_is_json_error_with_nonzero_exit(self):
        with open(self.envelope_path, "w") as handle:
            json.dump({"schema_version": "1", "report_id": "broken"}, handle)

        code, stdout, stderr = self.run_cli([
            "deliver", "--envelope", self.envelope_path,
        ])

        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "error")
        self.assertEqual(len(stdout.strip().splitlines()), 1)
        self.assertIn("malformed_envelope", stderr)
        self.assertEqual(self.service.deliver_calls, [])

    def test_invalid_envelope_metadata_is_rejected_before_delivery(self):
        invalid_values = (
            ("generated_at", "not-a-timestamp"),
            ("detector", {"name": "wifi-health-detector", "version": ""}),
            ("ai_summary", {"mode": "external", "text": "summary"}),
        )
        for field, value in invalid_values:
            with self.subTest(field=field):
                payload = envelope_payload()
                payload[field] = value
                with open(self.envelope_path, "w") as handle:
                    json.dump(payload, handle)
                self.service.deliver_calls = []

                code, stdout, stderr = self.run_cli([
                    "deliver", "--envelope", self.envelope_path,
                ])

                self.assertNotEqual(code, 0)
                self.assertEqual(json.loads(stdout)["reason"], "malformed_envelope")
                self.assertIn("malformed_envelope", stderr)
                self.assertEqual(self.service.deliver_calls, [])

    def test_internal_service_failure_is_json_error_with_nonzero_exit(self):
        class RaisingService(FakeService):
            def deliver(self, envelope):
                raise RuntimeError("database unavailable")

        commands = BridgeCommands(
            RaisingService(), load_config(self.config_path), self.config_path
        )
        stdout = io.StringIO()
        stderr = io.StringIO()

        code = main(
            ["deliver", "--envelope", self.envelope_path], commands=commands,
            stdout=stdout, stderr=stderr,
        )

        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["reason"], "internal_error")
        self.assertEqual(stderr.getvalue(), "internal_error\n")

    def test_utf8_envelope_path_preserves_non_ascii_report(self):
        unicode_path = os.path.join(self.directory.name, "企业报告.json")
        with open(unicode_path, "w", encoding="utf-8") as handle:
            json.dump(envelope_payload(), handle, ensure_ascii=False)

        code, stdout, stderr = self.run_cli([
            "deliver", "--envelope", unicode_path,
        ])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "delivered")
        self.assertEqual(stderr, "")

    def test_retry_uses_durable_report_id_without_an_envelope(self):
        report_id = envelope_payload()["report_id"]
        code, stdout, _ = self.run_cli([
            "retry", "--report-id", report_id,
            "--capabilities", self.capabilities_path,
        ])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "delivered")
        self.assertEqual(
            self.service.retry_calls, [(report_id, capability_bundle())]
        )
        self.assertEqual(self.service.deliver_calls, [])

    def test_deliver_passes_versioned_capabilities_and_summary_request(self):
        code, stdout, stderr = self.run_cli([
            "deliver", "--envelope", self.envelope_path,
            "--capabilities", self.capabilities_path,
            "--request-host-summary",
        ])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "delivered")
        self.assertEqual(stderr, "")
        self.assertEqual(self.service.deliver_calls[0][1], capability_bundle())
        self.assertTrue(self.service.deliver_calls[0][2])

    def test_continue_accepts_a_correlated_operation_result_file(self):
        operation_result = {
            "schema_version": "1", "action_id": "a" * 32,
            "report_id": envelope_payload()["report_id"],
            "platform": "dingtalk", "provider": "native",
            "operation": "auth_status", "status": "succeeded",
            "reason": "", "retryable": False,
            "data": {"authorization": "authorized"},
        }
        path = os.path.join(self.directory.name, "operation-result.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(operation_result, handle)

        code, stdout, stderr = self.run_cli([
            "continue", "--operation-result", path,
        ])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "delivered")
        self.assertEqual(stderr, "")
        self.assertEqual(self.service.continue_calls, [operation_result])

    def test_bind_uses_service_bind(self):
        code, stdout, stderr = self.run_cli([
            "bind", "--platform", "dingtalk",
        ])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["data"]["profile"], "corp:user")
        self.assertEqual(stderr, "")
        self.assertEqual(self.service.bind_calls, [("dingtalk", None)])

    def test_bind_passes_versioned_native_capabilities(self):
        code, stdout, stderr = self.run_cli([
            "bind", "--platform", "dingtalk",
            "--capabilities", self.capabilities_path,
        ])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "ok")
        self.assertEqual(stderr, "")
        self.assertEqual(
            self.service.bind_calls, [("dingtalk", capability_bundle())]
        )

    def test_recipients_persists_non_secret_configuration(self):
        code, stdout, stderr = self.run_cli([
            "recipients", "--platform", "dingtalk", "--profile", "corp:user",
            "--recipient", "network", "--recipient", "security",
        ])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "configured")
        self.assertEqual(stderr, "")
        saved = load_config(self.config_path)
        self.assertEqual(saved.channels[0].recipients, ["network", "security"])

    def test_status_reports_configuration_without_delivery(self):
        code, stdout, stderr = self.run_cli(["status"])

        self.assertEqual(code, 0)
        result = json.loads(stdout)
        self.assertEqual(result["status"], "enabled")
        self.assertEqual(result["channels"][0]["platform"], "dingtalk")
        self.assertEqual(stderr, "")
        self.assertEqual(self.service.deliver_calls, [])

    def test_fresh_config_can_be_enabled_bound_configured_and_delivered(self):
        config = BridgeConfig()
        config_path = os.path.join(self.directory.name, "fresh-config.json")
        ledger_path = os.path.join(self.directory.name, "fresh-ledger.sqlite3")
        save_config(config, config_path)
        service = BridgeService(
            config, [ActivationProvider()], DeliveryLedger(ledger_path)
        )

        def invoke(arguments):
            stdout = io.StringIO()
            stderr = io.StringIO()
            code = main(
                ["--config", config_path] + arguments,
                commands=BridgeCommands(service, config, config_path),
                stdout=stdout,
                stderr=stderr,
            )
            return code, json.loads(stdout.getvalue()), stderr.getvalue()

        code, status, _ = invoke(["status"])
        self.assertEqual(code, 0)
        self.assertEqual(status["status"], "disabled")

        code, enabled, _ = invoke(["enable", "--platform", "dingtalk"])
        self.assertEqual(code, 0)
        self.assertEqual(enabled["status"], "enabled")
        self.assertEqual(enabled["channel"]["provider"], "auto")
        self.assertTrue(load_config(config_path).enabled)

        code, bound, _ = invoke(["bind", "--platform", "dingtalk"])
        self.assertEqual(code, 0)
        self.assertEqual(bound["status"], "ok")
        self.assertEqual(load_config(config_path).channels[0].profile, "corp:user")

        code, configured, _ = invoke([
            "recipients", "--platform", "dingtalk", "--profile", "corp:user",
            "--recipient", "ops",
        ])
        self.assertEqual(code, 0)
        self.assertEqual(configured["status"], "configured")
        self.assertEqual(load_config(config_path).channels[0].recipients, ["ops"])

        service.state_store.confirm({
            "platform": "dingtalk", "provider": "native",
            "profile": "corp:user", "recipients": ["ops"],
        })

        code, delivered, _ = invoke([
            "deliver", "--envelope", self.envelope_path,
        ])
        self.assertEqual(code, 0)
        self.assertEqual(delivered["status"], "delivered")

    def test_help_still_emits_one_json_document(self):
        code, stdout, stderr = self.run_cli(["--help"])

        self.assertEqual(code, 0)
        result = json.loads(stdout)
        self.assertEqual(result["status"], "ok")
        self.assertIn("deliver", result["commands"])
        self.assertEqual(len(stdout.strip().splitlines()), 1)
        self.assertEqual(stderr, "")

    def test_production_factory_selects_available_dws_without_login(self):
        save_config(BridgeConfig(
            enabled=True,
            channels=[ChannelConfig("dingtalk", provider="auto")],
        ), self.config_path)
        ledger_path = os.path.join(self.directory.name, "production-ledger.sqlite3")
        calls = []

        class ProcessResult(object):
            def __init__(self, stdout):
                self.returncode = 0
                self.stdout = stdout
                self.stderr = ""

        def run_process(command, **kwargs):
            calls.append(list(command))
            outputs = {
                ("dws", "--help"): "DWS command line",
                ("dws", "auth", "status", "--help"): "--format json",
                ("dws", "auth", "status", "--format", "json"):
                    '{"authenticated":true}',
                ("dws", "profile", "list", "--help"): "--format json",
                ("dws", "profile", "list", "--format", "json"):
                    '{"profiles":[{"profile":"corp:user"}]}',
            }
            return ProcessResult(outputs[tuple(command)])

        commands = build_commands(
            self.config_path, ledger_path,
            os.path.join(self.directory.name, "production-state"),
            run_process=run_process,
        )
        result = commands.bind("dingtalk")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["profile"], "corp:user")
        self.assertFalse(any("login" in command for command in calls))

    def test_recipients_reject_an_unbound_or_mismatched_profile(self):
        config = BridgeConfig(
            enabled=True,
            channels=[ChannelConfig("feishu", provider="auto")],
        )
        path = os.path.join(self.directory.name, "unbound.json")
        save_config(config, path)
        commands = BridgeCommands(self.service, config, path)

        for arguments in (
                ["recipients", "--platform", "feishu", "--recipient", "ops"],
                ["recipients", "--platform", "feishu",
                 "--profile", "tenant:other", "--recipient", "ops"]):
            with self.subTest(arguments=arguments):
                stdout = io.StringIO()
                stderr = io.StringIO()
                code = main(
                    arguments, commands=commands, stdout=stdout, stderr=stderr
                )
                self.assertEqual(code, 2)
                self.assertEqual(
                    json.loads(stdout.getvalue())["reason"],
                    "profile_not_validated",
                )

    def test_malformed_capabilities_are_a_fixed_input_error(self):
        with open(self.capabilities_path, "w", encoding="utf-8") as handle:
            json.dump({"schema_version": "1", "capabilities": "bad"}, handle)

        code, stdout, stderr = self.run_cli([
            "deliver", "--envelope", self.envelope_path,
            "--capabilities", self.capabilities_path,
        ])

        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout)["reason"], "malformed_capabilities")
        self.assertEqual(stderr, "malformed_capabilities\n")
        self.assertEqual(self.service.deliver_calls, [])


if __name__ == "__main__":
    unittest.main()
