import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from vcenter_aiops.cli.main import main
from test_execution import FakeProvider


class WriteCliTests(unittest.TestCase):
    def test_interactive_single_command_can_apply_after_exact_confirmation(self):
        from vcenter_aiops.application.context import Context
        from vcenter_aiops.application.execution import Engine
        from vcenter_aiops.application.providers import ProviderRouter
        from vcenter_aiops.infrastructure.store import Store
        class Terminal(io.StringIO):
            def isatty(self):
                return True
        @contextlib.contextmanager
        def session(ctx):
            yield object()
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"VCENTER_AIOPS_HOME": temp}):
            provider = FakeProvider()
            store = Store(Path(temp) / "state.db")
            plan = Engine(store, ProviderRouter(None, {"vm": provider}), "lab").preview("vm power-on", {"vm_id": "vm-1"}, "tty-test").data
            store.close()
            with patch.object(Context, "session", session), patch("vcenter_aiops.providers.vsphere.mutations.Mutations", return_value=provider), patch("sys.stdin", Terminal(plan["digest"] + "\n")), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                code = main(["--profile", "lab", "vm", "power-on", "--vm-id", "vm-1", "--request-id", "tty-test", "--no-wait"])
            self.assertEqual(code, 0)
            self.assertEqual(provider.submissions, ["vm power-on"])

    def test_cli_preview_apply_reconcile_share_one_engine(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"VCENTER_AIOPS_HOME": temp}):
            from vcenter_aiops.application.context import Context
            @contextlib.contextmanager
            def session(ctx):
                yield object()
            provider = FakeProvider()
            with patch.object(Context, "session", session), patch("vcenter_aiops.providers.vsphere.mutations.Mutations", return_value=provider):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = main(["--profile", "lab", "vm", "power-on", "--vm-id", "vm-1", "--request-id", "cli-1"])
                self.assertEqual(code, 4)
                plan = json.loads(output.getvalue())["data"]
                self.assertEqual(provider.submissions, [])
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = main(["--profile", "lab", "plan", "apply", plan["id"], "--confirm", plan["digest"]])
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(output.getvalue())["status"], "succeeded")
                self.assertEqual(provider.submissions, ["vm power-on"])

    def test_invalid_write_parameters_do_not_create_state(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"VCENTER_AIOPS_HOME": temp + "/data"}):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["vm", "reconfigure", "--vm-id", "vm-1", "--cpu", "0"])
            self.assertEqual(code, 2)
            self.assertFalse(Path(temp, "data").exists())

    def test_task_inspect_reports_persisted_state_without_connecting(self):
        from vcenter_aiops.infrastructure.store import Store
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"VCENTER_AIOPS_HOME": temp}):
            store = Store(Path(temp) / "state.db")
            op = store.prepare("test-1", "server-a:vm-1", {"command": "vm power-on"})
            store.claim(op["id"])
            store.close()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["task", "inspect", op["id"]])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.getvalue())["data"]["state"], "submitting")

    def test_plan_file_cannot_execute_arbitrary_shell_or_unknown_params(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"VCENTER_AIOPS_HOME": temp + "/data"}):
            source = Path(temp) / "plan.json"
            source.write_text(json.dumps({"steps": [{"command": "shell exec", "params": {"program": "bad"}}]}))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = main(["--profile", "lab", "plan", "create", "--file", str(source)])
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(output.getvalue())["error"]["code"], "command_unknown")
            self.assertFalse(Path(temp, "data").exists())
