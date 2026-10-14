import importlib.util
from pathlib import Path
import tempfile
import unittest

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store


class SearchProvider:
    def __init__(self):
        self.calls = 0
        self.state = "running"
        self.lost = False

    def prepare(self, **params):
        return {**params, "server_uuid": "server-a", "datastore_name": "data"}

    def submit(self, scope):
        self.calls += 1
        if self.lost:
            raise OSError("response contains secret")
        return {**scope, "task_id": "task-1"}

    def observe(self, receipt, timeout):
        if self.state == "missing":
            raise OSError("task evicted")
        return {**receipt, "state": self.state, "items": [{"name": "boot.iso"}] if self.state == "succeeded" else []}


class SearchRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.db")
        self.provider = SearchProvider()
        self.params = {"datastore_id": "datastore-1", "path": "images", "limit": 10, "images_only": True, "recursive": True}

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def engine(self, profile="lab"):
        self.assertIsNotNone(importlib.util.find_spec("vcenter_aiops.application.searches"), "durable search lifecycle missing")
        from vcenter_aiops.application.searches import Searches
        return Searches(self.store, self.provider, profile)

    def test_restart_observes_original_task_and_caches_completed_results(self):
        started = self.engine().start(self.params, "request-1", 0)
        self.assertEqual(started.status, "running")
        self.store.close()
        self.store = Store(Path(self.temp.name) / "state.db")
        self.provider.state = "succeeded"
        completed = self.engine().reconcile(started.operation_id, 0)
        self.assertEqual(completed.status, "succeeded")
        self.assertEqual(completed.data["result"]["items"], [{"name": "boot.iso"}])
        self.provider.state = "missing"
        self.assertEqual(self.engine().reconcile(started.operation_id, 0).status, "succeeded")
        self.assertEqual(self.provider.calls, 1)

    def test_duplicate_request_reuses_original_search(self):
        first = self.engine().start(self.params, "same", 0)
        second = self.engine().start(self.params, "same", 0)
        self.assertEqual(first.operation_id, second.operation_id)
        self.assertEqual(self.provider.calls, 1)
        with self.assertRaises(OperationError):
            self.engine().start({**self.params, "path": "other"}, "same", 0)

    def test_lost_submit_response_never_reissues_search(self):
        self.provider.lost = True
        first = self.engine().start(self.params, "lost", 0)
        self.assertEqual(first.status, "reconciliation_required")
        self.assertNotIn("secret", str(first.to_dict()))
        self.provider.lost = False
        self.engine().start(self.params, "lost", 0)
        self.engine().reconcile(first.operation_id, 0)
        self.assertEqual(self.provider.calls, 1)

    def test_other_profile_cannot_reconcile_or_read_search(self):
        first = self.engine().start(self.params, "req", 0)
        with self.assertRaises(OperationError) as error:
            self.engine("other").reconcile(first.operation_id, 0)
        self.assertEqual(error.exception.code, "profile_mismatch")

    def test_missing_task_remains_uncertain_and_can_later_be_observed(self):
        first = self.engine().start(self.params, "req", 0)
        self.provider.state = "missing"
        self.assertEqual(self.engine().reconcile(first.operation_id, 0).status, "reconciliation_required")
        self.provider.state = "succeeded"
        self.assertEqual(self.engine().reconcile(first.operation_id, 0).status, "succeeded")
        self.assertEqual(self.provider.calls, 1)

    def test_concurrent_requests_only_submit_once(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from vcenter_aiops.application.searches import Searches
        self.engine()  # Initialize the schema before both connections start.
        barrier = threading.Barrier(2)
        prepare = self.provider.prepare
        def aligned(**params):
            scope = prepare(**params)
            barrier.wait(timeout=5)
            return scope
        self.provider.prepare = aligned
        def run():
            store = Store(Path(self.temp.name) / "state.db")
            try:
                return Searches(store, self.provider, "lab").start(self.params, "concurrent", 0)
            finally:
                store.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: run(), range(2)))
        self.assertEqual(results[0].operation_id, results[1].operation_id)
        self.assertEqual(self.provider.calls, 1)

    def test_late_observer_cannot_regress_saved_success(self):
        from vcenter_aiops.application.searches import Searches
        first = self.engine().start(self.params, "late", 0)
        def delayed(receipt, timeout):
            store = Store(Path(self.temp.name) / "state.db")
            provider = SearchProvider()
            provider.state = "succeeded"
            try:
                result = Searches(store, provider, "lab").reconcile(first.operation_id, 0)
                self.assertEqual(result.status, "succeeded")
            finally:
                store.close()
            return {**receipt, "state": "running"}
        self.provider.observe = delayed
        result = self.engine().reconcile(first.operation_id, 0)
        self.assertEqual(result.status, "succeeded")
        self.assertEqual(result.data["result"]["items"], [{"name": "boot.iso"}])
