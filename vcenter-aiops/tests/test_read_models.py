import importlib.util
from types import SimpleNamespace as NS
import unittest


class ReadModelTests(unittest.TestCase):
    def reader(self):
        self.assertIsNotNone(importlib.util.find_spec("vcenter_aiops.providers.vsphere.reads"), "read models missing")
        from vcenter_aiops.providers.vsphere.reads import Reads
        return Reads

    def test_snapshot_tree_has_precise_ids_not_only_names(self):
        Reads = self.reader()
        child = NS(snapshot=NS(_moId="snapshot-2"), name="same", description="<script>", state="poweredOff", createTime=None, childSnapshotList=[])
        root = NS(snapshot=NS(_moId="snapshot-1"), name="same", description="", state="poweredOff", createTime=None, childSnapshotList=[child])
        vm = NS(snapshot=NS(rootSnapshotList=[root]))
        provider = NS(vm=lambda _: vm)
        data = Reads(provider).snapshots("vm-1", 100)
        self.assertEqual([i["id"] for i in data["items"]], ["snapshot-1", "snapshot-2"])
        self.assertEqual(data["items"][1]["parent_id"], "snapshot-1")
        self.assertTrue(data["untrusted_content"])

    def test_snapshot_limit_marks_truncation(self):
        Reads = self.reader()
        roots = [NS(snapshot=NS(_moId=f"snapshot-{i}"), name="n", description="", state="poweredOff", createTime=None, childSnapshotList=[]) for i in range(3)]
        data = Reads(NS(vm=lambda _: NS(snapshot=NS(rootSnapshotList=roots)))).snapshots("vm-1", 1)
        self.assertTrue(data["truncated"])
        self.assertEqual(len(data["items"]), 1)

    def test_tools_status_reports_not_running_without_fabricating_ip(self):
        Reads = self.reader()
        vm = NS(guest=NS(toolsRunningStatus="guestToolsNotRunning", toolsVersionStatus2="guestToolsNotInstalled", ipAddress=None, guestFamily="linuxGuest"), runtime=NS(powerState="poweredOff"))
        data = Reads(NS(vm=lambda _: vm)).tools("vm-1")
        self.assertFalse(data["ready"])
        self.assertIsNone(data["ip_address"])
