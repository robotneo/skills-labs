from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from pyVmomi import vim
import test_placement
import test_provider
from vcenter_aiops.application.execution import Engine
from vcenter_aiops.application.providers import ProviderRouter
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store


class TemplateTests(unittest.TestCase):
    def make(self, template=True):
        provider = test_placement.PlacementTests.make(self, template)
        ds = vim.Datastore("datastore-1", self.stub)
        self.stub.values[("vm-1", "datastore")] = [ds]
        self.stub.values[("datastore-1", "host")] = [NS(
            key=vim.HostSystem("host-1", self.stub),
            mountInfo=NS(accessible=True, mounted=True, accessMode="readWrite"))]
        return provider

    def test_template_filter_precedes_limit_and_continues_pages(self):
        def item(number, template):
            row = test_provider.InventoryTests.item(number)
            row.propSet.append(NS(name="config.template", val=template))
            return row
        inventory, collector = test_provider.InventoryTests.make(self, [
            NS(token="more", objects=[item(1, False)]),
            NS(token=None, objects=[item(2, True)])])
        with patch.object(vim.view.ContainerView, "Destroy"):
            result = inventory.list("template", 1)
        self.assertEqual([x["id"] for x in result["items"]], ["2"])
        self.assertEqual(result["items"][0]["kind"], "template")
        self.assertFalse(result["truncated"])

    def test_template_inspect_excludes_regular_vm(self):
        row = test_provider.InventoryTests.item(1)
        row.propSet.append(NS(name="config.template", val=False))
        inventory, _ = test_provider.InventoryTests.make(self, [NS(token=None, objects=[row])])
        with patch.object(vim.view.ContainerView, "Destroy"), self.assertRaises(OperationError) as error:
            inventory.resolve("template", object_id="1")
        self.assertEqual(error.exception.code, "target_not_found")

    def test_convert_uses_synchronous_method_and_verifies_identity_and_placement(self):
        provider = self.make()
        p = {"vm_id": "vm-1", "pool_id": "resgroup-1", "host_id": "host-1"}
        binding = provider.preflight("template convert", p)
        original = self.stub.InvokeMethod
        def invoke(obj, info, args):
            original(obj, info, args)
            self.stub.values[("vm-1", "config")].template = False
            self.stub.values[("vm-1", "resourcePool")] = vim.ResourcePool("resgroup-1", self.stub)
            return None
        self.stub.InvokeMethod = invoke
        receipt = provider.submit("template convert", p, binding)
        self.assertNotIn("task_id", receipt)
        self.assertEqual(self.stub.calls[0][1], "MarkAsVirtualMachine")
        self.assertEqual(self.stub.calls[0][2]["pool"]._moId, "resgroup-1")
        self.assertEqual(self.stub.calls[0][2]["host"]._moId, "host-1")
        self.assertTrue(provider.verify("template convert", p, binding, {}))
        self.stub.values[("vm-1", "config")].instanceUuid = "reused"
        self.assertFalse(provider.verify("template convert", p, binding, {}))

    def test_convert_rejects_vm_missing_privilege_or_stale_identity(self):
        for case in ("regular", "permission", "identity"):
            with self.subTest(case=case):
                provider = self.make(template=case != "regular")
                p = {"vm_id": "vm-1", "pool_id": "resgroup-1", "host_id": "host-1"}
                if case == "permission":
                    provider.content.authorizationManager.HasPrivilegeOnEntity = lambda **kw: [False] * len(kw["privId"])
                with self.assertRaises(OperationError) as error:
                    binding = provider.preflight("template convert", p)
                    self.stub.values[("vm-1", "config")].instanceUuid = "reused"
                    provider.submit("template convert", p, binding)
                self.assertEqual(error.exception.code, {"regular": "precondition_failed",
                    "permission": "permission_denied", "identity": "plan_stale"}[case])
                self.assertEqual(self.stub.calls, [])

    def test_template_unknown_flag_is_not_silently_reported_as_no_templates(self):
        row = test_provider.InventoryTests.item(1)
        row.missingSet = [NS(path="config.template")]
        inventory, _ = test_provider.InventoryTests.make(self, [NS(token=None, objects=[row])])
        with patch.object(vim.view.ContainerView, "Destroy"), self.assertRaises(OperationError) as error:
            inventory.list("template", 100)
        self.assertEqual(error.exception.code, "query_incomplete")

    def test_conversion_rejects_invalid_placement_before_remote_write(self):
        cases = ("pool_owner", "maintenance", "disconnected", "storage_missing", "storage_inaccessible",
                 "mount_readonly", "mount_unknown", "mount_unmounted", "mount_inaccessible", "network_missing", "pool_privilege")
        for case in cases:
            with self.subTest(case=case):
                provider = self.make()
                if case == "pool_owner":
                    self.stub.values[("resgroup-1", "owner")] = vim.ClusterComputeResource("domain-c2", self.stub)
                elif case == "maintenance":
                    self.stub.values[("host-1", "runtime")].inMaintenanceMode = True
                elif case == "disconnected":
                    self.stub.values[("host-1", "runtime")].connectionState = "disconnected"
                elif case == "storage_missing":
                    self.stub.values[("host-1", "datastore")] = []
                elif case == "storage_inaccessible":
                    self.stub.values[("datastore-1", "summary")].accessible = False
                elif case == "mount_readonly":
                    self.stub.values[("datastore-1", "host")][0].mountInfo.accessMode = "readOnly"
                elif case == "mount_unknown":
                    self.stub.values[("datastore-1", "host")] = []
                elif case == "mount_unmounted":
                    self.stub.values[("datastore-1", "host")][0].mountInfo.mounted = False
                elif case == "mount_inaccessible":
                    self.stub.values[("datastore-1", "host")][0].mountInfo.accessible = None
                elif case == "network_missing":
                    self.stub.values[("vm-1", "network")] = [vim.Network("network-1", self.stub)]
                elif case == "pool_privilege":
                    provider.content.authorizationManager.HasPrivilegeOnEntity = lambda **kw: [kw["entity"]._moId != "resgroup-1"] * len(kw["privId"])
                with self.assertRaises(OperationError) as error:
                    provider.preflight("template convert", {"vm_id": "vm-1", "pool_id": "resgroup-1", "host_id": "host-1"})
                self.assertEqual(error.exception.code, "permission_denied" if case == "pool_privilege" else "placement_invalid")
                self.assertEqual(self.stub.calls, [])

    def test_conversion_binds_storage_and_network_and_rejects_changed_mapping(self):
        provider = self.make()
        p = {"vm_id": "vm-1", "pool_id": "resgroup-1", "host_id": "host-1"}
        binding = provider.preflight("template convert", p)
        self.assertEqual(binding["placement"].get("datastore_ids"), ["datastore-1"])
        self.assertEqual(binding["placement"].get("network_ids"), [])
        self.stub.values[("vm-1", "network")] = [vim.Network("network-1", self.stub)]
        self.stub.values[("host-1", "network")] = [vim.Network("network-1", self.stub)]
        with self.assertRaises(OperationError) as error:
            provider.submit("template convert", p, binding)
        self.assertEqual(error.exception.code, "plan_stale")
        self.assertEqual(self.stub.calls, [])

    def test_conversion_rejects_resolved_pool_or_host_with_wrong_id(self):
        for kind, requested, returned in (("pool", "resgroup-1", "resgroup-2"), ("host", "host-1", "host-2")):
            with self.subTest(kind=kind):
                provider = self.make()
                original = provider.resolver
                provider.resolver = lambda resource_kind, object_id: original(resource_kind, returned if object_id == requested else object_id)
                self.stub.values[(returned, "name")] = "other-object"
                with self.assertRaises(OperationError) as error:
                    provider.preflight("template convert", {"vm_id": "vm-1", "pool_id": "resgroup-1", "host_id": "host-1"})
                self.assertEqual(error.exception.code, "target_changed")
                self.assertEqual(self.stub.calls, [])

    def test_template_inspect_success_retains_template_identity(self):
        row = test_provider.InventoryTests.item(1)
        row.propSet += [NS(name="config.template", val=True), NS(name="config.instanceUuid", val="template-uuid")]
        inventory, _ = test_provider.InventoryTests.make(self, [NS(token=None, objects=[row])])
        with patch.object(vim.view.ContainerView, "Destroy"):
            result = inventory.resolve("template", object_id="1")
        self.assertEqual(result["config.instanceUuid"], "template-uuid")
        self.assertTrue(result["config.template"])

    def test_conversion_honors_documented_default_for_unset_mounted_flag(self):
        provider = self.make()
        self.stub.values[("datastore-1", "host")][0].mountInfo = vim.host.MountInfo(
            accessible=True, accessMode="readWrite")
        binding = provider.preflight("template convert", {"vm_id": "vm-1", "pool_id": "resgroup-1", "host_id": "host-1"})
        self.assertEqual(binding["placement"]["datastore_ids"], ["datastore-1"])

    def test_conversion_rejects_parameters_that_could_imply_other_mutations(self):
        provider = self.make()
        for extra in ({"name": "renamed"}, {"power_on": True}, {"pool_id": None}, {"host_id": "host-*"}):
            with self.subTest(extra=extra):
                with self.assertRaises(OperationError) as error:
                    provider.preflight("template convert", {"vm_id": "vm-1", "pool_id": "resgroup-1", "host_id": "host-1", **extra})
                self.assertIn(error.exception.code, ("invalid_arguments", "placement_invalid"))
        self.assertEqual(self.stub.calls, [])

    def test_conversion_success_and_postcondition_failure_are_verified_by_engine(self):
        for mismatch in (None, "name", "power", "pool", "host", "template"):
            with self.subTest(mismatch=mismatch), TemporaryDirectory() as directory:
                provider = self.make()
                original = self.stub.InvokeMethod
                def invoke(obj, info, args):
                    original(obj, info, args)
                    self.stub.values[("vm-1", "config")].template = mismatch == "template"
                    self.stub.values[("vm-1", "resourcePool")] = vim.ResourcePool("resgroup-2" if mismatch == "pool" else "resgroup-1", self.stub)
                    if mismatch == "name":
                        self.stub.values[("vm-1", "name")] = "renamed"
                    if mismatch == "power":
                        self.stub.values[("vm-1", "runtime")].powerState = "poweredOn"
                    if mismatch == "host":
                        self.stub.values[("vm-1", "runtime")].host = vim.HostSystem("host-2", self.stub)
                    return None
                self.stub.InvokeMethod = invoke
                store = Store(Path(directory) / "state.db")
                engine = Engine(store, ProviderRouter(None, {"vm": provider}), "p", 0)
                preview = engine.preview("template convert", {"vm_id": "vm-1", "pool_id": "resgroup-1", "host_id": "host-1"})
                result = engine.apply(preview.data["id"], preview.data["digest"])
                self.assertEqual(result.status, "succeeded" if mismatch is None else "reconciliation_required")
                engine.reconcile(preview.data["id"])
                self.assertEqual([call[1] for call in self.stub.calls], ["MarkAsVirtualMachine"])
                store.close()

    def test_convert_response_lost_never_resubmits(self):
        provider = self.make()
        p = {"vm_id": "vm-1", "pool_id": "resgroup-1", "host_id": "host-1"}
        original = self.stub.InvokeMethod
        def lost(obj, info, args):
            original(obj, info, args)
            raise ConnectionError("lost response")
        self.stub.InvokeMethod = lost
        with TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.db")
            engine = Engine(store, ProviderRouter(None, {"vm": provider}), "p", 0)
            preview = engine.preview("template convert", p)
            result = engine.apply(preview.data["id"], preview.data["digest"])
            self.assertEqual(result.status, "reconciliation_required")
            engine.apply(preview.data["id"], preview.data["digest"])
            engine.reconcile(preview.data["id"])
            self.assertEqual(len(self.stub.calls), 1)
            store.close()
