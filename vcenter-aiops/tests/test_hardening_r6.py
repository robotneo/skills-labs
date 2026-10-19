"""Round-6 hardening: refuse to write durable local state through a pre-planted
symlink or unsafe target. Covers the SQLite state DB (Store), the audit export
publish step and the opt-in redacted debug log. All offline, POSIX-only."""
import os
from pathlib import Path
import stat
import tempfile
import unittest

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure import diagnostics
from vcenter_aiops.infrastructure.store import Store
from vcenter_aiops.application.audit import AuditLog


class StateDbSymlinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)

    def _make_store(self):
        return Store(self.dir / "state.sqlite3")

    @unittest.skipUnless(os.name == "posix", "O_NOFOLLOW semantics are POSIX-only")
    def test_normal_store_creates_and_reopens_private_file(self):
        store = self._make_store()
        store.close()
        path = self.dir / "state.sqlite3"
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        # Reopening an existing private DB keeps working.
        again = self._make_store()
        again.close()

    @unittest.skipUnless(os.name == "posix", "O_NOFOLLOW semantics are POSIX-only")
    def test_symlinked_state_db_is_refused(self):
        outside = self.dir / "outside.sqlite3"
        outside.write_bytes(b"not a trusted database")
        link = self.dir / "state.sqlite3"
        link.symlink_to(outside)
        with self.assertRaises(OperationError) as ctx:
            Store(link)
        self.assertEqual(ctx.exception.code, "state_db_unsafe")
        self.assertEqual(ctx.exception.exit_code, 3)
        # The link target must be untouched.
        self.assertEqual(outside.read_bytes(), b"not a trusted database")

    @unittest.skipUnless(os.name == "posix", "O_NOFOLLOW semantics are POSIX-only")
    def test_extra_hardlink_state_db_is_refused(self):
        store = self._make_store()
        store.close()
        path = self.dir / "state.sqlite3"
        alias = self.dir / "alias.sqlite3"
        os.link(path, alias)
        self.assertEqual(path.stat().st_nlink, 2)
        with self.assertRaises(OperationError) as ctx:
            self._make_store()
        self.assertEqual(ctx.exception.code, "state_db_unsafe")

    @unittest.skipUnless(os.name == "posix", "fchmod tightening is POSIX-only")
    def test_loose_mode_is_tightened_not_refused(self):
        store = self._make_store()
        store.close()
        path = self.dir / "state.sqlite3"
        os.chmod(path, 0o644)  # an older install with a permissive umask
        reopened = self._make_store()
        reopened.close()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


class AuditExportSymlinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.store = Store(self.dir / "state.sqlite3")
        self.addCleanup(self.store.close)
        self.audit = AuditLog(self.store)

    def test_normal_export_succeeds(self):
        target = self.dir / "export.json"
        result = self.audit.export(target)
        self.assertEqual(result["status"], "succeeded")
        self.assertTrue(target.is_file())

    def test_existing_regular_file_stays_export_exists(self):
        target = self.dir / "export.json"
        target.write_text("keep me")
        with self.assertRaises(OperationError) as ctx:
            self.audit.export(target)
        self.assertEqual(ctx.exception.code, "export_exists")
        self.assertEqual(ctx.exception.exit_code, 2)
        self.assertEqual(target.read_text(), "keep me")

    @unittest.skipUnless(os.name == "posix", "symlinks are POSIX-testable here")
    def test_symlinked_export_target_is_refused(self):
        outside = self.dir / "outside.txt"
        outside.write_text("do not overwrite")
        link = self.dir / "export.json"
        link.symlink_to(outside)
        with self.assertRaises(OperationError) as ctx:
            self.audit.export(link)
        self.assertEqual(ctx.exception.code, "export_target_unsafe")
        self.assertEqual(ctx.exception.exit_code, 3)
        self.assertEqual(outside.read_text(), "do not overwrite")

    @unittest.skipUnless(os.name == "posix", "fifo/special-file creation is POSIX")
    def test_special_file_export_target_is_refused(self):
        fifo = self.dir / "export.json"
        os.mkfifo(fifo)
        with self.assertRaises(OperationError) as ctx:
            self.audit.export(fifo)
        self.assertEqual(ctx.exception.code, "export_target_unsafe")
        self.assertEqual(ctx.exception.exit_code, 3)


class DebugLogSymlinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve()
        self.logs = self.home / "logs"
        self.log = self.logs / "debug.log"
        self._old_home = os.environ.get("VCENTER_AIOPS_HOME")
        os.environ["VCENTER_AIOPS_HOME"] = str(self.home)

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("VCENTER_AIOPS_HOME", None)
        else:
            os.environ["VCENTER_AIOPS_HOME"] = self._old_home

    @unittest.skipUnless(os.name == "posix", "O_NOFOLLOW semantics are POSIX-only")
    def test_append_never_follows_planted_symlink(self):
        self.logs.mkdir(parents=True, exist_ok=True)
        outside = self.home / "outside.log"
        outside.write_text("pristine")
        self.log.symlink_to(outside)
        with self.assertRaises(OSError):
            diagnostics.record_internal_error(RuntimeError("x"), explicit=True)
        # Nothing must be written through the link.
        self.assertEqual(outside.read_text(), "pristine")

    @unittest.skipUnless(os.name == "posix", "O_NOFOLLOW semantics are POSIX-only")
    def test_rotate_ignores_planted_symlink_and_append_refuses(self):
        self.logs.mkdir(parents=True, exist_ok=True)
        outside = self.home / "outside.log"
        outside.write_text("big" * 5000)  # large enough to be "rotation eligible"
        self.log.symlink_to(outside)
        with self.assertRaises(OSError):
            diagnostics.record_internal_error(RuntimeError("x"), explicit=True)
        # The planted link must not have been renamed into the backup slot.
        self.assertTrue(self.log.is_symlink())
        self.assertFalse((self.logs / "debug.log.1").exists())

    @unittest.skipUnless(os.name == "posix", "regular-file path is POSIX-checked")
    def test_normal_log_is_written_0600(self):
        result = diagnostics.record_internal_error(RuntimeError("secret"),
                                                   explicit=True)
        self.assertEqual(result, self.log)
        self.assertEqual(stat.S_IMODE(self.log.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
