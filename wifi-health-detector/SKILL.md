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

Useful options: `--interface`, `--mask`, `--json PATH`, `--csv PATH`, `--speedtest`, `--no-public-test`, `--timeout`, `--language zh|en`, `--view full|summary`, and `--verbose`. Run `--help` for details.

## Output Contract

Run the platform launcher without `--view full`. Its default Markdown is the final answer and must be relayed verbatim. Do not summarize it, rewrite diagnoses, translate values, add commentary inside it, or remove, merge, rename, or reorder rows. If execution fails, report the runtime error separately instead of fabricating a report.

The default report always contains exactly five top-level sections in this order: `📶 Wi-Fi Health Report`, `⭐ Core Metrics`, `🏠 Local Network Quality`, `🌐 Public Network Quality`, and `🧭 Diagnostics & Recommendations` (localized when `--language zh` is used). It does not include Complete Parameter Details. The core table always keeps these 18 rows in order: OS version, chip architecture, MAC address, Wi-Fi name, wireless interface, band, channel, channel width, RSSI, SNR, transmit rate, receive rate, gateway latency, gateway jitter, gateway loss, public latency, public loss, and security type. Preserve unavailable values in their fixed positions together with their reasons.

Use `--view full` only when the user explicitly requests raw diagnostic evidence or the eight detailed data sections. JSON and CSV exports always remain complete regardless of the Markdown view.

Terminal output contains raw network identifiers. Use `--mask` before sharing or exporting results outside the user's private context. Throughput testing is opt-in with `--speedtest`; default public checks are only DNS and lightweight ping.

The skill has no third-party Python dependencies. For the schema and field semantics, read [references/OUTPUT-SCHEMA.md](references/OUTPUT-SCHEMA.md) only when integrating JSON/CSV output.
