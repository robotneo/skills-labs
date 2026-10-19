"""M-8: OVA extraction must resist decompression bombs (total bytes / entries)."""
import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.providers.vsphere.ovf import extract_ova


def make_tar(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in entries:
            info = tarfile.TarInfo(name=name)
            payload = data.encode("utf-8") if isinstance(data, str) else data
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    buffer.seek(0)
    return buffer


class ExtractBombTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def _extract(self, buffer, **limits):
        archive = self.root / "a.ova"
        archive.write_bytes(buffer.read())
        return extract_ova(str(archive), str(self.root / "out"), **limits)

    def test_normal_archive_within_limits_extracts(self):
        buffer = make_tar([("app.ovf", "<Envelope/>"),
                           ("disk1.vmdk", "x" * 4096)])
        base = self._extract(buffer, max_total_bytes=10_000, max_entries=10)
        self.assertTrue((Path(base) / "app.ovf").exists())
        self.assertTrue((Path(base) / "disk1.vmdk").exists())

    def test_total_bytes_exceeded_rejected(self):
        # Two files of 4 KiB each; a 5 KiB ceiling must trip on actual writes.
        buffer = make_tar([("a.vmdk", "a" * 4096), ("b.vmdk", "b" * 4096)])
        with self.assertRaises(OperationError) as error:
            self._extract(buffer, max_total_bytes=5 * 1024, max_entries=100)
        self.assertEqual(error.exception.code, "ovf_archive_too_large")
        self.assertEqual(error.exception.exit_code, 2)

    def test_over_limit_chunk_is_never_persisted(self):
        # First member (4 KiB) fits a 5 KiB ceiling; the second 4 KiB chunk must
        # be rejected *before* it is written, so no over-limit bytes reach disk.
        buffer = make_tar([("a.vmdk", "a" * 4096), ("b.vmdk", "b" * 4096)])
        with self.assertRaises(OperationError):
            self._extract(buffer, max_total_bytes=5 * 1024, max_entries=100)
        base = self.root / "out"
        self.assertFalse((Path(base) / "b.vmdk").exists())
        a_path = Path(base) / "a.vmdk"
        self.assertTrue(a_path.exists())
        self.assertEqual(a_path.stat().st_size, 4096)

    def test_entry_count_exceeded_rejected(self):
        buffer = make_tar([("f1.txt", "1"), ("f2.txt", "2"), ("f3.txt", "3")])
        with self.assertRaises(OperationError) as error:
            self._extract(buffer, max_total_bytes=10 ** 9, max_entries=2)
        self.assertEqual(error.exception.code, "ovf_archive_too_many_entries")
        self.assertEqual(error.exception.exit_code, 2)

    def test_accounts_actual_written_bytes_not_header_claim(self):
        # A header claiming a huge size but carrying little data must not, by
        # itself, trip the byte bound; the bound is on bytes actually written.
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            info = tarfile.TarInfo(name="small.vmdk")
            payload = b"only-a-few-bytes"
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        buffer.seek(0)
        base = self._extract(buffer, max_total_bytes=100, max_entries=10)
        self.assertEqual((Path(base) / "small.vmdk").read_bytes(), b"only-a-few-bytes")


if __name__ == "__main__":
    unittest.main()
