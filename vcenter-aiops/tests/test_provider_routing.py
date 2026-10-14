import contextlib
import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from vcenter_aiops.application import registry
from vcenter_aiops.application.execution import Engine
from vcenter_aiops.domain.contracts import Command
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store, canonical
from test_execution import FakeProvider
import test_vm_provider


class RecordingProvider(FakeProvider):
    """Offline boundary double: rejects routing metadata leaking to providers."""
    def __init__(self):
        super().__init__()
        self.calls = []

    def record(self, method, binding):
        if "provider_kind" in binding:
            raise AssertionError("routing metadata escaped into provider")
        self.calls.append(method)

    def preflight(self, command, params):
        self.calls.append("preflight")
        return super().preflight(command, params)

    def submit(self, command, params, binding):
        self.record("submit", binding)
        return super().submit(command, params, binding)

    def observe(self, receipt, binding):
        self.record("observe", binding)
        return super().observe(receipt, binding)

    def verify(self, command, params, binding, observation):
        self.record("verify", binding)
        return super().verify(command, params, binding, observation)

    def cancel(self, receipt, binding):
        self.record("cancel", binding)
        return {"cancel_requested": True}


class ProviderRoutingTests(unittest.TestCase):
    def router_class(self):
        self.assertIsNotNone(importlib.util.find_spec("vcenter_aiops.application.providers"),
                             "shared provider routing is missing")
        from vcenter_aiops.application.providers import ProviderRouter
        return ProviderRouter

    def router(self):
        cls = self.router_class()
        self.vm, self.guest = RecordingProvider(), RecordingProvider()
        synthetic = Command("test guest-change", "remote_write", "Offline routing fixture",
                            "unused:handler", provider_kind="guest")
        registration = patch.object(registry, "COMMANDS", registry.COMMANDS + (synthetic,))
        self.addCleanup(registration.stop)
        registration.start()
        return cls(None, providers={"vm": self.vm, "guest": self.guest})

    def test_command_metadata_defaults_existing_commands_to_vm(self):
        self.assertEqual(registry.lookup("vm power-on").describe().get("provider_kind"), "vm")

    def test_injected_provider_lifecycle_uses_registered_command_ownership(self):
        router = self.router()
        params = {"vm_id": "vm-1"}
        binding = router.preflight("test guest-change", params)
        self.assertEqual(binding["provider_kind"], "guest")
        receipt = router.submit("test guest-change", params, binding)
        observation = router.observe(receipt, binding)
        self.assertTrue(router.verify("test guest-change", params, binding, observation))
        self.assertEqual(router.cancel(receipt, binding), {"cancel_requested": True})
        self.assertEqual(self.guest.calls, ["preflight", "submit", "observe", "verify", "cancel"])
        self.assertEqual(self.vm.calls, [])
        self.assertEqual(binding["provider_kind"], "guest")

    def test_wrong_provider_binding_never_submits_or_verifies(self):
        router = self.router()
        params = {"vm_id": "vm-1"}
        original = router.preflight("vm power-on", params)
        for kind in ("unknown", "guest", None, [], "os:system"):
            binding = {**original, "provider_kind": kind}
            with self.subTest(kind=kind):
                with self.assertRaises(OperationError):
                    router.submit("vm power-on", params, binding)
                with self.assertRaises(OperationError):
                    router.verify("vm power-on", params, binding, {"state": "success"})
        self.assertEqual(self.vm.calls, ["preflight"])
        self.assertEqual(self.guest.calls, [])

    def test_missing_route_is_not_treated_as_legacy_vm_binding(self):
        router = self.router()
        binding = self.vm.preflight("vm power-on", {"vm_id": "vm-1"})
        with self.assertRaises(OperationError):
            router.submit("vm power-on", {"vm_id": "vm-1"}, binding)
        self.assertEqual(self.vm.submissions, [])

    def test_unknown_command_never_uses_injected_provider(self):
        router = self.router()
        with self.assertRaises(OperationError) as error:
            router.preflight("guest arbitrary", {"vm_id": "vm-1"})
        self.assertEqual(error.exception.code, "command_unknown")
        self.assertEqual(self.vm.calls + self.guest.calls, [])

    def test_unavailable_registered_kind_fails_before_preflight(self):
        self.router()
        router = self.router_class()(None, providers={"vm": self.vm})
        with self.assertRaises(OperationError) as error:
            router.preflight("test guest-change", {"vm_id": "vm-1"})
        self.assertEqual(error.exception.code, "provider_unknown")
        self.assertEqual(self.vm.calls + self.guest.calls, [])

    def test_observe_cancel_and_matches_reject_unknown_routes(self):
        router = self.router()
        valid = router.preflight("vm power-on", {"vm_id": "vm-1"})
        for kind in ("unknown", None, []):
            binding = {**valid, "provider_kind": kind}
            with self.subTest(kind=kind):
                with self.assertRaises(OperationError):
                    router.observe({"task_id": "server-a:task-1"}, binding)
                with self.assertRaises(OperationError):
                    router.cancel({"task_id": "server-a:task-1"}, binding)
                with self.assertRaises(OperationError):
                    router.matches(valid, binding)
        self.assertEqual(self.vm.calls, ["preflight"])
        self.assertEqual(self.guest.calls, [])

    def test_matches_rejects_different_registered_owners(self):
        router = self.router()
        valid = router.preflight("vm power-on", {"vm_id": "vm-1"})
        with self.assertRaises(OperationError) as error:
            router.matches(valid, {**valid, "provider_kind": "guest"})
        self.assertEqual(error.exception.code, "provider_mismatch")

    def test_cross_provider_plan_rejected_before_any_preflight(self):
        router = self.router()
        with self.assertRaises(OperationError) as error:
            router.bind_steps([
                {"command": "vm power-on", "params": {"vm_id": "vm-1"}},
                {"command": "test guest-change", "params": {"vm_id": "vm-1"}},
            ])
        self.assertEqual(error.exception.code, "plan_dependency_unsupported")
        self.assertEqual(self.vm.calls + self.guest.calls, [])

    def test_cross_provider_plan_rejected_before_missing_provider_check(self):
        self.router()
        router = self.router_class()(None, providers={"vm": self.vm})
        with self.assertRaises(OperationError) as error:
            router.bind_steps([
                {"command": "vm power-on", "params": {"vm_id": "vm-1"}},
                {"command": "test guest-change", "params": {"vm_id": "vm-1"}},
            ])
        self.assertEqual(error.exception.code, "plan_dependency_unsupported")
        self.assertEqual(self.vm.calls, [])

    def test_single_provider_without_projection_cannot_guess_multistep_state(self):
        router = self.router()
        with self.assertRaises(OperationError) as error:
            router.bind_steps([
                {"command": "test guest-change", "params": {"vm_id": "vm-1"}},
                {"command": "test guest-change", "params": {"vm_id": "vm-1"}},
            ])
        self.assertEqual(error.exception.code, "plan_dependency_unsupported")
        self.assertEqual(self.guest.calls, [])

    def test_real_vm_projection_and_matching_semantics_are_preserved(self):
        cls = self.router_class()
        fixture = test_vm_provider.VmProviderTests()
        vm = fixture.make()
        router = cls(None, providers={"vm": vm})
        bound = router.bind_steps([
            {"command": "vm reconfigure", "params": {"vm_id": "vm-1", "cpu": 4}},
            {"command": "vm power-on", "params": {"vm_id": "vm-1"}},
            {"command": "vm power-off", "params": {"vm_id": "vm-1"}},
        ])
        self.assertEqual([s["binding"]["provider_kind"] for s in bound], ["vm", "vm", "vm"])
        self.assertEqual(bound[1]["binding"]["before"]["cpu"], 4)
        self.assertEqual(bound[2]["binding"]["before"]["power"], "poweredOn")
        expected = bound[1]["binding"]
        actual = {**expected, "before": {**expected["before"], "change_version": "2"}}
        self.assertTrue(router.matches(expected, actual))
        self.assertEqual(actual["before"]["change_version"], "2")
        self.assertEqual(fixture.calls, [])

    def test_default_vm_provider_power_preview_and_execution(self):
        cls = self.router_class()
        fixture = test_vm_provider.VmProviderTests()
        vm = fixture.make()
        task = type("Task", (), {"info": type("Info", (), {
            "state": "success", "error": None, "result": None, "progress": 100})()})()
        def power_on():
            fixture.calls.append("power-on")
            fixture.vm.runtime.powerState = "poweredOn"
            return type("TaskIdentity", (), {"_moId": "task-1"})()
        fixture.vm.PowerOnVM_Task = power_on
        with patch("vcenter_aiops.providers.vsphere.mutations.Mutations.object",
                   side_effect=lambda kind, oid: task if kind == "task" else fixture.vm):
            router = cls(vm.si)
            with tempfile.TemporaryDirectory() as temp, contextlib.closing(Store(Path(temp) / "state.db")) as store:
                engine = Engine(store, router, "lab")
                plan = engine.preview("vm power-on", {"vm_id": "vm-1"}).data
                self.assertEqual(plan["payload"]["steps"][0]["binding"]["provider_kind"], "vm")
                self.assertEqual(fixture.calls, [])
                self.assertEqual(engine.apply(plan["id"], plan["digest"]).status, "succeeded")
                self.assertEqual(fixture.calls, ["power-on"])

    def test_provider_route_is_fixed_in_plan_digest(self):
        router = self.router()
        with tempfile.TemporaryDirectory() as temp, contextlib.closing(Store(Path(temp) / "state.db")) as store:
            engine = Engine(store, router, "lab")
            plan = engine.preview("vm power-on", {"vm_id": "vm-1"}).data
            payload = plan["payload"]
            self.assertEqual(payload["steps"][0]["binding"]["provider_kind"], "vm")
            payload["steps"][0]["binding"]["provider_kind"] = "guest"
            self.assertNotEqual(hashlib.sha256(canonical(payload).encode()).hexdigest(), plan["digest"])
            store.db.execute("UPDATE plans SET payload=? WHERE id=?", (canonical(payload), plan["id"]))
            with self.assertRaises(OperationError) as error:
                engine.apply(plan["id"], plan["digest"])
            self.assertEqual(error.exception.code, "plan_corrupted")
            self.assertEqual(self.vm.submissions + self.guest.submissions, [])

    def test_unknown_submission_reconciles_without_resubmitting(self):
        router = self.router()
        with tempfile.TemporaryDirectory() as temp, contextlib.closing(Store(Path(temp) / "state.db")) as store:
            engine = Engine(store, router, "lab")
            plan = engine.preview("test guest-change", {"vm_id": "vm-1"}).data
            self.guest.lose_response = True
            self.assertEqual(engine.apply(plan["id"], plan["digest"]).status, "reconciliation_required")
            self.assertEqual(engine.reconcile(plan["id"]).status, "reconciliation_required")
            self.assertEqual(engine.apply(plan["id"], plan["digest"]).status, "reconciliation_required")
            self.assertEqual(self.guest.submissions, ["test guest-change"])
            self.assertEqual(self.vm.submissions, [])

    def test_changes_and_plan_handlers_persist_routed_bindings(self):
        from vcenter_aiops.application.commands import changes, plans
        self.router()
        with tempfile.TemporaryDirectory() as temp, contextlib.closing(Store(Path(temp) / "state.db")) as store:
            class Context:
                profile, timeout = "lab", 1
                def session(self):
                    return contextlib.nullcontext(None)
                def store(self):
                    return contextlib.nullcontext(store)
            with patch("vcenter_aiops.providers.vsphere.mutations.Mutations", return_value=self.vm):
                preview = changes.preview(Context(), "vm power-on", {"vm_id": "vm-1"})
                self.assertEqual(preview.data["payload"]["steps"][0]["binding"]["provider_kind"], "vm")
                batch = plans.batch_power_on(Context(), {"vm_ids": ["vm-2"]})
                self.assertEqual(batch.data["payload"]["steps"][0]["binding"]["provider_kind"], "vm")
                self.assertTrue(plans.plan_validate(Context(), {"plan_id": preview.data["id"]}).data["valid"])

    def test_registry_and_cli_help_do_not_import_sdk(self):
        self.router_class()
        process = subprocess.run([sys.executable, "-c", "import sys; from vcenter_aiops.application.providers import ProviderRouter; from vcenter_aiops.cli.main import main; main(['--help']); assert 'pyVmomi' not in sys.modules"],
                                 capture_output=True, text=True, check=False)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("usage:", process.stdout)
