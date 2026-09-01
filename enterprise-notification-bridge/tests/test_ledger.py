from __future__ import absolute_import

import os
import sys
import tempfile
import unittest
import warnings


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
        first = DeliveryLedger(self.path)
        second = DeliveryLedger(self.path)

        self.assertTrue(first.claim(KEY).acquired)
        self.assertFalse(second.claim(KEY).acquired)

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
