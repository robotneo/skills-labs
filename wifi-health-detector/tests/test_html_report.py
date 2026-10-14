from __future__ import absolute_import

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from wifi_health.diagnose import diagnose
from wifi_health.html_report import HtmlReportError, render_html, write_html_file
from wifi_health.models import Field, Report
from wifi_health.output import render_json


class HtmlReportTests(unittest.TestCase):
    def _report(self):
        report = Report.empty()
        report.sections["system"]["checked_at"] = Field(
            "2026-08-21T14:00:00+08:00", source="fixture")
        report.sections["system"]["os"] = Field("Darwin", source="fixture")
        report.sections["system"]["os_version"] = Field("24.1.0", source="fixture")
        report.sections["adapter"]["interface"] = Field("en0", source="fixture")
        report.sections["adapter"]["mac"] = Field("aa:bb:cc:dd:ee:ff", source="fixture")
        report.sections["connection"]["ssid"] = Field("Office", source="fixture")
        report.sections["connection"]["band"] = Field("5 GHz", source="fixture")
        report.sections["connection"]["channel"] = Field(149, source="fixture")
        report.sections["connection"]["security"] = Field("WPA3", source="fixture")
        report.sections["radio"]["rssi"] = Field(-55, "dBm", source="fixture")
        report.sections["radio"]["snr"] = Field(40, "dB", source="fixture")
        report.sections["link"]["tx_rate"] = Field(866.7, "Mbit/s", source="fixture")
        report.sections["local_quality"]["latency"] = Field(3.2, "ms", source="fixture")
        report.sections["local_quality"]["packet_loss"] = Field(0.0, "%", source="fixture")
        report.diagnosis = diagnose(report)
        return report

    def _json(self, report=None):
        return json.loads(render_json(report or self._report()))

    def test_renders_standalone_self_contained_document(self):
        document = render_html(self._json(), "zh")
        self.assertTrue(document.lstrip().lower().startswith("<!doctype html>"))
        self.assertIn("<html", document)
        self.assertIn('charset="utf-8"', document)
        self.assertIn("<style>", document)
        # Fixed, inline-only styling: no external assets, links or scripts that
        # could render differently offline or exfiltrate report data.
        lowered = document.lower()
        for forbidden in ("http://", "https://", "<script", "src=", "<link",
                          "<iframe", "@import", "url("):
            self.assertNotIn(forbidden, lowered, forbidden)
        self.assertIn("Wi-Fi 健康报告", document)

    def test_rendering_is_deterministic(self):
        payload = self._json()
        self.assertEqual(render_html(payload, "zh"), render_html(payload, "zh"))

    def test_includes_score_verdict_and_section_labels(self):
        document = render_html(self._json(), "zh")
        self.assertIn("健康评分", document)
        self.assertIn("数据置信度", document)
        self.assertIn("核心参数", document)
        self.assertIn("本地网络质量", document)
        self.assertIn("公网质量", document)
        self.assertIn("诊断与建议", document)
        # The score ring reflects the diagnosed score.
        self.assertIn(">%d<" % self._json()["diagnosis"]["score"], document)

    def test_english_language_uses_english_labels(self):
        document = render_html(self._json(), "en")
        self.assertIn('lang="en"', document)
        self.assertIn("Wi-Fi Health Report", document)
        self.assertIn("Core Metrics", document)
        self.assertIn("Recommendations", document)

    def test_unknown_language_falls_back_to_chinese(self):
        document = render_html(self._json(), "fr")
        self.assertIn("Wi-Fi 健康报告", document)

    def test_escapes_untrusted_identifiers(self):
        report = self._report()
        report.sections["connection"]["ssid"] = Field(
            '<script>alert(1)</script> & "x"', source="fixture")
        document = render_html(json.loads(render_json(report)), "zh")
        self.assertNotIn("<script>alert(1)", document)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", document)
        self.assertIn("&amp;", document)

    def test_unavailable_fields_render_em_dash_without_failing(self):
        report = self._report()
        report.sections["public_quality"]["download_speed"] = report.sections[
            "public_quality"]["download_speed"]
        payload = json.loads(render_json(report))
        payload["sections"]["link"]["rx_rate"] = {
            "value": None, "unit": "", "availability": "unavailable",
            "source": "", "reason": "macOS does not expose the current receive PHY rate",
        }
        document = render_html(payload, "zh")
        self.assertIn("—", document)
        self.assertIn("未提供", document)

    def test_warning_verdict_renders_issues_and_recommendations(self):
        report = self._report()
        report.sections["radio"]["rssi"] = Field(-72, "dBm", source="fixture")
        report.diagnosis = diagnose(report)
        document = render_html(json.loads(render_json(report)), "zh")
        self.assertIn("主要问题", document)
        self.assertIn("优化建议", document)
        self.assertIn("#1", document)

    def test_collection_warnings_are_shown(self):
        payload = self._json()
        payload["warnings"] = ["周边网络扫描被跳过"]
        document = render_html(payload, "zh")
        self.assertIn("周边网络扫描被跳过", document)
        self.assertIn("采集告警", document)

    def test_write_html_file_persists_document(self):
        payload = self._json()
        handle, path = tempfile.mkstemp(suffix=".html")
        os.close(handle)
        try:
            write_html_file(payload, path, "zh")
            with open(path, "r", encoding="utf-8") as saved:
                content = saved.read()
            self.assertEqual(content, render_html(payload, "zh"))
            self.assertTrue(content.startswith("<!doctype html>"))
        finally:
            os.unlink(path)

    def test_rejects_non_object_input(self):
        with self.assertRaises(HtmlReportError):
            render_html("not-an-object", "zh")
        with self.assertRaises(HtmlReportError):
            render_html(None, "zh")

    def test_attachment_passes_bridge_self_contained_policy(self):
        # The bridge rejects HTML containing scripts or external URLs. Assert
        # the producer output always satisfies that contract.
        sys.path.insert(
            0,
            os.path.join(
                ROOT, "integrations", "enterprise-notification-bridge"),
        )
        try:
            from notification_bridge.contract import _validate_html_attachment
        except ImportError:
            self.skipTest("bridge contract helper unavailable")
        for language in ("zh", "en"):
            _validate_html_attachment(render_html(self._json(), language))


if __name__ == "__main__":
    unittest.main()
