from __future__ import absolute_import

import json
import os
import subprocess
import sys
import tempfile
import unittest
import shutil


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.contract import build_envelope


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.directory.name, "config.json")
        self.ledger_path = os.path.join(self.directory.name, "ledger.sqlite3")
        self.state_path = os.path.join(self.directory.name, "state")
        self.envelope_path = os.path.join(self.directory.name, "envelope.json")
        with open(os.path.join(FIXTURES, "standard-report.md"), encoding="utf-8") as handle:
            markdown = handle.read()
        with open(os.path.join(FIXTURES, "standard-report.json"), encoding="utf-8") as handle:
            report_json = json.load(handle)
        envelope = build_envelope(markdown, report_json, "", "deterministic", "2.4.0")
        with open(self.envelope_path, "w") as handle:
            json.dump(envelope.to_dict(), handle)
        self.dws_path = os.path.join(self.directory.name, "dws")
        with open(self.dws_path, "w") as handle:
            handle.write("#!/bin/sh\n")
            handle.write("case \"$*\" in\n")
            handle.write("  '--help') echo 'DWS help' ;;\n")
            handle.write("  *'auth status --help'*) echo '--format json' ;;\n")
            handle.write("  *'auth status --format json'*) echo '{\"authenticated\":true}' ;;\n")
            handle.write("  *'profile list --help'*) echo '--format json' ;;\n")
            handle.write("  *'profile list --format json'*) echo '{\"profiles\":[{\"profile\":\"corp:user\"}]}' ;;\n")
            handle.write("  *) exit 1 ;;\n")
            handle.write("esac\n")
        os.chmod(self.dws_path, 0o755)
        with open(self.config_path, "w") as handle:
            json.dump({
                "version": 1,
                "notification": {
                    "enabled": True,
                    "failure_policy": "non_blocking",
                    "ai_summary": {"provider": "host_agent", "fallback": "deterministic"},
                    "channels": [{
                        "platform": "dingtalk",
                        "provider": "auto",
                        "profile": "corp:user",
                        "recipients": [],
                    }],
                },
            }, handle)

    def tearDown(self):
        self.directory.cleanup()

    def test_unix_launcher_forwards_deliver_arguments_as_json(self):
        result = self._run(os.path.join(ROOT, "run.sh"), "deliver")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "recipient_not_configured")
        self.assertEqual(result.stdout.strip().count("\n"), 0)

    def test_launcher_has_all_cross_platform_entrypoints(self):
        for name in ("run.sh", "run.bat", "run.ps1"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, name)))

    def test_windows_launchers_forward_all_arguments(self):
        with open(os.path.join(ROOT, "run.bat"), encoding="utf-8") as handle:
            batch = handle.read()
        with open(os.path.join(ROOT, "run.ps1"), encoding="utf-8") as handle:
            powershell = handle.read()
        self.assertIn('%*', batch)
        self.assertIn('@ForwardedArgs', powershell)
        self.assertIn('run.ps1" %*', batch)
        self.assertIn('PYTHONUTF8', powershell)
        with open(os.path.join(ROOT, "run.sh"), encoding="utf-8") as handle:
            self.assertIn("PYTHONUTF8=1", handle.read())

    def test_unix_launcher_forwards_setup_arguments_without_evaluation(self):
        capture_path = os.path.join(self.directory.name, "argv.json")
        python_path = os.path.join(self.directory.name, "capture-python")
        with open(python_path, "w", encoding="utf-8") as handle:
            handle.write("#!/bin/sh\n")
            handle.write("printf '%s\\n' \"$@\" > \"$CAPTURE_PATH\"\n")
        os.chmod(python_path, 0o755)
        marker = os.path.join(self.directory.name, "must-not-exist")
        arguments = [
            "setup", "--platform", "dingtalk", "--provider", "dws-cli",
            "--capabilities", "capabilities;touch " + marker,
            "--install-dws", "--china-mirror", "--device-login", "--yes",
        ]
        environment = dict(
            os.environ,
            ENTERPRISE_NOTIFICATION_BRIDGE_PYTHON=python_path,
            CAPTURE_PATH=capture_path,
        )

        result = subprocess.run(
            [os.path.join(ROOT, "run.sh")] + arguments,
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        with open(capture_path, encoding="utf-8") as handle:
            forwarded = handle.read().splitlines()
        self.assertEqual(forwarded[1:], arguments)
        self.assertTrue(forwarded[0].endswith("main.py"))
        self.assertFalse(os.path.exists(marker))

    def test_launchers_do_not_use_dynamic_shell_evaluation(self):
        for name in ("run.sh", "run.ps1"):
            with self.subTest(name=name):
                with open(os.path.join(ROOT, name), encoding="utf-8") as handle:
                    source = handle.read().lower()
                self.assertNotIn("eval ", source)
                self.assertNotIn("invoke-expression", source)

    @unittest.skipUnless(shutil.which("pwsh") or shutil.which("powershell"),
                         "PowerShell is not available on this host")
    def test_powershell_launcher_forwards_help_when_available(self):
        executable = shutil.which("pwsh") or shutil.which("powershell")
        result = subprocess.run(
            [executable, "-NoProfile", "-File", os.path.join(ROOT, "run.ps1"), "--help"],
            env=dict(os.environ, ENTERPRISE_NOTIFICATION_BRIDGE_PYTHON=sys.executable),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "ok")

    def _run(self, launcher, command):
        environment = os.environ.copy()
        environment["ENTERPRISE_NOTIFICATION_BRIDGE_CONFIG"] = self.config_path
        environment["ENTERPRISE_NOTIFICATION_BRIDGE_LEDGER"] = self.ledger_path
        environment["ENTERPRISE_NOTIFICATION_BRIDGE_STATE"] = self.state_path
        environment["ENTERPRISE_NOTIFICATION_BRIDGE_PYTHON"] = sys.executable
        environment["PATH"] = self.directory.name + os.pathsep + environment.get("PATH", "")
        return subprocess.run(
            [launcher, command, "--envelope", self.envelope_path],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=False,
        )


if __name__ == "__main__":
    unittest.main()
