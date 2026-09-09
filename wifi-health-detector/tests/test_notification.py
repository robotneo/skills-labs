from __future__ import absolute_import

import contextlib
import io
import json
import os
import shutil
import subprocess
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
from wifi_health import notification as notification_module
from wifi_health.notification import ReportContractError, trigger_notification
from wifi_health.output import render_json, render_text


class NotificationIntegrationTests(unittest.TestCase):
    def test_discovery_prefers_bundle_and_preserves_legacy_fallback(self):
        bundled = os.path.join(ROOT, "integrations", "enterprise-notification-bridge",
                               "run.bat" if os.name == "nt" else "run.sh")
        legacy = os.path.join(REPOSITORY_ROOT, "enterprise-notification-bridge",
                              "run.bat" if os.name == "nt" else "run.sh")
        for available, expected in (([bundled, legacy], bundled), ([legacy], legacy)):
            with patch.dict(os.environ, {}, clear=True), patch(
                "wifi_health.notification.os.path.isfile", side_effect=lambda path: path in available
            ):
                self.assertEqual(notification_module._discover_bridge_command(), ([expected], False))

    def test_standalone_copy_delivers_disabled_without_dws(self):
        installed = os.path.join(self.directory.name, "installed-skill")
        shutil.copytree(ROOT, installed, ignore=shutil.ignore_patterns("__pycache__"))
        environment = dict(os.environ)
        environment.pop("ENTERPRISE_NOTIFICATION_BRIDGE", None)
        environment.update({
            "ENTERPRISE_NOTIFICATION_BRIDGE_CONFIG": os.path.join(self.directory.name, "config.json"),
            "ENTERPRISE_NOTIFICATION_BRIDGE_LEDGER": os.path.join(self.directory.name, "ledger.sqlite3"),
            "ENTERPRISE_NOTIFICATION_BRIDGE_STATE": os.path.join(self.directory.name, "state"),
            "ENTERPRISE_NOTIFICATION_BRIDGE_PYTHON": sys.executable,
            "DWS_EXE": os.path.join(self.directory.name, "missing-dws"),
        })
        script = (
            "import json; from wifi_health.notification import trigger_notification; "
            "p='integrations/enterprise-notification-bridge/tests/fixtures/'; "
            "m=open(p+'standard-report.md',encoding='utf-8').read(); "
            "j=json.load(open(p+'standard-report.json',encoding='utf-8')); "
            "r=trigger_notification(m,j); print(r.status)"
        )
        result = subprocess.run([sys.executable, "-c", script], cwd=installed,
                                env=environment, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "notification_disabled")
        entries = []
        for directory, _, files in os.walk(installed):
            if "SKILL.md" in files:
                entries.append(os.path.join(directory, "SKILL.md"))
        self.assertEqual(entries, [os.path.join(installed, "SKILL.md")])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        fixture_directory = os.path.join(
            ROOT, "integrations", "enterprise-notification-bridge", "tests", "fixtures"
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
                "notification_failed",
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

    def test_dependency_attention_statuses_preserve_report_and_hide_bridge_details(self):
        report = self._sample_report()
        expected = render_text(report, language="en")
        statuses = (
            "dependency_install_required",
            "dependency_install_declined",
            "dependency_download_failed",
            "dependency_integrity_failed",
            "dependency_install_failed",
            "dependency_version_unsupported",
            "dependency_verification_failed",
            "dws_upgrade_required",
            "dws_authorization_required",
            "dws_admin_authorization_required",
        )
        secret = "corp:secret-profile token=private org=ding-secret"

        for status in statuses:
            with self.subTest(status=status):
                code, stdout, stderr = self._run_detector(
                    report,
                    bridge_command=self._bridge_command(
                        {"status": status, "reason": secret}
                    ),
                )

                self.assertEqual(code, 0)
                self.assertEqual(stdout, expected)
                self.assertEqual(
                    stderr, "Enterprise notification: {0}\n".format(status)
                )
                self.assertNotIn(secret, stderr)

    def test_untrusted_bridge_statuses_map_to_stable_failure_without_leaking(self):
        report = self._sample_report()
        expected = render_text(report, language="en")
        statuses = (
            "unknown_status",
            " token=secret-profile ",
            "dependency_install_required\norg=secret",
            "delivered\t",
            "delivered\x1b[31m",
            "dependency install required",
            "UPPER_CASE_STATUS",
            "status;token=secret",
            7,
            None,
        )

        for status in statuses:
            with self.subTest(status=status):
                code, stdout, stderr = self._run_detector(
                    report,
                    bridge_command=self._bridge_command(
                        {"status": status, "reason": "org=secret token=private"}
                    ),
                )

                self.assertEqual(code, 0)
                self.assertEqual(stdout, expected)
                self.assertEqual(stderr, "Enterprise notification: bridge_failed\n")
                self.assertNotIn(str(status), stderr)
                self.assertNotIn("secret", stderr)

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

    def test_changed_fixed_table_headers_and_rows_never_invoke_bridge(self):
        english_markdown = render_text(self._sample_report(), language="en")
        mutations = (
            (
                "zh summary header", self.markdown,
                "| 健康状态 | 健康评分 | 数据置信度 |",
                "| 状态 | 健康评分 | 数据置信度 |",
            ),
            ("zh core header", self.markdown, "| 核心参数 | 当前值 |", "| 参数 | 当前值 |"),
            (
                "zh local header", self.markdown,
                "| 参数 | 当前值 | 状态 |", "| 指标 | 当前值 | 状态 |",
            ),
            (
                "zh public header", self.markdown,
                "## 🌐 公网质量\n\n| 参数 | 当前值 | 状态 |",
                "## 🌐 公网质量\n\n| 指标 | 当前值 | 状态 |",
            ),
            ("zh local row", self.markdown, "| 测试目标 |", "| 目标 |"),
            ("zh public row", self.markdown, "| DNS 解析延迟 |", "| DNS 延迟 |"),
            (
                "en summary header", english_markdown,
                "| Health | Score | Data Confidence |",
                "| Status | Score | Data Confidence |",
            ),
            (
                "en core header", english_markdown,
                "| Metric | Current Value |", "| Parameter | Current Value |",
            ),
            (
                "en local header", english_markdown,
                "| Parameter | Current Value | Status |",
                "| Metric | Current Value | Status |",
            ),
            (
                "en public header", english_markdown,
                "## 🌐 Public Network Quality\n\n| Parameter | Current Value | Status |",
                "## 🌐 Public Network Quality\n\n| Metric | Current Value | Status |",
            ),
            ("en local row", english_markdown, "| Target |", "| Test Target |"),
            ("en public row", english_markdown, "| DNS Latency |", "| DNS Resolution |"),
        )

        for name, markdown, old, new in mutations:
            with self.subTest(name=name):
                record_path = os.path.join(self.directory.name, name + ".json")
                invalid_markdown = markdown.replace(old, new, 1)
                self.assertNotEqual(invalid_markdown, markdown)

                with self.assertRaises(ReportContractError):
                    trigger_notification(
                        invalid_markdown,
                        self.report_json,
                        bridge_command=self._bridge_command(
                            {"status": "delivered"}, record_path=record_path
                        ),
                    )

                self.assertFalse(os.path.exists(record_path))

    def test_local_and_public_tables_reject_shape_and_whitespace_mutations(self):
        english_markdown = render_text(self._sample_report(), language="en")
        languages = (
            (
                "zh", self.markdown,
                (("## 🏠 本地网络质量", "## 🌐 公网质量"),
                 ("## 🌐 公网质量", "## 🧭 诊断与建议")),
                "参数", "测试目标", "额外",
            ),
            (
                "en", english_markdown,
                (("## 🏠 Local Network Quality", "## 🌐 Public Network Quality"),
                 ("## 🌐 Public Network Quality", "## 🧭 Diagnostics & Recommendations")),
                "Parameter", "Target", "Extra",
            ),
        )
        mutations = ("extra column", "fixed label whitespace", "header whitespace")

        for language, markdown, sections, header, label, extra in languages:
            for table_name, (start, end) in zip(("local", "public"), sections):
                for mutation in mutations:
                    name = "{0} {1} {2}".format(language, table_name, mutation)
                    with self.subTest(name=name):
                        invalid_markdown = self._mutate_table(
                            markdown, start, end, header, label, extra, mutation
                        )
                        record_path = os.path.join(self.directory.name, name + ".json")

                        with self.assertRaises(ReportContractError):
                            trigger_notification(
                                invalid_markdown,
                                self.report_json,
                                bridge_command=self._bridge_command(
                                    {"status": "delivered"}, record_path=record_path
                                ),
                            )

                        self.assertFalse(os.path.exists(record_path))

    def test_renderer_escaped_dynamic_pipe_remains_a_single_table_cell(self):
        report = self._sample_report()
        report.sections["connection"]["ssid"] = Field(
            "Office | Lab", source="fixture"
        )
        markdown = render_text(report, language="en")
        self.assertIn(r"Office \| Lab", markdown)

        result = trigger_notification(
            markdown,
            json.loads(render_json(report)),
            bridge_command=self._bridge_command({"status": "delivered"}),
        )

        self.assertEqual(result.status, "delivered")

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

    def test_malformed_bridge_override_returns_structured_failure(self):
        with patch.dict(
            os.environ, {"ENTERPRISE_NOTIFICATION_BRIDGE": "'"}, clear=False
        ):
            result = trigger_notification(self.markdown, self.report_json)

        self.assertEqual(result.status, "bridge_failed")
        self.assertEqual(result.reason, "invalid_bridge_command")
        self.assertTrue(result.requires_attention)

    def test_explicit_bridge_override_is_a_cross_platform_json_vector(self):
        command = [
            r"C:\Program Files\Enterprise Bridge\run.bat",
            "--config", r"C:\配置\bridge.json",
        ]

        normalized = notification_module._normalize_bridge_command(
            json.dumps(command, ensure_ascii=False)
        )

        self.assertEqual(normalized, command)

    def test_malformed_bridge_override_preserves_cli_success_and_stdout(self):
        report = self._sample_report()
        expected = render_text(report, language="en")

        code, stdout, stderr = self._run_detector(report, bridge_override="'")

        self.assertEqual(code, 0)
        self.assertEqual(stdout, expected)
        self.assertEqual(stderr, "Enterprise notification: bridge_failed\n")

    def test_blank_explicit_bridge_overrides_return_structured_failure(self):
        for override in ("   ", "''"):
            with self.subTest(override=override), patch.dict(
                os.environ, {"ENTERPRISE_NOTIFICATION_BRIDGE": override}, clear=False
            ):
                result = trigger_notification(self.markdown, self.report_json)

            self.assertEqual(result.status, "bridge_failed")
            self.assertEqual(result.reason, "invalid_bridge_command")
            self.assertTrue(result.requires_attention)

    def test_blank_explicit_bridge_overrides_preserve_cli_output_and_success(self):
        report = self._sample_report()
        expected = render_text(report, language="en")

        for override in ("   ", "''"):
            with self.subTest(override=override):
                code, stdout, stderr = self._run_detector(
                    report, bridge_override=override
                )

                self.assertEqual(code, 0)
                self.assertEqual(stdout, expected)
                self.assertEqual(stderr, "Enterprise notification: bridge_failed\n")

    def test_absent_override_and_adjacent_bridge_remains_unavailable_skip(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "wifi_health.notification.os.path.isfile", return_value=False
        ):
            result = trigger_notification(self.markdown, self.report_json)

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "bridge_unavailable")
        self.assertFalse(result.requires_attention)

    def test_adjacent_bridge_discovery_passes_validated_envelope_and_is_non_blocking(self):
        config_path = os.path.join(self.directory.name, "adjacent-config.json")
        ledger_path = os.path.join(self.directory.name, "adjacent-ledger.sqlite3")
        state_path = os.path.join(self.directory.name, "adjacent-state")
        with open(config_path, "w") as handle:
            json.dump({
                "version": 1,
                "notification": {
                    "enabled": True,
                    "failure_policy": "non_blocking",
                    "channels": [{
                        "platform": "dingtalk",
                        "provider": "auto",
                        "profile": "corp:user",
                        "recipients": [],
                    }],
                },
            }, handle)
        dws_path = os.path.join(self.directory.name, "dws")
        dws_log = os.path.join(self.directory.name, "dws.log")
        with open(dws_path, "w") as handle:
            handle.write("#!/bin/sh\n")
            handle.write("echo \"$*\" >> \"$DWS_LOG\"\n")
            handle.write("case \"$*\" in\n")
            handle.write("  '--help') echo 'DWS help' ;;\n")
            handle.write("  *'auth status --help'*) echo '--format json' ;;\n")
            handle.write("  *'profile list --help'*) echo '--format json' ;;\n")
            handle.write("  *'auth status --format json'*)\n")
            handle.write("    if [ \"${DWS_MODE:-ok}\" = failure ]; then exit 9; fi\n")
            handle.write("    echo '{\"authenticated\":true}' ;;\n")
            handle.write("  *'profile list --format json'*)\n")
            handle.write("    echo '{\"profiles\":[{\"profile\":\"corp:user\"}]}' ;;\n")
            handle.write("  *) exit 1 ;;\n")
            handle.write("esac\n")
        os.chmod(dws_path, 0o755)

        report = self._sample_report()
        expected = render_text(report, language="en")
        adjacent_launcher = os.path.join(
            ROOT, "integrations", "enterprise-notification-bridge", "run.sh"
        )
        observed = []
        real_run = notification_module.subprocess.run
        bridge_statuses = []

        def observe_and_run(command, *args, **kwargs):
            if command and os.path.abspath(command[0]) == os.path.abspath(adjacent_launcher):
                envelope_path = command[command.index("--envelope") + 1]
                with open(envelope_path, encoding="utf-8") as handle:
                    observed.append(json.load(handle))
            result = real_run(command, *args, **kwargs)
            if command and os.path.abspath(command[0]) == os.path.abspath(adjacent_launcher):
                bridge_statuses.append(json.loads(result.stdout)["status"])
            return result

        environment = {
            "ENTERPRISE_NOTIFICATION_BRIDGE_CONFIG": config_path,
            "ENTERPRISE_NOTIFICATION_BRIDGE_LEDGER": ledger_path,
            "ENTERPRISE_NOTIFICATION_BRIDGE_STATE": state_path,
            "WIFI_HEALTH_PYTHON": sys.executable,
            "DWS_LOG": dws_log,
            "PATH": self.directory.name + os.pathsep + os.environ.get("PATH", ""),
        }
        with patch.dict(os.environ, environment, clear=True), patch(
            "wifi_health.cli.collect_report", return_value=report
        ), patch("wifi_health.cli.apply_quality"), patch(
            "wifi_health.notification.subprocess.run", side_effect=observe_and_run
        ):
            code, stdout, stderr = self._run_detector_without_override()

        self.assertEqual(code, 0)
        self.assertEqual(stdout, expected)
        self.assertEqual(stderr, "")
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["report"]["markdown"], expected)
        self.assertEqual(observed[0]["report"]["json"], json.loads(render_json(report)))
        self.assertEqual(observed[0]["ai_summary"]["mode"], "deterministic")
        self.assertEqual(bridge_statuses, ["recipient_not_configured"])

        with patch.dict(os.environ, dict(environment, DWS_MODE="failure"), clear=True), patch(
            "wifi_health.cli.collect_report", return_value=report
        ), patch("wifi_health.cli.apply_quality"), patch(
            "wifi_health.notification.subprocess.run", side_effect=observe_and_run
        ):
            code, failed_stdout, failed_stderr = self._run_detector_without_override()

        self.assertEqual(code, 0)
        self.assertEqual(failed_stdout, expected)
        self.assertIn("dws_command_failed", failed_stderr)
        self.assertEqual(len(observed), 2)
        self.assertEqual(bridge_statuses, ["recipient_not_configured", "dws_command_failed"])
        with open(dws_log, encoding="utf-8") as handle:
            dws_calls = handle.read().splitlines()
        self.assertTrue(dws_calls)
        self.assertFalse(any("send" in call or "recipient" in call for call in dws_calls))

    def _run_detector_without_override(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["--language", "en", "--no-public-test"])
        return code, stdout.getvalue(), stderr.getvalue()

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

    @staticmethod
    def _mutate_table(markdown, start, end, header, label, extra, mutation):
        prefix, remainder = markdown.split(start, 1)
        table, suffix = remainder.split(end, 1)
        lines = table.splitlines()
        if mutation == "header whitespace":
            index = next(
                i for i, line in enumerate(lines) if line.startswith("| " + header + " |")
            )
            lines[index] = lines[index].replace("| " + header + " |", "|  " + header + " |", 1)
        else:
            index = next(
                i for i, line in enumerate(lines) if line.startswith("| " + label + " |")
            )
            if mutation == "fixed label whitespace":
                lines[index] = lines[index].replace("| " + label + " |", "|  " + label + " |", 1)
            else:
                lines[index] = lines[index][:-1] + "| " + extra + " |"
        return prefix + start + "\n".join(lines) + end + suffix

    def _run_detector(
            self, report, bridge_command=None, extra_args=None, bridge_override=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        if bridge_override is None:
            bridge_override = json.dumps(bridge_command, ensure_ascii=False)
        environment = {"ENTERPRISE_NOTIFICATION_BRIDGE": bridge_override}
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
