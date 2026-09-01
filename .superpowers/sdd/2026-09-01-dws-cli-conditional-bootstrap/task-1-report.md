# Task 1 Report: DWS Dependency Discovery and Version Contract

**Audit date:** 2026-09-02
**Implementation commit:** `daefe84` (`feat: declare and verify conditional dws dependency`)

## Scope completed

- Added immutable `DwsDependency` and `DependencyStatus` results.
- Added `discover_dws(environment, platform_name, which)` with the specified
  precedence: absolute `DWS_EXE`, current `PATH`, documented user-local paths,
  macOS Homebrew paths, then already-declared npm prefix paths.
- Added `verify_dws(executable, runner)` with minimum DWS version `1.0.15`,
  JSON-only version parsing, semantic-version threshold handling, executable
  path validation, and JSON capability gates for `auth status`, `auth login`,
  and `profile list`.
- Kept dependency discovery and verification read-only: no networking,
  downloading, package-manager invocation, or installation behavior exists in
  this module.
- Kept `python>=3.7` unconditional and declared
  `dingtalk:dws-cli: [dws>=1.0.15]` as conditional metadata in both manifests.

## Inherited WIP audit

The inherited worktree contained four uncommitted paths and they were all
preserved and reviewed:

- `notification_bridge/dependencies.py`
- `tests/test_dependencies.py`
- `manifest.json`
- `skill.yaml`

The inherited tests were already GREEN when first run (16 tests). No original
pre-implementation RED transcript was present, so the earlier agent's exact
test-first ordering cannot be independently proven from repository state.

Review found one specification gap in the inherited implementation: an
absolute executable path was passed to the runner without first proving that
it was an executable regular file. A new behavior test was added first, it was
observed failing, and the minimal path-validation implementation was then
added.

## RED evidence

1. Inherited test mutation check: temporarily moved only
   `notification_bridge/dependencies.py` outside the worktree and ran the
   focused test file. The suite failed with
   `ModuleNotFoundError: No module named 'notification_bridge.dependencies'`.
   The WIP module was immediately restored unchanged.
2. New executable-validation test:
   `test_nonexistent_absolute_executable_is_rejected_without_running_it`.
   Before implementation it failed because the result reason was
   `dependency_verification_failed` instead of `dws_executable_invalid`; the
   fake runner had been invoked when it should not have been.

## GREEN and verification evidence

Final verification used the bundled offline Python runtime because the host's
default `python3` currently fails through a missing Xcode Command Line Tools
`xcrun` path.

Commands/results:

- `python3 -m unittest enterprise-notification-bridge/tests/test_dependencies.py enterprise-notification-bridge/tests/test_dws_provider.py`
  — 29 tests passed.
- Parsed both changed Python files with `ast.parse(..., feature_version=(3, 7))`
  — Python 3.7 syntax accepted.
- Parsed `manifest.json` with the standard-library `json` module — accepted.
- `git diff --check` — no whitespace errors.

## Self-review and risks

- The minimum version is exactly `1.0.15`; `1.0.14` and `1.0.15-rc.1` require
  upgrade, while later stable versions pass.
- Version output must be a JSON object containing a valid semantic-version
  string. Free-form version output is rejected.
- Absolute executable references must be executable regular files. A bare
  command name remains accepted as the platform-resolved-command form allowed
  by the design.
- Discovery is dependency-injected through `which` and performs no subprocess,
  network, or install operation.
- The host `python3` toolchain issue is environmental and was not modified.
- Task 2+ behavior (installer planning, setup orchestration, MCP/CLI exposure,
  and detector integration) remains intentionally unimplemented.
