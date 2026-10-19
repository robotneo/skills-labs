"""Round-5 hardening: downgrade-lock symlink refusal, durable config replace,
and idempotent performance indexes. All offline, no vCenter connection."""
import os
import tempfile
import unittest
from pathlib import Path

from vcenter_aiops.infrastructure import locking
from vcenter_aiops.infrastructure.config import Profiles, _fsync_directory
from vcenter_aiops.infrastructure.store import Store


class DowngradeLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    @unittest.skipUnless(os.name == "posix", "O_NOFOLLOW semantics are POSIX-only")
    def test_downgrade_lock_refuses_symlink(self):
        target = self.dir / "target"
        target.write_text("")
        link = self.dir / "the.lock"
        link.symlink_to(target)
        with self.assertRaises(OSError):
            # O_NOFOLLOW makes the kernel reject the symlink before any stat.
            locking.open_lock(link)

    @unittest.skipUnless(os.name == "posix", "O_NOFOLLOW semantics are POSIX-only")
    def test_downgrade_lock_creates_and_reuses_regular_file(self):
        lock = self.dir / "the.lock"
        fd = locking.open_lock(lock)
        try:
            self.assertTrue(lock.is_file())
            mode = lock.stat().st_mode & 0o777
            self.assertEqual(mode, 0o600)
        finally:
            os.close(fd)
        # Reopening the same regular file keeps working.
        fd2 = locking.open_lock(lock)
        os.close(fd2)

    @unittest.skipUnless(os.name == "posix", "regular-file check is POSIX-path")
    def test_exclusive_context_still_works(self):
        lock = self.dir / "ctx.lock"
        with locking.exclusive(lock) as acquired:
            self.assertTrue(acquired)


class ConfigDurabilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_fsync_directory_swallows_oserror(self):
        # A directory fsync failure must never break a profile save.
        original = os.open
        def boom(*a, **k):
            raise OSError("not supported")
        os.open = boom
        try:
            _fsync_directory(self.dir)  # should not raise
        finally:
            os.open = original

    def test_save_then_load_roundtrip(self):
        profiles = Profiles(self.dir)
        value = {"schema_version": 1, "profiles":
                 {"lab": {"host": "vc.example", "user": "r",
                          "password_ref": "env:X", "verify_tls": True}}}
        profiles.save(value)
        self.assertEqual(profiles.load(), value)


class IndexTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.temp.name) / "state.sqlite3")

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def _indexes(self, db, table):
        rows = db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
            (table,)).fetchall()
        return {r[0] for r in rows}

    def test_operations_target_index_present_and_idempotent(self):
        self.assertIn("idx_operations_target", self._indexes(self.store.db, "operations"))
        # Constructing a second Store over the same DB re-runs the idempotent DDL.
        second = Store(Path(self.temp.name) / "state.sqlite3")
        try:
            self.assertIn("idx_operations_target", self._indexes(second.db, "operations"))
        finally:
            second.close()

    def test_datastore_searches_profile_index_present(self):
        from vcenter_aiops.application.searches import Searches
        # Constructor creates the table and the profile/created index.
        Searches(self.store, object(), "lab")
        indexes = self._indexes(self.store.db, "datastore_searches")
        self.assertIn("idx_datastore_searches_profile", indexes)
        # Re-constructing must stay idempotent.
        Searches(self.store, object(), "lab")


if __name__ == "__main__":
    unittest.main()
