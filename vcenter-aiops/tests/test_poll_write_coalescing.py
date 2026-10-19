"""M-1: polling must not fsync three writes on every unchanged running tick.

A long task is observed many times while still running. Plan A persists only when
the operation state or canonical observation actually changes; repeated identical
running observations skip the operations/steps/audit writes (no WAL introduced).
State transitions and the terminal write still persist on first sighting.
"""
from pathlib import Path
import tempfile
import unittest

from vcenter_aiops.infrastructure.store import Store
from test_execution import FakeProvider


class CountingProvider(FakeProvider):
    def __init__(self, running_ticks=3):
        super().__init__()
        self.running_ticks = running_ticks
        self.observations = 0

    def observe(self, receipt, binding):
        self.observations += 1
        if self.observations <= self.running_ticks:
            # Identical content on every running tick: same state AND same
            # progress payload, so canonical(observation) is byte-identical.
            return {"state": "running", "cancelled": False, "progress": 10}
        return {"state": "success", "cancelled": False, "progress": 100}

    def verify(self, command, params, binding, observation):
        return observation.get("state") == "success"


class PollWriteCoalescingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _audit_count(self, event, operation_id):
        return self.store.db.execute(
            "SELECT COUNT(*) FROM audit WHERE event=? AND subject=?",
            (event, operation_id)).fetchone()[0]

    def test_identical_running_ticks_write_once_then_terminal_writes(self):
        from vcenter_aiops.application.execution import Engine
        provider = CountingProvider(running_ticks=3)
        engine = Engine(self.store, provider, "lab")
        plan = engine.preview("vm power-on", {"vm_id": "vm-1"}, "req-m1").data
        result = engine.apply(plan["id"], plan["digest"], wait=True)
        self.assertEqual(result.status, "succeeded")
        # 3 identical running observations + 1 success were actually polled.
        self.assertEqual(provider.observations, 4)
        operation_id = result.operation_id
        # First running tick persists once (observation goes None -> value);
        # the next two identical ticks must not add operation_running audits.
        self.assertEqual(self._audit_count("operation_running", operation_id), 1)
        # Terminal transition is always persisted exactly once.
        self.assertEqual(self._audit_count("operation_succeeded", operation_id), 1)
        self.assertEqual(self.store.operation(operation_id)["state"], "succeeded")

    def test_progress_change_still_persists_running_update(self):
        # When the running observation content changes (progress advances) the
        # step observation is updated even though the state stays running.
        from vcenter_aiops.application.execution import Engine

        class AdvancingProvider(CountingProvider):
            def observe(self, receipt, binding):
                self.observations += 1
                if self.observations == 1:
                    return {"state": "running", "cancelled": False, "progress": 10}
                if self.observations == 2:
                    return {"state": "running", "cancelled": False, "progress": 50}
                return {"state": "success", "cancelled": False, "progress": 100}

        provider = AdvancingProvider()
        engine = Engine(self.store, provider, "lab")
        plan = engine.preview("vm power-on", {"vm_id": "vm-1"}, "req-m1b").data
        result = engine.apply(plan["id"], plan["digest"], wait=True)
        self.assertEqual(result.status, "succeeded")
        operation_id = result.operation_id
        # Two distinct running observations -> two running persistence points.
        self.assertEqual(self._audit_count("operation_running", operation_id), 2)
        self.assertEqual(self._audit_count("operation_succeeded", operation_id), 1)


if __name__ == "__main__":
    unittest.main()
