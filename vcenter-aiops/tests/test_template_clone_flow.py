"""deploy clone-template: confirmed-execution flow tests (no real vCenter).

These extend test_template_clone.py with full Engine/ProviderRouter scenarios:
preview->confirm->apply success, remote task failure, request-id idempotency
(no duplicate submission), lost response after submit = uncertainty (never
resubmitted), running-task cancellation, stale-plan rejection before write,
single-step plan constraint, and the clone rollback boundary (no fabricated
compensation). Transport is the same real pyVmomi object graph plus a stubbed
SOAP stub reused from the unit-test fixture.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from pyVmomi import vim

from vcenter_aiops.application.execution import Engine
from vcenter_aiops.application.providers import ProviderRouter
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store
from vcenter_aiops.providers.vsphere.template_clone import TemplateClone
from test_template_clone import CloneFixture, BASE


class FlakyCloneFixture(CloneFixture):
    """CloneFixture with a transport toggle for lost-response scenarios."""

    def __init__(self):
        super().__init__()
        self.lose_clone_response = False
        original_invoke = self.stub.InvokeMethod

        def invoke(obj, info, args):
            result = original_invoke(obj, info, args)
            # Simulate the response vanishing AFTER the remote CloneVM was
            # accepted (the original InvokeMethod already recorded the call).
            if info.wsdlName == "CloneVM_Task" and self.lose_clone_response:
                raise OSError("response lost after remote submission")
            return result

        self.stub.InvokeMethod = invoke

    def provider(self):
        return TemplateClone(self.si, resolver=self.resolve)


class CloneFlowEngineTests(unittest.TestCase):
    def make_engine_with(self, fixture):
        router = ProviderRouter(None, providers={"template_clone": fixture.provider()})
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = Store(Path(tmp.name) / "state.db")
        self.addCleanup(store.close)
        return Engine(store, router, "lab", timeout=0), store

    def make_engine(self):
        fixture = FlakyCloneFixture()
        engine, store = self.make_engine_with(fixture)
        return engine, store, fixture

    def clone_calls(self, fixture):
        return [c for c in fixture.stub.calls if c[1] == "CloneVM_Task"]

    # -- normal clone ------------------------------------------------------

    def test_full_engine_preview_confirm_apply_succeeds(self):
        engine, store, fx = self.make_engine()
        plan = engine.preview("deploy clone-template", dict(BASE)).data
        self.assertEqual(plan["status"], "awaiting_confirmation")
        self.assertEqual(plan["payload"]["steps"][0]["binding"]["provider_kind"],
                         "template_clone")
        self.assertEqual(self.clone_calls(fx), [])  # preview never writes
        result = engine.apply(plan["id"], plan["digest"])
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(len(self.clone_calls(fx)), 1)
        step = result.data["execution"][0]
        self.assertEqual(step["state"], "succeeded")
        self.assertEqual(step["receipt"]["task_id"], "server-1:task-1")
        self.assertEqual(step["observation"]["state"], "success")

    # -- parameter anomaly: rejected before any remote write --------------

    def test_non_template_preview_rejected_with_zero_writes(self):
        engine, store, fx = self.make_engine()
        fx.stub.values[("vm-1", "config")].template = False
        with self.assertRaises(OperationError) as ctx:
            engine.preview("deploy clone-template", dict(BASE))
        self.assertEqual(ctx.exception.code, "precondition_failed")
        self.assertEqual(self.clone_calls(fx), [])

    def test_drift_before_apply_is_rejected_without_write(self):
        engine, store, fx = self.make_engine()
        plan = engine.preview("deploy clone-template", dict(BASE)).data
        # A same-named VM appears in the target folder after confirmation is
        # issued. The engine's pre-submit preflight recheck raises before the
        # executing transaction / any remote write happens.
        other = vim.VirtualMachine("vm-9", fx.stub)
        fx.stub.values[("vm-9", "name")] = "target"
        fx.stub.values[("group-v1", "childEntity")] = [other]
        with self.assertRaises(OperationError) as ctx:
            engine.apply(plan["id"], plan["digest"])
        self.assertEqual(ctx.exception.code, "target_exists")
        self.assertEqual(self.clone_calls(fx), [])

    def test_submit_wraps_preflight_failure_as_submission_rejected(self):
        # The provider's own submit-time recheck must classify a precondition
        # failure as SubmissionRejected (read scope), never as uncertainty.
        from vcenter_aiops.domain.models import SubmissionRejected
        engine, store, fx = self.make_engine()
        provider = fx.provider()
        p = dict(BASE)
        binding = provider.preflight("deploy clone-template", p)
        other = vim.VirtualMachine("vm-9", fx.stub)
        fx.stub.values[("vm-9", "name")] = "target"
        fx.stub.values[("group-v1", "childEntity")] = [other]
        with self.assertRaises(SubmissionRejected) as ctx:
            provider.submit("deploy clone-template", p, binding)
        self.assertEqual(ctx.exception.code, "target_exists")
        self.assertEqual(self.clone_calls(fx), [])

    # -- remote task failure ----------------------------------------------

    def test_remote_task_error_marks_failed_and_does_not_retry(self):
        engine, store, fx = self.make_engine()
        plan = engine.preview("deploy clone-template", dict(BASE)).data
        fx.set_task_state("error", error=NS(msg="vCenter rejected placement"))
        result = engine.apply(plan["id"], plan["digest"])
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.data["execution"][0]["state"], "failed")
        self.assertEqual(result.data["execution"][0]["observation"]["state"], "error")
        # Exactly one submission; the engine must not retry a failed task.
        self.assertEqual(len(self.clone_calls(fx)), 1)

    # -- retry / idempotency ----------------------------------------------

    def test_same_request_id_returns_same_plan_and_submits_once(self):
        engine, store, fx = self.make_engine()
        p = dict(BASE)
        first = engine.preview("deploy clone-template", p, "clone-req-1").data
        second = engine.preview("deploy clone-template", p, "clone-req-1").data
        self.assertEqual(first["id"], second["id"])
        engine.apply(first["id"], first["digest"])
        # Re-applying the same (now succeeded) plan does not submit again.
        again = engine.apply(first["id"], first["digest"])
        self.assertEqual(again.status, "succeeded")
        self.assertEqual(len(self.clone_calls(fx)), 1)

    def test_same_request_id_with_changed_params_conflicts(self):
        engine, store, fx = self.make_engine()
        engine.preview("deploy clone-template", dict(BASE), "clone-req-2")
        changed = dict(BASE, name="different-name")
        with self.assertRaises(OperationError) as ctx:
            engine.preview("deploy clone-template", changed, "clone-req-2")
        self.assertEqual(ctx.exception.code, "request_conflict")
        self.assertEqual(self.clone_calls(fx), [])

    def test_lost_response_after_submit_is_uncertainty_and_never_resubmitted(self):
        engine, store, fx = self.make_engine()
        plan = engine.preview("deploy clone-template", dict(BASE)).data
        fx.lose_clone_response = True
        result = engine.apply(plan["id"], plan["digest"])
        # Response lost after the remote call -> uncertainty, not failure.
        self.assertEqual(result.status, "reconciliation_required")
        self.assertEqual(len(self.clone_calls(fx)), 1)
        # Neither reconcile nor a repeated apply may issue a second CloneVM.
        self.assertEqual(engine.reconcile(plan["id"]).status, "reconciliation_required")
        self.assertEqual(engine.apply(plan["id"], plan["digest"]).status,
                         "reconciliation_required")
        self.assertEqual(len(self.clone_calls(fx)), 1)

    # -- state rollback / cancel ------------------------------------------

    def test_running_clone_can_be_cancelled_once(self):
        engine, store, fx = self.make_engine()
        plan = engine.preview("deploy clone-template", dict(BASE)).data
        # Submit without blocking so the operation is left running; a real
        # running TaskInfo carries cancelable=True (set_task_state omits it).
        fx.set_task_state("running")
        fx.stub.values[("task-1", "info")].cancelable = True
        applied = engine.apply(plan["id"], plan["digest"], wait=False)
        self.assertEqual(applied.status, "running")
        row = store.db.execute(
            "SELECT operation_id FROM execution_steps WHERE plan_id=?",
            (plan["id"],)).fetchone()
        operation = store.operation(row["operation_id"])
        confirmation = operation["remote_task"]  # exact server:task identity
        engine.cancel(row["operation_id"], confirmation)
        self.assertEqual(len([c for c in fx.stub.calls if c[1] == "CancelTask"]), 1)
        # A second cancel is rejected (operation already cancel_requested).
        with self.assertRaises(OperationError) as ctx:
            engine.cancel(row["operation_id"], confirmation)
        self.assertEqual(ctx.exception.code, "transition_invalid")

    def test_cancel_requires_exact_task_identity(self):
        engine, store, fx = self.make_engine()
        plan = engine.preview("deploy clone-template", dict(BASE)).data
        fx.set_task_state("running")
        engine.apply(plan["id"], plan["digest"], wait=False)
        row = store.db.execute(
            "SELECT operation_id FROM execution_steps WHERE plan_id=?",
            (plan["id"],)).fetchone()
        with self.assertRaises(OperationError) as ctx:
            engine.cancel(row["operation_id"], "server-1:task-999")
        self.assertEqual(ctx.exception.code, "confirmation_required")
        self.assertEqual([c for c in fx.stub.calls if c[1] == "CancelTask"], [])

    def test_clone_has_no_fabricated_compensation(self):
        engine, store, fx = self.make_engine()
        # A succeeded clone is not "rolled back" by deleting the new VM: the
        # engine reports compensation unavailable rather than inventing a revert.
        plan = engine.preview("deploy clone-template", dict(BASE)).data
        engine.apply(plan["id"], plan["digest"])
        result = engine.rollback(plan["id"])
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error["code"], "compensation_unavailable")
        self.assertEqual(result.data["uncompensated"][0]["command"],
                         "deploy clone-template")
        self.assertEqual(len(self.clone_calls(fx)), 1)  # rollback issues no write

    def test_multi_step_plan_rejected(self):
        engine, store, fx = self.make_engine()
        steps = [{"command": "deploy clone-template", "params": dict(BASE)},
                 {"command": "deploy clone-template", "params": dict(BASE, name="other")}]
        with self.assertRaises(OperationError) as ctx:
            engine.preview_steps(steps)
        self.assertEqual(ctx.exception.code, "plan_dependency_unsupported")
        self.assertEqual(self.clone_calls(fx), [])

    def test_receipt_and_observation_persisted_as_json(self):
        engine, store, fx = self.make_engine()
        plan = engine.preview("deploy clone-template", dict(BASE)).data
        engine.apply(plan["id"], plan["digest"])
        raw = store.db.execute(
            "SELECT receipt, observation FROM execution_steps WHERE plan_id=?",
            (plan["id"],)).fetchone()
        receipt = json.loads(raw["receipt"])
        observation = json.loads(raw["observation"])
        self.assertEqual(receipt["task_id"], "server-1:task-1")
        self.assertEqual(observation["result_id"], "vm-2")
        self.assertEqual(observation["state"], "success")

    def test_cancelled_task_observation_drives_cancelled_state(self):
        # A RequestCanceled fault (user/DRS cancelled the clone) must surface as
        # operation state "cancelled", not a generic failure, and never retry.
        from pyVmomi import vmodl
        engine, store, fx = self.make_engine()
        plan = engine.preview("deploy clone-template", dict(BASE)).data
        fx.set_task_state("error", error=vmodl.fault.RequestCanceled())
        result = engine.apply(plan["id"], plan["digest"])
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.data["execution"][0]["state"], "cancelled")
        self.assertTrue(result.data["execution"][0]["observation"]["cancelled"])
        self.assertEqual(len(self.clone_calls(fx)), 1)

    def test_running_apply_then_reconcile_reaches_success(self):
        engine, store, fx = self.make_engine()
        plan = engine.preview("deploy clone-template", dict(BASE)).data
        # First apply leaves the operation running; later observe sees success.
        fx.set_task_state("running")
        fx.stub.values[("task-1", "info")].cancelable = True
        applied = engine.apply(plan["id"], plan["digest"], wait=False)
        self.assertEqual(applied.status, "running")
        fx.set_task_state("success", fx.created)
        reconciled = engine.reconcile(plan["id"])
        self.assertEqual(reconciled.status, "succeeded")
        self.assertEqual(reconciled.data["execution"][0]["state"], "succeeded")
        self.assertEqual(len(self.clone_calls(fx)), 1)


if __name__ == "__main__":
    unittest.main()
