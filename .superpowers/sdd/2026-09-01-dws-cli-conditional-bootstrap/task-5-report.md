# Task 5 Report: Documentation, Validation, and Gated Live Test

**Audit date:** 2026-09-02

## Scope completed

- Added behavior-based CLI setup contract tests for the five required paths:
  native selection, missing DWS, declined installation, a successful fake
  installation, and expired authorization followed by one login and Profile
  binding.
- Documented the native-first Provider decision and the rule that DWS is a
  conditional DingTalk fallback, never a detector dependency.
- Documented the official DingTalk GitHub source and the explicitly selected
  official Gitee China mirror, including the approval gate and prohibition on
  download-to-shell pipelines and unofficial mirrors.
- Documented first-use/expired-only login, exact Profile selection, fixed
  recipient configuration after binding, and non-blocking detector behavior.
- Documented independent DWS upgrade/uninstall, cross-Agent use by Codex,
  Claude Code, WorkBuddy, OpenClaw, and compatible company Agents.
- Added a real-environment runbook whose default stopping point is verified
  setup with zero messages sent.

## Behavior verification

- `test_setup_cli_native_path_never_discovers_or_installs_dws` drives the real
  CLI parser and setup command adapter with a host-native capability file and
  proves dependency discovery and installation are untouched.
- `test_setup_cli_missing_dws_returns_install_action_without_installing` proves
  a correlated `install_dependency` action is emitted without installation.
- `test_setup_cli_declined_install_does_not_invoke_installer` proves
  `--install-dws` without `--yes` exits with
  `dependency_install_declined` before discovery or installation.
- `test_setup_cli_fake_install_rediscovers_verifies_and_binds` proves an
  approved fake install is followed by rediscovery, verification, and Profile
  binding in the expected order.
- `test_setup_cli_expired_auth_logs_in_once_before_profile_binding` proves an
  expired session logs in once, rechecks authorization, and binds the returned
  Profile.

## Automated verification evidence

- Wi-Fi detector suite: 52 tests run, 1 conditional skip, 0 failures.
- Enterprise Notification Bridge suite: 223 tests run, 1 conditional skip, 0
  failures.
- `compileall` passed for both projects.
- Both Skill `quick_validate.py` checks passed.
- All 49 Python files parsed with Python 3.7 grammar.
- `git diff --check` passed.
- The host `/usr/bin/python3` remains unusable because its Apple Command Line
  Tools proxy references a missing `xcrun`; verification used the installed
  offline Python 3.12 runtime at `/Users/hua/.local/bin/python3.12`.

## Gated real-environment preflight not executed

No DWS download or installation, DingTalk login/QR window, authorization
mutation, organization/Profile query, recipient resolution, or message send was
performed. Those external actions require explicit approval. The runbook asks
for approval in stages and requires a separately approved exact Profile and
fixed recipient before the first real send.

## Parked finding

Task 1's adjudicated help-parser compatibility finding was not changed. Task 5
only documents the supported fail-closed DWS command contract and does not
broaden the parser to accept hypothetical help grammar.
