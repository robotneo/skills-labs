"""Direct unit tests for notification_bridge.standard_report.

Previously the re-renderer was exercised only through contract validation;
these tests pin its language detection, normalization, fixed table shape, and
canonical output directly.
"""
from __future__ import absolute_import

import json
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge import standard_report as sr


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
with open(os.path.join(FIXTURES, "standard-report.json"), "r", encoding="utf-8") as handle:
    REPORT_JSON = json.load(handle)
with open(os.path.join(FIXTURES, "standard-report.md"), "r", encoding="utf-8") as handle:
    ZH_MARKDOWN = handle.read()


class LanguageTests(unittest.TestCase):
    def test_detect_language_for_zh_and_en(self):
        self.assertEqual(sr.detect_language("# 📶 Wi-Fi 健康报告\n..."), "zh")
        self.assertEqual(sr.detect_language("# 📶 Wi-Fi Health Report\n..."), "en")

    def test_detect_language_rejects_unknown_title(self):
        self.assertIsNone(sr.detect_language("# other report\n"))

    def test_normalize_markdown_unifies_crlf(self):
        self.assertEqual(
            sr.normalize_markdown("a\r\nb\rc\n"), "a\nb\rc\n"
        )


class RenderTests(unittest.TestCase):
    def test_chinese_render_matches_canonical_fixture_byte_for_byte(self):
        self.assertEqual(
            sr.render_standard_markdown(REPORT_JSON, "zh"), ZH_MARKDOWN
        )

    def test_render_is_deterministic(self):
        first = sr.render_standard_markdown(REPORT_JSON, "zh")
        second = sr.render_standard_markdown(REPORT_JSON, "zh")
        self.assertEqual(first, second)
        self.assertTrue(second.endswith("\n"))

    def test_english_render_uses_english_fixed_sections_and_headers(self):
        text = sr.render_standard_markdown(REPORT_JSON, "en")
        self.assertTrue(text.startswith("# 📶 Wi-Fi Health Report\n"))
        for section in (
            "## ⭐ Core Metrics", "## 🏠 Local Network Quality",
            "## 🌐 Public Network Quality",
            "## 🧭 Diagnostics & Recommendations",
        ):
            self.assertIn(section, text)
        self.assertIn("| Health | Score | Data Confidence |", text)
        self.assertIn("| Metric | Current Value |", text)
        self.assertIn("### Main Issues", text)
        self.assertIn("### Recommendations", text)

    def test_core_table_has_eighteen_fixed_rows_in_order(self):
        for language, labels in (
            ("zh", sr.ZH_CORE_ROW_LABELS),
            ("en", sr.EN_CORE_ROW_LABELS),
        ):
            with self.subTest(language=language):
                self.assertEqual(len(labels), 18)
                text = sr.render_standard_markdown(REPORT_JSON, language)
                positions = [text.index("| " + label + " |") for label in labels]
                self.assertEqual(positions, sorted(positions))

    def test_quality_row_labels_derive_from_field_label_order(self):
        self.assertEqual(
            list(sr.ZH_LOCAL_ROW_LABELS),
            [sr.FIELD_LABELS_ZH[name] for name in sr.LOCAL_QUALITY_FIELDS],
        )
        self.assertEqual(len(sr.ZH_LOCAL_ROW_LABELS), 5)
        self.assertEqual(len(sr.ZH_PUBLIC_ROW_LABELS), 7)
        self.assertEqual(
            list(sr.EN_PUBLIC_ROW_LABELS),
            [sr.FIELD_LABELS_EN[name] for name in sr.PUBLIC_QUALITY_FIELDS],
        )

    def test_rendered_field_appends_unit_and_escapes_pipe(self):
        import copy
        payload = copy.deepcopy(REPORT_JSON)
        payload["sections"]["connection"]["ssid"].update(
            value="A | B", availability="available", reason=""
        )
        payload["sections"]["link"]["tx_rate"].update(
            value=300.0, unit="Mbps", availability="available", reason=""
        )
        text = sr.render_standard_markdown(payload, "en")
        self.assertIn("A \\| B", text)
        self.assertIn("300 Mbps", text)

    def test_unavailable_field_renders_localized_reason(self):
        import copy
        payload = copy.deepcopy(REPORT_JSON)
        payload["sections"]["public_quality"]["download_speed"].update(
            value=None, availability="unavailable",
            reason="enable with --speedtest",
        )
        zh = sr.render_standard_markdown(payload, "zh")
        en = sr.render_standard_markdown(payload, "en")
        self.assertIn("使用 --speedtest 开启", zh)
        self.assertIn("Unavailable: enable with --speedtest", en)


if __name__ == "__main__":
    unittest.main()
