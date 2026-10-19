"""M-6: the opt-in redacted debug log must be size-bounded with rotation.

Previously ``record_internal_error`` appended forever, so a fault loop could grow
``debug.log`` without limit. The fix rotates to a single ``debug.log.1`` backup
once a byte threshold is crossed, keeping total disk use bounded, while leaving
redaction, 0600 permissions and default-off behaviour unchanged.
"""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from vcenter_aiops.infrastructure import diagnostics


class DebugLogRotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.logs = self.home / "logs"
        self.log = self.logs / "debug.log"
        self.backup = self.logs / "debug.log.1"
        self._old_env = {k: os.environ.get(k) for k in
                         ("VCENTER_AIOPS_HOME", "VCENTER_AIOPS_DEBUG_LOG",
                          "VCENTER_AIOPS_DEBUG_LOG_MAX_BYTES")}
        os.environ["VCENTER_AIOPS_HOME"] = str(self.home)
        os.environ["VCENTER_AIOPS_DEBUG_LOG"] = "1"
        os.environ.pop("VCENTER_AIOPS_DEBUG_LOG_MAX_BYTES", None)

    def tearDown(self):
        for key, value in self._old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def record(self, n=1, message="boom"):
        for i in range(n):
            try:
                raise RuntimeError(f"{message}-{i}")
            except RuntimeError as exc:
                diagnostics.record_internal_error(exc, operation_id=f"op-{i}")

    def test_disabled_by_default_writes_nothing(self):
        os.environ.pop("VCENTER_AIOPS_DEBUG_LOG", None)
        self.assertIsNone(diagnostics.record_internal_error(RuntimeError("x")))
        self.assertFalse(self.logs.exists())

    def test_enabled_writes_redacted_0600_record(self):
        result = diagnostics.record_internal_error(RuntimeError("secret-token"),
                                                   explicit=True)
        self.assertEqual(result, self.log)
        mode = stat.S_IMODE(os.stat(self.log).st_mode)
        self.assertEqual(mode, 0o600)
        line = self.log.read_text(encoding="utf-8").strip()
        record = json.loads(line)
        self.assertEqual(record["event"], "internal_error")
        self.assertEqual(record["fault_type"], "RuntimeError")
        self.assertNotIn("secret-token", line)  # never the exception message

    def test_rotates_to_single_backup_when_threshold_crossed(self):
        os.environ["VCENTER_AIOPS_DEBUG_LOG_MAX_BYTES"] = "200"
        # Each JSON line is well over 100 bytes, so a handful crosses 200.
        self.record(6)
        self.assertTrue(self.log.exists())
        self.assertTrue(self.backup.exists(), "超阈值应轮转产生 debug.log.1")
        self.assertFalse((self.logs / "debug.log.2").exists(), "仅保留一份备份")
        # Current log must itself be under/near the threshold after rotation.
        self.assertLess(os.path.getsize(self.log), 1200)
        # Both files stay owner-only.
        for path in (self.log, self.backup):
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
        # Records remain valid JSON lines and stay redacted.
        for path in (self.log, self.backup):
            for line in path.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                self.assertEqual(record["event"], "internal_error")
                self.assertNotIn("boom", json.dumps(record))

    def test_rotation_is_bounded_over_many_records(self):
        os.environ["VCENTER_AIOPS_DEBUG_LOG_MAX_BYTES"] = "300"
        self.record(40)
        files = list(self.logs.iterdir())
        self.assertEqual({p.name for p in files}, {"debug.log", "debug.log.1"})
        total = sum(os.path.getsize(p) for p in files)
        # Bounded to roughly two threshold-sized files plus slack.
        self.assertLess(total, 4000)

    def test_invalid_max_bytes_env_falls_back_to_default(self):
        os.environ["VCENTER_AIOPS_DEBUG_LOG_MAX_BYTES"] = "not-a-number"
        # Must not raise; a single normal record is written.
        diagnostics.record_internal_error(RuntimeError("x"), explicit=True)
        self.assertTrue(self.log.exists())


if __name__ == "__main__":
    unittest.main()
