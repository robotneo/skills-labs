# Enterprise Notification Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically hand a validated `wifi-health-detector` report to a cross-agent notification bridge that uses the host AI for summarization and sends through a single non-conflicting DingTalk, Feishu, or WeCom Provider.

**Architecture:** Add a separate `enterprise-notification-bridge` Skill with a Python 3.7-compatible core, CLI, MCP stdio interface, Provider selection, local non-secret configuration, and SQLite delivery ledger. Integrate it only after the detector has rendered and validated its unchanged standard report; notification failures are reported separately and never change a successful detection exit code.

**Tech Stack:** Python 3.7+ standard library, `unittest`, SQLite, JSON/YAML-compatible configuration, subprocess-based DWS adapter, JSON-RPC 2.0 MCP stdio interface.

**Spec:** `docs/superpowers/specs/2026-08-31-enterprise-notification-bridge-design.md`

## Global Constraints

- Keep `wifi-health-detector` compatible with macOS 10.12+ and Windows 10/11 using Python 3.7+.
- Preserve the detector's fixed five-section Markdown report and all 18 core rows byte-for-byte regardless of notification state.
- Notification failure is non-blocking and must not change a successful detector exit code.
- Platform credentials remain owned by the native connector or platform CLI and never enter repository files, reports, configuration, or delivery ledgers.
- Each platform selects exactly one Provider implementation per delivery attempt.
- Multiple organizations or ambiguous recipients always require explicit user selection.
- The host agent supplies the AI summary; deterministic summary generation is the fallback.
- Recipient configuration may remain empty; in that state no message is sent.
- Use TDD for every behavior change and make a focused commit after each task.

## File Structure

### New Skill

- `enterprise-notification-bridge/SKILL.md` — agent-independent workflow and native/CLI capability mapping.
- `enterprise-notification-bridge/README.md` — installation, binding, recipient setup, CLI and MCP usage.
- `enterprise-notification-bridge/manifest.json` — Skill metadata and supported agents/platforms.
- `enterprise-notification-bridge/skill.yaml` — compact Skill registry metadata.
- `enterprise-notification-bridge/main.py` — compatibility entry point.
- `enterprise-notification-bridge/run.sh` — macOS/Linux launcher.
- `enterprise-notification-bridge/run.bat` and `run.ps1` — Windows launchers.
- `enterprise-notification-bridge/notification_bridge/models.py` — versioned envelope and result types.
- `enterprise-notification-bridge/notification_bridge/contract.py` — envelope/report validation and stable report ID.
- `enterprise-notification-bridge/notification_bridge/config.py` — non-secret local configuration loading and atomic writes.
- `enterprise-notification-bridge/notification_bridge/providers/base.py` — Provider protocol and selection data types.
- `enterprise-notification-bridge/notification_bridge/providers/dws.py` — DingTalk DWS command adapter.
- `enterprise-notification-bridge/notification_bridge/providers/native.py` — host-agent native connector handshake for DingTalk, Feishu, and WeCom.
- `enterprise-notification-bridge/notification_bridge/selector.py` — explicit/native/CLI Provider precedence.
- `enterprise-notification-bridge/notification_bridge/ledger.py` — SQLite idempotency claims and delivery outcomes.
- `enterprise-notification-bridge/notification_bridge/service.py` — authorization, binding, recipient, summary fallback, and send orchestration.
- `enterprise-notification-bridge/notification_bridge/cli.py` — CLI commands and structured JSON output.
- `enterprise-notification-bridge/notification_bridge/mcp_server.py` — MCP stdio tools backed by the same service.
- `enterprise-notification-bridge/tests/` — contract, Provider, service, ledger, CLI, MCP, and launcher tests.

### Existing Skill Changes

- `wifi-health-detector/wifi_health/notification.py` — optional Bridge discovery and non-blocking invocation.
- `wifi-health-detector/wifi_health/cli.py` — render once, export envelope input, trigger Bridge after validation.
- `wifi-health-detector/wifi_health/output.py` — expose the existing validation function without changing rendering.
- `wifi-health-detector/tests/test_notification.py` — integration and output-isolation tests.
- `wifi-health-detector/SKILL.md`, `README.md`, `manifest.json`, and `skill.yaml` — document automatic post-report notification.

---

### Task 1: Versioned Handoff Contract

**Files:**
- Create: `enterprise-notification-bridge/notification_bridge/__init__.py`
- Create: `enterprise-notification-bridge/notification_bridge/models.py`
- Create: `enterprise-notification-bridge/notification_bridge/contract.py`
- Create: `enterprise-notification-bridge/tests/test_contract.py`
- Create: `enterprise-notification-bridge/tests/fixtures/standard-report.md`
- Create: `enterprise-notification-bridge/tests/fixtures/standard-report.json`

**Interfaces:**
- Consumes: standardized Markdown and JSON emitted by `wifi-health-detector` 2.4.x.
- Produces: `build_envelope(markdown, report_json, summary_text, summary_mode, detector_version) -> Envelope`, `validate_envelope(envelope) -> None`, and `Envelope.to_dict() -> OrderedDict`.

- [ ] **Step 1: Write failing contract tests**

```python
def test_build_envelope_is_stable_for_the_same_report():
    first = build_envelope(MARKDOWN, REPORT, "摘要", "host_agent", "2.4.0")
    second = build_envelope(MARKDOWN, REPORT, "另一摘要", "host_agent", "2.4.0")
    self.assertEqual(first.report_id, second.report_id)

def test_report_validator_rejects_added_core_row():
    envelope = valid_envelope(markdown=MARKDOWN.replace(
        "| 安全类型 | none |", "| 新增字段 | value |\n| 安全类型 | none |"
    ))
    with self.assertRaisesRegex(ContractError, "standard report"):
        validate_envelope(envelope)

def test_summary_is_not_part_of_report_identity():
    self.assertNotIn("摘要", build_envelope(MARKDOWN, REPORT, "摘要", "host_agent", "2.4.0").report.markdown)
```

- [ ] **Step 2: Run the contract tests and verify RED**

Run: `python3 -m unittest enterprise-notification-bridge/tests/test_contract.py -v`

Expected: import failure because `notification_bridge.contract` does not exist.

- [ ] **Step 3: Implement immutable models and validation**

Implement these exact public types:

```python
class ContractError(ValueError):
    pass

class Envelope(object):
    schema_version = "1"

    def __init__(self, report_id, generated_at, detector, report, ai_summary):
        self.report_id = report_id
        self.generated_at = generated_at
        self.detector = detector
        self.report = report
        self.ai_summary = ai_summary

    def to_dict(self):
        return OrderedDict([
            ("schema_version", self.schema_version),
            ("report_id", self.report_id),
            ("generated_at", self.generated_at),
            ("detector", self.detector),
            ("report", self.report),
            ("ai_summary", self.ai_summary),
        ])

def compute_report_id(markdown, report_json):
    canonical_json = json.dumps(report_json, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload = (markdown + "\n" + canonical_json).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def build_envelope(markdown, report_json, summary_text, summary_mode, detector_version):
    envelope = Envelope(
        compute_report_id(markdown, report_json),
        report_json["sections"]["system"]["checked_at"]["value"],
        {"name": "wifi-health-detector", "version": detector_version},
        {"markdown": markdown, "json": copy.deepcopy(report_json)},
        {"mode": summary_mode, "text": summary_text},
    )
    validate_envelope(envelope)
    return envelope

def validate_envelope(envelope):
    if envelope.schema_version != "1":
        raise ContractError("unsupported envelope schema")
    if compute_report_id(envelope.report["markdown"], envelope.report["json"]) != envelope.report_id:
        raise ContractError("report_id does not match report")
    validate_markdown_contract(envelope.report["markdown"])
    validate_json_contract(envelope.report["json"])
```

Copy the detector's fixed section names and 18 core row labels into explicit contract constants. Validate exact order and reject missing or additional top-level report sections. Validate JSON `schema_version`, sections, diagnosis, and warnings without mutating the input.

- [ ] **Step 4: Run contract tests and the detector output contract tests**

Run:

```bash
python3 -m unittest enterprise-notification-bridge/tests/test_contract.py -v
python3 -m unittest wifi-health-detector/tests/test_core.py -v
```

Expected: both suites pass.

- [ ] **Step 5: Commit the handoff contract**

```bash
git add enterprise-notification-bridge/notification_bridge enterprise-notification-bridge/tests
git commit -m "feat: add notification bridge report contract"
```

### Task 2: Non-Secret Configuration and Provider Contract

**Files:**
- Create: `enterprise-notification-bridge/notification_bridge/config.py`
- Create: `enterprise-notification-bridge/notification_bridge/providers/__init__.py`
- Create: `enterprise-notification-bridge/notification_bridge/providers/base.py`
- Create: `enterprise-notification-bridge/notification_bridge/selector.py`
- Create: `enterprise-notification-bridge/tests/test_config.py`
- Create: `enterprise-notification-bridge/tests/test_selector.py`

**Interfaces:**
- Consumes: `BridgeConfig`, environment capability declarations, and Provider instances.
- Produces: `load_config(path=None) -> BridgeConfig`, `save_config(config, path=None) -> None`, `Provider` protocol, `ProviderResult`, and `select_provider(platform, configured_name, providers) -> Provider`.

- [ ] **Step 1: Write failing configuration and selection tests**

```python
def test_config_rejects_secret_fields(self):
    with self.assertRaisesRegex(ConfigError, "secret"):
        BridgeConfig.from_dict({"notification": {"token": "secret"}})

def test_explicit_provider_wins(self):
    chosen = select_provider("dingtalk", "dws-cli", [native_provider(), dws_provider()])
    self.assertEqual(chosen.name, "dws-cli")

def test_native_wins_over_cli_in_auto_mode(self):
    chosen = select_provider("dingtalk", "auto", [dws_provider(), native_provider()])
    self.assertEqual(chosen.name, "native")

def test_selector_returns_unavailable_without_invoking_login(self):
    chosen = select_provider("feishu", "auto", [])
    self.assertEqual(chosen.availability, "unavailable")
```

- [ ] **Step 2: Run tests and verify RED**

Run: `python3 -m unittest enterprise-notification-bridge/tests/test_config.py enterprise-notification-bridge/tests/test_selector.py -v`

Expected: import failures for configuration and selector modules.

- [ ] **Step 3: Implement Provider and configuration types**

Use these signatures:

```python
class Provider(object):
    platform = None
    name = None
    priority = 0

    def capabilities(self): raise NotImplementedError
    def auth_status(self, profile=None): raise NotImplementedError
    def login(self): raise NotImplementedError
    def list_profiles(self): raise NotImplementedError
    def resolve_recipient(self, profile, selector): raise NotImplementedError
    def send_report(self, profile, recipient, envelope): raise NotImplementedError

class ProviderResult(object):
    def __init__(self, status, reason="", retryable=False, data=None):
        self.status = status
        self.reason = reason
        self.retryable = bool(retryable)
        self.data = data or {}

def select_provider(platform, configured_name, providers):
    candidates = [item for item in providers if item.platform == platform and item.capabilities().get("available")]
    if configured_name != "auto":
        matches = [item for item in candidates if item.name == configured_name]
        if len(matches) != 1:
            return UnavailableProvider(platform, "configured_provider_unavailable")
        return matches[0]
    if not candidates:
        return UnavailableProvider(platform, "provider_unavailable")
    return sorted(candidates, key=lambda item: (-item.priority, item.name))[0]
```

`BridgeConfig.from_dict()` must accept only `version`, `notification.enabled`, `failure_policy`, `ai_summary`, and channel `platform/provider/profile/recipients`. Recursively reject keys containing `token`, `secret`, `password`, `credential`, or `refresh`.

Resolve the default configuration directory with `DWS_CONFIG_DIR`-independent, application-owned paths: `%APPDATA%/enterprise-notification-bridge` on Windows and `~/Library/Application Support/enterprise-notification-bridge` on macOS. Tests always inject a temporary path.

- [ ] **Step 4: Run configuration and selector tests**

Run: `python3 -m unittest enterprise-notification-bridge/tests/test_config.py enterprise-notification-bridge/tests/test_selector.py -v`

Expected: all tests pass.

- [ ] **Step 5: Commit Provider foundations**

```bash
git add enterprise-notification-bridge/notification_bridge enterprise-notification-bridge/tests
git commit -m "feat: add bridge provider selection and config"
```

### Task 3: DingTalk DWS and Native-Agent Providers

**Files:**
- Create: `enterprise-notification-bridge/notification_bridge/providers/dws.py`
- Create: `enterprise-notification-bridge/notification_bridge/providers/native.py`
- Create: `enterprise-notification-bridge/tests/test_dws_provider.py`
- Create: `enterprise-notification-bridge/tests/test_native_provider.py`

**Interfaces:**
- Consumes: `Provider`, `ProviderResult`, a command runner, and host-agent capability/result envelopes.
- Produces: `DwsProvider`, `NativeProvider`, and structured `action_required` results for login, profile selection, recipient selection, and native sends.

- [ ] **Step 1: Write failing DWS and native Provider tests**

```python
def test_dws_profile_list_uses_json_and_stable_profile(self):
    runner = FakeRunner(stdout='{"profiles":[{"profile":"corp:user","isCurrent":true}]}')
    result = DwsProvider(runner).list_profiles()
    self.assertEqual(runner.calls[0], ["dws", "profile", "list", "--format", "json"])
    self.assertEqual(result.data[0]["profile"], "corp:user")

def test_multiple_profiles_require_selection(self):
    result = choose_profile([{"profile": "a:u"}, {"profile": "b:u"}])
    self.assertEqual(result.status, "action_required")
    self.assertEqual(result.reason, "profile_selection_required")

def test_native_provider_emits_tool_request_without_guessing_tool_name(self):
    result = NativeProvider("feishu", capability_descriptor()).send_report(
        "tenant:user", "recipient", ENVELOPE
    )
    self.assertEqual(result.status, "action_required")
    self.assertEqual(result.data["operation"], "send_report")
```

- [ ] **Step 2: Run Provider tests and verify RED**

Run: `python3 -m unittest enterprise-notification-bridge/tests/test_dws_provider.py enterprise-notification-bridge/tests/test_native_provider.py -v`

Expected: import failures for `providers.dws` and `providers.native`.

- [ ] **Step 3: Implement safe command and native handshakes**

`DwsProvider` must:

- discover `dws` without changing authentication state;
- execute every DWS business command with `--format json`;
- use `dws auth status --format json`, `dws auth login --format json`, and `dws profile list --format json` only after their current `--help` confirms those flags;
- retain stable `profile=corpId:userId` values returned by DWS;
- return `action_required` when multiple Profiles exist;
- use an injected runner in every test;
- never use HTTP, browser automation, invented IDs, or copied tokens.

`NativeProvider` must accept a host-supplied capability descriptor rather than assuming Agent-specific tool names:

```python
{
  "platform": "feishu",
  "provider": "native",
  "operations": ["auth_status", "login", "list_profiles", "resolve_recipient", "send_report"]
}
```

Each operation returns an `action_required` record for the host agent. The host resumes the Bridge with a validated `operation_result`; the Bridge never executes an unknown native tool itself.

- [ ] **Step 4: Run Provider conformance tests**

Run: `python3 -m unittest enterprise-notification-bridge/tests/test_dws_provider.py enterprise-notification-bridge/tests/test_native_provider.py enterprise-notification-bridge/tests/test_selector.py -v`

Expected: all tests pass and no test launches an external login window.

- [ ] **Step 5: Commit Provider adapters**

```bash
git add enterprise-notification-bridge/notification_bridge/providers enterprise-notification-bridge/tests
git commit -m "feat: add dws and native notification providers"
```

### Task 4: Idempotent Delivery Ledger

**Files:**
- Create: `enterprise-notification-bridge/notification_bridge/ledger.py`
- Create: `enterprise-notification-bridge/tests/test_ledger.py`

**Interfaces:**
- Consumes: `report_id`, platform, Provider name, Profile, and recipient ID.
- Produces: `DeliveryLedger.claim(key) -> Claim`, `mark_success`, `mark_failure`, and `get`.

- [ ] **Step 1: Write failing ledger tests**

```python
def test_successful_delivery_cannot_be_claimed_twice(self):
    key = DeliveryKey("report", "dingtalk", "dws-cli", "corp:user", "recipient")
    first = self.ledger.claim(key)
    self.assertTrue(first.acquired)
    self.ledger.mark_success(first, "message-id")
    self.assertFalse(self.ledger.claim(key).acquired)

def test_retryable_failure_can_be_reclaimed(self):
    claim = self.ledger.claim(KEY)
    self.ledger.mark_failure(claim, "timeout", retryable=True)
    self.assertTrue(self.ledger.claim(KEY).acquired)

def test_two_connections_cannot_claim_concurrently(self):
    self.assertTrue(self.first.claim(KEY).acquired)
    self.assertFalse(self.second.claim(KEY).acquired)
```

- [ ] **Step 2: Run ledger tests and verify RED**

Run: `python3 -m unittest enterprise-notification-bridge/tests/test_ledger.py -v`

Expected: import failure for `notification_bridge.ledger`.

- [ ] **Step 3: Implement the SQLite ledger**

Use `sqlite3` with `BEGIN IMMEDIATE`, a unique compound key, and explicit states `claimed`, `succeeded`, `retryable_failure`, and `permanent_failure`.

```python
class DeliveryKey(namedtuple("DeliveryKeyBase", "report_id platform provider profile recipient")):
    __slots__ = ()

class DeliveryLedger(object):
    def claim(self, key):
        with self.transaction("IMMEDIATE") as connection:
            row = self._get_row(connection, key)
            if row and row["state"] in ("claimed", "succeeded", "permanent_failure"):
                return Claim(key, row["claim_id"], False)
            claim_id = uuid.uuid4().hex
            self._upsert_claim(connection, key, claim_id)
            return Claim(key, claim_id, True)

    def mark_success(self, claim, external_id=""):
        self._finish(claim, "succeeded", "", False, external_id)

    def mark_failure(self, claim, reason, retryable):
        state = "retryable_failure" if retryable else "permanent_failure"
        self._finish(claim, state, reason, retryable, "")

    def get(self, key):
        with self.connection() as connection:
            return self._get_row(connection, key)
```

Store timestamps, reason, retryability, and optional external message ID. Do not store Markdown, JSON reports, summaries, credentials, or tokens.

- [ ] **Step 4: Run ledger tests**

Run: `python3 -m unittest enterprise-notification-bridge/tests/test_ledger.py -v`

Expected: all tests pass, including the two-connection claim test.

- [ ] **Step 5: Commit the ledger**

```bash
git add enterprise-notification-bridge/notification_bridge/ledger.py enterprise-notification-bridge/tests/test_ledger.py
git commit -m "feat: add idempotent notification ledger"
```

### Task 5: Bridge Orchestration Service and Deterministic Summary

**Files:**
- Create: `enterprise-notification-bridge/notification_bridge/service.py`
- Create: `enterprise-notification-bridge/tests/test_service.py`

**Interfaces:**
- Consumes: validated `Envelope`, `BridgeConfig`, Providers, and `DeliveryLedger`.
- Produces: `BridgeService.deliver(envelope) -> DeliveryBatchResult`, `bind(platform) -> ProviderResult`, and `deterministic_summary(report_json) -> str`.

- [ ] **Step 1: Write failing service tests**

```python
def test_no_recipient_skips_without_calling_send(self):
    result = service(config=channel(recipients=[])).deliver(ENVELOPE)
    self.assertEqual(result.results[0].reason, "recipient_not_configured")
    self.assertEqual(provider.send_calls, [])

def test_host_summary_is_preserved_and_full_report_is_sent(self):
    service.deliver(ENVELOPE)
    sent = provider.send_calls[0].envelope
    self.assertEqual(sent.ai_summary["text"], "AI summary")
    self.assertEqual(sent.report["markdown"], STANDARD_MARKDOWN)

def test_failed_send_is_non_blocking_and_retryable(self):
    provider.next_result = ProviderResult("failed", "timeout", retryable=True)
    result = service.deliver(ENVELOPE)
    self.assertEqual(result.status, "notification_failed")
    self.assertTrue(result.results[0].retryable)

def test_missing_ai_summary_uses_deterministic_fallback(self):
    envelope = envelope_without_summary()
    result = service.deliver(envelope)
    self.assertIn("Wi-Fi", provider.send_calls[0].envelope.ai_summary["text"])
```

- [ ] **Step 2: Run service tests and verify RED**

Run: `python3 -m unittest enterprise-notification-bridge/tests/test_service.py -v`

Expected: import failure for `notification_bridge.service`.

- [ ] **Step 3: Implement orchestration in this exact order**

```python
def deliver(self, envelope):
    validate_envelope(envelope)
    for channel in self.config.enabled_channels():
        provider = select_provider(channel.platform, channel.provider, self.providers)
        if provider.availability == "unavailable":
            results.append(ProviderResult("skipped", provider.reason))
            continue
        auth = provider.auth_status(channel.profile)
        if auth.status != "authorized":
            results.append(auth)
            continue
        if not channel.profile:
            results.append(self.bind(channel.platform))
            continue
        if not channel.recipients:
            results.append(ProviderResult("skipped", "recipient_not_configured"))
            continue
        for selector in channel.recipients:
            results.append(self._deliver_one(provider, channel.profile, selector, envelope))
    return DeliveryBatchResult(results)
```

`deterministic_summary()` must use only health status, score, diagnosis issues, and recommendations already present in report JSON. It must not invent a cause or recommendation.

- [ ] **Step 4: Run all Bridge unit tests**

Run: `python3 -m unittest discover -s enterprise-notification-bridge/tests -v`

Expected: all tests pass.

- [ ] **Step 5: Commit the service**

```bash
git add enterprise-notification-bridge/notification_bridge/service.py enterprise-notification-bridge/tests/test_service.py
git commit -m "feat: orchestrate enterprise report delivery"
```

### Task 6: CLI and MCP Interfaces over the Same Core

**Files:**
- Create: `enterprise-notification-bridge/notification_bridge/cli.py`
- Create: `enterprise-notification-bridge/notification_bridge/mcp_server.py`
- Create: `enterprise-notification-bridge/main.py`
- Create: `enterprise-notification-bridge/tests/test_cli.py`
- Create: `enterprise-notification-bridge/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: JSON envelopes/configuration and the Task 5 `BridgeService`.
- Produces: CLI commands `status`, `bind`, `recipients`, `deliver`, `retry`, and MCP tools `notification_status`, `bind_notification_profile`, `configure_notification_recipient`, `deliver_enterprise_report`, `retry_enterprise_report`.

- [ ] **Step 1: Write failing CLI and MCP tests**

```python
def test_deliver_prints_json_only(self):
    code, stdout, stderr = run_cli(["deliver", "--envelope", self.path])
    self.assertEqual(code, 0)
    self.assertEqual(json.loads(stdout)["status"], "delivered")

def test_notification_failure_keeps_cli_success(self):
    code, stdout, _ = run_cli(["deliver", "--envelope", self.path])
    self.assertEqual(code, 0)
    self.assertEqual(json.loads(stdout)["status"], "notification_failed")

def test_mcp_tools_list_exposes_five_bridge_tools(self):
    response = send_rpc({"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}})
    self.assertEqual([tool["name"] for tool in response["result"]["tools"]], EXPECTED_TOOLS)
```

- [ ] **Step 2: Run interface tests and verify RED**

Run: `python3 -m unittest enterprise-notification-bridge/tests/test_cli.py enterprise-notification-bridge/tests/test_mcp_server.py -v`

Expected: import failures for CLI and MCP server modules.

- [ ] **Step 3: Implement thin interfaces**

The CLI must always emit one JSON document to standard output and diagnostics to standard error. `deliver` and `retry` return zero when the Bridge processed the request, including `notification_failed`; malformed envelopes and internal Bridge failures return nonzero.

The MCP server implements JSON-RPC `initialize`, `notifications/initialized`, `tools/list`, and `tools/call` over newline-delimited stdio. Tool handlers must call the same `BridgeService` methods as the CLI and return structured content; no Provider or delivery logic may live in `mcp_server.py`.

- [ ] **Step 4: Run interface and full Bridge tests**

Run:

```bash
python3 -m unittest enterprise-notification-bridge/tests/test_cli.py enterprise-notification-bridge/tests/test_mcp_server.py -v
python3 -m unittest discover -s enterprise-notification-bridge/tests -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit CLI and MCP interfaces**

```bash
git add enterprise-notification-bridge/main.py enterprise-notification-bridge/notification_bridge enterprise-notification-bridge/tests
git commit -m "feat: expose notification bridge cli and mcp tools"
```

### Task 7: Detector Post-Report Trigger with Output Isolation

**Files:**
- Create: `wifi-health-detector/wifi_health/notification.py`
- Create: `wifi-health-detector/tests/test_notification.py`
- Modify: `wifi-health-detector/wifi_health/cli.py`
- Modify: `wifi-health-detector/wifi_health/output.py`

**Interfaces:**
- Consumes: `render_text(report, language, mask, view)`, `render_json(report, mask)`, optional host summary/capability environment, and the Bridge CLI.
- Produces: `trigger_notification(markdown, report_json, summary=None, bridge_command=None) -> NotificationResult` without changing detector stdout or exit status.

- [ ] **Step 1: Write failing detector integration tests**

```python
def test_bridge_receives_report_after_validation(self):
    result = trigger_notification(STANDARD_MARKDOWN, REPORT_JSON, bridge_command=fake_bridge)
    self.assertEqual(result.status, "delivered")
    self.assertEqual(fake_bridge.envelope["report"]["markdown"], STANDARD_MARKDOWN)

def test_missing_bridge_is_non_blocking(self):
    result = trigger_notification(STANDARD_MARKDOWN, REPORT_JSON, bridge_command=["missing-bridge"])
    self.assertEqual(result.reason, "bridge_unavailable")

def test_notification_diagnostics_never_change_standard_output(self):
    before = run_detector(notification_enabled=False)
    after = run_detector(notification_enabled=True, bridge_result="failed")
    self.assertEqual(before.stdout, after.stdout)
    self.assertEqual(after.exit_code, 0)

def test_invalid_report_never_invokes_bridge(self):
    with self.assertRaises(ReportContractError):
        trigger_notification(INVALID_MARKDOWN, REPORT_JSON, bridge_command=fake_bridge)
    self.assertEqual(fake_bridge.calls, [])
```

- [ ] **Step 2: Run integration tests and verify RED**

Run: `python3 -m unittest wifi-health-detector/tests/test_notification.py -v`

Expected: import failure for `wifi_health.notification`.

- [ ] **Step 3: Expose validation and implement non-blocking trigger**

Refactor the existing renderer validation into a public `validate_standard_report(markdown, language)` function without changing any rendered bytes. In `cli.main()`:

```python
markdown = render_text(report, args.language, args.mask, args.view)
validate_standard_report(markdown, args.language)
json_text = render_json(report, args.mask)
print(markdown, end="")
notification_result = trigger_notification(markdown, json.loads(json_text))
if notification_result.requires_attention:
    print(notification_result.message, file=sys.stderr)
```

Bridge discovery order is an explicit `ENTERPRISE_NOTIFICATION_BRIDGE` command override followed by an adjacent installed Skill launcher. Never search or execute arbitrary similarly named commands. Add `--no-notify` for an explicit per-run opt-out and preserve current behavior when the Bridge is absent.

- [ ] **Step 4: Run detector and Bridge regression suites**

Run:

```bash
python3 -m unittest wifi-health-detector/tests/test_notification.py -v
python3 -m unittest discover -s wifi-health-detector/tests -v
python3 -m unittest discover -s enterprise-notification-bridge/tests -v
```

Expected: all tests pass and detector output snapshots are unchanged.

- [ ] **Step 5: Commit detector integration**

```bash
git add wifi-health-detector/wifi_health wifi-health-detector/tests
git commit -m "feat: trigger enterprise notifications after wifi reports"
```

### Task 8: Packaging, Cross-Agent Instructions, and End-to-End Verification

**Files:**
- Create: `enterprise-notification-bridge/SKILL.md`
- Create: `enterprise-notification-bridge/README.md`
- Create: `enterprise-notification-bridge/manifest.json`
- Create: `enterprise-notification-bridge/skill.yaml`
- Create: `enterprise-notification-bridge/run.sh`
- Create: `enterprise-notification-bridge/run.bat`
- Create: `enterprise-notification-bridge/run.ps1`
- Create: `enterprise-notification-bridge/tests/test_launchers.py`
- Create: `enterprise-notification-bridge/tests/test_agent_contracts.py`
- Modify: `wifi-health-detector/SKILL.md`
- Modify: `wifi-health-detector/README.md`
- Modify: `wifi-health-detector/manifest.json`
- Modify: `wifi-health-detector/skill.yaml`

**Interfaces:**
- Consumes: all Bridge and detector interfaces from Tasks 1-7.
- Produces: installable Skills whose instructions enforce the same handoff behavior across supported agents.

- [ ] **Step 1: Write failing launcher and instruction-contract tests**

```python
def test_every_agent_instruction_requires_report_validation_before_delivery(self):
    text = read_skill()
    for agent in ("Codex", "Claude Code", "WorkBuddy", "OpenClaw", "generic"):
        self.assertIn(agent, text)
    self.assertIn("validate", text.lower())
    self.assertIn("one Provider", text)

def test_launchers_forward_deliver_arguments(self):
    result = run_launcher(["deliver", "--envelope", fixture_path])
    self.assertEqual(json.loads(result.stdout)["status"], "recipient_not_configured")
```

- [ ] **Step 2: Run packaging tests and verify RED**

Run: `python3 -m unittest enterprise-notification-bridge/tests/test_launchers.py enterprise-notification-bridge/tests/test_agent_contracts.py -v`

Expected: failures because launchers and Skill metadata do not exist.

- [ ] **Step 3: Add packaging and exact agent workflow instructions**

The Bridge `SKILL.md` must instruct every agent to:

1. accept only validated standard reports;
2. generate a short summary from the JSON without changing the report;
3. declare native platform capabilities when present;
4. use native Provider first in auto mode, otherwise the supported CLI fallback;
5. complete login only on first use or expired authorization;
6. require explicit organization selection when ambiguous;
7. skip sending when recipients are empty;
8. keep notification failures outside the report and non-blocking;
9. never add, remove, or rename standardized report content.

Document DWS commands using `--format json`, stable `corpId:userId` Profiles, and no direct HTTP/browser fallback. Document Feishu and WeCom native-provider handshakes without inventing vendor-specific command names.

Increment `wifi-health-detector` to the next minor version and add `enterprise-notification-bridge` as an optional integration, not a Python package dependency.

- [ ] **Step 4: Run complete verification**

Run:

```bash
TEST_PYTHON=/Users/hua/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3
$TEST_PYTHON -m compileall -q wifi-health-detector enterprise-notification-bridge
$TEST_PYTHON -m unittest discover -s wifi-health-detector/tests -v
$TEST_PYTHON -m unittest discover -s enterprise-notification-bridge/tests -v
$TEST_PYTHON /Users/hua/.codex/skills/.system/skill-creator/scripts/quick_validate.py wifi-health-detector
$TEST_PYTHON /Users/hua/.codex/skills/.system/skill-creator/scripts/quick_validate.py enterprise-notification-bridge
git diff --check
```

Expected: both full suites pass, both Skills validate, compilation succeeds, and `git diff --check` emits no output.

- [ ] **Step 5: Perform a safe end-to-end dry run**

Run the detector with a fake Bridge Provider and verify:

- detector stdout equals the saved standard-report fixture;
- the Bridge receives one envelope;
- the AI summary is separate from the report;
- a missing recipient returns `recipient_not_configured` and sends nothing;
- a simulated Provider failure leaves detector exit code at zero;
- repeating the same envelope produces no duplicate send.

- [ ] **Step 6: Commit packaging and documentation**

```bash
git add enterprise-notification-bridge wifi-health-detector docs/superpowers
git commit -m "docs: package enterprise notification workflow"
```

## Final Review Checklist

- [ ] Compare every acceptance criterion in the design spec with at least one passing test named in this plan.
- [ ] Confirm no configuration, fixture, ledger, report, or Git diff contains real organization IDs, recipients, tokens, SSIDs, MAC addresses, or gateway addresses.
- [ ] Confirm notification diagnostics never appear in the standardized Markdown output.
- [ ] Confirm native and CLI Providers cannot both send the same platform/report combination.
- [ ] Confirm all subprocess calls use explicit argument arrays and all DWS calls request JSON.
- [ ] Confirm Python syntax remains compatible with 3.7 and no third-party runtime dependency was introduced.
- [ ] Run `git status --short` and verify only intended implementation files remain.
