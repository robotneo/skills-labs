import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from vcenter_aiops.application.context import Context
from vcenter_aiops.cli.main import main
from vcenter_aiops.infrastructure.store import Store


class HistoryPresetPolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"VCENTER_AIOPS_HOME": self.temp.name})
        self.env.start()
        self.store = Store(Path(self.temp.name) / "state.db")

    def tearDown(self):
        self.store.close()
        self.env.stop()
        self.temp.cleanup()

    def cli(self, *args):
        output = io.StringIO()
        # Non-tty automation: opt into the direct-effect risk gate via --yes;
        # profile/parameter validations inside the handler still run normally.
        argv = ["--yes", *args]
        with patch.object(Context, "session", side_effect=AssertionError("unexpected remote connection")), contextlib.redirect_stdout(output):
            code = main(list(argv))
        return code, json.loads(output.getvalue())

    def plan(self, profile="lab", command="vm power-on", params=None):
        return self.store.create_plan([{"command": command, "params": params or {"vm_id": "vm-1"},
                                        "binding": {"secret": "BOUND-SECRET"}}], profile)

    def test_history_pages_are_bounded_and_global_scope_is_explicit(self):
        self.plan("lab")
        self.plan("other")
        self.plan("lab")
        code, first = self.cli("history", "list", "--limit", "2")
        self.assertEqual(code, 0)
        self.assertEqual(first["data"]["scope"], "all_local_profiles")
        self.assertEqual(len(first["data"]["items"]), 2)
        self.assertTrue(first["data"]["truncated"])
        code, second = self.cli("history", "list", "--limit", "2", "--after-id", str(first["data"]["next_cursor"]),
                                "--snapshot-max-id", str(first["data"]["snapshot_max_id"]))
        self.assertEqual(code, 0)
        self.assertEqual(len(second["data"]["items"]), 1)

    def test_history_show_enforces_profile_and_hides_execution_authority(self):
        plan = self.plan()
        self.store.db.execute("UPDATE plans SET digest=? WHERE id=?", ("CONFIRM-SECRET", plan["id"]))
        code, scoped = self.cli("--profile", "other", "history", "show", plan["id"])
        self.assertEqual(code, 4)
        self.assertEqual(scoped["error"]["code"], "history_not_found")
        code, shown = self.cli("--profile", "lab", "history", "show", plan["id"])
        self.assertEqual(code, 0)
        self.assertEqual(shown["data"]["profile"], "lab")
        self.assertNotIn("BOUND-SECRET", json.dumps(shown))
        self.assertNotIn("CONFIRM-SECRET", json.dumps(shown))

    def test_preset_save_requires_explicit_profile_and_does_not_overwrite(self):
        code, missing = self.cli("preset", "save", "daily", "--command-path", "vm power-on", "--params", '{"vm_id":"vm-1"}')
        self.assertEqual(code, 3)
        self.assertEqual(missing["error"]["code"], "profile_required")
        args = ("--profile", "lab", "preset", "save", "daily", "--command-path", "vm power-on", "--params", '{"vm_id":"vm-1"}')
        code, saved = self.cli(*args)
        self.assertEqual(code, 0)
        self.assertEqual(saved["data"]["params"], {"vm_id": "vm-1"})
        code, duplicate = self.cli(*args)
        self.assertEqual(code, 2)
        self.assertEqual(duplicate["error"]["code"], "preset_exists")
        code, other = self.cli("--profile", "other", "preset", "show", "daily")
        self.assertEqual(code, 2)
        self.assertEqual(other["error"]["code"], "preset_not_found")

    def test_preset_rejects_execution_control_and_nested_unknown_fields(self):
        for params in ('{"vm_id":"vm-1","confirm":"x"}',
                       '{"vm_id":"vm-1","request_id":"old"}',
                       '{"vm_id":"vm-1","binding":{"authorization":"x"}}'):
            code, result = self.cli("--profile", "lab", "preset", "save", "unsafe", "--command-path", "vm power-on", "--params", params)
            self.assertEqual(code, 2)
            self.assertEqual(result["error"]["code"], "preset_invalid")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='presets'").fetchone()[0], 1)
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM presets").fetchone()[0], 0)

    def test_policy_check_is_static_and_never_grants_authority(self):
        code, result = self.cli("policy", "check", "vm power-on", "--params", '{"vm_id":"vm-1"}')
        self.assertEqual(code, 0)
        data = result["data"]
        self.assertTrue(data["static_valid"])
        self.assertEqual(data["authorization"], "not_checked")
        self.assertNotIn("allowed", data)
        self.assertNotIn("confirmation", json.dumps(result))
        self.assertIn("VirtualMachine.Interact.PowerOn", data["required_privileges"])

    def test_from_history_reuses_only_validated_params_and_never_previews(self):
        plan = self.plan("lab", "vm rename", {"vm_id": "vm-1", "new_name": "next"})
        code, result = self.cli("--profile", "lab", "preset", "from-history", "reuse", "--plan-id", plan["id"], "--position", "0")
        self.assertEqual(code, 0)
        self.assertEqual(result["data"]["params"], {"vm_id": "vm-1", "new_name": "next"})
        self.assertEqual(result["data"]["source"], {"type": "history", "plan_id": plan["id"], "position": 0})
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM plans").fetchone()[0], 1)
        self.assertNotIn("BOUND-SECRET", json.dumps(result))
        code, scoped = self.cli("--profile", "other", "preset", "from-history", "reuse", "--plan-id", plan["id"], "--position", "0")
        self.assertEqual(code, 4)
        self.assertEqual(scoped["error"]["code"], "history_not_found")

    def test_from_history_requires_explicit_position_for_multi_step_plan(self):
        plan = self.store.create_plan([
            {"command": "vm power-on", "params": {"vm_id": "vm-1"}},
            {"command": "vm power-on", "params": {"vm_id": "vm-2"}},
        ], "lab")
        code, result = self.cli("--profile", "lab", "preset", "from-history", "chosen", "--plan-id", plan["id"])
        self.assertEqual(code, 2)
        self.assertEqual(result["error"]["code"], "invalid_arguments")
        from vcenter_aiops.application.registry import lookup
        self.assertIn("position", lookup("preset from-history").input_schema()["required"])
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='presets'").fetchone()[0], 0)
        code, selected = self.cli("--profile", "lab", "preset", "from-history", "chosen", "--plan-id", plan["id"], "--position", "1")
        self.assertEqual(code, 0)
        self.assertEqual(selected["data"]["params"], {"vm_id": "vm-2"})

    def test_from_history_rejects_old_control_params(self):
        plan = self.plan("lab", params={"vm_id": "vm-1", "request_id": "OLD-REQUEST"})
        code, result = self.cli("--profile", "lab", "preset", "from-history", "old", "--plan-id", plan["id"], "--position", "0")
        self.assertEqual(code, 2)
        self.assertEqual(result["error"]["code"], "preset_invalid")
        self.assertNotIn("OLD-REQUEST", json.dumps(result))

    def test_corrupt_or_old_preset_cannot_be_loaded(self):
        self.cli("--profile", "lab", "preset", "list")
        for name, payload in (("old", {"schema_version": 0, "command": "vm power-on", "params": {"vm_id": "vm-1"}, "source": {"type": "explicit"}}),
                              ("malformed_source", {"schema_version": 1, "command": "vm power-on", "params": {"vm_id": "vm-1"}, "source": {"type": "history", "plan_id": "SECRET-TOKEN", "position": "bad"}})):
            self.store.db.execute("INSERT INTO presets VALUES(?,?,?,0)", ("lab", name, json.dumps(payload)))
            code, result = self.cli("--profile", "lab", "preset", "show", name)
            self.assertEqual(code, 4)
            self.assertEqual(result["error"]["code"], "preset_corrupt")
            self.assertNotIn("SECRET-TOKEN", json.dumps(result))

    def test_concurrent_saves_keep_all_rows_and_exact_delete(self):
        from vcenter_aiops.application.presets import Presets
        errors = []
        def worker(index):
            local = Store(Path(self.temp.name) / "state.db")
            try:
                Presets(local).save("lab", f"p{index}", "vm power-on", {"vm_id": f"vm-{index}"})
            except Exception as error:
                errors.append(error)
            finally:
                local.close()
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        code, result = self.cli("--profile", "lab", "preset", "list", "--limit", "10")
        self.assertEqual(code, 0)
        self.assertEqual([item["name"] for item in result["data"]["items"]], [f"p{i}" for i in range(8)])
        code, deleted = self.cli("--profile", "lab", "preset", "delete", "p3")
        self.assertEqual(code, 0)
        self.assertEqual(deleted["data"]["deleted"], "p3")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM presets").fetchone()[0], 7)

    def test_from_vm_extracts_whole_gib_cpu_memory_for_explicit_target_only(self):
        from vcenter_aiops.application.commands.history_presets import preset_from_vm
        vm = SimpleNamespace(config=SimpleNamespace(hardware=SimpleNamespace(numCPU=4, memoryMB=8192)))
        @contextlib.contextmanager
        def session(_ctx):
            yield SimpleNamespace(RetrieveContent=lambda: SimpleNamespace(about=SimpleNamespace(instanceUuid="server")))
        with patch.object(Context, "session", session), patch("vcenter_aiops.providers.vsphere.mutations.Mutations.vm", return_value=vm):
            result = preset_from_vm(Context("lab"), {"name": "source", "source_vm_id": "vm-1", "target_vm_id": "vm-2"})
        self.assertEqual(result.data["params"], {"vm_id": "vm-2", "cpu": 4, "memory_gb": 8})
        self.assertEqual(result.data["source"], {"type": "vm", "source_vm_id": "vm-1"})
        self.assertTrue(any("磁盘" in warning and "克隆" in warning for warning in result.warnings))
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM plans").fetchone()[0], 0)

    def test_from_vm_rejects_fractional_gib_without_saving(self):
        from vcenter_aiops.application.commands.history_presets import preset_from_vm
        from vcenter_aiops.domain.models import OperationError
        vm = SimpleNamespace(config=SimpleNamespace(hardware=SimpleNamespace(numCPU=2, memoryMB=1536)))
        @contextlib.contextmanager
        def session(_ctx):
            yield SimpleNamespace(RetrieveContent=lambda: SimpleNamespace(about=SimpleNamespace(instanceUuid="server")))
        with patch.object(Context, "session", session), patch("vcenter_aiops.providers.vsphere.mutations.Mutations.vm", return_value=vm):
            with self.assertRaises(OperationError) as failure:
                preset_from_vm(Context("lab"), {"name": "fractional", "source_vm_id": "vm-1", "target_vm_id": "vm-2"})
        self.assertEqual(failure.exception.code, "preset_hardware_unsupported")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='presets'").fetchone()[0], 0)

    def test_provider_extracts_only_plain_hardware_primitives_with_identity_check(self):
        from vcenter_aiops.providers.vsphere.mutations import Mutations
        from vcenter_aiops.providers.vsphere.reads import Reads
        from vcenter_aiops.domain.models import OperationError
        vm = SimpleNamespace(_moId="vm-1", config=SimpleNamespace(instanceUuid="uuid-1",
                              hardware=SimpleNamespace(numCPU=4, memoryMB=8192)))
        si = SimpleNamespace(RetrieveContent=lambda: SimpleNamespace(about=SimpleNamespace(instanceUuid="server")))
        reader = Reads(Mutations(si, resolver=lambda kind, oid: vm))
        self.assertIsNotNone(getattr(reader, "preset_hardware", None), "Provider must return plain hardware data")
        self.assertEqual(reader.preset_hardware("vm-1"), {"cpu": 4, "memory_gb": 8})
        vm._moId = "vm-2"
        with self.assertRaises(OperationError) as failure:
            reader.preset_hardware("vm-1")
        self.assertEqual(failure.exception.code, "target_changed")

    def test_from_vm_consumes_provider_primitives_without_sdk_object(self):
        @contextlib.contextmanager
        def session(_ctx):
            yield SimpleNamespace(RetrieveContent=lambda: SimpleNamespace(about=SimpleNamespace(instanceUuid="server")))
        class PlainReads:
            def __init__(self, provider):
                pass
            def preset_hardware(self, source_vm_id):
                if source_vm_id != "vm-1":
                    raise AssertionError("wrong source")
                return {"cpu": 6, "memory_gb": 12}
        with patch.object(Context, "session", session), \
             patch("vcenter_aiops.providers.vsphere.reads.Reads", PlainReads), \
             patch("vcenter_aiops.providers.vsphere.mutations.Mutations.vm", side_effect=AssertionError("SDK object crossed boundary")):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--yes", "--profile", "lab", "preset", "from-vm", "plain",
                             "--source-vm-id", "vm-1", "--target-vm-id", "vm-2"])
            result = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["data"]["params"], {"vm_id": "vm-2", "cpu": 6, "memory_gb": 12})
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM plans").fetchone()[0], 0)

    def test_from_vm_invalid_profile_never_opens_session(self):
        code, result = self.cli("preset", "from-vm", "x", "--source-vm-id", "vm-1", "--target-vm-id", "vm-2")
        self.assertEqual(code, 3)
        self.assertEqual(result["error"]["code"], "profile_required")
        code, result = self.cli("--profile", "invalid/name", "preset", "from-vm", "x", "--source-vm-id", "vm-1", "--target-vm-id", "vm-2")
        self.assertEqual(code, 3)
        self.assertEqual(result["error"]["code"], "profile_required")

    def test_history_show_reports_operation_state_without_receipt(self):
        from vcenter_aiops.application.execution import Engine
        plan = self.plan()
        Engine(self.store, None, "lab")
        operation = self.store.prepare("request-1", "server:vm-1", {"vm_id": "vm-1"})
        self.store.db.execute("INSERT INTO execution_steps(plan_id,position,operation_id,receipt) VALUES(?,?,?,?)",
                              (plan["id"], 0, operation["id"], '{"password":"RECEIPT-SECRET"}'))
        code, result = self.cli("--profile", "lab", "history", "show", plan["id"])
        self.assertEqual(code, 0)
        self.assertEqual(result["data"]["operations"], [{"position": 0, "state": "prepared"}])
        self.assertNotIn("RECEIPT-SECRET", json.dumps(result))

    def test_secret_params_rejected_without_echoing_value(self):
        code, result = self.cli("--profile", "lab", "preset", "save", "unsafe", "--command-path", "vm power-on",
                                "--params", '{"vm_id":"vm-1","password":"PRIVATE-VALUE"}')
        self.assertEqual(code, 2)
        self.assertEqual(result["error"]["code"], "preset_invalid")
        self.assertNotIn("PRIVATE-VALUE", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
