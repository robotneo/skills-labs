# Task 3 Scoped Code Review

**Review date:** 2026-09-02  
**Scope:** `77ab5de..630dd0f`  
**Decision:** **CHANGES REQUESTED**

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

