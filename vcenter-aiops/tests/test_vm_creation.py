"""Empty VM creation through real SDK methods and offline transport only."""
import importlib.util
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


PARAMS = dict(name="empty", folder_id="group-v1", pool_id="resgroup-1", host_id="host-1",
              datastore_id="datastore-1", network_id="network-1", guest_id="otherGuest64",
              hardware_version="vmx-13", cpu=2, memory_gb=2, disk_gb=8)


class Fixture:
    def __init__(self):
        self.calls, self.queries, self.privileges = [], [], []
        self.allowed, self.lose = True, False
        self.dc = NS(_moId="datacenter-1", _wsdlName="Datacenter")
        self.folder = NS(_moId="group-v1", _wsdlName="Folder", name="VMs", parent=self.dc,
                         childType=["vim.VirtualMachine"], childEntity=[], disabledMethod=[])
        self.dc.vmFolder = self.folder
        self.compute = NS(_moId="domain-c1", _wsdlName="ClusterComputeResource", parent=self.dc)
        self.pool = NS(_moId="resgroup-1", _wsdlName="ResourcePool", name="pool", owner=self.compute, vm=[])
        self.ds = NS(_moId="datastore-1", _wsdlName="Datastore", name="store",
                     summary=NS(accessible=True, maintenanceMode="normal", freeSpace=100 * 1024**3))
        self.net = NS(_moId="network-1", _wsdlName="Network", name="LAN")
        self.host = NS(_moId="host-1", _wsdlName="HostSystem", name="esx", parent=self.compute,
                       runtime=NS(connectionState="connected", inMaintenanceMode=False),
                       datastore=[self.ds], network=[self.net], vm=[])
        self.data = {"datastore-1": self.ds, "network-1": self.net, "host-1": self.host, "resgroup-1": self.pool}
        self.ds = vim.Datastore("datastore-1", self)
        self.net = vim.Network("network-1", self)
        self.host = vim.HostSystem("host-1", self)
        self.pool = vim.ResourcePool("resgroup-1", self)
        self.data["host-1"].datastore = [self.ds]
        self.data["host-1"].network = [self.net]
        self.guest = vim.vm.GuestOsDescriptor(id="otherGuest64", supportedMaxCPUs=4,
            supportedMinMemMB=512, supportedMaxMemMB=8192,
            supportedDiskControllerList=[vim.vm.device.VirtualLsiLogicController],
            recommendedSCSIController=vim.vm.device.VirtualLsiLogicController,
            supportedEthernetCard=[vim.vm.device.VirtualE1000], recommendedEthernetCard=vim.vm.device.VirtualE1000,
            supportedForCreate=True)
        self.option = vim.vm.ConfigOption(version="vmx-13", guestOSDescriptor=[self.guest],
            hardwareOptions=vim.vm.VirtualHardwareOption(hwVersion=13, numCPU=[1, 2, 4],
                memoryMB=vim.option.LongOption(min=256, max=16384), virtualDeviceOption=[
                vim.vm.device.VirtualLsiLogicControllerOption(type=vim.vm.device.VirtualLsiLogicController,
                    supportedDevice=[vim.vm.device.VirtualDisk], sharing=["noSharing"],
                    numSCSIDisks=vim.option.IntOption(min=0, max=15)),
                vim.vm.device.VirtualE1000Option(type=vim.vm.device.VirtualE1000),
                vim.vm.device.VirtualDiskOption(type=vim.vm.device.VirtualDisk,
                    capacityInKB=vim.option.LongOption(min=1024, max=64 * 1024**2),
                    backingOption=[vim.vm.device.VirtualDiskOption.FlatVer2BackingOption(
                        type=vim.vm.device.VirtualDisk.FlatVer2BackingInfo,
                        diskMode=vim.option.ChoiceOption(choiceInfo=[vim.ElementDescription(key="persistent")]),
                        thinProvisioned=vim.option.BoolOption(supported=True, defaultValue=False))])]))
        self.compute.environmentBrowser = NS(QueryConfigOption=self.query)
        self.folder.CreateVM_Task = vim.Folder("group-v1", self).CreateVM_Task
        self.task = NS(_moId="task-1", _wsdlName="Task", info=NS(key="task-1",
            task=vim.Task("task-1", self), entity=None, name="vim.Folder.createVm", state="success",
            error=None, progress=100, cancelable=True), CancelTask=lambda: None)
        self.content = NS(about=NS(instanceUuid="server-1", apiType="VirtualCenter", apiVersion="6.5"),
            sessionManager=NS(currentSession=NS(key="session-1")),
            authorizationManager=NS(HasPrivilegeOnEntity=self.permission))
        self.si = NS(RetrieveContent=lambda: self.content, _stub=self)
        self.objects = {"folder": self.folder, "pool": self.pool, "host": self.host,
                        "datastore": self.ds, "network": self.net, "task": self.task}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return self.option

    def permission(self, **kwargs):
        self.privileges.append((kwargs["entity"]._moId, kwargs["privId"]))
        return [self.allowed] * len(kwargs["privId"])

    def resolve(self, kind, object_id):
        obj = self.objects[kind]
        return obj

    def InvokeMethod(self, obj, info, args):
        self.calls.append((info.wsdlName, args))
        spec, pool, host = args
        devices = [change.device for change in spec.deviceChange]
        devices[1].backing.fileName = "[store] empty/empty.vmdk"
        self.vm = NS(_moId="vm-10", _wsdlName="VirtualMachine", name=spec.name, parent=self.folder,
            resourcePool=pool, runtime=NS(host=host, powerState="poweredOff"), datastore=[self.ds], network=[self.net],
            config=NS(instanceUuid="new-uuid", uuid="bios-uuid", template=False, guestId=spec.guestId,
                version=spec.version, hardware=NS(numCPU=spec.numCPUs, memoryMB=spec.memoryMB, device=devices)))
        self.task.info.result = self.vm
        self.objects["vm"] = self.vm
        self.folder.childEntity.append(self.vm)
        self.pool.vm.append(self.vm)
        self.host.vm.append(self.vm)
        if self.lose:
            raise OSError("response lost")
        return vim.Task("task-1", self)

    def InvokeAccessor(self, obj, info):
        return getattr(self.data[obj._moId], info.name)

    def provider(self):
        if importlib.util.find_spec("vcenter_aiops.providers.vsphere.creation") is None:
            raise AssertionError("empty VM creation provider missing")
        from vcenter_aiops.providers.vsphere.creation import Creation
        return Creation(self.si, resolver=self.resolve)


class CreationTests(unittest.TestCase):
    def test_new_disk_initializes_authoritative_byte_capacity(self):
        f = Fixture()
        provider = f.provider()
        binding = provider.preflight("vm create", PARAMS)
        provider.submit("vm create", PARAMS, binding)
        self.assertEqual(f.calls[0][1][0].deviceChange[1].device.capacityInBytes, 8589934592)

    def engine(self, fixture):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        store = Store(Path(temp.name) / "state.db")
        self.addCleanup(store.close)
        return Engine(store, ProviderRouter(None, providers={"creation": fixture.provider()}), "lab", timeout=0)

    def test_create_sdk_spec_and_engine_result(self):
        f = Fixture()
        e = self.engine(f)
        p = e.preview_steps([dict(command="vm create", params=PARAMS)])
        r = e.apply(p.data["id"], p.data["digest"])
        self.assertEqual(r.status, "succeeded")
        self.assertEqual(r.data["execution"][0]["observation"]["instance_uuid"], "new-uuid")
        self.assertEqual(f.calls[0][0], "CreateVM_Task")
        spec, pool, host = f.calls[0][1]
        self.assertIsInstance(spec, vim.vm.ConfigSpec)
        self.assertEqual((spec.numCPUs, spec.memoryMB, spec.version, spec.guestId), (2, 2048, "vmx-13", "otherGuest64"))
        self.assertEqual(spec.files.vmPathName, "[store]")
        self.assertIs(pool, f.pool)
        self.assertIs(host, f.host)
        controller, disk, nic = [change.device for change in spec.deviceChange]
        self.assertIsInstance(controller, vim.vm.device.VirtualLsiLogicController)
        self.assertIsInstance(disk, vim.vm.device.VirtualDisk)
        self.assertEqual((disk.capacityInKB, disk.controllerKey, disk.unitNumber), (8388608, controller.key, 0))
        self.assertEqual(spec.deviceChange[1].fileOperation, "create")
        self.assertIsInstance(nic, vim.vm.device.VirtualE1000)
        self.assertEqual(nic.backing.network._moId, "network-1")
        self.assertTrue(nic.connectable.startConnected)
        self.assertFalse(nic.connectable.connected)
        self.assertEqual(f.vm.runtime.powerState, "poweredOff")
        self.assertEqual(f.queries[0], dict(key="vmx-13", host=f.host))
        self.assertIn(("group-v1", ["VirtualMachine.Inventory.Create"]), f.privileges)
        self.assertIn(("group-v1", ["VirtualMachine.Config.AddNewDisk"]), f.privileges)
        self.assertEqual(e.store.db.execute("SELECT COUNT(*) FROM leases").fetchone()[0], 0)

    def test_required_inputs_and_reject_existing_import_options(self):
        command = lookup("vm create")
        self.assertEqual(command.provider_kind, "creation")
        for key in PARAMS:
            with self.subTest(key=key), self.assertRaises(OperationError):
                command.validate({k: v for k, v in PARAMS.items() if k != key})
        with self.assertRaises(OperationError):
            command.validate({**PARAMS, "existing_disk": "disk.vmdk"})

    def test_target_capability_constraints_fail_closed(self):
        cases = [("cpu list", lambda f, p: p.update(cpu=3)),
                 ("guest cpu", lambda f, p: setattr(f.guest, "supportedMaxCPUs", 1)),
                 ("guest memory", lambda f, p: setattr(f.guest, "supportedMaxMemMB", 1024)),
                 ("hardware memory", lambda f, p: setattr(f.option.hardwareOptions.memoryMB, "max", 1024)),
                 ("version", lambda f, p: setattr(f.option, "version", "vmx-14")),
                 ("hardware numeric version", lambda f, p: setattr(f.option.hardwareOptions, "hwVersion", 14)),
                 ("guest missing", lambda f, p: p.update(guest_id="invalid")),
                 ("controller", lambda f, p: f.guest.supportedDiskControllerList.clear()),
                 ("nic", lambda f, p: f.guest.supportedEthernetCard.clear()),
                 ("disk limit", lambda f, p: p.update(disk_gb=65)),
                 ("deprecated disk", lambda f, p: setattr(f.option.hardwareOptions.virtualDeviceOption[2], "deprecated", True)),
                 ("option missing", lambda f, p: f.option.hardwareOptions.numCPU.clear())]
        for label, mutate in cases:
            with self.subTest(label=label):
                f, p = Fixture(), dict(PARAMS)
                mutate(f, p)
                with self.assertRaises(OperationError):
                    f.provider().preflight("vm create", p)
                self.assertEqual(f.calls, [])

    def test_placement_permissions_and_identity_fail_closed(self):
        cases = [("space", lambda f: setattr(f.ds.summary, "freeSpace", 1)),
                 ("permissions", lambda f: setattr(f, "allowed", False)),
                 ("pool owner", lambda f: setattr(f.data["resgroup-1"], "owner", NS(_moId="domain-c2"))),
                 ("host network", lambda f: setattr(f.data["host-1"], "network", [])),
                 ("host datastore", lambda f: setattr(f.data["host-1"], "datastore", [])),
                 ("resolver identity", lambda f: f.objects.update(network=NS(_moId="network-2", _wsdlName="Network", name="wrong"))),
                 ("maintenance", lambda f: setattr(f.host.runtime, "inMaintenanceMode", True)),
                 ("folder kind", lambda f: setattr(f.folder, "childType", ["HostSystem"])),
                 ("name conflict", lambda f: f.folder.childEntity.append(NS(_moId="vm-2", name="empty"))),
                 ("datacenter", lambda f: setattr(f.compute, "parent", NS(_moId="datacenter-2", _wsdlName="Datacenter"))),
                 ("disabled", lambda f: f.folder.disabledMethod.append("CreateVM_Task"))]
        for label, mutate in cases:
            with self.subTest(label=label):
                f = Fixture()
                mutate(f)
                with self.assertRaises(OperationError):
                    f.provider().preflight("vm create", PARAMS)
                self.assertEqual(f.calls, [])

    def test_response_lost_is_never_resubmitted(self):
        f = Fixture()
        e = self.engine(f)
        p = e.preview_steps([dict(command="vm create", params=PARAMS)])
        f.lose = True
        r = e.apply(p.data["id"], p.data["digest"])
        self.assertEqual(r.status, "reconciliation_required")
        e.apply(p.data["id"], p.data["digest"])
        e.reconcile(p.data["id"])
        self.assertEqual(len(f.calls), 1)

    def test_task_result_identity_and_postconditions(self):
        cases = [("wrong key", lambda f: setattr(f.task.info, "key", "task-2")),
                 ("wrong task", lambda f: setattr(f.task.info, "task", vim.Task("task-2", f))),
                 ("wrong entity", lambda f: setattr(f.task.info, "entity", vim.Folder("group-v2", f))),
                 ("result type", lambda f: setattr(f.task.info, "result", vim.Folder("group-v1", f))),
                 ("uuid missing", lambda f: setattr(f.vm.config, "instanceUuid", None)),
                 ("powered", lambda f: setattr(f.vm.runtime, "powerState", "poweredOn")),
                 ("wrong host", lambda f: setattr(f.vm.runtime, "host", NS(_moId="host-2"))),
                 ("wrong disk", lambda f: setattr(f.vm.config.hardware.device[1], "capacityInKB", 1)),
                 ("wrong guest", lambda f: setattr(f.vm.config, "guestId", "otherGuest")),
                 ("wrong nic", lambda f: setattr(f.vm.config.hardware.device[2].backing, "network", vim.Network("network-2", f)))]
        for label, mutate in cases:
            with self.subTest(label=label):
                f = Fixture()
                provider = f.provider()
                b = provider.preflight("vm create", PARAMS)
                receipt = provider.submit("vm create", PARAMS, b)
                mutate(f)
                try:
                    observation = provider.observe(receipt, b)
                except OperationError:
                    continue
                self.assertFalse(provider.verify("vm create", PARAMS, b, observation))

    def test_result_vm_entity_allowed_and_uuid_pinned(self):
        f = Fixture()
        provider = f.provider()
        b = provider.preflight("vm create", PARAMS)
        receipt = provider.submit("vm create", PARAMS, b)
        f.task.info.entity = f.vm
        observation = provider.observe(receipt, b)
        self.assertTrue(provider.verify("vm create", PARAMS, b, observation))
        f.vm.config.instanceUuid = "replacement-uuid"
        self.assertFalse(provider.verify("vm create", PARAMS, b, observation))

    def test_creation_plan_dependencies_are_rejected(self):
        f = Fixture()
        e = self.engine(f)
        with self.assertRaises(OperationError):
            e.preview_steps([dict(command="vm create", params=PARAMS),
                             dict(command="vm create", params={**PARAMS, "name": "second"})])

    def test_device_backing_and_controller_constraints(self):
        cases = [("backing absent", lambda f: f.option.hardwareOptions.virtualDeviceOption[2].backingOption.clear()),
                 ("disk mode", lambda f: setattr(f.option.hardwareOptions.virtualDeviceOption[2].backingOption[0].diskMode,
                                                "choiceInfo", [vim.ElementDescription(key="independent_nonpersistent")])),
                 ("controller disk", lambda f: setattr(f.option.hardwareOptions.virtualDeviceOption[0].numSCSIDisks, "max", 0)),
                 ("sharing", lambda f: setattr(f.option.hardwareOptions.virtualDeviceOption[0], "sharing", ["physicalSharing"]))]
        for label, mutate in cases:
            with self.subTest(label=label):
                f = Fixture()
                mutate(f)
                with self.assertRaises(OperationError):
                    f.provider().preflight("vm create", PARAMS)

    def test_task_folder_and_absent_entity_supported_server_remains_pinned(self):
        for entity in (None, "folder"):
            f = Fixture()
            provider = f.provider()
            b = provider.preflight("vm create", PARAMS)
            receipt = provider.submit("vm create", PARAMS, b)
            f.task.info.entity = f.folder if entity else None
            observation = provider.observe(receipt, b)
            self.assertTrue(provider.verify("vm create", PARAMS, b, observation))
            f.content.about.instanceUuid = "other-server"
            with self.assertRaises(OperationError):
                provider.observe(receipt, b)

    def test_existing_result_and_stale_binding_rejected(self):
        f = Fixture()
        old = NS(_moId="vm-10", _wsdlName="VirtualMachine", name="old")
        f.host.vm.append(old)
        provider = f.provider()
        b = provider.preflight("vm create", PARAMS)
        receipt = provider.submit("vm create", PARAMS, b)
        with self.assertRaises(OperationError):
            provider.observe(receipt, b)
        f = Fixture()
        provider = f.provider()
        b = provider.preflight("vm create", PARAMS)
        f.guest.supportedMaxCPUs = 2
        with self.assertRaises(OperationError):
            provider.submit("vm create", PARAMS, b)
        self.assertEqual(f.calls, [])

    def test_dvs_exact_backing_and_placement_verification(self):
        f = Fixture()
        f.net = vim.dvs.DistributedVirtualPortgroup("dvportgroup-1", f)
        f.data["dvportgroup-1"] = NS(name="DVS", key="pg-key", config=NS(distributedVirtualSwitch=NS(uuid="switch-uuid")))
        f.objects["network"] = f.net
        f.data["host-1"].network = [f.net]
        p = {**PARAMS, "network_id": "dvportgroup-1"}
        provider = f.provider()
        b = provider.preflight("vm create", p)
        receipt = provider.submit("vm create", p, b)
        observation = provider.observe(receipt, b)
        self.assertTrue(provider.verify("vm create", p, b, observation))
        backing = f.calls[0][1][0].deviceChange[2].device.backing
        self.assertEqual((backing.port.portgroupKey, backing.port.switchUuid), ("pg-key", "switch-uuid"))
        backing.port.switchUuid = "other-switch"
        self.assertFalse(provider.verify("vm create", p, b, observation))

    def test_missing_optional_new_fields_use_legacy_constraints(self):
        f = Fixture()
        # Older targets need not supply newer recommendedDiskController fields;
        # old recommendation plus explicit supported types and limits suffices.
        self.assertIsNone(f.guest.recommendedDiskController)
        f.guest.supportedMaxCPUs = 1
        with self.assertRaises(OperationError):
            f.provider().preflight("vm create", PARAMS)


if __name__ == "__main__":
    unittest.main()
