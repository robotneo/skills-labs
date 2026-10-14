import tempfile
import time
import unittest
from pathlib import Path

from vcenter_aiops.application.ipsignals import IpSignals
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store


class IpSignalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.db")
        self.vms = []
        self.moment = [time.time()]
        self.now = lambda: self.moment[0]

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def signals(self, pinger):
        return IpSignals(self.store, self.vms, pinger=pinger, now=self.now)

    def test_check_collects_three_signals(self):
        self.vms = [{"id": "vm-9", "name": "10.0.0.5-web",
                     "guest.ipAddress": "10.0.0.5"}]
        result = self.signals(lambda address: True).check("10.0.0.5", "net-a")
        self.assertEqual(result["ping"]["reachable"], True)
        self.assertEqual(len(result["inventory_use"]), 1)

    def test_available_true_only_with_clear_free_evidence(self):
        result = self.signals(lambda address: False).available("10.0.0.7", "net-a")
        self.assertTrue(result["available"], result)

    def test_available_false_when_inventory_use(self):
        self.vms = [{"id": "vm-3", "name": "host",
                     "guest.ipAddress": "10.0.0.7"}]
        result = self.signals(lambda address: False).available("10.0.0.7", "net-a")
        self.assertFalse(result["available"])
        self.assertIn("inventory_use", result["reasons"])

    def test_available_false_when_ping_reachable(self):
        result = self.signals(lambda address: True).available("10.0.0.7", "net-a")
        self.assertFalse(result["available"])
        self.assertIn("ping_reachable", result["reasons"])

    def test_available_inconclusive_when_ping_unavailable(self):
        result = self.signals(lambda address: None).available("10.0.0.7", "net-a")
        self.assertTrue(result["inconclusive"])
        self.assertFalse(result["available"])
        self.assertIn("ping_inconclusive", result["reasons"])

    def test_available_false_when_active_lease(self):
        self.store.reserve("net-a", "10.0.0.7", "owner", minutes=10)
        result = self.signals(lambda address: False).available("10.0.0.7", "net-a")
        self.assertIn("active_lease", result["reasons"])
        self.assertFalse(result["available"])

    def test_expired_lists_only_past_leases(self):
        self.store.reserve("net-a", "10.0.0.8", "owner", minutes=10)
        self.moment[0] += 20 * 60
        listing = self.signals(lambda address: False).expired()
        self.assertEqual(listing["count"], 1)
        self.assertEqual(listing["items"][0]["ip"], "10.0.0.8")

    def test_expire_release_removes_exact_lease(self):
        lease = self.store.reserve("net-a", "10.0.0.8", "owner", minutes=1)
        self.moment[0] += 5 * 60
        result = self.signals(lambda address: False).expire_release(lease["lease_id"])
        self.assertEqual(result["released"], lease["lease_id"])
        self.assertEqual(self.store.leases(), [])

    def test_expire_release_rejects_unexpired(self):
        lease = self.store.reserve("net-a", "10.0.0.8", "owner", minutes=60)
        with self.assertRaises(OperationError) as error:
            self.signals(lambda address: False).expire_release(lease["lease_id"])
        self.assertEqual(error.exception.code, "lease_not_expired")


if __name__ == "__main__":
    unittest.main()
