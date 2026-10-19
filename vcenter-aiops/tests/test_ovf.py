import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.providers.vsphere.ovf import (
    extract_ova,
    parse_descriptor,
    safe_member_name,
    validate_mapping,
    validate_placement,
)


def make_tar(entries, links=()):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in entries:
            info = tarfile.TarInfo(name=name)
            payload = data.encode("utf-8")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
        for name, target in links:
            info = tarfile.TarInfo(name=name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            tar.addfile(info)
    buffer.seek(0)
    return buffer


class SafeNameTests(unittest.TestCase):
    def test_normal_relative_name(self):
        self.assertEqual(safe_member_name("disk/vmdk/file.vmdk"),
                         "disk/vmdk/file.vmdk")

    def test_parent_traversal_rejected(self):
        self.assertIsNone(safe_member_name("../escape.vmdk"))
        self.assertIsNone(safe_member_name("a/../../b"))

    def test_absolute_and_drive_rejected(self):
        self.assertIsNone(safe_member_name("/etc/passwd"))
        self.assertIsNone(safe_member_name("C:\\windows\\x"))

    def test_backslash_parent_rejected(self):
        self.assertIsNone(safe_member_name("..\\..\\x"))


class ExtractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_extract_normal_entries(self):
        archive = self.root / "a.ova"
        archive.write_bytes(make_tar([("ovf/x.txt", "data"),
                                     ("y.vmdk", "disk")]).read())
        destination = self.root / "out"
        extract_ova(str(archive), str(destination))
        self.assertTrue((destination / "ovf" / "x.txt").exists())
        self.assertTrue((destination / "y.vmdk").exists())

    def test_extract_rejects_parent_path(self):
        archive = self.root / "evil.ova"
        archive.write_bytes(make_tar([("../evil.txt", "x")]).read())
        with self.assertRaises(OperationError) as error:
            extract_ova(str(archive), str(self.root / "out"))
        self.assertEqual(error.exception.code, "ovf_unsafe_path")

    def test_extract_rejects_symlink_escape(self):
        archive = self.root / "link.ova"
        archive.write_bytes(
            make_tar([("safe.txt", "x")], [("link", "../target")]).read())
        with self.assertRaises(OperationError) as error:
            extract_ova(str(archive), str(self.root / "out"))
        self.assertEqual(error.exception.code, "ovf_unsafe_link")


DESCRIPTOR = """<?xml version="1.0"?>
<Envelope xmlns="http://schemas.dmtf.org/ovf/envelope/1"
 xmlns:ovf="http://schemas.dmtf.org/ovf/envelope/1">
  <NetworkSection>
    <Network ovf:name="VM Network"/>
    <Network ovf:name="Management"/>
  </NetworkSection>
  <References>
    <File ovf:href="disk1.vmdk"/>
  </References>
</Envelope>"""


class DescriptorTests(unittest.TestCase):
    def test_parse_networks_and_files(self):
        data = parse_descriptor(DESCRIPTOR)
        self.assertEqual(data["networks"], ["VM Network", "Management"])
        self.assertEqual(data["files"], ["disk1.vmdk"])

    def test_validate_mapping_ok(self):
        mapping = {"VM Network": "network-1", "Management": "network-2"}
        result = validate_mapping(DESCRIPTOR, mapping, ["disk1.vmdk"])
        self.assertEqual(result["network_mapping"], mapping)

    def test_missing_network_mapping_rejected(self):
        with self.assertRaises(OperationError) as error:
            validate_mapping(DESCRIPTOR, {"VM Network": "network-1"},
                             ["disk1.vmdk"])
        self.assertEqual(error.exception.code,
                         "ovf_network_mapping_incomplete")

    def test_missing_file_rejected(self):
        mapping = {"VM Network": "network-1", "Management": "network-2"}
        with self.assertRaises(OperationError) as error:
            validate_mapping(DESCRIPTOR, mapping, [])
        self.assertEqual(error.exception.code, "ovf_file_missing")

    def test_invalid_network_target_rejected(self):
        mapping = {"VM Network": "weird", "Management": "network-2"}
        with self.assertRaises(OperationError) as error:
            validate_mapping(DESCRIPTOR, mapping, ["disk1.vmdk"])
        self.assertEqual(error.exception.code, "ovf_network_target_invalid")


class PlacementTests(unittest.TestCase):
    def test_placement_ok(self):
        params = {"resource_pool_id": "resgroup-1", "host_id": "host-1",
                  "folder_id": "group-v1", "datastore_id": "datastore-1"}
        self.assertTrue(validate_placement(params))

    def test_placement_missing_rejected(self):
        with self.assertRaises(OperationError):
            validate_placement({"host_id": "host-1"})

    def test_placement_bad_id_rejected(self):
        params = {"resource_pool_id": "x", "host_id": "host-1",
                  "folder_id": "group-v1", "datastore_id": "datastore-1"}
        with self.assertRaises(OperationError) as error:
            validate_placement(params)
        self.assertEqual(error.exception.code, "target_invalid")


if __name__ == "__main__":
    unittest.main()
