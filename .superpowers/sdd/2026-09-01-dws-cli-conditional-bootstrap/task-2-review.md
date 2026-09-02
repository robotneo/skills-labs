# Task 2 Scoped Code Review

**Review date:** 2026-09-02  
**Scope:** `bef321b..9356902`  
**Primary files:** `notification_bridge/installer.py`, `tests/test_installer.py`  
**Verdict:** **CHANGES REQUESTED**

## Findings

### Critical

1. **The official-source allowlist is bypassable through attacker-controlled equality.**

   `installer.py:146-153` validates a supplied plan using
   `plan == github_plan or plan == gitee_plan`. The left operand is the
   caller-supplied object, so its `__eq__` implementation controls the answer.
   A non-`DwsInstallPlan` object can return `True` from `__eq__` while exposing
   an arbitrary URL, filename, command, and environment. The executor then
   downloads and runs that untrusted payload while returning
   `dependency_ready` with source `official-github`.

   Read-only adversarial probe result:

   ```text
   DwsInstallResult(status='ready', reason='dependency_ready', source='official-github')
   download_url= https://evil.invalid/payload.sh
   ran= True
   ```

   This defeats Task 2's central security boundary: only the exact official
   GitHub plan or explicitly selected official Gitee plan may execute. Require
   the exact trusted plan type and compare canonical field values from trusted
   operands; do not invoke equality supplied by the candidate object. Add a
   regression test with a deceptive `__eq__` implementation.

### Important

1. **The approval gate accepts arbitrary truthy values instead of explicit Boolean approval.**

   `installer.py:76-80` uses `if not approved`. Values such as the string
   `"false"` and integer `1` therefore authorize download and execution. A
   serialization or continuation-layer type mistake can silently turn a
   negative-looking value into software-execution approval.

   Probe result:

   ```text
   'false' dependency_ready 1 1
   1 dependency_ready 1 1
   ```

   The security contract says installation proceeds only after explicit user
   approval. Fail closed unless `approved is True`, and cover string, integer,
   `None`, and collection inputs.

2. **Cleanup failures are ignored while the result still reports success.**

   `installer.py:140-142` calls `shutil.rmtree(..., ignore_errors=True)` and
   cannot observe or report that the downloaded installer remains on disk.
   A runner that changes the private directory mode to `000` causes the
   function to return `dependency_ready` while leaving `dws-install-*` and the
   payload behind. This violates the design requirement that temporary
   installer files and directories are removed after success or failure.

   Probe result:

   ```text
   DwsInstallResult(status='ready', reason='dependency_ready', source='official-github')
   ['dws-install-wghjenz_']
   ```

   Make cleanup observable and fail closed with a stable result when cleanup
   cannot complete. A defensive permission restoration before removal may be
   needed because the executed installer controls its working directory.
   Add success-path and failure-path regression tests that deliberately make
   the directory initially non-removable.

### Minor

None.

## Positive observations

- Canonical plans use fixed official GitHub/Gitee URLs and explicit Gitee
  selection; there is no automatic mirror fallback in the plan contract.
- macOS/Linux use a downloaded local script, and Windows uses PowerShell
  `-File`; all runner calls explicitly pass `shell=False`.
- The public result excludes subprocess stdout/stderr and exception text.
- Existing tests cover private mode `0700`, symbolic-link rejection, optional
  checksum mismatch/malformed metadata, stable failure codes, and normal
  cleanup paths.

## Verification evidence

- Focused installer suite: **16 passed**.
- Full Bridge suite: **187 passed, 1 skipped**.
- `git diff --check bef321b..9356902`: **passed**.
- Three read-only adversarial probes reproduced the allowlist bypass, weak
  approval typing, and silent cleanup failure described above.

The passing suite does not make Task 2 acceptable because the critical
allowlist bypass permits arbitrary remote code execution through the exact
interface intended to enforce official-source installation.
