"""Controlled channel for ``vm delete`` (replaces global fail-closed).

Authorization requires ALL of:
  * no local linked-clone dependency record;
  * a complete whole-vCenter inventory scan finding no OTHER VM/template or
    snapshot whose disk chain shares a target backing file;
  * explicit --allow-shared-datastore attestation for the unobservable case
    (another vCenter / standalone host mounting the shared datastore);
  * the existing two plan.apply confirmations (digest + DESTROY token).

Snapshot revert/delete and storage-bearing migration stay globally forbidden
(covered in test_linked_clone_strict). Any incomplete inventory evidence fails
closed.
"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS

from pyVmomi import vim

import test_linked_clone_strict
from vcenter_aiops.application.execution import Engine
from vcenter_aiops.application.providers import ProviderRouter
from vcenter_aiops.domain.models import OperationError, SubmissionRejected
from vcenter_aiops.infrastructure.store import Store


class DeleteGuardedChannelTests(test_linked_clone_strict.LinkedTests):
    def attach_view(self, provider, machines):
        """Expose a whole-vCenter VM/template enumeration to the scan."""
        view = NS(view=list(machines), Destroy=lambda: None)
        provider.content.rootFolder = vim.Folder("root", self.stub)
        provider.content.viewManager = NS(
            CreateContainerView=lambda root, types, recursive: view)
        return view

    def plain_machine(self, mo_id, name, file_name, *, datastore_id="datastore-1"):
        """A VM whose single FlatVer2 disk points at a given backing file."""
        backing = vim.vm.device.VirtualDisk.FlatVer2BackingInfo(
            fileName=file_name, datastore=vim.Datastore(datastore_id, self.stub),
            diskMode="persistent", uuid="disk-" + mo_id,
            contentId="content-" + mo_id, sharing="sharingNone")
        disk = vim.vm.device.VirtualDisk(key=9000, controllerKey=1000, unitNumber=0,
                                         capacityInKB=1024, backing=backing)
        return NS(_moId=mo_id, name=name,
                  config=NS(hardware=NS(device=[disk])), snapshot=None)

    def test_without_attestation_flag_scan_clean_still_rejects(self):
        provider = self.make()
        self.attach_view(provider, [])  # only the target exists in the vCenter
        with self.assertRaises(OperationError) as error:
            provider.preflight("vm delete", {"vm_id": "vm-1"})
        self.assertEqual(error.exception.code, "dependency_unproven")
        self.assertEqual(self.stub.calls, [])

    def test_clean_scan_with_flag_passes_and_binds_json_stable_evidence(self):
        provider = self.make()
        self.attach_view(provider, [])
        binding = provider.preflight(
            "vm delete", {"vm_id": "vm-1", "allow_shared_datastore": True})
        self.assertEqual(binding["risk"], "destructive")
        scan = binding["dependency_scan"]
        self.assertEqual(scan["scanned"], [])
        # Target owns current.vmdk (leaf) + base.vmdk (its parent delta).
        files = {row[1] for row in scan["protected"]}
        self.assertIn("[ds] source/current.vmdk", files)
        self.assertIn("[ds] source/base.vmdk", files)
        # Shapes survive the canonical/JSON round-trip done by the plan store.
        import json
        self.assertEqual(json.loads(json.dumps(scan)), scan)

    def test_consumer_sharing_backing_file_is_rejected_even_with_flag(self):
        provider = self.make()
        child = self.plain_machine("vm-2", "linked-child", "[ds] source/base.vmdk")
        self.attach_view(provider, [child])
        with self.assertRaises(OperationError) as error:
            provider.preflight(
                "vm delete", {"vm_id": "vm-1", "allow_shared_datastore": True})
        self.assertEqual(error.exception.code, "dependency_present")
        self.assertIn("vm-2", str(error.exception))
        self.assertEqual(self.stub.calls, [])

    def test_unrelated_backing_files_do_not_block_delete(self):
        provider = self.make()
        other = self.plain_machine("vm-2", "independent", "[ds] other/standalone.vmdk")
        self.attach_view(provider, [other])
        binding = provider.preflight(
            "vm delete", {"vm_id": "vm-1", "allow_shared_datastore": True})
        self.assertEqual(binding["dependency_scan"]["scanned"], ["vm-2"])

    def test_incomplete_inventory_evidence_fails_closed_even_with_flag(self):
        # viewManager absent, like the offline stub default: enumeration cannot
        # be obtained, which must never be read as "no consumers".
        provider = self.make()
        with self.assertRaises(OperationError) as error:
            provider.preflight(
                "vm delete", {"vm_id": "vm-1", "allow_shared_datastore": True})
        self.assertEqual(error.exception.code, "dependency_unproven")
        self.assertEqual(self.stub.calls, [])

    def test_unreadable_candidate_config_fails_closed(self):
        provider = self.make()
        broken = NS(_moId="vm-2", name="broken", config=None, snapshot=None)
        self.attach_view(provider, [broken])
        with self.assertRaises(OperationError) as error:
            provider.preflight(
                "vm delete", {"vm_id": "vm-1", "allow_shared_datastore": True})
        self.assertEqual(error.exception.code, "dependency_unproven")
        self.assertEqual(self.stub.calls, [])

    def test_submit_destroy_after_flag_and_rechecks_scan_at_submission(self):
        provider = self.make()
        self.attach_view(provider, [])
        params = {"vm_id": "vm-1", "allow_shared_datastore": True}
        binding = provider.preflight("vm delete", params)
        provider.submit("vm delete", params, binding)
        self.assertEqual(self.stub.calls[0][1], "Destroy_Task")

    def test_consumer_appearing_between_preview_and_submit_is_rejected(self):
        provider = self.make()
        view = self.attach_view(provider, [])
        params = {"vm_id": "vm-1", "allow_shared_datastore": True}
        binding = provider.preflight("vm delete", params)
        # A linked child is registered after preview, before the write.
        child = self.plain_machine("vm-2", "linked-child", "[ds] source/base.vmdk")
        view.view.append(child)
        with self.assertRaises(SubmissionRejected) as error:
            provider.submit("vm delete", params, binding)
        self.assertEqual(error.exception.code, "dependency_present")
        self.assertEqual(self.stub.calls, [])

    def test_local_dependency_record_takes_priority_over_clean_scan(self):
        provider = self.make()
        self.attach_view(provider, [])
        with TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.db")
            Engine(store, ProviderRouter(None, {"vm": provider}), "p", 0)
            # A submitted-but-unresolved linked clone against this parent.
            step = {"command": "deploy linked-clone", "params": {},
                    "binding": {"parent_dependency": {"server_uuid": "server-1",
                                "parent_uuid": "uuid-1", "snapshot_id": "snapshot-1", "disks": []}}}
            op = store.prepare("server-1:vm-1", "server-1:vm-1", step)
            store.db.execute("UPDATE operations SET state='succeeded' WHERE id=?", (op["id"],))
            with self.assertRaises(OperationError) as error:
                provider.preflight(
                    "vm delete", {"vm_id": "vm-1", "allow_shared_datastore": True})
            self.assertEqual(error.exception.code, "dependency_present")
            store.close()
        self.assertEqual(self.stub.calls, [])

    def test_engine_applies_destroy_only_with_both_confirmations(self):
        from vcenter_aiops.domain.models import fail as fail_error
        provider = self.make()
        self.attach_view(provider, [])
        self.stub.values[("task-1", "info")] = NS(
            state="success", error=None, progress=100,
            result=vim.VirtualMachine("vm-gone", self.stub))
        # Real vCenter raises ManagedObjectNotFound on vm-1 after Destroy_Task;
        # mutations.vm() normalises that to vm_not_found, which verify() treats
        # as the delete success postcondition. Emulate it on the offline stub.
        original_invoke = self.stub.InvokeMethod
        original_accessor = self.stub.InvokeAccessor

        def invoke(obj, info, args):
            returned = original_invoke(obj, info, args)
            if info.wsdlName == "Destroy_Task":
                def accessor(target, prop):
                    if target._moId == "vm-1" and prop.name == "config":
                        fail_error("vm_not_found", "指定 VM 不存在或已被删除: vm-1", 4)
                    return original_accessor(target, prop)
                self.stub.InvokeAccessor = accessor
            return returned
        self.stub.InvokeMethod = invoke
        with TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.db")
            engine = Engine(store, ProviderRouter(None, {"vm": provider}), "p", 0)
            plan = engine.preview(
                "vm delete", {"vm_id": "vm-1", "allow_shared_datastore": True}).data
            # Missing the second DESTROY token -> deterministic reject, no write.
            with self.assertRaises(OperationError) as error:
                engine.apply(plan["id"], plan["digest"])
            self.assertEqual(error.exception.code, "second_confirmation_required")
            self.assertEqual(self.stub.calls, [])
            result = engine.apply(plan["id"], plan["digest"],
                                  "DESTROY:" + plan["digest"], wait=True)
            self.assertEqual(result.status, "succeeded")
            self.assertEqual(self.stub.calls[0][1], "Destroy_Task")
            store.close()


if __name__ == "__main__":
    unittest.main()
