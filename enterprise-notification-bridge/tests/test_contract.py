from __future__ import absolute_import

import copy
import json
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
DETECTOR_ROOT = os.path.join(os.path.dirname(ROOT), "wifi-health-detector")
if DETECTOR_ROOT not in sys.path:
    sys.path.insert(0, DETECTOR_ROOT)

from notification_bridge.contract import ContractError, build_envelope, compute_report_id, validate_envelope
from wifi_health.diagnose import diagnose
from wifi_health.models import Field, Report
from wifi_health.output import render_text


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
with open(os.path.join(FIXTURES, "standard-report.md"), "r") as handle:
    MARKDOWN = handle.read()
with open(os.path.join(FIXTURES, "standard-report.json"), "r") as handle:
    REPORT = json.load(handle)


def valid_envelope(markdown=MARKDOWN, report_json=REPORT):
    return build_envelope(markdown, report_json, "摘要", "host_agent", "2.4.0")


class ContractTests(unittest.TestCase):
    def test_build_envelope_is_stable_for_the_same_report(self):
        first = build_envelope(MARKDOWN, REPORT, "摘要", "host_agent", "2.4.0")
        second = build_envelope(MARKDOWN, REPORT, "另一摘要", "host_agent", "2.4.0")
        self.assertEqual(first.report_id, second.report_id)

    def test_report_validator_rejects_added_core_row(self):
        envelope = valid_envelope()
        envelope.report["markdown"] = MARKDOWN.replace(
            "| 安全类型 | none |", "| 新增字段 | value |\n| 安全类型 | none |"
        )
        envelope.report_id = compute_report_id(envelope.report["markdown"], envelope.report["json"])
        with self.assertRaisesRegex(ContractError, "standard report"):
            validate_envelope(envelope)

    def test_summary_is_not_part_of_report_identity(self):
        envelope = build_envelope(MARKDOWN, REPORT, "摘要", "host_agent", "2.4.0")
        self.assertNotIn("摘要", envelope.report["markdown"])

    def test_validator_rejects_missing_or_reordered_sections(self):
        missing = MARKDOWN.replace("## 🌐 公网质量\n\n", "")
        with self.assertRaisesRegex(ContractError, "standard report"):
            validate_envelope(valid_envelope(markdown=missing))

        reordered = MARKDOWN.replace(
            "## 🏠 本地网络质量", "## TEMPORARY"
        ).replace(
            "## 🌐 公网质量", "## 🏠 本地网络质量"
        ).replace("## TEMPORARY", "## 🌐 公网质量")
        with self.assertRaisesRegex(ContractError, "standard report"):
            validate_envelope(valid_envelope(markdown=reordered))

    def test_validator_rejects_invalid_json_without_mutating_it(self):
        invalid = copy.deepcopy(REPORT)
        invalid["sections"].pop("radio")
        original = copy.deepcopy(invalid)
        with self.assertRaisesRegex(ContractError, "sections"):
            build_envelope(MARKDOWN, invalid, "摘要", "host_agent", "2.4.0")
        self.assertEqual(invalid, original)

    def test_validator_rejects_incomplete_detector_section_payload(self):
        invalid = copy.deepcopy(REPORT)
        invalid["sections"]["adapter"] = {}
        with self.assertRaisesRegex(ContractError, "fields"):
            build_envelope(MARKDOWN, invalid, "摘要", "host_agent", "2.4.0")

    def test_build_envelope_accepts_detector_english_standard_report(self):
        report = Report.empty()
        report.sections["system"]["checked_at"] = Field(
            "2026-08-21T14:00:00+08:00", source="fixture"
        )
        report.diagnosis = diagnose(report)
        markdown = render_text(report, language="en")
        envelope = build_envelope(markdown, report.to_dict(), "summary", "host_agent", "2.4.0")
        self.assertEqual(envelope.report["markdown"], markdown)

    def test_to_dict_uses_the_versioned_envelope_order(self):
        payload = valid_envelope().to_dict()
        self.assertEqual(list(payload), [
            "schema_version", "report_id", "generated_at", "detector", "report", "ai_summary",
        ])
        self.assertEqual(payload["schema_version"], "1")


if __name__ == "__main__":
    unittest.main()
