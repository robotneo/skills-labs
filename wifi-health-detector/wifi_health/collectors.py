from __future__ import absolute_import

import datetime
import json
import os
import platform
import re
import sys

from .models import Report
from .parsers import band_for_channel, parse_macos_airport, parse_macos_default_route, parse_windows_ipconfig, parse_windows_netsh


AIRPORT = "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport"


def _set_values(report, mapping, values, source):
    for key, target in mapping.items():
        if key in values:
            section, name, unit = target
            report.set(section, name, values[key], unit=unit, source=source)


def collect_system(report):
    uname = platform.uname()
    report.set("system", "os", platform.system(), source="platform")
    version = platform.mac_ver()[0] if platform.system() == "Darwin" else platform.release()
    report.set("system", "os_version", version, source="platform")
    build = platform.version() if platform.system() == "Windows" else uname.release
    report.set("system", "build", build, source="platform")
    report.set("system", "architecture", platform.machine(), source="platform")
    report.set("system", "checked_at", datetime.datetime.now().astimezone().isoformat(), source="clock")
    privilege = "administrator/root" if hasattr(os, "geteuid") and os.geteuid() == 0 else "standard user"
    if platform.system() == "Windows": privilege = "current user"
    report.set("system", "privilege", privilege, source="runtime")
    report.set("system", "python_version", platform.python_version(), source=sys.executable)


class MacCollector(object):
    def __init__(self, runner, interface=None):
        self.runner = runner
        self.requested_interface = interface

    def collect(self, report):
        interface = self._interface(report)
        report.set("adapter", "interface", interface, source="networksetup")
        self._collect_ifconfig(report, interface)
        self._collect_route(report, interface)
        self._collect_wireless(report)
        self._collect_dns(report)

    def _interface(self, report):
        if self.requested_interface: return self.requested_interface
        result = self.runner.run(["/usr/sbin/networksetup", "-listallhardwareports"])
        lines = result.stdout.splitlines()
        for index, line in enumerate(lines):
            if re.match(r"Hardware Port:\s*(Wi-Fi|AirPort)", line, re.I) and index + 1 < len(lines):
                match = re.search(r"Device:\s*(\S+)", lines[index + 1])
                if match: return match.group(1)
        report.warnings.append("Unable to identify the Wi-Fi interface; using en0 fallback.")
        return "en0"

    def _collect_ifconfig(self, report, interface):
        result = self.runner.run(["/sbin/ifconfig", interface])
        if not result.ok:
            report.mark_unavailable("adapter", "status", result.error or result.stderr or "interface not found", "ifconfig")
            return
        patterns = {
            "status": r"status:\s*(\S+)", "mac": r"\bether\s+([0-9a-f:]{17})",
            "ipv4": r"\binet\s+([\d.]+)", "ipv6": r"\binet6\s+([^\s%]+)",
            "subnet": r"\binet\s+[\d.]+\s+netmask\s+(\S+)",
        }
        found = {name: re.search(pattern, result.stdout, re.I) for name, pattern in patterns.items()}
        if found["status"]: report.set("adapter", "status", found["status"].group(1), source="ifconfig")
        if found["mac"]: report.set("adapter", "mac", found["mac"].group(1), source="ifconfig")
        for name in ("ipv4", "ipv6", "subnet"):
            if found[name]: report.set("ip", name, found[name].group(1), source="ifconfig")

    def _collect_route(self, report, interface):
        result = self.runner.run(["/sbin/route", "-n", "get", "default"])
        gateway = re.search(r"gateway:\s*(\S+)", result.stdout)
        route_interface = re.search(r"interface:\s*(\S+)", result.stdout)
        if gateway and (not route_interface or route_interface.group(1) == interface):
            report.set("ip", "gateway", gateway.group(1), source="route")
            return
        fallback = self.runner.run(["/usr/sbin/netstat", "-rn", "-f", "inet"])
        gateway_value = parse_macos_default_route(fallback.stdout, interface)
        if gateway_value:
            report.set("ip", "gateway", gateway_value, source="netstat")

    def _collect_wireless(self, report):
        values = {}
        sources = []
        profiler = self.runner.run(["/usr/sbin/system_profiler", "SPAirPortDataType", "-detailLevel", "mini"], timeout=20)
        if profiler.stdout:
            parsed = _parse_macos_profiler(profiler.stdout)
            if parsed: values.update(parsed); sources.append("system_profiler")
        if os.path.exists(AIRPORT):
            airport = self.runner.run([AIRPORT, "-I"])
            if airport.stdout:
                values.update(parse_macos_airport(airport.stdout)); sources.append("airport -I")
            scan = self.runner.run([AIRPORT, "-s"], timeout=15)
            if scan.stdout and values.get("channel"):
                same, adjacent = _count_macos_channels(scan.stdout, values["channel"])
                values["same_channel_networks"] = same
                values["adjacent_channel_networks"] = adjacent
        if not values:
            wdutil = self.runner.run(["/usr/bin/wdutil", "info"])
            reason = wdutil.stderr or wdutil.stdout or "wireless details unavailable"
            report.warnings.append("Wireless details unavailable: " + reason.strip().splitlines()[0])
        mapping = {
            "ssid": ("connection", "ssid", ""), "bssid": ("connection", "bssid", ""),
            "state": ("connection", "state", ""), "security": ("connection", "security", ""),
            "authentication": ("connection", "authentication", ""), "band": ("connection", "band", ""),
            "channel": ("connection", "channel", ""), "center_channel": ("connection", "center_channel", ""),
            "channel_width": ("connection", "channel_width", "MHz"), "rssi": ("radio", "rssi", "dBm"),
            "noise": ("radio", "noise", "dBm"), "snr": ("radio", "snr", "dB"),
            "same_channel_networks": ("radio", "same_channel_networks", "networks"),
            "adjacent_channel_networks": ("radio", "adjacent_channel_networks", "networks"),
            "tx_rate": ("link", "tx_rate", "Mbps"), "max_rate": ("link", "max_rate", "Mbps"),
            "mcs": ("link", "mcs", ""), "current_phy": ("adapter", "current_phy", ""),
            "country_code": ("adapter", "country_code", ""), "firmware": ("adapter", "firmware", ""),
            "supported_phy": ("adapter", "supported_phy", ""), "description": ("adapter", "description", ""),
        }
        _set_values(report, mapping, values, "+".join(sources) or "macOS wireless tools")
        if values.get("rssi") is not None:
            report.set("radio", "signal_level", _signal_level(values["rssi"]), source="derived from RSSI")

    def _collect_dns(self, report):
        result = self.runner.run(["/usr/sbin/scutil", "--dns"])
        servers = []
        for match in re.finditer(r"nameserver\[\d+\]\s*:\s*(\S+)", result.stdout):
            if match.group(1) not in servers: servers.append(match.group(1))
        if servers: report.set("ip", "dns_servers", servers, source="scutil")


class WindowsCollector(object):
    def __init__(self, runner, interface=None):
        self.runner = runner
        self.requested_interface = interface

    def collect(self, report):
        netsh = self.runner.run(["netsh", "wlan", "show", "interfaces"])
        values = parse_windows_netsh(netsh.stdout)
        if not values:
            report.warnings.append("netsh did not return an active Wi-Fi connection.")
        if self.requested_interface and values.get("interface") != self.requested_interface:
            report.warnings.append("Requested interface differs from the active interface returned by netsh.")
        mapping = {
            "interface": ("adapter", "interface", ""), "description": ("adapter", "description", ""),
            "mac": ("adapter", "mac", ""), "current_phy": ("adapter", "current_phy", ""),
            "state": ("connection", "state", ""), "ssid": ("connection", "ssid", ""),
            "bssid": ("connection", "bssid", ""), "authentication": ("connection", "authentication", ""),
            "cipher": ("connection", "cipher", ""), "band": ("connection", "band", ""),
            "channel": ("connection", "channel", ""), "signal_percent": ("radio", "signal_percent", "%"),
            "rssi": ("radio", "rssi", "dBm estimated"), "tx_rate": ("link", "tx_rate", "Mbps"),
            "rx_rate": ("link", "rx_rate", "Mbps"),
        }
        _set_values(report, mapping, values, "netsh wlan")
        if values.get("interface"): report.set("adapter", "status", values.get("state", "present"), source="netsh wlan")
        if values.get("signal_percent") is not None:
            report.set("radio", "signal_level", _percent_level(values["signal_percent"]), source="derived from signal percent")
        ip_values = self._powershell_ip(values.get("interface"))
        source = "PowerShell Get-NetIPConfiguration"
        if not ip_values:
            ip_values = parse_windows_ipconfig(self.runner.run(["ipconfig", "/all"]).stdout)
            source = "ipconfig"
        for name in ("ipv4", "ipv6", "subnet", "gateway", "dns_servers", "dhcp_enabled", "dhcp_lease"):
            if name in ip_values: report.set("ip", name, ip_values[name], source=source)
        self._nearby(report, values.get("channel"))

    def _powershell_ip(self, interface):
        if not interface: return {}
        escaped = interface.replace("'", "''")
        script = ("$c=Get-NetIPConfiguration -InterfaceAlias '%s' -ErrorAction Stop;"
                  "[pscustomobject]@{ipv4=($c.IPv4Address.IPAddress|Select-Object -First 1);"
                  "ipv6=($c.IPv6Address.IPAddress|Select-Object -First 1);"
                  "gateway=($c.IPv4DefaultGateway.NextHop|Select-Object -First 1);"
                  "dns_servers=@($c.DNSServer.ServerAddresses)}|ConvertTo-Json -Compress" % escaped)
        result = self.runner.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script])
        if not result.ok: return {}
        try: return json.loads(result.stdout)
        except (ValueError, TypeError): return {}

    def _nearby(self, report, current_channel):
        text = self.runner.run(["netsh", "wlan", "show", "networks", "mode=bssid"]).stdout
        channels = [int(value) for value in re.findall(r"(?:Channel|频道)\s*:\s*(\d+)", text, re.I)]
        if current_channel is not None and channels:
            same = max(0, sum(1 for channel in channels if channel == current_channel) - 1)
            adjacent = sum(1 for channel in channels if channel != current_channel and abs(channel - current_channel) <= 4)
            report.set("radio", "same_channel_networks", same, "networks", "netsh wlan scan")
            report.set("radio", "adjacent_channel_networks", adjacent, "networks", "netsh wlan scan")


def _parse_macos_profiler(text):
    values = {}
    for pattern, name in ((r"Firmware Version:\s*(.+)", "firmware"), (r"Country Code:\s*(\S+)", "country_code"),
                          (r"Supported PHY Modes:\s*(.+)", "supported_phy"), (r"Card Type:\s*(.+)", "description"),
                          (r"Status:\s*(.+)", "state")):
        match = re.search(pattern, text)
        if match: values[name] = match.group(1).strip()
    current = re.search(r"Current Network Information:\s*\n\s*([^:]+):\s*\n(?P<body>(?:\s{10,}.+\n?)+)", text)
    if current:
        values["ssid"] = current.group(1).strip(); body = current.group("body")
        for key, name in (("PHY Mode", "current_phy"), ("BSSID", "bssid"), ("Security", "security")):
            match = re.search(re.escape(key) + r":\s*(.+)", body)
            if match: values[name] = match.group(1).strip()
        channel_text = re.search(r"Channel:\s*(.+)", body)
        if channel_text:
            channel = re.search(r"(\d+)", channel_text.group(1)); width = re.search(r"(\d+)MHz", channel_text.group(1), re.I)
            if channel: values["channel"] = int(channel.group(1)); values["band"] = band_for_channel(values["channel"])
            if width: values["channel_width"] = int(width.group(1))
    return values


def _count_macos_channels(text, current):
    channels = []
    for line in text.splitlines()[1:]:
        matches = re.findall(r"\b(\d{1,3})(?:,[+-]?\d+)?\b", line)
        if matches: channels.append(int(matches[-1]))
    return max(0, sum(c == current for c in channels) - 1), sum(c != current and abs(c - current) <= 4 for c in channels)


def _signal_level(rssi):
    if rssi >= -60: return "strong"
    if rssi >= -67: return "good"
    if rssi >= -75: return "weak"
    return "poor"


def _percent_level(percent):
    if percent >= 75: return "strong"
    if percent >= 55: return "good"
    if percent >= 35: return "weak"
    return "poor"


def collect_report(runner, interface=None):
    report = Report.empty(); collect_system(report)
    system = platform.system().lower()
    if system == "darwin": MacCollector(runner, interface).collect(report)
    elif system == "windows": WindowsCollector(runner, interface).collect(report)
    else: raise RuntimeError("Unsupported operating system: %s" % platform.system())
    return report
