# Task 2 Scoped Re-review

**Review date:** 2026-09-02  
**Fix commit:** `32db606`  
**Baseline review:** `b3470ca`  
**Verdict:** **CHANGES REQUESTED**

## Original findings

### Resolved: official-source allowlist equality bypass

The executor now requires `type(plan) is DwsInstallPlan` and compares every
canonical field using trusted built-in string/tuple comparisons. A deceptive
non-plan object whose `__eq__` always returns `True` is rejected before any
download or process call.

Adversarial result:

```text
status=failed reason=dependency_install_failed source=None
downloads=0 runs=0
```

### Resolved: weak approval typing

The gate now requires `approved is True`. The string `"false"`, integer `1`,
`None`, and collection values all decline without creating a temporary
directory, downloading, or executing.

### Resolved: silent cleanup failure

Cleanup now restores directory permissions, retries removal, and returns the
stable `dependency_cleanup_failed` result if the directory still exists.
Both the restrictive-directory probe and mocked persistent-removal failure are
covered by focused tests.

## New findings

### Critical

None.

### Important

1. **Malformed exact-type plans can still escape the stable failure contract.**

   `installer.py:163-169` calls `plan_dws_install(plan.platform, ...)` and
   catches only `TypeError` and `ValueError`. An exact `DwsInstallPlan` can
   contain a non-string platform value; `_platform_key()` then calls `.strip()`
   and raises `AttributeError`. The exception escapes
   `execute_dws_install()` instead of returning
   `dependency_install_failed`.

   Reproduction:

   ```python
   plan = DwsInstallPlan(1, "official-github", "x", "x", (), ())
   execute_dws_install(plan, True, downloader, runner, temp_root)
   # AttributeError: 'int' object has no attribute 'strip'
   ```

   This does not permit execution, but it breaks the installer boundary's
   fail-closed, stable-result behavior and can propagate through the future
   non-blocking setup workflow. Validate the platform field type before plan
   construction/comparison or contain all expected malformed-plan exceptions.
   Add exact-type malformed-field tests, not only deceptive-object tests.

2. **Checksum I/O failures leak raw exceptions instead of producing the stable integrity result.**

   `installer.py:113-120` calls `_file_sha256()` outside an exception boundary.
   If the downloaded file cannot be opened or read, `OSError` escapes with its
   original text. The temporary directory is cleaned, but callers receive no
   `DwsInstallResult`, and sensitive path/error text may propagate into upper
   layer logs.

   Read-only probe with `_file_sha256` raising
   `OSError("secret path")` produced:

   ```text
   RAISED OSError secret path
   remaining=[]
   ```

   Convert checksum-read failures to `dependency_integrity_failed` without
   copying exception text, and add a regression test. This is required by the
   Task 2 contract for distinct stable download/integrity/execution outcomes.

### Minor

None.

## Positive observations

- The exact official GitHub/Gitee URLs, explicit mirror selection, local-file
  execution, PowerShell `-File`, and `shell=False` behavior remain intact.
- The allowlist fix avoids candidate-defined equality at nested field levels,
  including string and tuple subclasses.
- Cleanup failures can no longer silently coexist with `dependency_ready`.
- Results continue to exclude installer stdout/stderr and caught exception
  text.

## Verification evidence

- Focused installer suite: **20 passed**.
- Full Bridge suite: **191 passed, 1 skipped**.
- `git diff --check b3470ca..32db606`: **passed**.
- Original adversarial probes: all three original findings are fixed.
- Adjacent malformed-plan and checksum-I/O probes reproduced the two Important
  findings above.

Task 2 is not ready to proceed until public installer inputs and integrity I/O
failures consistently return stable, non-leaking results.
