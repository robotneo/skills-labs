"""M-5: redacted local diagnostics for the internal_error/exit5 catch-all."""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from vcenter_aiops.cli.main import main
from vcenter_aiops.infrastructure import diagnostics


SECRET_MESSAGE = "endpoint https://vcenter.secret.local sso password=hunter2 token=AAAA-BBBB"


class DiagnosticsUnitTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = self._tmp.name
        self.home = Path(self.tmp) / "data"

    def tearDown(self):
        self._tmp.cleanup()

    def _env(self, debug_env=None):
        env = {"VCENTER_AIOPS_HOME": str(self.home)}
        if debug_env is not None:
            env["VCENTER_AIOPS_DEBUG_LOG"] = debug_env
        return patch.dict(os.environ, env, clear=False)

    def test_disabled_by_default_returns_none_and_writes_nothing(self):
        with self._env():
            result = diagnostics.record_internal_error(RuntimeError(SECRET_MESSAGE))
        self.assertIsNone(result)
        self.assertFalse(self.home.exists())

    def test_enabled_by_env_and_by_explicit_flag(self):
        for explicit, env_value, expected in (
                (False, None, False),
                (False, "0", False),
                (False, "1", True),
                (False, "true", True),
                (False, "on", True),
                (True, None, True),
                (True, "0", True)):
            with self.subTest(explicit=explicit, env=env_value), self._env(env_value):
                self.assertIs(diagnostics.debug_log_enabled(explicit), expected)

    def test_record_is_redacted_and_file_modes_are_private(self):
        with self._env("1"):
            def boom():
                raise RuntimeError(SECRET_MESSAGE)
            try:
                boom()
            except RuntimeError as exc:
                log_path = diagnostics.record_internal_error(
                    exc, operation_id="op-123", explicit=False)
        self.assertIsNotNone(log_path)
        # Directory 0700, file 0600.
        self.assertEqual(stat.S_IMODE(log_path.parent.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(log_path.stat().st_mode), 0o600)
        line = log_path.read_text(encoding="utf-8").strip()
        record = json.loads(line)
        self.assertEqual(record["event"], "internal_error")
        self.assertEqual(record["fault_type"], "RuntimeError")
        self.assertEqual(record["operation_id"], "op-123")
        # Frames name local code only; no locals/arguments.
        self.assertTrue(record["frames"])
        for frame in record["frames"]:
            self.assertEqual(set(frame), {"file", "function", "line"})
            self.assertNotIn("locals", frame)
        # The secret payload (endpoint/credentials) must never be persisted.
        self.assertNotIn("hunter2", line)
        self.assertNotIn("vcenter.secret.local", line)
        self.assertNotIn("AAAA-BBBB", line)
        self.assertNotIn(SECRET_MESSAGE, line)

    def test_records_append_without_truncating(self):
        with self._env("1"):
            diagnostics.record_internal_error(ValueError("first"), operation_id="a")
            diagnostics.record_internal_error(KeyError("second"), operation_id="b")
        lines = (self.home / "logs" / "debug.log").read_text().strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["operation_id"], "a")
        self.assertEqual(json.loads(lines[1])["operation_id"], "b")


class CliDiagnosticsTests(unittest.TestCase):
    def _run(self, argv, env_extra=None):
        env = {"VCENTER_AIOPS_HOME": self.home}
        if env_extra:
            env.update(env_extra)
        out, err = io.StringIO(), io.StringIO()
        # vm power-on is an engine (remote_write) command, so the direct-effect
        # risk gate does not block it in this non-TTY harness; the patched invoke
        # raises and exercises the catch-all diagnostics path.
        with patch.dict(os.environ, env, clear=False), \
                patch("vcenter_aiops.cli.main.invoke", side_effect=RuntimeError(SECRET_MESSAGE)), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = str(Path(self._tmp.name) / "data")

    def tearDown(self):
        self._tmp.cleanup()

    def test_internal_error_is_generic_and_logs_nothing_by_default(self):
        code, stdout, _ = self._run(["vm", "power-on", "--vm-id", "vm-1"])
        self.assertEqual(code, 5)
        payload = json.loads(stdout)
        self.assertEqual(payload["error"]["code"], "internal_error")
        self.assertEqual(payload["error"]["message"], "内部执行失败")
        self.assertNotIn("hunter2", stdout)
        self.assertFalse((Path(self.home) / "logs").exists())

    def test_debug_log_flag_persists_redacted_record(self):
        code, stdout, _ = self._run(
            ["--debug-log", "vm", "power-on", "--vm-id", "vm-1"])
        self.assertEqual(code, 5)
        log = Path(self.home) / "logs" / "debug.log"
        record = json.loads(log.read_text().strip())
        self.assertEqual(record["fault_type"], "RuntimeError")
        self.assertNotIn("hunter2", log.read_text())
        # CLI argv (which can carry identifiers) is not part of the record.
        self.assertNotIn("vm-1", log.read_text())
        self.assertEqual(stat.S_IMODE(log.stat().st_mode), 0o600)

    def test_debug_log_env_persists_redacted_record(self):
        code, _, _ = self._run(
            ["vm", "power-on", "--vm-id", "vm-1"], {"VCENTER_AIOPS_DEBUG_LOG": "1"})
        self.assertEqual(code, 5)
        self.assertTrue((Path(self.home) / "logs" / "debug.log").exists())

    def test_logging_failure_never_masks_exit5(self):
        # If diagnostics itself blows up, the CLI still returns a clean exit5.
        env = {"VCENTER_AIOPS_HOME": self.home}
        out = io.StringIO()
        with patch.dict(os.environ, env, clear=False), \
                patch("vcenter_aiops.cli.main.invoke", side_effect=RuntimeError(SECRET_MESSAGE)), \
                patch("vcenter_aiops.infrastructure.diagnostics.record_internal_error",
                      side_effect=OSError("disk full")), \
                contextlib.redirect_stdout(out):
            code = main(["--debug-log", "vm", "power-on", "--vm-id", "vm-1"])
        self.assertEqual(code, 5)
        self.assertEqual(json.loads(out.getvalue())["error"]["code"], "internal_error")


if __name__ == "__main__":
    unittest.main()
