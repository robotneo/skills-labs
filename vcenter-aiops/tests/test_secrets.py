"""Real authenticated vault tests; all keys, homes and connections are isolated."""
import concurrent.futures
import contextlib
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from cryptography.fernet import Fernet

from vcenter_aiops.application.context import Context
from vcenter_aiops.cli.main import invoke, main
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.config import Profiles


class SecretTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name) / "data"
        self.key = Fernet.generate_key().decode()
        self.env = patch.dict(os.environ, {"VCENTER_AIOPS_HOME": str(self.home),
                                          "VCENTER_AIOPS_MASTER_KEY": self.key}, clear=True)
        self.env.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.env.stop)

    def vault(self):
        self.assertIsNotNone(importlib.util.find_spec("vcenter_aiops.infrastructure.secrets"),
                             "authenticated vault implementation missing")
        from vcenter_aiops.infrastructure.secrets import SecretVault
        return SecretVault(self.home)

    def cli(self, *args, value=""):
        out, err = io.StringIO(), io.StringIO()
        with patch("sys.stdin", io.StringIO(value)), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(args))
        return code, json.loads(out.getvalue()), out.getvalue() + err.getvalue()

    def error(self, code, call):
        with self.assertRaises(OperationError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def test_authenticated_roundtrip_encrypts_entire_inner_structure(self):
        vault = self.vault()
        result = vault.set("private-name", "  password-marker  ")
        self.assertEqual(result["revision"], 1)
        self.assertEqual(vault.resolve("private-name"), "  password-marker  ")
        raw = (self.home / "secrets.json").read_bytes()
        for marker in (b"private-name", b"password-marker", self.key.encode()):
            self.assertNotIn(marker, raw)
        envelope = json.loads(raw)
        self.assertEqual(set(envelope), {"schema_version", "ciphertext"})
        inner = json.loads(Fernet(self.key).decrypt(envelope["ciphertext"].encode()))
        self.assertEqual(inner["secrets"]["private-name"]["value"], "  password-marker  ")
        self.assertEqual(set(vault.list()[0]), {"name", "revision", "created_at", "updated_at"})
        self.assertTrue(result["created_at"].endswith("Z"))

    def test_exact_mutations_preserve_other_entries_and_increment_revision(self):
        vault = self.vault()
        original = vault.set("one", "first")
        vault.set("one-more", "untouched")
        self.error("secret_exists", lambda: vault.set("one", "replacement"))
        rotated = vault.rotate("one", "second")
        self.assertEqual(rotated["revision"], 2)
        self.assertEqual(rotated["created_at"], original["created_at"])
        self.assertEqual(vault.resolve("one"), "second")
        self.assertEqual(vault.resolve("one-more"), "untouched")
        self.error("secret_not_found", lambda: vault.rotate("missing", "x"))
        self.error("secret_not_found", lambda: vault.delete("missing"))
        vault.delete("one")
        self.assertEqual([item["name"] for item in vault.list()], ["one-more"])

    def test_wrong_or_missing_or_malformed_key_preserves_existing_bytes(self):
        vault = self.vault()
        vault.set("one", "first")
        before = (self.home / "secrets.json").read_bytes()
        for key, code in ((Fernet.generate_key().decode(), "secret_authentication_failed"),
                          ("broken", "secret_key_invalid"), ("", "secret_key_missing")):
            with self.subTest(code=code), patch.dict(os.environ, {"VCENTER_AIOPS_MASTER_KEY": key}):
                for action in (lambda: vault.set("two", "new"), lambda: vault.rotate("one", "new"),
                               lambda: vault.delete("one"), vault.list):
                    self.error(code, action)
                self.assertEqual((self.home / "secrets.json").read_bytes(), before)

    def test_malformed_or_tampered_envelopes_are_never_overwritten(self):
        vault = self.vault()
        vault.set("one", "first")
        envelope = json.loads((self.home / "secrets.json").read_text())
        token = envelope["ciphertext"]
        tampered = token[:30] + ("A" if token[30] != "A" else "B") + token[31:]
        cases = [b"{", b'[]', b'{"schema_version":true,"ciphertext":"x"}',
                 b'{"schema_version":1,"schema_version":1,"ciphertext":"x"}',
                 json.dumps({**envelope, "extra": 1}).encode(),
                 json.dumps({**envelope, "ciphertext": tampered}).encode()]
        for raw in cases:
            with self.subTest(raw=raw[:40]):
                (self.home / "secrets.json").write_bytes(raw)
                with self.assertRaises(OperationError):
                    vault.set("two", "new")
                self.assertEqual((self.home / "secrets.json").read_bytes(), raw)

    def test_authenticated_but_invalid_inner_schema_is_rejected(self):
        vault = self.vault()
        vault.set("one", "first")
        entry = {"value": "first", "revision": 1, "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T00:00:00Z"}
        cases = [{"schema_version": 1, "secrets": [], "extra": 1},
                 {"schema_version": True, "secrets": {}},
                 {"schema_version": 1, "secrets": {"../bad": entry}}]
        for changes in ({"revision": True}, {"revision": 0}, {"value": ""}, {"value": 3},
                        {"created_at": "tomorrow"}, {"updated_at": "2026-09-01T00:00:00+08:00"}, {"extra": 1}):
            cases.append({"schema_version": 1, "secrets": {"one": {**entry, **changes}}})
        for inner in cases:
            raw = json.dumps({"schema_version": 1, "ciphertext": Fernet(self.key).encrypt(json.dumps(inner).encode()).decode()}).encode()
            (self.home / "secrets.json").write_bytes(raw)
            self.error("secret_storage_invalid", lambda: vault.rotate("one", "new"))
            self.assertEqual((self.home / "secrets.json").read_bytes(), raw)

    def test_names_and_values_are_bounded_before_storage(self):
        vault = self.vault()
        for name in ("", "../x", "a/b", "a b", "a" * 65, "名字"):
            self.error("secret_name_invalid", lambda: vault.set(name, "value"))
        for value in ("", "x" * 4097, "密" * 1366, "\ud800"):
            self.error("secret_value_invalid", lambda: vault.set("one", value))
        self.assertFalse(self.home.exists())
        vault.set("a" * 64, "密" * 1365 + "x")
        self.assertEqual(len(vault.resolve("a" * 64).encode()), 4096)

    def test_concurrent_set_and_rotate_do_not_lose_updates(self):
        vault = self.vault()
        vault.set("shared", "initial")
        def write(index):
            vault.set(f"item{index}", f"value{index}")
            vault.rotate("shared", f"rotation{index}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(write, range(20)))
        self.assertEqual(len(vault.list()), 21)
        self.assertEqual(next(row for row in vault.list() if row["name"] == "shared")["revision"], 21)

    def test_private_file_lock_and_home_permissions(self):
        vault = self.vault()
        vault.set("one", "first")
        for path, expected in ((self.home, 0o700), (self.home / "secrets.json", 0o600), (self.home / "secrets.lock", 0o600)):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), expected)
            path.chmod(0o777)
            self.error("secret_storage_unsafe", vault.list)
            path.chmod(expected)

    def test_symlink_and_hardlink_files_and_lock_are_rejected(self):
        vault = self.vault()
        self.home.mkdir(mode=0o700)
        outside = Path(self.temp.name) / "outside"
        outside.write_bytes(b"keep")
        outside.chmod(0o600)
        for name in ("secrets.json", "secrets.lock"):
            for kind in ("symlink", "hardlink"):
                target = self.home / name
                if target.exists():
                    target.unlink()
                if kind == "symlink":
                    target.symlink_to(outside)
                else:
                    os.link(outside, target)
                self.error("secret_storage_unsafe", lambda: vault.set("one", "value"))
                self.assertEqual(outside.read_bytes(), b"keep")
                target.unlink()

    def test_symlink_home_is_rejected_without_creating_files(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir(mode=0o700)
        self.home.symlink_to(outside, target_is_directory=True)
        self.error("secret_storage_unsafe", lambda: self.vault().set("one", "value"))
        self.assertEqual(list(outside.iterdir()), [])

    def test_failed_or_interrupted_replace_preserves_original_and_cleans_ciphertext_temp(self):
        vault = self.vault()
        vault.set("one", "first")
        before = (self.home / "secrets.json").read_bytes()
        for failure in (OSError("private-marker"), KeyboardInterrupt()):
            with patch("os.replace", side_effect=failure):
                with self.assertRaises((OperationError, KeyboardInterrupt)):
                    vault.rotate("one", "second-private-marker")
            self.assertEqual((self.home / "secrets.json").read_bytes(), before)
            self.assertEqual({path.name for path in self.home.iterdir()}, {"secrets.json", "secrets.lock"})

    def test_cli_stdin_preserves_spaces_and_removes_only_one_line_ending(self):
        for index, value, expected in ((1, "  value  \r\n", "  value  "), (2, "value\n\n", "value\n"), (3, "value\r", "value")):
            code, result, output = self.cli("secret", "set", f"one{index}", "--stdin", value=value)
            self.assertEqual(code, 0, result)
            self.assertNotIn(expected, output)
            self.assertEqual(self.vault().resolve(f"one{index}"), expected)
        self.assertEqual(self.cli("secret", "rotate", "one1", "--stdin", value="replacement")[0], 0)
        self.assertEqual(self.cli("secret", "delete", "one1")[0], 0)

    def test_cli_rejects_plaintext_flags_nonterminal_implicit_input_and_profile(self):
        for args, code in ((["secret", "set", "one"], "secret_input_required"),
                           (["secret", "set", "one", "--value", "PRIVATE_MARKER"], "invalid_arguments"),
                           (["--profile", "lab", "secret", "list"], "secret_scope_unsupported"),
                           (["secret", "get", "one"], "invalid_arguments")):
            status, result, output = self.cli(*args, value="PRIVATE_MARKER")
            self.assertEqual(status, 2)
            self.assertEqual(result["error"]["code"], code)
            self.assertNotIn("PRIVATE_MARKER", output)
        self.assertFalse(self.home.exists())

    def test_cli_rejects_empty_and_oversize_values_without_echo(self):
        for value in ("\n", "x" * 4097, "密" * 4097):
            status, result, output = self.cli("secret", "set", "one", "--stdin", value=value)
            self.assertEqual(status, 2)
            self.assertEqual(result["error"]["code"], "secret_value_invalid")
            self.assertNotIn("x" * 20, output)
        self.assertFalse(self.home.exists())

    def test_terminal_uses_hidden_input_and_echo_fallback_is_rejected(self):
        import getpass
        self.vault()
        stream = io.StringIO()
        with patch.object(stream, "isatty", return_value=True), patch("sys.stdin", stream), patch("getpass.getpass", return_value="hidden-value"):
            result = invoke("secret set", {"name": "one"}, Context())
        self.assertEqual(result.data["revision"], 1)
        self.assertEqual(self.vault().resolve("one"), "hidden-value")
        with patch.object(stream, "isatty", return_value=True), patch("sys.stdin", stream), patch("getpass.getpass", side_effect=getpass.GetPassWarning("unsafe")):
            self.error("secret_input_unavailable", lambda: invoke("secret rotate", {"name": "one"}, Context()))
        self.assertEqual(self.vault().resolve("one"), "hidden-value")

    def test_credentials_profile_and_session_resolve_only_at_connection(self):
        self.vault().set("login", "session-marker")
        profile = {"host": "example.invalid", "user": "reader", "password_ref": "secret:login"}
        Profiles(self.home).put("lab", profile)
        with patch("pyVim.connect.SmartConnect", return_value=object()) as connect, patch("pyVim.connect.Disconnect"):
            with Context("lab").session():
                pass
            self.assertEqual(connect.call_args.kwargs["pwd"], "session-marker")
        with patch("pyVim.connect.SmartConnect") as connect:
            self.error("profile_required", lambda: Context().session().__enter__())
            connect.assert_not_called()

    def test_shared_reference_validation_and_env_do_not_load_crypto(self):
        self.assertIsNotNone(importlib.util.find_spec("vcenter_aiops.infrastructure.credentials"), "shared reference interface missing")
        from vcenter_aiops.infrastructure.credentials import resolve_credential, validate_reference
        for ref in ("plain", "env:", "secret:", "secret:../x", "env:BAD-X", "secret:x:y"):
            self.error("credential_reference_invalid", lambda: validate_reference(ref))
        with patch.dict(os.environ, {"TEST_PASSWORD": "  env-value  "}), patch.dict(sys.modules, {"cryptography": None, "cryptography.fernet": None}):
            self.assertEqual(resolve_credential("env:TEST_PASSWORD"), "  env-value  ")
            self.error("credential_missing", lambda: resolve_credential("env:MISSING"))
            self.error("dependency_missing", lambda: self.vault().list())
        self.assertFalse(self.home.exists())

    def test_cli_success_and_failure_never_persist_or_output_secret_material(self):
        from vcenter_aiops.infrastructure.store import Store
        store = Store(self.home / "state.db")
        store.close()
        marker = "ZERO_LEAKAGE_MARKER_42"
        outputs = []
        status, result, output = self.cli("secret", "set", "one", "--stdin", value=marker)
        self.assertEqual(status, 0, result)
        outputs.append(output)
        outputs.append(self.cli("secret", "set", "one", "--stdin", value=marker)[2])
        outputs.append(self.cli("secret", "list")[2])
        with patch.dict(os.environ, {"VCENTER_AIOPS_MASTER_KEY": Fernet.generate_key().decode()}):
            outputs.append(self.cli("secret", "rotate", "one", "--stdin", value=marker)[2])
        for output in outputs:
            self.assertNotIn(marker, output)
            self.assertNotIn(self.key, output)
        for path in self.home.iterdir():
            self.assertNotIn(marker.encode(), path.read_bytes())
            self.assertNotIn(self.key.encode(), path.read_bytes())

    def test_import_and_help_without_optional_dependencies_have_no_storage_side_effects(self):
        code = """
import sys
sys.modules['cryptography'] = None
sys.modules['cryptography.fernet'] = None
sys.modules['pyVmomi'] = None
from vcenter_aiops.cli.main import main
main(['secret', 'set', '--help'])
"""
        process = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                                 env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("4096", process.stdout)
        self.assertFalse(self.home.exists())

    def test_noncanonical_token_corruption_is_rejected_even_if_fernet_ignores_it(self):
        vault = self.vault()
        vault.set("one", "value")
        envelope = json.loads((self.home / "secrets.json").read_text())
        envelope["ciphertext"] += "!"
        original = json.dumps(envelope).encode()
        (self.home / "secrets.json").write_bytes(original)
        self.error("secret_authentication_failed", lambda: vault.rotate("one", "new"))
        self.assertEqual((self.home / "secrets.json").read_bytes(), original)

    def test_temporary_name_collision_does_not_delete_an_existing_file(self):
        vault = self.vault()
        vault.set("one", "value")
        collision = self.home / ".secrets-fixed.tmp"
        collision.write_bytes(b"existing-ciphertext")
        collision.chmod(0o600)
        with patch("vcenter_aiops.infrastructure.secrets.uuid.uuid4", return_value=SimpleNamespace(hex="fixed")):
            self.error("secret_storage_io", lambda: vault.rotate("one", "new"))
        self.assertTrue(collision.exists(), "cleanup deleted a file it did not create")
        self.assertEqual(collision.read_bytes(), b"existing-ciphertext")
        self.assertEqual(vault.resolve("one"), "value")

    def test_replaced_lock_while_waiting_is_rejected_before_decrypting(self):
        import fcntl
        vault = self.vault()
        vault.set("one", "value")
        before = (self.home / "secrets.json").read_bytes()
        flock = fcntl.flock
        def replace_lock(fd, operation):
            if operation == fcntl.LOCK_EX:
                (self.home / "secrets.lock").unlink()
                (self.home / "secrets.lock").touch(mode=0o600)
            return flock(fd, operation)
        with patch("fcntl.flock", side_effect=replace_lock):
            self.error("secret_storage_unsafe", lambda: vault.rotate("one", "new"))
        self.assertEqual((self.home / "secrets.json").read_bytes(), before)

    def test_symlink_swap_at_open_cannot_follow_file_or_lock_or_home(self):
        vault = self.vault()
        vault.set("one", "value")
        outside = Path(self.temp.name) / "outside"
        outside.write_bytes(b"outside-keep")
        outside.chmod(0o600)
        real_open = os.open
        for name in ("secrets.json", "secrets.lock"):
            target = self.home / name
            original = target.read_bytes()
            fired = []
            def swap(path, flags, *args, **kwargs):
                if str(path) == name and not fired:
                    fired.append(True)
                    target.unlink()
                    target.symlink_to(outside)
                return real_open(path, flags, *args, **kwargs)
            with patch("os.open", side_effect=swap):
                self.error("secret_storage_unsafe", vault.list)
            self.assertTrue(fired)
            self.assertEqual(outside.read_bytes(), b"outside-keep")
            target.unlink()
            target.write_bytes(original)
            target.chmod(0o600)
        old_home = Path(self.temp.name) / "original-home"
        outside_dir = Path(self.temp.name) / "outside-dir"
        outside_dir.mkdir(mode=0o700)
        def swap_home(path, flags, *args, **kwargs):
            if path == self.home:
                self.home.rename(old_home)
                self.home.symlink_to(outside_dir, target_is_directory=True)
            return real_open(path, flags, *args, **kwargs)
        with patch("os.open", side_effect=swap_home):
            self.error("secret_storage_unsafe", vault.list)
        self.assertEqual(list(outside_dir.iterdir()), [])

    def test_directory_descriptor_keeps_replace_off_a_redirected_home(self):
        vault = self.vault()
        vault.set("one", "value")
        original_home = Path(self.temp.name) / "original-home"
        outside = Path(self.temp.name) / "outside-dir"
        outside.mkdir(mode=0o700)
        real_open = os.open
        redirected = []
        def redirect(path, flags, *args, **kwargs):
            fd = real_open(path, flags, *args, **kwargs)
            if str(path) == "secrets.lock" and not redirected:
                redirected.append(True)
                self.home.rename(original_home)
                self.home.symlink_to(outside, target_is_directory=True)
            return fd
        with patch("os.open", side_effect=redirect):
            vault.rotate("one", "new")
        self.assertEqual(list(outside.iterdir()), [])
        from vcenter_aiops.infrastructure.secrets import SecretVault
        self.assertEqual(SecretVault(original_home).resolve("one"), "new")

    def test_profile_scope_rejected_before_every_secret_operation_or_prompt(self):
        for args in (("list",), ("set", "one", "--stdin"), ("rotate", "one", "--stdin"), ("delete", "one")):
            status, result, _ = self.cli("--profile", "lab", "secret", *args, value="value")
            self.assertEqual(status, 2)
            self.assertEqual(result["error"]["code"], "secret_scope_unsupported")
        self.assertFalse(self.home.exists())

    def test_windows_backend_explicitly_fails_closed_but_env_resolution_still_works(self):
        vault = self.vault()
        from vcenter_aiops.infrastructure.credentials import resolve_credential
        with patch("os.name", "nt"), patch.dict(os.environ, {"TEST_PASSWORD": "env-value"}):
            self.error("secret_storage_unsupported", lambda: vault.set("one", "value"))
            self.assertEqual(resolve_credential("env:TEST_PASSWORD"), "env-value")
        self.assertFalse(self.home.exists())

    def test_missing_crypto_dependency_preserves_existing_file(self):
        vault = self.vault()
        vault.set("one", "value")
        before = (self.home / "secrets.json").read_bytes()
        with patch.dict(sys.modules, {"cryptography": None, "cryptography.fernet": None}):
            self.error("dependency_missing", lambda: vault.rotate("one", "replacement"))
        self.assertEqual((self.home / "secrets.json").read_bytes(), before)

    def test_process_concurrency_keeps_all_additions_and_revisions(self):
        vault = self.vault()
        vault.set("shared", "initial")
        script = """
import sys
from vcenter_aiops.infrastructure.secrets import SecretVault
v = SecretVault(sys.argv[1])
v.set('process' + sys.argv[2], 'value')
v.rotate('shared', 'replacement')
"""
        env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
        processes = [subprocess.Popen([sys.executable, "-c", script, str(self.home), str(i)],
                                     env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(6)]
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            self.assertEqual(process.returncode, 0, stderr)
            self.assertEqual(stdout, b"")
        self.assertEqual(len(vault.list()), 7)
        self.assertEqual(next(row for row in vault.list() if row["name"] == "shared")["revision"], 7)

    def test_binary_stdin_invalid_encoding_and_exact_byte_limit(self):
        stream = io.TextIOWrapper(io.BytesIO(b"\xff\n"), encoding="utf-8")
        output = io.StringIO()
        with patch("sys.stdin", stream), contextlib.redirect_stdout(output):
            status = main(["secret", "set", "one", "--stdin"])
        self.assertEqual(status, 2)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], "secret_value_invalid")
        stream = io.TextIOWrapper(io.BytesIO(b"x" * 4096 + b"\r\n"), encoding="utf-8")
        with patch("sys.stdin", stream), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["secret", "set", "one", "--stdin"]), 0)
        self.assertEqual(self.vault().resolve("one"), "x" * 4096)

    def test_secret_auth_failure_and_sdk_failure_emit_no_logs_or_secrets(self):
        vault = self.vault()
        marker = "SESSION_SECRET_MARKER"
        vault.set("login", marker)
        Profiles(self.home).put("lab", {"host": "example.invalid", "user": "reader", "password_ref": "secret:login"})
        logs = io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        self.addCleanup(logging.getLogger().removeHandler, handler)
        with patch("pyVim.connect.SmartConnect", side_effect=RuntimeError(marker)):
            status, result, output = self.cli("--profile", "lab", "profile", "test")
        self.assertEqual(status, 3)
        self.assertEqual(result["error"]["code"], "connection_failed")
        self.assertNotIn(marker, output + logs.getvalue())
        with patch.dict(os.environ, {"VCENTER_AIOPS_MASTER_KEY": Fernet.generate_key().decode()}), patch("pyVim.connect.SmartConnect") as connect:
            status, result, output = self.cli("--profile", "lab", "profile", "test")
            connect.assert_not_called()
        self.assertEqual(result["error"]["code"], "secret_authentication_failed")
        self.assertNotIn(marker, output + logs.getvalue())
