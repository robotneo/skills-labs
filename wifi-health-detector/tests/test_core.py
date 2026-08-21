import csv
import io
import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from wifi_health.diagnose import diagnose
from wifi_health.cli import build_parser
from wifi_health.models import Field, Report, unavailable
from wifi_health.output import flatten_report, render_csv, render_json, render_text
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
        """
        en = parse_windows_netsh(english)
        zh = parse_windows_netsh(chinese)
        self.assertEqual(en["ssid"], "Lab:Guest")
        self.assertEqual(en["band"], "6 GHz")
        self.assertEqual(en["rx_rate"], 1201.0)
        self.assertEqual(zh["interface"], "WLAN")
        self.assertEqual(zh["channel"], 44)
        self.assertEqual(zh["tx_rate"], 780.0)
        self.assertEqual(zh["signal_percent"], 76)

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

    def test_default_full_report_has_dashboard_before_fixed_details(self):
        text = render_text(self._sample_report(), language="zh")
        headings = ["# 📶 Wi-Fi 健康报告", "## ⭐ 核心参数", "## 🧭 诊断与建议", "## 📋 完整参数详情"]
        positions = [text.index(heading) for heading in headings]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(text.count("### "), 10)  # issues, recommendations, and 8 fixed detail sections

    def test_dashboard_keeps_all_core_rows_when_values_are_unavailable(self):
        report = Report.empty()
        report.diagnosis = diagnose(report)
        text = render_text(report, language="zh", view="summary")
        for label in (
            "Wi-Fi 名称", "无线接口", "频段 / 信道 / 频宽", "信号强度", "信噪比",
            "发送 / 接收速率", "网关延迟", "网关抖动 / 丢包", "公网延迟 / 丢包", "安全类型",
        ):
            self.assertIn("| %s |" % label, text)
        self.assertIn("—（系统未提供", text)

    def test_summary_has_fixed_local_and_public_quality_sections(self):
        report = self._sample_report()
        report.sections["local_quality"]["target"] = Field("192.168.1.1", source="fixture")
        report.sections["local_quality"]["reachable"] = Field(True, source="fixture")
        report.sections["local_quality"]["jitter"] = Field(1.1, "ms", source="fixture")
        report.sections["public_quality"]["target"] = Field("1.1.1.1", source="fixture")
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

    def test_cli_defaults_to_full_and_accepts_summary(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args([]).view, "full")
        self.assertEqual(parser.parse_args(["--view", "summary"]).view, "summary")

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

    def test_all_sections_and_unavailable_reasons_are_preserved(self):
        report = Report.empty()
        report.sections["connection"]["ssid"] = Field("Office", source="fixture")
        report.sections["radio"]["noise"] = unavailable("not exposed by OS")
        report.diagnosis = diagnose(report)
        text = render_text(report, language="en")
        payload = json.loads(render_json(report))
        self.assertIn("System", text)
        self.assertIn("Diagnostics", text)
        self.assertIn("not exposed by OS", text)
        self.assertEqual(payload["schema_version"], "2.0")
        self.assertIn("public_quality", payload["sections"])

    def test_chinese_report_localizes_diagnosis_and_recommendations(self):
        report = Report.empty()
        report.sections["radio"]["rssi"] = Field(-80, "dBm", source="fixture")
        report.diagnosis = diagnose(report)
        text = render_text(report, language="zh")
        self.assertIn("数据置信度", text)
        self.assertIn("优化建议", text)
        self.assertIn("靠近接入点", text)
        self.assertNotIn("Recommendations:", text)

    def test_chinese_dashboard_localizes_evidence_and_runtime_notes(self):
        report = Report.empty()
        report.sections["radio"]["rssi"] = Field(-80, "dBm", source="fixture")
        report.warnings.append("Unable to identify the Wi-Fi interface; using en0 fallback.")
        report.diagnosis = diagnose(report)
        text = render_text(report, language="zh", view="summary")
        self.assertIn("RSSI 为 -80 dBm", text)
        self.assertIn("无法自动识别 Wi-Fi 接口，已使用 en0", text)
        self.assertNotIn("Move closer", text)
        self.assertNotIn("Unable to identify", text)

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
