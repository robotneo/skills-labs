# Task 2 Scoped Re-review — Round 2

**Review date:** 2026-09-02  
**Fix commit:** `63a1be4`  
**Previous review:** `d259b92`  
**Verdict:** **CHANGES REQUESTED**

## Previous findings

### Resolved: malformed exact-type plan exception

`_is_official_plan()` now rejects a non-string platform before calling
`plan_dws_install()`. Tests also cover malformed source, URL, filename,
command, and environment fields. All malformed plans return the stable
`dependency_install_failed` result without downloading or executing.

### Resolved: checksum file-read exception

Checksum calculation is now inside an exception boundary. Hashing errors fail
closed as `dependency_integrity_failed`, do not execute the installer, do not
copy exception text, and clean the temporary directory.

### Regression status of earlier findings

- Deceptive candidate equality remains rejected.
- Only the literal Boolean `True` authorizes installation.
- Cleanup permission restoration and stable cleanup failure remain intact.

## New findings

### Critical

None.

### Important

1. **Adapter result-property exceptions still escape the stable, non-leaking boundary.**

   `execute_dws_install()` catches exceptions while invoking the downloader
   and process runner, but accesses attributes on their returned objects after
   those `try` blocks:

   - `installer.py:113`: `getattr(receipt, "expected_sha256", None)`
   - `installer.py:141`: `getattr(process_result, "returncode", 1)`

   A downloader receipt whose `expected_sha256` property raises causes the raw
   exception to escape instead of returning a download/integrity failure. A
   process result whose `returncode` property raises likewise escapes instead
   of returning `dependency_install_failed`. In both cases the exception text
   can reach upper-layer logs, contrary to the privacy contract.

   Read-only probes produced:

   ```text
   receipt RAISED RuntimeError receipt-secret
   process-result RAISED RuntimeError runner-secret
   ```

   Cleanup did run, but no `DwsInstallResult` was returned. Treat adapter
   invocation and validation of its returned value as one exception boundary,
   or require and validate an exact safe receipt/result shape before reading
   fields. Map receipt inspection failures to a stable download or integrity
   reason and process-result inspection failures to
   `dependency_install_failed`. Add regression tests that use raising
   properties and assert the secret text is absent.

### Minor

None.

## Positive observations

- Official GitHub/Gitee plan validation remains strict and candidate-defined
  equality is not invoked.
- The approval gate, private temporary directory, local-file execution,
  `shell=False`, PowerShell `-File`, checksum comparison, and cleanup behavior
  remain unchanged and correct under the covered paths.
- Existing stable results never include subprocess stdout/stderr or caught
  exception details.

## Verification evidence

- Focused installer suite: **22 passed**.
- Full Bridge suite: **193 passed, 1 skipped**.
- `git diff --check d259b92..63a1be4`: **passed**.
- Previous malformed-plan and checksum-I/O probes: **fixed**.
- New receipt-property and process-result-property probes: both reproduced the
  Important finding above; temporary directories were still cleaned.

Task 2 is not ready to proceed while injected downloader/runner result objects
can bypass stable error handling and expose raw exception text.
