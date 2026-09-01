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
        self.assertIn('@args', powershell)
        self.assertIn('run.ps1" %*', batch)

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
