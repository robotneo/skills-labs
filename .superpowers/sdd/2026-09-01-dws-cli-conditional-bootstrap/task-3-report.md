# Task 3 Report: DWS Setup Orchestration, CLI, and MCP

**Audit date:** 2026-09-02

## Scope completed

- Added one idempotent `BridgeService.setup_dependency(...)` orchestration
  boundary shared by CLI, MCP, and correlated continuation handling.
- Kept native providers and all non-DingTalk platforms outside the DWS
  discovery and installer path. `auto` selects a declared native DingTalk
  capability before considering DWS.
- Added missing/outdated dependency handling, explicit install approval,
  official-source plan selection, post-install rediscovery, post-install
  version/leaf verification, and verified executable injection.
- Added durable, correlated `install_dependency` actions. Repeated setup with
  the same platform/source choice reuses the existing pending action instead
  of producing duplicates. A successful correlated continuation delegates
  back to the same setup service.
- Reused the existing authorization and Profile-binding workflow after DWS is
  verified. Setup never selects or configures a recipient. Existing
  first-use/expired-login semantics remain authoritative.
- Added CLI `setup` with the planned platform/provider/capability/install,
  mirror, device-login, and approval flags. `--install-dws` without `--yes`
  is rejected and every CLI outcome remains one JSON document.
- Added MCP `setup_notification_dependency`, delegating through
  `BridgeCommands` to the same service and continuation store.
- Updated `DwsProvider` to accept a verified executable while preserving the
  exact per-leaf `--help` JSON-format gate.

## RED evidence

- The Task 3 setup suite was executed against pre-Task-3 commit `77ab5de` in
  an isolated temporary tree. All 11 setup tests errored because
  `BridgeService` did not accept dependency orchestration inputs and exposed
  no `setup_dependency` method.
- The host `/usr/bin/python3` could not start because the configured Xcode
  Command Line Tools path references a missing `xcrun`; all behavioral checks
  therefore used Codex's bundled offline Python runtime.

## GREEN and verification evidence

- Focused setup/CLI/MCP/DWS/workflow suite: 68 tests passed.
- Full Bridge suite: 211 tests passed, with 1 existing conditional skip.
- `compileall` passed for all Bridge Python source and tests.
- Every Bridge Python file parsed with
  `ast.parse(..., feature_version=(3, 7))`.
- `manifest.json` parsed successfully.
- `git diff --check` passed.

## Self-review and risks

- Installation cannot execute from setup unless both the install request and
  exact Boolean approval are present. Native and non-DingTalk requests return
  before discovery, verification, plan creation, download, or execution.
- The setup action contains only public dependency metadata; it contains no
  token, organization, Profile, recipient, or report contents.
- `device_login` is carried consistently through CLI/MCP but remains reserved
  for the existing DWS login continuation surface because the provider must
  not invent an undocumented DWS argument.
- The provider runner is intentionally reused for Task 1 verification, then
  the verified absolute executable is injected for business leaves. The
  per-leaf help gate still executes before every previously unconfirmed leaf.
- Task 1's parked help-parser compatibility issue was not modified. Task 4
  detector/launcher integration and Task 5 documentation/live preflight were
  not started.

## Review fix: stale install-action lifecycle

- Added the original requested provider (`auto` or `dws-cli`) to the correlated
  install action. Continuation now resumes through that original selection
  boundary instead of forcing `dws-cli`.
- A newer successful `auto` selection through a declared native DingTalk
  capability invalidates the older matching install action before returning;
  replay is rejected as a missing/consumed pending action and never reaches DWS
  discovery or installation.
- Once DWS is verified ready—whether it became available externally, was
  installed by a directly approved setup, or was installed by continuation—all
  pending DingTalk DWS install actions are invalidated before authorization.
  Replaying an older approval therefore cannot execute the installer again.
- TDD RED evidence: the native-selection and direct-install regression tests
  both failed because the old pending action remained present. The existing
  dependency-ready continuation test stayed green and was retained to prove
  that an externally satisfied dependency consumes the action without calling
  the installer.
- Focused Task 3/CLI/MCP/DWS/workflow/continuation suite: 77 tests passed.
- Full Bridge suite: 214 tests passed, with 1 existing conditional skip.
- All 34 Bridge Python files parsed with Python 3.7 grammar; `compileall` and
  `git diff --check` passed.
