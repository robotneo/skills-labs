from __future__ import absolute_import

import copy
import json
import os
import sys
import unittest
from collections import OrderedDict


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
DETECTOR_ROOT = os.path.dirname(os.path.dirname(ROOT))
if DETECTOR_ROOT not in sys.path:
    sys.path.insert(0, DETECTOR_ROOT)

from notification_bridge.contract import ContractError, build_envelope, compute_report_id, validate_envelope
from wifi_health.diagnose import diagnose
from wifi_health.models import Field, Report
from wifi_health.output import render_text


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
with open(os.path.join(FIXTURES, "standard-report.md"), "r", encoding="utf-8") as handle:
    MARKDOWN = handle.read()
with open(os.path.join(FIXTURES, "standard-report.json"), "r", encoding="utf-8") as handle:
    REPORT = json.load(handle)


def valid_envelope(markdown=MARKDOWN, report_json=REPORT):
    return build_envelope(markdown, report_json, "摘要", "host_agent", "2.4.0")


class ContractTests(unittest.TestCase):
    def test_legacy_detector_float_rendering_remains_accepted(self):
        from notification_bridge.standard_report import render_standard_markdown
        payload=copy.deepcopy(REPORT)
        field=payload['sections']['local_quality']['jitter']
        field.update(value=0.0,unit='ms',availability='available',reason='')
        markdown=render_standard_markdown(payload,'zh').replace('| 0 ms |','| 0.0 ms |')
        self.assertIn('0.0 ms',markdown)
        build_envelope(markdown,payload,'','deterministic','2.5.0')

    def test_build_envelope_is_stable_for_the_same_report(self):
        first = build_envelope(MARKDOWN, REPORT, "摘要", "host_agent", "2.4.0")
        second = build_envelope(MARKDOWN, REPORT, "另一摘要", "host_agent", "2.4.0")
        self.assertEqual(first.report_id, second.report_id)

    def test_report_validator_rejects_added_core_row(self):
        markdown = MARKDOWN.replace(
            "| 安全类型 | none |", "| 新增字段 | value |\n| 安全类型 | none |"
        )
        with self.assertRaisesRegex(ContractError, "standard report"):
            valid_envelope(markdown=markdown)

    def test_report_validator_rejects_arbitrary_inserted_prose(self):
        mutations = (
            MARKDOWN.replace(
                "# 📶 Wi-Fi 健康报告\n",
                "# 📶 Wi-Fi 健康报告\n\n任意新增内容\n",
                1,
            ),
            MARKDOWN.replace(
                "## 🧭 诊断与建议\n",
                "任意新增内容\n\n## 🧭 诊断与建议\n",
                1,
            ),
            MARKDOWN + "\n任意新增内容\n",
        )
        for markdown in mutations:
            with self.subTest(markdown=markdown):
                with self.assertRaisesRegex(ContractError, "standard report"):
                    valid_envelope(markdown=markdown)

    def test_report_validator_rejects_omitted_diagnosis_content(self):
        mutations = (
            MARKDOWN.replace("- 未发现明确问题\n", "", 1),
            MARKDOWN.replace("- 暂无建议\n", "", 1),
        )
        for markdown in mutations:
            with self.subTest(markdown=markdown):
                with self.assertRaisesRegex(ContractError, "standard report"):
                    valid_envelope(markdown=markdown)

    def test_report_validator_rejects_markdown_that_disagrees_with_json(self):
        markdown = MARKDOWN.replace("| Wi-Fi 名称 | Office |", "| Wi-Fi 名称 | Guest |", 1)
        with self.assertRaisesRegex(ContractError, "standard report"):
            valid_envelope(markdown=markdown)

    def test_report_validator_rejects_every_single_line_insertion_or_omission(self):
        lines = MARKDOWN.splitlines()
        for index in range(len(lines)):
            omitted = "\n".join(lines[:index] + lines[index + 1:]) + "\n"
            with self.subTest(operation="omit", line=index + 1):
                with self.assertRaisesRegex(ContractError, "standard report"):
                    valid_envelope(markdown=omitted)
        for index in range(len(lines) + 1):
            inserted = "\n".join(lines[:index] + ["任意新增内容"] + lines[index:]) + "\n"
            with self.subTest(operation="insert", line=index + 1):
                with self.assertRaisesRegex(ContractError, "standard report"):
                    valid_envelope(markdown=inserted)

    def test_build_envelope_canonicalizes_windows_line_endings(self):
        windows_markdown = MARKDOWN.replace("\n", "\r\n")
        envelope = valid_envelope(markdown=windows_markdown)
        self.assertEqual(envelope.report["markdown"], MARKDOWN)
        self.assertEqual(envelope.report_id, compute_report_id(MARKDOWN, REPORT))

    def test_bridge_validates_every_fixed_markdown_table(self):
        mutations = (
            ("| 健康状态 | 健康评分 | 数据置信度 |", "| 状态 | 健康评分 | 数据置信度 |"),
            ("| 测试目标 | 192.168.1.1 | 可用 |", "| 目标 | 192.168.1.1 | 可用 |"),
            ("| DNS 解析延迟 | 20 ms | 可用 |", "| DNS 延迟 | 20 ms | 可用 |"),
        )
        for old, new in mutations:
            with self.subTest(old=old):
                changed = MARKDOWN.replace(old, new, 1)
                self.assertNotEqual(changed, MARKDOWN)
                with self.assertRaisesRegex(ContractError, "standard report"):
                    valid_envelope(markdown=changed)

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

    def test_json_contract_compares_key_sets_not_mapping_order(self):
        reordered = copy.deepcopy(REPORT)
        reordered = OrderedDict(reversed(list(reordered.items())))
        reordered["sections"] = OrderedDict(
            reversed(list(reordered["sections"].items()))
        )
        for section, fields in list(reordered["sections"].items()):
            reordered["sections"][section] = OrderedDict(
                reversed(list(fields.items()))
            )
        reordered["diagnosis"] = OrderedDict(
            reversed(list(reordered["diagnosis"].items()))
        )

        envelope = build_envelope(
            MARKDOWN, reordered, "摘要", "host_agent", "2.5.0"
        )

        self.assertEqual(envelope.report_id, compute_report_id(MARKDOWN, reordered))

    def test_diagnosis_and_warning_items_have_strict_schemas(self):
        invalid_values = []
        issue = copy.deepcopy(REPORT)
        issue["diagnosis"]["issues"] = [42]
        invalid_values.append(issue)
        recommendation = copy.deepcopy(REPORT)
        recommendation["diagnosis"]["recommendations"] = [{
            "id": "weak_signal", "priority": "urgent", "reason": "weak",
            "action": "move", "unexpected": True,
        }]
        invalid_values.append(recommendation)
        category = copy.deepcopy(REPORT)
        category["diagnosis"]["category_scores"] = {"signal": "high"}
        invalid_values.append(category)
        warning = copy.deepcopy(REPORT)
        warning["warnings"] = [{"message": "opaque"}]
        invalid_values.append(warning)

        for report_json in invalid_values:
            with self.subTest(report_json=report_json):
                with self.assertRaisesRegex(ContractError, "report JSON"):
                    build_envelope(
                        MARKDOWN, report_json, "摘要", "host_agent", "2.5.0"
                    )

    def test_validator_rejects_incomplete_detector_section_payload(self):
        invalid = copy.deepcopy(REPORT)
        invalid["sections"]["adapter"] = {}
        with self.assertRaisesRegex(ContractError, "fields"):
            build_envelope(MARKDOWN, invalid, "摘要", "host_agent", "2.4.0")

    def test_validator_rejects_available_field_with_null_value(self):
        invalid = copy.deepcopy(REPORT)
        invalid["sections"]["adapter"]["interface"]["availability"] = "available"
        invalid["sections"]["adapter"]["interface"]["value"] = None
        with self.assertRaisesRegex(ContractError, "available field"):
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

    def test_build_envelope_accepts_detector_chinese_report_with_diagnosis(self):
        report = Report.empty()
        report.sections["system"]["checked_at"] = Field(
            "2026-09-01T12:00:00+08:00", source="fixture"
        )
        report.sections["radio"]["rssi"] = Field(-80, "dBm", source="fixture")
        report.diagnosis = diagnose(report)
        markdown = render_text(report, language="zh")

        envelope = build_envelope(
            markdown, report.to_dict(), "摘要", "host_agent", "2.5.0"
        )

        self.assertEqual(envelope.report["markdown"], markdown)
        self.assertEqual(envelope.report["json"]["diagnosis"]["issues"], ["weak_signal"])

    def test_to_dict_uses_the_versioned_envelope_order(self):
        payload = valid_envelope().to_dict()
        self.assertEqual(list(payload), [
            "schema_version", "report_id", "generated_at", "detector", "report", "ai_summary",
        ])
        self.assertEqual(payload["schema_version"], "1")

    def test_envelope_owns_canonical_defensive_copies(self):
        source = copy.deepcopy(REPORT)
        detector = {"name": "wifi-health-detector", "version": "2.5.0"}
        report = {"markdown": MARKDOWN, "json": source}
        summary = {"mode": "host_agent", "text": "摘要"}
        from notification_bridge.models import Envelope
        envelope = Envelope(
            compute_report_id(MARKDOWN, source),
            source["sections"]["system"]["checked_at"]["value"],
            detector, report, summary,
        )

        detector["name"] = "mutated"
        report["markdown"] = "mutated"
        summary["text"] = "mutated"
        exposed = envelope.to_dict()
        exposed["report"]["json"]["warnings"].append("mutated")

        self.assertEqual(envelope.detector["name"], "wifi-health-detector")
        self.assertEqual(envelope.report["markdown"], MARKDOWN)
        self.assertEqual(envelope.ai_summary["text"], "摘要")
        self.assertEqual(envelope.report["json"]["warnings"], [])

    def test_validator_rejects_invalid_generated_at(self):
        for generated_at in (None, "", "not-a-timestamp", "2026-02-30T12:00:00Z"):
            with self.subTest(generated_at=generated_at):
                from notification_bridge.models import Envelope
                payload = valid_envelope().to_dict()
                envelope = Envelope(
                    payload["report_id"], generated_at, payload["detector"],
                    payload["report"], payload["ai_summary"],
                )
                with self.assertRaisesRegex(ContractError, "generated_at"):
                    validate_envelope(envelope)

    def test_validator_rejects_invalid_detector_identity(self):
        invalid_detectors = (
            None,
            {},
            {"name": "wifi-health-detector", "version": ""},
            {"name": "other-detector", "version": "2.5.0"},
            {"name": "wifi-health-detector", "version": "2.3.9"},
            {"name": "wifi-health-detector", "version": "3.0.0"},
            {"name": "", "version": "2.4.0"},
            {"name": "wifi-health-detector", "version": "2.4.0", "extra": True},
        )
        for detector in invalid_detectors:
            with self.subTest(detector=detector):
                from notification_bridge.models import Envelope
                payload = valid_envelope().to_dict()
                envelope = Envelope(
                    payload["report_id"], payload["generated_at"], detector,
                    payload["report"], payload["ai_summary"],
                )
                with self.assertRaisesRegex(ContractError, "detector"):
                    validate_envelope(envelope)

    def test_validator_rejects_invalid_ai_summary(self):
        invalid_summaries = (
            None,
            {},
            {"mode": "external", "text": "summary"},
            {"mode": "host_agent", "text": 42},
            {"mode": "deterministic", "text": "summary", "extra": True},
        )
        for summary in invalid_summaries:
            with self.subTest(summary=summary):
                from notification_bridge.models import Envelope
                payload = valid_envelope().to_dict()
                envelope = Envelope(
                    payload["report_id"], payload["generated_at"],
                    payload["detector"], payload["report"], summary,
                )
                with self.assertRaisesRegex(ContractError, "ai_summary"):
                    validate_envelope(envelope)


if __name__ == "__main__":
    unittest.main()
