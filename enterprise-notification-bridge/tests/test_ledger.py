from __future__ import absolute_import

import os
import sys
import tempfile
import threading
import unittest
import warnings
import os.path
import stat
from datetime import datetime, timedelta, timezone


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.ledger import DeliveryKey, DeliveryLedger


KEY = DeliveryKey("report", "dingtalk", "dws-cli", "corp:user", "recipient")


class DeliveryLedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, "delivery-ledger.sqlite3")
        self.ledger = DeliveryLedger(self.path)

    def tearDown(self):
        self.directory.cleanup()

    def test_successful_delivery_cannot_be_claimed_twice(self):
        first = self.ledger.claim(KEY)
        self.assertTrue(first.acquired)

        self.ledger.mark_success(first, "message-id")

        duplicate = self.ledger.claim(KEY)
        self.assertFalse(duplicate.acquired)
        self.assertEqual(duplicate.claim_id, first.claim_id)
        self.assertEqual(self.ledger.get(KEY)["state"], "succeeded")

    def test_retryable_failure_can_be_reclaimed(self):
        first = self.ledger.claim(KEY)
        self.ledger.mark_failure(first, "timeout", retryable=True)

        retry = self.ledger.claim(KEY)

        self.assertTrue(retry.acquired)
        self.assertNotEqual(retry.claim_id, first.claim_id)
        self.assertEqual(self.ledger.get(KEY)["state"], "claimed")

    def test_two_connections_cannot_claim_concurrently(self):
        barrier = threading.Barrier(3)
        acquired = []
        failures = []

        def contender():
            try:
                ledger = DeliveryLedger(self.path)
                barrier.wait()
                acquired.append(ledger.claim(KEY).acquired)
            except Exception as error:
                failures.append(error)

        threads = [threading.Thread(target=contender) for _ in range(2)]
        for thread in threads:
            thread.start()
        barrier.wait()
        for thread in threads:
            thread.join(10)

        self.assertEqual(failures, [])
        self.assertEqual(sorted(acquired), [False, True])

    def test_expired_claim_requires_reconciliation_instead_of_blind_resend(self):
        current = [datetime(2026, 8, 31, tzinfo=timezone.utc)]
        ledger = DeliveryLedger(
            self.path, lease_seconds=30, clock=lambda: current[0]
        )
        first = ledger.claim(KEY)
        current[0] += timedelta(seconds=31)

        stale = ledger.claim(KEY)

        self.assertFalse(stale.acquired)
        self.assertEqual(stale.claim_id, first.claim_id)
        self.assertEqual(stale.reason, "delivery_reconciliation_required")
        self.assertEqual(ledger.get(KEY)["state"], "claimed")

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are unavailable")
    def test_ledger_file_is_user_only(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)

    def test_permanent_failure_cannot_be_reclaimed(self):
        claim = self.ledger.claim(KEY)
        self.ledger.mark_failure(claim, "recipient_not_found", retryable=False)

        self.assertFalse(self.ledger.claim(KEY).acquired)
        self.assertEqual(self.ledger.get(KEY)["state"], "permanent_failure")

    def test_stale_claim_cannot_finish_a_reclaimed_delivery(self):
        first = self.ledger.claim(KEY)
        self.ledger.mark_failure(first, "timeout", retryable=True)
        retry = self.ledger.claim(KEY)

        self.ledger.mark_success(first, "stale-message")

        row = self.ledger.get(KEY)
        self.assertEqual(row["state"], "claimed")
        self.assertEqual(row["claim_id"], retry.claim_id)

    def test_entry_contains_only_delivery_metadata(self):
        claim = self.ledger.claim(KEY)
        self.ledger.mark_success(claim, "message-id")

        row = self.ledger.get(KEY)

        self.assertEqual(set(row.keys()), set((
            "report_id", "platform", "provider", "profile", "recipient",
            "claim_id", "state", "created_at", "updated_at", "reason",
            "retryable", "external_id",
        )))

    def test_claim_does_not_use_a_deprecated_timestamp_api(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", DeprecationWarning)
            self.ledger.claim(KEY)

        self.assertEqual([], [warning for warning in caught
                              if issubclass(warning.category, DeprecationWarning)])


if __name__ == "__main__":
    unittest.main()
