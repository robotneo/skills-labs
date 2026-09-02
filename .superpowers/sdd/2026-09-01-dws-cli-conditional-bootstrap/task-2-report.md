# Task 2 Report: Approved Official DWS Installer

**Audit date:** 2026-09-02
**Implementation commit:** `07c89da` (`feat: add approved official dws installer`)

## Scope completed

- Added immutable `DwsInstallPlan`, `DownloadReceipt`, and
  `DwsInstallResult` contracts.
- Added fixed macOS, Linux, and Windows plans for the official DWS project.
  macOS/Linux execute a downloaded local `install.sh` with `sh`; Windows
  executes a downloaded local `install.ps1` with PowerShell `-File`.
- Added explicit GitHub and Gitee source selection. Gitee is used only when
  `china_mirror=True`; the execution environment disables the upstream
  installer's automatic mirror fallback and removes inherited source-selector
  overrides before applying the selected official source.
- Required explicit approval before any temporary directory, download, or
  process activity.
- Downloaded installers are stored under a private mode-`0700` temporary
  directory and executed with `shell=False`. Symbolic-link installer payloads
  are rejected.
- Added optional published SHA-256 verification through `DownloadReceipt`.
  Missing checksum metadata remains eligible for later post-install binary,
  version, and leaf-capability verification as specified by the design;
  malformed or mismatching published metadata fails closed.
- Added distinct stable outcomes for declined, download, integrity, and
  execution failures. Exceptions and process output are never copied into the
  result.
- Cleanup runs in `finally` for successful installation and every failure
  reached after temporary-directory creation.

## RED evidence

1. The initial focused test run failed with
   `ModuleNotFoundError: No module named 'notification_bridge.installer'`.
2. The symbolic-link payload test initially returned `dependency_ready`; it
   passed only after the installer rejected downloaded symlinks.
3. Official repository inspection showed the real entrypoints are
   `scripts/install.sh` and `scripts/install.ps1`. Three URL-path tests then
   failed against the original root-level URL construction and passed after
   the fixed allowlist was corrected.
4. Source-selection tests initially showed no execution-environment contract.
   They passed after GitHub plans set `DWS_NO_FALLBACK=1` and explicit Gitee
   plans additionally set the official `DWS_GITEE_REPO` value.
5. An inherited `DWS_GITEE_REPO=untrusted/fork` initially leaked into a GitHub
   plan's process environment. The test passed after inherited source selector
   variables were removed before applying the fixed plan.
6. A nonexistent temporary root initially raised `FileNotFoundError`. It now
   returns the stable `dependency_install_failed` result without downloading
   or executing.

## GREEN and verification evidence

The host's default `python3` remains unavailable because its Xcode Command Line
Tools path invokes a missing `xcrun`; verification used the bundled offline
Python 3.12 runtime.

- Focused installer suite: 16 tests passed.
- Full Bridge suite: 187 tests passed, with 1 existing conditional skip.
- `compileall` passed for Bridge source and tests.
- Both changed Python files parsed with
  `ast.parse(..., feature_version=(3, 7))`.
- `git diff --check` passed.
- Read-only upstream checks confirmed both fixed GitHub entrypoints and both
  matching official Gitee mirror entrypoints are currently accessible.

## Self-review and risks

- No remote script is piped to a shell or expression evaluator. The download
  boundary writes a local file before execution.
- The plan is revalidated against exact canonical plans before execution, so
  callers cannot substitute another URL, filename, command, environment, or
  source while retaining a trusted source label.
- Installer stdout/stderr, exceptions, report contents, Profiles, organization
  identifiers, tokens, and cookies are absent from `DwsInstallResult`.
- The official script URLs track the upstream `main` branch, matching the
  project's published installation entrypoints. The scripts internally verify
  downloaded release assets; Task 3 must still run Task 1's executable,
  version, and leaf-capability verification after installation before treating
  DWS as usable.
- This task intentionally does not add CLI/MCP setup orchestration, provider
  selection, detector integration, authorization, or Profile binding.

## Review remediation: round 1

The scoped Task 2 review identified three fail-closed boundary defects. They
were reproduced with tests before implementation changes:

- An object with attacker-controlled `__eq__` initially impersonated an
  official plan and reached download and execution.
- Non-Boolean truthy values such as `"false"` and `1` initially authorized
  installation.
- A cleanup exception initially escaped or could be ignored while a completed
  installer was reported ready; a mode-`000` private directory was also left
  behind by the old best-effort cleanup.

The remediation now requires the exact `DwsInstallPlan` type, validates every
canonical scalar, command, and environment value using exact built-in types,
and never invokes candidate-supplied equality. Approval is accepted only when
`approved is True`. Cleanup restores private-directory permissions, makes two
bounded removal attempts, and overrides any otherwise successful result with
the stable, non-sensitive `dependency_cleanup_failed` outcome if removal still
cannot be confirmed.

Post-remediation verification on 2026-09-02:

- Focused installer suite: 20 tests passed.
- Full Bridge suite: 191 tests passed, with 1 existing conditional skip.
- `compileall` passed for Bridge source and tests.
- Both changed Python files parsed with
  `ast.parse(..., feature_version=(3, 7))`.
- `git diff --check` passed.
