from types import SimpleNamespace as NS
import unittest
from pyVmomi import vim

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.providers.vsphere.mutations import Mutations


class Stub:
    def __init__(self):
        self.values = {}
        self.calls = []

    def InvokeAccessor(self, obj, info):
        return self.values[(obj._moId, info.name)]

    def InvokeMethod(self, obj, info, args):
        self.calls.append((obj._moId, info.wsdlName, dict(zip([p.name for p in info.params], args))))
        return vim.Task("task-1", self)


class PlacementTests(unittest.TestCase):
    def make(self, template=False):
        stub = Stub()
        vm = vim.VirtualMachine("vm-1", stub)
        folder = vim.Folder("group-v1", stub)
        pool = vim.ResourcePool("resgroup-1", stub)
        datastore = vim.Datastore("datastore-1", stub)
        host = vim.HostSystem("host-1", stub)
        stub.values.update({
            ("vm-1", "config"): NS(instanceUuid="uuid-1", changeVersion="1", template=template, keyId=None,
                                   hardware=NS(numCPU=2, memoryMB=2048, device=[vim.vm.device.VirtualDisk(key=1, capacityInKB=1024)])),
            ("vm-1", "runtime"): NS(powerState="poweredOff", connectionState="connected", host=host),
            ("vm-1", "name"): "source", ("vm-1", "disabledMethod"): [],
            ("vm-1", "network"): [], ("vm-1", "snapshot"): None,
            ("group-v1", "name"): "VMs", ("group-v1", "childEntity"): [],
            ("group-v1", "childType"): ["vim.VirtualMachine"],
            ("resgroup-1", "name"): "Resources", ("resgroup-1", "owner"): vim.ClusterComputeResource("domain-c1", stub),
            ("datastore-1", "name"): "ds", ("datastore-1", "summary"): NS(accessible=True, maintenanceMode="normal", freeSpace=1024**3),
            ("host-1", "name"): "host", ("host-1", "runtime"): NS(connectionState="connected", inMaintenanceMode=False),
            ("host-1", "parent"): vim.ClusterComputeResource("domain-c1", stub),
            ("host-1", "datastore"): [datastore], ("host-1", "network"): [],
        })
        content = NS(about=NS(instanceUuid="server-1", apiType="VirtualCenter", apiVersion="8.0.3"),
                     sessionManager=NS(currentSession=NS(key="session")),
                     authorizationManager=NS(HasPrivilegeOnEntity=lambda **kw: [True] * len(kw["privId"])))
        si = NS(RetrieveContent=lambda: content, _stub=stub)
        self.stub = stub
        self.params = {"vm_id": "vm-1", "name": "target", "folder_id": "group-v1", "pool_id": "resgroup-1", "datastore_id": "datastore-1", "host_id": "host-1"}
        return Mutations(si)

    def test_clone_is_off_and_placement_is_explicit(self):
        provider = self.make()
        binding = provider.preflight("vm clone", self.params)
        self.assertEqual(self.stub.calls, [])
        provider.submit("vm clone", self.params, binding)
        _, method, p = self.stub.calls[0]
        self.assertEqual(method, "CloneVM_Task")
        self.assertFalse(p["spec"].powerOn)
        self.assertFalse(p["spec"].template)
        self.assertEqual(p["spec"].location.datastore._moId, "datastore-1")

    def test_template_deploy_rejects_vm_source(self):
        provider = self.make()
        with self.assertRaises(OperationError) as error:
            provider.preflight("deploy template", self.params)
        self.assertEqual(error.exception.code, "precondition_failed")
        self.assertEqual(self.stub.calls, [])

    def test_insufficient_storage_rejects_before_submit(self):
        provider = self.make()
        self.stub.values[("datastore-1", "summary")].freeSpace = 1
        with self.assertRaises(OperationError) as error:
            provider.preflight("vm clone", self.params)
        self.assertEqual(error.exception.code, "capacity_insufficient")
        self.assertEqual(self.stub.calls, [])

    def test_migrate_uses_relocate_not_deprecated_migrate(self):
        # Compute-only migration remains supported. Storage relocation now
        # requires unavailable global dependency exclusion and must fail closed.
        import test_templates_linked
        provider = test_templates_linked.TemplateTests.make(self, False)
        self.stub.values[("datastore-1", "summary")].type = "VMFS"
        # The VIM-only connection cannot exclude PMem storage profiles on
        # disks; the supported compute-only case is explicitly diskless.
        self.stub.values[("vm-1", "config")].hardware.device = []
        p = {k: v for k, v in self.params.items() if k not in ("name", "folder_id", "datastore_id")}
        binding = provider.preflight("vm migrate", p)
        provider.submit("vm migrate", p, binding)
        self.assertEqual(self.stub.calls[0][1], "RelocateVM_Task")

    def test_host_not_in_target_compute_resource_is_rejected(self):
        provider = self.make()
        self.stub.values[("host-1", "parent")] = vim.ClusterComputeResource("domain-c2", self.stub)
        with self.assertRaises(OperationError) as error:
            provider.preflight("vm clone", self.params)
        self.assertEqual(error.exception.code, "placement_invalid")
