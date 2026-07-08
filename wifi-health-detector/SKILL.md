---
name: wifi-health-detector
description: Detect Wi-Fi and wireless network quality on macOS and Windows. Use when the user asks to check Wi-Fi quality, wireless network status, SSID, band, channel, channel width, RSSI or signal strength, negotiated rate, IP address, gateway, MAC address, packet loss, latency, co-channel interference, health score, or optimization suggestions.
---

# Wi-Fi Health Detector

Run `main.py` to collect current Wi-Fi hardware parameters and local network quality, then output a health score and concise optimization suggestions.

Use local/elevated execution when possible. Latency, packet loss, Wi-Fi scan, and gateway checks need access to the real network interface; sandboxed execution may produce inaccurate network-quality values.

## Commands

```bash
python3 main.py
python3 main.py --interface en0
```

## Output Contract

Always preserve and fully relay both report sections. Do not summarize away either section in the assistant's final answer.

1. `📶 无线网络核心参数`: output this section as a Markdown table. Include IP address, gateway address, SSID, band, signal strength, negotiated rate, channel width, channel, co-channel interference, MAC address, latency, packet loss, and security type. Do not use `====` separator lines.
2. `🌐 当前网络状态`: health score, stability assessment, main issues, and optimization suggestions.

When answering the user after running this skill, include the complete `📶 无线网络核心参数` section first and the complete `🌐 当前网络状态` section second.

The skill is dependency-free and supports Python 3.7+ on macOS and Windows.
