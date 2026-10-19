"""L-8: the ping probe timeout must be a configurable budget, not a hard-coded
``subprocess.run(timeout=4)``. Default behaviour and fail-open (timeout/launch
failure -> None/inconclusive) are preserved; the budget is overridable per call
and via ``VCENTER_AIOPS_PING_TIMEOUT`` (clamped to 1-30s).
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vcenter_aiops.application import ipsignals
from vcenter_aiops.application.ipsignals import ping_probe, IpSignals
from vcenter_aiops.infrastructure.store import Store


class PingTimeoutTests(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("VCENTER_AIOPS_PING_TIMEOUT")
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.db")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
        if self._old is None:
            os.environ.pop("VCENTER_AIOPS_PING_TIMEOUT", None)
        else:
            os.environ["VCENTER_AIOPS_PING_TIMEOUT"] = self._old

    def _capturing_run(self, captured, returncode=1):
        def fake_run(command, capture_output, timeout):
            captured["command"] = command
            captured["timeout"] = timeout
            return subprocess.CompletedProcess(command, returncode, b"", b"")
        return fake_run

    def test_default_timeout_is_four_seconds(self):
        os.environ.pop("VCENTER_AIOPS_PING_TIMEOUT", None)
        self.assertEqual(ipsignals.resolve_ping_timeout(), 4)
        captured = {}
        with patch.object(ipsignals.subprocess, "run", self._capturing_run(captured, 0)):
            self.assertIs(ping_probe("10.0.0.1"), True)
        self.assertEqual(captured["timeout"], 4)

    def test_explicit_timeout_is_passed(self):
        captured = {}
        with patch.object(ipsignals.subprocess, "run", self._capturing_run(captured)):
            ping_probe("10.0.0.1", timeout=10)
        self.assertEqual(captured["timeout"], 10)

    def test_env_override_is_resolved_and_clamped(self):
        os.environ["VCENTER_AIOPS_PING_TIMEOUT"] = "12"
        self.assertEqual(ipsignals.resolve_ping_timeout(), 12)
        os.environ["VCENTER_AIOPS_PING_TIMEOUT"] = "999"
        self.assertEqual(ipsignals.resolve_ping_timeout(), 30)
        os.environ["VCENTER_AIOPS_PING_TIMEOUT"] = "0"
        self.assertEqual(ipsignals.resolve_ping_timeout(), 1)
        os.environ["VCENTER_AIOPS_PING_TIMEOUT"] = "soon"
        self.assertEqual(ipsignals.resolve_ping_timeout(), 4)

    def test_env_override_reaches_default_pinger_via_ipsignals(self):
        os.environ["VCENTER_AIOPS_PING_TIMEOUT"] = "12"
        captured = {}
        signals = IpSignals(self.store, [])
        with patch.object(ipsignals.subprocess, "run", self._capturing_run(captured)):
            signals.check("10.0.0.7", "net-a")
        self.assertEqual(captured["timeout"], 12)

    def test_timeout_still_fails_open_to_none(self):
        def raise_timeout(command, capture_output, timeout):
            raise subprocess.TimeoutExpired(command, timeout)

        with patch.object(ipsignals.subprocess, "run", raise_timeout):
            self.assertIsNone(ping_probe("10.0.0.1", timeout=1))

    def test_custom_pinger_keeps_single_argument_contract(self):
        # Injected pingers (the common offline seam) keep pinger(address); the
        # timeout only binds the built-in default probe.
        passed = {}

        def custom_pinger(address):
            passed["address"] = address
            return False

        signals = IpSignals(self.store, [], pinger=custom_pinger, ping_timeout=8)
        signals.check("10.0.0.7", "net-a")
        self.assertEqual(passed, {"address": "10.0.0.7"})
        self.assertEqual(signals.ping_timeout, 8)

    def test_ipsignals_wraps_default_pinger_with_configured_budget(self):
        captured = {}
        signals = IpSignals(self.store, [], ping_timeout=6)
        with patch.object(ipsignals.subprocess, "run", self._capturing_run(captured)):
            signals.check("10.0.0.7", "net-a")
        self.assertEqual(captured["timeout"], 6)


if __name__ == "__main__":
    unittest.main()

