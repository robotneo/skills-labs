from datetime import datetime, timezone
from types import SimpleNamespace as NS
import unittest

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.providers.vsphere.ops import OpsReads


def event(key, name, created, message="msg", user="admin"):
    return NS(_event_type=name, key=key, createdTime=created, userName=user,
              fullFormattedMessage=message)


def ops(event_pages=(), events_enabled=True, event_error=None):
    collector = NS(
        ReadNextEvents=lambda maxCount: event_pages,
        DestroyCollector=lambda: None)
    event_manager = NS(CreateCollectorForEvents=lambda spec: collector)
    content = NS(eventManager=event_manager)
    return OpsReads(NS(RetrieveContent=lambda: content, _stub="stub"))


class EventsTests(unittest.TestCase):
    def test_events_map_fields_and_mark_untrusted(self):
        now = datetime(2026, 10, 10, tzinfo=timezone.utc)
        provider = ops([event(7, "VmPoweredOnEvent", now, "<script>")])
        data = provider.events({"limit": 100, "since": None})
        self.assertEqual(data["items"][0]["type"], "VmPoweredOnEvent")
        self.assertTrue(data["untrusted_content"])

    def test_events_limit_truncation(self):
        now = datetime(2026, 10, 10, tzinfo=timezone.utc)
        provider = ops([event(i, "E", now) for i in range(2)])
        data = provider.events({"limit": 2})
        self.assertTrue(data["truncated"])

    def test_events_invalid_since_rejected(self):
        provider = ops([])
        with self.assertRaises(OperationError) as error:
            provider.events({"limit": 100, "since": "not-a-date"})
        self.assertEqual(error.exception.code, "invalid_arguments")

    def test_events_invalid_entity_rejected(self):
        provider = ops([])
        with self.assertRaises(OperationError) as error:
            provider.events({"limit": 100, "vm_id": "weird-1"})
        self.assertEqual(error.exception.code, "target_invalid")


def datastore(accessible=True, free_bytes=100 * 1024 ** 3):
    return NS(_moId="datastore-1",
              summary=NS(accessible=accessible, freeSpace=free_bytes))


def host(effective_memory_mb=4096, cpu_threads=8, datastores=None):
    return NS(
        _moId="host-1",
        summary=NS(effectiveMemory=effective_memory_mb),
        hardware=NS(cpuInfo=NS(numCpuThreads=cpu_threads)),
        datastore=datastores if datastores is not None else [datastore()])


def cluster(effective_memory_mb=8192, cpu_threads=16, datastores=None):
    return NS(
        _moId="domain-c1",
        summary=NS(effectiveMemory=effective_memory_mb,
                   numCpuThreads=cpu_threads),
        datastore=datastores if datastores is not None else [datastore()])


def ops_with(objects):
    provider = OpsReads(NS(RetrieveContent=lambda: NS(), _stub="stub"))
    provider._managed = lambda object_id: objects[object_id]
    return provider


class QuotaTests(unittest.TestCase):
    def test_datastore_quota_satisfied(self):
        provider = ops_with({"datastore-1": datastore(free_bytes=200 * 1024 ** 3)})
        data = provider.quota({"datastore_id": "datastore-1", "storage_gb": 50})
        self.assertTrue(data["satisfied"])
        self.assertNotIn("storage", data["unavailable"])

    def test_datastore_quota_exceeded(self):
        provider = ops_with({"datastore-1": datastore(free_bytes=10 * 1024 ** 3)})
        data = provider.quota({"datastore_id": "datastore-1", "storage_gb": 50})
        self.assertFalse(data["satisfied"])

    def test_datastore_inaccessible_is_unavailable_not_zero(self):
        provider = ops_with({"datastore-1": datastore(accessible=False)})
        data = provider.quota({"datastore_id": "datastore-1", "storage_gb": 1})
        self.assertIn("storage", data["unavailable"])
        self.assertFalse(data["satisfied"])

    def test_host_quota_satisfied(self):
        provider = ops_with({"host-1": host()})
        data = provider.quota({"host_id": "host-1", "cpu": 4, "memory_gb": 2,
                               "storage_gb": 10})
        self.assertTrue(data["satisfied"], data)

    def test_host_memory_exceeded(self):
        provider = ops_with({"host-1": host(effective_memory_mb=1024)})
        data = provider.quota({"host_id": "host-1", "memory_gb": 8})
        self.assertFalse(data["satisfied"])

    def test_cluster_quota_satisfied(self):
        provider = ops_with({"domain-c1": cluster()})
        data = provider.quota({"cluster_id": "domain-c1", "cpu": 8,
                               "memory_gb": 4, "storage_gb": 20})
        self.assertTrue(data["satisfied"], data)

    def test_cluster_with_inaccessible_ds_marks_unavailable(self):
        provider = ops_with({"domain-c1": cluster(datastores=[datastore(accessible=False)])})
        data = provider.quota({"cluster_id": "domain-c1", "storage_gb": 1})
        self.assertIn("storage", data["unavailable"])
        self.assertFalse(data["satisfied"])

    def test_invalid_quota_target_rejected(self):
        provider = ops_with({})
        with self.assertRaises(OperationError) as error:
            provider.quota({"cluster_id": "vm-1"})
        self.assertEqual(error.exception.code, "target_invalid")


if __name__ == "__main__":
    unittest.main()
