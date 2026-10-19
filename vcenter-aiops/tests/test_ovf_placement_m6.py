"""M-6: read-only remote placement evidence for deploy ova/ovf previews.

A preview must surface every deterministic placement problem before any remote
write: stale folder/pool/host/datastore/network MoRefs (structured
*_not_found/4, not internal_error), cross-datacenter or incoherent placement,
host-invisible datastore/network, and missing per-entity privileges. None of
these checks may call CreateImportSpec / ImportVapp / acquire an HttpNfcLease.
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from pyVmomi import vmodl

from vcenter_aiops.domain.models import OperationError, SubmissionRejected
from vcenter_aiops.providers.vsphere.ovf_deploy import OvfDeploy
from test_ovf_deploy import (DESCRIPTOR, FakeSi, base_params, healthy_topology)


class _Dangling:
    """Managed-object whose first evidence fetch raises MONF for its own id."""

    def __init__(self, mo_id, fault_attr, fault_cls):
        self._moId = mo_id
        self._fault_attr = fault_attr
        self._fault_cls = fault_cls

    def __getattr__(self, name):
        if name == self._fault_attr:
            raise vmodl.fault.ManagedObjectNotFound(
                obj=self._fault_cls(self._moId, None))
        raise AttributeError(name)


class _Authz:
    def __init__(self, deny=(), missing=False):
        self.deny = set(deny)
        self.missing = missing
        self.calls = []

    def HasPrivilegeOnEntity(self, entity, sessionId, privId):
        privs = list(privId)
        self.calls.append((getattr(entity, "_moId", None), tuple(privs)))
        if self.missing:
            return None
        return [entity._moId not in self.deny] * len(privs)


class M6Harness(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.ovf_dir = root / "pkg"
        self.ovf_dir.mkdir()
        (self.ovf_dir / "descriptor.ovf").write_text(DESCRIPTOR, encoding="utf-8")
        (self.ovf_dir / "disk1.vmdk").write_text("diskbytes", encoding="utf-8")
        self.work = str(root / "work")

    def tearDown(self):
        self.temp.cleanup()

    def build(self, topology=None, authz=None, session="session-1"):
        topo = topology or healthy_topology()
        self.topo = topo
        self.si = FakeSi()
        if authz is not None:
            self.si.content.authorizationManager = authz
        if session is None:
            self.si.content.sessionManager = NS(currentSession=None)

        def resolver(kind, object_id):
            if kind == "vm":
                return NS(_moId="vm-100", config=NS(instanceUuid="x"),
                          runtime=NS(powerState="poweredOff"))
            return {
                "pool": topo["pool"], "host": topo["host"], "folder": topo["folder"],
                "datastore": topo["datastore"], "network": topo["network"],
            }[kind]

        provider = OvfDeploy(
            self.si, resolver=resolver,
            upload=lambda t, i: None,
            driver=lambda l, f, u, deadline=None: None,
            cisp_builder=lambda p, h, v: NS(networkMapping=list(v["network_mapping"])))
        return provider

    def params(self, **overrides):
        p = base_params(str(self.ovf_dir), self.work)
        p.update(overrides)
        return p

    def assert_preview_clean(self):
        # No CreateImportSpec and no ImportVApp happened during preview.
        self.assertEqual(self.si.ovf_manager.calls, [])
        self.assertEqual(self.topo["pool"].imports, [])


class TestStaleObjects(M6Harness):
    def _dangling(self, kind, object_id):
        from pyVmomi import vim
        if kind == "network":
            cls = vim.dvs.DistributedVirtualPortgroup if object_id.startswith("dvportgroup-") else vim.Network
            return _Dangling(object_id, "name", cls)
        attr = "summary" if kind == "datastore" else "name"
        cls = {"pool": vim.ResourcePool, "host": vim.HostSystem,
               "folder": vim.Folder, "datastore": vim.Datastore}[kind]
        return _Dangling(object_id, attr, cls)

    def test_stale_placement_ids_are_structured_not_found(self):
        cases = [
            ("pool", "resgroup-999999", "resource_pool_not_found", "resource_pool_id"),
            ("host", "host-999999", "host_not_found", "host_id"),
            ("folder", "group-v999999", "folder_not_found", "folder_id"),
            ("datastore", "datastore-999999", "datastore_not_found", "datastore_id"),
        ]
        for kind, oid, code, param in cases:
            with self.subTest(kind=kind):
                topo = healthy_topology()
                provider = self.build(topo)

                def resolver(k, i, _kind=kind, _oid=oid):
                    if k == "vm":
                        return NS(_moId="vm-100")
                    if k == _kind:
                        return self._dangling(_kind, _oid)
                    return {"pool": topo["pool"], "host": topo["host"],
                            "folder": topo["folder"], "datastore": topo["datastore"],
                            "network": topo["network"]}[k]
                provider.resolver = resolver
                with self.assertRaises(OperationError) as error:
                    provider.preflight("deploy ovf", self.params(**{param: oid}))
                self.assertEqual(error.exception.code, code)
                self.assertEqual(error.exception.exit_code, 4)
                self.assert_preview_clean()

    def test_stale_network_target_is_not_found(self):
        topo = healthy_topology()
        provider = self.build(topo)
        from pyVmomi import vim

        def resolver(k, i):
            if k == "vm":
                return NS(_moId="vm-100")
            if k == "network":
                return _Dangling("network-999999", "name", vim.Network)
            return {"pool": topo["pool"], "host": topo["host"], "folder": topo["folder"],
                    "datastore": topo["datastore"], "network": topo["network"]}[k]
        provider.resolver = resolver
        with self.assertRaises(OperationError) as error:
            provider.preflight("deploy ovf",
                                self.params(network_mapping={"VM Network": "network-999999"}))
        self.assertEqual(error.exception.code, "network_not_found")
        self.assertEqual(error.exception.exit_code, 4)
        self.assert_preview_clean()

    def test_resolver_raising_at_construction_is_normalized(self):
        from pyVmomi import vim
        topo = healthy_topology()
        provider = self.build(topo)

        def resolver(k, i):
            if k == "folder":
                raise vmodl.fault.ManagedObjectNotFound(
                    obj=vim.Folder("group-v777", None))
            return {"pool": topo["pool"], "host": topo["host"], "folder": topo["folder"],
                    "datastore": topo["datastore"], "network": topo["network"],
                    "vm": NS(_moId="vm-100")}[k]
        provider.resolver = resolver
        with self.assertRaises(OperationError) as error:
            provider.preflight("deploy ovf", self.params(folder_id="group-v777"))
        self.assertEqual(error.exception.code, "folder_not_found")
        self.assertEqual(error.exception.exit_code, 4)


class TestIncoherentPlacement(M6Harness):
    def test_cross_datacenter_folder_rejected(self):
        topo = healthy_topology()
        other_dc = NS(_moId="datacenter-2", _wsdlName="Datacenter", parent=None)
        topo["folder"].parent = other_dc
        provider = self.build(topo)
        with self.assertRaises(OperationError) as error:
            provider.preflight("deploy ovf", self.params())
        self.assertEqual(error.exception.code, "placement_invalid")
        self.assertEqual(error.exception.exit_code, 4)
        self.assert_preview_clean()

    def test_host_pool_compute_mismatch_rejected(self):
        topo = healthy_topology()
        other_compute = NS(_moId="domain-c8", _wsdlName="ClusterComputeResource",
                           parent=topo["dc"])
        topo["host"].parent = other_compute
        provider = self.build(topo)
        with self.assertRaises(OperationError) as error:
            provider.preflight("deploy ovf", self.params())
        self.assertEqual(error.exception.code, "placement_invalid")

    def test_disconnected_or_maintenance_host_rejected(self):
        for attr, value in (("connectionState", "disconnected"), ("inMaintenanceMode", True)):
            with self.subTest(attr=attr):
                topo = healthy_topology()
                setattr(topo["host"].runtime, attr, value)
                provider = self.build(topo)
                with self.assertRaises(OperationError) as error:
                    provider.preflight("deploy ovf", self.params())
                self.assertEqual(error.exception.code, "placement_invalid")

    def test_non_vm_folder_rejected(self):
        topo = healthy_topology()
        topo["folder"].childType = ["vim.Folder"]
        provider = self.build(topo)
        with self.assertRaises(OperationError) as error:
            provider.preflight("deploy ovf", self.params())
        self.assertEqual(error.exception.code, "placement_invalid")

    def test_inaccessible_or_maintenance_datastore_rejected(self):
        for attr, value in (("accessible", False), ("maintenanceMode", "enteringMaintenance")):
            with self.subTest(attr=attr):
                topo = healthy_topology()
                setattr(topo["datastore"].summary, attr, value)
                provider = self.build(topo)
                with self.assertRaises(OperationError) as error:
                    provider.preflight("deploy ovf", self.params())
                self.assertEqual(error.exception.code, "placement_invalid")

    def test_datastore_not_visible_to_host_rejected(self):
        topo = healthy_topology()
        topo["host"].datastore = []
        provider = self.build(topo)
        with self.assertRaises(OperationError) as error:
            provider.preflight("deploy ovf", self.params())
        self.assertEqual(error.exception.code, "placement_invalid")

    def test_network_not_visible_to_host_rejected(self):
        topo = healthy_topology()
        topo["host"].network = []
        provider = self.build(topo)
        with self.assertRaises(OperationError) as error:
            provider.preflight("deploy ovf", self.params())
        self.assertEqual(error.exception.code, "placement_invalid")


class TestPrivileges(M6Harness):
    def test_missing_privilege_is_denied(self):
        for denied in ("resgroup-1", "datastore-1", "group-v1", "network-1"):
            with self.subTest(denied=denied):
                provider = self.build(authz=_Authz(deny={denied}))
                with self.assertRaises(OperationError) as error:
                    provider.preflight("deploy ovf", self.params())
                self.assertEqual(error.exception.code, "permission_denied")
                self.assertEqual(error.exception.exit_code, 4)

    def test_privilege_checks_are_scoped_per_entity(self):
        authz = _Authz()
        provider = self.build(authz=authz)
        provider.preflight("deploy ovf", self.params())
        checked = {mo_id for mo_id, _ in authz.calls}
        self.assertEqual(checked, {"resgroup-1", "datastore-1", "group-v1", "network-1"})

    def test_no_session_is_local_state_error(self):
        provider = self.build(session=None)
        with self.assertRaises(OperationError) as error:
            provider.preflight("deploy ovf", self.params())
        self.assertEqual(error.exception.code, "session_missing")
        self.assertEqual(error.exception.exit_code, 3)


class TestPreviewSideEffects(M6Harness):
    def test_preview_creates_no_import_spec_or_lease(self):
        provider = self.build()
        binding = provider.preflight("deploy ovf", self.params())
        self.assertEqual(self.si.ovf_manager.calls, [])
        self.assertEqual(self.topo["pool"].imports, [])
        self.assertIn("placement", binding["scope"])

    def test_dvportgroup_target_is_verified(self):
        topo = healthy_topology()
        dvpg = NS(_moId="dvportgroup-2", name="Segment-B")
        topo["network"] = dvpg
        topo["host"].network = [dvpg]
        provider = self.build(topo)

        def resolver(k, i):
            if k == "network":
                return dvpg
            return {"pool": topo["pool"], "host": topo["host"], "folder": topo["folder"],
                    "datastore": topo["datastore"], "vm": NS(_moId="vm-100")}[k]
        provider.resolver = resolver
        binding = provider.preflight(
            "deploy ovf", self.params(network_mapping={"VM Network": "dvportgroup-2"}))
        self.assertEqual(binding["scope"]["placement"]["networks"]["dvportgroup-2"], "Segment-B")
        self.assertEqual(self.topo["pool"].imports, [])

    def test_placement_drift_between_preview_and_submit_is_stale(self):
        provider = self.build()
        binding = provider.preflight("deploy ovf", self.params())
        # Datastore becomes host-invisible after preview; submit re-runs preflight
        # and refuses with plan_stale before any remote write.
        self.topo["host"].datastore = []
        with self.assertRaises(SubmissionRejected) as error:
            provider.submit("deploy ovf", self.params(), binding)
        self.assertEqual(error.exception.code, "placement_invalid")
        self.assertEqual(self.topo["pool"].imports, [])


if __name__ == "__main__":
    unittest.main()
