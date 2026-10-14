import importlib.util
from types import SimpleNamespace as NS
import unittest

from vcenter_aiops.domain.models import OperationError


class VmProviderTests(unittest.TestCase):
    def make(self):
        self.assertIsNotNone(importlib.util.find_spec("vcenter_aiops.providers.vsphere.mutations"), "VM mutations missing")
        from vcenter_aiops.providers.vsphere.mutations import Mutations
        self.calls = []
        def task(method, **kwargs):
            self.calls.append((method, kwargs))
            return NS(_moId="task-1")
        self.vm = NS(_moId="vm-1", name="test-vm", disabledMethod=[],
                     config=NS(instanceUuid="uuid-1", changeVersion="1", template=False,
                               hardware=NS(numCPU=2, memoryMB=2048)),
                     runtime=NS(powerState="poweredOff", connectionState="connected"),
                     guest=NS(toolsRunningStatus="guestToolsRunning"), snapshot=None,
                     PowerOnVM_Task=lambda **kw: task("power-on", **kw),
                     PowerOffVM_Task=lambda **kw: task("power-off", **kw),
                     ShutdownGuest=lambda **kw: self.calls.append(("shutdown", kw)),
                     Destroy_Task=lambda **kw: task("delete", **kw),
                     ReconfigVM_Task=lambda **kw: task("reconfigure", **kw),
                     CreateSnapshot_Task=lambda **kw: task("snapshot-create", **kw))
        self.permissions = True
        content = NS(about=NS(instanceUuid="server-1", apiVersion="6.5", apiType="VirtualCenter"),
                     sessionManager=NS(currentSession=NS(key="session-1")),
                     authorizationManager=NS(HasPrivilegeOnEntity=lambda **kw: [self.permissions for _ in kw["privId"]]))
        si = NS(RetrieveContent=lambda: content, _stub=None)
        return Mutations(si, resolver=lambda kind, oid: self.vm)

    def test_preflight_is_read_only_and_binds_vm_and_server(self):
        provider = self.make()
        binding = provider.preflight("vm power-on", {"vm_id": "vm-1"})
        self.assertEqual(binding["target"], "server-1:vm-1")
        self.assertEqual(binding["instance_uuid"], "uuid-1")
        self.assertEqual(self.calls, [])

    def test_delete_rejects_powered_on_without_implicit_shutdown(self):
        provider = self.make()
        self.vm.runtime.powerState = "poweredOn"
        with self.assertRaises(OperationError):
            provider.preflight("vm delete", {"vm_id": "vm-1"})
        self.assertEqual(self.calls, [])

    def test_privilege_and_disabled_method_block_preflight(self):
        provider = self.make()
        self.permissions = False
        with self.assertRaises(OperationError):
            provider.preflight("vm power-on", {"vm_id": "vm-1"})
        self.permissions = True
        self.vm.disabledMethod = ["PowerOnVM_Task"]
        with self.assertRaises(OperationError):
            provider.preflight("vm power-on", {"vm_id": "vm-1"})
        self.assertEqual(self.calls, [])

    def test_shutdown_returns_receipt_not_fake_task_and_never_hard_powers_off(self):
        provider = self.make()
        self.vm.runtime.powerState = "poweredOn"
        p = {"vm_id": "vm-1"}
        receipt = provider.submit("vm shutdown", p, provider.preflight("vm shutdown", p))
        self.assertNotIn("task_id", receipt)
        self.assertEqual(self.calls, [("shutdown", {})])

    def test_reconfigure_builds_one_spec_with_units_and_change_version(self):
        provider = self.make()
        p = {"vm_id": "vm-1", "cpu": 4, "memory_gb": 8}
        receipt = provider.submit("vm reconfigure", p, provider.preflight("vm reconfigure", p))
        spec = self.calls[0][1]["spec"]
        self.assertEqual(spec.numCPUs, 4)
        self.assertEqual(spec.memoryMB, 8192)
        self.assertEqual(spec.changeVersion, "1")
        self.assertEqual(receipt["task_id"], "server-1:task-1")

    def test_snapshot_create_never_defaults_memory_or_quiesce(self):
        provider = self.make()
        p = {"vm_id": "vm-1", "snapshot_name": "baseline", "memory": False, "quiesce": False}
        provider.submit("vm snapshot-create", p, provider.preflight("vm snapshot-create", p))
        self.assertEqual(self.calls, [("snapshot-create", {"name": "baseline", "description": "", "memory": False, "quiesce": False})])

    def test_task_identity_from_other_server_is_rejected(self):
        provider = self.make()
        with self.assertRaises(OperationError):
            provider.observe({"task_id": "server-2:task-1"}, {"server_uuid": "server-1"})

    def test_submit_rechecks_identity_before_any_write(self):
        provider = self.make()
        p = {"vm_id": "vm-1"}
        binding = provider.preflight("vm power-on", p)
        self.vm.config.instanceUuid = "replacement-vm"
        with self.assertRaises(OperationError):
            provider.submit("vm power-on", p, binding)
        self.assertEqual(self.calls, [])

    def test_plan_can_project_power_on_then_off_without_writing(self):
        provider = self.make()
        self.assertTrue(callable(getattr(provider, "bind_steps", None)))
        steps = provider.bind_steps([
            {"command": "vm power-on", "params": {"vm_id": "vm-1"}},
            {"command": "vm power-off", "params": {"vm_id": "vm-1"}},
        ])
        self.assertEqual(steps[0]["binding"]["before"]["power"], "poweredOff")
        self.assertEqual(steps[1]["binding"]["before"]["power"], "poweredOn")
        self.assertEqual(self.vm.runtime.powerState, "poweredOff")
        self.assertEqual(self.calls, [])

    def test_shutdown_observation_waits_for_guest_power_off(self):
        provider = self.make()
        self.vm.runtime.powerState = "poweredOn"
        p = {"vm_id": "vm-1"}
        binding = provider.preflight("vm shutdown", p)
        receipt = provider.submit("vm shutdown", p, binding)
        self.assertEqual(provider.observe(receipt, binding)["state"], "running")
        self.vm.runtime.powerState = "poweredOff"
        self.assertEqual(provider.observe(receipt, binding)["state"], "success")

    def test_cpu_only_projection_preserves_non_gib_memory(self):
        provider = self.make()
        self.assertTrue(callable(getattr(provider, "bind_steps", None)))
        self.vm.config.hardware.memoryMB = 512
        steps = provider.bind_steps([
            {"command": "vm reconfigure", "params": {"vm_id": "vm-1", "cpu": 4}},
            {"command": "vm power-on", "params": {"vm_id": "vm-1"}},
        ])
        self.assertEqual(steps[1]["binding"]["before"]["memory_mb"], 512)
