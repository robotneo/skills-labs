# Enterprise Notification Bridge

The Enterprise Notification Bridge delivers a validated Wi-Fi Health Detector
report to enabled, configured enterprise channels. It is a Python 3.7+
standard-library package with no third-party runtime dependency.

The Bridge preserves the detector's standard Markdown and JSON report. The
optional AI summary lives separately in the envelope and delivery diagnostics
never alter the report or block the detector's successful output.

## Run

macOS and Unix-like systems:

```bash
./run.sh status
./run.sh deliver --envelope /path/to/validated-envelope.json
```

Windows:

```text
run.bat status
run.bat deliver --envelope C:\path\to\validated-envelope.json
```

Fresh installations start disabled. Activate delivery explicitly in this
order; no report generation enables notifications implicitly:

```text
run.sh status
run.sh enable --platform dingtalk --provider auto
run.sh bind --platform dingtalk
run.sh recipients --platform dingtalk --profile corpId:userId --recipient <configured-selector>
run.sh deliver --envelope /path/to/validated-envelope.json
```

`enable` only persists the enabled channel and has no authentication side
effect. For MCP clients, call the existing
`configure_notification_recipient` tool to explicitly enable and configure the
channel, then call `bind_notification_profile` and
`deliver_enterprise_report`; the MCP surface remains exactly five tools.

The CLI writes one JSON result to stdout. Configure state and the metadata-only
delivery ledger with `ENTERPRISE_NOTIFICATION_BRIDGE_CONFIG` and
`ENTERPRISE_NOTIFICATION_BRIDGE_LEDGER` when a non-default location is needed.

## Configuration and safety

Delivery follows enabled channel configuration and its selected Provider. In
`auto` mode the host native Provider is preferred, with the supported CLI
fallback used only when native capability is unavailable. There is one Provider
per platform/report combination.

Profiles are stable values returned by the Provider, such as
`corpId:userId`. Multiple Profiles require an explicit user selection; the
Bridge never reuses a current organization or guesses an ID. Empty recipients
mean no send and return `recipient_not_configured`; the Bridge never infers
`self` or a default recipient.

Native Feishu and WeCom delivery is a host-advertised capability handshake, so
this package does not invent vendor-specific tool names. The DWS fallback uses
documented commands with `--format json` and never uses a direct HTTP/browser
fallback.

See [SKILL.md](SKILL.md) for the complete cross-agent handoff recipe for Codex,
Claude Code, WorkBuddy, OpenClaw, and generic compatible Agents.
