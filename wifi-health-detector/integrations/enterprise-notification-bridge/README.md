# Enterprise Notification Bridge

The Enterprise Notification Bridge delivers a validated Wi-Fi Health Detector
report to enabled, configured enterprise channels. It is a Python 3.7+
standard-library package with no third-party runtime dependency.

The Bridge preserves the detector's standard Markdown and JSON report. The
optional AI summary lives separately in the envelope and delivery diagnostics
never alter the report or block the detector's successful output.

JSON is the canonical report data. Before delivery, the Bridge rebuilds the
entire localized Markdown report deterministically from that JSON and requires
full-text equality, normalizing only Windows CRLF line endings to LF. Extra or
missing prose, rows, diagnosis items, recommendations, blank lines, reordered
content, and Markdown-equivalent rewrites are rejected before any Provider is
called. The same check runs again for continuation and durable retry sends.

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

To suppress the detector-to-Bridge trigger for one detector run, use
`wifi-health-detector --no-notify`. This flag does not alter the standardized
report.

Fresh installations start disabled. Activate delivery explicitly in this
order; no report generation enables notifications implicitly:

```text
run.sh status
run.sh enable --platform dingtalk --provider auto
run.sh setup --platform dingtalk --provider auto [--capabilities /path/to/capabilities.json]
run.sh recipients --platform dingtalk --profile corpId:userId --recipient <configured-selector>
run.sh deliver --envelope /path/to/validated-envelope.json
```

`enable` only persists the enabled channel and has no authentication side
effect. `setup` is native-first when the declared host-native DingTalk
capability includes the complete setup operation set (`auth_status`, `login`,
and `list_profiles`). A send-only or otherwise partial native capability is not
setup-capable, so `provider=auto` falls back to DWS while explicit
`provider=native` returns `configured_provider_unavailable`. DWS 1.0.15 or
newer is checked as a conditional fallback. Missing or outdated DWS returns an
action without executing it. Review that action, then approve explicitly with:

```text
run.sh setup --platform dingtalk --provider dws-cli --install-dws --yes
```

The official installer is pinned to a reviewed commit and checked against
bundled SHA-256 values before execution. `--china-mirror` selects its official
Gitee mirror; unavailable revisions and checksum mismatches fail closed.
Installation is limited to the CLI, not additional agent skills. See
[setup details](references/DWS-SETUP.md). Setup requests DingTalk login or QR/device
authorization only on first use or after authorization expires. `--device-login`
(MCP: `deviceLogin`) uses the documented `dws auth login --device` flow when a
DWS login is actually required; it has no effect when authorization is already
valid. Setup then binds a Provider-returned Profile. Multiple Profiles require
the user's exact choice.
Fixed recipients are configured afterward and can be decided later. For MCP
clients, use `bind_notification_profile`,
`configure_notification_recipient`, and `deliver_enterprise_report`.

The CLI writes one JSON result to stdout. Configure state and the metadata-only
delivery ledger with `ENTERPRISE_NOTIFICATION_BRIDGE_CONFIG` and
`ENTERPRISE_NOTIFICATION_BRIDGE_LEDGER`; durable pending actions, retry
envelopes, and first-send confirmations use
`ENTERPRISE_NOTIFICATION_BRIDGE_STATE`. Files are UTF-8 and created with
user-only permissions where the operating system supports them.

## Native and host continuation

Native DingTalk, Feishu, and WeCom integrations are supplied by the host as a
versioned capability bundle. Pass its JSON file with `--capabilities` to
`bind`, `deliver`, or `retry`. When the result is `action_required`, execute
only the returned semantic `action` through the host integration, then resume
the exact action with a correlated operation-result file:

```text
run.sh continue --operation-result /path/to/operation-result.json
```

The same continuation carries first-use/expired-login results, profile lists,
explicit multi-profile choices, resolved recipients, first-send confirmation,
host-generated summaries, send results, and stale-delivery reconciliation.
Do not edit correlation fields or invent tool names. `status` lists pending
actions after a process restart. A failed send can be retried without rerunning
Wi-Fi detection:

```text
run.sh retry --report-id <64-character-report-id> --capabilities /path/to/capabilities.json
```

Start the line-oriented MCP server with `python3 -m
notification_bridge.mcp_server`. It exposes six tools, including
`continue_enterprise_notification`; every tool delegates to the same durable
service used by the CLI.

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

Native DingTalk, Feishu, and WeCom delivery is a host-advertised capability handshake, so
this package does not invent vendor-specific tool names. The DWS fallback uses
documented commands with `--format json` and never uses a direct HTTP/browser
fallback. DWS recipient resolution and message sending remain host-mediated
until DWS documents those leaf operations; the Bridge returns a resumable
action instead of guessing a command.

DWS lifecycle management is independent of detection. Rerun approved setup
when the Bridge reports `dws_upgrade_required`, or use the official DWS upgrade
procedure. Uninstall DWS with its official platform procedure, then select a
native Provider or disable the channel. The detector never installs, upgrades,
authorizes, or uninstalls DWS.

See [references/DWS-SETUP.md](references/DWS-SETUP.md) for cross-platform and
cross-Agent setup, upgrade/uninstall guidance, and a gated real-environment
runbook. The runbook sends nothing unless an exact Profile, fixed recipient,
and separate first-send approval have all been supplied.

Local verification covers Python 3.7-compatible source and launcher behavior.
Release CI should also run the suite with Python 3.7 and on Windows with
PowerShell available; the local PowerShell launcher test is skipped when that
runtime is absent.

See [OPERATIONS.md](OPERATIONS.md) for the complete cross-agent handoff recipe for Codex,
Claude Code, WorkBuddy, OpenClaw, and generic compatible Agents.
