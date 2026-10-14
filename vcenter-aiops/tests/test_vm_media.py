"""ISO uses durable completed metadata searches, never implicit search submission."""
from datetime import datetime, timezone
import time
import unittest

from pyVmomi import vim
import test_vm_devices as disk_tests
from vcenter_aiops.application.searches import Searches
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.providers.vsphere.datastores import Datastores
from vcenter_aiops.application.registry import lookup


class MediaTests(unittest.TestCase):
    engine = disk_tests.DeviceTests.engine

    def setup_media(self):
        f = disk_tests.Fixture()
        cdrom = vim.vm.device.VirtualCdrom(key=3000, controllerKey=1000, unitNumber=2,
            backing=vim.vm.device.VirtualCdrom.RemotePassthroughBackingInfo(deviceName="", useAutoDetect=True),
            connectable=vim.vm.device.VirtualDevice.ConnectInfo(connected=False, startConnected=False, allowGuestControl=False))
        f.vm.config.hardware.device.append(cdrom)
        e = self.engine(f)
        ds = Datastores(f.si, resolver=lambda oid: f.ds)
        metadata = vim.host.DatastoreBrowser.SearchResults(folderPath="[store] images/",
            file=[vim.host.DatastoreBrowser.FileInfo(path="boot.iso", fileSize=1024,
                modification=datetime(2026, 9, 26, tzinfo=timezone.utc))])
        from types import SimpleNamespace as NS
        search_task = NS(info=NS(key="task-2", state="success", result=metadata))
        ds.task = lambda oid: search_task
        f.data["datastore-1"].browser = NS(SearchDatastore_Task=lambda **kw: NS(_moId="task-2"))
        search = Searches(e.store, ds, "lab").start(dict(datastore_id="datastore-1", path="images", images_only=True))
        old_resolve = e.provider.providers["vm"].resolver
        e.provider.providers["vm"].resolver = lambda kind, oid: search_task if (kind, oid) == ("task", "task-2") else old_resolve(kind, oid)
        p = dict(vm_id="vm-1", cdrom_key=3000, datastore_id="datastore-1", path="images/boot.iso", search_id=search.data["search_id"])
        return f, e, p, search_task

    def test_iso_mount_and_unmount_real_specs_and_accurate_postconditions(self):
        f, e, p, task = self.setup_media()
        # A hidden preflight search would call this failing external boundary.
        f.data["datastore-1"].browser.SearchDatastore_Task = lambda **kw: self.fail("unexpected search")
        preview = e.preview("deploy iso", p)
        self.assertEqual(f.calls, [])
        self.assertTrue(preview.warnings)
        binding = preview.data["payload"]["steps"][0]["binding"]
        self.assertEqual(binding["media"]["file"]["size_bytes"], 1024)
        result = e.apply(preview.data["id"], preview.data["digest"])
        self.assertEqual(result.status, "succeeded")
        change = f.calls[0][1][0].deviceChange[0]
        self.assertEqual((change.operation, change.device.key), ("edit", 3000))
        self.assertIsInstance(change.device.backing, vim.vm.device.VirtualCdrom.IsoBackingInfo)
        self.assertEqual(change.device.backing.fileName, "[store] images/boot.iso")
        self.assertEqual(change.device.backing.datastore._moId, "datastore-1")
        self.assertTrue(change.device.connectable.startConnected)
        self.assertFalse(change.device.connectable.connected)
        self.assertIn(("datastore-1", ["Datastore.Browse"]), f.permissions)
        self.assertIn(("vm-1", ["VirtualMachine.Config.EditDevice", "VirtualMachine.Interact.SetCDMedia", "VirtualMachine.Interact.DeviceConnection"]), f.permissions)
        provider = e.provider
        f.vm.config.hardware.device[-1].connectable.startConnected = False
        self.assertFalse(provider.verify("deploy iso", p, binding, {}))
        f.vm.config.hardware.device[-1].connectable.startConnected = True
        unmount = e.preview("deploy unmount-iso", dict(vm_id="vm-1", cdrom_key=3000))
        self.assertEqual(e.apply(unmount.data["id"], unmount.data["digest"]).status, "succeeded")
        change = f.calls[-1][1][0].deviceChange[0]
        self.assertIsNone(change.fileOperation)
        self.assertIsInstance(change.device.backing, vim.vm.device.VirtualCdrom.RemotePassthroughBackingInfo)
        self.assertFalse(change.device.connectable.startConnected)
        self.assertFalse(change.device.connectable.connected)

    def test_media_preflight_rejects_unsafe_paths_wrong_device_and_storage(self):
        for path in ["../boot.iso", "/boot.iso", "images/%2e%2e/boot.iso", "images\\boot.iso", "images/[store]boot.iso", "images/boot.txt"]:
            f, e, p, task = self.setup_media()
            with self.subTest(path=path), self.assertRaises(OperationError):
                e.preview("deploy iso", {**p, "path": path})
        for mutate in [lambda f, p: p.update(cdrom_key=2000),
                       lambda f, p: setattr(f.data["datastore-1"].summary, "accessible", False),
                       lambda f, p: setattr(f.data["host-1"], "datastore", []),
                       lambda f, p: setattr(f, "allowed", False)]:
            f, e, p, task = self.setup_media()
            mutate(f, p)
            with self.assertRaises(OperationError):
                e.preview("deploy iso", p)
            self.assertEqual(f.calls, [])

    def test_completed_evidence_profile_identity_age_and_metadata_fail_closed(self):
        for field, value in [("created", time.time() - 301), ("created", time.time() + 100),
                             ("profile", "other"), ("state", "running"), ("receipt", None)]:
            f, e, p, task = self.setup_media()
            e.store.db.execute("UPDATE datastore_searches SET " + field + "=? WHERE id=?", (value, p["search_id"]))
            with self.subTest(field=field), self.assertRaises(OperationError):
                e.preview("deploy iso", p)
        for mutate in [lambda task: setattr(task.info, "key", "task-99"),
                       lambda task: setattr(task.info.result.file[0], "fileSize", 2048),
                       lambda task: setattr(task.info.result, "folderPath", "[store] other/"),
                       lambda task: setattr(task.info, "state", "running")]:
            f, e, p, task = self.setup_media()
            preview = e.preview("deploy iso", p)
            mutate(task)
            with self.assertRaises(OperationError):
                e.apply(preview.data["id"], preview.data["digest"])
            self.assertEqual(f.calls, [])

    def test_media_bindings_expire_and_pin_existing_drive_before_submit(self):
        f, e, p, task = self.setup_media()
        preview = e.preview("deploy iso", p)
        e.store.db.execute("UPDATE datastore_searches SET created=? WHERE id=?", (time.time() - 301, p["search_id"]))
        with self.assertRaises(OperationError):
            e.apply(preview.data["id"], preview.data["digest"])
        f, e, p, task = self.setup_media()
        preview = e.preview("deploy iso", p)
        f.vm.config.hardware.device[-1].unitNumber = 3
        with self.assertRaises(OperationError):
            e.apply(preview.data["id"], preview.data["digest"])
        self.assertEqual(f.calls, [])

    def test_iso_schema_requires_persisted_search_and_device_dependencies_reject(self):
        f, e, p, task = self.setup_media()
        self.assertEqual(lookup("deploy iso").validate(p)["search_id"], p["search_id"])
        with self.assertRaises(OperationError):
            lookup("deploy iso").validate({k: v for k, v in p.items() if k != "search_id"})
        with self.assertRaises(OperationError):
            e.preview_steps([dict(command="deploy iso", params=p), dict(command="vm power-on", params=dict(vm_id="vm-1"))])

    def test_reconcile_submitted_iso_after_search_evidence_expires(self):
        f, e, p, task = self.setup_media()
        preview = e.preview("deploy iso", p)
        f.task.info.state = "running"
        self.assertEqual(e.apply(preview.data["id"], preview.data["digest"], wait=False).status, "running")
        e.store.db.execute("UPDATE datastore_searches SET created=? WHERE id=?", (time.time() - 301, p["search_id"]))
        f.task.info.state = "success"
        self.assertEqual(e.reconcile(preview.data["id"]).status, "succeeded")
        self.assertEqual(len(f.calls), 1)

    def test_drive_replacement_postcondition_returns_false(self):
        f, e, p, task = self.setup_media()
        preview = e.preview("deploy iso", p)
        binding = preview.data["payload"]["steps"][0]["binding"]
        f.vm.config.hardware.device[-1] = vim.vm.device.VirtualDisk(key=3000)
        self.assertFalse(e.provider.verify("deploy iso", p, binding, {}))

    def test_resolved_vm_object_id_must_match_requested_vm(self):
        f, e, p, task = self.setup_media()
        f.vm._moId = "vm-2"
        with self.assertRaises(OperationError):
            e.preview("deploy iso", p)

    def test_new_engine_reuses_trusted_search_evidence_without_cli_state(self):
        f, e, p, task = self.setup_media()
        from vcenter_aiops.application.execution import Engine
        from vcenter_aiops.application.providers import ProviderRouter
        other = Engine(e.store, ProviderRouter(None, {"vm": e.provider.providers["vm"]}), "lab", timeout=0)
        preview = other.preview_steps([dict(command="deploy iso", params=p)])
        self.assertEqual(other.apply(preview.data["id"], preview.data["digest"]).status, "succeeded")

    def test_directory_trailing_space_is_distinct_from_verified_iso_path(self):
        f, e, p, task = self.setup_media()
        with self.assertRaises(OperationError) as error:
            e.preview("deploy iso", {**p, "path": "images /boot.iso"})
        self.assertEqual(error.exception.code, "iso_not_observed")
        self.assertEqual(f.calls, [])

    def test_evidence_expiry_after_claim_is_known_not_submitted_and_unlocks_target(self):
        f, e, p, task = self.setup_media()
        preview = e.preview("deploy iso", p)
        original_claim = e.store.claim
        def expire_after_claim(operation_id):
            original_claim(operation_id)
            e.store.db.execute("UPDATE datastore_searches SET created=? WHERE id=?", (time.time() - 301, p["search_id"]))
        e.store.claim = expire_after_claim
        result = e.apply(preview.data["id"], preview.data["digest"])
        self.assertEqual(f.calls, [])
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error["code"], "search_evidence_expired")
        self.assertFalse(result.error["retryable"])
        self.assertEqual(result.data["execution"][0]["observation"]["state"], "not_submitted")
        self.assertEqual(e.result(preview.data["id"]).error, result.error)
        self.assertEqual(e.reconcile(preview.data["id"]).status, "failed")
        self.assertEqual(e.apply(preview.data["id"], preview.data["digest"]).status, "failed")
        e.store.claim = original_claim
        next_operation = e.store.prepare("new-fresh-plan", "server-1:vm-1", {})
        e.store.claim(next_operation["id"])
        self.assertEqual(e.store.operation(next_operation["id"])["state"], "submitting")
