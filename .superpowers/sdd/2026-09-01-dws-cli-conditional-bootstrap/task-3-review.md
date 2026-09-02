# Task 3 Scoped Code Review

**Review date:** 2026-09-02  
**Scope:** `77ab5de..630dd0f`  
**Decision:** **CHANGES REQUESTED**

## Re-review 1 — `aefce0f`

**Decision:** **CHANGES REQUESTED**

The original two reproductions are fixed:

- A newer `provider=auto` setup with a declared native capability deletes the
  older matching auto install action, and replay fails before DWS is touched.
- Dependency-ready and directly approved successful setup delete matching
  pending install actions, preventing the previously observed duplicate install.
- The install action now preserves `requested_provider`; continuation delegates
  back through the same setup selection boundary rather than forcing `dws-cli`.

One adjacent stale-action path remains.

### Important — Explicit native selection does not invalidate an older auto install action

The native branch returns at `service.py:88-91` without calling
`_delete_dependency_install_actions()`. Only the following `provider == "auto"`
native-capability branch invalidates the old auto action. Consequently:

1. An earlier `setup_dependency("dingtalk", "auto")` creates an install action.
2. A newer explicit `setup_dependency("dingtalk", "native", native_bundle)`
   returns `native_provider_selected` but leaves that auto action pending.
3. Continuing the old auto action uses its stored no-native capability snapshot
   and executes the DWS installer.

The adversarial probe reproduced one `install` call after the explicit native
selection. This leaves a stale cross-request action able to contradict the
newer provider decision and the invariant that native selection never causes a
DWS installation. When explicit native selection succeeds, invalidate pending
`requested_provider="auto"` install actions for that platform before returning.
Consider whether an explicit newer provider decision should also invalidate
other obsolete setup actions according to the intended last-request semantics.

Re-review verification:

- Focused setup/CLI/MCP/DWS/workflow/continuation suite: **77 passed**.
- Full Bridge suite: **214 passed, 1 skipped**.
- Original auto-to-auto stale-action probe: fixed by action invalidation.
- Original direct-install duplicate probe: covered and fixed.
- New auto-to-explicit-native stale-action probe: **reproduced installation**.

## Findings

### Important — A stale install action can bypass current `auto` selection and repeat installation

`_dependency_install_action()` persists only the normalized capabilities from the
request which originally created the action, and it records the action/context as
`provider=dws-cli` even when that request used `provider=auto`
(`service.py:145-170`).  The continuation path then unconditionally resumes with
`provider="dws-cli"`, the old capability snapshot, and `approved=True`
(`service.py:297-303`).  It therefore never re-evaluates the current host-native
capability boundary before executing the installer.

An adversarial probe demonstrated this sequence:

1. `setup_dependency("dingtalk", "auto")` creates an install action while no
   native capability is declared.
2. A later `setup_dependency("dingtalk", "auto", native_bundle)` correctly
   returns `native_provider_selected` without touching DWS.
3. Continuing the earlier action still calls discovery, the installer,
   rediscovery, and verification, and returns `ok`.

This violates the load-bearing rule that `auto` requests DWS only when native is
unavailable at the time the approved setup is executed, and permits an action
from an obsolete request state to cause an unnecessary external installation.
Preserve the original requested provider in correlated state and re-run the
selection boundary when continuing, or invalidate the pending action when a
newer setup resolves through native.

The same pending-action lifecycle also permits duplicate installation after a
direct approved setup: create an install action, then call setup directly with
`install_dws=True, approved=True`; the direct path installs successfully but
leaves the old pending action in the store.  Continuing that still-valid action
invokes the installer a second time.  The probe observed two `install` calls.
Successful direct setup must consume/invalidate matching pending install actions,
or the continuation must detect that DWS is already verified and complete
without executing the installer again.

## Checks that passed

- Native provider requests and non-DingTalk platforms return before DWS
  discovery/installation in the reviewed direct setup path.
- Direct installation requires both `install_dws` and the exact Boolean approval.
- Installation success is followed by rediscovery and verification.
- Operation-result schema validation correlates action ID, report ID, platform,
  provider, and operation; consumed continuation records reject ordinary replay.
- Setup does not select or configure recipients.
- `device_login` does not construct an undocumented DWS command.
- The verified executable is injected into `DwsProvider`, and business commands
  retain their per-leaf help gate.
- CLI setup emits through the existing single-JSON output boundary; MCP delegates
  through `BridgeCommands.setup()` to the same service.
- Stable reason codes are returned without installer stdout/stderr, credentials,
  organization data, recipients, or report contents.

## Verification evidence

- Focused Task 3/CLI/MCP/DWS/workflow suite: **68 passed**.
- Full Bridge suite: **211 passed, 1 skipped**.
- Adversarial stale-action probe: reproduced installation after a newer native
  `auto` selection.
- Adversarial duplicate-action probe: reproduced a second installer invocation
  by continuing a pending action after direct approved installation succeeded.
