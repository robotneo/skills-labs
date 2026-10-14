import importlib.util
from types import SimpleNamespace as NS
import unittest

from vcenter_aiops.domain.models import OperationError


class BrowserTests(unittest.TestCase):
    def test_root_directory_command_can_omit_path(self):
        from vcenter_aiops.application.registry import lookup
        for command in ("datastore browse", "datastore scan"):
            params = lookup(command).validate({"datastore_id": "datastore-1"})
            self.assertEqual(params["datastore_id"], "datastore-1")

    def provider(self, state="success"):
        self.assertIsNotNone(importlib.util.find_spec("vcenter_aiops.providers.vsphere.datastores"), "browser missing")
        from vcenter_aiops.providers.vsphere.datastores import Datastores
        self.calls = []
        files = [NS(path=n, fileSize=12, modification=None) for n in ("notes.txt", "installer.ISO", "appliance.ova")]
        self.task = NS(_moId="task-1", info=NS(key="task-1", state=state, result=NS(folderPath="[data] images/", file=files)))
        def search(**kwargs):
            self.calls.append(kwargs)
            return self.task
        self.ds = NS(name="data", summary=NS(accessible=True), browser=NS(SearchDatastore_Task=search, SearchDatastoreSubFolders_Task=search))
        self.about = NS(instanceUuid="server-a")
        provider = Datastores(NS(_stub=None, RetrieveContent=lambda: NS(about=self.about)), resolver=lambda _: self.ds)
        provider.task = lambda _: self.task
        return provider

    def test_recursive_scan_reads_all_folders_with_one_global_limit(self):
        provider = self.provider()
        self.assertTrue(callable(getattr(provider, "prepare", None)), "durable search preparation missing")
        from unittest.mock import Mock
        self.ds.browser.SearchDatastore_Task = Mock(side_effect=AssertionError("recursive search used nonrecursive API"))
        self.task.info.result = [NS(folderPath="[data] images/a/", file=[NS(path="a.iso", fileSize=1, modification=None)]),
                                 NS(folderPath="[data] images/b/", file=[NS(path="b.ovf", fileSize=2, modification=None)])]
        scope = provider.prepare("datastore-1", "images", 1, True, True)
        receipt = provider.submit(scope)
        provider.task = lambda _: self.task
        data = provider.observe(receipt, 0)
        self.assertTrue(data["recursive"])
        self.assertEqual([i["name"] for i in data["items"]], ["a.iso"])
        self.assertTrue(data["truncated"])

    def test_recovery_rejects_other_server_before_reading_task(self):
        provider = self.provider()
        self.assertTrue(callable(getattr(provider, "prepare", None)), "durable search preparation missing")
        receipt = provider.submit(provider.prepare("datastore-1", "images"))
        self.about.instanceUuid = "server-b"
        with self.assertRaises(OperationError) as error:
            provider.observe(receipt, 0)
        self.assertEqual(error.exception.code, "server_mismatch")

    def test_scan_finds_images_and_reports_output_truncation(self):
        provider = self.provider()
        data = provider.search("datastore-1", "images", 1, 1, images_only=True)
        self.assertEqual(data["items"][0]["name"], "installer.ISO")
        self.assertTrue(data["truncated"])
        self.assertFalse(data["recursive"])
        self.assertEqual(self.calls[0]["datastorePath"], "[data] images")

    def test_path_escape_rejected_without_remote_search(self):
        provider = self.provider()
        for path in ("../other", "[other] x", "/absolute", "x\\y", "a/../../x", "%2e%2e/x"):
            with self.assertRaises(OperationError):
                provider.search("datastore-1", path, 10, 1)
        self.assertEqual(self.calls, [])

    def test_timeout_reports_running_task_not_empty_success(self):
        provider = self.provider("running")
        data = provider.search("datastore-1", "", 10, 0)
        self.assertEqual(data["state"], "running")
        self.assertEqual(data["task_id"], "task-1")
        self.assertNotIn("items", data)
        self.assertEqual(len(self.calls), 1)

    def test_remote_error_is_not_empty_directory(self):
        provider = self.provider("error")
        with self.assertRaises(OperationError) as error:
            provider.search("datastore-1", "", 10, 1)
        self.assertEqual(error.exception.code, "datastore_search_failed")
