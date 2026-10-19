"""M-7 regression: linked.mount second-level fetches normalise dangling MoRefs.

``mount()`` proves source/target hosts can read-write every datastore in a linked
clone disk chain. After resolving the datastore it performs *second-level*
managed-property traversals that can independently raise ManagedObjectNotFound:

* iterating ``ds.host`` (the datastore's host mount list), and
* reading ``host.datastore`` for each required source/target host.

A reference that vanished between preview and submit is a deterministic
precondition failure (host_not_found / datastore_not_found, exit 4), not a raw
SDK fault surfacing as internal_error (5) or, worse, uncertainty after a later
write. A fault naming a *different* object must still propagate (fail closed).
"""
from types import SimpleNamespace as NS
import unittest

from pyVmomi import vim, vmodl

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.providers.vsphere import linked


def monf(kind, object_id):
    cls = {"host": vim.HostSystem, "datastore": vim.Datastore}[kind]
    return vmodl.fault.ManagedObjectNotFound(obj=cls(object_id, object()))


class RaisingHost:
    """HostSystem-like object whose managed-property fetch goes dangling."""

    def __init__(self, host_id):
        self._moId = host_id

    @property
    def datastore(self):
        raise monf("host", self._moId)


class RaisingDatastore:
    def __init__(self, datastore_id):
        self._moId = datastore_id
        self.summary = NS(accessible=True, maintenanceMode="normal", type="VMFS")

    @property
    def host(self):
        raise monf("datastore", self._moId)


class HealthyDatastore:
    def __init__(self, host_id):
        self._moId = "datastore-1"
        self.summary = NS(accessible=True, maintenanceMode="normal", type="VMFS")
        self.host = [NS(key=NS(_moId=host_id),
                        mountInfo=NS(accessible=True, mounted=True,
                                     accessMode="readWrite"))]


class HealthyHost:
    def __init__(self, host_id, datastore_id):
        self._moId = host_id
        self.datastore = [NS(_moId=datastore_id)]


class FakeProvider:
    server_uuid = "server-1"

    def __init__(self, ds):
        self._ds = ds
        self.priv_called = False

    def resolver(self, kind, oid):
        return self._ds

    def privileges(self, entity, privs):
        self.priv_called = True


class LinkedMountMonfTests(unittest.TestCase):
    def test_stale_required_host_datastore_is_host_not_found(self):
        ds = HealthyDatastore("host-1")
        provider = FakeProvider(ds)
        stale_host = RaisingHost("host-1")
        with self.assertRaises(OperationError) as raised:
            linked.mount(provider, "datastore-1", [stale_host])
        self.assertEqual(raised.exception.code, "host_not_found")
        self.assertEqual(raised.exception.exit_code, 4)
        self.assertFalse(provider.priv_called)  # rejected before privilege gate

    def test_stale_datastore_host_list_is_datastore_not_found(self):
        ds = RaisingDatastore("datastore-1")
        provider = FakeProvider(ds)
        host = HealthyHost("host-1", "datastore-1")
        with self.assertRaises(OperationError) as raised:
            linked.mount(provider, "datastore-1", [host])
        self.assertEqual(raised.exception.code, "datastore_not_found")
        self.assertEqual(raised.exception.exit_code, 4)
        self.assertFalse(provider.priv_called)

    def test_fault_naming_other_host_propagates(self):
        # ds.host carries a mount entry whose traversal faults on a DIFFERENT
        # host than the one mount() is proving: that must not be rewritten.
        class OtherHostMount:
            @property
            def mountInfo(self):
                raise monf("host", "host-999")

            key = NS(_moId="host-1")

        ds = NS(_moId="datastore-1",
                summary=NS(accessible=True, maintenanceMode="normal", type="VMFS"),
                host=[OtherHostMount()])
        provider = FakeProvider(ds)
        host = HealthyHost("host-1", "datastore-1")
        with self.assertRaises(vmodl.fault.ManagedObjectNotFound):
            linked.mount(provider, "datastore-1", [host])
        self.assertFalse(provider.priv_called)

    def test_healthy_mount_passes_and_checks_privileges(self):
        ds = HealthyDatastore("host-1")
        provider = FakeProvider(ds)
        host = HealthyHost("host-1", "datastore-1")
        linked.mount(provider, "datastore-1", [host])
        self.assertTrue(provider.priv_called)


if __name__ == "__main__":
    unittest.main()
