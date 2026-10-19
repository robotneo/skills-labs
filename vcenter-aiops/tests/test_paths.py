import os
import stat
import tempfile
import unittest
from pathlib import Path

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.paths import ensure_private


@unittest.skipIf(os.name != "posix", "POSIX permission semantics only")
class EnsurePrivateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _mode(self, path):
        return stat.S_IMODE(os.lstat(path).st_mode)

    def test_new_directory_is_0700(self):
        target = self.root / "a" / "b"
        ensure_private(target)
        self.assertEqual(self._mode(target), 0o700)

    def test_existing_loose_directory_is_tightened(self):
        target = self.root / "data"
        target.mkdir(parents=True)
        os.chmod(target, 0o777)
        ensure_private(target)
        self.assertEqual(self._mode(target), 0o700)

    def test_group_only_bits_are_removed(self):
        target = self.root / "data"
        target.mkdir(parents=True)
        os.chmod(target, 0o750)
        ensure_private(target)
        self.assertEqual(self._mode(target), 0o700)

    def test_symlink_directory_is_rejected(self):
        real = self.root / "real"
        real.mkdir()
        link = self.root / "link"
        link.symlink_to(real)
        with self.assertRaises(OperationError) as error:
            ensure_private(link)
        self.assertEqual(error.exception.code, "data_directory_invalid")

    def test_parent_directories_are_not_tightened(self):
        parent = self.root / "parent"
        parent.mkdir()
        os.chmod(parent, 0o755)
        leaf = parent / "leaf"
        ensure_private(leaf)
        # Only the leaf is hardened; we do not reach up to rewrite parent modes.
        self.assertEqual(self._mode(parent), 0o755)
        self.assertEqual(self._mode(leaf), 0o700)


if __name__ == "__main__":
    unittest.main()
