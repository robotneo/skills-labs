---
name: enterprise-notification-bridge
description: Use when a validated Wi-Fi health report must be routed to configured enterprise notification channels through native host capabilities or the adjacent Bridge launcher.
---

# Enterprise Notification Bridge

Use this Skill only after the detector has produced and validated its standard
Markdown report and machine-readable JSON report. The report is the source of
truth; an AI-generated summary is a separate envelope field.

## Operational recipe

1. Validate both report representations against the detector's fixed output
   contract before preparing an envelope. If validation fails, stop and do not
   call a Provider.
2. Read the Bridge configuration and operate only on enabled channels. Honor
   each channel's configured platform and `provider`; do not use a hard-coded
   platform order. Use one Provider per platform/report combination. In `auto`
   mode, use the host's available native Provider first and the supported CLI
   fallback only when the native capability is unavailable. Never let native and
   CLI Providers both send the same combination.
3. Declare native platform capabilities when the host provides them. Native
   Feishu and WeCom integrations use a host-advertised handshake: request the
   semantic operations `auth_status`, `login`, `list_profiles`,
   `resolve_recipient`, and `send_report`, then accept only a matching host
   result. Do not invent vendor-specific tool or command names.
4. Check authorization before delivery. Ask the host to complete login only on
   first use or when authorization has expired; do not log in on every run.
5. Bind an organization only from Provider-returned Profiles. A Profile is a
   stable `corpId:userId` value supplied by the Provider. If multiple Profiles
   or organizations are returned, stop and require the user to select one
   explicitly; never reuse a current/default organization or guess an ID. If
   exactly one Profile is returned, it may be selected as the sole available
   choice and persisted as configuration.
6. Resolve recipients only from configured recipient selectors. An empty
   recipient list means `recipient_not_configured`: skip sending and report the
   status; never infer `self`, `default`, the current user, or any other
   recipient. A selector that cannot be resolved requires an explicit user
   choice.
7. Send the validated envelope through the selected Provider. Keep the original
   Markdown and JSON byte/content contract unchanged: never add, remove,
   rename, reorder, translate, or summarize inside the standardized report.
8. Keep delivery diagnostics outside the report. Notification failures,
   unavailable Providers, login/profile actions, and recipient configuration are
   non-blocking: preserve the detector report and exit status, while returning a
   structured Bridge result for follow-up.

## Supported interfaces

On macOS or Unix-like hosts, run `./run.sh`; on Windows, run `run.bat` (which
delegates to `run.ps1`). The launcher forwards the explicit Bridge commands:

```text
run.sh status
run.sh bind --platform <configured-platform>
run.sh recipients --platform <configured-platform> --profile corpId:userId --recipient <configured-selector>
run.sh deliver --envelope <validated-envelope.json> [--capabilities <capabilities.json>] [--request-host-summary]
run.sh retry --report-id <64-character-report-id> [--capabilities <capabilities.json>]
run.sh continue --operation-result <correlated-operation-result.json>
```

### Fresh installation setup

The default configuration is disabled and report generation never enables it
implicitly. Use this explicit CLI sequence, with a temporary or configured
`ENTERPRISE_NOTIFICATION_BRIDGE_CONFIG` path as needed:

```text
run.sh status
run.sh enable --platform dingtalk --provider auto
run.sh bind --platform dingtalk
run.sh recipients --platform dingtalk --profile corpId:userId --recipient <configured-selector>
run.sh deliver --envelope <validated-envelope.json>
```

`enable` only persists an enabled channel and performs no login or delivery.
`bind` then performs the Provider's authorization/Profile handshake. Do not
configure recipients before an exact Provider/Profile binding has completed.
MCP clients use `bind_notification_profile`,
`configure_notification_recipient`, `deliver_enterprise_report`,
`retry_enterprise_report`, and `continue_enterprise_notification`; the full
MCP surface contains six tools including `notification_status`.

The CLI emits exactly one JSON document on stdout and diagnostics on stderr.
`deliver` and `retry` remain process-successful when delivery itself fails;
malformed envelopes and internal errors are nonzero. The adjacent detector
launcher discovers this `run.sh`/`run.bat` path explicitly and never searches
arbitrary similarly named commands.

The detector's `--no-notify` flag suppresses the optional trigger for one run
without changing the report. Start the line-oriented MCP server with
`python3 -m notification_bridge.mcp_server`.

### Continuation protocol

Pass a versioned host capability bundle through `--capabilities` (or the
equivalent MCP argument). If the Bridge returns `action_required`, perform only
the returned semantic action using the host's native integration and submit a
result whose `action_id`, `report_id`, platform, Provider, and operation exactly
match. Resume with `continue --operation-result ...` or
`continue_enterprise_notification`. This protocol covers authorization status,
first-use/expired login, organization listing and explicit selection,
recipient resolution, first-send confirmation, host summary generation,
message sending, and stale-delivery reconciliation. Never synthesize a result
or change correlation fields.

Pending actions, retry envelopes, and confirmation scopes are durable under
`ENTERPRISE_NOTIFICATION_BRIDGE_STATE`; the metadata-only ledger is separate.
Use `retry --report-id ...` after a retryable failure so Wi-Fi detection does
not run again. `status` exposes pending actions after restart.

### DWS fallback

The DWS fallback is JSON-only. Before each supported leaf operation, confirm
that the Provider-returned help advertises JSON formatting, then invoke the
documented operation with `--format json`. Keep DWS Profile values exactly as
returned (`corpId:userId`); do not construct IDs or call undocumented send
commands. Recipient resolution and sending remain host-mediated when DWS does
not expose a documented operation. No direct HTTP/browser fallback is allowed
for DWS.

### Agent handoff

The same recipe applies in Codex, Claude Code, WorkBuddy, OpenClaw, and any
generic compatible Agent. The agent may generate a short summary from the
validated JSON, but must place it only in `ai_summary` and must preserve the
standard report exactly. If a Provider requests login, Profile selection, or
recipient selection, surface that action and wait for the user's explicit
choice; do not guess, silently reuse, or alter the report.
