"""Persistent transitions must not turn uncertain submission into a retry."""
from pathlib import Path
import tempfile
import unittest

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store


class OperationStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.db")
        self.op = self.store.prepare("request-1", "server-a:vm-7", {"command": "power-on"})["id"]

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_unknown_submission_keeps_target_locked(self):
        self.assertTrue(callable(getattr(self.store, "mark_unknown", None)), "missing uncertainty transition")
        self.store.claim(self.op)
        self.store.mark_unknown(self.op)
        self.assertEqual(self.store.operation(self.op)["state"], "unknown")
        other = self.store.prepare("request-2", "server-a:vm-7", {})["id"]
        with self.assertRaises(OperationError) as error:
            self.store.claim(other)
        self.assertEqual(error.exception.code, "target_busy")

    def test_only_matching_remote_task_can_complete(self):
        self.assertTrue(callable(getattr(self.store, "observe_task", None)), "missing verified task transition")
        self.store.claim(self.op)
        self.store.submitted(self.op, "server-a:task-9")
        with self.assertRaises(OperationError):
            self.store.observe_task(self.op, "server-b:task-9", "success")
        self.assertEqual(self.store.operation(self.op)["state"], "running")
        self.store.observe_task(self.op, "server-a:task-9", "success")
        self.assertEqual(self.store.operation(self.op)["state"], "succeeded")
        other = self.store.prepare("request-2", "server-a:vm-7", {})["id"]
        self.store.claim(other)
        self.assertEqual(self.store.operation(other)["state"], "submitting")

    def test_missing_task_is_unknown_not_cancelled(self):
        self.assertTrue(callable(getattr(self.store, "mark_unknown", None)), "missing uncertainty transition")
        self.store.claim(self.op)
        self.store.submitted(self.op, "server-a:task-9")
        self.store.mark_unknown(self.op)
        self.assertEqual(self.store.operation(self.op)["remote_task"], "server-a:task-9")
        self.store.observe_task(self.op, "server-a:task-9", "error")
        self.assertEqual(self.store.operation(self.op)["state"], "failed")
        with self.assertRaises(OperationError):
            self.store.mark_unknown(self.op)

    def test_prepared_and_unbound_operations_cannot_be_completed(self):
        self.assertTrue(callable(getattr(self.store, "observe_task", None)), "missing verified task transition")
        with self.assertRaises(OperationError):
            self.store.observe_task(self.op, "server-a:task-9", "success")
        self.store.claim(self.op)
        self.store.mark_unknown(self.op)
        with self.assertRaises(OperationError):
            self.store.observe_task(self.op, "server-a:task-9", "success")
        self.assertEqual(self.store.operation(self.op)["state"], "unknown")
