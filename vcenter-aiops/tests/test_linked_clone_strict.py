"""Offline contracts at the actual SOAP/spec and durable Engine boundaries."""
import copy
from contextlib import contextmanager
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS
import unittest

from pyVmomi import vim
import test_templates_linked
from vcenter_aiops.application.execution import Engine
from vcenter_aiops.application.providers import ProviderRouter
from vcenter_aiops.application.registry import lookup
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store


class LinkedTests(unittest.TestCase):
    def make(self):
        provider = test_templates_linked.TemplateTests.make(self, False)
        self.stub.values[("datastore-1", "summary")].type = "VMFS"
        ds = vim.Datastore("datastore-1", self.stub)
        backing = vim.vm.device.VirtualDisk.FlatVer2BackingInfo(
            fileName="[ds] source/base.vmdk", datastore=ds, diskMode="persistent",
            uuid="disk-base", contentId="base-content", sharing="sharingNone")
        disk = vim.vm.device.VirtualDisk(key=2000, controllerKey=1000, unitNumber=0,
            capacityInKB=1024, backing=backing)
        config = self.stub.values[("vm-1", "config")]
        config.hardware.device = [copy.deepcopy(disk)]
        config.hardware.device[0].backing = vim.vm.device.VirtualDisk.FlatVer2BackingInfo(
            fileName="[ds] source/current.vmdk", datastore=ds, diskMode="persistent",
            uuid="disk-current", contentId="current-content", sharing="sharingNone", parent=backing)
        snapshot = vim.vm.Snapshot("snapshot-1", self.stub)
        snap_config = copy.copy(config)
        snap_config.hardware = NS(numCPU=2, memoryMB=2048, device=[disk])
        self.stub.values[("snapshot-1", "config")] = snap_config
        self.stub.values[("snapshot-1", "vm")] = vim.VirtualMachine("vm-1", self.stub)
        self.stub.values[("vm-1", "snapshot")] = NS(currentSnapshot=snapshot,
            rootSnapshotList=[NS(snapshot=snapshot, childSnapshotList=[])])
        self.stub.values[("vm-1", "capability")] = NS(snapshotConfigSupported=True, snapshotOperationsSupported=True)
        self.stub.values[("host-1", "capability")] = NS(cloneFromSnapshotSupported=True, deltaDiskBackingsSupported=True)
        self.params.update(parent_uuid="uuid-1", snapshot_id="snapshot-1")
        return provider

    def binding(self, provider):
        try:
            return provider.preflight("deploy linked-clone", self.params)
        except OperationError as exc:
            self.fail("Linked clone contract missing or invalid: " + exc.code)

    def test_real_sdk_spec_uses_explicit_snapshot_and_child_backing(self):
        provider = self.make()
        binding = self.binding(provider)
        self.assertEqual(binding["parent_dependency"]["parent_uuid"], "uuid-1")
        self.assertEqual(binding["parent_dependency"]["snapshot_id"], "snapshot-1")
        self.assertEqual(self.stub.calls, [])
        provider.submit("deploy linked-clone", self.params, binding)
        spec = self.stub.calls[0][2]["spec"]
        self.assertEqual(spec.snapshot._moId, "snapshot-1")
        self.assertEqual(spec.location.diskMoveType, "createNewChildDiskBacking")
        self.assertFalse(spec.powerOn)
        self.assertFalse(spec.template)

    def test_parent_snapshot_capability_backing_and_permission_are_checked(self):
        for case, code in (("uuid", "target_changed"), ("snapshot", "snapshot_not_found"),
                           ("owner", "target_changed"), ("capability", "capability_unsupported"),
                           ("encrypted", "capability_unsupported"), ("backing", "capability_unsupported"),
                           ("permission", "permission_denied")):
            with self.subTest(case=case):
                provider = self.make()
                if case == "uuid": self.params["parent_uuid"] = "other"
                if case == "snapshot": self.params["snapshot_id"] = "snapshot-9"
                if case == "owner": self.stub.values[("snapshot-1", "vm")] = vim.VirtualMachine("vm-9", self.stub)
                if case == "capability": self.stub.values[("host-1", "capability")].deltaDiskBackingsSupported = False
                if case == "encrypted": self.stub.values[("snapshot-1", "config")].keyId = NS(keyId="secret")
                if case == "backing": self.stub.values[("snapshot-1", "config")].hardware.device[0].backing = vim.vm.device.VirtualDisk.RawDiskMappingVer1BackingInfo()
                if case == "permission": provider.content.authorizationManager.HasPrivilegeOnEntity = lambda **kw: [False] * len(kw["privId"])
                with self.assertRaises(OperationError) as error:
                    provider.preflight("deploy linked-clone", self.params)
                self.assertEqual(error.exception.code, code)
                self.assertEqual(self.stub.calls, [])

    def test_changed_parent_disk_chain_or_network_rejects_stale_submission(self):
        for change in ("chain", "network", "snapshot"):
            with self.subTest(change=change):
                provider = self.make()
                binding = self.binding(provider)
                if change == "chain": self.stub.values[("vm-1", "config")].hardware.device[0].backing.fileName = "[ds] source/other.vmdk"
                if change == "snapshot": self.stub.values[("snapshot-1", "config")].hardware.device[0].backing.uuid = "changed"
                if change == "network":
                    self.stub.values[("vm-1", "network")] = [vim.Network("network-1", self.stub)]
                    self.stub.values[("host-1", "network")] = [vim.Network("network-1", self.stub)]
                with self.assertRaises(OperationError):
                    provider.submit("deploy linked-clone", self.params, binding)
                self.assertEqual(self.stub.calls, [])

    def child(self):
        config = copy.deepcopy(self.stub.values[("snapshot-1", "config")])
        config.instanceUuid = "child-uuid"
        parent = config.hardware.device[0].backing
        config.hardware.device[0].backing = vim.vm.device.VirtualDisk.FlatVer2BackingInfo(
            fileName="[ds] target/child.vmdk", datastore=vim.Datastore("datastore-1", self.stub),
            diskMode="persistent", uuid="child-disk", contentId="child-content", sharing="sharingNone", parent=parent)
        self.stub.values.update({("vm-2", "config"): config, ("vm-2", "name"): "target",
            ("vm-2", "runtime"): NS(powerState="poweredOff", connectionState="connected", host=vim.HostSystem("host-1", self.stub)),
            ("vm-2", "parent"): vim.Folder("group-v1", self.stub),
            ("vm-2", "resourcePool"): vim.ResourcePool("resgroup-1", self.stub),
            ("vm-2", "network"): [], ("vm-2", "datastore"): [vim.Datastore("datastore-1", self.stub)]})

    def test_verify_requires_actual_child_identity_and_all_linked_backings(self):
        for case in ("valid", "full_clone", "wrong_parent", "same_uuid", "same_object", "missing_result"):
            with self.subTest(case=case):
                provider = self.make()
                binding = self.binding(provider)
                self.child()
                config = self.stub.values[("vm-2", "config")]
                if case == "full_clone": config.hardware.device[0].backing.parent = None
                if case == "wrong_parent": config.hardware.device[0].backing.parent.fileName = "[ds] other/base.vmdk"
                if case == "same_uuid": config.instanceUuid = "uuid-1"
                observation = {"result_id": "vm-1" if case == "same_object" else "vm-2", "instance_uuid": "child-uuid"}
                if case == "missing_result": observation = {}
                self.assertEqual(provider.verify("deploy linked-clone", self.params, binding, observation), case == "valid")

    def test_verify_checks_each_nic_network_and_only_allows_dv_port_reassignment(self):
        for case in ("standard", "swapped", "distributed", "new_port", "other_switch", "other_portgroup", "other_key"):
            with self.subTest(case=case):
                provider = self.make()
                networks = [vim.Network("network-1", self.stub), vim.Network("network-2", self.stub)]
                self.stub.values[("vm-1", "network")] = networks
                self.stub.values[("host-1", "network")] = networks
                if case in ("standard", "swapped"):
                    backings = [vim.vm.device.VirtualEthernetCard.NetworkBackingInfo(network=n, deviceName="net") for n in networks]
                else:
                    backings = [vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(
                        port=vim.dvs.PortConnection(switchUuid="switch-1", portgroupKey="group-" + str(i), portKey="port-" + str(i))) for i in (1, 2)]
                for config in (self.stub.values[("vm-1", "config")], self.stub.values[("snapshot-1", "config")]):
                    config.hardware.device.extend(vim.vm.device.VirtualVmxnet3(key=4000 + i, backing=copy.deepcopy(b)) for i, b in enumerate(backings))
                binding = self.binding(provider)
                self.child()
                self.stub.values[("vm-2", "network")] = networks
                nics = self.stub.values[("vm-2", "config")].hardware.device[1:]
                if case == "swapped": nics[0].backing, nics[1].backing = nics[1].backing, nics[0].backing
                if case == "new_port": nics[0].backing.port.portKey = "newly-allocated-port"
                if case == "other_switch": nics[0].backing.port.switchUuid = "switch-2"
                if case == "other_portgroup": nics[0].backing.port.portgroupKey = "other-group"
                if case == "other_key": nics[0].key = 9999
                self.assertEqual(provider.verify("deploy linked-clone", self.params, binding,
                    {"result_id": "vm-2", "instance_uuid": "child-uuid"}), case in ("standard", "distributed", "new_port"))

    def test_strict_cleanup_rejects_even_with_no_local_dependencies(self):
        # Snapshot revert/delete and storage-bearing migration have no
        # attestation channel and stay globally fail-closed. Whole-VM delete has
        # its own controlled-channel tests in test_delete_guarded_channel.
        for command in ("vm snapshot-delete", "vm snapshot-revert", "vm migrate"):
            with self.subTest(command=command):
                provider = self.make()
                params = {"vm_id": "vm-1"}
                if "snapshot-" in command: params["snapshot_id"] = "snapshot-1"
                if command == "vm migrate": params.update(pool_id="resgroup-1", host_id="host-1", datastore_id="datastore-1")
                with self.assertRaises(OperationError) as error:
                    provider.preflight(command, params)
                self.assertEqual(error.exception.code, "dependency_unproven")
                self.assertEqual(self.stub.calls, [])

    def test_delete_still_rejects_when_inventory_scan_is_unavailable(self):
        # No viewManager on the stub content = the whole-vCenter enumeration
        # cannot be obtained: fail closed even with the attestation flag.
        provider = self.make()
        with self.assertRaises(OperationError) as error:
            provider.preflight("vm delete", {"vm_id": "vm-1", "allow_shared_datastore": True})
        self.assertEqual(error.exception.code, "dependency_unproven")
        self.assertEqual(self.stub.calls, [])

    def test_compute_migration_has_no_storage_spec_and_power_on_is_unchanged(self):
        provider = self.make()
        self.stub.values[("vm-1", "config")].hardware.device = []
        params = {"vm_id": "vm-1", "pool_id": "resgroup-1", "host_id": "host-1"}
        try:
            lookup("vm migrate").validate(params)
        except OperationError as exc:
            self.fail("Compute-only migration is unavailable: " + exc.code)
        binding = provider.preflight("vm migrate", params)
        provider.submit("vm migrate", params, binding)
        spec = self.stub.calls[0][2]["spec"]
        self.assertIsNone(spec.datastore)
        self.assertFalse(spec.disk)
        self.assertIsNone(spec.diskMoveType)
        self.assertFalse(spec.deviceChange)
        provider.preflight("vm power-on", {"vm_id": "vm-1"})

    def test_compute_only_rejects_implicit_pmem_moves_and_unknown_storage(self):
        for case in ("pmem", "nvdimm", "unknown", "vvol"):
            with self.subTest(case=case):
                provider = self.make()
                self.stub.values[("vm-1", "config")].hardware.device = []
                if case == "nvdimm":
                    self.stub.values[("vm-1", "config")].hardware.device.append(vim.vm.device.VirtualNVDIMM(key=3000))
                else:
                    self.stub.values[("datastore-1", "summary")].type = {"pmem": "PMEM", "unknown": None, "vvol": "VVOL"}[case]
                with self.assertRaises(OperationError) as error:
                    provider.preflight("vm migrate", {"vm_id": "vm-1", "host_id": "host-1", "pool_id": "resgroup-1"})
                self.assertEqual(error.exception.code, "dependency_unproven")
                self.assertEqual(self.stub.calls, [])

    def test_compute_migration_rechecks_new_disk_at_submit_and_verify(self):
        provider = self.make()
        config = self.stub.values[("vm-1", "config")]
        original_devices = config.hardware.device
        config.hardware.device = []
        params = {"vm_id": "vm-1", "host_id": "host-1", "pool_id": "resgroup-1"}
        binding = provider.preflight("vm migrate", params)
        self.stub.values[("vm-1", "resourcePool")] = vim.ResourcePool("resgroup-1", self.stub)
        config.hardware.device = original_devices
        with self.assertRaises(OperationError) as error: provider.submit("vm migrate", params, binding)
        self.assertEqual(error.exception.code, "dependency_unproven")
        self.assertFalse(provider.verify("vm migrate", params, binding, {}))

    def test_compute_migration_requires_profile_exclusion_even_on_vmfs_and_nfs(self):
        for datastore_type in ("VMFS", "NFS", "NFS41"):
            with self.subTest(datastore_type=datastore_type):
                provider = self.make()
                current = self.stub.values[("vm-1", "config")]
                # Real VIM DTO has no associated profile field: conventional
                # datastore and a valid disk do not provide PBM evidence.
                self.stub.values[("vm-1", "config")] = vim.vm.ConfigInfo(
                    instanceUuid="uuid-1", changeVersion="1", template=False,
                    hardware=vim.vm.VirtualHardware(numCPU=2, memoryMB=2048, device=current.hardware.device))
                self.stub.values[("datastore-1", "summary")].type = datastore_type
                with self.assertRaises(OperationError) as error:
                    provider.preflight("vm migrate", {"vm_id": "vm-1", "host_id": "host-1", "pool_id": "resgroup-1"})
                self.assertEqual(error.exception.code, "dependency_unproven")
                self.assertEqual(self.stub.calls, [])

    def test_compute_migration_rejects_missing_device_inventory(self):
        provider = self.make()
        self.stub.values[("vm-1", "config")].hardware.device = None
        with self.assertRaises(OperationError) as error:
            provider.preflight("vm migrate", {"vm_id": "vm-1", "host_id": "host-1", "pool_id": "resgroup-1"})
        self.assertEqual(error.exception.code, "dependency_unproven")

    def test_response_lost_keeps_dependency_and_never_retries_across_profiles(self):
        provider = self.make()
        self.binding(provider)
        original = self.stub.InvokeMethod
        def lost(obj, info, args):
            original(obj, info, args)
            raise ConnectionError("lost")
        self.stub.InvokeMethod = lost
        with TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.db")
            engine = Engine(store, ProviderRouter(None, {"vm": provider}), "profile-a", 0)
            plan = engine.preview("deploy linked-clone", self.params).data
            result = engine.apply(plan["id"], plan["digest"])
            self.assertEqual(result.status, "reconciliation_required")
            engine.apply(plan["id"], plan["digest"])
            engine.reconcile(plan["id"])
            self.assertEqual(len(self.stub.calls), 1)
            Engine(store, ProviderRouter(None, {"vm": provider}), "profile-b", 0)
            with self.assertRaises(OperationError) as error:
                provider.preflight("vm delete", {"vm_id": "vm-1"})
            self.assertEqual(error.exception.code, "dependency_present")
            store.close()

    def test_persistent_dependencies_exclude_only_prepared_or_proven_not_submitted(self):
        self.assertIsNotNone(importlib.util.find_spec("vcenter_aiops.application.dependencies"), "Dependency resolver missing")
        from vcenter_aiops.application.dependencies import Dependencies
        with TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.db")
            Engine(store, object(), "p", 0)
            resolver = Dependencies(store)
            for state in ("prepared", "submitting", "unknown", "failed", "cancelled", "succeeded"):
                step = {"command": "deploy linked-clone", "params": {}, "binding": {"parent_dependency": {
                    "server_uuid": "server-1", "parent_uuid": "uuid-1", "snapshot_id": "snapshot-1", "disks": []}}}
                op = store.prepare(state, "server-1:vm-1", step)
                store.db.execute("UPDATE operations SET state=? WHERE id=?", (state, op["id"]))
            records = resolver.records("server-1", "uuid-1")
            self.assertEqual({r["state"] for r in records}, {"submitting", "unknown", "failed", "cancelled", "succeeded"})
            self.assertEqual(resolver.records("server-2", "uuid-1"), [])
            store.close()

    def test_active_claim_uses_parent_uuid_across_profiles_and_changed_moids(self):
        with TemporaryDirectory() as directory:
            first = Store(Path(directory) / "state.db")
            second = Store(Path(directory) / "state.db")
            for left, right in (("deploy linked-clone", "vm delete"), ("vm snapshot-delete", "deploy linked-clone"),
                                ("deploy linked-clone", "deploy linked-clone")):
                first.db.execute("DELETE FROM operations")
                def payload(command, object_id):
                    return {"command": command, "params": {}, "binding": {"server_uuid": "s", "instance_uuid": "u", "object_id": object_id}}
                a = first.prepare("a", "s:vm-1", payload(left, "vm-1"))
                b = second.prepare("b", "s:vm-2", payload(right, "vm-2"))
                first.claim(a["id"])
                with self.assertRaises(OperationError) as error:
                    second.claim(b["id"])
                self.assertEqual(error.exception.code, "target_busy")
                first.mark_unknown(a["id"])
                with self.assertRaises(OperationError): second.claim(b["id"])
                first.db.execute("UPDATE operations SET state='succeeded' WHERE id=?", (a["id"],))
                second.claim(b["id"])
            second.close()
            first.close()

    def test_direct_engine_injects_same_cross_profile_dependency_resolver(self):
        provider = self.make()
        with TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.db")
            Engine(store, provider, "p", 0)
            self.assertTrue(callable(getattr(provider, "parent_dependencies", None)), "Direct Engine lacks dependency resolver")
            store.close()

    def test_sdk_result_type_and_uuid_are_bound_before_child_verification(self):
        provider = self.make()
        binding = self.binding(provider)
        self.child()
        self.stub.values[("task-1", "info")] = NS(state="success", error=None, progress=100,
            result=vim.VirtualMachine("vm-2", self.stub))
        observation = provider.observe({"task_id": "server-1:task-1"}, binding)
        self.assertEqual(observation.get("instance_uuid"), "child-uuid")
        self.stub.values[("vm-2", "config")].instanceUuid = "replacement"
        self.assertFalse(provider.verify("deploy linked-clone", self.params, binding, observation))

    def test_malformed_snapshot_chain_mount_and_resolved_target_are_rejected(self):
        for case in ("missing_uuid", "independent", "encrypted_disk", "readonly_mount", "wrong_host", "duplicate_disk"):
            with self.subTest(case=case):
                provider = self.make()
                disk = self.stub.values[("snapshot-1", "config")].hardware.device[0]
                if case == "missing_uuid": disk.backing.uuid = None
                if case == "independent": disk.backing.diskMode = "independent_persistent"
                if case == "encrypted_disk": disk.backing.keyId = vim.encryption.CryptoKeyId(keyId="not-real")
                if case == "readonly_mount": self.stub.values[("datastore-1", "host")][0].mountInfo.accessMode = "readOnly"
                if case == "duplicate_disk": self.stub.values[("snapshot-1", "config")].hardware.device.append(copy.deepcopy(disk))
                if case == "wrong_host":
                    old = provider.resolver
                    provider.resolver = lambda kind, oid: vim.HostSystem("host-9", self.stub) if kind == "host" else old(kind, oid)
                    self.stub.values[("host-9", "name")] = "other"
                with self.assertRaises(OperationError): provider.preflight("deploy linked-clone", self.params)
                self.assertEqual(self.stub.calls, [])

    def test_submission_intent_protects_cleanup_and_not_submitted_is_excluded(self):
        from vcenter_aiops.application.dependencies import Dependencies
        for rejected in (False, True):
            with self.subTest(rejected=rejected), TemporaryDirectory() as directory:
                provider = self.make()
                store = Store(Path(directory) / "state.db")
                engine = Engine(store, ProviderRouter(None, {"vm": provider}), "p", 0)
                plan = engine.preview("deploy linked-clone", self.params).data
                if rejected:
                    original = store.claim
                    def claim(oid):
                        original(oid)
                        self.stub.values[("host-1", "capability")].deltaDiskBackingsSupported = False
                    store.claim = claim
                else:
                    original = self.stub.InvokeMethod
                    def invoke(obj, info, args):
                        with self.assertRaises(OperationError) as error: provider.preflight("vm delete", {"vm_id": "vm-1"})
                        self.assertEqual(error.exception.code, "dependency_present")
                        return original(obj, info, args)
                    self.stub.InvokeMethod = invoke
                    self.stub.values[("task-1", "info")] = NS(state="running", error=None, result=None, progress=0)
                result = engine.apply(plan["id"], plan["digest"], wait=False)
                self.assertEqual(result.status, "failed" if rejected else "running")
                self.assertEqual(len(Dependencies(store).records("server-1", "uuid-1")), 0 if rejected else 1)
                store.close()

    def test_single_command_plan_validate_apply_and_task_reconcile_share_real_provider(self):
        from vcenter_aiops.application.commands.linked import deploy_linked_clone
        from vcenter_aiops.application.commands.changes import plan_apply
        from vcenter_aiops.application.commands.plans import plan_validate, task_reconcile
        provider = self.make()
        self.child()
        self.stub.values[("task-1", "info")] = NS(state="running", error=None, progress=10, result=None)
        with TemporaryDirectory() as directory:
            store = Store(Path(directory) / "state.db")
            @contextmanager
            def session(): yield provider.si
            @contextmanager
            def stored(): yield store
            ctx = NS(session=session, store=stored, profile="p", timeout=0)
            plan = deploy_linked_clone(ctx, self.params).data
            self.assertTrue(plan_validate(ctx, {"plan_id": plan["id"]}).data["valid"])
            result = plan_apply(ctx, {"plan_id": plan["id"], "confirm": plan["digest"], "wait": False})
            self.assertEqual(result.status, "running")
            self.stub.values[("task-1", "info")] = NS(state="success", error=None, progress=100, result=vim.VirtualMachine("vm-2", self.stub))
            finished = task_reconcile(ctx, {"operation_id": result.operation_id})
            self.assertEqual(finished.status, "succeeded")
            self.assertEqual(len(self.stub.calls), 1)
            with self.assertRaises(OperationError):
                Engine(store, ProviderRouter(provider.si), "p", 0).preview_steps([
                    {"command": "vm snapshot-delete", "params": {"vm_id": "vm-1", "snapshot_id": "snapshot-1"}}])
            store.close()
