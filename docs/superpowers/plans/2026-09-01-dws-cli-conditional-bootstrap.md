# DWS CLI Conditional Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an approved, cross-platform, conditionally invoked DWS CLI installation and verification workflow for the DingTalk fallback Provider.

**Architecture:** A focused dependency module discovers and verifies DWS, while a separate installer adapter produces and executes only approved official install plans. CLI and MCP expose one idempotent setup workflow that reuses the existing continuation, authorization, Profile, and Provider-selection services. `wifi-health-detector` remains report-first and never installs dependencies itself.

**Tech Stack:** Python 3.7+ standard library, POSIX shell, PowerShell, unittest, existing Bridge CLI/MCP/service/continuation architecture.

**Spec:** `docs/superpowers/specs/2026-09-01-dws-cli-conditional-bootstrap-design.md`

## Global Constraints

- DWS minimum version is exactly `1.0.15`.
- DWS is conditional on `dingtalk:dws-cli`; Python remains unconditional.
- `provider=native` and non-DingTalk platforms must never install DWS.
- `provider=auto` must prefer a declared host-native Provider before DWS.
- No remote installer may execute without explicit user approval.
- Only official DingTalk GitHub or explicitly selected official Gitee sources are allowed.
- Do not use `curl | sh`, `irm | iex`, direct DingTalk HTTP APIs, or undocumented DWS leaves.
- Every DWS business leaf retains the per-leaf `--help` JSON-format gate.
- Installation, authorization, and notification failures remain non-blocking for Wi-Fi output.
- No credentials, organization data, recipients, or report content may enter install logs.

---

### Task 1: Dependency discovery and version contract

**Files:**
- Create: `enterprise-notification-bridge/notification_bridge/dependencies.py`
- Create: `enterprise-notification-bridge/tests/test_dependencies.py`
- Modify: `enterprise-notification-bridge/manifest.json`
- Modify: `enterprise-notification-bridge/skill.yaml`

**Interfaces:**
- Produces: `DwsDependency`, `DependencyStatus`, `discover_dws(environment, platform_name, which)`, and `verify_dws(executable, runner)`.
- Consumes later: setup service and installer use the exact dependency status and executable path.

- [ ] **Step 1: Write failing discovery and version tests**

```python
def test_explicit_dws_executable_precedes_path_lookup(self):
    status = discover_dws(
        {"DWS_EXE": "/approved/dws"}, "darwin", lambda name: "/path/dws"
    )
    self.assertEqual(status.executable, "/approved/dws")

def test_version_below_1_0_15_requires_upgrade(self):
    status = verify_dws("/tmp/dws", FakeRunner(version="1.0.14"))
    self.assertEqual(status.reason, "dws_upgrade_required")
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
python3 -m unittest enterprise-notification-bridge/tests/test_dependencies.py
```

Expected: import failure because `notification_bridge.dependencies` does not exist.

- [ ] **Step 3: Implement immutable dependency results and semantic-version comparison**

Implement the exact minimum version constant, explicit-path precedence,
platform candidate paths, PATH lookup injection, JSON-only version parsing,
and stable reasons. Do not invoke installation from this module.

- [ ] **Step 4: Add conditional manifest metadata**

Add `conditional_requirements.dingtalk:dws-cli = ["dws>=1.0.15"]` without
moving Python out of the unconditional requirements.

- [ ] **Step 5: Run focused and existing DWS Provider tests**

```bash
python3 -m unittest \
  enterprise-notification-bridge/tests/test_dependencies.py \
  enterprise-notification-bridge/tests/test_dws_provider.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add enterprise-notification-bridge/notification_bridge/dependencies.py \
  enterprise-notification-bridge/tests/test_dependencies.py \
  enterprise-notification-bridge/manifest.json \
  enterprise-notification-bridge/skill.yaml
git commit -m "feat: declare and verify conditional dws dependency"
```

### Task 2: Official installer planning and approved execution

**Files:**
- Create: `enterprise-notification-bridge/notification_bridge/installer.py`
- Create: `enterprise-notification-bridge/tests/test_installer.py`

**Interfaces:**
- Consumes: `DependencyStatus` from Task 1.
- Produces: `DwsInstallPlan`, `plan_dws_install(platform_name, china_mirror)`, and `execute_dws_install(plan, approved, downloader, process_runner, temp_root)`.

- [ ] **Step 1: Write failing installer-boundary tests**

```python
def test_installer_refuses_execution_without_approval(self):
    result = execute_dws_install(
        official_plan("darwin"), False, downloader, runner, self.tempdir
    )
    self.assertEqual(result.reason, "dependency_install_declined")
    self.assertEqual(runner.calls, [])

def test_auto_plan_never_uses_shell_pipeline(self):
    plan = plan_dws_install("darwin", china_mirror=False)
    self.assertNotIn("|", plan.command)
    self.assertEqual(plan.source, "official-github")
```

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest enterprise-notification-bridge/tests/test_installer.py
```

Expected: import failure because `notification_bridge.installer` does not exist.

- [ ] **Step 3: Implement OS-specific official install plans**

Use a private temporary directory, a downloaded local script, `shell=False`,
and fixed source allowlists. Implement macOS/Linux shell-script execution and
Windows PowerShell `-File` execution. Gitee is selected only by
`china_mirror=True`; it is not an automatic fallback.

- [ ] **Step 4: Implement distinct download/integrity/execution cleanup results**

Ensure cleanup runs for every outcome and return stable codes without copying
opaque installer stderr into the result.

- [ ] **Step 5: Run installer tests**

```bash
python3 -m unittest enterprise-notification-bridge/tests/test_installer.py
```

Expected: PASS for approval, source allowlist, platform command, cleanup, and
post-install failure cases.

- [ ] **Step 6: Commit**

```bash
git add enterprise-notification-bridge/notification_bridge/installer.py \
  enterprise-notification-bridge/tests/test_installer.py
git commit -m "feat: add approved official dws installer"
```

### Task 3: Setup orchestration, CLI, and MCP continuation

**Files:**
- Modify: `enterprise-notification-bridge/notification_bridge/service.py`
- Modify: `enterprise-notification-bridge/notification_bridge/continuation.py`
- Modify: `enterprise-notification-bridge/notification_bridge/cli.py`
- Modify: `enterprise-notification-bridge/notification_bridge/mcp_server.py`
- Modify: `enterprise-notification-bridge/notification_bridge/providers/dws.py`
- Create: `enterprise-notification-bridge/tests/test_setup_workflow.py`
- Modify: `enterprise-notification-bridge/tests/test_cli.py`
- Modify: `enterprise-notification-bridge/tests/test_mcp_server.py`

**Interfaces:**
- Consumes: discovery, verification, and installer interfaces from Tasks 1-2.
- Produces: `BridgeService.setup_dependency(...)`, CLI `setup`, MCP `setup_notification_dependency`, and correlated dependency-install continuation actions.

- [ ] **Step 1: Write failing Provider-selection and setup tests**

```python
def test_native_provider_never_requests_dws_install(self):
    result = service.setup_dependency("dingtalk", "native", capabilities=native)
    self.assertEqual(result.reason, "native_provider_selected")
    self.assertEqual(installer.calls, [])

def test_auto_requests_install_only_when_native_is_unavailable(self):
    result = service.setup_dependency("dingtalk", "auto", capabilities={})
    self.assertEqual(result.status, "action_required")
    self.assertEqual(result.reason, "dependency_install_required")
```

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest enterprise-notification-bridge/tests/test_setup_workflow.py
```

Expected: failure because setup orchestration is absent.

- [ ] **Step 3: Implement idempotent service orchestration**

Sequence: select Provider boundary, discover, verify, return correlated install
action, accept approved installation result, re-discover, re-verify, then call
the existing auth/Profile binding workflow. Preserve all existing recipient and
first-send gates.

- [ ] **Step 4: Add CLI setup arguments**

Implement:

```text
setup --platform dingtalk --provider auto|native|dws-cli
      [--capabilities FILE] [--install-dws] [--china-mirror]
      [--device-login] [--yes]
```

Reject `--install-dws` without `--yes`. Emit exactly one JSON object.

- [ ] **Step 5: Add MCP setup tool and continuation correlation**

Add `setup_notification_dependency` to the MCP inventory. It must call the
same service method and persist the same action schema; do not implement a
second setup workflow in the MCP transport.

- [ ] **Step 6: Keep DWS leaf help gates and executable injection**

Update `DwsProvider` to receive the verified executable path while still
checking each exact leaf `--help` before JSON business execution.

- [ ] **Step 7: Run setup, CLI, MCP, DWS, and workflow tests**

```bash
python3 -m unittest \
  enterprise-notification-bridge/tests/test_setup_workflow.py \
  enterprise-notification-bridge/tests/test_cli.py \
  enterprise-notification-bridge/tests/test_mcp_server.py \
  enterprise-notification-bridge/tests/test_dws_provider.py \
  enterprise-notification-bridge/tests/test_workflow.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add enterprise-notification-bridge/notification_bridge \
  enterprise-notification-bridge/tests/test_setup_workflow.py \
  enterprise-notification-bridge/tests/test_cli.py \
  enterprise-notification-bridge/tests/test_mcp_server.py
git commit -m "feat: orchestrate dws dependency setup"
```

### Task 4: Detector integration and launcher behavior

**Files:**
- Modify: `wifi-health-detector/wifi_health/notification.py`
- Modify: `wifi-health-detector/tests/test_notification.py`
- Modify: `enterprise-notification-bridge/run.sh`
- Modify: `enterprise-notification-bridge/run.ps1`
- Modify: `enterprise-notification-bridge/tests/test_launchers.py`

**Interfaces:**
- Consumes: Bridge dependency statuses from Task 3.
- Produces: non-blocking detector handling and launcher forwarding for setup.

- [ ] **Step 1: Write failing detector non-blocking tests**

```python
def test_dependency_install_required_never_changes_detector_stdout(self):
    completed = run_cli_with_bridge_result("dependency_install_required")
    self.assertEqual(completed.returncode, 0)
    self.assertEqual(completed.stdout, expected_standard_report)
```

- [ ] **Step 2: Write failing launcher forwarding tests**

Assert POSIX and PowerShell launchers forward `setup`, mirror, device-login, and
approval arguments without evaluating them in a shell.

- [ ] **Step 3: Run and verify RED**

```bash
python3 -m unittest \
  wifi-health-detector/tests/test_notification.py \
  enterprise-notification-bridge/tests/test_launchers.py
```

Expected: setup/dependency assertions fail.

- [ ] **Step 4: Implement minimal detector and launcher behavior**

Keep install attention outside stdout. Do not invoke installation from the
detector. Preserve `--no-notify`, report identity, and exit code.

- [ ] **Step 5: Run focused tests**

Run the command from Step 3. Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add wifi-health-detector/wifi_health/notification.py \
  wifi-health-detector/tests/test_notification.py \
  enterprise-notification-bridge/run.sh \
  enterprise-notification-bridge/run.ps1 \
  enterprise-notification-bridge/tests/test_launchers.py
git commit -m "feat: expose non-blocking dws setup workflow"
```

### Task 5: Documentation, validation, and gated real-environment test

**Files:**
- Modify: `enterprise-notification-bridge/SKILL.md`
- Modify: `enterprise-notification-bridge/README.md`
- Modify: `wifi-health-detector/SKILL.md`
- Modify: `wifi-health-detector/README.md`
- Create: `enterprise-notification-bridge/references/DWS-SETUP.md`
- Modify: `enterprise-notification-bridge/tests/test_agent_contracts.py`

**Interfaces:**
- Consumes: all prior runtime behavior.
- Produces: cross-Agent installation instructions and a manual live-test runbook.

- [ ] **Step 1: Add behavior-based Agent contract tests**

Exercise CLI `setup` with native, missing-DWS, declined-install, successful
fake-install, and expired-auth fixtures. Do not test documentation by grepping
phrases.

- [ ] **Step 2: Document conditional setup and approval boundaries**

Explain native-first selection, official sources, `--china-mirror`, first-use
login, organization selection, fixed-recipient configuration, non-blocking
detector behavior, and how to uninstall or independently upgrade DWS.

- [ ] **Step 3: Run complete automated verification**

```bash
python3 -m unittest discover -s wifi-health-detector/tests -p 'test_*.py'
python3 -m unittest discover -s enterprise-notification-bridge/tests -p 'test_*.py'
python3 -m compileall -q wifi-health-detector enterprise-notification-bridge
python3 /Users/hua/.codex/skills/.system/skill-creator/scripts/quick_validate.py wifi-health-detector
python3 /Users/hua/.codex/skills/.system/skill-creator/scripts/quick_validate.py enterprise-notification-bridge
git diff --check
```

Expected: all tests and validators pass; only platform-runtime tests may be
skipped when PowerShell or Windows is unavailable.

- [ ] **Step 4: Run gated real-environment preflight only after user approval**

Verify `dws --version`, `dws auth status --format json`, and
`dws profile list --format json`. Do not send a message until the user selects
an exact Profile and fixed recipient and approves the first send.

- [ ] **Step 5: Commit**

```bash
git add enterprise-notification-bridge wifi-health-detector \
  docs/superpowers/specs/2026-09-01-dws-cli-conditional-bootstrap-design.md \
  docs/superpowers/plans/2026-09-01-dws-cli-conditional-bootstrap.md
git commit -m "docs: complete conditional dws bootstrap workflow"
```
