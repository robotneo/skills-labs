import os
import stat
import subprocess
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(__file__))


class LauncherTests(unittest.TestCase):
    def test_macos_launcher_skips_broken_python_and_uses_override(self):
        real_python = os.environ.get("TEST_PYTHON")
        if not real_python:
            self.skipTest("TEST_PYTHON is required for launcher integration test")
        result = subprocess.run(
            ["/bin/sh", os.path.join(ROOT, "run.sh"), "--help"],
            env=dict(os.environ, WIFI_HEALTH_PYTHON=real_python),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("--no-public-test", result.stdout)

    def test_macos_launcher_reports_runtime_problem_not_wifi_problem(self):
        with tempfile.TemporaryDirectory() as directory:
            broken = os.path.join(directory, "python3")
            with open(broken, "w") as handle:
                handle.write("#!/bin/sh\necho 'xcrun: invalid active developer path' >&2\nexit 1\n")
            os.chmod(broken, stat.S_IRWXU)
            env = dict(os.environ, PATH=directory, WIFI_HEALTH_PYTHON=broken)
            result = subprocess.run(
                ["/bin/sh", os.path.join(ROOT, "run.sh"), "--help"],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                universal_newlines=True,
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Python", result.stdout)
        self.assertNotIn("Wi-Fi is disconnected", result.stdout)


if __name__ == "__main__":
    unittest.main()
