import unittest
import test_execution
from vcenter_aiops.domain.models import OperationError


class PlanTests(unittest.TestCase):
    setUp = test_execution.ExecutionTests.setUp
    tearDown = test_execution.ExecutionTests.tearDown
    engine = test_execution.ExecutionTests.engine
    preview = test_execution.ExecutionTests.preview
    def sequence(self, engine):
        self.assertTrue(callable(getattr(engine, "preview_steps", None)), "multi-step preview missing")
        return engine.preview_steps([
            {"command": "vm power-on", "params": {"vm_id": "vm-1"}},
            {"command": "vm power-on", "params": {"vm_id": "vm-2"}},
        ], "batch-1").data

    def test_batch_preview_does_not_write_and_persists_bounded_targets(self):
        engine = self.engine()
        plan = self.sequence(engine)
        self.assertEqual([s["binding"]["target"] for s in plan["payload"]["steps"]], ["server-a:vm-1", "server-a:vm-2"])
        self.assertEqual(self.provider.submissions, [])

    def test_validate_projects_later_steps_and_detects_live_drift(self):
        engine = self.engine()
        name = ["A"]
        def bind(steps):
            current, bound = name[0], []
            for step in steps:
                binding = self.provider.preflight(step["command"], step["params"])
                binding["before"]["name"] = current
                bound.append({**step, "binding": binding})
                current = step["params"]["new_name"]
            return bound
        self.provider.bind_steps = bind
        plan = engine.preview_steps([{"command": "vm rename", "params": {"vm_id": "vm-1", "new_name": n}} for n in ("B", "C")]).data
        self.assertTrue(callable(getattr(engine, "validate", None)), "projected plan validation missing")
        self.assertTrue(engine.validate(plan["id"]).data["valid"])
        name[0] = "external-change"
        self.assertFalse(engine.validate(plan["id"]).data["valid"])
        self.assertEqual(engine.result(plan["id"]).data["digest"], plan["digest"])
        self.assertEqual(self.provider.submissions, [])

    def test_validate_running_plan_requires_reconciliation(self):
        engine = self.engine()
        plan = self.sequence(engine)
        self.provider.task_state = "running"
        engine.apply(plan["id"], plan["digest"], wait=False)
        self.assertTrue(callable(getattr(engine, "validate", None)), "plan validation missing")
        with self.assertRaises(OperationError) as error:
            engine.validate(plan["id"])
        self.assertEqual(error.exception.code, "plan_validation_blocked")

    def test_resume_validation_skips_completed_steps_without_consuming_confirmation(self):
        engine = self.engine()
        plan = self.sequence(engine)
        self.provider.task_state = "running"
        engine.apply(plan["id"], plan["digest"], wait=False)
        self.provider.task_state = "success"
        resume = engine.reconcile(plan["id"])
        self.provider.state = "poweredOff"
        validated = engine.validate(plan["id"])
        self.assertTrue(validated.data["valid"])
        self.assertEqual(validated.data["completed_steps"], [0])
        self.assertEqual([s["position"] for s in validated.data["steps"]], [1])
        self.assertEqual(engine.result(plan["id"]).data["confirmation"], resume.data["confirmation"])
        self.assertEqual(len(self.provider.submissions), 1)

    def test_same_epoch_stale_completion_rechecks_current_steps(self):
        engine = self.engine()
        plan = self.sequence(engine)
        self.provider.observe = lambda *args: {"state": "success" if len(self.provider.submissions) == 1 else "running"}
        result = engine.apply(plan["id"], plan["digest"], wait=False)
        self.assertEqual(result.status, "running")
        # An observer that read only step one reaches its finish after apply exits.
        engine.finish_reconcile(plan["id"], "ready_to_resume", engine.epoch(plan["id"]))
        result = engine.result(plan["id"])
        self.assertEqual(result.status, "running")
        self.assertEqual([s["state"] for s in result.data["execution"]], ["succeeded", "running"])

    def test_reconcile_does_not_submit_later_steps(self):
        engine = self.engine()
        plan = self.sequence(engine)
        self.provider.task_state = "running"
        self.assertEqual(engine.apply(plan["id"], plan["digest"], wait=False).status, "running")
        self.provider.task_state = "success"
        resume = engine.reconcile(plan["id"])
        self.assertEqual(resume.status, "ready_to_resume")
        self.assertEqual(self.provider.submissions, ["vm power-on"])
        # The independent second target still has the previewed state.
        self.provider.state = "poweredOff"
        self.assertEqual(engine.apply(plan["id"], resume.data.get("confirmation", plan["digest"])).status, "succeeded")
        self.assertEqual(self.provider.submissions, ["vm power-on", "vm power-on"])

    def test_failed_first_step_never_submits_second(self):
        engine = self.engine()
        plan = self.sequence(engine)
        self.provider.task_state = "error"
        self.assertEqual(engine.apply(plan["id"], plan["digest"]).status, "failed")
        self.assertEqual(self.provider.submissions, ["vm power-on"])

    def test_archive_rejects_unfinished_plan(self):
        engine = self.engine()
        self.assertTrue(callable(getattr(engine, "archive", None)))
        plan = self.preview(engine).data
        with self.assertRaises(OperationError):
            engine.archive(plan["id"])
        engine.apply(plan["id"], plan["digest"])
        self.assertEqual(engine.archive(plan["id"]).status, "archived")

    def test_rollback_only_previews_compensation_then_records_outcome(self):
        engine = self.engine()
        self.assertTrue(callable(getattr(engine, "rollback", None)))
        plan = engine.preview("vm rename", {"vm_id": "vm-1", "new_name": "new-name"}).data
        engine.apply(plan["id"], plan["digest"])
        rollback = engine.rollback(plan["id"])
        self.assertEqual(rollback.status, "awaiting_confirmation")
        self.assertEqual(rollback.data["payload"]["steps"][0]["params"]["new_name"], "original-name")
        self.assertEqual(len(self.provider.submissions), 1)
        engine.apply(rollback.data["id"], rollback.data["digest"])
        self.assertEqual(engine.result(plan["id"]).status, "compensated")

    def test_destroy_has_no_fabricated_snapshot_rollback(self):
        engine = self.engine()
        self.assertTrue(callable(getattr(engine, "rollback", None)))
        plan = self.preview(engine, "vm delete").data
        engine.apply(plan["id"], plan["digest"], "DESTROY:" + plan["digest"])
        result = engine.rollback(plan["id"])
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error["code"], "compensation_unavailable")
        self.assertEqual(len(self.provider.submissions), 1)

    def test_second_step_failure_is_partial_not_total_failure(self):
        engine = self.engine()
        plan = self.sequence(engine)
        self.provider.observe = lambda *args: {"state": "success" if len(self.provider.submissions) == 1 else "error"}
        self.assertEqual(engine.apply(plan["id"], plan["digest"]).status, "partial")

    def test_reconcile_does_not_erase_compensated_status(self):
        engine = self.engine()
        plan = engine.preview("vm rename", {"vm_id": "vm-1", "new_name": "new-name"}).data
        engine.apply(plan["id"], plan["digest"])
        rollback = engine.rollback(plan["id"]).data
        engine.apply(rollback["id"], rollback["digest"])
        self.assertEqual(engine.reconcile(plan["id"]).status, "compensated")

    def test_cpu_only_compensation_does_not_change_memory(self):
        engine = self.engine()
        original = self.provider.preflight
        def with_hardware(command, params):
            binding = original(command, params)
            binding["before"].update(cpu=2, memory_mb=4096)
            return binding
        self.provider.preflight = with_hardware
        plan = engine.preview("vm reconfigure", {"vm_id": "vm-1", "cpu": 4}).data
        engine.apply(plan["id"], plan["digest"])
        rollback = engine.rollback(plan["id"]).data
        params = rollback["payload"]["steps"][0]["params"]
        self.assertEqual(params, {"vm_id": "vm-1", "cpu": 2})

    def test_multiple_renames_compensate_from_final_to_initial_name(self):
        engine = self.engine()
        current = {"name": "A"}
        preflight, submit = self.provider.preflight, self.provider.submit
        def read(command, p):
            binding = preflight(command, p)
            binding["before"]["name"] = current["name"]
            return binding
        def bind(steps):
            name, bound = current["name"], []
            for step in steps:
                binding = read(step["command"], step["params"])
                binding["before"]["name"] = name
                bound.append({**step, "binding": binding})
                name = step["params"]["new_name"]
            return bound
        def perform(command, p, binding):
            receipt = submit(command, p, binding)
            current["name"] = p["new_name"]
            return receipt
        self.provider.preflight, self.provider.bind_steps, self.provider.submit = read, bind, perform
        self.provider.verify = lambda command, p, *_: current["name"] == p["new_name"]
        plan = engine.preview_steps([{"command": "vm rename", "params": {"vm_id": "vm-1", "new_name": name}} for name in ("B", "C")]).data
        self.assertEqual(engine.apply(plan["id"], plan["digest"]).status, "succeeded")
        rollback = engine.rollback(plan["id"])
        self.assertEqual(rollback.status, "awaiting_confirmation")
        self.assertEqual(len(rollback.data["payload"]["steps"]), 1)
        self.assertEqual(rollback.data["payload"]["steps"][0]["params"]["new_name"], "A")

    def test_resume_requires_a_new_finite_confirmation(self):
        engine = self.engine()
        plan = self.sequence(engine)
        self.provider.task_state = "running"
        engine.apply(plan["id"], plan["digest"], wait=False)
        self.provider.task_state = "success"
        resume = engine.reconcile(plan["id"])
        self.assertEqual(resume.status, "ready_to_resume")
        self.provider.state = "poweredOff"
        with self.assertRaises(OperationError) as error:
            engine.apply(plan["id"], plan["digest"])
        self.assertEqual(error.exception.code, "confirmation_invalid")
        self.assertNotEqual(resume.data["confirmation"], plan["digest"])
        from unittest.mock import patch
        with patch("vcenter_aiops.application.execution.time.time", return_value=resume.data["confirmation_expires"] + 1):
            with self.assertRaises(OperationError):
                engine.apply(plan["id"], resume.data["confirmation"])
        self.assertEqual(self.provider.submissions, ["vm power-on"])

    def test_old_reconcile_cannot_reopen_new_execution_round(self):
        engine = self.engine()
        plan = self.sequence(engine)
        self.provider.task_state = "running"
        engine.apply(plan["id"], plan["digest"], wait=False)
        def delayed(*args):
            from vcenter_aiops.application.execution import Engine
            from vcenter_aiops.infrastructure.store import Store
            from pathlib import Path
            provider = test_execution.FakeProvider()
            provider.state = "poweredOn"
            other = Store(Path(self.temp.name) / "state.db")
            try:
                newer = Engine(other, provider, "lab")
                resume = newer.reconcile(plan["id"])
                provider.state, provider.task_state = "poweredOff", "running"
                result = newer.apply(plan["id"], resume.data["confirmation"], wait=False)
                self.assertEqual(result.status, "running")
            finally:
                other.close()
            return {"state": "running"}
        self.provider.observe = delayed
        result = engine.reconcile(plan["id"])
        self.assertEqual(result.status, "running")
        self.assertEqual([s["state"] for s in result.data["execution"]], ["succeeded", "running"])
