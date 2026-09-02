# Task 5 Review: Documentation, Validation, and Gated Live Test

**Review date:** 2026-09-02

**Initial reviewed commit:** `4263a7f9777eef90781144a4652670812492311f`

**Re-reviewed fix commit:** `2cce4fa26b4bbdb1330de5243409d36374c83837`

**Final verdict:** **PASS**

## Findings

### Important — Documentation calls the mutable `main` installer a release and overstates artifact validation

`enterprise-notification-bridge/README.md:59` says the default source is an
official DingTalk GitHub *release*, and
`enterprise-notification-bridge/references/DWS-SETUP.md:39-43` repeats that
description and says the installer validates the planned artifact. The runtime
actually downloads `install.sh` or `install.ps1` from the repository's mutable
`main/scripts` path (`notification_bridge/installer.py:11-18`). With the
production `UrlDownloader`, no checksum receipt is supplied, so execution
validates the fixed official plan/URL and downloaded-file boundary but does not
cryptographically validate the downloaded bytes.

This makes the operator-facing trust statement stronger and different from the
implemented boundary. Describe it as the official repository installer script
from the pinned allowlisted URL, not a release artifact, and state precisely
that checksum validation occurs only when integrity metadata is available. If
the product requirement truly is a release artifact with mandatory integrity
verification, the runtime must change in an earlier implementation task rather
than documenting behavior it does not provide.

### Minor — The PowerShell example is not directly runnable from a normal current directory

`enterprise-notification-bridge/references/DWS-SETUP.md:32-33` uses
`run.ps1 ...`. PowerShell normally does not search the current directory for
commands, so the documented local launcher form should be `./run.ps1 ...` (or
`.\\run.ps1 ...` on Windows). The batch example is unaffected.

## Requirement audit

- The five new setup tests call the real CLI parser and `BridgeCommands.setup`,
  then traverse the real `BridgeService.setup_dependency` flow. Native,
  missing-DWS, declined approval, fake successful installation, and expired
  authorization are all covered behaviorally rather than only by prose grep.
- Native setup proves no dependency discovery or installation. Missing and
  declined paths prove no installer invocation. The successful fake install
  proves rediscovery and verification before Profile binding. Expired auth
  proves exactly one login before authorization recheck and binding.
- Setup ends in bind/Profile state and never calls recipient resolution or
  `send_report`. The live runbook explicitly stops before send and requires a
  separately approved exact Profile and fixed recipient. No real DWS command,
  login, organization query, recipient lookup, or message send was executed in
  this review.
- Native-first, GitHub/Gitee selection, approval, first-use/expired login,
  Profile selection, fixed-recipient-after-binding, detector non-blocking,
  detector-never-installs, independent lifecycle, cross-Agent use, and gated
  preflight boundaries are present. The source/integrity wording above must be
  corrected to match implementation.

## Fresh verification evidence

- Wi-Fi detector: 52 tests run, 1 platform skip, 0 failures.
- Enterprise Notification Bridge: 223 tests run, 1 platform skip, 0 failures.
- `compileall` passed for both projects.
- Both Skill `quick_validate.py` checks passed.
- Python 3.7 grammar parse passed for all 49 Python files.
- `git diff --check` passed before this review artifact was added.
- The pre-review worktree was clean.

## Scoped re-review round 1

The fix commit resolves every requested documentation issue:

- README, Skill instructions, and DWS setup reference now describe the actual
  official repository installer scripts at the fixed allowlisted
  `main/scripts` URLs instead of calling them release artifacts.
- The integrity boundary now matches `installer.py`: fixed source, plan, and
  downloaded-file checks are unconditional; SHA-256 is checked only when a
  download receipt supplies `expected_sha256`; the default URL downloader does
  not claim an unconditional checksum.
- The Windows PowerShell local-launcher example now uses `./run.ps1`.
- Adjacent lifecycle language now says official upgrade procedure rather than
  release procedure, and the Task 5 report records the corrected trust boundary.

The five behavior tests remain aligned with the documented setup flow and
continue to exercise the real CLI parser, `BridgeCommands`, and setup service.
The successful path ends at Profile binding. Recipient resolution and
`send_report` are not entered, while the runbook still requires a separate
approval naming the exact Profile and fixed recipient before any real send.

### Fresh re-review verification

- Wi-Fi detector: 52 tests run, 1 platform skip, 0 failures.
- Enterprise Notification Bridge: 223 tests run, 1 platform skip, 0 failures.
- `compileall` passed for both projects.
- Both Skill `quick_validate.py` checks passed.
- Python 3.7 grammar parse passed for all 49 Python files.
- `git diff --check` passed before this review update.
- The pre-review worktree was clean.
- No real DWS command, installation, login/QR flow, organization query,
  recipient lookup, or message send was executed.

Task 5 is approved.
