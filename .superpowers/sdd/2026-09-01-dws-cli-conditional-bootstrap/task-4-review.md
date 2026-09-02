# Task 4 Independent Review

**Review date:** 2026-09-02
**Original range:** `4cedc78..9ccb51e`
**Re-review fix:** `8fba1fe`
**Current decision:** **PASS**

## Findings

### Important — untrusted Bridge `status` can still leak secrets and inject stderr lines

`wifi_health.notification._result_from_process()` accepts every string-valued
`status` from the Bridge response and stores it unchanged. `NotificationResult.message`
then writes that unvalidated value to the detector diagnostic. Removing `reason`
therefore does not establish the stated stable, non-sensitive stderr contract:
the same provider/Profile/organization/token material can be returned in `status`,
and a newline creates additional diagnostic lines.

Affected code:

- `wifi-health-detector/wifi_health/notification.py:38-41`
- `wifi-health-detector/wifi_health/notification.py:166-182`

Adversarial end-to-end probes through the detector produced:

```text
status = "token=secret-profile"
stderr = "Enterprise notification: token=secret-profile\n"

status = "dependency_install_required\norg=secret"
stderr = "Enterprise notification: dependency_install_required\norg=secret\n"
```

Both runs preserved exit code `0` and the report stdout, but violated the
privacy and stable-code requirement. Map Bridge statuses through an explicit
allowlist (or an equivalently closed protocol validator) and convert any
unknown/malformed value to one stable local code such as `bridge_failed`.
Add regression cases for unknown, whitespace-padded, newline-bearing, and
secret-bearing status strings.

### Minor — Windows forwarding claim is not behaviorally tested

The only Windows-specific forwarding assertion searches source text for `%*`
and `@ForwardedArgs`. When PowerShell is available, the runtime test forwards
only `--help`; it does not verify setup arguments containing empty values,
spaces, quotes, or shell metacharacters. Thus the report's claim that Windows
forwards all arguments safely is not established by the suite.

Affected tests:

- `enterprise-notification-bridge/tests/test_launchers.py:77-85`
- `enterprise-notification-bridge/tests/test_launchers.py:133-146`

Add a PowerShell runtime capture test parallel to the POSIX test, including the
full setup flag set and adversarial argument values. It may remain conditionally
skipped on hosts without PowerShell, but should execute on Windows/PowerShell CI.

## Requirement checks

- Standard Markdown stdout: exact equality passes for all documented dependency,
  upgrade, and authorization statuses.
- Detector non-blocking policy: exit code remains `0` for the tested Bridge
  attention and failure outcomes.
- `--no-notify`: existing test confirms no Bridge invocation and no fallback.
- Detector operation boundary: implementation invokes only `deliver`; no setup,
  installation, authentication, or recipient workflow is called.
- POSIX launcher: adversarial NUL-delimited capture preserved spaces, quotes,
  globs, dollar/backtick text, semicolon text, and the full setup flag vector;
  the marker command was not executed.
- PowerShell launcher: no `Invoke-Expression` or string-command construction is
  present, but exact adversarial runtime forwarding was not executable on this
  host and is not covered by the current conditional test.

## Verification evidence

Using `/Users/hua/.local/bin/python3.12` because `/usr/bin/python3` is blocked by
the host's missing Xcode Command Line Tools `xcrun`:

- Focused Task 4 suite: **26 passed, 1 skipped**.
- Full Wi-Fi detector suite: **51 passed, 1 skipped**.
- Full Enterprise Notification Bridge suite: **218 passed, 1 skipped**.
- Python 3.7 AST parse: **49 Python files passed**.
- `compileall`: passed for both projects.
- `sh -n enterprise-notification-bridge/run.sh`: passed.
- `git diff --check 4cedc78..9ccb51e`: passed.
- PowerShell runtime checks: unavailable (`pwsh`/Windows PowerShell absent).

The Important status-validation finding blocked the original Task 4 revision.

## Scoped re-review — round 1

Commit `8fba1fe` resolves the blocking finding and the adjacent Windows test gap.

### Status-boundary result

- The detector now accepts only a closed set of Bridge delivery protocol codes.
- Unknown, whitespace-padded, newline/tab/escape-bearing, secret-bearing, and
  non-string status values map to the stable local `bridge_failed` diagnostic.
- Rejected status and reason values are not included in stderr.
- Documented dependency/upgrade/authorization statuses remain visible as their
  stable codes, while `delivered` remains silent.
- The detector continues to exit `0` and preserves the standardized Markdown
  stdout exactly for both accepted and rejected Bridge statuses.

Additional adversarial probes covered JSON arrays and objects, including
`["dependency_install_required"]` and `{"code":"delivered"}`. They produced
only `Enterprise notification: bridge_failed`, did not leak the synthetic
secret reason, preserved stdout, and exited `0`.

### Launcher-test result

- The conditional PowerShell test now captures the actual argument vector.
- It covers the full setup flag set, an empty recipient value, spaces, embedded
  quotes, and PowerShell/shell metacharacters.
- The host has no PowerShell runtime, so this behavior test was skipped locally;
  its conditional form will execute on PowerShell/Windows CI.
- The production launcher still uses the call operator with argument arrays and
  contains no dynamic expression or string-command execution.

### Fresh verification

Using `/Users/hua/.local/bin/python3.12` because the host `/usr/bin/python3`
still depends on the unavailable Xcode Command Line Tools `xcrun`:

- Focused Task 4 suite: **27 passed, 1 skipped**.
- Full Wi-Fi detector suite: **52 passed, 1 skipped**.
- Full Enterprise Notification Bridge suite: **218 passed, 1 skipped**.
- Python 3.7 AST parse: **49 files passed**.
- `compileall`: passed for both projects.
- POSIX launcher syntax validation: passed.
- `git diff --check c82cd85..8fba1fe`: passed.

No Critical, Important, or Minor findings remain within the scoped Task 4
re-review. **Task 4 is approved.**
