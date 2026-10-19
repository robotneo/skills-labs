"""M-10 regression: a non-serialisable post-write observation is unknown/6.

Provider observations are JSON values, but a remote-controlled free-text field
(entity name, error message) can in principle carry a lone UTF-16 surrogate or an
object the canonicaliser cannot dump. Persistence happens through
``canonical(observation)`` -> a SQLite TEXT bind (UTF-8): a lone surrogate dumps
fine but the bind raises UnicodeEncodeError, and a non-JSON value raises TypeError.

That failure occurs AFTER the remote write was already submitted, so it must never
surface as internal_error (5) -- which looks like a local bug and invites a retry
-- nor trigger any resubmission. It is an unprovable result: the engine must store
a structured unknown observation (code ``observation_unserializable``), keep the
operation id for reconciliation, and report reconciliation_required (6).
"""
from pathlib import Path
import tempfile
import unittest

from vcenter_aiops.infrastructure.store import Store
from test_execution import FakeProvider


class LoneSurrogateProvider(FakeProvider):
    def observe(self, receipt, binding):
        # success with a remote-controlled name carrying a lone surrogate.
        return {"state": "success", "cancelled": False,
                "entity_name": "vm-\ud800-name"}

    def verify(self, command, params, binding, observation):
        return True


class NonJsonProvider(FakeProvider):
    def observe(self, receipt, binding):
        return {"state": "success", "cancelled": False, "weird": object()}

    def verify(self, command, params, binding, observation):
        return True


class ObservationSerialiseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _apply(self, provider):
        from vcenter_aiops.application.execution import Engine
        engine = Engine(self.store, provider, "lab")
        plan = engine.preview("vm power-on", {"vm_id": "vm-1"}, "req-m10").data
        result = engine.apply(plan["id"], plan["digest"], wait=True)
        return result

    def test_lone_surrogate_observation_becomes_structured_unknown_6(self):
        provider = LoneSurrogateProvider()
        result = self._apply(provider)
        # No exception escapes; the write is not retried (exactly one submit).
        self.assertEqual(provider.submissions, ["vm power-on"])
        self.assertEqual(result.status, "reconciliation_required")
        self.assertTrue(result.operation_id)

    def test_non_json_observation_becomes_structured_unknown_6(self):
        provider = NonJsonProvider()
        result = self._apply(provider)
        self.assertEqual(provider.submissions, ["vm power-on"])
        self.assertEqual(result.status, "reconciliation_required")
        self.assertTrue(result.operation_id)


if __name__ == "__main__":
    unittest.main()
