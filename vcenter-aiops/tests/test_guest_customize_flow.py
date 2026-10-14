"""End-to-end offline coverage for the declarative guest-customize command.

Reuses the same real-pyVmomi transport stub as test_guest_processes so that only
SOAP is faked; the SDK DTOs, fixed wrapper run description, plan engine and
marker protocol are all the production code paths.
"""
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from pyVmomi import vim, VmomiSupport

from vcenter_aiops.application.execution import Engine
from vcenter_aiops.application.providers import ProviderRouter
from vcenter_aiops.domain.models import OperationError, SubmissionRejected
from vcenter_aiops.infrastructure.store import Store


SECRET = "offline-guest-password-do-not-persist"


def spec(**changes):
    data = {"hostname": "web-01",
            "adapter": {"name": "eth0",
                        "ipv4": {"method": "static", "address": "192.168.1.10",
                                 "prefix": 24, "gateway": "192.168.1.1"},
                        "dns_servers": ["8.8.8.8"], "dns_search": ["example.com"]}}
    data.update(changes)
    return data


class GuestStub:
    def __init__(self):
        self.calls = []
        self.files = []
        self.remaining = 0
        self.reject_start = False

    def InvokeMethod(self, obj, info, args):
        self.calls.append((info.wsdlName, args))
        if info.wsdlName == "StartProgramInGuest":
            if self.reject_start:
                raise vim.fault.GuestOperationsUnavailable(msg="offline")
            return VmomiSupport.long(5555)
        if info.wsdlName == "ListFilesInGuest":
            return vim.vm.guest.FileManager.ListFileInfo(files=self.files, remaining=self.remaining)
        raise AssertionError(info.wsdlName)

    def markers(self, binding, code=0):
        run = binding["run"]
        self.files = [
            vim.vm.guest.FileManager.FileInfo(
                path="claimed-v1-" + run["run_id"] + "-" + run["digest"], type="file", size=0),
            vim.vm.guest.FileManager.FileInfo(
                path="done-v1-" + run["run_id"] + "-" + run["digest"] + "-" + str(code),
                type="file", size=0),
        ]


class Fixture:
    def __init__(self):
        self.stub = GuestStub()
        self.permissions = True
        self.vm = NS(_moId="vm-1", config=NS(instanceUuid="vm-uuid", template=False),
                     runtime=NS(connectionState="connected", powerState="poweredOn"),
                     guest=NS(guestFamily="linuxGuest", toolsRunningStatus="guestToolsRunning",
                              guestOperationsReady=True))
        self.content = NS(about=NS(instanceUuid="vc-uuid", apiType="VirtualCenter", apiVersion="8.0.3"),
                          sessionManager=NS(currentSession=NS(key="session")),
                          authorizationManager=NS(HasPrivilegeOnEntity=lambda **k: [self.permissions]*len(k["privId"])),
                          guestOperationsManager=NS(processManager=vim.vm.guest.ProcessManager("proc", self.stub),
                                                    fileManager=vim.vm.guest.FileManager("file", self.stub)))
        self.si = NS(RetrieveContent=lambda: self.content, _stub=self.stub)

    def provider(self):
        from vcenter_aiops.providers.vsphere.guest import Guest
        return Guest(self.si, resolver=lambda kind, oid: self.vm)


class GuestCustomizeFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"VCENTER_AIOPS_HOME": self.temp.name,
                                           "TEST_GUEST_PASSWORD": SECRET}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.fixture = Fixture()
        self.spec_path = Path(self.temp.name) / "customize.json"
        self.spec_path.write_text(json.dumps(spec()), encoding="utf-8")

    def params(self, **changes):
        values = dict(vm_id="vm-1", guest_username="operator",
                      credential_ref="env:TEST_GUEST_PASSWORD", os_family="linux",
                      python_path="/usr/bin/python3", spec_file=str(self.spec_path),
                      run_parent="/home/operator/runs")
        values.update(changes)
        return values

    def engine(self):
        store = Store(Path(self.temp.name) / "state.db")
        self.addCleanup(store.close)
        return Engine(store, ProviderRouter(None, providers={"guest": self.fixture.provider()}),
                      "offline", 0)

    def binding_of(self, plan):
        return plan.data["payload"]["steps"][0]["binding"]

    def test_preview_builds_customize_run_without_starting(self):
        plan = self.engine().preview("vm guest-customize", self.params())
        binding = self.binding_of(plan)
        run = binding["run"]
        self.assertEqual(run["mode"], "customize")
        self.assertFalse(run["capture_output"])
        self.assertEqual(run["stdio"], "DEVNULL")
        self.assertEqual(run["program_path"], "/usr/bin/python3")
        self.assertIn("apply_customize", run["source"])
        # The wrapper tail base64-decodes to a mode=customize payload.
        import base64
        tail = run["source"].split("base64.b64decode('", 1)[1].split("')", 1)[0]
        import json as _json
        decoded = _json.loads(base64.b64decode(tail))
        self.assertEqual(decoded["mode"], "customize")
        self.assertEqual(decoded["customize_spec"]["hostname"], "web-01")
        # The validated declarative spec rides inside the fixed wrapper payload.
        self.assertIn("customize_spec", binding["params"])
        self.assertEqual(binding["params"]["customize_spec"]["hostname"], "web-01")
        self.assertEqual(self.fixture.stub.calls, [])
        self.assertNotIn(SECRET, json.dumps(plan.to_dict()))

    def test_apply_drives_wrapper_and_marker_completes(self):
        engine = self.engine()
        plan = engine.preview("vm guest-customize", self.params())
        self.fixture.stub.markers(self.binding_of(plan), 0)
        result = engine.apply(plan.data["id"], plan.data["digest"])
        self.assertEqual(result.status, "succeeded")
        step = result.data["execution"][0]
        self.assertEqual(step["receipt"]["pid"], 5555)
        self.assertEqual(step["observation"]["exit_code"], 0)
        start = next(args for name, args in self.fixture.stub.calls if name == "StartProgramInGuest")
        self.assertIsInstance(start[2], vim.vm.guest.ProcessManager.ProgramSpec)
        self.assertTrue(self.fixture.provider().verify(
            "vm guest-customize", None, self.binding_of(plan), step["observation"]))

    def test_nonzero_customize_exit_is_failed(self):
        engine = self.engine()
        plan = engine.preview("vm guest-customize", self.params())
        self.fixture.stub.markers(self.binding_of(plan), 1)
        result = engine.apply(plan.data["id"], plan.data["digest"])
        self.assertEqual(result.status, "failed")

    def test_binding_roundtrip_revalidates_spec_in_customize_mode(self):
        provider = self.fixture.provider()
        params = self.params()
        binding = provider.preflight("vm guest-customize", params)
        receipt = provider.submit("vm guest-customize", params, binding)
        self.fixture.stub.markers(binding, 0)
        observation = provider.observe(receipt, binding)
        self.assertEqual(observation["state"], "success")
        # Cross-command recovery is rejected: an exec receipt cannot recover customize.
        with self.assertRaises(OperationError):
            provider.recover_receipt("vm guest-exec", params, binding)

    def test_pre_write_failure_is_submission_rejected_without_remote_write(self):
        provider = self.fixture.provider()
        params = self.params()
        binding = provider.preflight("vm guest-customize", params)
        # A missing credential fails while resolving auth, before any SDK write.
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SubmissionRejected) as caught:
                provider.submit("vm guest-customize", params, binding)
        self.assertEqual(caught.exception.code, "credential_missing")
        self.assertEqual(self.fixture.stub.calls, [])

    def test_sdk_write_fault_is_post_write_uncertainty_not_a_rejection(self):
        provider = self.fixture.provider()
        params = self.params()
        binding = provider.preflight("vm guest-customize", params)
        self.fixture.stub.reject_start = True
        with self.assertRaises(OperationError):
            provider.submit("vm guest-customize", params, binding)
        self.assertTrue(any(name == "StartProgramInGuest"
                            for name, _ in self.fixture.stub.calls))

    def test_invalid_spec_file_blocks_preview(self):
        bad = Path(self.temp.name) / "bad.json"
        bad.write_text(json.dumps({"hostname": "x"}), encoding="utf-8")  # no adapter
        with self.assertRaises(OperationError) as caught:
            self.engine().preview("vm guest-customize", self.params(spec_file=str(bad)))
        self.assertEqual(caught.exception.code, "guest_spec_invalid")
        self.assertEqual(self.fixture.stub.calls, [])

    def test_missing_spec_file_blocks_preview(self):
        with self.assertRaises(OperationError) as caught:
            self.engine().preview("vm guest-customize",
                                  self.params(spec_file=str(Path(self.temp.name) / "nope.json")))
        self.assertEqual(caught.exception.code, "guest_spec_invalid")


if __name__ == "__main__":
    unittest.main()
