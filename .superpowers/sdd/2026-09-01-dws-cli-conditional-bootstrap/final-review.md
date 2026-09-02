# Final Whole-Branch Review: DWS CLI Conditional Bootstrap

**Review date:** 2026-09-02

**Scope:** `035fecb..5d7146b`

**Verdict:** **CHANGES REQUESTED**

## Summary

The branch preserves the major safety boundaries: ordinary detector delivery
never installs software, installation needs explicit approval, only exact
official GitHub/Gitee plans execute, downloaded scripts run locally with
`shell=False`, temporary files are cleaned up, setup stops at Profile binding,
and the detector keeps the standardized report on stdout while suppressing
Bridge details. The two full test suites pass.

Two load-bearing contract defects remain. The parked Task 1 help parser defect
is reproducible and rejects common valid DWS/Cobra declarations. In addition,
`provider=auto` treats any DingTalk native descriptor as setup-capable even
when it lacks the authorization/Profile operations needed by setup, preventing
the required DWS fallback.

## Critical

None.

## Important

### 1. Valid JSON-capable DWS help is rejected

`enterprise-notification-bridge/notification_bridge/dependencies.py:194`
removes every parenthetical region before parsing declarations. It therefore
deletes explicit positive declarations such as `(choices: text, json)` and
`(one of: text | json)`. The parser also rejects the common Cobra form
`Output format: json|table|raw (default "json")` because `Output format:` is
not recognized as a value declaration.

Read-only adversarial probe results:

```text
choices-parenthetical False
one-of-parenthetical  False
cobra                 False
negative-parenthetical False
unavailable           False
jsonl                 False
no-json                False
```

The negative cases correctly fail closed, but all three positive cases also
fail. Since `verify_dws` applies this gate to `auth status`, `auth login`, and
`profile list`, a valid DWS installation can remain permanently stuck at
`dependency_verification_failed`. Add explicit positive tests for the three
forms above and preserve rejection of `(no json support)`, `json unavailable`,
`jsonl`, and `no-json`.

### 2. Partial native capabilities incorrectly suppress the DWS fallback

`enterprise-notification-bridge/notification_bridge/service.py:85-95`
defines native availability as the presence of any DingTalk capability
descriptor, without checking whether it advertises the operations setup needs
(`auth_status`, `login`, and `list_profiles`). A descriptor that advertises
only `send_report` returns `ready/native_provider_selected` and performs no DWS
discovery:

```text
ready native_provider_selected []
```

That native provider cannot complete authorization or Profile binding, while
the design requires `auto` to request DWS only after native capability is
absent or unavailable. Treat native setup as available only when the required
setup operation set is present. For explicit `provider=native`, return the
stable unavailable result when those operations are incomplete; for `auto`,
continue into the DWS dependency path. Add both regression cases.

## Minor

### 1. `--device-login` is accepted but discarded

`enterprise-notification-bridge/notification_bridge/service.py:75-80`
immediately deletes `device_login`. The public CLI/MCP flag therefore has no
observable effect. If DWS login has no documented alternate argument, remove
the flag from the public contract or document it as reserved; otherwise carry
the requested mode through the correlated authorization action without
inventing an undocumented DWS command.

### 2. Whole-branch whitespace validation is not clean

`git diff --check 035fecb..HEAD` reports trailing whitespace in:

- `.superpowers/sdd/2026-09-01-dws-cli-conditional-bootstrap/task-2-review.md`
- `.superpowers/sdd/2026-09-01-dws-cli-conditional-bootstrap/task-3-review.md`

Remove the trailing spaces before merge.

## Cross-module boundary audit

- Conditional install/provider selection: native and non-DingTalk paths avoid
  installation; the partial-native availability defect above remains.
- Approval and continuation replay: direct installation requires literal
  approval, correlated install actions are reused/invalidated, and stale replay
  is rejected.
- Source trust and execution: only exact official GitHub/Gitee plans pass;
  downloaded scripts execute from a private local directory with `shell=False`;
  Gitee fallback is disabled; optional checksum metadata is verified.
- Cleanup and error containment: installer adapter/property failures map to
  stable reasons; persistent cleanup failure overrides success.
- Authorization/Profile/recipient boundary: setup rechecks authorization,
  logs in only when needed, binds only Provider-returned Profiles, and does not
  resolve or send to recipients.
- Detector stdout/privacy: Bridge statuses use a closed allowlist; unknown or
  malformed values become `bridge_failed`; report stdout and detector success
  are preserved; detector invokes only `deliver` and never setup/install.
- Launchers/docs: POSIX forwarding is behaviorally tested; conditional
  PowerShell coverage exists; documentation describes the actual mutable
  official installer-script trust boundary and a zero-send live preflight.

## Verification evidence

- Wi-Fi detector: **52 tests passed, 1 skipped**.
- Enterprise Notification Bridge: **223 tests passed, 1 skipped**.
- Both Skill `quick_validate.py` checks: **passed**.
- `compileall` for both projects: **passed**.
- Python 3.7 grammar parse: **49 files passed**.
- `git diff --check 035fecb..HEAD`: **failed** only for the four trailing-space
  lines listed above.
- No real DWS download, installation, login/QR flow, organization query,
  recipient lookup, or message send was performed.

