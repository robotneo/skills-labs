"""Shared dangling-ManagedObjectReference (MoRef) normalisation.

pyVmomi constructs a lazily-resolved MoRef without contacting vCenter; the first
property read is what forces a fetch. When the underlying object has been
deleted concurrently (or the id is stale), that read raises
``vmodl.fault.ManagedObjectNotFound``. Before a write this is a *deterministic*
precondition failure and must surface as a structured ``*_not_found`` error with
exit code 4 -- never as a top-level internal_error (5) or a misleading
"unknown result" (6).

Fail-closed exact-object rule (same precedent as
``clusters._existing_cluster`` / ``hosts._existing_host``): only a fault whose
``obj`` names the *requested* id is rewritten. A fault naming any other object
is re-raised so unrelated failures are never silently swallowed. Post-write
(observe/verify/cancel) evidence expiry is handled by the callers as unknown/6,
not here.
"""
from ...domain.models import fail


def existing(probe, object_id, code, message):
    """Run one controlled fetch; normalise a dangling MoRef to structured failure.

    ``probe`` is a zero-argument callable performing the property read that must
    round-trip to vCenter (e.g. ``lambda: obj.name``). Its return value is
    passed through on success so callers can chain the first read.

    A ``ManagedObjectNotFound`` whose missing object id equals ``object_id``
    (or whose fault carries no resolvable id) becomes ``fail(code, message, 4)``;
    a fault for a different object propagates untouched.
    """
    from pyVmomi import vmodl
    try:
        return probe()
    except vmodl.fault.ManagedObjectNotFound as fault:
        missing = getattr(getattr(fault, "obj", None), "_moId", None)
        if object_id is None or missing in (object_id, None):
            fail(code, message, 4)
        raise


def check_privileges(content, entity, required, *, denied, unable,
                     session_code="session_missing", session_exit=3,
                     session_message="服务端会话不可用"):
    """Fail-closed proof that the current session holds every required privilege.

    Single shared implementation for every write/preview path (OVF import, host
    maintenance, cluster/VM/template/guest operations). Mechanism is identical
    everywhere: resolve the current session key and the authorization manager
    defensively (a half-initialised fake/real ``content`` must never authorise by
    accident), call ``HasPrivilegeOnEntity`` once for the exact entity, and accept
    only a sequence of the same length whose every element is literally ``True``.

    Anything short of positive proof fails closed:
      * missing/blank session key  -> ``session_code`` (default session_missing/3);
        clusters historically folds this into permission_denied/4, preserved via
        the ``session_*`` overrides;
      * missing/non-callable check -> permission_denied/4 with ``unable``;
      * wrong shape/count/any False -> permission_denied/4 with ``denied``.
    """
    session = getattr(getattr(content, "sessionManager", None), "currentSession", None)
    session_key = getattr(session, "key", None)
    if not isinstance(session_key, str) or not session_key:
        fail(session_code, session_message, session_exit)
    manager = getattr(content, "authorizationManager", None)
    check = getattr(manager, "HasPrivilegeOnEntity", None)
    if not callable(check):
        fail("permission_denied", unable, 4)
    required = list(required)
    granted = check(entity=entity, sessionId=session_key, privId=required)
    if (not isinstance(granted, (list, tuple))
            or len(granted) != len(required)
            or not all(g is True for g in granted)):
        fail("permission_denied", denied, 4)
