"""H-1 regression: guest-output/download/upload handlers must return a Result.

Previously these three handlers returned a bare dict (or the provider dict
directly), so the CLI post-processing chain raised AttributeError *after* a
successful transfer, surfacing as internal_error/exit 5 and inviting duplicate
uploads. These tests drive the real ``main()`` end to end with a fake guest
provider and assert exit 0 plus the on-disk effect.
"""
import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vcenter_aiops.cli.main import main
from vcenter_aiops.infrastructure.paths import data_home
from vcenter_aiops.infrastructure.store import Store


RUN_ID = "a" * 32


class FakeGuest:
    def __init__(self):
        self.uploads = []

    def fetch_output(self, binding):
        return {"state": "succeeded", "run_id": RUN_ID,
                "stdout": "hello", "stderr": "", "exit_code": 0}

    def download_file(self, vm_id, username, credential_ref, guest_path, family):
        return {"state": "succeeded", "guest_path": guest_path,
                "transferred_bytes": 5, "payload": b"hello"}

    def upload_file(self, vm_id, username, credential_ref, guest_path, family,
                    payload, overwrite=False):
        self.uploads.append((guest_path, payload, overwrite))
        return {"state": "succeeded", "guest_path": guest_path,
                "transferred_bytes": len(payload), "overwritten": overwrite}


class FakeRouter:
    guest = FakeGuest()

    def __init__(self, *args, **kwargs):
        pass

    def _provider(self, kind):
        assert kind == "guest"
        return FakeRouter.guest


@contextlib.contextmanager
def fake_session(ctx):
    yield object()


def run(argv, stdin=""):
    out, err = io.StringIO(), io.StringIO()
    with (patch("sys.stdin", io.StringIO(stdin)),
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err)):
        code = main(list(argv))
    return code, json.loads(out.getvalue()), err.getvalue()


class GuestFileCommandResultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"VCENTER_AIOPS_HOME": self.temp.name})
        self.env.start()
        FakeRouter.guest = FakeGuest()
        # A resolvable (but never connected) profile for the active --profile.
        root = data_home()
        root.mkdir(parents=True, exist_ok=True)
        (root / "config.yaml").write_text(
            "schema_version: 1\nprofiles:\n  lab:\n"
            "    host: vcenter.lab.example\n    user: admin\n"
            "    password_ref: env:GUEST_PASS\n    verify_tls: false\n",
            encoding="utf-8")
        # A trusted plan row so guest_output can resolve the run binding.
        store = Store(data_home() / "state.db")
        try:
            store.create_plan([{
                "command": "vm guest-exec-output",
                "params": {},
                "binding": {"provider_kind": "guest",
                            "run": {"run_id": RUN_ID, "capture_output": True}},
            }], "lab")
        finally:
            store.close()
        self._patches = [
            patch("vcenter_aiops.application.context.Context.session", fake_session),
            patch("vcenter_aiops.application.commands.guest.ProviderRouter", FakeRouter),
        ]
        for patcher in self._patches:
            patcher.start()

    def tearDown(self):
        for patcher in self._patches:
            patcher.stop()
        self.env.stop()
        self.temp.cleanup()

    def test_guest_output_success_returns_result_exit0(self):
        code, result, err = run(["--profile", "lab", "vm", "guest-output", RUN_ID])
        self.assertEqual(code, 0, err)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["data"]["state"], "succeeded")
        self.assertEqual(result["data"]["stdout"], "hello")
        self.assertEqual(result["data"]["run_id"], RUN_ID)

    def test_guest_download_writes_file_and_returns_result_exit0(self):
        target = Path(self.temp.name) / "sub" / "out.bin"
        code, result, err = run(["--yes", "--profile", "lab", "vm", "guest-download",
                                 "--vm-id", "vm-1", "--guest-username", "root",
                                 "--credential-ref", "env:G", "--os-family", "linux",
                                 "--guest-path", "/tmp/x", "--file", str(target)])
        self.assertEqual(code, 0, err)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["data"]["state"], "succeeded")
        self.assertEqual(result["data"]["file"], str(target))
        self.assertNotIn("payload", result["data"])
        self.assertTrue(target.exists())
        self.assertEqual(target.read_bytes(), b"hello")
        mode = stat.S_IMODE(target.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_guest_upload_transfers_and_returns_result_exit0(self):
        source = Path(self.temp.name) / "in.bin"
        source.write_bytes(b"abcd")
        code, result, err = run(["--yes", "--profile", "lab", "vm", "guest-upload",
                                 "--vm-id", "vm-1", "--guest-username", "root",
                                 "--credential-ref", "env:G", "--os-family", "linux",
                                 "--file", str(source), "--guest-path", "/tmp/in.bin"])
        self.assertEqual(code, 0, err)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["data"]["state"], "succeeded")
        self.assertEqual(result["data"]["transferred_bytes"], 4)
        self.assertEqual(FakeRouter.guest.uploads,
                         [("/tmp/in.bin", b"abcd", False)])


if __name__ == "__main__":
    unittest.main()
