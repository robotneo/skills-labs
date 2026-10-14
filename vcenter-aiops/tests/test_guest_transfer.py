import base64
import unittest
from types import SimpleNamespace as NS

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.providers.vsphere import guest_transfer


RUN_ID = "a" * 32
DIGEST = "b" * 64


def run(family="linux", directory="/runs/" + RUN_ID):
    return {"run_id": RUN_ID, "digest": DIGEST, "directory": directory,
            "capture_output": True, "stdout_name": "stdout.b64",
            "stderr_name": "stderr.b64"}


def file_item(name, size=0, type_="file"):
    return NS(path=name, size=size, type=type_)


def finished_listing(family="linux", code=0, stdout=b"out", stderr=b"err"):
    prefix = RUN_ID + "-" + DIGEST
    files = [file_item(".", type_="directory"), file_item("..", type_="directory"),
             file_item("claimed-v1-" + prefix),
             file_item("stdout.b64", size=len(base64.b64encode(stdout))),
             file_item("stderr.b64", size=len(base64.b64encode(stderr))),
             file_item("done-v1-" + prefix + "-" + str(code))]
    return NS(files=files, remaining=0)


class ReadOutputTests(unittest.TestCase):
    def setUp(self):
        self.fetched = {}

        def fetch(path):
            return self.fetched[path]

        self.fetch = fetch

    def _prepare(self, stdout, stderr, family="linux"):
        sep = "\\" if family == "windows" else "/"
        base = ("/runs/" + RUN_ID) if family == "linux" else ("C:\\runs\\" + RUN_ID)
        self.fetched[base + sep + "stdout.b64"] = base64.b64encode(stdout)
        self.fetched[base + sep + "stderr.b64"] = base64.b64encode(stderr)
        return run(family, base)

    def test_success_decodes_streams(self):
        r = self._prepare(b"hello", b"boom")
        listing = finished_listing()
        result = guest_transfer.read_output(listing, r, "linux", self.fetch)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["stdout"], "hello")
        self.assertEqual(result["stderr"], "boom")

    def test_nonzero_exit_still_reads_output(self):
        r = self._prepare(b"", b"err")
        listing = finished_listing(code=7)
        result = guest_transfer.read_output(listing, r, "linux", self.fetch)
        self.assertEqual(result["exit_code"], 7)

    def test_in_progress_returns_none(self):
        listing = NS(files=[file_item(".", type_="directory"),
                            file_item("claimed-v1-" + RUN_ID + "-" + DIGEST)],
                     remaining=0)
        self.assertIsNone(guest_transfer.read_output(listing, run(), "linux", self.fetch))

    def test_corrupt_base64_is_uncertain(self):
        r = self._prepare(b"x", b"y")
        for key in list(self.fetched):
            if key.endswith("stdout.b64"):
                self.fetched[key] = b"not_base64!!"
        listing = finished_listing()
        with self.assertRaises(OperationError) as ctx:
            guest_transfer.read_output(listing, r, "linux", self.fetch)
        self.assertEqual(ctx.exception.code, "guest_result_invalid")


class DownloadTests(unittest.TestCase):
    def test_success(self):
        def initiate(path):
            return NS(url="https://vc/x", size=3)

        def fetch(url, max_bytes=None):
            return b"abc"

        result = guest_transfer.download(
            initiate, fetch, guest_path="/var/log/app.log", family="linux")
        self.assertEqual(result["bytes"], 3)

    def test_size_mismatch_is_uncertain(self):
        def initiate(path):
            return NS(url="u", size=3)

        def fetch(url, max_bytes=None):
            return b"ab"

        with self.assertRaises(OperationError) as ctx:
            guest_transfer.download(
                initiate, fetch, guest_path="/a.log", family="linux")
        self.assertEqual(ctx.exception.code, "guest_transfer_invalid")

    def test_declared_oversize_rejected_before_fetch(self):
        calls = []

        def initiate(path):
            return NS(url="u", size=guest_transfer.MAX_TRANSFER_BYTES + 1)

        def fetch(url, max_bytes=None):
            calls.append(url)
            return b""

        with self.assertRaises(OperationError) as ctx:
            guest_transfer.download(
                initiate, fetch, guest_path="/big.log", family="linux")
        self.assertEqual(ctx.exception.code, "guest_file_too_large")
        self.assertEqual(calls, [])

    def test_bad_guest_path_rejected(self):
        with self.assertRaises(OperationError):
            guest_transfer.download(lambda p: None, lambda u, max_bytes=None: b"",
                                    guest_path="relative", family="linux")


class UploadTests(unittest.TestCase):
    def test_success(self):
        def initiate(path, size, overwrite):
            self.assertFalse(overwrite)
            return "https://vc/put"

        puts = []
        result = guest_transfer.upload(
            initiate, lambda url, payload: puts.append((url, payload)),
            guest_path="/etc/config.ini", family="linux", payload=b"data")
        self.assertEqual(result["bytes"], 4)
        self.assertEqual(puts[0][1], b"data")

    def test_overwrite_flag_propagates(self):
        seen = {}

        def initiate(path, size, overwrite):
            seen["overwrite"] = overwrite
            return "u"

        guest_transfer.upload(initiate, lambda url, payload: None,
                              guest_path="/a", family="linux",
                              payload=b"x", overwrite=True)
        self.assertTrue(seen["overwrite"])

    def test_oversize_rejected(self):
        with self.assertRaises(OperationError) as ctx:
            guest_transfer.upload(
                lambda *a: "u", lambda url, payload: None,
                guest_path="/a", family="linux",
                payload=b"x" * (guest_transfer.MAX_TRANSFER_BYTES + 1))
        self.assertEqual(ctx.exception.code, "guest_file_too_large")


if __name__ == "__main__":
    unittest.main()
