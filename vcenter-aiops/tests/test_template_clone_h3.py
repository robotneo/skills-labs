"""H-3: template_clone must normalise dangling MoRefs before the write.

deploy clone-template was the one placement path still reading raw lazily-
constructed MoRefs without the shared ``mor.existing`` envelope. A stale
template/folder/pool/host/datastore/network id therefore surfaced as an
internal_error (5) on its first server-side property read instead of a
deterministic *_not_found (4). These tests pin the contract:

* resolve + the first evidence fetch live in one probe, so an *injecting*
  resolver that raises MONF at construction is normalised too;
* a MONF naming the requested id (or no id) -> structured *_not_found/4;
* a MONF naming any *other* object is re-raised, never swallowed;
* a malformed id stays a client error (2), the resolver is never called;
* in submit's pre-write guarantee scope a stale template is a
  SubmissionRejected (4), never uncertainty (6), and CloneVM_Task is not called.
"""
import unittest

from pyVmomi import vim, vmodl

from vcenter_aiops.domain.models import OperationError, SubmissionRejected
from vcenter_aiops.providers.vsphere.template_clone import TemplateClone
from test_template_clone import BASE, CloneFixture


_WSDL = {
    "folder": ("Folder", vim.Folder),
    "pool": ("ResourcePool", vim.ResourcePool),
    "host": ("HostSystem", vim.HostSystem),
    "datastore": ("Datastore", vim.Datastore),
    "network": ("Network", vim.Network),
    "vm": ("VirtualMachine", vim.VirtualMachine),
}


def _ref_cls(kind, object_id):
    if kind == "network" and str(object_id).startswith("dvportgroup-"):
        return vim.dvs.DistributedVirtualPortgroup
    return _WSDL[kind][1]


def _stale_class(kind, object_id, fault_id):
    """Build a subclass of the real SDK type whose fetches raise MONF.

    Subclassing the actual pyVmomi type keeps construction-time metadata
    (``_wsdlName`` / isinstance identity used by Clusters._id) truthful, while
    any property requiring a round-trip raises ManagedObjectNotFound exactly as a
    concurrently deleted object does on a real stub.
    """
    base = _ref_cls(kind, object_id)
    fault_ref = base(fault_id, None)

    def __getattr__(self, name):
        raise vmodl.fault.ManagedObjectNotFound(obj=fault_ref)

    cls = type("Stale" + base.__name__, (base,), {"__getattr__": __getattr__})
    return cls


def StaleObject(kind, object_id, fault_id=None):
    return _stale_class(kind, object_id,
                        object_id if fault_id is None else fault_id)(object_id, None)


def _monf(kind, object_id, fault_id=None):
    ref_cls = _WSDL[kind][1]
    return vmodl.fault.ManagedObjectNotFound(
        obj=ref_cls(object_id if fault_id is None else fault_id, None))


def make_provider(fx, *, stale=(), raising=(), vm_flip_stale=False):
    """Return a TemplateClone whose resolver can fault for chosen kinds.

    stale/raising are kinds (always) or (kind, id) tuples. ``raising`` models an
    injecting resolver that throws MONF at construction; ``stale`` returns a
    lazily-resolved object whose first read throws. vm_flip_stale makes the
    template healthy on the first resolve (preview) then dangling (submit).
    """
    state = {"vm_resolves": 0}

    def hit(spec, kind, object_id):
        return kind in spec or (kind, object_id) in spec

    def resolver(kind, object_id):
        if kind == "vm" and object_id == "vm-1" and vm_flip_stale:
            state["vm_resolves"] += 1
            if state["vm_resolves"] > 1:
                return StaleObject("vm", object_id)
        if hit(raising, kind, object_id):
            raise _monf(kind, object_id)
        if hit(stale, kind, object_id):
            return StaleObject(kind, object_id)
        return fx.resolve(kind, object_id)

    return TemplateClone(fx.si, resolver=resolver)


class TemplateCloneDanglingMorTests(unittest.TestCase):
    def setUp(self):
        self.fx = CloneFixture()

    def preflight(self, provider, **over):
        p = dict(BASE)
        p.update(over)
        return provider.preflight("deploy clone-template", p), p

    # -- lazy resolver: MONF fires on the first property read ---------------
    def test_stale_template_lazy_read_is_vm_not_found_4(self):
        provider = make_provider(self.fx, stale=("vm",))
        with self.assertRaises(OperationError) as ctx:
            provider.preflight("deploy clone-template", dict(BASE))
        self.assertEqual(ctx.exception.code, "vm_not_found")
        self.assertEqual(ctx.exception.exit_code, 4)
        self.assertEqual(self.fx.stub.calls, [])

    def test_stale_placement_objects_are_structured_not_found(self):
        cases = [
            ("folder", "folder_not_found", {}),
            ("pool", "resource_pool_not_found", {}),
            ("datastore", "datastore_not_found", {}),
            ("host", "host_not_found", {}),
            ("network", "network_not_found", {"network_id": "network-1"}),
            ("network", "network_not_found", {"network_id": "dvportgroup-1"}),
        ]
        for kind, code, over in cases:
            fx = CloneFixture()
            provider = make_provider(fx, stale=(kind,))
            with self.subTest(kind=kind):
                with self.assertRaises(OperationError) as ctx:
                    provider.preflight("deploy clone-template", dict(BASE, **over))
                self.assertEqual(ctx.exception.code, code)
                self.assertEqual(ctx.exception.exit_code, 4)
                self.assertEqual(fx.stub.calls, [])

    # -- injecting resolver: MONF raised at construction --------------------
    def test_injecting_resolver_construction_monf_is_normalised(self):
        provider = make_provider(self.fx, raising=("vm",))
        with self.assertRaises(OperationError) as ctx:
            provider.preflight("deploy clone-template", dict(BASE))
        self.assertEqual(ctx.exception.code, "vm_not_found")
        self.assertEqual(ctx.exception.exit_code, 4)

    def test_injecting_resolver_placement_construction_monf(self):
        provider = make_provider(self.fx, raising=("folder",))
        with self.assertRaises(OperationError) as ctx:
            provider.preflight("deploy clone-template", dict(BASE))
        self.assertEqual(ctx.exception.code, "folder_not_found")
        self.assertEqual(ctx.exception.exit_code, 4)

    # -- fail-closed: a fault for another object must never be swallowed -----
    def test_monf_naming_other_object_is_reraised(self):
        other = StaleObject("folder", "group-v1", fault_id="group-v777")

        def resolver(kind, object_id):
            if kind == "folder":
                return other
            return self.fx.resolve(kind, object_id)

        provider = TemplateClone(self.fx.si, resolver=resolver)
        with self.assertRaises(vmodl.fault.ManagedObjectNotFound):
            provider.preflight("deploy clone-template", dict(BASE))

    # -- malformed ids stay client errors; resolver untouched ---------------
    def test_malformed_ids_are_exit2_without_resolve(self):
        seen = []

        def resolver(kind, object_id):
            seen.append((kind, object_id))
            return self.fx.resolve(kind, object_id)

        provider = TemplateClone(self.fx.si, resolver=resolver)
        with self.assertRaises(OperationError) as ctx:
            provider.preflight("deploy clone-template", dict(BASE, vm_id="vmtwo"))
        self.assertEqual(ctx.exception.exit_code, 2)
        with self.assertRaises(OperationError) as ctx:
            provider.preflight("deploy clone-template", dict(BASE, folder_id="folder-x"))
        self.assertEqual(ctx.exception.exit_code, 2)
        # Every resolve so far was the healthy vm-1; no malformed id resolved.
        self.assertTrue(all(oid != "folder-x" for _, oid in seen))

    # -- submit guarantee scope: stale -> SubmissionRejected/4, no write ----
    def test_submit_stale_template_is_rejected_not_unknown(self):
        provider = make_provider(self.fx, vm_flip_stale=True)
        binding, p = self.preflight(provider)  # first resolve healthy
        with self.assertRaises(SubmissionRejected) as ctx:
            provider.submit("deploy clone-template", p, binding)
        self.assertEqual(ctx.exception.code, "vm_not_found")
        self.assertEqual(ctx.exception.exit_code, 4)
        # The single write call must never have been issued.
        self.assertEqual([c for c in self.fx.stub.calls if c[1] == "CloneVM_Task"], [])

    def test_healthy_path_still_succeeds_after_envelope(self):
        provider = make_provider(self.fx)
        binding, p = self.preflight(provider)
        provider.submit("deploy clone-template", p, binding)
        self.assertEqual(self.fx.stub.calls[0][1], "CloneVM_Task")


if __name__ == "__main__":
    unittest.main()
