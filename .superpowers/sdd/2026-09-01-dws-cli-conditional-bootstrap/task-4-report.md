# Task 4 Report: Detector Integration and Launcher Behavior

**Audit date:** 2026-09-02

## Scope completed

- Kept Wi-Fi detection report-first and non-blocking for every dependency,
  upgrade, authorization, and administrator-authorization attention status.
- Preserved the standardized Markdown report byte-for-byte on stdout and kept
  detector exit status at zero when notification setup needs attention.
- Stopped copying arbitrary Bridge reason text into detector diagnostics.
  stderr now contains only the stable Bridge status, preventing Profile,
  organization, token, or authorization context from leaking through a
  provider-supplied reason.
- Preserved `--no-notify`; the detector still never invokes Bridge setup or
  installation and only calls the existing `deliver` path.
- Kept POSIX and PowerShell launchers as argument-vector forwarding boundaries.
  POSIX disables pathname expansion and PowerShell snapshots the incoming
  argument array before invoking Python. Neither launcher uses dynamic shell
  evaluation or command-string construction.
- Added an executable POSIX regression test covering exact forwarding of
  `setup`, `--platform`, `--provider`, `--capabilities`, `--install-dws`,
  `--china-mirror`, `--device-login`, and `--yes`, including a shell metacharacter
  payload that must remain inert.

## RED evidence

- The focused Task 4 suite failed in all 10 dependency/authorization status
  subtests before the implementation change. Each failure showed the synthetic
  Profile/token/organization reason copied into stderr.
- The host `/usr/bin/python3` could not start because the configured Xcode
  Command Line Tools path references a missing `xcrun`; behavioral checks used
  Codex's bundled offline Python runtime.

## GREEN and verification evidence

- Focused notification/launcher suite: 26 tests passed, 1 conditional skip.
- Full Wi-Fi detector suite: 51 tests passed, 1 conditional skip.
- Full Enterprise Notification Bridge suite: 218 tests passed, 1 conditional
  skip.
- Every Python source file in both projects parsed with Python 3.7 grammar.
- `compileall` passed for both projects.
- POSIX launcher syntax validation passed.
- PowerShell runtime/parser validation was conditionally skipped because this
  macOS host has neither `pwsh` nor Windows PowerShell installed; static safety
  and forwarding assertions passed.
- `git diff --check` passed.

## Self-review and risks

- `NotificationResult.reason` remains available internally for programmatic
  handling, but the detector's human-readable diagnostic deliberately excludes
  it because the Bridge/provider boundary cannot guarantee that arbitrary
  reason text is non-sensitive.
- The standardized report rendering path was not changed. Tests compare stdout
  using exact string equality for every new attention status.
- No installer, setup service, authentication command, or recipient selection
  was added to the detector.
- `run.bat` already delegates all arguments to `run.ps1` and was outside Task 4's
  modification list; its existing forwarding assertion remains green.
- Task 1's parked help-parser compatibility issue and Task 5 documentation/live
  preflight were not modified.

## Review fix: stable status boundary and Windows argument coverage

- Added a closed allowlist for Bridge delivery status codes at the detector
  subprocess boundary. Unknown values, non-string values, whitespace-padded
  values, newline/tab/escape-bearing values, and other malformed formats now
  become the local `bridge_failed` code; the rejected value is never copied to
  stderr.
- Kept the detector contract unchanged: notification failures remain
  non-blocking, stdout remains the exact standardized report, and successful
  delivery/known attention codes retain their existing behavior.
- Replaced the PowerShell help-only runtime check with an exact argument capture
  test covering the full setup vector, spaces, embedded quotes, an empty value,
  and shell metacharacters. It runs when `pwsh` or Windows PowerShell is
  available and is conditionally skipped on this macOS host.

### Review-fix RED evidence

- The new adversarial detector test failed in six string-valued cases before
  the implementation change: unknown, secret-bearing, whitespace-padded,
  newline-bearing, space-separated, uppercase, and metacharacter statuses were
  written verbatim to stderr. Non-string cases were already fail-closed.

### Review-fix GREEN and verification evidence

- Focused notification/launcher suite: 27 tests passed, 1 conditional skip.
- Full Wi-Fi detector suite: 52 tests passed, 1 conditional skip.
- Full Enterprise Notification Bridge suite: 218 tests passed, 1 conditional
  skip.
- Python 3.7 AST parse: 49 Python files passed.
- `compileall` passed for both projects.
- POSIX launcher syntax validation and current-change `git diff --check` passed.
- Historical range `git diff --check 4cedc78..HEAD` still reports the two
  Markdown hard-break spaces already committed in `task-4-review.md`; this fix
  did not alter the independent review record.
