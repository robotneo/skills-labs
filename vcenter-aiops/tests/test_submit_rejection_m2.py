"""M-2 regression: hosts/clusters/creation submit wraps pre-write rejections.

All three providers re-run read-only preflight inside submit() to detect a plan
that went stale between preview and confirmation. That recheck -- plus capability
validation and target resolution that happen before the write call -- is a
*deterministic* failure: no remote write was issued, so it is safe to retry and
must surface as SubmissionRejected (exit 4), aligned with ovf_deploy/mutations.
Previously the recheck sat outside any guarantee block, so a plain
OperationError(plan_stale) fell through the engine's generic handler into
"result unknown / reconcile" (exit 6), implying a write that never happened.
"""
from types import SimpleNamespace as NS
import unittest

from vcenter_aiops.domain.models import OperationError, SubmissionRejected
from vcenter_aiops.providers.vsphere.clusters import Clusters
from vcenter_aiops.providers.vsphere.creation import Creation
from vcenter_aiops.providers.vsphere.hosts import Hosts


def make_provider(cls):
    content = NS(about=NS(instanceUuid="server-1"))
    si = NS(RetrieveContent=lambda: content, _stub=None)
    return cls(si, resolver=lambda kind, oid: None)


class SubmitPreWriteRejectionTests(unittest.TestCase):
    def _assert_plan_stale_rejected(self, provider, command, params):
        binding = {"a": 1}
        # Force the in-submit preflight recheck to disagree with the binding.
        provider.preflight = lambda cmd, p: {"a": 2}
        with self.assertRaises(SubmissionRejected) as raised:
            provider.submit(command, params, binding)
        self.assertEqual(raised.exception.code, "plan_stale")
        self.assertEqual(raised.exception.exit_code, 4)

    def test_hosts_plan_stale_is_submission_rejected(self):
        provider = make_provider(Hosts)
        self._assert_plan_stale_rejected(
            provider, "host maintenance-exit", {"host_id": "host-1"})

    def test_clusters_plan_stale_is_submission_rejected(self):
        provider = make_provider(Clusters)
        self._assert_plan_stale_rejected(
            provider, "cluster delete", {"cluster_id": "domain-c1"})

    def test_creation_plan_stale_is_submission_rejected(self):
        provider = make_provider(Creation)
        self._assert_plan_stale_rejected(
            provider, "vm create", {"name": "new-vm"})

    def test_submission_rejected_is_still_an_operation_error(self):
        # The engine catches SubmissionRejected specifically; it must remain an
        # OperationError subclass so generic handling is not broken elsewhere.
        provider = make_provider(Hosts)
        provider.preflight = lambda cmd, p: {"a": 2}
        with self.assertRaises(OperationError):
            provider.submit("host maintenance-exit", {"host_id": "host-1"},
                            {"a": 1})


if __name__ == "__main__":
    unittest.main()
