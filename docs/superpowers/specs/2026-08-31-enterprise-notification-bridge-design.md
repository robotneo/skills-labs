# Enterprise Notification Bridge Design

## Purpose

Extend the Wi-Fi health workflow so a successfully validated report can be summarized by the host AI agent and delivered through DingTalk, Feishu, or WeCom without coupling platform authentication or credentials to `wifi-health-detector`.

The design must work across Codex, Claude Code, WorkBuddy, OpenClaw, company-built agents with native enterprise messaging integrations, and agents that can only execute local commands.

## Scope

This design covers:

- triggering notification delivery after a valid Wi-Fi report is generated;
- using the host agent to generate a concise AI summary;
- preserving the complete standardized report without modification;
- first-use and expired-authorization login flows;
- organization and account binding;
- fixed-recipient configuration;
- DingTalk, Feishu, and WeCom provider boundaries;
- native-agent versus local-CLI provider selection;
- non-blocking notification failures;
- duplicate-delivery prevention.

This design does not select the final recipients, implement a central cloud service, or store enterprise-platform credentials in either Skill.

## Architecture

The workflow is split into two Skills with a narrow handoff contract.

### `wifi-health-detector`

Responsibilities:

- collect and diagnose Wi-Fi and network quality;
- produce the fixed five-section Markdown report;
- produce an equivalent machine-readable JSON report;
- validate both outputs before delivery is attempted;
- trigger `enterprise-notification-bridge` after successful validation;
- keep notification status out of the standardized report;
- return success when detection succeeds even if notification fails.

It must not authenticate enterprise accounts, select organizations, store recipients, or send messages directly.

### `enterprise-notification-bridge`

Responsibilities:

- accept the validated Markdown report, JSON report, and host-agent summary;
- validate the handoff envelope and standardized report contract;
- manage platform Provider discovery and selection;
- initiate first-use or expired-authorization login;
- bind an organization and account using stable platform identifiers;
- manage fixed-recipient configuration;
- send the AI summary together with the complete original report;
- generate and enforce an idempotency key;
- record delivery status separately from detector output;
- retry delivery without rerunning Wi-Fi detection.

It must not rewrite, shorten, reorder, or enrich the original standardized report.

### Host AI agent

Responsibilities:

- receive the validated JSON result;
- generate a short operational summary containing health state, material issues, and recommended actions;
- pass the summary and untouched reports to the Bridge;
- use a deterministic summary template when model summarization is unavailable.

This avoids requiring an additional LLM API key inside the Bridge.

## Handoff Contract

The detector hands the Bridge a versioned envelope:

```json
{
  "schema_version": "1",
  "report_id": "<stable-id>",
  "generated_at": "<RFC3339 timestamp>",
  "detector": {
    "name": "wifi-health-detector",
    "version": "<version>"
  },
  "report": {
    "markdown": "<complete standardized report>",
    "json": {}
  },
  "ai_summary": {
    "mode": "host_agent|deterministic",
    "text": "<short summary>"
  }
}
```

Requirements:

- `report_id` is derived from stable report inputs and is identical across retries of the same report.
- The Markdown report must pass the existing fixed-layout validator.
- The JSON report must pass its versioned schema.
- `ai_summary.text` is separate from the report and cannot replace it.
- Invalid envelopes are rejected without attempting authorization or delivery.

## Provider Model

Each messaging platform implements the same logical operations:

- `capabilities`: report available native and CLI capabilities;
- `auth_status`: report whether the selected identity is usable;
- `login`: initiate an interactive scan/login flow;
- `list_profiles`: list organizations and accounts available to the user;
- `bind_profile`: bind a stable organization/account identifier;
- `resolve_recipient`: resolve a configured fixed recipient without guessing IDs;
- `send_report`: deliver the summary and complete report;
- `delivery_status`: return a structured result suitable for retry decisions.

Initial platform Providers are DingTalk, Feishu, and WeCom. Provider-specific credentials remain owned by the native connector or platform CLI.

## Provider Selection and Conflict Avoidance

Exactly one Provider implementation is selected for each platform and delivery attempt. Selection order is:

1. a Provider explicitly configured by the user;
2. a compatible native Provider exposed by the current agent;
3. a supported local platform CLI, such as DingTalk DWS;
4. unavailable, which skips delivery and records a structured reason.

The Bridge must never invoke both a native connector and a local CLI for the same platform and report. Capability detection must not trigger login or change the current platform identity.

Provider credentials cannot be copied from one implementation to another. Switching Provider implementations requires a new authorization check and explicit binding validation.

## Authorization and Organization Binding

Authorization is required only on first use or when the saved authorization is invalid or expired.

Flow:

1. Check the selected Provider's authorization status.
2. If authorization is valid, continue without prompting.
3. If authorization is missing or expired, initiate the Provider's official login or scan flow.
4. Query available organization/account Profiles after successful login.
5. If exactly one valid Profile exists, bind it.
6. If multiple valid Profiles exist, require the user to select one.
7. Store only the stable, non-secret Profile identifier.

The implementation must not select the first, most recent, or similarly named organization when selection is ambiguous. For DWS, the stable value is `corpId:userId`, and credentials remain in DWS-managed secure storage.

## Recipient Configuration

Recipients are fixed but configured after organization binding.

- An empty recipient list means binding is complete but delivery is skipped.
- Recipient IDs must be resolved through the selected Provider; they cannot be invented or inferred from display names alone.
- Ambiguous people or groups require user selection.
- Recipient bindings are scoped to a platform Profile so they cannot silently cross organizations.
- Recipient changes do not require Wi-Fi detector changes.

## Runtime Flow

1. Run `wifi-health-detector`.
2. Validate the standardized Markdown and JSON reports.
3. Print only the standardized Markdown report to standard output.
4. Ask the host agent to create the short summary, or use the deterministic fallback.
5. Invoke `enterprise-notification-bridge` with the versioned envelope.
6. Discover and select one Provider for each enabled platform.
7. Complete authorization and organization binding when required.
8. Skip platforms with no configured recipient.
9. Check `report_id` against the delivery ledger.
10. Deliver the AI summary and complete report.
11. Record a structured success, skipped, retryable failure, or permanent failure result.

Notification logs and status go to a separate log or standard error and must never be appended to the standardized report.

## Failure Semantics

Notification delivery is non-blocking relative to Wi-Fi detection.

- Detection or report validation failure: return detector failure and do not invoke the Bridge.
- Bridge missing: preserve detector success and record `bridge_unavailable`.
- Authorization cancelled or failed: preserve detector success and record the Provider error.
- Organization selection required: preserve detector success and record `profile_selection_required`.
- No recipients configured: preserve detector success and record `recipient_not_configured`.
- AI summary failure: use the deterministic summary and continue.
- Retryable send failure: preserve detector success and store enough state to retry the same envelope.
- Permanent send failure: preserve detector success and report the platform's structured reason.

Only a detector/report failure may change the detector's success status.

## Idempotency and Retry

The Bridge maintains a local delivery ledger keyed by:

```text
report_id + platform + provider + profile + recipient
```

A successful ledger entry prevents duplicate delivery. A retryable failure can be retried with the same envelope without rerunning detection. Concurrent attempts must use an atomic claim so two agents cannot send the same report simultaneously.

The ledger contains delivery metadata only, not platform credentials.

## Configuration

Example non-secret configuration:

```yaml
version: 1
notification:
  enabled: true
  failure_policy: non_blocking
  ai_summary:
    provider: host_agent
    fallback: deterministic
  channels:
    - platform: dingtalk
      provider: auto
      profile: null
      recipients: []
    - platform: feishu
      provider: auto
      profile: null
      recipients: []
    - platform: wecom
      provider: auto
      profile: null
      recipients: []
```

Configuration must live in the user's local application configuration area, not in the installed Skill package or repository. Secret tokens and OAuth material are prohibited from this file.

## Security and Privacy

- Use only official native connectors or platform CLIs for authorization and delivery.
- Never print, export, or copy access and refresh tokens.
- Never commit local bindings, recipients, credentials, or delivery ledgers.
- Show the target platform, organization, Provider, and recipient before the first delivery.
- Treat the Wi-Fi report as potentially sensitive because it includes SSID, MAC address, network metrics, and gateway information.
- Do not enable public sharing or broad group delivery by default.
- Preserve the detector's explicit `--mask` behavior when the user requests redaction.

## Packaging and Cross-Agent Compatibility

The Bridge should use one implementation core with two interfaces:

- an MCP interface for agents that support MCP tools;
- a CLI interface for agents that can execute local commands.

Both interfaces must use the same validation, Provider selection, binding, idempotency, and delivery logic. Agent-specific Skill instructions only map host capabilities to the common Provider contract; they must not duplicate business logic.

An agent with a native enterprise connector can expose it as a native Provider. Agents without a native connector use the CLI interface and local platform CLI fallback.

## Test Strategy

### Contract tests

- accept valid standardized Markdown and JSON;
- reject reports with missing, reordered, added, or renamed fixed fields;
- prove the AI summary cannot mutate the original report;
- verify version handling and deterministic `report_id` generation.

### Provider tests

- run the same conformance suite against DingTalk, Feishu, and WeCom Providers;
- verify explicit Provider selection overrides automatic discovery;
- verify native Provider precedence over CLI fallback;
- verify only one Provider is invoked per platform;
- verify Provider switching requires authorization and binding validation.

### Authorization tests

- first-use scan flow;
- valid authorization without a new prompt;
- expired authorization requiring a new scan;
- single-organization automatic binding;
- multi-organization explicit selection;
- cancelled or failed authorization remains non-blocking.

### Delivery tests

- no recipient means no send;
- fixed-person and fixed-group resolution;
- ambiguous recipient requires selection;
- host-agent summary and deterministic fallback;
- successful delivery ledger entry;
- retryable failure and retry without redetection;
- concurrent duplicate suppression;
- permanent failure remains non-blocking.

### Integration tests

- `wifi-health-detector` output remains byte-for-byte independent of notification status;
- Codex, Claude Code, WorkBuddy, OpenClaw, and generic CLI instruction paths produce the same handoff envelope;
- native Agent connector and local CLI coexistence does not cause duplicate sends;
- notification diagnostics never add sections or rows to the standardized report.

## Acceptance Criteria

The design is successfully implemented when:

1. A valid Wi-Fi report automatically triggers the Bridge.
2. The detector report remains in its fixed standardized format.
3. First use and expired authorization initiate the official platform login flow.
4. Multiple organizations require explicit selection.
5. Recipient configuration can be deferred without causing errors or messages.
6. The host AI agent produces the summary, with a deterministic fallback.
7. The complete original report is always included in a delivered message.
8. Native and CLI Providers do not conflict or duplicate delivery.
9. DingTalk, Feishu, and WeCom share one Provider contract.
10. Notification failures do not change a successful detector result.
11. A delivery can be retried without rerunning detection.
12. Credentials remain owned by the enterprise platform connector and never enter the repository or report.

