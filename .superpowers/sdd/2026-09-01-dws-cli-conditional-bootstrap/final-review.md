# Final Whole-Branch Re-review: DWS CLI Conditional Bootstrap

**Review date:** 2026-09-02

**Scope:** baseline `035fecb` through verification commit `7bd9801`

**Fix commit:** `268cd8c`

**Verdict:** **PASS**

## Final assessment

The final fix resolves both Important and both Minor findings from the first
whole-branch review. No new Critical, Important, or Minor defect was found in
the changed dependency verification, provider-selection, device-login, test,
documentation, or validation surfaces.

The branch retains the required safety and product boundaries: native-capable
hosts do not install DWS; partial native setup capability falls back only under
`auto`; installation requires explicit approval and an exact official plan;
setup ends at authorization/Profile binding without selecting or sending to a
recipient; detector stdout remains the standardized report; and no ordinary
detector run downloads or executes DWS.

## Resolution of previous findings

### Important 1 — DWS JSON help parser: resolved

The parser now recognizes explicit positive parenthetical enum declarations
before removing unrelated parenthetical notes, and separately recognizes the
common Cobra `Output format:` declaration.

Fresh read-only adversarial probe:

```text
choices-parenthetical  True
one-of-parenthetical   True
cobra                  True
negative-parenthetical False
unavailable            False
jsonl                  False
no-json                False
negative-choice        False
cobra-jsonl             False
cobra-no-json           False
```

The accepted cases are:

- `--format <format> Output format (choices: text, json)`
- `--format <format> Output format (one of: text | json)`
- `--format string Output format: json|table|raw (default "json")`

Negative notes, unavailable JSON, `jsonl`, and `no-json` continue to fail
closed. The new focused tests also retain the earlier next-option, multiline,
annotation, and explanatory-boundary protections.

### Important 2 — Partial native setup capability: resolved

Native setup availability now requires all three operations: `auth_status`,
`login`, and `list_profiles`.

Under `provider=auto`, send-only or partial native descriptors continue into
the DWS dependency path. Under explicit `provider=native`, the same descriptor
returns `configured_provider_unavailable` without discovering or installing
DWS. Complete native setup capability remains native-first and does not touch
DWS.

### Minor 1 — `--device-login`: resolved

The local official DWS reference at
`/Users/hua/.agents/skills/dws/references/global-reference.md` explicitly
documents `dws auth login --device`.

The Bridge maps CLI `--device-login` and MCP `deviceLogin: true` to that exact
documented flag. The provider still checks the canonical `auth login --help`
leaf before JSON execution.

Fresh injected-provider probe confirms the authorization gate:

```text
authorized ok []
missing    ok [True]
```

Thus an already-authorized Profile does not call login and never adds
`--device`; a missing authorization performs one login with device mode and
then rechecks authorization. The direct DWS command-vector probe also confirms
normal login omits `--device` and device login adds it only to the business
login command.

### Minor 2 — whitespace validation: resolved

The trailing whitespace in the Task 2 and Task 3 review records was removed.
`git diff --check 035fecb..HEAD` now passes.

## Cross-module audit

- Conditional dependency: DWS remains conditional on DingTalk `dws-cli`; it is
  not a detector or native-provider dependency.
- Provider selection: complete native setup capability wins; partial native
  capability has the correct explicit-native and auto-fallback behavior.
- Approval/source trust: installation requires literal approval and accepts
  only exact official GitHub/Gitee plans; the China mirror is explicit.
- Execution/cleanup: scripts execute locally with `shell=False` from a private
  temporary directory; optional published checksum metadata is verified;
  cleanup and adapter failures return stable codes.
- Continuations/replay: correlated install actions are reused and invalidated;
  stale approval replay cannot reinstall after native selection or dependency
  readiness.
- Authorization/Profile: login runs only when missing or expired; device mode
  is scoped to that login; only Provider-returned Profiles may be bound.
- Recipient/send boundary: setup does not infer or configure a recipient and
  does not send a report.
- Detector privacy/stdout: only closed protocol statuses cross into detector
  diagnostics; unknown content becomes `bridge_failed`; standardized report
  stdout and detector success remain unchanged.
- Launchers/docs: setup flags are forwarded without shell evaluation, and the
  documentation matches native fallback, installer trust, device login,
  Profile selection, fixed-recipient, and zero-send live-test behavior.

## Fresh verification evidence

- Wi-Fi Health Detector: **52 passed, 1 skipped**.
- Enterprise Notification Bridge: **232 passed, 1 skipped**.
- Both Skill `quick_validate.py` checks: **passed**.
- `compileall` for both projects: **passed**.
- Python 3.7 grammar parse: **49 files passed**.
- `git diff --check 035fecb..HEAD`: **passed**.
- Worktree was clean before this review record was updated.

No real DWS download, installation, DingTalk login/QR flow, organization
query, recipient lookup, or message send was executed during re-review.
