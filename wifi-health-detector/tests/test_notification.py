from __future__ import absolute_import

import contextlib
import io
import json
import os
import shlex
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
REPOSITORY_ROOT = os.path.dirname(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from wifi_health.cli import main
from wifi_health.diagnose import diagnose
from wifi_health.models import Field, Report
from wifi_health.notification import ReportContractError, trigger_notification
from wifi_health.output import render_json, render_text


class NotificationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        fixture_directory = os.path.join(
            REPOSITORY_ROOT, "enterprise-notification-bridge", "tests", "fixtures"
        )
        with open(os.path.join(fixture_directory, "standard-report.md"), encoding="utf-8") as handle:
            self.markdown = handle.read()
        with open(os.path.join(fixture_directory, "standard-report.json"), encoding="utf-8") as handle:
            self.report_json = json.load(handle)

    def tearDown(self):
        self.directory.cleanup()

    def test_bridge_receives_strict_envelope_after_report_validation(self):
        record_path = os.path.join(self.directory.name, "envelope.json")
        bridge_command = self._bridge_command(
            {"status": "delivered", "reason": "sent"}, record_path=record_path
        )

        result = trigger_notification(
            self.markdown,
            self.report_json,
            summary="Wi-Fi is healthy.",
            bridge_command=bridge_command,
        )

        self.assertEqual(result.status, "delivered")
        with open(record_path, encoding="utf-8") as handle:
            envelope = json.load(handle)
        self.assertEqual(envelope["schema_version"], "1")
        self.assertEqual(envelope["report"]["markdown"], self.markdown)
        self.assertEqual(envelope["report"]["json"], self.report_json)
        self.assertEqual(
            envelope["ai_summary"],
            {"mode": "host_agent", "text": "Wi-Fi is healthy."},
        )

    def test_missing_bridge_is_non_blocking(self):
        result = trigger_notification(
            self.markdown,
            self.report_json,
            bridge_command=[os.path.join(self.directory.name, "missing-bridge")],
        )

        self.assertEqual(result.reason, "bridge_unavailable")
        self.assertFalse(result.requires_attention)

    def test_absent_successful_and_failed_bridge_never_change_standard_output(self):
        report = self._sample_report()
        expected = render_text(report, language="en")
        cases = (
            ("absent", [os.path.join(self.directory.name, "missing-bridge")], None),
            ("successful", self._bridge_command({"status": "delivered"}), None),
            (
                "failed",
                self._bridge_command(
                    {"status": "notification_failed", "reason": "send_failed"}
                ),
                "send_failed",
            ),
            (
                "action required",
                self._bridge_command({"status": "profile_selection_required"}),
                "profile_selection_required",
            ),
        )

        for name, bridge_command, diagnostic in cases:
            with self.subTest(name=name):
                code, stdout, stderr = self._run_detector(
                    report, bridge_command=bridge_command
                )
                self.assertEqual(code, 0)
                self.assertEqual(stdout, expected)
                if diagnostic is None:
                    self.assertEqual(stderr, "")
                else:
                    self.assertIn(diagnostic, stderr)

    def test_no_notify_skips_an_explicit_bridge(self):
        record_path = os.path.join(self.directory.name, "called.json")
        report = self._sample_report()

        code, stdout, stderr = self._run_detector(
            report,
            bridge_command=self._bridge_command(
                {"status": "delivered"}, record_path=record_path
            ),
            extra_args=["--no-notify"],
        )

        self.assertEqual(code, 0)
        self.assertEqual(stdout, render_text(report, language="en"))
        self.assertEqual(stderr, "")
        self.assertFalse(os.path.exists(record_path))

    def test_invalid_markdown_never_invokes_bridge(self):
        record_path = os.path.join(self.directory.name, "called.json")
        invalid_markdown = self.markdown.replace("## ⭐ 核心参数", "## 核心参数")

        with self.assertRaises(ReportContractError):
            trigger_notification(
                invalid_markdown,
                self.report_json,
                bridge_command=self._bridge_command(
                    {"status": "delivered"}, record_path=record_path
                ),
            )

        self.assertFalse(os.path.exists(record_path))

    def test_renamed_core_metric_never_invokes_bridge(self):
        record_path = os.path.join(self.directory.name, "called.json")
        invalid_markdown = self.markdown.replace(
            "| 操作系统版本 |", "| 操作系统 |", 1
        )

        with self.assertRaises(ReportContractError):
            trigger_notification(
                invalid_markdown,
                self.report_json,
                bridge_command=self._bridge_command(
                    {"status": "delivered"}, record_path=record_path
                ),
            )

        self.assertFalse(os.path.exists(record_path))

    def test_invalid_json_never_invokes_bridge(self):
        record_path = os.path.join(self.directory.name, "called.json")
        invalid_json = dict(self.report_json)
        invalid_json.pop("warnings")

        with self.assertRaises(ReportContractError):
            trigger_notification(
                self.markdown,
                invalid_json,
                bridge_command=self._bridge_command(
                    {"status": "delivered"}, record_path=record_path
                ),
            )

        self.assertFalse(os.path.exists(record_path))

    def test_malformed_nonzero_bridge_response_is_non_blocking(self):
        result = trigger_notification(
            self.markdown,
            self.report_json,
            bridge_command=self._bridge_command([], return_code=2),
        )

        self.assertEqual(result.status, "bridge_failed")
        self.assertEqual(result.reason, "bridge_failed")
        self.assertTrue(result.requires_attention)

    def test_unexpected_bridge_runner_failure_is_non_blocking(self):
        with patch(
            "wifi_health.notification.subprocess.run",
            side_effect=RuntimeError("runner failed"),
        ):
            result = trigger_notification(
                self.markdown,
                self.report_json,
                bridge_command=[sys.executable],
            )

        self.assertEqual(result.status, "bridge_failed")
        self.assertEqual(result.reason, "bridge_failed")

    def _bridge_command(self, response, record_path=None, return_code=0):
        script = [
            "import json,sys",
            "path=sys.argv[sys.argv.index('--envelope')+1]",
        ]
        if record_path is not None:
            script.append(
                "open({0!r},'w',encoding='utf-8').write(open(path,encoding='utf-8').read())".format(
                    record_path
                )
            )
        script.append("print({0!r})".format(json.dumps(response)))
        script.append("raise SystemExit({0})".format(return_code))
        return [sys.executable, "-c", ";".join(script)]

    def _run_detector(self, report, bridge_command, extra_args=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        environment = {
            "ENTERPRISE_NOTIFICATION_BRIDGE": " ".join(
                shlex.quote(part) for part in bridge_command
            )
        }
        arguments = ["--language", "en", "--no-public-test"]
        arguments.extend(extra_args or [])
        with patch("wifi_health.cli.collect_report", return_value=report), patch(
            "wifi_health.cli.apply_quality"
        ), patch.dict(os.environ, environment, clear=False), contextlib.redirect_stdout(
            stdout
        ), contextlib.redirect_stderr(stderr):
            code = main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    @staticmethod
    def _sample_report():
        report = Report.empty()
        report.sections["system"]["checked_at"] = Field(
            "2026-08-21T14:00:00+08:00", source="fixture"
        )
        report.sections["system"]["os"] = Field("Darwin", source="fixture")
        report.sections["adapter"]["interface"] = Field("en0", source="fixture")
        report.sections["connection"]["ssid"] = Field("Office", source="fixture")
        report.sections["connection"]["band"] = Field("5 GHz", source="fixture")
        report.sections["connection"]["channel"] = Field(149, source="fixture")
        report.sections["radio"]["rssi"] = Field(-55, "dBm", source="fixture")
        report.sections["local_quality"]["latency"] = Field(
            3.2, "ms", source="fixture"
        )
        report.sections["local_quality"]["packet_loss"] = Field(
            0.0, "%", source="fixture"
        )
        report.diagnosis = diagnose(report)
        return report


if __name__ == "__main__":
    unittest.main()
