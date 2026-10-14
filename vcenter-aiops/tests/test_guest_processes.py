import contextlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

from pyVmomi import vim, VmomiSupport

from vcenter_aiops.application.execution import Engine
from vcenter_aiops.application.providers import ProviderRouter
from vcenter_aiops.application.registry import lookup
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store
from vcenter_aiops.infrastructure.locking import exclusive


SECRET = "offline-guest-password-do-not-persist"


def options(**changes):
    values = dict(vm_id="vm-1", guest_username="operator", credential_ref="env:TEST_GUEST_PASSWORD",
                  os_family="linux", python_path="/usr/bin/python3", program="/bin/true", argv=[],
                  working_directory="/home/operator", run_parent="/home/operator/runs")
    values.update(changes)
    return values


class GuestStub:
    """Only SOAP transport is replaced; methods and DTOs are actual pyVmomi types."""
    def __init__(self):
        self.calls = []
        self.passwords_at_call = []
        self.files = []
        self.remaining = 0
        self.lost = False
        self.error = None

    def InvokeMethod(self, obj, info, args):
        self.calls.append((info.wsdlName, args))
        self.passwords_at_call.append(args[1].password)
        if self.error:
            raise self.error
        if info.wsdlName == "StartProgramInGuest":
            if self.lost:
                raise OSError(SECRET + " https://bad.invalid/?token=secret")
            return VmomiSupport.long(4321)
        if info.wsdlName == "ListFilesInGuest":
            return vim.vm.guest.FileManager.ListFileInfo(files=self.files, remaining=self.remaining)
        raise AssertionError(info.wsdlName)

    def markers(self, binding, code=None, claimed=True):
        run = binding["run"]
        names = ["claimed-v1-" + run["run_id"] + "-" + run["digest"]] if claimed else []
        if code is not None:
            names.append("done-v1-" + run["run_id"] + "-" + run["digest"] + "-" + str(code))
        self.files = [vim.vm.guest.FileManager.FileInfo(path=name, type="file", size=0) for name in names]


class Fixture:
    def __init__(self):
        self.stub = GuestStub()
        self.permissions = True
        self.vm = NS(_moId="vm-1", config=NS(instanceUuid="vm-uuid", template=False),
                     runtime=NS(connectionState="connected", powerState="poweredOn"),
                     guest=NS(guestFamily="linuxGuest", toolsRunningStatus="guestToolsRunning",
                              guestOperationsReady=True))
        self.sdk_vm = vim.VirtualMachine("vm-1", self.stub)
        self.content = NS(about=NS(instanceUuid="vc-uuid", apiType="VirtualCenter", apiVersion="8.0.3"),
                          sessionManager=NS(currentSession=NS(key="session")),
                          authorizationManager=NS(HasPrivilegeOnEntity=lambda **k: [self.permissions]*len(k["privId"])),
                          guestOperationsManager=NS(processManager=vim.vm.guest.ProcessManager("proc", self.stub),
                                                    fileManager=vim.vm.guest.FileManager("file", self.stub)))
        self.si = NS(RetrieveContent=lambda: self.content, _stub=self.stub)

    def provider(self):
        if importlib.util.find_spec("vcenter_aiops.providers.vsphere.guest") is None:
            raise AssertionError("Guest wrapper Provider is missing")
        from vcenter_aiops.providers.vsphere.guest import Guest
        return Guest(self.si, resolver=lambda kind, oid: self.vm)


class GuestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir="/private/tmp")
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {"VCENTER_AIOPS_HOME": self.temp.name,
                                           "TEST_GUEST_PASSWORD": SECRET}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.fixture = Fixture()

    def engine(self, timeout=0):
        store = Store(Path(self.temp.name) / "state.db")
        self.addCleanup(store.close)
        return Engine(store, ProviderRouter(None, providers={"guest": self.fixture.provider()}), "offline", timeout)

    def preview(self, engine):
        return engine.preview("vm guest-exec", options())

    def test_preview_contract_has_no_password_and_never_starts_guest(self):
        try:
            spec = lookup("vm guest-exec")
        except OperationError:
            self.fail("Guest command contract is missing")
        self.assertEqual(spec.provider_kind, "guest")
        with self.assertRaises(OperationError):
            spec.validate({**options(), "password": SECRET})
        result = self.preview(self.engine())
        run = result.data["payload"]["steps"][0]["binding"]["run"]
        self.assertEqual(run["stdio"], "DEVNULL")
        self.assertEqual(run["shell"], False)
        self.assertIn("source", run)
        self.assertEqual(self.fixture.stub.calls, [])
        self.assertNotIn(SECRET, json.dumps(result.to_dict()))

    def test_success_exit_requires_bound_marker_and_persists_real_pid(self):
        engine = self.engine()
        plan = self.preview(engine)
        self.fixture.stub.markers(plan.data["payload"]["steps"][0]["binding"], 0)
        result = engine.apply(plan.data["id"], plan.data["digest"])
        self.assertEqual(result.status, "succeeded")
        step = result.data["execution"][0]
        self.assertEqual(step["receipt"]["pid"], 4321)
        self.assertIsNone(step["remote_task"])
        self.assertEqual(step["observation"]["exit_code"], 0)
        self.assertNotIn(SECRET, json.dumps(result.to_dict()))
        start = next(args for name, args in self.fixture.stub.calls if name == "StartProgramInGuest")
        self.assertIsInstance(start[1], vim.vm.guest.NamePasswordAuthentication)
        self.assertEqual(self.fixture.stub.passwords_at_call[0], SECRET)
        self.assertEqual(start[1].password, "")
        self.assertIsInstance(start[2], vim.vm.guest.ProcessManager.ProgramSpec)
        query = next(args for name, args in self.fixture.stub.calls if name == "ListFilesInGuest")
        self.assertEqual(query[3:5], [0, 8])

    def test_nonzero_exit_and_linux_signal_are_failed_not_unknown(self):
        for code in (3, -9):
            with self.subTest(code=code):
                engine = self.engine()
                plan = self.preview(engine)
                self.fixture.stub.markers(plan.data["payload"]["steps"][0]["binding"], code)
                result = engine.apply(plan.data["id"], plan.data["digest"])
                self.assertEqual(result.status, "failed")
                self.assertEqual(result.data["execution"][0]["observation"]["exit_code"], code)

    def test_claimed_is_pending_without_liveness_and_timeout_becomes_unknown(self):
        engine = self.engine()
        plan = self.preview(engine)
        binding = plan.data["payload"]["steps"][0]["binding"]
        self.fixture.stub.markers(binding)
        pending = engine.apply(plan.data["id"], plan.data["digest"], wait=False)
        self.assertEqual(pending.status, "running")
        self.assertEqual(pending.data["execution"][0]["observation"]["phase"], "completion_pending")
        self.assertEqual(pending.data["execution"][0]["observation"]["liveness"], "unverified")
        timed = engine.reconcile(plan.data["id"], wait=True)
        self.assertEqual(timed.status, "reconciliation_required")
        self.fixture.stub.markers(binding, 0)
        self.assertEqual(engine.reconcile(plan.data["id"]).status, "succeeded")

    def test_deadline_crossed_during_persistence_still_reports_unknown(self):
        engine = self.engine(timeout=1)
        plan = self.preview(engine)
        self.fixture.stub.markers(plan.data["payload"]["steps"][0]["binding"])
        times = iter([0, 0, 2])
        with patch("vcenter_aiops.application.execution.time.monotonic", side_effect=lambda: next(times, 2)):
            result = engine.apply(plan.data["id"], plan.data["digest"])
        self.assertEqual(result.status, "reconciliation_required")
        self.assertEqual(result.data["execution"][0]["observation"]["error"]["code"], "guest_completion_timeout")

    def test_missing_corrupt_duplicate_wrong_run_or_paginated_markers_are_unknown(self):
        provider = self.fixture.provider()
        binding = provider.preflight("vm guest-exec", options())
        receipt = provider.submit("vm guest-exec", options(), binding)
        for defect in ("missing", "wrong_run", "nonzero_size", "symlink", "duplicate", "pagination", "foreign", "bad_exit"):
            with self.subTest(defect=defect):
                self.fixture.stub.markers(binding, 0)
                self.fixture.stub.remaining = 0
                files = self.fixture.stub.files
                if defect == "missing": files.clear()
                elif defect == "wrong_run": files[-1].path = files[-1].path.replace(binding["run"]["run_id"], "0"*32)
                elif defect == "nonzero_size": files[-1].size = 2
                elif defect == "symlink": files[-1].type = "symlink"
                elif defect == "duplicate": files.append(files[-1])
                elif defect == "pagination": self.fixture.stub.remaining = 1
                elif defect == "foreign": files.append(vim.vm.guest.FileManager.FileInfo(path="other", type="file", size=0))
                elif defect == "bad_exit": files[-1].path = files[-1].path[:-1] + "4294967295"
                self.assertEqual(provider.observe(receipt, binding)["state"], "unknown")

    def test_vm_server_tools_user_and_receipt_mismatch_fail_closed(self):
        provider = self.fixture.provider()
        binding = provider.preflight("vm guest-exec", options())
        receipt = provider.submit("vm guest-exec", options(), binding)
        self.fixture.stub.markers(binding, 0)
        for key, value in (("pid", -1), ("run_id", "0"*32), ("digest", "0"*64)):
            self.assertEqual(provider.observe({**receipt, key: value}, binding)["state"], "unknown")
        self.fixture.vm.config.instanceUuid = "replacement"
        self.assertEqual(provider.observe(receipt, binding)["state"], "unknown")
        self.fixture.vm.config.instanceUuid = "vm-uuid"
        self.fixture.content.about.instanceUuid = "other-vcenter"
        self.assertEqual(provider.observe(receipt, binding)["state"], "unknown")

    def test_lost_start_response_recovers_by_run_identity_without_resubmit(self):
        engine = self.engine()
        plan = self.preview(engine)
        self.fixture.stub.lost = True
        first = engine.apply(plan.data["id"], plan.data["digest"])
        self.assertEqual(first.status, "reconciliation_required")
        self.fixture.stub.markers(plan.data["payload"]["steps"][0]["binding"], 0)
        recovered = self.engine().reconcile(plan.data["id"])
        self.assertEqual(recovered.status, "succeeded")
        self.assertIsNone(recovered.data["execution"][0]["receipt"]["pid"])
        engine.apply(plan.data["id"], plan.data["digest"])
        self.assertEqual(sum(name == "StartProgramInGuest" for name, _ in self.fixture.stub.calls), 1)

    def interleave_start_and_recovery(self, exit_code, *, lose_response=False, fail_query=False, fail_receipt=False):
        engine = self.engine()
        other = self.engine()
        plan = self.preview(engine)
        self.fixture.stub.markers(plan.data["payload"]["steps"][0]["binding"], exit_code)
        self.fixture.stub.lost = lose_response
        original = self.fixture.stub.InvokeMethod
        concurrent = []
        query_error_armed = False

        def transport(obj, info, args):
            nonlocal query_error_armed
            if info.wsdlName == "StartProgramInGuest":
                concurrent.append(other.reconcile(plan.data["id"]))
                query_error_armed = True
            elif info.wsdlName == "ListFilesInGuest" and fail_query and query_error_armed:
                raise OSError("offline temporary observation failure")
            return original(obj, info, args)

        audit = engine.store.audit

        def failing_receipt(event, *args):
            if event == "operation_receipted":
                raise OSError("offline receipt persistence failure")
            return audit(event, *args)

        if fail_receipt:
            engine.store.audit = failing_receipt
        with patch.object(self.fixture.stub, "InvokeMethod", side_effect=transport):
            try:
                result = engine.apply(plan.data["id"], plan.data["digest"])
            except OperationError as exc:
                self.fail("late submission regressed a concurrent terminal operation: " + exc.code)
        self.assertEqual(len(concurrent), 1)
        self.assertEqual(concurrent[0].status, "executing")
        self.assertEqual(concurrent[0].data["execution"][0]["state"], "submitting")
        self.assertIsNone(concurrent[0].data["execution"][0]["receipt"])
        if lose_response or fail_query or fail_receipt:
            self.assertEqual(result.status, "reconciliation_required")
            self.assertEqual(result.data["execution"][0]["state"], "unknown")
        else:
            self.assertEqual(result.status, "succeeded" if exit_code == 0 else "failed")
        recovered = other.reconcile(plan.data["id"])
        self.assertEqual(recovered.status, "succeeded" if exit_code == 0 else "failed")
        self.assertEqual(recovered.data["execution"][0]["state"], "succeeded" if exit_code == 0 else "failed")
        self.assertEqual(sum(name == "StartProgramInGuest" for name, _ in self.fixture.stub.calls), 1)

    def test_active_start_success_marker_and_late_lost_response_cannot_race_recovery(self):
        self.interleave_start_and_recovery(0, lose_response=True)

    def test_active_start_failed_marker_late_receipt_and_failed_query_cannot_regress_terminal(self):
        self.interleave_start_and_recovery(7, fail_query=True)

    def test_active_start_success_marker_and_late_valid_response_finish_without_recovery_race(self):
        self.interleave_start_and_recovery(0)

    def test_active_start_failed_marker_and_late_lost_response_recover_after_owner_releases(self):
        self.interleave_start_and_recovery(7, lose_response=True)

    def test_active_start_receipt_persistence_failure_recovers_after_owner_releases(self):
        self.interleave_start_and_recovery(0, fail_receipt=True)

    def test_missing_receipt_recovery_holds_plan_lock_through_observation(self):
        engine = self.engine()
        plan = self.preview(engine)
        self.fixture.stub.lost = True
        engine.apply(plan.data["id"], plan.data["digest"])
        self.fixture.stub.markers(plan.data["payload"]["steps"][0]["binding"], 0)
        lock = engine.store.path.parent / ("plan-" + plan.data["id"] + ".lock")
        acquired_during_observation = []
        original = self.fixture.stub.InvokeMethod

        def transport(obj, info, args):
            if info.wsdlName == "ListFilesInGuest":
                with exclusive(lock, blocking=False) as acquired:
                    acquired_during_observation.append(acquired)
            return original(obj, info, args)

        with patch.object(self.fixture.stub, "InvokeMethod", side_effect=transport):
            recovered = self.engine().reconcile(plan.data["id"])
        self.assertEqual(acquired_during_observation, [False])
        self.assertEqual(recovered.status, "succeeded")
        with exclusive(lock, blocking=False) as acquired:
            self.assertTrue(acquired)

    def test_abrupt_process_exit_releases_recovery_lock_without_stale_owner(self):
        engine = self.engine()
        plan = self.preview(engine)
        self.fixture.stub.lost = True
        engine.apply(plan.data["id"], plan.data["digest"])
        self.fixture.stub.markers(plan.data["payload"]["steps"][0]["binding"], 0)
        lock = engine.store.path.parent / ("plan-" + plan.data["id"] + ".lock")
        script = (
            "import os, sys\nfrom pathlib import Path\n"
            "from vcenter_aiops.infrastructure.locking import exclusive\n"
            "with exclusive(Path(sys.argv[1])) as acquired:\n"
            "    print('locked' if acquired else 'failed', flush=True)\n"
            "    sys.stdin.readline()\n"
            "    os._exit(0)\n"
        )
        environment = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        child = subprocess.Popen([sys.executable, "-c", script, str(lock)], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=environment)
        try:
            self.assertEqual(child.stdout.readline().strip(), "locked")
            before = len(self.fixture.stub.calls)
            blocked = self.engine().reconcile(plan.data["id"])
            self.assertEqual(blocked.data["execution"][0]["state"], "unknown")
            self.assertIsNone(blocked.data["execution"][0]["receipt"])
            self.assertEqual(len(self.fixture.stub.calls), before)
            child.communicate(input="release\n", timeout=5)
            self.assertEqual(child.returncode, 0)
            self.assertEqual(self.engine().reconcile(plan.data["id"]).status, "succeeded")
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)

    def test_unsubmitted_preview_cannot_recover_or_start_even_with_marker(self):
        engine = self.engine()
        plan = self.preview(engine)
        self.fixture.stub.markers(plan.data["payload"]["steps"][0]["binding"], 0)
        self.assertEqual(engine.reconcile(plan.data["id"]).status, "awaiting_confirmation")
        self.assertEqual(self.fixture.stub.calls, [])

    def test_prepared_but_unclaimed_intent_cannot_recover_completed_marker(self):
        engine = self.engine()
        plan = self.preview(engine)
        step = plan.data["payload"]["steps"][0]
        operation = engine.store.prepare(plan.data["id"] + ":0", step["binding"]["target"], step)
        engine.store.db.execute("INSERT INTO execution_steps(plan_id,position,operation_id) VALUES(?,0,?)", (plan.data["id"], operation["id"]))
        engine.status(plan.data["id"], "reconciliation_required")
        self.fixture.stub.markers(step["binding"], 0)
        self.assertEqual(engine.reconcile(plan.data["id"]).status, "reconciliation_required")
        self.assertEqual(self.fixture.stub.calls, [])
        self.assertEqual(engine.store.operation(operation["id"])["state"], "prepared")

    def test_secret_vault_reference_resolves_only_at_call_without_plaintext_storage(self):
        from cryptography.fernet import Fernet
        from vcenter_aiops.infrastructure.secrets import SecretVault
        with patch.dict(os.environ, {"VCENTER_AIOPS_MASTER_KEY": Fernet.generate_key().decode()}):
            SecretVault(Path(self.temp.name)).set("guest", SECRET)
            provider = self.fixture.provider()
            params = options(credential_ref="secret:guest")
            binding = provider.preflight("vm guest-exec", params)
            self.assertEqual(self.fixture.stub.calls, [])
            provider.submit("vm guest-exec", params, binding)
            self.assertEqual(self.fixture.stub.passwords_at_call, [SECRET])
            self.assertNotIn(SECRET, json.dumps(binding))
            self.assertNotIn(SECRET.encode(), (Path(self.temp.name) / "secrets.json").read_bytes())

    def test_tools_os_permissions_or_username_changes_do_not_launch(self):
        for defect, code in (("tools", "guest_tools_unavailable"), ("os", "guest_os_mismatch"),
                             ("permission", "permission_denied"), ("username", "plan_stale")):
            with self.subTest(defect=defect):
                self.fixture = Fixture()
                provider = self.fixture.provider()
                params = options()
                binding = provider.preflight("vm guest-exec", params)
                if defect == "tools": self.fixture.vm.guest.guestOperationsReady = False
                elif defect == "os": self.fixture.vm.guest.guestFamily = "windowsGuest"
                elif defect == "permission": self.fixture.permissions = False
                else: params["guest_username"] = "other"
                with self.assertRaises(OperationError) as caught:
                    provider.submit("vm guest-exec", params, binding)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(self.fixture.stub.calls, [])

    def test_cancel_does_not_change_operation_state_or_call_kill(self):
        engine = self.engine()
        plan = self.preview(engine)
        self.fixture.stub.markers(plan.data["payload"]["steps"][0]["binding"])
        result = engine.apply(plan.data["id"], plan.data["digest"], wait=False)
        before = engine.store.operation(result.operation_id)["state"]
        with self.assertRaises(OperationError) as caught:
            engine.cancel(result.operation_id, None)
        self.assertEqual(caught.exception.code, "cancellation_unsupported")
        self.assertEqual(engine.store.operation(result.operation_id)["state"], before)
        self.assertFalse(any("Terminate" in name for name, _ in self.fixture.stub.calls))

    def test_sdk_fault_is_sanitized_and_credential_missing_never_starts(self):
        provider = self.fixture.provider()
        binding = provider.preflight("vm guest-exec", options())
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(OperationError) as caught:
                provider.submit("vm guest-exec", options(), binding)
        self.assertEqual(caught.exception.code, "credential_missing")
        self.assertEqual(self.fixture.stub.calls, [])
        self.fixture.stub.error = vim.fault.InvalidGuestLogin(msg=SECRET)
        observation = provider.observe({"kind": "guest_wrapper", "pid": 4321,
                                       "run_id": binding["run"]["run_id"], "digest": binding["run"]["digest"]}, binding)
        self.assertEqual(observation["error"]["code"], "guest_authentication_failed")
        self.assertNotIn(SECRET, json.dumps(observation))

    def test_windows_spec_and_exit_range(self):
        self.fixture.vm.guest.guestFamily = "windowsGuest"
        params = options(os_family="windows", python_path=r"C:\Python310\python.exe", program=r"C:\Windows\System32\whoami.exe",
                         working_directory=r"C:\Work", run_parent=r"C:\PrivateRuns", argv=['space value', 'quote"value', ''])
        provider = self.fixture.provider()
        binding = provider.preflight("vm guest-exec", params)
        receipt = provider.submit("vm guest-exec", params, binding)
        spec = next(args[2] for name, args in self.fixture.stub.calls if name == "StartProgramInGuest")
        self.assertIsInstance(spec, vim.vm.guest.ProcessManager.WindowsProgramSpec)
        self.fixture.stub.markers(binding, 4294967295)
        self.assertEqual(provider.observe(receipt, binding)["exit_code"], 4294967295)
        for path in (r"C:\Work\bad.cmd", r"\\server\share\x.exe", r"C:\foo\..\x.exe", r"C:\foo:x.exe"):
            with self.assertRaises(OperationError):
                provider.preflight("vm guest-exec", {**params, "program": path})

    def test_sdk_dot_directory_entries_do_not_hide_completed_marker(self):
        provider = self.fixture.provider()
        binding = provider.preflight("vm guest-exec", options())
        receipt = provider.submit("vm guest-exec", options(), binding)
        self.fixture.stub.markers(binding, 0)
        self.fixture.stub.files[:0] = [vim.vm.guest.FileManager.FileInfo(path=p, type="directory", size=4096) for p in (".", "..")]
        self.assertEqual(provider.observe(receipt, binding)["state"], "success")
        self.fixture.stub.files[0].type = "symlink"
        self.assertEqual(provider.observe(receipt, binding)["state"], "unknown")

    def test_receipt_persistence_failure_can_recover_without_second_launch(self):
        engine = self.engine()
        plan = self.preview(engine)
        engine.store.db.execute("CREATE TRIGGER receipt_failure BEFORE UPDATE OF receipt ON execution_steps BEGIN SELECT RAISE(FAIL, 'offline failure'); END")
        result = engine.apply(plan.data["id"], plan.data["digest"])
        self.assertEqual(result.status, "reconciliation_required")
        self.assertIsNone(result.data["execution"][0]["receipt"])
        engine.store.db.execute("DROP TRIGGER receipt_failure")
        self.fixture.stub.markers(plan.data["payload"]["steps"][0]["binding"], 0)
        self.assertEqual(self.engine().reconcile(plan.data["id"]).status, "succeeded")
        self.assertEqual(sum(name == "StartProgramInGuest" for name, _ in self.fixture.stub.calls), 1)

    def test_cross_entry_plan_apply_task_wait_and_guest_status_share_exact_operation(self):
        @contextlib.contextmanager
        def session():
            yield self.fixture.si

        @contextlib.contextmanager
        def store():
            value = Store(Path(self.temp.name) / "state.db")
            try:
                yield value
            finally:
                value.close()

        ctx = NS(session=session, store=store, profile="offline", timeout=0)
        with patch("vcenter_aiops.providers.vsphere.guest.Guest", return_value=self.fixture.provider()):
            preview = lookup("vm guest-exec").handler()(ctx, options())
            binding = preview.data["payload"]["steps"][0]["binding"]
            self.fixture.stub.markers(binding)
            applied = lookup("plan apply").handler()(ctx, {"plan_id": preview.data["id"], "confirm": preview.data["digest"], "wait": False})
            waited = lookup("task wait").handler()(ctx, {"operation_id": applied.operation_id})
            self.assertEqual(waited.status, "reconciliation_required")
            self.fixture.stub.markers(binding, 0)
            status = lookup("vm guest-process-status").handler()(ctx, {"operation_id": applied.operation_id})
            self.assertEqual(status.status, "succeeded")
            self.assertEqual(status.operation_id, applied.operation_id)
        self.assertEqual(sum(name == "StartProgramInGuest" for name, _ in self.fixture.stub.calls), 1)

    def test_wrapper_executes_exact_argv_once_and_never_follows_existing_run_link(self):
        provider = self.fixture.provider()
        parent = Path(self.temp.name).resolve()
        params = options(python_path=sys.executable, program=sys.executable, working_directory=str(parent),
                         run_parent=str(parent), argv=["-c", "import sys; raise SystemExit(0 if sys.argv[1:]==['a b', '\"', ''] else 8)", "a b", '"', ""])
        binding = provider.preflight("vm guest-exec", params)
        run = binding["run"]
        completed = subprocess.run([sys.executable, "-c", run["source"]], capture_output=True, timeout=5)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        directory = parent / run["run_id"]
        self.assertTrue((directory / ("done-v1-" + run["run_id"] + "-" + run["digest"] + "-0")).is_file())
        names = sorted(p.name for p in directory.iterdir())
        duplicate = subprocess.run([sys.executable, "-c", run["source"]], capture_output=True, timeout=5)
        self.assertNotEqual(duplicate.returncode, 0)
        self.assertEqual(sorted(p.name for p in directory.iterdir()), names)
        second = provider.preflight("vm guest-exec", params)["run"]
        (parent / second["run_id"]).symlink_to(directory, target_is_directory=True)
        self.assertNotEqual(subprocess.run([sys.executable, "-c", second["source"]], capture_output=True, timeout=5).returncode, 0)

    def test_wrapper_rejects_public_parent_before_payload_and_leaves_failed_launch_unknown(self):
        provider = self.fixture.provider()
        parent = Path(self.temp.name).resolve()
        params = options(python_path=sys.executable, program="/missing-executable", working_directory=str(parent), run_parent=str(parent))
        parent.chmod(0o777)
        run = provider.preflight("vm guest-exec", params)["run"]
        result = subprocess.run([sys.executable, "-c", run["source"]], capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((parent / run["run_id"]).exists())
        parent.chmod(0o700)
        result = subprocess.run([sys.executable, "-c", run["source"]], capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(any(p.name.startswith("done-") for p in (parent / run["run_id"]).iterdir()))

    def test_wrapper_crash_after_claim_leaves_no_completion_and_reentry_cannot_execute(self):
        provider = self.fixture.provider()
        parent = Path(self.temp.name).resolve()
        params = options(python_path=sys.executable, program=sys.executable, working_directory=str(parent),
                         run_parent=str(parent), argv=["-c", "import os,signal; os.kill(os.getppid(),signal.SIGKILL)"])
        run = provider.preflight("vm guest-exec", params)["run"]
        result = subprocess.run([sys.executable, "-c", run["source"]], capture_output=True, timeout=5)
        self.assertEqual(result.returncode, -9)
        names = [p.name for p in (parent / run["run_id"]).iterdir()]
        self.assertTrue(any(name.startswith("claimed-v1-") for name in names))
        self.assertFalse(any(name.startswith("done-v1-") for name in names))
        self.assertEqual(subprocess.run([sys.executable, "-c", run["source"]], capture_output=True, timeout=5).returncode, 125)
