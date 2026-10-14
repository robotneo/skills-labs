"""Disk mutations exercise real SDK specs using offline transport."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest

from pyVmomi import vim
from vcenter_aiops.application.execution import Engine
from vcenter_aiops.application.providers import ProviderRouter
from vcenter_aiops.application.registry import lookup
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store
from vcenter_aiops.providers.vsphere.mutations import Mutations


EXPAND = dict(operation="expand", device_key=2000, capacity_gb=16)
ADD = dict(operation="add", device_key=-1, controller_key=1000, unit_number=1,
           datastore_id="datastore-1", capacity_gb=4)


class Fixture:
    def __init__(self):
        self.calls, self.permissions = [], []
        self.allowed = True
        self.ds = vim.Datastore("datastore-1", self)
        self.host = vim.HostSystem("host-1", self)
        self.disk = vim.vm.device.VirtualDisk(key=2000, controllerKey=1000, unitNumber=0,
            capacityInKB=8388608, backing=vim.vm.device.VirtualDisk.FlatVer2BackingInfo(
                fileName="[store] vm/disk.vmdk", datastore=self.ds, diskMode="persistent",
                thinProvisioned=False, eagerlyScrub=False))
        self.controller = vim.vm.device.VirtualLsiLogicController(key=1000, busNumber=0,
            sharedBus="noSharing", scsiCtlrUnitNumber=7, device=[2000])
        self.vm = NS(_moId="vm-1", name="vm", disabledMethod=[], snapshot=None,
            runtime=NS(host=self.host, powerState="poweredOff", connectionState="connected"),
            config=NS(instanceUuid="uuid-1", changeVersion="1", template=False, version="vmx-13",
                keyId=None, hardware=NS(numCPU=2, memoryMB=2048, device=[self.controller, self.disk])),
            ReconfigVM_Task=vim.VirtualMachine("vm-1", self).ReconfigVM_Task)
        self.option = vim.vm.ConfigOption(version="vmx-13", hardwareOptions=vim.vm.VirtualHardwareOption(
            virtualDeviceOption=[vim.vm.device.VirtualDiskOption(type=vim.vm.device.VirtualDisk,
                capacityInKB=vim.option.LongOption(min=1024, max=64 * 1024**2),
                backingOption=[vim.vm.device.VirtualDiskOption.FlatVer2BackingOption(
                    type=vim.vm.device.VirtualDisk.FlatVer2BackingInfo,
                    diskMode=vim.option.ChoiceOption(choiceInfo=[vim.ElementDescription(key="persistent")]),
                    thinProvisioned=vim.option.BoolOption(supported=True, defaultValue=False))]),
                vim.vm.device.VirtualLsiLogicControllerOption(type=vim.vm.device.VirtualLsiLogicController,
                    supportedDevice=[vim.vm.device.VirtualDisk], sharing=["noSharing"],
                    numSCSIDisks=vim.option.IntOption(min=0, max=15))]))
        self.data = {"datastore-1": NS(name="store", summary=NS(accessible=True,
            maintenanceMode="normal", freeSpace=100 * 1024**3), info=NS(maxVirtualDiskCapacity=64 * 1024**3),
            capability=vim.Datastore.Capability(directoryHierarchySupported=True, rawDiskMappingsSupported=True,
                perFileThinProvisioningSupported=True, vmdkExpandSupported=True)),
            "host-1": NS(datastore=[self.ds], parent=NS(environmentBrowser=NS(QueryConfigOption=lambda **kw: self.option)))}
        self.task = NS(info=NS(state="success", error=None, result=None, progress=100))
        content = NS(about=NS(instanceUuid="server-1", apiType="VirtualCenter", apiVersion="6.5"),
            sessionManager=NS(currentSession=NS(key="session-1")),
            authorizationManager=NS(HasPrivilegeOnEntity=self.permission))
        self.si = NS(RetrieveContent=lambda: content, _stub=self)

    def permission(self, **kw):
        self.permissions.append((kw["entity"]._moId, kw["privId"]))
        return [self.allowed] * len(kw["privId"])

    def InvokeAccessor(self, obj, info):
        return getattr(self.data[obj._moId], info.name)

    def InvokeMethod(self, obj, info, args):
        self.calls.append((info.wsdlName, args))
        spec = args[0]
        if spec.numCPUs is not None:
            self.vm.config.hardware.numCPU = spec.numCPUs
        for change in spec.deviceChange:
            disk = change.device
            if change.operation == "edit":
                self.vm.config.hardware.device = [disk if d.key == disk.key else d for d in self.vm.config.hardware.device]
            else:
                disk = deepcopy(disk)
                disk.key = 2001
                disk.backing.fileName = "[store] vm/new.vmdk"
                self.vm.config.hardware.device.append(disk)
        self.vm.config.changeVersion = "2"
        return vim.Task("task-1", self)

    def provider(self):
        return Mutations(self.si, resolver=lambda kind, oid: {"vm": self.vm, "task": self.task,
                         "host": self.host, "datastore": self.ds}[kind])


class DeviceTests(unittest.TestCase):
    def engine(self, f):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = Store(Path(temp.name) / "state.db")
        self.addCleanup(store.close)
        return Engine(store, ProviderRouter(None, {"vm": f.provider()}), "lab", timeout=0)

    def test_disk_list_rejects_unknown_nested_fields_and_types(self):
        c = lookup("vm reconfigure")
        for disk in [EXPAND, ADD]:
            self.assertEqual(c.validate(dict(vm_id="vm-1", disks=[disk]))["disks"], [disk])
        for disk in [{**EXPAND, "remove": True}, {**EXPAND, "capacity_gb": True},
                     {**EXPAND, "device_key": "2000"}, {**EXPAND, "operation": "delete"},
                     {**EXPAND, "datastore_id": "datastore-1"}, {"operation": "add", "capacity_gb": 4}]:
            with self.subTest(disk=disk), self.assertRaises(OperationError):
                c.validate(dict(vm_id="vm-1", disks=[disk]))
        self.assertIn("oneOf", c.input_schema()["properties"]["disks"]["items"])

    def test_disk_engine_builds_edit_and_add_specs_with_bound_units(self):
        f = Fixture()
        e = self.engine(f)
        p = dict(vm_id="vm-1", disks=[EXPAND, ADD])
        preview = e.preview("vm reconfigure", p)
        binding = preview.data["payload"]["steps"][0]["binding"]
        self.assertEqual(binding["disks"][0]["before_kb"], 8388608)
        self.assertEqual(binding["disks"][0]["after_bytes"], 17179869184)
        self.assertEqual(binding["uncompensated"], ["disks"])
        self.assertTrue(preview.warnings)
        self.assertEqual(f.calls, [])
        result = e.apply(preview.data["id"], preview.data["digest"])
        self.assertEqual(result.status, "succeeded")
        spec = f.calls[0][1][0]
        edit, add = spec.deviceChange
        self.assertEqual((edit.operation, edit.device.key, edit.device.capacityInKB), ("edit", 2000, 16777216))
        self.assertIsNone(edit.fileOperation)
        self.assertEqual((add.operation, add.fileOperation, add.device.key), ("add", "create", -1))
        self.assertEqual((add.device.controllerKey, add.device.unitNumber, add.device.capacityInKB), (1000, 1, 4194304))
        self.assertFalse(add.device.backing.thinProvisioned)
        self.assertIn(("vm-1", ["VirtualMachine.Config.DiskExtend", "VirtualMachine.Config.AddNewDisk"]), f.permissions)
        self.assertIn(("datastore-1", ["Datastore.AllocateSpace"]), f.permissions)

    def test_disks_fail_closed_before_submission(self):
        cases = [lambda f: setattr(f.vm.runtime, "powerState", "poweredOn"),
                 lambda f: setattr(f.vm, "snapshot", NS(rootSnapshotList=[1])),
                 lambda f: setattr(f.vm.config, "keyId", NS(keyId="encrypted")),
                 lambda f: setattr(f.disk.backing, "diskMode", "independent_persistent"),
                 lambda f: setattr(f.disk.backing, "parent", vim.vm.device.VirtualDisk.FlatVer2BackingInfo()),
                 lambda f: setattr(f.disk, "backing", vim.vm.device.VirtualDisk.RawDiskMappingVer1BackingInfo()),
                 lambda f: setattr(f.controller, "sharedBus", "physicalSharing"),
                 lambda f: setattr(f.data["datastore-1"].summary, "accessible", False),
                 lambda f: setattr(f.data["datastore-1"].summary, "freeSpace", 1),
                 lambda f: setattr(f.data["datastore-1"].info, "maxVirtualDiskCapacity", 1024),
                 lambda f: setattr(f.option.hardwareOptions.virtualDeviceOption[0].capacityInKB, "max", 1024),
                 lambda f: setattr(f, "allowed", False)]
        for mutate in cases:
            with self.subTest(mutate=mutate):
                f = Fixture()
                mutate(f)
                with self.assertRaises(OperationError):
                    f.provider().preflight("vm reconfigure", dict(vm_id="vm-1", disks=[EXPAND]))
                self.assertEqual(f.calls, [])
        for disks in [[{**EXPAND, "capacity_gb": 7}], [EXPAND, EXPAND],
                      [{**ADD, "unit_number": 0}], [{**ADD, "unit_number": 7}], [],
                      [{**ADD, "controller_key": 99}], [{**ADD, "device_key": 2001}]]:
            with self.subTest(disks=disks), self.assertRaises(OperationError):
                Fixture().provider().preflight("vm reconfigure", dict(vm_id="vm-1", disks=disks))

    def test_disk_staleness_and_specific_device_postconditions(self):
        f = Fixture()
        provider = f.provider()
        p = dict(vm_id="vm-1", disks=[EXPAND])
        binding = provider.preflight("vm reconfigure", p)
        f.disk.backing.fileName = "[store] different.vmdk"
        with self.assertRaises(OperationError):
            provider.submit("vm reconfigure", p, binding)
        self.assertEqual(f.calls, [])
        f = Fixture()
        provider = f.provider()
        p = dict(vm_id="vm-1", disks=[ADD])
        binding = provider.preflight("vm reconfigure", p)
        provider.submit("vm reconfigure", p, binding)
        self.assertTrue(provider.verify("vm reconfigure", p, binding, {}))
        f.vm.config.hardware.device[-1].unitNumber = 2
        self.assertFalse(provider.verify("vm reconfigure", p, binding, {}))

    def test_disk_device_dependencies_are_rejected_and_cpu_remains_projectable(self):
        for first in [dict(vm_id="vm-1", disks=[EXPAND]), dict(vm_id="vm-1", disks=[ADD])]:
            with self.assertRaises(OperationError):
                Fixture().provider().bind_steps([dict(command="vm reconfigure", params=first),
                    dict(command="vm power-on", params=dict(vm_id="vm-1"))])

    def test_mixed_disk_cpu_compensation_reports_partial_and_never_shrinks(self):
        f = Fixture()
        e = self.engine(f)
        preview = e.preview("vm reconfigure", dict(vm_id="vm-1", cpu=4, disks=[EXPAND]))
        e.apply(preview.data["id"], preview.data["digest"])
        rollback = e.rollback(preview.data["id"])
        self.assertEqual(rollback.data["uncompensated"][0]["fields"], ["disks"])
        self.assertEqual(rollback.data["payload"]["steps"][0]["params"], dict(vm_id="vm-1", cpu=2))
        e.apply(rollback.data["id"], rollback.data["digest"])
        self.assertEqual(e.result(preview.data["id"]).status, "compensation_partial")
        self.assertEqual(f.vm.config.hardware.device[1].capacityInKB, 16777216)

    def test_authoritative_capacity_mismatch_fails_closed(self):
        f = Fixture()
        f.disk.capacityInBytes = 9 * 1024**3
        with self.assertRaises(OperationError):
            f.provider().preflight("vm reconfigure", dict(vm_id="vm-1", disks=[EXPAND]))

    def test_controller_identity_is_verified_after_add(self):
        f = Fixture()
        provider = f.provider()
        p = dict(vm_id="vm-1", disks=[ADD])
        binding = provider.preflight("vm reconfigure", p)
        provider.submit("vm reconfigure", p, binding)
        f.controller.sharedBus = "physicalSharing"
        self.assertFalse(provider.verify("vm reconfigure", p, binding, {}))

    def test_postcondition_wrong_backing_returns_false(self):
        f = Fixture()
        provider = f.provider()
        p = dict(vm_id="vm-1", disks=[EXPAND])
        binding = provider.preflight("vm reconfigure", p)
        provider.submit("vm reconfigure", p, binding)
        f.vm.config.hardware.device[1].backing = vim.vm.device.VirtualDisk.RawDiskMappingVer1BackingInfo()
        self.assertFalse(provider.verify("vm reconfigure", p, binding, {}))

    def test_missing_reserved_scsi_unit_fails_closed(self):
        f = Fixture()
        f.controller.scsiCtlrUnitNumber = None
        with self.assertRaises(OperationError):
            f.provider().preflight("vm reconfigure", dict(vm_id="vm-1", disks=[ADD]))

    def test_documented_undefined_expand_flag_uses_actual_capacity_limits(self):
        p = dict(vm_id="vm-1", disks=[EXPAND])
        for version in ("6.5", "6.7", "7.0", "8.0"):
            f = Fixture()
            f.si.RetrieveContent().about.apiVersion = version
            f.data["datastore-1"].capability.vmdkExpandSupported = None
            e = self.engine(f)
            preview = e.preview("vm reconfigure", p)
            self.assertEqual(e.apply(preview.data["id"], preview.data["digest"]).status, "succeeded")
        for version, flag in [("6.5", False), ("6.7", False), ("8.0", False)]:
            f = Fixture()
            f.si.RetrieveContent().about.apiVersion = version
            f.data["datastore-1"].capability.vmdkExpandSupported = flag
            with self.subTest(version=version, flag=flag), self.assertRaises(OperationError):
                f.provider().preflight("vm reconfigure", p)
    def test_missing_or_malformed_datastore_capability_is_not_undefined_flag(self):
        for capability in (None, NS(vmdkExpandSupported=None), "unknown"):
            f = Fixture()
            f.data["datastore-1"].capability = capability
            with self.assertRaises(OperationError):
                f.provider().preflight("vm reconfigure", dict(vm_id="vm-1", disks=[EXPAND]))

    def test_add_and_expand_initialize_authoritative_byte_capacity(self):
        f = Fixture()
        provider = f.provider()
        p = dict(vm_id="vm-1", disks=[EXPAND, ADD])
        binding = provider.preflight("vm reconfigure", p)
        provider.submit("vm reconfigure", p, binding)
        edit, add = f.calls[0][1][0].deviceChange
        self.assertEqual((edit.device.capacityInBytes, add.device.capacityInBytes), (17179869184, 4294967296))

    def test_native_linked_clone_without_visible_parent_is_rejected(self):
        f = Fixture()
        f.disk.nativeUnmanagedLinkedClone = True
        with self.assertRaises(OperationError):
            f.provider().preflight("vm reconfigure", dict(vm_id="vm-1", disks=[EXPAND]))
