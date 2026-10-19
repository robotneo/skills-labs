"""M-1 regression: stale snapshot at submit is a pre-write rejection, not unknown.

``vm snapshot-revert`` / ``vm snapshot-delete`` re-resolve the snapshot inside
their submit method. If the snapshot was deleted externally between preview and
confirmation, that last re-read deterministically fails with snapshot_not_found
*before any write is issued*. It is a safe-to-retry precondition failure
(SubmissionRejected -> exit 4); it must not fall through the generic post-write
handler that marks the operation "result unknown / reconcile" (exit 6) and tempts
a resubmit of a destructive revert/delete.

Read sequence that matters: the explicit preflight in the test is tree read #1;
submit() re-runs preflight through matches() (read #2); the per-command submit
method then re-resolves the snapshot (read #3). The tree is healthy for reads
1-2 and goes dangling on read #3.
"""
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from pyVmomi import vim, vmodl

from vcenter_aiops.domain.models import SubmissionRejected
from vcenter_aiops.providers.vsphere.mutations import Mutations


def _monf(snapshot_id):
    ref = vim.VirtualMachineSnapshot(snapshot_id, object())
    return vmodl.fault.ManagedObjectNotFound(obj=ref)


class FlipNode:
    def __init__(self, snapshot_id, method_name, write_recorder, go_stale_on_read):
        self._reads = 0
        self._go_stale_on_read = go_stale_on_read

        def write(**kwargs):
            write_recorder.append((snapshot_id, kwargs))
            return NS(_moId="task-9")

        self.snapshot = NS(_moId=snapshot_id, **{method_name: write})

    @property
    def childSnapshotList(self):
        self._reads += 1
        if self._reads >= self._go_stale_on_read:
            raise _monf(self.snapshot._moId)
        return []


def make_provider(node, written):
    vm = NS(
        _moId="vm-1", name="test-vm", disabledMethod=[],
        config=NS(instanceUuid="uuid-1", changeVersion="1", template=False,
                  hardware=NS(numCPU=2, memoryMB=2048)),
        runtime=NS(powerState="poweredOff", connectionState="connected"),
        guest=NS(toolsRunningStatus="guestToolsRunning"),
        snapshot=NS(rootSnapshotList=[node]))
    content = NS(
        about=NS(instanceUuid="server-1", apiVersion="6.5", apiType="VirtualCenter"),
        sessionManager=NS(currentSession=NS(key="session-1")),
        authorizationManager=NS(
            HasPrivilegeOnEntity=lambda **kw: [True for _ in kw["privId"]]))
    si = NS(RetrieveContent=lambda: content, _stub=None)
    return Mutations(si, resolver=lambda kind, oid: vm)


class SnapshotSubmitStaleTests(unittest.TestCase):
    def _assert_stale_rejected(self, command, method_name, write_kwargs):
        written = []
        node = FlipNode("snapshot-1", method_name, written, go_stale_on_read=3)
        provider = make_provider(node, written)
        params = {"vm_id": "vm-1", "snapshot_id": "snapshot-1"}
        # linked.guard is an independent fail-closed dependency gate unrelated to
        # the submit-time resolution under test; neutralize it for both reads.
        with patch("vcenter_aiops.providers.vsphere.linked.guard", lambda *a, **k: None):
            binding = provider.preflight(command, params)   # read #1 healthy
            with self.assertRaises(SubmissionRejected) as raised:
                provider.submit(command, params, binding)   # #2 healthy, #3 stale
        self.assertEqual(raised.exception.code, "snapshot_not_found")
        self.assertEqual(raised.exception.exit_code, 4)
        self.assertEqual(written, [])  # write method never invoked

    def test_stale_snapshot_revert_is_rejected_before_write(self):
        self._assert_stale_rejected(
            "vm snapshot-revert", "RevertToSnapshot_Task",
            {"suppressPowerOn": True})

    def test_stale_snapshot_delete_is_rejected_before_write(self):
        self._assert_stale_rejected(
            "vm snapshot-delete", "RemoveSnapshot_Task",
            {"removeChildren": False})

    def test_healthy_revert_still_issues_exactly_one_write(self):
        written = []
        node = FlipNode("snapshot-1", "RevertToSnapshot_Task", written,
                        go_stale_on_read=10_000)  # never goes stale
        provider = make_provider(node, written)
        params = {"vm_id": "vm-1", "snapshot_id": "snapshot-1"}
        with patch("vcenter_aiops.providers.vsphere.linked.guard", lambda *a, **k: None):
            binding = provider.preflight("vm snapshot-revert", params)
            receipt = provider.submit("vm snapshot-revert", params, binding)
        self.assertEqual(receipt["task_id"], "server-1:task-9")
        self.assertEqual(written, [("snapshot-1", {"suppressPowerOn": True})])


if __name__ == "__main__":
    unittest.main()
