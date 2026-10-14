"""Direct unit tests for the Windows-only collection and parsing paths.

These paths used to be reached only indirectly through the portable/Node
black-box capture, making them the largest cross-platform regression blind
spot. They are pure data transforms (or early-return on non-Windows hosts), so
they can be tested directly on macOS/Linux without a WLAN stack.
"""
from __future__ import absolute_import

import os
import sys
import unittest
from unittest.mock import patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from wifi_health.command import CommandResult, CommandRunner
from wifi_health.collectors import WindowsCollector
from wifi_health.models import Report
from wifi_health.parsers import band_for_channel, parse_windows_ipconfig
from wifi_health import windows_wlan


ENGLISH_NETSH = """
    Name                   : Wi-Fi
    Description            : Intel(R) Wi-Fi 6E AX210
    Physical address       : 11:22:33:44:55:66
    State                  : connected
    SSID                   : Lab:Guest
    BSSID                  : aa:bb:cc:dd:ee:ff
    Radio type             : 802.11ax
    Authentication         : WPA3-Personal
    Cipher                 : CCMP
    Channel                : 36
    Receive rate (Mbps)    : 1201
    Transmit rate (Mbps)   : 961
    Signal                 : 82%
    Band                   : 5 GHz
    Channel width          : 80 MHz
"""

ENGLISH_IPCONFIG = """
Wireless LAN adapter Wi-Fi:

   Connection-specific DNS Suffix  . : lab.example
   IPv4 Address. . . . . . . . . . . : 192.168.1.20(Preferred)
   Subnet Mask . . . . . . . . . . . : 255.255.255.0
   Default Gateway . . . . . . . . . : 192.168.1.1
"""

CHINESE_IPCONFIG = """
无线局域网适配器 WLAN:

   IPv4 地址 . . . . . . . . . . . . : 10.0.0.5
   子网掩码  . . . . . . . . . . . . : 255.255.0.0
   默认网关. . . . . . . . . . . . . : 10.0.0.1
"""


class BandForChannelTests(unittest.TestCase):
    def test_none_channel_is_unknown_band(self):
        self.assertIsNone(band_for_channel(None))

    def test_two_point_four_and_five_gig_boundaries(self):
        for channel in (1, 6, 11, 14):
            self.assertEqual(band_for_channel(channel), "2.4 GHz", channel)
        for channel in (15, 36, 44, 149, 165):
            self.assertEqual(band_for_channel(channel), "5 GHz", channel)


class WindowsIpconfigParserTests(unittest.TestCase):
    def test_english_ipconfig(self):
        values = parse_windows_ipconfig(ENGLISH_IPCONFIG)
        self.assertEqual(values["ipv4"], "192.168.1.20")
        self.assertEqual(values["subnet"], "255.255.255.0")
        self.assertEqual(values["gateway"], "192.168.1.1")

    def test_chinese_ipconfig(self):
        values = parse_windows_ipconfig(CHINESE_IPCONFIG)
        self.assertEqual(values["ipv4"], "10.0.0.5")
        self.assertEqual(values["subnet"], "255.255.0.0")
        self.assertEqual(values["gateway"], "10.0.0.1")

    def test_missing_fields_are_simply_absent(self):
        self.assertEqual(parse_windows_ipconfig("Windows IP Configuration\n"), {})


class BssidNormalizationTests(unittest.TestCase):
    def test_none_and_empty(self):
        self.assertEqual(windows_wlan._normalize_bssid(None), "")
        self.assertEqual(windows_wlan._normalize_bssid(""), "")

    def test_dashes_lowercased_to_colons(self):
        self.assertEqual(
            windows_wlan._normalize_bssid("AA-BB-cc-DD-ee-ff"),
            "aa:bb:cc:dd:ee:ff",
        )

    def test_colon_form_is_lowercased_unchanged(self):
        self.assertEqual(
            windows_wlan._normalize_bssid("AA:BB:CC:DD:EE:FF"),
            "aa:bb:cc:dd:ee:ff",
        )


class ChannelWidthIeEdgeTests(unittest.TestCase):
    def test_empty_blob_has_no_width(self):
        self.assertIsNone(windows_wlan.channel_width_from_ies(b""))

    def test_ht_twenty_megahertz(self):
        # HT Operation with secondary offset 0 and no 40 MHz bit -> 20.
        self.assertEqual(
            windows_wlan.channel_width_from_ies(
                bytes([61, 22, 36, 0x00] + [0] * 20)),
            20,
        )
        # secondary offset 2 without the supporting bit still means 20.
        self.assertEqual(
            windows_wlan.channel_width_from_ies(
                bytes([61, 22, 36, 0x02] + [0] * 20)),
            20,
        )

    def test_unknown_vht_channel_width_defaults_to_twenty(self):
        self.assertEqual(
            windows_wlan.channel_width_from_ies(bytes([192, 5, 0, 0, 0, 0, 0])),
            20,
        )

    def test_truncated_information_element_is_ignored(self):
        # Element declares more bytes than remain; parsing must stop, not raise.
        self.assertIsNone(
            windows_wlan.channel_width_from_ies(bytes([61, 22, 36]))
        )

    def test_multiple_elements_keep_the_widest(self):
        ht20 = bytes([61, 22, 36, 0x00] + [0] * 20)
        vht80 = bytes([192, 5, 1, 0, 0, 0, 0])
        self.assertEqual(
            windows_wlan.channel_width_from_ies(ht20 + vht80), 80
        )


class CurrentChannelWidthPlatformGateTests(unittest.TestCase):
    @unittest.skipIf(os.name == "nt", "non-Windows early return only")
    def test_returns_none_without_touching_wlanapi_off_windows(self):
        self.assertIsNone(windows_wlan.current_channel_width("Lab", None))


class FakeRunner(object):
    """Scripted CommandRunner returning canned results per invoked command."""

    fast = True

    def __init__(self, mapping):
        self._mapping = mapping
        self.calls = []

    def run(self, args, timeout=None):
        args = list(args)
        self.calls.append(args)
        if args[:2] == ["netsh", "wlan"]:
            key = "netsh interfaces" if "interfaces" in args else "netsh networks"
        elif args and args[0] == "powershell.exe":
            key = "powershell"
        elif args[:2] == ["ipconfig", "/all"]:
            key = "ipconfig"
        else:
            key = "other"
        return self._mapping.get(key, CommandResult(args, 127, error="not scripted"))


class WindowsCollectorTests(unittest.TestCase):
    def _collect(self, runner):
        report = Report.empty()
        WindowsCollector(runner).collect(report)
        return report

    def test_maps_netsh_and_falls_back_to_ipconfig(self):
        runner = FakeRunner({
            "netsh interfaces": CommandResult([], 0, ENGLISH_NETSH),
            # PowerShell unavailable -> collector must fall back to ipconfig.
            "powershell": CommandResult([], 1, stderr="not found"),
            "ipconfig": CommandResult([], 0, ENGLISH_IPCONFIG),
        })
        report = self._collect(runner)
        self.assertEqual(report.get("connection", "ssid").value, "Lab:Guest")
        self.assertEqual(report.get("connection", "channel").value, 36)
        self.assertEqual(report.get("connection", "channel_width").value, 80)
        self.assertEqual(report.get("radio", "rssi").value, -59)  # 82% -> RSSI
        self.assertEqual(report.get("ip", "ipv4").value, "192.168.1.20")
        self.assertEqual(report.get("ip", "gateway").value, "192.168.1.1")
        # Fallback provenance is recorded, not PowerShell.
        self.assertEqual(report.get("ip", "ipv4").source, "ipconfig")
        invoked = ("powershell.exe" in [call[0] for call in runner.calls])
        self.assertTrue(invoked)

    def test_prefers_powershell_when_it_returns_json(self):
        powershell_json = (
            '{"ipv4": "172.16.0.9", "ipv6": "fe80::1", '
            '"gateway": "172.16.0.1", "dns_servers": ["1.1.1.1", "8.8.8.8"]}'
        )
        runner = FakeRunner({
            "netsh interfaces": CommandResult([], 0, ENGLISH_NETSH),
            "powershell": CommandResult([], 0, powershell_json),
            "ipconfig": CommandResult([], 0, ENGLISH_IPCONFIG),
        })
        report = self._collect(runner)
        self.assertEqual(report.get("ip", "ipv4").value, "172.16.0.9")
        self.assertEqual(report.get("ip", "gateway").value, "172.16.0.1")
        self.assertEqual(
            report.get("ip", "dns_servers").value, ["1.1.1.1", "8.8.8.8"]
        )
        self.assertEqual(
            report.get("ip", "ipv4").source, "PowerShell Get-NetIPConfiguration"
        )
        # Successful PowerShell means ipconfig /all must never run.
        self.assertNotIn(["ipconfig", "/all"], runner.calls)

    def test_warns_when_netsh_has_no_active_connection(self):
        runner = FakeRunner({
            "netsh interfaces": CommandResult([], 0, "There is no wireless interface."),
            "powershell": CommandResult([], 1),
            "ipconfig": CommandResult([], 0, ""),
        })
        report = self._collect(runner)
        self.assertTrue(
            any("netsh did not return an active Wi-Fi connection" in warning
                for warning in report.warnings)
        )

    def test_mismatched_requested_interface_warns(self):
        runner = FakeRunner({
            "netsh interfaces": CommandResult([], 0, ENGLISH_NETSH),
            "powershell": CommandResult([], 1),
            "ipconfig": CommandResult([], 0, ENGLISH_IPCONFIG),
        })
        report = Report.empty()
        WindowsCollector(runner, interface="Ethernet0").collect(report)
        self.assertTrue(
            any("Requested interface differs" in warning
                for warning in report.warnings)
        )


class CommandRunnerExitBranchTests(unittest.TestCase):
    def test_missing_executable_returns_127_without_raising(self):
        result = CommandRunner(timeout=5).run(
            ["/nonexistent/path/wifi-health-no-such-bin"]
        )
        self.assertEqual(result.returncode, 127)
        self.assertNotEqual(result.error, "")
        self.assertFalse(result.ok)

    def test_exhausted_budget_returns_124_before_spawning(self):
        runner = CommandRunner(timeout=10, budget=0.0)
        result = runner.run([sys.executable, "-c", "print(1)"])
        self.assertEqual(result.returncode, 124)
        self.assertIn("budget", result.error)

    def test_timeout_returns_124_and_marks_reason(self):
        import subprocess

        class FakeProcess(object):
            pid = 4242

            def __init__(self):
                self.communicate_calls = 0

            def communicate(self, timeout=None):
                self.communicate_calls += 1
                if self.communicate_calls == 1:
                    raise subprocess.TimeoutExpired("sleep", timeout)
                return b"", b""

        process = FakeProcess()
        with patch("wifi_health.command.subprocess.Popen",
                   return_value=process), patch(
                "wifi_health.command.os.killpg") as killpg:
            result = CommandRunner(timeout=1).run(["sleep", "30"])

        self.assertEqual(result.returncode, 124)
        self.assertEqual(result.error, "timeout")
        killpg.assert_called_once_with(4242, getattr(__import__("signal"), "SIGKILL"))


if __name__ == "__main__":
    unittest.main()
