"""H-4 matrix: dangling MoRef normalisation across the remaining object types.

Every pre-write read of a well-formed but stale/deleted MoRef must surface as a
structured ``*_not_found`` failure with exit code 4, never internal_error (5).
The fail-closed exact-object rule is re-asserted: a ManagedObjectNotFound naming
a *different* object must propagate, and malformed ids stay exit 2.

Covers datastore browse prepare, vm reconfigure --disks datastore, placement
resources (pool/host/folder/ds), linked-clone mount, iso evidence task, ops
events entity / quota target, cluster-create folder, externally-deleted
snapshot node, and M-4 guest preflight vm.
"""
import json
import time
from types import SimpleNamespace as NS
import unittest

from pyVmomi import vim, vmodl

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.providers.vsphere import placement, linked, media, devices
from vcenter_aiops.providers.vsphere.datastores import Datastores
from vcenter_aiops.providers.vsphere.ops import OpsReads
from vcenter_aiops.providers.vsphere.mutations import Mutations
from vcenter_aiops.providers.vsphere.guest import Guest


def missing(mo_id):
    # A real fault object whose missing reference id we control precisely. The
    # fault.obj must be a pyVmomi ManagedObject, so snapshot refs use the managed
    # vim.vm.Snapshot type rather than a SimpleNamespace.
    prefix = mo_id.split("-", 1)[0] if "-" in mo_id else "task"
    cls = {"host": vim.HostSystem, "vm": vim.VirtualMachine, "folder": vim.Folder,
           "datastore": vim.Datastore, "pool": vim.ResourcePool,
           "cluster": vim.ClusterComputeResource, "task": vim.Task,
           "snapshot": vim.vm.Snapshot}.get(prefix, vim.Task)
    return vmodl.fault.ManagedObjectNotFound(obj=cls(mo_id, None))


class _Dangling:
    """Managed-object double whose first evidence fetch raises MONF."""

    def __init__(self, mo_id, fault_attr, fault_id=None, wsdl_name=None):
        self._moId = mo_id
        self._fault_attr = fault_attr
        self._fault_id = fault_id if fault_id is not None else mo_id
        self._wsdlName = wsdl_name if wsdl_name is not None else "VirtualMachine"

    def __getattr__(self, name):
        if name == self._fault_attr:
            raise missing(self._fault_id)
        raise AttributeError(name)


def _content():
    return NS(about=NS(instanceUuid="server-1", apiType="VirtualCenter", apiVersion="8.0.3"))


class DatastoreDanglingTests(unittest.TestCase):
    def test_browse_prepare_dangling_datastore_is_not_found(self):
        def resolver(oid):
            return _Dangling(oid, "summary")
        with self.assertRaises(OperationError) as error:
            Datastores(NS(RetrieveContent=_content, _stub=None), resolver=resolver).prepare("datastore-999999")
        self.assertEqual(error.exception.code, "datastore_not_found")
        self.assertEqual(error.exception.exit_code, 4)

    def test_browse_prepare_unrelated_fault_propagates(self):
        def resolver(oid):
            return _Dangling(oid, "summary", fault_id="datastore-777")
        with self.assertRaises(vmodl.fault.ManagedObjectNotFound):
            Datastores(NS(RetrieveContent=_content, _stub=None), resolver=resolver).prepare("datastore-999999")

    def test_browse_prepare_malformed_id_is_exit2(self):
        with self.assertRaises(OperationError) as error:
            Datastores(NS(RetrieveContent=_content, _stub=None)).prepare("ds-1")
        self.assertEqual(error.exception.exit_code, 2)

    def test_devices_datastore_dangling_is_not_found(self):
        provider = NS(resolver=lambda kind, oid: _Dangling(oid, "summary", wsdl_name="Datastore"))
        with self.assertRaises(OperationError) as error:
            devices.datastore(provider, None, "datastore-999999")
        self.assertEqual(error.exception.code, "datastore_not_found")
        self.assertEqual(error.exception.exit_code, 4)


class PlacementDanglingTests(unittest.TestCase):
    def test_each_placement_kind_has_structured_not_found(self):
        cases = [
            ("pool", "resgroup-999999", r"resgroup-\d+", "resource_pool_not_found"),
            ("host", "host-999999", r"host-\d+", "host_not_found"),
            ("folder", "group-v999999", r"group-v\d+", "folder_not_found"),
            ("datastore", "datastore-999999", r"datastore-\d+", "datastore_not_found"),
        ]
        for kind, oid, pattern, code in cases:
            with self.subTest(kind=kind):
                provider = NS(resolver=lambda k, o, _a="name": _Dangling(o, _a))
                with self.assertRaises(OperationError) as error:
                    placement.resource(provider, kind, oid, pattern)
                self.assertEqual(error.exception.code, code)
                self.assertEqual(error.exception.exit_code, 4)

    def test_placement_unrelated_fault_propagates(self):
        provider = NS(resolver=lambda k, o: _Dangling(o, "name", fault_id="host-777"))
        with self.assertRaises(vmodl.fault.ManagedObjectNotFound):
            placement.resource(provider, "host", "host-999999", r"host-\d+")

    def test_placement_malformed_id_is_exit2(self):
        provider = NS(resolver=lambda k, o: NS(_moId=o, name="x"))
        with self.assertRaises(OperationError) as error:
            placement.resource(provider, "host", "not-host", r"host-\d+")
        self.assertEqual(error.exception.exit_code, 2)

    def test_linked_mount_dangling_datastore_is_not_found(self):
        provider = NS(resolver=lambda kind, oid: _Dangling(oid, "summary"),
                      privileges=lambda entity, priv: None)
        with self.assertRaises(OperationError) as error:
            linked.mount(provider, "datastore-999999", ())
        self.assertEqual(error.exception.code, "datastore_not_found")
        self.assertEqual(error.exception.exit_code, 4)


class OpsDanglingTests(unittest.TestCase):
    def _ops(self, objects):
        provider = OpsReads(NS(RetrieveContent=lambda: NS(eventManager=None), _stub="stub"))
        provider._managed = lambda object_id: objects[object_id]
        return provider

    def test_events_dangling_entity_is_target_not_found(self):
        provider = self._ops({"vm-999999": _Dangling("vm-999999", "name")})
        with self.assertRaises(OperationError) as error:
            provider.events({"limit": 10, "vm_id": "vm-999999"})
        self.assertEqual(error.exception.code, "target_not_found")
        self.assertEqual(error.exception.exit_code, 4)

    def test_quota_dangling_target_is_target_not_found(self):
        for oid in ("host-999999", "domain-c999999", "datastore-999999"):
            with self.subTest(oid=oid):
                provider = self._ops({oid: _Dangling(oid, "summary")})
                key = {oid.startswith("host") and "host_id"
                       or oid.startswith("domain") and "cluster_id"
                       or "datastore_id": oid}
                with self.assertRaises(OperationError) as error:
                    provider.quota(key)
                self.assertEqual(error.exception.code, "target_not_found")
                self.assertEqual(error.exception.exit_code, 4)

    def test_quota_unrelated_fault_propagates(self):
        provider = self._ops({"host-999999": _Dangling("host-999999", "summary", fault_id="host-1")})
        with self.assertRaises(vmodl.fault.ManagedObjectNotFound):
            provider.quota({"host_id": "host-999999"})


class ClusterCreateFolderDanglingTests(unittest.TestCase):
    def _provider(self, missing_id):
        from test_cluster_lifecycle import ClusterFixture
        fixture = ClusterFixture()
        fault = vmodl.fault.ManagedObjectNotFound(obj=vim.Folder(missing_id, fixture))

        def resolve(kind, object_id):
            if kind == "folder" and object_id == "group-h999999":
                raise fault
            return fixture.resolve(kind, object_id)

        from vcenter_aiops.providers.vsphere.clusters import Clusters as RealClusters
        return RealClusters(fixture.si, resolver=resolve), fixture

    def test_create_with_dangling_folder_is_folder_not_found(self):
        provider, fixture = self._provider("group-h999999")
        with self.assertRaises(OperationError) as error:
            provider.preflight("cluster create", {"folder_id": "group-h999999", "name": "new"})
        self.assertEqual(error.exception.code, "folder_not_found")
        self.assertEqual(error.exception.exit_code, 4)
        self.assertEqual(fixture.calls, [])

    def test_create_folder_naming_other_object_fault_propagates(self):
        provider, fixture = self._provider("group-h1")
        with self.assertRaises(vmodl.fault.ManagedObjectNotFound):
            provider.preflight("cluster create", {"folder_id": "group-h999999", "name": "new"})
        self.assertEqual(fixture.calls, [])


class SnapshotNodeDeletedTests(unittest.TestCase):
    def test_snapshot_node_deleted_externally_is_not_found(self):
        snap_ref = NS(_moId="snapshot-9")

        class Node:
            def __init__(self):
                self.snapshot = snap_ref
            @property
            def childSnapshotList(self):
                raise missing("snapshot-9")
        vm = NS(snapshot=NS(rootSnapshotList=[Node()]))
        mut = Mutations.__new__(Mutations)
        with self.assertRaises(OperationError) as error:
            mut.snapshot(vm, "snapshot-9")
        self.assertEqual(error.exception.code, "snapshot_not_found")
        self.assertEqual(error.exception.exit_code, 4)

    def test_snapshot_node_fault_naming_other_object_propagates(self):
        snap_ref = NS(_moId="snapshot-9")

        class Node:
            snapshot = snap_ref
            @property
            def childSnapshotList(self):
                raise missing("snapshot-1")
        vm = NS(snapshot=NS(rootSnapshotList=[Node()]))
        mut = Mutations.__new__(Mutations)
        with self.assertRaises(vmodl.fault.ManagedObjectNotFound):
            mut.snapshot(vm, "snapshot-9")


class GuestPreflightDanglingVmTests(unittest.TestCase):
    def _guest(self, resolver):
        si = NS(RetrieveContent=lambda: _content(), _stub=None)
        return Guest(si, resolver=resolver)

    def test_preflight_dangling_vm_is_vm_not_found_not_unknown(self):
        def resolver(kind, oid):
            raise missing("vm-999999")
        provider = self._guest(resolver)
        with self.assertRaises(OperationError) as error:
            provider._identity({"vm_id": "vm-999999", "os_family": "linux"}, execute=True)
        self.assertEqual(error.exception.code, "vm_not_found")
        self.assertEqual(error.exception.exit_code, 4)

    def test_preflight_other_object_fault_propagates(self):
        def resolver(kind, oid):
            raise missing("vm-1")
        provider = self._guest(resolver)
        with self.assertRaises(vmodl.fault.ManagedObjectNotFound):
            provider._identity({"vm_id": "vm-999999", "os_family": "linux"}, execute=True)

    def test_malformed_vm_id_stays_exit2(self):
        provider = self._guest(lambda kind, oid: NS())
        with self.assertRaises(OperationError) as error:
            provider._identity({"vm_id": "not-vm", "os_family": "linux"}, execute=True)
        self.assertEqual(error.exception.exit_code, 2)


class MediaTaskDanglingTests(unittest.TestCase):
    def test_iso_evidence_dangling_search_task_is_task_not_found(self):
        now = time.time()
        meta = {"server_uuid": "server-1", "datastore_id": "datastore-1", "datastore_name": "ds"}
        row = {"id": 1, "created": now, "state": "succeeded",
               "scope": json.dumps(meta), "receipt": json.dumps({**meta, "task_id": "task-1"}),
               "result": json.dumps({**meta, "items": []})}

        def resolver(kind, oid):
            if kind == "task" and oid == "task-1":
                return _Dangling("task-1", "info")
            raise AssertionError((kind, oid))

        provider = NS(search_record=lambda search_id: row, server_uuid="server-1",
                      resolver=resolver)
        ds = NS(_moId="datastore-1", name="ds")
        params = {"search_id": 1, "path": "folder/image.iso"}
        with self.assertRaises(OperationError) as error:
            media.evidence(provider, params, ds)
        self.assertEqual(error.exception.code, "task_not_found")
        self.assertEqual(error.exception.exit_code, 4)


if __name__ == "__main__":
    unittest.main()
