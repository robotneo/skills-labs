from __future__ import absolute_import

import re


def band_for_channel(channel):
    if channel is None:
        return None
    if 1 <= channel <= 14:
        return "2.4 GHz"
    return "5 GHz"


def parse_macos_airport(text):
    values = {}
    aliases = {
        "agrctlrssi": "rssi", "agrctlnoise": "noise", "lasttxrate": "tx_rate",
        "maxrate": "max_rate", "bssid": "bssid", "ssid": "ssid", "mcs": "mcs",
        "state": "state", "802.11 auth": "authentication", "link auth": "security",
    }
    for raw in text.splitlines():
        if ":" not in raw:
            continue
        key, value = raw.strip().split(":", 1)
        normalized = key.strip().lower()
        value = value.strip()
        if normalized == "channel":
            match = re.search(r"(\d+)(?:\s*,\s*(\d+))?", value)
            if match:
                values["channel"] = int(match.group(1))
                values["band"] = band_for_channel(values["channel"])
                if match.group(2):
                    values["channel_width"] = int(match.group(2))
            continue
        target = aliases.get(normalized)
        if not target:
            continue
        if target in ("rssi", "noise", "mcs"):
            match = re.search(r"-?\d+", value)
            if match:
                values[target] = int(match.group(0))
        elif target in ("tx_rate", "max_rate"):
            match = re.search(r"[\d.]+", value)
            if match:
                values[target] = float(match.group(0))
        else:
            values[target] = value
    if "rssi" in values and "noise" in values:
        values["snr"] = values["rssi"] - values["noise"]
    return values


WINDOWS_KEYS = {
    "name": "interface", "名称": "interface",
    "description": "description", "描述": "description",
    "physical address": "mac", "物理地址": "mac",
    "state": "state", "状态": "state",
    "ssid": "ssid", "bssid": "bssid",
    "radio type": "current_phy", "无线电类型": "current_phy",
    "authentication": "authentication", "身份验证": "authentication",
    "cipher": "cipher", "密码": "cipher",
    "channel": "channel", "频道": "channel",
    "receive rate (mbps)": "rx_rate", "接收速率(mbps)": "rx_rate",
    "transmit rate (mbps)": "tx_rate", "传输速率(mbps)": "tx_rate",
    "signal": "signal_percent", "信号": "signal_percent",
    "band": "band", "频带": "band",
}


def parse_windows_netsh(text):
    values = {}
    for raw in text.splitlines():
        if ":" not in raw:
            continue
        key, value = raw.strip().split(":", 1)
        normalized = re.sub(r"\s+", " ", key.strip()).lower()
        target = WINDOWS_KEYS.get(normalized)
        if not target:
            continue
        value = value.strip()
        if target == "ssid" and normalized == "bssid":
            continue
        if target == "channel":
            match = re.search(r"\d+", value)
            if match:
                values[target] = int(match.group(0))
        elif target in ("rx_rate", "tx_rate"):
            match = re.search(r"[\d.]+", value.replace(",", "."))
            if match:
                values[target] = float(match.group(0))
        elif target == "signal_percent":
            match = re.search(r"\d+", value)
            if match:
                values[target] = int(match.group(0))
        else:
            values[target] = value
    if "band" in values:
        match = re.search(r"(2\.4|5|6)", values["band"])
        if match:
            values["band"] = match.group(1) + " GHz"
    elif "channel" in values:
        values["band"] = band_for_channel(values["channel"])
    if "signal_percent" in values:
        values["rssi"] = int(values["signal_percent"] / 2.0 - 100)
    return values


def parse_ping(text):
    result = {"packet_loss_percent": 100.0, "latency_ms": None, "jitter_ms": None}
    loss_patterns = [
        r"([\d.]+)%\s*packet loss",
        r"\(([\d.]+)%\s*(?:loss|丢失)\)",
        r"([\d.]+)%\s*(?:丢失|loss)",
    ]
    for pattern in loss_patterns:
        match = re.search(pattern, text, re.I)
        if match:
            result["packet_loss_percent"] = float(match.group(1))
            break
    unix = re.search(r"(?:round-trip|rtt) min/avg/max/(?:stddev|mdev)\s*=\s*[\d.]+/([\d.]+)/[\d.]+/([\d.]+)", text, re.I)
    windows = re.search(r"(?:Average|平均)\s*=\s*([\d.]+)ms", text, re.I)
    if unix:
        result["latency_ms"] = float(unix.group(1))
        result["jitter_ms"] = float(unix.group(2))
    elif windows:
        result["latency_ms"] = float(windows.group(1))
        minimum = re.search(r"(?:Minimum|最短)\s*=\s*([\d.]+)ms", text, re.I)
        maximum = re.search(r"(?:Maximum|最长)\s*=\s*([\d.]+)ms", text, re.I)
        if minimum and maximum:
            result["jitter_ms"] = round(float(maximum.group(1)) - float(minimum.group(1)), 2)
    return result


def parse_windows_ipconfig(text):
    values = {}
    patterns = {
        "ipv4": r"(?:IPv4 Address|IPv4 地址)[^:]*:\s*([\d.]+)",
        "subnet": r"(?:Subnet Mask|子网掩码)[^:]*:\s*([\d.]+)",
        "gateway": r"(?:Default Gateway|默认网关)[^:]*:\s*([\d.]+)",
    }
    for name, pattern in patterns.items():
        match = re.search(pattern, text, re.I)
        if match:
            values[name] = match.group(1)
    return values


def parse_macos_default_route(text, interface):
    for raw in text.splitlines():
        columns = raw.split()
        if len(columns) >= 4 and columns[0] == "default" and columns[-1] == interface:
            return columns[1]
        if len(columns) >= 5 and columns[0] == "default" and columns[3] == interface:
            return columns[1]
    return None
