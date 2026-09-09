---
name: wifi-health-detector
description: Use when diagnosing Wi-Fi quality, wireless status, signal, interference, link speed, addressing, latency, loss, security, or connection health on macOS 10.12+ or Windows 10/11.
---

# Wi-Fi Health Detector

Collect the complete client, radio, IP, local-network, and public-network report. Missing OS fields remain visible with their availability reason and never reduce the score.

Use local execution when possible. Sandboxes can hide SSID/radio fields or block network tests. Do not describe a runtime, command, permission, or sandbox error as a disconnected Wi-Fi diagnosis.

## Commands

```bash
# macOS 10.12+
./run.sh

# Windows 10/11
run.bat
```

The launchers validate Python 3.7+ before starting and distinguish a broken Apple `xcrun` proxy from Wi-Fi problems. Keep `python3 main.py` only as a compatibility fallback when a known-good interpreter is already available.

Useful options: `--interface`, `--mask`, `--json PATH`, `--csv PATH`, `--speedtest`, `--no-public-test`, `--timeout`, `--language zh|en`, `--view summary`, and `--verbose`. Run `--help` for details.

## Output Contract

The platform launcher's stdout is the complete final response. After a successful run, return stdout byte-for-byte as the entire answer: no preface, code fence, summary, interpretation, translation, conclusion, or trailing note. Do not reconstruct the report from JSON/CSV. If execution fails, report only the runtime error; never fabricate a report.

The report always contains exactly five top-level sections in this order: `📶 Wi-Fi Health Report`, `⭐ Core Metrics`, `🏠 Local Network Quality`, `🌐 Public Network Quality`, and `🧭 Diagnostics & Recommendations` (localized when `--language zh` is used). The core table always keeps these 18 rows in order: OS version, chip architecture, MAC address, Wi-Fi name, wireless interface, band, channel, channel width, RSSI, SNR, transmit rate, receive rate, gateway latency, gateway jitter, gateway loss, public latency, public loss, and security type. Missing values remain in their fixed positions with reasons. The executable validates this contract before printing and rejects nonstandard Markdown views. When handing the report to `enterprise-notification-bridge`, JSON is the canonical data and the Bridge deterministically rebuilds Markdown and requires full-text equality; no Agent may insert, omit, duplicate, reorder, translate, or reformat any report content.

JSON and CSV are explicit machine-data exports and retain all eight raw data sections. They never change or extend the Markdown report.

Enterprise notification is bundled as an optional component at `integrations/enterprise-notification-bridge`; no second Skill installation is needed. Notification is disabled by default. The detector hands off the validated report to the component, which skips delivery unless a channel is enabled. Its diagnostics remain outside the fixed report and never change detector stdout or exit status. The detector must never install, upgrade, authorize, or uninstall DWS.

For notification setup or a pending notification action, read [the Bridge operations guide](integrations/enterprise-notification-bridge/OPERATIONS.md). After the first report, offer optional notification setup through a separate follow-up interaction, keeping the final report response unchanged. Remember the user's choice: use Bridge `enable` or `disable`, persist the platform, Provider-returned organization and explicit recipients, and honor a saved disabled preference. Do not enable notification just because the component or a chat client is present. Reuse valid authorization; request login only on first use or expiry.

Use capabilities explicitly advertised and callable by the host, never the Agent's name as evidence. Prefer a complete native Provider; for DingTalk only, fall back to a verified local DWS CLI when native capability is unavailable. Install DWS only during requested notification setup with applicable user authorization. Feishu/WeCom without supported host capabilities require an integration, not DWS. Preserve the report when setup or delivery cannot complete.

Discovery order is the explicit `ENTERPRISE_NOTIFICATION_BRIDGE` JSON command vector, then the bundled component, then the legacy adjacent Bridge directory. Existing external overrides remain supported. `--no-notify` skips notification for one run without changing saved preferences.

Run without `--mask` so the standard report shows the Wi-Fi name. Add `--mask` only when the user explicitly requests redaction or says the report will be shared publicly; never hide the SSID by default. Throughput testing is opt-in with `--speedtest`. Default public checks aggregate mainland-China targets: AliDNS `223.5.5.5` and `223.6.6.6`, Tencent Public DNS `119.29.29.29`, Baidu `www.baidu.com`, and Taobao `www.taobao.com`.

Keep both transmit and receive rate rows. Windows reports independent association Rx/Tx PHY rates. Current macOS tools normally expose only the transmit PHY rate, so the receive row must remain visible with its specific unavailable reason; never infer it from transmit rate or replace it with zero. Channel width comes from full `system_profiler SPAirPortDataType` on macOS. On Windows, use the direct `netsh` field when present and otherwise derive current width from Native Wi-Fi BSS operation information elements; never substitute the adapter's configured maximum width.

The skill has no third-party Python dependencies. For the schema and field semantics, read [references/OUTPUT-SCHEMA.md](references/OUTPUT-SCHEMA.md) only when integrating JSON/CSV output.
