"""Regression for the two read-path defects found against real vCenter 8.0.3.

Real vCenter differs from the offline SOAP fakes in two ways that made whole
read families fail on site:

1. 64-bit scalar fields (datastore summary.capacity/freeSpace, ISO fileSize,
   disk capacities) arrive as ``pyVmomi.VmomiSupport.long`` -- an ``int``
   subclass for which ``type(value) is int`` is False.
2. DatastoreBrowser task managed-object ids are session-scoped, e.g.
   ``session[52cbcdca-...]525c034d-...``, not the numeric ``task-N`` the fakes
   used.

These tests pin both contracts so the fakes cannot silently diverge again.
"""
import unittest
from types import SimpleNamespace as NS

from pyVmomi import VmomiSupport, vim

from vcenter_aiops.domain.models import OperationError

long = VmomiSupport.long


class ScalarTypeContractTests(unittest.TestCase):
    def test_inventory_scalar_accepts_pyvmomi_long(self):
        from vcenter_aiops.providers.vsphere.inventory import Inventory
        capacity = long(536_870_912_000)      # 500 GiB, as returned on site
        free = long(1024 * 1024 * 1024)
        self.assertIs(type(capacity), long)
        self.assertIsNot(type(capacity), int)
        self.assertEqual(Inventory._scalar(capacity), capacity)
        self.assertEqual(Inventory._scalar(free), free)

    def test_inventory_scalar_keeps_bool_distinct_from_int(self):
        from vcenter_aiops.providers.vsphere.inventory import Inventory
        self.assertIs(Inventory._scalar(True), True)
        self.assertIs(Inventory._scalar(False), False)
        self.assertEqual(Inventory._scalar(7), 7)
        self.assertIsNone(Inventory._scalar(None))

    def test_inventory_scalar_flattens_enum_like_string_subclass(self):
        from vcenter_aiops.providers.vsphere.inventory import Inventory

        class Enum(str):
            pass

        value = Enum("green")
        self.assertEqual(Inventory._scalar(value), "green")
        self.assertIs(type(Inventory._scalar(value)), str)

    def test_inventory_scalar_rejects_structured_objects(self):
        from vcenter_aiops.providers.vsphere.inventory import Inventory
        with self.assertRaises(OperationError) as error:
            Inventory._scalar(object())
        self.assertEqual(error.exception.code, "query_incomplete")

    def test_cache_primitives_accept_nested_long(self):
        from vcenter_aiops.infrastructure.cache import _primitives
        snapshot = {"items": [
            {"id": "datastore-1", "kind": "datastore", "name": "vsan",
             "summary.capacity": long(10_995_116_277_760),
             "summary.freeSpace": long(4_000_000_000), "unavailable": []}],
            "truncated": False}
        self.assertTrue(_primitives(snapshot))
        self.assertTrue(_primitives(long(1)))
        self.assertTrue(_primitives(True))
        self.assertFalse(_primitives(object()))

    def test_write_path_integer_helper_matches_real_types(self):
        from vcenter_aiops.providers.vsphere.devices import is_integer
        self.assertTrue(is_integer(long(536_870_912_000)))
        self.assertTrue(is_integer(1024))
        self.assertFalse(is_integer(True))
        self.assertFalse(is_integer(False))
        self.assertFalse(is_integer(None))
        self.assertFalse(is_integer(1.5))


class FakePropertyCollector:
    """Minimal PropertyCollector that serves one page of datastore records."""

    def __init__(self, objects):
        self._objects = objects
        self.cancelled = []

    def RetrievePropertiesEx(self, specSet=None, options=None):
        page = NS(objects=self._objects, token=None)
        self._objects = []
        return page

    def ContinueRetrievePropertiesEx(self, token=None):  # pragma: no cover
        return None

    def CancelRetrievePropertiesEx(self, token=None):
        self.cancelled.append(token)


def datastore_record(moid, name, capacity, free):
    # DynamicProperty-like entries; values use the real pyVmomi long type.
    def prop(name, val):
        return NS(name=name, val=val)
    return NS(obj=NS(_moId=moid),
              propSet=[prop("name", name),
                       prop("summary.capacity", capacity),
                       prop("summary.freeSpace", free)],
              missingSet=[])


class InventoryDatastoreReadTests(unittest.TestCase):
    def test_datastore_list_with_long_capacity_succeeds(self):
        from vcenter_aiops.providers.vsphere.inventory import Inventory
        collector = FakePropertyCollector([
            datastore_record("datastore-1", "vmfs-a", long(536_870_912_000), long(107_374_182_400)),
            datastore_record("datastore-2", "vsan", long(10_995_116_277_760), long(4_000_000_000)),
        ])
        view = vim.view.ContainerView("view-1", None)
        view.Destroy = lambda: None
        content = NS(
            rootFolder=vim.Folder("group-d1", None),
            viewManager=NS(CreateContainerView=lambda *a, **k: view),
            propertyCollector=collector)
        si = NS(RetrieveContent=lambda: content)
        inv = Inventory(si)
        result = inv.list("datastore", 100)
        self.assertFalse(result["truncated"])
        self.assertEqual(len(result["items"]), 2)
        first = result["items"][0]
        self.assertEqual(first["summary.capacity"], long(536_870_912_000))
        self.assertEqual(first["summary.freeSpace"], long(107_374_182_400))


class TaskIdentityContractTests(unittest.TestCase):
    SESSION_TASK_ID = "session[52cbcdca-1234-5678-9abc-def012345678]525c034d-1234-5678-9abc-def012345678"

    def test_accepts_real_session_task_id_and_legacy_numeric(self):
        from vcenter_aiops.providers.vsphere.datastores import valid_task_id
        self.assertTrue(valid_task_id("task-1"))
        self.assertTrue(valid_task_id(self.SESSION_TASK_ID))

    def test_rejects_injection_and_malformed_task_ids(self):
        from vcenter_aiops.providers.vsphere.datastores import valid_task_id
        for bad in ("task-", "Task-1", "task-1;reboot", "session[abc] x",
                    "../task-1", "", None, 123, "task-1\n"):
            self.assertFalse(valid_task_id(bad), repr(bad))

    def _browser_provider(self, task_id):
        from vcenter_aiops.providers.vsphere.datastores import Datastores
        files = [NS(path="installer.iso", fileSize=long(4 * 1024**3), modification=None)]
        task = NS(_moId=task_id,
                  info=NS(key=task_id, state="success",
                          result=NS(folderPath="[data] images/", file=files)))

        def search(**kwargs):
            return task

        ds = NS(name="data", summary=NS(accessible=True),
                browser=NS(SearchDatastore_Task=search,
                           SearchDatastoreSubFolders_Task=search))
        about = NS(instanceUuid="server-a")
        provider = Datastores(NS(_stub=None, RetrieveContent=lambda: NS(about=about)),
                              resolver=lambda _: ds)
        provider.task = lambda _: task
        return provider

    def test_observe_accepts_real_session_task_id(self):
        provider = self._browser_provider(self.SESSION_TASK_ID)
        receipt = provider.submit(provider.prepare("datastore-1", "images"))
        self.assertEqual(receipt["task_id"], self.SESSION_TASK_ID)
        data = provider.observe(receipt, 5)
        self.assertEqual(data["state"], "succeeded")
        self.assertEqual(data["items"][0]["name"], "installer.iso")
        self.assertEqual(data["items"][0]["size_bytes"], long(4 * 1024**3))

    def test_server_mismatch_still_rejected_before_task_read(self):
        provider = self._browser_provider(self.SESSION_TASK_ID)
        receipt = provider.submit(provider.prepare("datastore-1", "images"))
        provider.si.RetrieveContent = lambda: NS(about=NS(instanceUuid="server-b"))
        with self.assertRaises(OperationError) as error:
            provider.observe(receipt, 5)
        self.assertEqual(error.exception.code, "server_mismatch")

    def test_info_key_binding_still_rejects_swapped_task(self):
        provider = self._browser_provider(self.SESSION_TASK_ID)
        receipt = provider.submit(provider.prepare("datastore-1", "images"))
        # vCenter answers with a different task than the recorded one.
        other = NS(_moId=self.SESSION_TASK_ID,
                   info=NS(key="session[aaaaaaaa]bbbbbbbb", state="success",
                           result=NS(folderPath="[data] images/", file=[])))
        provider.task = lambda _: other
        with self.assertRaises(OperationError) as error:
            provider.observe(receipt, 5)
        self.assertEqual(error.exception.code, "task_identity_mismatch")


if __name__ == "__main__":
    unittest.main()
