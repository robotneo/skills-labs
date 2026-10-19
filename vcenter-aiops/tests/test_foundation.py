import concurrent.futures
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from vcenter_aiops.cli.main import main
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.config import Profiles
from vcenter_aiops.infrastructure.store import Store
from vcenter_aiops.providers.vsphere.inventory import Inventory


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "data"
        self.env = patch.dict(os.environ, {"VCENTER_AIOPS_HOME": str(self.home)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def cli(self, *args):
        out = io.StringIO()
        # Non-tty automation: opt into the direct-effect risk gate via --yes;
        # read commands ignore the flag, and handler validations still run.
        with contextlib.redirect_stdout(out):
            code = main(["--yes", *args])
        return code, json.loads(out.getvalue())

    def test_version_and_doctor_do_not_create_state(self):
        for command in (("version",), ("doctor",), ("capabilities", "list")):
            code, data = self.cli(*command)
            self.assertEqual(code, 0)
            self.assertEqual(data["schema_version"], "1")
        self.assertFalse(self.home.exists())

    def test_capabilities_do_not_claim_unimplemented_features(self):
        _, result = self.cli("capabilities", "list")
        self.assertFalse(result["data"]["prd_complete"])
        self.assertEqual(result["data"]["vsphere"]["6.5"], "not_lab_verified")
        paths = [c["path"] for c in result["data"]["commands"]]
        # OVA/OVF are implemented offline but never claimed lab-verified here.
        self.assertIn("deploy ova", paths)
        self.assertIn("deploy ovf", paths)
        for command in result["data"]["commands"]:
            if command["path"] in ("deploy ova", "deploy ovf"):
                self.assertEqual(command["vsphere"]["8.0"], "not_lab_verified")
        # Shelved governance leaves remain, so the PRD is not marked complete.
        self.assertFalse(result["data"]["prd_complete"])

    def test_old_handler_action_is_rejected(self):
        code, data = self.cli("--action", "list_all")
        self.assertEqual(code, 2)
        self.assertEqual(data["error"]["code"], "invalid_arguments")

    def test_every_registered_leaf_has_help(self):
        from vcenter_aiops.application.registry import COMMANDS
        from vcenter_aiops.cli.main import build_parser
        for command in COMMANDS:
            with self.subTest(command=command.path), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    build_parser().parse_args(command.path.split() + ["--help"])
                self.assertEqual(result.exception.code, 0)

    def test_malformed_yaml_is_configuration_error(self):
        self.home.mkdir()
        (self.home / "config.yaml").write_text("profiles: [", encoding="utf-8")
        code, result = self.cli("profile", "list")
        self.assertEqual(code, 3)
        self.assertEqual(result["error"]["code"], "config_invalid")

    def test_import_does_not_load_sdk(self):
        code = "import sys; import vcenter_aiops.cli.main; assert 'pyVmomi' not in sys.modules"
        self.assertEqual(subprocess.run([sys.executable, "-c", code], capture_output=True).returncode, 0)

    def test_profiles_store_references_and_roundtrip(self):
        code, result = self.cli("profile", "add", "lab", "--host", "example.test", "--user", "reader", "--password-ref", "env:VC_TEST")
        self.assertEqual(code, 0)
        _, result = self.cli("profile", "show", "lab")
        self.assertEqual(result["data"]["password_ref"], "env:VC_TEST")
        self.assertTrue(result["data"]["verify_tls"])
        self.assertEqual(self.cli("profile", "delete", "lab")[0], 0)
        self.assertEqual(self.cli("profile", "show", "lab")[0], 3)

    def test_concurrent_profile_additions_are_not_lost(self):
        def add(index):
            Profiles(self.home).put(f"lab{index}", {"host": "example.test", "user": "reader", "password_ref": "env:PASSWORD"})
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(add, range(24)))
        self.assertEqual(len(Profiles(self.home).load()["profiles"]), 24)

    def test_plaintext_and_invalid_port_rejected(self):
        profiles = Profiles(self.home)
        for changes in ({"password": "secret"}, {"port": 0}, {"password_ref": "secret"}):
            value = {"host": "h", "user": "u", "password_ref": "env:PASS", **changes}
            with self.assertRaises(OperationError):
                profiles.put("lab", value)
        self.assertFalse(self.home.exists())

    def test_ip_scope_and_exact_release(self):
        store = Store(self.home / "state.db")
        try:
            first = store.reserve("net1", "10.0.0.1", "one")
            with self.assertRaises(OperationError):
                store.reserve("net1", "10.0.0.1", "two")
            store.reserve("net2", "10.0.0.1", "two")
            store.release(first["lease_id"])
            self.assertEqual(len(store.leases()), 1)
            self.assertEqual(store.leases()[0]["scope"], "net2")
        finally:
            store.close()

    def test_concurrent_ip_only_one_winner(self):
        path = self.home / "state.db"
        Store(path).close()
        def reserve(i):
            store = Store(path)
            try:
                store.reserve("net", "10.0.0.2", str(i))
                return True
            except OperationError:
                return False
            finally:
                store.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            self.assertEqual(sum(pool.map(reserve, range(10))), 1)

    def test_operation_idempotency_and_unknown_submission(self):
        path = self.home / "state.db"
        store = Store(path)
        op = store.prepare("request", "vc1:vm1", {"action": "power_on"})
        self.assertEqual(store.prepare("request", "vc1:vm1", {"action": "power_on"})["id"], op["id"])
        with self.assertRaises(OperationError):
            store.prepare("request", "vc2:vm1", {"action": "power_on"})
        store.claim(op["id"])
        store.close()
        store = Store(path)
        try:
            with self.assertRaises(OperationError) as error:
                store.claim(op["id"])
            self.assertEqual(error.exception.code, "reconciliation_required")
            second = store.prepare("second", "vc1:vm1", {})
            with self.assertRaises(OperationError) as error:
                store.claim(second["id"])
            self.assertEqual(error.exception.code, "target_busy")
        finally:
            store.close()

    def test_plan_digest_and_parameterized_id_lookup(self):
        store = Store(self.home / "state.db")
        try:
            result = store.create_plan([{"operation": "vm.power_on"}], "lab")
            self.assertEqual(len(result["digest"]), 64)
            self.assertEqual(result["status"], "draft")
            with self.assertRaises(OperationError):
                store.plan("../../config.yaml")
            self.assertEqual(len(store.plans()), 1)
        finally:
            store.close()

    def test_object_resolution_rejects_duplicates_and_truncation(self):
        inventory = object.__new__(Inventory)
        with patch.object(inventory, "list", return_value={"items": [{"id": "1", "name": "same"}, {"id": "2", "name": "same"}], "truncated": False}):
            with self.assertRaises(OperationError) as error:
                inventory.resolve("vm", name="same")
            self.assertEqual(error.exception.code, "target_ambiguous")
            self.assertEqual(inventory.resolve("vm", object_id="2")["id"], "2")
        with patch.object(inventory, "list", return_value={"items": [], "truncated": True}):
            with self.assertRaises(OperationError) as error:
                inventory.resolve("vm", name="missing")
            self.assertEqual(error.exception.code, "query_incomplete")


if __name__ == "__main__":
    unittest.main()
