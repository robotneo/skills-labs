"""R-6: datastore search submit must split deterministic pre-write rejection
(SubmissionRejected -> failed, exit 4, no task launched) from an unobservable
post-write failure (generic exception -> reconciliation_required, exit 6, never
auto-resubmitted). All offline with fakes."""
from pathlib import Path
import tempfile
import unittest

from vcenter_aiops.domain.models import OperationError, SubmissionRejected
from vcenter_aiops.infrastructure.store import Store
from vcenter_aiops.application.searches import Searches


class _BaseProvider:
    def __init__(self):
        self.submit_calls = 0

    def prepare(self, **params):
        return {**params, "server_uuid": "server-a", "datastore_name": "data"}

    def observe(self, receipt, timeout):
        return {**receipt, "state": "running", "items": []}


class _RejectedBeforeWrite(_BaseProvider):
    def submit(self, scope):
        self.submit_calls += 1
        # Mirrors datastores.Datastores.submit: a pre-write guard proves no
        # browse task was launched.
        raise SubmissionRejected("search_scope_changed", "搜索范围或服务端身份已变化", 4)


class _LostAfterWrite(_BaseProvider):
    def submit(self, scope):
        self.submit_calls += 1
        raise OSError("response lost after the task was launched: secret-token")


class SearchSubmitClassificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "state.db")
        self.addCleanup(self.store.close)
        self.params = {"datastore_id": "datastore-1", "path": "images",
                       "limit": 10, "images_only": False, "recursive": False}

    def engine(self, provider):
        return Searches(self.store, provider, "lab")

    def test_prewrite_rejection_is_failed_exit4_and_not_resent(self):
        provider = _RejectedBeforeWrite()
        engine = self.engine(provider)
        with self.assertRaises(SubmissionRejected) as ctx:
            engine.start(self.params, "rejected-req", 0)
        self.assertEqual(ctx.exception.code, "search_scope_changed")
        self.assertEqual(ctx.exception.exit_code, 4)
        self.assertEqual(provider.submit_calls, 1)
        # The durable row must record a terminal failed/not_submitted outcome.
        rows = list(self.store.db.execute(
            "SELECT state, result FROM datastore_searches WHERE request_id=?",
            ("rejected-req",)))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "failed")
        self.assertIn("not_submitted", rows[0]["result"])
        # Retrying the same request id must not call submit again; it reads back
        # the terminal failed result rather than raising.
        again = self.engine(provider).start(self.params, "rejected-req", 0)
        self.assertEqual(again.status, "failed")
        self.assertEqual(provider.submit_calls, 1)

    def test_generic_postwrite_failure_stays_reconciliation_required(self):
        provider = _LostAfterWrite()
        result = self.engine(provider).start(self.params, "lost-req", 0)
        self.assertEqual(result.status, "reconciliation_required")
        self.assertEqual(provider.submit_calls, 1)
        # The untrusted fault text must never be persisted or returned.
        self.assertNotIn("secret-token", str(result.to_dict()))

    def test_plain_operation_error_is_not_treated_as_prewrite_guarantee(self):
        # Negative case: only the explicit SubmissionRejected guarantee may be
        # classified as deterministic; a generic OperationError raised by submit
        # still happens around the write boundary and must stay uncertain.
        class _PlainOpError(_BaseProvider):
            def submit(self, scope):
                self.submit_calls += 1
                raise OperationError("some_fault", "未证明写未发起", 5)
        provider = _PlainOpError()
        result = self.engine(provider).start(self.params, "plain-req", 0)
        self.assertEqual(result.status, "reconciliation_required")
        self.assertEqual(provider.submit_calls, 1)


if __name__ == "__main__":
    unittest.main()
