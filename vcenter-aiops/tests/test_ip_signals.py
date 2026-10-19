import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path

from vcenter_aiops.application.commands import local as local_commands
from vcenter_aiops.application.ipsignals import IpSignals, require_ip_address
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

    def test_require_ip_address_accepts_literal_ips(self):
        for value in ("10.0.0.7", "192.168.1.1", "::1", "2001:db8::1"):
            self.assertEqual(require_ip_address(value), value)

    def test_check_rejects_ping_option_injection(self):
        # A leading dash would be parsed by ping as an option; it must be
        # rejected before the pinger is ever invoked (argv list, but option
        # injection still applies).
        calls = []

        def pinger(address):
            calls.append(address)
            return None

        for bad in ("-c10", "-D", "--adaptive", "example.com", "10.0.0.0/24",
                    "10.0.0.1 extra", 1234):
            with self.assertRaises(OperationError) as error:
                self.signals(pinger).check(bad, "net-a")
            self.assertEqual(error.exception.code, "invalid_arguments")
            with self.assertRaises(OperationError):
                self.signals(pinger).available(bad, "net-a")
        self.assertEqual(calls, [])


class IpExpireCommandTests(unittest.TestCase):
    """Regression for D5: ``ip expire --apply`` without a lease_id must surface
    a structured ``invalid_arguments`` error instead of raising a KeyError that
    the CLI swallows into a generic ``internal_error`` (exit 5)."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.db")
        self.moment = [time.time()]

        @contextmanager
        def store_cm():
            try:
                yield self.store
            finally:
                pass

        class Ctx:
            pass

        self.ctx = Ctx()
        self.ctx.store = store_cm

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _patched_signals(self):
        # Pin the clock used by expire_release so an expired lease is recognised.
        return IpSignals(self.store, [], pinger=lambda a: False,
                         now=lambda: self.moment[0])

    def test_apply_without_lease_id_is_invalid_arguments(self):
        with self.assertRaises(OperationError) as error:
            local_commands.ip_expire(self.ctx, {"apply": True})
        self.assertEqual(error.exception.code, "invalid_arguments")

    def test_apply_with_empty_lease_id_is_invalid_arguments(self):
        with self.assertRaises(OperationError) as error:
            local_commands.ip_expire(self.ctx, {"apply": True, "lease_id": ""})
        self.assertEqual(error.exception.code, "invalid_arguments")

    def test_apply_with_lease_id_still_reaches_domain_logic(self):
        # An explicit, non-expired lease must hit the domain rule unchanged.
        lease = self.store.reserve("net-a", "10.0.0.9", "owner", minutes=60)
        with self.assertRaises(OperationError) as error:
            local_commands.ip_expire(self.ctx, {"apply": True,
                                                "lease_id": lease["lease_id"]})
        self.assertEqual(error.exception.code, "lease_not_expired")

    def test_apply_releases_expired_lease(self):
        lease = self.store.reserve("net-a", "10.0.0.9", "owner", minutes=1)
        self.moment[0] += 5 * 60
        # The handler imports IpSignals lazily from ..ipsignals, so patch there.
        from vcenter_aiops.application import ipsignals
        real = ipsignals.IpSignals
        ipsignals.IpSignals = lambda store, vms, **kw: self._patched_signals()
        try:
            result = local_commands.ip_expire(
                self.ctx, {"apply": True, "lease_id": lease["lease_id"]})
            self.assertEqual(result.data["released"], lease["lease_id"])
            self.assertEqual(self.store.leases(), [])
        finally:
            ipsignals.IpSignals = real

    def test_listing_without_apply_ignores_lease_id(self):
        self.store.reserve("net-a", "10.0.0.9", "owner", minutes=1)
        result = local_commands.ip_expire(self.ctx, {"apply": False})
        self.assertEqual(result.data["count"], 0)


if __name__ == "__main__":
    unittest.main()
