from __future__ import absolute_import

import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.dependencies import (  # noqa: E402
    MINIMUM_DWS_VERSION,
    discover_dws,
    verify_dws,
)


class CommandResult(object):
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


class FakeRunner(object):
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def run(self, command):
        self.calls.append(command)
        response = self.responses.get(tuple(command))
        if response is None:
            return CommandResult(returncode=127)
        return response


def verified_runner(executable, version="1.0.15"):
    return FakeRunner({
        (executable, "--version", "--format", "json"):
            CommandResult('{"version":"%s"}' % version),
        (executable, "auth", "status", "--help"):
            CommandResult("Usage: status --format json"),
        (executable, "auth", "login", "--help"):
            CommandResult("Usage: login --format json"),
        (executable, "profile", "list", "--help"):
            CommandResult("Usage: list --format json"),
    })


class DwsDiscoveryTests(unittest.TestCase):
    def test_explicit_absolute_dws_executable_precedes_path_lookup(self):
        calls = []

        def which(name):
            calls.append(name)
            return "/path/dws"

        status = discover_dws(
            {"DWS_EXE": "/approved/dws"}, "darwin", which
        )

        self.assertEqual(status.executable, "/approved/dws")
        self.assertEqual(calls, [])

    def test_relative_dws_override_is_rejected_before_path_lookup(self):
        status = discover_dws(
            {"DWS_EXE": "relative/dws"}, "linux", lambda name: "/path/dws"
        )

        self.assertEqual(status.status, "unavailable")
        self.assertEqual(status.reason, "dws_executable_invalid")
        self.assertIsNone(status.executable)

    def test_path_lookup_precedes_documented_local_candidates(self):
        calls = []

        def which(name):
            calls.append(name)
            if name == "dws":
                return "/usr/bin/dws"
            return None

        status = discover_dws({"HOME": "/home/agent"}, "linux", which)

        self.assertEqual(status.executable, "/usr/bin/dws")
        self.assertEqual(calls, ["dws"])

    def test_user_local_candidate_precedes_homebrew_on_macos(self):
        calls = []

        def which(name):
            calls.append(name)
            if name == "/Users/agent/.local/bin/dws":
                return name
            if name == "/opt/homebrew/bin/dws":
                return name
            return None

        status = discover_dws({"HOME": "/Users/agent"}, "darwin", which)

        self.assertEqual(status.executable, "/Users/agent/.local/bin/dws")
        self.assertNotIn("/opt/homebrew/bin/dws", calls)

    def test_homebrew_candidate_precedes_npm_global_candidate(self):
        calls = []

        def which(name):
            calls.append(name)
            if name in ("/opt/homebrew/bin/dws", "/usr/local/bin/dws"):
                return name
            return None

        status = discover_dws(
            {"HOME": "/Users/agent", "NPM_CONFIG_PREFIX": "/npm"},
            "darwin",
            which,
        )

        self.assertEqual(status.executable, "/opt/homebrew/bin/dws")
        self.assertNotIn("/npm/bin/dws", calls)

    def test_npm_prefix_candidate_is_used_only_when_discoverable(self):
        def which(name):
            if name == "/npm/bin/dws":
                return name
            return None

        status = discover_dws(
            {"HOME": "/home/agent", "NPM_CONFIG_PREFIX": "/npm"},
            "linux",
            which,
        )

        self.assertEqual(status.executable, "/npm/bin/dws")

    def test_missing_dws_returns_stable_install_required_reason(self):
        status = discover_dws({"HOME": "/home/agent"}, "linux", lambda name: None)

        self.assertEqual(status.status, "action_required")
        self.assertEqual(status.reason, "dependency_install_required")
        self.assertEqual(status.minimum_version, "1.0.15")


class DwsVerificationTests(unittest.TestCase):
    def test_nonexistent_absolute_executable_is_rejected_without_running_it(self):
        executable = os.path.join(
            tempfile.gettempdir(), "missing-dws-task-1-executable"
        )
        runner = FakeRunner({})

        status = verify_dws(executable, runner)

        self.assertEqual(status.status, "unavailable")
        self.assertEqual(status.reason, "dws_executable_invalid")
        self.assertEqual(runner.calls, [])

    def test_version_below_1_0_15_requires_upgrade(self):
        executable = sys.executable
        runner = verified_runner(executable, version="1.0.14")

        status = verify_dws(executable, runner)

        self.assertEqual(status.status, "action_required")
        self.assertEqual(status.reason, "dws_upgrade_required")
        self.assertEqual(status.version, "1.0.14")
        self.assertEqual(runner.calls, [
            [executable, "--version", "--format", "json"],
        ])

    def test_minimum_version_is_exactly_1_0_15(self):
        self.assertEqual(MINIMUM_DWS_VERSION, "1.0.15")

    def test_semantic_version_comparison_accepts_later_minor_version(self):
        executable = sys.executable

        status = verify_dws(executable, verified_runner(executable, "1.1.0"))

        self.assertEqual(status.status, "ready")
        self.assertEqual(status.reason, "dependency_ready")
        self.assertEqual(status.version, "1.1.0")

    def test_prerelease_of_minimum_version_still_requires_upgrade(self):
        executable = sys.executable

        status = verify_dws(
            executable, verified_runner(executable, "1.0.15-rc.1")
        )

        self.assertEqual(status.status, "action_required")
        self.assertEqual(status.reason, "dws_upgrade_required")

    def test_version_output_must_be_a_json_object(self):
        executable = sys.executable
        runner = FakeRunner({
            (executable, "--version", "--format", "json"):
                CommandResult("dws version 1.0.15"),
        })

        status = verify_dws(executable, runner)

        self.assertEqual(status.status, "unavailable")
        self.assertEqual(status.reason, "dependency_version_unsupported")

    def test_version_must_be_parseable_semver(self):
        executable = sys.executable
        runner = FakeRunner({
            (executable, "--version", "--format", "json"):
                CommandResult('{"version":"latest"}'),
        })

        status = verify_dws(executable, runner)

        self.assertEqual(status.reason, "dependency_version_unsupported")

    def test_required_leaf_help_must_advertise_json_output(self):
        executable = sys.executable
        runner = verified_runner(executable)
        runner.responses[(executable, "auth", "login", "--help")] = CommandResult(
            "Usage: login"
        )

        status = verify_dws(executable, runner)

        self.assertEqual(status.status, "unavailable")
        self.assertEqual(status.reason, "dependency_verification_failed")
        self.assertEqual(runner.calls[-1], [executable, "auth", "login", "--help"])

    def test_success_revalidates_all_required_json_leaf_capabilities(self):
        executable = sys.executable
        runner = verified_runner(executable)

        status = verify_dws(executable, runner)

        self.assertEqual(status.status, "ready")
        self.assertEqual(status.reason, "dependency_ready")
        self.assertEqual(status.executable, executable)
        self.assertEqual(status.minimum_version, "1.0.15")
        self.assertEqual(runner.calls, [
            [executable, "--version", "--format", "json"],
            [executable, "auth", "status", "--help"],
            [executable, "auth", "login", "--help"],
            [executable, "profile", "list", "--help"],
        ])

    def test_dependency_results_are_immutable(self):
        status = discover_dws({"DWS_EXE": "/approved/dws"}, "darwin", lambda name: None)

        with self.assertRaises(AttributeError):
            status.executable = "/changed/dws"


if __name__ == "__main__":
    unittest.main()
