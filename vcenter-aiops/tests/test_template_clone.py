"""deploy clone-template: full template clone equivalent to vcenter-ops flow.

Offline transport only: real pyVmomi object graph with a stubbed SOAP stub.
Covers placement validation, single CloneVM_Task spec assembly (NIC remap,
CPU/memory, disk resize, fixed-IP Linux customization/power-on), DRS placement,
request-id deduplication through the shared engine, and verify evidence.
"""
from types import SimpleNamespace as NS
import unittest

from pyVmomi import vim

from vcenter_aiops.application.execution import Engine
from vcenter_aiops.application.providers import ProviderRouter
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store
from vcenter_aiops.providers.vsphere.template_clone import TemplateClone
import tempfile
from pathlib import Path


class Stub:
    def __init__(self):
        self.values = {}
        self.calls = []
        self.task = None

    def InvokeAccessor(self, obj, info):
        return self.values[(obj._moId, info.name)]

    def InvokeMethod(self, obj, info, args):
        kwargs = dict(zip([p.name for p in info.params], args))
        self.calls.append((obj._moId, info.wsdlName, kwargs))
        if info.wsdlName == "CancelTask":
            self.cancelled = True
            return None
        return vim.Task("task-1", self)  # task info served from self.values


class CloneFixture:
    def __init__(self, powered_on=False):
        self.stub = Stub()
        V = self.stub.values
        self.dc = vim.Datacenter("datacenter-1", self.stub)
        self.compute = vim.ClusterComputeResource("domain-c1", self.stub)
        self.folder = vim.Folder("group-v1", self.stub)
        self.pool = vim.ResourcePool("resgroup-1", self.stub)
        self.ds = vim.Datastore("datastore-1", self.stub)
        self.host = vim.HostSystem("host-1", self.stub)
        self.net = vim.Network("network-1", self.stub)
        self.dvpg = vim.dvs.DistributedVirtualPortgroup("dvportgroup-1", self.stub)
        self.dvs = vim.DistributedVirtualSwitch("dvs-1", self.stub)

        self.src_disk = vim.vm.device.VirtualDisk(key=2000, controllerKey=1000, unitNumber=0,
                                                  capacityInKB=40 * 1024**2)
        self.src_nic = vim.vm.device.VirtualE1000(key=4000)
        self.template = vim.VirtualMachine("vm-1", self.stub)

        # Resulting cloned VM evidence.
        backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo(network=self.net, deviceName="LAN")
        self.new_disk = vim.vm.device.VirtualDisk(key=2000, controllerKey=1000, unitNumber=0,
                                                  capacityInKB=100 * 1024**2)
        self.new_nic = vim.vm.device.VirtualE1000(key=4000, backing=backing)
        self.created = vim.VirtualMachine("vm-2", self.stub)

        V.update({
            ("datacenter-1", "name"): "DC",
            ("domain-c1", "name"): "cluster", ("domain-c1", "parent"): self.dc,
            ("domain-c1", "resourcePool"): self.pool, ("domain-c1", "vm"): [],
            ("group-v1", "name"): "VMs", ("group-v1", "parent"): self.dc,
            ("group-v1", "childType"): ["vim.VirtualMachine"], ("group-v1", "childEntity"): [],
            ("resgroup-1", "name"): "Resources", ("resgroup-1", "owner"): self.compute,
            ("datastore-1", "name"): "ds",
            ("datastore-1", "summary"): NS(accessible=True, maintenanceMode="normal",
                                           freeSpace=500 * 1024**3, type="VMFS"),
            ("host-1", "name"): "esx", ("host-1", "parent"): self.compute,
            ("host-1", "runtime"): NS(connectionState="connected", inMaintenanceMode=False),
            ("host-1", "datastore"): [self.ds], ("host-1", "network"): [self.net, self.dvpg],
            ("host-1", "vm"): [],
            ("network-1", "name"): "LAN",
            ("dvportgroup-1", "name"): "DVPG", ("dvportgroup-1", "key"): "pg-key",
            ("dvportgroup-1", "config"): NS(distributedVirtualSwitch=NS(uuid="dvs-uuid")),
            ("vm-1", "config"): NS(instanceUuid="uuid-1", changeVersion="1", template=True, keyId=None,
                                   hardware=NS(numCPU=2, memoryMB=4096,
                                               device=[self.src_disk, self.src_nic])),
            ("vm-1", "runtime"): NS(connectionState="connected", powerState="poweredOff", host=self.host),
            ("vm-1", "name"): "tpl", ("vm-1", "disabledMethod"): [],
            ("vm-1", "network"): [self.net],
            ("vm-2", "config"): NS(instanceUuid="uuid-2", template=False,
                                   hardware=NS(numCPU=4, memoryMB=8192,
                                               device=[self.new_disk, self.new_nic])),
            ("vm-2", "runtime"): NS(connectionState="connected",
                                    powerState="poweredOn" if powered_on else "poweredOff", host=self.host),
            ("vm-2", "name"): "target", ("vm-2", "parent"): self.folder,
            ("vm-2", "resourcePool"): self.pool, ("vm-2", "datastore"): [self.ds],
            ("vm-2", "network"): [self.net],
        })

        self.set_task_state("success", self.created)
        self.task_obj = vim.Task("task-1", self.stub)
        self.content = NS(about=NS(instanceUuid="server-1", apiType="VirtualCenter", apiVersion="8.0.3"),
                          sessionManager=NS(currentSession=NS(key="session")),
                          authorizationManager=NS(HasPrivilegeOnEntity=self.permission))
        self.si = NS(RetrieveContent=lambda: self.content, _stub=self.stub)
        self._objects = {"folder": self.folder, "pool": self.pool, "host": self.host,
                         "datastore": self.ds, "network": self.net, "vm": self.created,
                         "task": self.task_obj}
        self.allowed = True
        self.cancelled = False
        self.stub.values[("task-1", "cancelable")] = True

    def set_task_state(self, state, result=None, error=None):
        self.stub.values[("task-1", "info")] = NS(
            key="task-1", state=state, error=error, progress=100, result=result)

    def permission(self, **kw):
        return [self.allowed] * len(kw["privId"])

    def resolve(self, kind, object_id):
        if kind == "network" and object_id == "dvportgroup-1":
            return self.dvpg
        if kind == "vm" and object_id == "vm-1":
            return self.template
        return self._objects.get(kind)

    def provider(self):
        return TemplateClone(self.si, resolver=self.resolve)

    def clone_kwargs(self):
        return self.stub.calls[0][2]


BASE = dict(vm_id="vm-1", name="target", folder_id="group-v1", pool_id="resgroup-1",
            datastore_id="datastore-1", host_id="host-1")


class TemplateCloneTests(unittest.TestCase):
    def setUp(self):
        self.fx = CloneFixture()

    def preflight(self, **over):
        p = dict(BASE)
        p.update(over)
        return self.fx.provider().preflight("deploy clone-template", p), p

    def test_minimal_off_clone_single_task(self):
        fx = self.fx
        provider = fx.provider()
        binding, p = self.preflight()
        provider.submit("deploy clone-template", p, binding)
        mo, method, kw = fx.stub.calls[0]
        self.assertEqual((mo, method), ("vm-1", "CloneVM_Task"))
        spec = kw["spec"]
        self.assertFalse(spec.powerOn)
        self.assertFalse(spec.template)
        self.assertIsNone(spec.customization)
        self.assertEqual(kw["folder"]._moId, "group-v1")
        self.assertEqual(kw["name"], "target")
        self.assertEqual(spec.location.datastore._moId, "datastore-1")
        self.assertEqual(spec.location.host._moId, "host-1")
        obs = provider.observe({"task_id": "server-1:task-1"}, binding)
        self.assertEqual(obs["state"], "success")
        self.assertTrue(provider.verify("deploy clone-template", p, binding, obs))

    def test_drs_placement_when_host_omitted(self):
        fx = self.fx
        p = {k: v for k, v in BASE.items() if k != "host_id"}
        binding = fx.provider().preflight("deploy clone-template", p)
        self.assertIsNone(binding["placement"]["host_id"])
        fx.provider().submit("deploy clone-template", p, binding)
        spec = fx.clone_kwargs()["spec"]
        self.assertEqual(spec.location.pool._moId, "resgroup-1")
        self.assertIsNone(spec.location.host)

    def test_full_spec_remap_hardware_and_customization(self):
        fx = self.fx
        p = dict(BASE, network_id="network-1", cpu=4, memory_gb=8, disk_gb=100,
                 ip_address="10.0.0.20", gateway="10.0.0.1")
        binding = fx.provider().preflight("deploy clone-template", p)
        fx.provider().submit("deploy clone-template", p, binding)
        spec = fx.clone_kwargs()["spec"]
        self.assertTrue(spec.powerOn)
        self.assertEqual(spec.config.numCPUs, 4)
        self.assertEqual(spec.config.memoryMB, 8192)
        # NIC edit + disk edit travel in the same atomic clone ConfigSpec.
        nic_change = next(c for c in spec.config.deviceChange
                          if isinstance(c.device, vim.vm.device.VirtualEthernetCard))
        self.assertEqual(str(nic_change.operation), "edit")
        disk_change = next(c for c in spec.config.deviceChange
                           if isinstance(c.device, vim.vm.device.VirtualDisk))
        self.assertEqual(disk_change.device.capacityInKB, 100 * 1024**2)
        self.assertIsInstance(nic_change.device.backing,
                              vim.vm.device.VirtualEthernetCard.NetworkBackingInfo)
        # Fixed-IP Linux customization with default mask/domain.
        cust = spec.customization
        self.assertEqual(cust.identity.domain, "local")
        ip_settings = cust.nicSettingMap[0].adapter
        self.assertEqual(ip_settings.ip.ipAddress, "10.0.0.20")
        self.assertEqual(ip_settings.subnetMask, "255.255.255.0")
        self.assertEqual(ip_settings.gateway, ["10.0.0.1"])
        self.assertTrue(any("wait-tools" in w or "Tools" in w for w in binding["warnings"]))

    def test_dvportgroup_backing(self):
        fx = self.fx
        p = dict(BASE, network_id="dvportgroup-1")
        binding = fx.provider().preflight("deploy clone-template", p)
        fx.provider().submit("deploy clone-template", p, binding)
        nic = next(c.device for c in fx.clone_kwargs()["spec"].config.deviceChange
                   if isinstance(c.device, vim.vm.device.VirtualEthernetCard))
        self.assertIsInstance(nic.backing,
                              vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo)
        self.assertEqual(nic.backing.port.portgroupKey, "pg-key")
        self.assertEqual(nic.backing.port.switchUuid, "dvs-uuid")

    # -- invalid arguments -------------------------------------------------

    def test_rejects_non_template_source(self):
        self.fx.stub.values[("vm-1", "config")].template = False
        with self.assertRaises(OperationError) as e:
            self.preflight()
        self.assertEqual(e.exception.code, "precondition_failed")
        self.assertEqual(self.fx.stub.calls, [])

    def test_rejects_bad_ip_and_mask(self):
        with self.assertRaises(OperationError) as e:
            self.preflight(ip_address="999.1.1.1")
        self.assertEqual(e.exception.code, "invalid_arguments")
        with self.assertRaises(OperationError) as e:
            self.preflight(ip_address="10.0.0.2", subnet_mask="not-a-mask")
        self.assertEqual(e.exception.code, "invalid_arguments")

    def test_rejects_disk_shrink_or_equal(self):
        with self.assertRaises(OperationError) as e:
            self.preflight(disk_gb=40)
        self.assertEqual(e.exception.code, "invalid_arguments")
        with self.assertRaises(OperationError) as e:
            self.preflight(disk_gb=20)
        self.assertEqual(e.exception.code, "invalid_arguments")

    def test_rejects_duplicate_name(self):
        other = vim.VirtualMachine("vm-9", self.fx.stub)
        self.fx.stub.values[("vm-9", "name")] = "target"
        self.fx.stub.values[("group-v1", "childEntity")] = [other]
        with self.assertRaises(OperationError) as e:
            self.preflight()
        self.assertEqual(e.exception.code, "target_exists")

    def test_rejects_insufficient_capacity(self):
        self.fx.stub.values[("datastore-1", "summary")].freeSpace = 1024
        with self.assertRaises(OperationError) as e:
            self.preflight(disk_gb=100)
        self.assertEqual(e.exception.code, "capacity_insufficient")

    def test_permission_denied_before_submit(self):
        self.fx.allowed = False
        with self.assertRaises(OperationError) as e:
            self.preflight()
        self.assertEqual(e.exception.code, "permission_denied")
        self.assertEqual(self.fx.stub.calls, [])

    def test_missing_required_param(self):
        from vcenter_aiops.application.registry import lookup
        with self.assertRaises(OperationError) as e:
            lookup("deploy clone-template").validate({"vm_id": "vm-1"})
        self.assertEqual(e.exception.code, "invalid_arguments")
        self.assertEqual(self.fx.stub.calls, [])

    # -- engine dedup / failed task ---------------------------------------

    def test_request_id_dedup_returns_same_plan(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(Path(tmp.name) / "state.db")
        self.addCleanup(store.close)
        router = ProviderRouter(self.fx.si, providers={"template_clone": self.fx.provider()})
        engine = Engine(store, router, "p1")
        p = dict(BASE, request_id="fixed-req")
        first = engine.preview("deploy clone-template", {k: v for k, v in p.items() if k != "request_id"},
                               "fixed-req")
        second = engine.preview("deploy clone-template", {k: v for k, v in p.items() if k != "request_id"},
                                "fixed-req")
        self.assertEqual(first.data["id"], second.data["id"])

    def test_observe_failed_task_drives_verify_false(self):
        fx = self.fx
        provider = fx.provider()
        binding, p = self.preflight()
        provider.submit("deploy clone-template", p, binding)
        fx.set_task_state("error", error=NS(msg="insufficient permissions"))
        obs = provider.observe({"task_id": "server-1:task-1"}, binding)
        self.assertEqual(obs["state"], "error")
        self.assertFalse(provider.verify("deploy clone-template", p, binding, obs))


if __name__ == "__main__":
    unittest.main()
