# Task 1 Report: DWS Dependency Discovery and Version Contract

**Audit date:** 2026-09-01
**Implementation commit:** `daefe84` (`feat: declare and verify conditional dws dependency`)
**Review fix commit:** `45a2aa9` (`fix: harden dws dependency verification`)
**Review fix round 2:** `2352b67` (`fix: bound dws json help parsing`)
**Review fix round 3:** `4fc1cab` (`fix: parse multiline dws format help`)

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
3. Leaf-help contract test:
   `test_leaf_help_rejects_json_mentioned_as_unsupported`. Before the fix,
   help text containing `--format` plus `json is unsupported` incorrectly
   produced `dependency_ready`.
4. Strict SemVer test:
   `test_numeric_prerelease_identifier_rejects_leading_zero`. Before the fix,
   `1.0.16-01` incorrectly passed verification instead of returning
   `dependency_version_unsupported`.
5. Windows discovery-order test:
   `test_windows_candidates_use_windows_paths_in_documented_order`. Before
   the fix, candidate paths were built with the test host's POSIX path module,
   so no expected Windows candidate was discovered.
6. Metadata mutation check: after adding direct manifest and `skill.yaml`
   contract tests, the conditional requirement sections were temporarily
   removed. Both tests failed because `dingtalk:dws-cli` was absent. The
   original metadata was then restored and both tests passed.
7. Structured help-boundary tests:
   `test_leaf_help_does_not_cross_semicolon_into_json_explanation` and
   `test_leaf_help_does_not_cross_sentence_into_unrelated_json_text`. Before
   the round 2 fix, both adversarial help strings incorrectly produced
   `dependency_ready` because the regular expression consumed arbitrary text
   through the end of the line.
8. Multiline option-block tests:
   `test_leaf_help_accepts_choices_on_indented_continuation_line` and
   `test_leaf_help_accepts_multiline_allowed_values_and_default_fields` failed
   before the round 3 fix because continuation fields were ignored.
   `test_leaf_help_rejects_json_only_inside_parenthetical_note` also failed
   because JSON mentioned only in `(no json support)` was incorrectly counted
   as a choice value.

## GREEN and verification evidence

Final verification used the bundled offline Python runtime because the host's
default `python3` currently fails through a missing Xcode Command Line Tools
`xcrun` path.

Commands/results:

- `python3 -m unittest enterprise-notification-bridge/tests/test_dependencies.py enterprise-notification-bridge/tests/test_dws_provider.py`
  — 40 tests passed.
- Parsed both changed Python files with `ast.parse(..., feature_version=(3, 7))`
  — Python 3.7 syntax accepted.
- Parsed `manifest.json` with the standard-library `json` module — accepted.
- `git diff --check` — no whitespace errors.

## Self-review and risks

- The minimum version is exactly `1.0.15`; `1.0.14` and `1.0.15-rc.1` require
  upgrade, while later stable versions pass.
- Version output must be a JSON object containing a valid semantic-version
  string. Free-form version output and numeric prerelease identifiers with
  leading zeroes are rejected.
- Leaf help is parsed into bounded regions belonging to the `--format` option:
  its immediate `<...>` or `[...]` value set, or labeled `allowed values`,
  `choices`, `one of`, `values`, or `default` fields. Field parsing stops at
  semicolons, sentence boundaries, or bracket boundaries, so unrelated later
  mentions of JSON cannot satisfy the gate. Common choices, inline value-set,
  and default-value help forms are covered by positive tests.
- Multiline help is parsed as a small option block. Continuation lines must be
  more deeply indented than the `--format` start line; collection stops at a
  blank line, the next option, or a same/lower-indented section. Parenthetical
  notes are removed before labeled fields are tokenized by punctuation,
  whitespace, and quoting, so only an independent `json` value is accepted.
- Windows candidates use `ntpath` and are tested in the documented order:
  current `PATH`, user-local paths, roaming npm, then the declared npm prefix.
- Both metadata files have direct tests proving Python stays unconditional and
  DWS `>=1.0.15` stays conditional on `dingtalk:dws-cli`.
- Absolute executable references must be executable regular files. A bare
  command name remains accepted as the platform-resolved-command form allowed
  by the design.
- Discovery is dependency-injected through `which` and performs no subprocess,
  network, or install operation.
- The host `python3` toolchain issue is environmental and was not modified.
- Task 2+ behavior (installer planning, setup orchestration, MCP/CLI exposure,
  and detector integration) remains intentionally unimplemented.
