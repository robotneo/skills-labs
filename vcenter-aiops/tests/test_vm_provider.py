import importlib.util
from types import SimpleNamespace as NS
import unittest

from pyVmomi import vim, vmodl
from vcenter_aiops.domain.models import OperationError


def missing_vm(object_id):
    """Stand-in for a dangling MoRef.

    Mutations.vm() reads ``_moId`` then fetches ``config``; real vCenter raises
    ManagedObjectNotFound on that first property read of a deleted reference.
    """
    fault = vmodl.fault.ManagedObjectNotFound(obj=vim.VirtualMachine(object_id, object()))

    class _MissingVM:
        def __init__(self):
            self._moId = object_id

        def __getattr__(self, name):
            raise fault

    return _MissingVM()


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

    def test_rename_rejects_bad_new_name_before_remote_read(self):
        provider = self.make()
        for bad in ("", "a/b", "a\\b", "100%", " leading", "trailing ", "x" * 81,
                    "vm\u200b", "a\x00b", None):
            with self.subTest(name=repr(bad)):
                with self.assertRaises(OperationError) as ctx:
                    provider.preflight("vm rename", {"vm_id": "vm-1", "new_name": bad})
                self.assertEqual(ctx.exception.code, "name_invalid")
                self.assertEqual(ctx.exception.exit_code, 2)
        # Rejected deterministically before any remote call / task.
        self.assertEqual(self.calls, [])

    def test_snapshot_create_rejects_bad_label_before_remote_read(self):
        provider = self.make()
        for bad in ("", "  x", "x  ", "x" * 81, "vm\u200b", "a\x00b", None):
            with self.subTest(name=repr(bad)):
                with self.assertRaises(OperationError) as ctx:
                    provider.preflight("vm snapshot-create",
                                       {"vm_id": "vm-1", "snapshot_name": bad})
                self.assertEqual(ctx.exception.code, "name_invalid")
                self.assertEqual(ctx.exception.exit_code, 2)
        # Separators remain legal in a snapshot label.
        provider.preflight("vm snapshot-create",
                           {"vm_id": "vm-1", "snapshot_name": "pre/upgrade 100%"})
        self.assertEqual(self.calls, [])

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

    def test_dangling_mor_preflight_is_structured_vm_not_found_d3(self):
        # All four batch power commands on a deleted vm must return vm_not_found
        # (exit 4), not a top-level internal_error (exit 5).
        provider = self.make()
        provider.resolver = lambda kind, oid: missing_vm(oid)
        for command in ("vm power-on", "vm power-off", "vm shutdown", "vm reset"):
            with self.subTest(command=command):
                with self.assertRaises(OperationError) as error:
                    provider.preflight(command, {"vm_id": "vm-99999999"})
                self.assertEqual(error.exception.code, "vm_not_found")
                self.assertEqual(error.exception.exit_code, 4)
                self.assertIn("vm-99999999", str(error.exception))
        self.assertEqual(self.calls, [])

    def test_batch_bind_steps_reports_first_missing_vm_d3(self):
        provider = self.make()
        def resolver(kind, oid):
            return missing_vm(oid) if oid == "vm-99999999" else self.vm
        provider.resolver = resolver
        with self.assertRaises(OperationError) as error:
            provider.bind_steps([
                {"command": "vm power-on", "params": {"vm_id": "vm-1"}},
                {"command": "vm power-on", "params": {"vm_id": "vm-99999999"}},
            ])
        self.assertEqual(error.exception.code, "vm_not_found")
        self.assertIn("vm-99999999", str(error.exception))
        self.assertEqual(self.calls, [])

    def test_malformed_vm_id_is_target_invalid_not_not_found_d3(self):
        provider = self.make()
        with self.assertRaises(OperationError) as error:
            provider.preflight("vm power-on", {"vm_id": "not-a-mor"})
        self.assertEqual(error.exception.code, "target_invalid")
        self.assertEqual(error.exception.exit_code, 2)

    def test_delete_verify_succeeds_when_vm_gone_d3(self):
        provider = self.make()
        binding = provider.preflight("vm power-on", {"vm_id": "vm-1"})
        provider.resolver = lambda kind, oid: missing_vm(oid)
        # Only vm delete treats "object is gone" as a satisfied postcondition.
        self.assertTrue(provider.verify("vm delete", {"vm_id": "vm-1"}, binding, {}))
        # A non-delete command must not treat a dangling MoRef as success.
        self.assertFalse(provider.verify("vm power-on", {"vm_id": "vm-1"}, binding, {}))
