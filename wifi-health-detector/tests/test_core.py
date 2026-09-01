import csv
import copy
import io
import json
import os
import sys
import tempfile
import unittest
from collections import OrderedDict
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from wifi_health.diagnose import diagnose
from wifi_health.cli import apply_quality, build_parser
from wifi_health.collectors import MacCollector
from wifi_health.command import CommandResult
from wifi_health.models import Field, Report, unavailable
from wifi_health.output import (
    ReportContractError,
    flatten_report,
    render_csv,
    render_json,
    render_text,
    validate_standard_json,
)
from wifi_health.parsers import (
    parse_macos_airport,
    parse_macos_default_route,
    parse_ping,
    parse_windows_netsh,
)


class ParserTests(unittest.TestCase):
    def test_macos_airport_parses_unicode_ssid_and_radio_metrics(self):
        sample = """
             agrCtlRSSI: -57
             agrCtlNoise: -92
             state: running
             op mode: station
             lastTxRate: 866
             maxRate: 1300
             802.11 auth: wpa2-psk
             link auth: wpa2-psk
             BSSID: aa:bb:cc:dd:ee:ff
             SSID: 办公室: 5G
             MCS: 9
             channel: 149,80
        """
        values = parse_macos_airport(sample)
        self.assertEqual(values["ssid"], "办公室: 5G")
        self.assertEqual(values["rssi"], -57)
        self.assertEqual(values["noise"], -92)
        self.assertEqual(values["snr"], 35)
        self.assertEqual(values["channel"], 149)
        self.assertEqual(values["channel_width"], 80)
        self.assertEqual(values["band"], "5 GHz")

    def test_windows_netsh_parses_english_and_chinese_fields(self):
        english = """
    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6E AX210
    Physical address       : 11:22:33:44:55:66
    State                  : connected
    SSID                   : Lab:Guest
    BSSID                  : aa:bb:cc:dd:ee:ff
    Radio type             : 802.11ax
    Authentication         : WPA3-Personal
    Cipher                 : CCMP
    Channel                : 37
    Receive rate (Mbps)    : 1201
    Transmit rate (Mbps)   : 961
    Signal                 : 82%
    Band                   : 6 GHz
    Channel width          : 160 MHz
        """
        chinese = """
    名称                   : WLAN
    描述                   : Intel Wireless
    物理地址               : 11-22-33-44-55-66
    状态                   : 已连接
    SSID                   : 办公网
    BSSID                  : aa:bb:cc:dd:ee:ff
    无线电类型             : 802.11ac
    身份验证               : WPA2-个人
    密码                   : CCMP
    频道                   : 44
    接收速率(Mbps)         : 866
    传输速率(Mbps)         : 780
    信号                   : 76%
    信道宽度               : 80 MHz
        """
        en = parse_windows_netsh(english)
        zh = parse_windows_netsh(chinese)
        self.assertEqual(en["ssid"], "Lab:Guest")
        self.assertEqual(en["band"], "6 GHz")
        self.assertEqual(en["rx_rate"], 1201.0)
        self.assertEqual(en["channel_width"], 160)
        self.assertEqual(zh["interface"], "WLAN")
        self.assertEqual(zh["channel"], 44)
        self.assertEqual(zh["tx_rate"], 780.0)
        self.assertEqual(zh["signal_percent"], 76)
        self.assertEqual(zh["channel_width"], 80)

    def test_windows_bss_information_elements_yield_current_channel_width(self):
        from wifi_health.windows_wlan import channel_width_from_ies

        ht_40 = bytes([61, 22, 36, 0x05] + [0] * 20)
        vht_80 = bytes([192, 5, 1, 42, 0, 0, 0])
        vht_160 = bytes([192, 5, 2, 50, 114, 0, 0])
        self.assertEqual(channel_width_from_ies(ht_40), 40)
        self.assertEqual(channel_width_from_ies(ht_40 + vht_80), 80)
        self.assertEqual(channel_width_from_ies(ht_40 + vht_160), 160)

    def test_ping_parser_handles_macos_windows_and_total_timeout(self):
        mac = "3 packets transmitted, 3 packets received, 0.0% packet loss\nround-trip min/avg/max/stddev = 1.0/2.0/4.0/1.2 ms"
        win = "Packets: Sent = 3, Received = 2, Lost = 1 (33% loss),\nMinimum = 8ms, Maximum = 14ms, Average = 11ms"
        timeout = "Request timeout for icmp_seq 0"
        self.assertEqual(parse_ping(mac)["latency_ms"], 2.0)
        self.assertEqual(parse_ping(mac)["jitter_ms"], 1.2)
        self.assertEqual(parse_ping(win)["packet_loss_percent"], 33.0)
        self.assertEqual(parse_ping(win)["latency_ms"], 11.0)
        self.assertEqual(parse_ping(timeout)["packet_loss_percent"], 100.0)

    def test_macos_netstat_fallback_selects_default_route_for_wifi_interface(self):
        sample = """
Destination        Gateway            Flags           Netif Expire
default            172.18.17.254      UGScg             en0
default            fe80::%utun3       UGcIg           utun3
        """
        self.assertEqual(parse_macos_default_route(sample, "en0"), "172.18.17.254")


class CollectorTests(unittest.TestCase):
    def test_macos_uses_full_profiler_for_width_and_explains_missing_rx_rate(self):
        profiler = """
          Current Network Information:
            Office:
              PHY Mode: 802.11ac
              Channel: 153 (5GHz, 20MHz)
              Security: WPA2 Personal
              Transmit Rate: 174
        """

        class Runner(object):
            def __init__(self):
                self.calls = []

            def run(self, args, timeout=None):
                self.calls.append(list(args))
                stdout = profiler if args[:2] == ["/usr/sbin/system_profiler", "SPAirPortDataType"] else ""
                return CommandResult(args, 0, stdout=stdout)

        runner = Runner()
        report = Report.empty()
        with patch("wifi_health.collectors.os.path.exists", return_value=False):
            MacCollector(runner)._collect_wireless(report)

        profiler_call = next(call for call in runner.calls if call[0] == "/usr/sbin/system_profiler")
        self.assertEqual(profiler_call, ["/usr/sbin/system_profiler", "SPAirPortDataType"])
        self.assertEqual(report.get("connection", "channel_width").value, 20)
        self.assertEqual(report.get("connection", "ssid").value, "Office")
        self.assertEqual(report.get("link", "rx_rate").reason, "macOS does not expose the current receive PHY rate")


class DiagnosisTests(unittest.TestCase):
    def test_unknown_metrics_do_not_reduce_score(self):
        report = Report.empty()
        report.sections["radio"]["rssi"] = unavailable("permission denied")
        report.sections["radio"]["snr"] = unavailable("unsupported")
        result = diagnose(report)
        self.assertEqual(result["score"], 100)
        self.assertLess(result["confidence_percent"], 100)
        self.assertEqual(result["verdict"], "insufficient_data")

    def test_observed_weak_signal_and_gateway_loss_create_evidence_based_advice(self):
        report = Report.empty()
        report.sections["radio"]["rssi"] = Field(-78, "dBm", source="fixture")
        report.sections["local_quality"]["packet_loss"] = Field(8.0, "%", source="fixture")
        result = diagnose(report)
        ids = [item["id"] for item in result["recommendations"]]
        self.assertIn("weak_signal", ids)
        self.assertIn("gateway_loss", ids)
        self.assertLess(result["score"], 70)

    def test_slow_dns_and_congested_24ghz_produce_targeted_advice(self):
        report = Report.empty()
        report.sections["connection"]["band"] = Field("2.4 GHz", source="fixture")
        report.sections["radio"]["same_channel_networks"] = Field(6, source="fixture")
        report.sections["public_quality"]["dns_latency"] = Field(420, "ms", source="fixture")
        result = diagnose(report)
        ids = [item["id"] for item in result["recommendations"]]
        self.assertIn("channel_congestion", ids)
        self.assertIn("prefer_higher_band", ids)
        self.assertIn("slow_dns", ids)


class PublicQualityTests(unittest.TestCase):
    def test_domestic_multi_target_results_are_aggregated_without_single_point_failure(self):
        report = Report.empty()
        ping_results = {
            "223.5.5.5": {"reachable": True, "latency_ms": 20.0, "jitter_ms": 2.0, "packet_loss_percent": 0.0},
            "223.6.6.6": {"reachable": False, "latency_ms": None, "jitter_ms": None, "packet_loss_percent": 100.0},
            "119.29.29.29": {"reachable": True, "latency_ms": 40.0, "jitter_ms": 4.0, "packet_loss_percent": 0.0},
        }
        dns_results = {
            "www.baidu.com": {"reachable": True, "latency_ms": 10.0},
            "www.taobao.com": {"reachable": True, "latency_ms": 30.0},
        }

        with patch("wifi_health.cli.ping_target", side_effect=lambda runner, target: ping_results[target]), patch(
            "wifi_health.cli.dns_test", side_effect=lambda host: dns_results[host]
        ):
            apply_quality(report, object())

        public = report.sections["public_quality"]
        self.assertEqual(
            public["target"].value,
            "223.5.5.5 / 223.6.6.6 / 119.29.29.29 / www.baidu.com / www.taobao.com",
        )
        self.assertTrue(public["reachable"].value)
        self.assertEqual(public["dns_latency"].value, 20.0)
        self.assertEqual(public["latency"].value, 30.0)
        self.assertEqual(public["jitter"].value, 3.0)
        self.assertEqual(public["packet_loss"].value, 0.0)


class OutputContractTests(unittest.TestCase):
    def _sample_report(self):
        report = Report.empty()
        report.sections["system"]["checked_at"] = Field("2026-08-21T14:00:00+08:00", source="fixture")
        report.sections["system"]["os"] = Field("Darwin", source="fixture")
        report.sections["adapter"]["interface"] = Field("en0", source="fixture")
        report.sections["connection"]["ssid"] = Field("Office", source="fixture")
        report.sections["connection"]["band"] = Field("5 GHz", source="fixture")
        report.sections["connection"]["channel"] = Field(149, source="fixture")
        report.sections["radio"]["rssi"] = Field(-55, "dBm", source="fixture")
        report.sections["local_quality"]["latency"] = Field(3.2, "ms", source="fixture")
        report.sections["local_quality"]["packet_loss"] = Field(0.0, "%", source="fixture")
        report.diagnosis = diagnose(report)
        return report

    def test_every_markdown_view_is_the_same_standard_report(self):
        report = self._sample_report()
        summary = render_text(report, language="zh", view="summary")
        full = render_text(report, language="zh", view="full")
        self.assertEqual(full, summary)
        self.assertEqual(
            [line for line in summary.splitlines() if line.startswith("## ")],
            [
                "## ⭐ 核心参数",
                "## 🏠 本地网络质量",
                "## 🌐 公网质量",
                "## 🧭 诊断与建议",
            ],
        )

    def test_dashboard_keeps_all_core_rows_when_values_are_unavailable(self):
        report = Report.empty()
        report.diagnosis = diagnose(report)
        text = render_text(report, language="zh", view="summary")
        for label in (
            "操作系统版本", "芯片架构", "MAC 地址", "Wi-Fi 名称", "无线接口",
            "Wi-Fi 工作频段", "无线信道", "信道频宽", "信号强度 RSSI", "信噪比 SNR",
            "发送速率", "接收速率", "网关延迟", "网关抖动", "网关丢包",
            "公网延迟", "公网丢包", "安全类型",
        ):
            self.assertIn("| %s |" % label, text)
        self.assertIn("—（系统未提供", text)

    def test_core_dashboard_uses_fixed_complete_parameter_rows_in_order(self):
        report = self._sample_report()
        report.sections["system"]["os_version"] = Field("13.7.8", source="fixture")
        report.sections["system"]["architecture"] = Field("x86_64", source="fixture")
        report.sections["adapter"]["mac"] = Field("38:f9:d3:5f:4b:77", source="fixture")
        text = render_text(report, language="zh", view="summary")
        labels = (
            "操作系统版本", "芯片架构", "MAC 地址", "Wi-Fi 名称", "无线接口",
            "Wi-Fi 工作频段", "无线信道", "信道频宽", "信号强度 RSSI", "信噪比 SNR",
            "发送速率", "接收速率", "网关延迟", "网关抖动", "网关丢包",
            "公网延迟", "公网丢包", "安全类型",
        )
        positions = [text.index("| %s |" % label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(len(positions), 18)

    def test_english_core_dashboard_matches_complete_chinese_layout(self):
        report = Report.empty()
        report.diagnosis = diagnose(report)
        text = render_text(report, language="en", view="summary")
        labels = (
            "Operating System Version", "Chip Architecture", "MAC Address", "Wi-Fi Name",
            "Wireless Interface", "Wi-Fi Band", "Wireless Channel", "Channel Width",
            "Signal Strength (RSSI)", "Signal-to-Noise Ratio (SNR)", "Transmit Rate",
            "Receive Rate", "Gateway Latency", "Gateway Jitter", "Gateway Packet Loss",
            "Public Latency", "Public Packet Loss", "Security Type",
        )
        positions = [text.index("| %s |" % label) for label in labels]
        self.assertEqual(positions, sorted(positions))

    def test_summary_has_fixed_local_and_public_quality_sections(self):
        report = self._sample_report()
        report.sections["local_quality"]["target"] = Field("192.168.1.1", source="fixture")
        report.sections["local_quality"]["reachable"] = Field(True, source="fixture")
        report.sections["local_quality"]["jitter"] = Field(1.1, "ms", source="fixture")
        report.sections["public_quality"]["target"] = Field("223.5.5.5", source="fixture")
        report.sections["public_quality"]["reachable"] = Field(True, source="fixture")
        report.sections["public_quality"]["dns_latency"] = Field(25.0, "ms", source="fixture")
        report.sections["public_quality"]["latency"] = Field(40.0, "ms", source="fixture")
        report.sections["public_quality"]["jitter"] = Field(2.0, "ms", source="fixture")
        report.sections["public_quality"]["packet_loss"] = Field(0.0, "%", source="fixture")
        text = render_text(report, language="zh", view="summary")
        headings = ["## ⭐ 核心参数", "## 🏠 本地网络质量", "## 🌐 公网质量", "## 🧭 诊断与建议"]
        positions = [text.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        for label in ("测试目标", "可达状态", "平均延迟", "网络抖动", "丢包率", "DNS 解析延迟"):
            self.assertIn("| %s |" % label, text)

    def test_quality_sections_keep_unavailable_rows_and_match_english_layout(self):
        report = Report.empty()
        report.diagnosis = diagnose(report)
        zh = render_text(report, language="zh", view="summary")
        en = render_text(report, language="en", view="summary")
        self.assertGreaterEqual(zh.count("—（系统未提供"), 12)
        self.assertIn("## 🏠 Local Network Quality", en)
        self.assertIn("## 🌐 Public Network Quality", en)
        self.assertIn("| DNS Latency |", en)

    def test_summary_view_omits_details_but_exports_remain_complete(self):
        report = self._sample_report()
        summary = render_text(report, language="zh", view="summary")
        payload = json.loads(render_json(report))
        rows = list(csv.DictReader(io.StringIO(render_csv(report))))
        self.assertNotIn("完整参数详情", summary)
        self.assertEqual(len(payload["sections"]), 8)
        self.assertEqual(len(rows), sum(len(fields) for fields in report.sections.values()))

    def test_cli_rejects_nonstandard_full_markdown_view(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args([]).view, "summary")
        self.assertEqual(parser.parse_args(["--view", "summary"]).view, "summary")
        with self.assertRaises(SystemExit):
            parser.parse_args(["--view", "full"])

    def test_default_cli_view_renders_only_the_five_fixed_sections(self):
        report = self._sample_report()
        view = build_parser().parse_args([]).view
        text = render_text(report, language="zh", view=view)
        headings = (
            "# 📶 Wi-Fi 健康报告", "## ⭐ 核心参数", "## 🏠 本地网络质量",
            "## 🌐 公网质量", "## 🧭 诊断与建议",
        )
        positions = [text.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn("完整参数详情", text)

    def test_renderer_default_is_the_same_fixed_summary(self):
        text = render_text(self._sample_report(), language="zh")
        self.assertIn("## 🧭 诊断与建议", text)
        self.assertNotIn("完整参数详情", text)

    def test_verdict_badges_are_stable_in_both_languages(self):
        expected = {
            "healthy": ("✅ 健康", "✅ Healthy"),
            "warning": ("⚠️ 一般/需关注", "⚠️ Warning"),
            "poor": ("❌ 较差", "❌ Poor"),
            "insufficient_data": ("❔ 数据不足", "❔ Insufficient data"),
        }
        for verdict, labels in expected.items():
            report = Report.empty()
            report.diagnosis = {"verdict": verdict, "score": 80, "confidence_percent": 50, "issues": [], "recommendations": []}
            self.assertIn(labels[0], render_text(report, language="zh", view="summary"))
            self.assertIn(labels[1], render_text(report, language="en", view="summary"))

    def test_machine_exports_preserve_all_sections_and_unavailable_reasons(self):
        report = Report.empty()
        report.sections["connection"]["ssid"] = Field("Office", source="fixture")
        report.sections["radio"]["noise"] = unavailable("not exposed by OS")
        report.diagnosis = diagnose(report)
        payload = json.loads(render_json(report))
        self.assertEqual(payload["schema_version"], "2.0")
        self.assertIn("public_quality", payload["sections"])
        self.assertEqual(payload["sections"]["radio"]["noise"]["reason"], "not exposed by OS")

    def test_json_validator_accepts_mapping_reordering(self):
        payload = json.loads(render_json(self._sample_report()))
        reordered = OrderedDict(reversed(list(payload.items())))
        reordered["sections"] = OrderedDict(
            reversed(list(reordered["sections"].items()))
        )
        reordered["diagnosis"] = OrderedDict(
            reversed(list(reordered["diagnosis"].items()))
        )

        validate_standard_json(reordered)

    def test_json_validator_rejects_malformed_diagnosis_and_warning_items(self):
        payload = json.loads(render_json(self._sample_report()))
        invalid_values = []
        issue = copy.deepcopy(payload)
        issue["diagnosis"]["issues"] = [7]
        invalid_values.append(issue)
        recommendation = copy.deepcopy(payload)
        recommendation["diagnosis"]["recommendations"] = [{
            "id": "weak_signal", "priority": "urgent", "reason": "weak",
            "action": "move", "unexpected": True,
        }]
        invalid_values.append(recommendation)
        warning = copy.deepcopy(payload)
        warning["warnings"] = [{"message": "opaque"}]
        invalid_values.append(warning)

        for invalid in invalid_values:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ReportContractError):
                    validate_standard_json(invalid)

    def test_chinese_report_localizes_diagnosis_and_recommendations(self):
        report = Report.empty()
        report.sections["radio"]["rssi"] = Field(-80, "dBm", source="fixture")
        report.diagnosis = diagnose(report)
        text = render_text(report, language="zh")
        self.assertIn("数据置信度", text)
        self.assertIn("优化建议", text)
        self.assertIn("靠近接入点", text)
        self.assertNotIn("Recommendations:", text)

    def test_standard_report_does_not_append_runtime_notes(self):
        report = Report.empty()
        report.sections["radio"]["rssi"] = Field(-80, "dBm", source="fixture")
        report.warnings.append("Unable to identify the Wi-Fi interface; using en0 fallback.")
        report.diagnosis = diagnose(report)
        text = render_text(report, language="zh", view="summary")
        self.assertIn("RSSI 为 -80 dBm", text)
        self.assertNotIn("运行提示", text)
        self.assertNotIn("Unable to identify", text)

    def test_macos_missing_receive_rate_has_a_specific_chinese_reason(self):
        report = self._sample_report()
        report.mark_unavailable(
            "link", "rx_rate", "macOS does not expose the current receive PHY rate", "macOS wireless tools"
        )
        text = render_text(report, language="zh")
        self.assertIn("macOS 未提供当前接收 PHY 速率", text)

    def test_masking_applies_to_text_json_and_csv(self):
        report = Report.empty()
        report.sections["connection"]["ssid"] = Field("SecretSSID", source="fixture")
        report.sections["connection"]["bssid"] = Field("aa:bb:cc:dd:ee:ff", source="fixture")
        report.sections["ip"]["ipv4"] = Field("192.168.10.24", source="fixture")
        report.diagnosis = diagnose(report)
        outputs = [
            render_text(report, mask=True, view="full"),
            render_text(report, mask=True, view="summary"),
            render_json(report, mask=True),
            render_csv(report, mask=True),
        ]
        for output in outputs:
            self.assertNotIn("SecretSSID", output)
            self.assertNotIn("aa:bb:cc:dd:ee:ff", output)
            self.assertNotIn("192.168.10.24", output)

    def test_csv_contains_value_unit_source_availability_and_reason(self):
        report = Report.empty()
        rows = list(csv.DictReader(io.StringIO(render_csv(report))))
        self.assertTrue(rows)
        self.assertEqual(
            set(rows[0]),
            {"section", "field", "value", "unit", "availability", "source", "reason"},
        )


if __name__ == "__main__":
    unittest.main()
