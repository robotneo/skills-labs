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

The Markdown report always starts with the complete fixed dashboard: status badge, score, confidence, ten core metric rows, issues, and prioritized recommendations. Relay this dashboard without removing rows. Use `--view summary` when the user asks for a concise check. The default `--view full` appends all eight fixed detail sections; relay those details when the user asks for complete parameters or raw diagnostic evidence. Preserve unavailable values and their reasons.

Terminal output contains raw network identifiers. Use `--mask` before sharing or exporting results outside the user's private context. Throughput testing is opt-in with `--speedtest`; default public checks are only DNS and lightweight ping.

The skill has no third-party Python dependencies. For the schema and field semantics, read [references/OUTPUT-SCHEMA.md](references/OUTPUT-SCHEMA.md) only when integrating JSON/CSV output.
