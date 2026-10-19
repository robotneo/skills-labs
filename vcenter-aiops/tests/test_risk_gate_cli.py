"""CLI pre-execution risk gate: offline, no remote connection.

These tests drive the real ``main()`` for direct-effect commands (local writes
/ exports), which bypass the plan engine and therefore need their own explicit
confirmation gate. Engine-backed remote writes keep their plan digest flow and
are covered by test_write_cli.
"""
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vcenter_aiops.cli.main import main


class TTY(io.StringIO):
    def __init__(self, text="", tty=True):
        super().__init__(text)
        self._tty = tty

    def isatty(self):
        return self._tty


class BulkProvider:
    """Multi-step fake supporting batch projection; the engine/SQLite are real."""
    def __init__(self):
        self.identity = "server-a"
        self.submissions = []

    def _binding(self, command, params):
        return {"target": "%s:%s" % (self.identity, params["vm_id"]), "server_uuid": self.identity,
                "object_id": params["vm_id"], "instance_uuid": "uuid-" + params["vm_id"],
                "before": {"power": "poweredOn"}, "risk": "change"}

    def preflight(self, command, params):
        return self._binding(command, params)

    def bind_steps(self, steps):
        return [{**s, "binding": self._binding(s["command"], s["params"])} for s in steps]

    def matches(self, expected, actual):
        return expected.get("object_id") == actual.get("object_id")

    def submit(self, command, params, binding):
        self.submissions.append(command)
        return {"task_id": "%s:task-%s" % (self.identity, params["vm_id"])}

    def observe(self, receipt, binding):
        return {"state": "success", "cancelled": False}

    def verify(self, command, params, binding, observation):
        return True


def run(argv, stdin="", tty=False):
    out, err = io.StringIO(), io.StringIO()
    with patch("sys.stdin", TTY(stdin, tty)), \
            contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(list(argv))
    return code, json.loads(out.getvalue()), err.getvalue()


class RiskGateCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        key = "T8T2J9k0Yq3Wv1pZxQ7nR4mH6cF5bL0dG8sV2eYwA3o="
        self.env = patch.dict(os.environ, {
            "VCENTER_AIOPS_HOME": self.temp.name,
            "VCENTER_AIOPS_MASTER_KEY": key})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def _create_secret(self, name="one", value="pw"):
        code, _, _ = run(["--yes", "secret", "set", name, "--stdin"], stdin=value)
        self.assertEqual(code, 0)

    # ---- low risk runs directly, no prompt --------------------------------
    def test_low_risk_read_runs_directly_non_tty(self):
        code, result, _ = run(["version"])
        self.assertEqual(code, 0)
        self.assertIn("version", result["data"])

    # ---- medium risk -------------------------------------------------------
    def test_medium_non_tty_without_yes_is_blocked_exit4(self):
        code, result, err = run(["secret", "set", "one", "--stdin"], stdin="pw")
        self.assertEqual(code, 4)
        self.assertEqual(result["error"]["code"], "confirmation_required")
        self.assertIn("中风险", err)
        self.assertFalse((Path(self.temp.name) / "secrets.json").exists())

    def test_medium_yes_authorises_non_tty(self):
        code, _, err = run(["--yes", "secret", "set", "one", "--stdin"], stdin="pw")
        self.assertEqual(code, 0)
        self.assertIn("--yes", err)

    def test_medium_yes_after_verb_also_works(self):
        code, _, _ = run(["secret", "set", "one", "--stdin", "--yes"], stdin="pw")
        self.assertEqual(code, 0)

    def test_medium_tty_requires_exact_token(self):
        code, result, _ = run(["secret", "set", "one", "--stdin"], stdin="pw\ntwo\n", tty=True)
        self.assertEqual(code, 4)
        self.assertEqual(result["error"]["code"], "confirmation_declined")

    def test_medium_tty_exact_token_proceeds(self):
        # Gate reads the confirmation token first; the handler then reads the
        # secret payload from the same stdin (--stdin).
        code, _, _ = run(["secret", "set", "one", "--stdin"], stdin="one\npw\n", tty=True)
        self.assertEqual(code, 0)

    # ---- high risk: precise target + second confirmation ------------------
    def test_high_non_tty_without_yes_blocked(self):
        self._create_secret()
        code, result, _ = run(["secret", "delete", "one"])
        self.assertEqual(code, 4)
        self.assertEqual(result["error"]["code"], "confirmation_required")

    def test_high_tty_wrong_token_declined(self):
        self._create_secret()
        code, result, _ = run(["secret", "delete", "one"], stdin="two\n", tty=True)
        self.assertEqual(code, 4)
        self.assertEqual(result["error"]["code"], "confirmation_declined")

    def test_high_tty_right_token_wrong_keyword_declined(self):
        self._create_secret()
        code, result, _ = run(["secret", "delete", "one"], stdin="one\nREMOVE\n", tty=True)
        self.assertEqual(code, 4)
        self.assertEqual(result["error"]["code"], "confirmation_declined")

    def test_high_tty_exact_token_and_delete_keyword_proceeds(self):
        self._create_secret()
        code, result, err = run(["secret", "delete", "one"], stdin="one\nDELETE\n", tty=True)
        self.assertEqual(code, 0, err)
        self.assertEqual(result["data"]["deleted"], "one")

    def test_high_yes_still_rejects_fuzzy_target(self):
        self._create_secret()
        # The wildcard is rejected as an invalid target even with --yes, before
        # any storage mutation.
        code, result, _ = run(["--yes", "secret", "delete", "vm-*"])
        self.assertEqual(code, 2)
        self.assertIn(result["error"]["code"], ("target_not_exact", "secret_name_invalid"))

    # ---- export egress -----------------------------------------------------
    def test_inventory_export_requires_confirmation_offline(self):
        # Without a reachable vCenter the command cannot succeed; the gate must
        # still fire first (exit 4 confirmation, not a connection error), proving
        # the gate precedes the handler/network call.
        code, result, err = run(["--profile", "lab", "inventory", "export", "--file",
                                 str(Path(self.temp.name) / "out.json")])
        self.assertEqual(code, 4)
        self.assertEqual(result["error"]["code"], "confirmation_required")
        self.assertIn("数据外发", err)

    # ---- bulk: enumerate targets, digest, then BATCH-<count> ---------------
    def _bulk_preview_digest(self, provider, request_id):
        import contextlib as _cl
        from vcenter_aiops.application.context import Context

        @_cl.contextmanager
        def session(ctx):
            yield object()
        out = io.StringIO()
        argv = ["--profile", "lab", "batch", "power-off",
                "--vm-ids", '["vm-1","vm-2"]', "--request-id", request_id]
        with patch.object(Context, "session", session), \
                patch("vcenter_aiops.providers.vsphere.mutations.Mutations", return_value=provider), \
                patch("sys.stdin", TTY("", tty=False)), \
                contextlib.redirect_stdout(out):
            code = main(argv)
        self.assertEqual(code, 4)
        return json.loads(out.getvalue())["data"]["digest"]

    def _run_bulk_tty(self, provider, digest, second_line):
        import contextlib as _cl
        from vcenter_aiops.application.context import Context

        @_cl.contextmanager
        def session(ctx):
            yield object()
        out, err = io.StringIO(), io.StringIO()
        stdin = TTY(digest + "\n" + second_line + "\n", tty=True)
        argv = ["--profile", "lab", "batch", "power-off",
                "--vm-ids", '["vm-1","vm-2"]', "--request-id", "bulk-tty"]
        with patch.object(Context, "session", session), \
                patch("vcenter_aiops.providers.vsphere.mutations.Mutations", return_value=provider), \
                patch("sys.stdin", stdin), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, err.getvalue()

    def test_bulk_requires_digest_then_batch_count_confirmation(self):
        provider = BulkProvider()
        digest = self._bulk_preview_digest(provider, "bulk-tty")
        code, err = self._run_bulk_tty(provider, digest, "BATCH-2")
        self.assertEqual(code, 0, err)
        self.assertEqual(provider.submissions, ["vm power-off", "vm power-off"])
        self.assertIn("#1", err) and self.assertIn("vm-1", err) and self.assertIn("共 2 台", err)

    def test_bulk_wrong_count_confirmation_cancels_without_submission(self):
        provider = BulkProvider()
        digest = self._bulk_preview_digest(provider, "bulk-tty")
        code, _ = self._run_bulk_tty(provider, digest, "BATCH-3")
        self.assertEqual(code, 4)
        self.assertEqual(provider.submissions, [])


if __name__ == "__main__":
    unittest.main()
