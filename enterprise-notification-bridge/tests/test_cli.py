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
        self.deliver_result = DeliveryBatchResult([
            ProviderResult("sent", data={"external_id": "message-1"})
        ])
        self.deliver_calls = []
        self.bind_calls = []

    def deliver(self, envelope):
        self.deliver_calls.append(envelope)
        return self.deliver_result

    def bind(self, platform):
        self.bind_calls.append(platform)
        return ProviderResult("ok", data={"profile": "corp:user"})


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
        with open(self.envelope_path, "w") as handle:
            json.dump(envelope_payload(), handle)
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
        self.assertEqual(self.service.deliver_calls[0].report_id,
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
        self.assertIn("database unavailable", stderr.getvalue())

    def test_retry_uses_the_same_delivery_core(self):
        code, stdout, _ = self.run_cli([
            "retry", "--envelope", self.envelope_path,
        ])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["status"], "delivered")
        self.assertEqual(len(self.service.deliver_calls), 1)

    def test_bind_uses_service_bind(self):
        code, stdout, stderr = self.run_cli([
            "bind", "--platform", "dingtalk",
        ])

        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["data"]["profile"], "corp:user")
        self.assertEqual(stderr, "")
        self.assertEqual(self.service.bind_calls, ["dingtalk"])

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
                ("dws", "profile", "list", "--help"): "--format json",
                ("dws", "profile", "list", "--format", "json"):
                    '{"profiles":[{"profile":"corp:user"}]}',
            }
            return ProcessResult(outputs[tuple(command)])

        commands = build_commands(
            self.config_path, ledger_path, run_process=run_process
        )
        result = commands.bind("dingtalk")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["profile"], "corp:user")
        self.assertFalse(any("login" in command for command in calls))


if __name__ == "__main__":
    unittest.main()
