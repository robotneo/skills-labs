import unittest
from types import SimpleNamespace as NS

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.providers.vsphere.ovf_lease import drive, state_name, upload_targets


def url(target="https://vc/nfc/disk1.vmdk", upload=True, thumb="AA:BB"):
    return NS(url=target, upload=upload, sslThumbprint=thumb, capacity=1024)


class FakeLease:
    """Scripted HttpNfcLease that flips state on observe calls."""

    def __init__(self, states, files=None, device=None):
        self._states = list(states)
        self.info = NS(deviceUrl=device or [url()],
                       entity=NS(name="vm-imported"))
        self.completed = []

    @property
    def state(self):
        current = self._states[0]
        if len(self._states) > 1:
            self._states.pop(0)
        return current

    def HttpNfcLeaseComplete(self):
        self.completed.append(True)


class StateNameTests(unittest.TestCase):
    def test_strips_enum_prefix(self):
        class State:
            def __init__(self, value):
                self.value = value

            def __str__(self):
                return self.value

        self.assertEqual(state_name(State("vim.HttpNfcLease.State.ready")), "ready")
        self.assertEqual(state_name("ready"), "ready")
        self.assertEqual(state_name("State.done"), "done")


class UploadTargetsTests(unittest.TestCase):
    def test_pairs_in_order(self):
        info = NS(deviceUrl=[url("u1"), url("u2")])
        targets = upload_targets(info, ["a.vmdk", "b.vmdk"])
        self.assertEqual([t["file"] for t in targets], ["a.vmdk", "b.vmdk"])
        self.assertEqual([t["url"] for t in targets], ["u1", "u2"])

    def test_skips_non_upload_entries(self):
        info = NS(deviceUrl=[url("u1"), url("u2", upload=False)])
        targets = upload_targets(info, ["a.vmdk"])
        self.assertEqual(len(targets), 1)

    def test_count_mismatch_rejected(self):
        info = NS(deviceUrl=[url(), url()])
        with self.assertRaises(OperationError) as ctx:
            upload_targets(info, ["a.vmdk"])
        self.assertEqual(ctx.exception.code, "ovf_lease_mismatch")

    def test_missing_url_rejected(self):
        info = NS(deviceUrl=[url(target="")])
        with self.assertRaises(OperationError) as ctx:
            upload_targets(info, ["a.vmdk"])
        self.assertEqual(ctx.exception.code, "ovf_lease_url_missing")


class DriveTests(unittest.TestCase):
    def test_happy_path_uploads_then_completes(self):
        lease = FakeLease(["initializing", "ready", "transferring", "done"])
        uploaded = []

        def upload(target, info):
            uploaded.append(target["file"])

        result = drive(lease, ["a.vmdk"], upload, sleep=lambda s: None)
        self.assertEqual(uploaded, ["a.vmdk"])
        self.assertEqual(lease.completed, [True])
        self.assertEqual(result.entity.name, "vm-imported")

    def test_uploads_only_once_when_ready_repeated(self):
        lease = FakeLease(["ready", "ready", "done"])
        calls = []
        drive(lease, ["a.vmdk"], lambda t, i: calls.append(t), sleep=lambda s: None)
        self.assertEqual(len(calls), 1)

    def test_lease_error_fails_without_upload(self):
        lease = FakeLease(["error"])
        lease.error = NS(__class__=NS(__name__="LeaseError"))
        with self.assertRaises(OperationError) as ctx:
            drive(lease, ["a.vmdk"], lambda t, i: None, sleep=lambda s: None)
        self.assertEqual(ctx.exception.code, "ovf_import_failed")
        self.assertEqual(lease.completed, [])

    def test_unknown_state_is_uncertainty(self):
        lease = FakeLease(["mystery"])
        with self.assertRaises(OperationError) as ctx:
            drive(lease, ["a.vmdk"], lambda t, i: None, sleep=lambda s: None)
        self.assertEqual(ctx.exception.code, "ovf_lease_unknown")

    def test_deadline_during_initializing_times_out(self):
        lease = FakeLease(["initializing"])
        clock = iter([0.0, 10.0])
        with self.assertRaises(OperationError) as ctx:
            drive(lease, ["a.vmdk"], lambda t, i: None,
                  sleep=lambda s: None, clock=lambda: next(clock), deadline=5.0)
        self.assertEqual(ctx.exception.code, "ovf_import_timeout")

    def test_upload_error_propagates_not_swallowed(self):
        lease = FakeLease(["ready", "done"])

        def boom(target, info):
            raise ConnectionError("put failed")

        with self.assertRaises(ConnectionError):
            drive(lease, ["a.vmdk"], boom, sleep=lambda s: None)


if __name__ == "__main__":
    unittest.main()
