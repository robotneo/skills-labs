import importlib.util
from pathlib import Path
import tempfile
import unittest

from vcenter_aiops.domain.models import OperationError, SubmissionRejected
from vcenter_aiops.infrastructure.store import Store


class FakeProvider:
    """External boundary only; engine and SQLite below are real."""
    def __init__(self):
        self.identity = "server-a"
        self.state = "poweredOff"
        self.submissions = []
        self.task_state = "success"
        self.lose_response = False

    def preflight(self, command, params):
        return {"target": self.identity + ":" + params["vm_id"], "server_uuid": self.identity,
                "object_id": params["vm_id"], "instance_uuid": "vm-uuid",
                "before": {"power": self.state, "name": "original-name"}, "risk": "destructive" if command == "vm delete" else "change"}

    def submit(self, command, params, binding):
        self.submissions.append(command)
        if self.lose_response:
            raise OSError("response lost")
        self.state = "poweredOn"
        return {"task_id": self.identity + ":task-1"}

    def observe(self, receipt, binding):
        return {"state": self.task_state, "cancelled": False}

    def verify(self, command, params, binding, observation):
        return self.state == "poweredOn"


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.db")
        self.provider = FakeProvider()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def engine(self):
        self.assertIsNotNone(importlib.util.find_spec("vcenter_aiops.application.execution"), "execution engine missing")
        from vcenter_aiops.application.execution import Engine
        return Engine(self.store, self.provider, "lab")

    def preview(self, engine, command="vm power-on", request_id="req-1"):
        return engine.preview(command, {"vm_id": "vm-1"}, request_id)

    def test_preview_does_not_submit_and_same_request_reuses_plan(self):
        engine = self.engine()
        first = self.preview(engine)
        second = self.preview(engine)
        self.assertEqual(first.status, "awaiting_confirmation")
        self.assertEqual(first.data["id"], second.data["id"])
        self.assertEqual(self.provider.submissions, [])
        with self.assertRaises(OperationError):
            engine.preview("vm power-on", {"vm_id": "vm-2"}, "req-1")

    def test_confirmation_hash_and_preconditions_checked_before_submit(self):
        engine = self.engine()
        plan = self.preview(engine).data
        with self.assertRaises(OperationError):
            engine.apply(plan["id"], "wrong")
        self.provider.identity = "server-b"
        with self.assertRaises(OperationError):
            engine.apply(plan["id"], plan["digest"])
        self.assertEqual(self.provider.submissions, [])

    def test_expired_confirmation_cannot_be_consumed(self):
        engine = self.engine()
        plan = self.preview(engine).data
        self.store.db.execute("UPDATE plans SET created=0 WHERE id=?", (plan["id"],))
        with self.assertRaises(OperationError):
            engine.apply(plan["id"], plan["digest"])
        self.assertEqual(self.provider.submissions, [])

    def test_success_verified_and_repeat_apply_never_resubmits(self):
        engine = self.engine()
        plan = self.preview(engine).data
        result = engine.apply(plan["id"], plan["digest"])
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(engine.apply(plan["id"], plan["digest"]).status, "succeeded")
        self.assertEqual(self.provider.submissions, ["vm power-on"])

    def test_lost_submission_response_requires_reconciliation(self):
        engine = self.engine()
        plan = self.preview(engine).data
        self.provider.lose_response = True
        result = engine.apply(plan["id"], plan["digest"])
        self.assertEqual(result.status, "reconciliation_required")
        self.assertEqual(engine.apply(plan["id"], plan["digest"]).status, "reconciliation_required")
        self.assertEqual(self.provider.submissions, ["vm power-on"])

    def test_operation_error_after_remote_call_remains_unknown_and_locked(self):
        engine = self.engine()
        plan = self.preview(engine).data
        submit = self.provider.submit
        def response_error(*args):
            submit(*args)
            raise OperationError("remote_response_invalid", "remote call may already have completed")
        self.provider.submit = response_error
        result = engine.apply(plan["id"], plan["digest"])
        self.assertEqual(result.status, "reconciliation_required")
        self.assertEqual(self.store.operation(result.operation_id)["state"], "unknown")
        self.assertEqual(engine.apply(plan["id"], plan["digest"]).status, "reconciliation_required")
        self.assertEqual(engine.reconcile(plan["id"]).status, "reconciliation_required")
        new_operation = self.store.prepare("new-plan", "server-a:vm-1", {})
        with self.assertRaises(OperationError) as error:
            self.store.claim(new_operation["id"])
        self.assertEqual(error.exception.code, "target_busy")
        self.assertEqual(self.provider.submissions, ["vm power-on"])

    def test_receipt_persistence_failure_remains_unknown_and_never_resends(self):
        engine = self.engine()
        plan = self.preview(engine).data
        audit = self.store.audit
        def persist_error(event, *args):
            if event == "operation_receipted":
                # Even the marker type outside the provider's pre-write scope
                # cannot prove that the already-called remote method was safe.
                raise SubmissionRejected("receipt_persistence_failed", "receipt transaction failed")
            return audit(event, *args)
        self.store.audit = persist_error
        result = engine.apply(plan["id"], plan["digest"])
        self.assertEqual(result.status, "reconciliation_required")
        self.assertEqual(self.store.operation(result.operation_id)["state"], "unknown")
        self.assertEqual(engine.apply(plan["id"], plan["digest"]).status, "reconciliation_required")
        self.assertEqual(engine.reconcile(plan["id"]).status, "reconciliation_required")
        self.assertEqual(self.provider.submissions, ["vm power-on"])

    def test_proven_rejection_after_completed_step_preserves_partial_result(self):
        engine = self.engine()
        preview = engine.preview_steps([
            {"command": "vm power-on", "params": {"vm_id": "vm-1"}},
            {"command": "vm power-on", "params": {"vm_id": "vm-2"}},
        ])
        original_submit = self.provider.submit
        def reject_second(command, params, binding):
            if params["vm_id"] == "vm-2":
                raise SubmissionRejected("precondition_failed", "target rejected before write")
            return original_submit(command, params, binding)
        self.provider.submit = reject_second
        result = engine.apply(preview.data["id"], preview.data["digest"])
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.error["code"], "precondition_failed")
        self.assertEqual([step["state"] for step in result.data["execution"]], ["succeeded", "failed"])
        self.assertEqual(self.provider.submissions, ["vm power-on"])

    def test_task_success_without_postcondition_is_not_success(self):
        engine = self.engine()
        plan = self.preview(engine).data
        self.provider.verify = lambda *args: False
        self.assertEqual(engine.apply(plan["id"], plan["digest"]).status, "reconciliation_required")

    def test_high_risk_requires_second_exact_confirmation(self):
        engine = self.engine()
        plan = self.preview(engine, "vm delete").data
        with self.assertRaises(OperationError):
            engine.apply(plan["id"], plan["digest"])
        self.assertEqual(self.provider.submissions, [])

    def test_running_task_reconciles_without_resubmission(self):
        engine = self.engine()
        plan = self.preview(engine).data
        self.provider.task_state = "running"
        self.assertEqual(engine.apply(plan["id"], plan["digest"], wait=False).status, "running")
        self.provider.task_state = "success"
        self.assertEqual(engine.reconcile(plan["id"]).status, "succeeded")
        self.assertEqual(self.provider.submissions, ["vm power-on"])

    def test_cancel_request_does_not_mean_cancelled(self):
        engine = self.engine()
        self.assertTrue(callable(getattr(engine, "cancel", None)))
        plan = self.preview(engine).data
        self.provider.task_state = "running"
        result = engine.apply(plan["id"], plan["digest"], wait=False)
        self.provider.cancel = lambda receipt, binding: None
        result = engine.cancel(result.operation_id, "server-a:task-1")
        self.assertEqual(result.data["execution"][0]["state"], "cancel_requested")
        with self.assertRaises(OperationError):
            other = self.store.prepare("other", "server-a:vm-1", {})
            self.store.claim(other["id"])

    def test_cancel_missing_receipt_cannot_mark_operation_cancelled(self):
        engine = self.engine()
        self.assertTrue(callable(getattr(engine, "cancel", None)))
        plan = self.preview(engine).data
        self.provider.lose_response = True
        result = engine.apply(plan["id"], plan["digest"])
        with self.assertRaises(OperationError):
            engine.cancel(result.operation_id, "server-a:task-1")
        self.assertEqual(self.store.operation(result.operation_id)["state"], "unknown")

    def test_late_running_observer_cannot_overwrite_success(self):
        engine = self.engine()
        plan = self.preview(engine).data
        self.provider.task_state = "running"
        engine.apply(plan["id"], plan["digest"], wait=False)
        def delayed_observation(*args):
            from vcenter_aiops.application.execution import Engine
            newer_provider = FakeProvider()
            newer_provider.state = "poweredOn"
            other_store = Store(Path(self.temp.name) / "state.db")
            try:
                newer = Engine(other_store, newer_provider, "lab").reconcile(plan["id"])
                self.assertEqual(newer.status, "succeeded")
            finally:
                other_store.close()
            return {"state": "running"}
        self.provider.observe = delayed_observation
        result = engine.reconcile(plan["id"])
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.data["execution"][0]["state"], "succeeded")
