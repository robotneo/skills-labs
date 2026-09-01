from __future__ import absolute_import

import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST_PATH = os.path.join(ROOT, "manifest.json")
SKILL_YAML_PATH = os.path.join(ROOT, "skill.yaml")
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
    json_format_help = (
        'Options:\n  --format <format>  Output format '
        '[allowed values: "text", "json"]'
    )
    return FakeRunner({
        (executable, "--version", "--format", "json"):
            CommandResult('{"version":"%s"}' % version),
        (executable, "auth", "status", "--help"):
            CommandResult(json_format_help),
        (executable, "auth", "login", "--help"):
            CommandResult(json_format_help),
        (executable, "profile", "list", "--help"):
            CommandResult(json_format_help),
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

    def test_windows_candidates_use_windows_paths_in_documented_order(self):
        calls = []

        def which(name):
            calls.append(name)
            if name == r"C:\npm\dws.cmd":
                return name
            return None

        status = discover_dws(
            {
                "USERPROFILE": r"C:\Users\agent",
                "NPM_CONFIG_PREFIX": r"C:\npm",
            },
            "windows",
            which,
        )

        self.assertEqual(status.executable, r"C:\npm\dws.cmd")
        self.assertEqual(calls, [
            "dws",
            r"C:\Users\agent\.local\bin\dws.cmd",
            r"C:\Users\agent\AppData\Roaming\npm\dws.cmd",
            r"C:\npm\dws.cmd",
        ])

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

    def test_numeric_prerelease_identifier_rejects_leading_zero(self):
        executable = sys.executable

        status = verify_dws(
            executable, verified_runner(executable, "1.0.16-01")
        )

        self.assertEqual(status.status, "unavailable")
        self.assertEqual(status.reason, "dependency_version_unsupported")

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

    def test_leaf_help_rejects_json_mentioned_as_unsupported(self):
        executable = sys.executable
        runner = verified_runner(executable)
        runner.responses[(executable, "auth", "status", "--help")] = CommandResult(
            "Options:\n"
            "  --format <format>  Output format; json is unsupported"
        )

        status = verify_dws(executable, runner)

        self.assertEqual(status.status, "unavailable")
        self.assertEqual(status.reason, "dependency_verification_failed")
        self.assertEqual(runner.calls[-1], [executable, "auth", "status", "--help"])

    def test_leaf_help_does_not_cross_semicolon_into_json_explanation(self):
        executable = sys.executable
        runner = verified_runner(executable)
        runner.responses[(executable, "auth", "status", "--help")] = CommandResult(
            "Options:\n"
            "  --format <format> allowed values: text; "
            "this command does not support json"
        )

        status = verify_dws(executable, runner)

        self.assertEqual(status.status, "unavailable")
        self.assertEqual(status.reason, "dependency_verification_failed")

    def test_leaf_help_does_not_cross_sentence_into_unrelated_json_text(self):
        executable = sys.executable
        runner = verified_runner(executable)
        runner.responses[(executable, "auth", "status", "--help")] = CommandResult(
            "Options:\n"
            "  --format <format> allowed values: text. "
            "JSON output is documented by another command."
        )

        status = verify_dws(executable, runner)

        self.assertEqual(status.status, "unavailable")
        self.assertEqual(status.reason, "dependency_verification_failed")

    def test_leaf_help_accepts_common_structured_json_value_sets(self):
        executable = sys.executable
        help_forms = (
            '  --format <format> [choices: "text", "json"]',
            "  --format <text|json>  Select output encoding",
            "  --format <format>  Output encoding [default: json]",
        )

        for help_text in help_forms:
            runner = verified_runner(executable)
            runner.responses[
                (executable, "auth", "status", "--help")
            ] = CommandResult(help_text)

            status = verify_dws(executable, runner)

            self.assertEqual(status.status, "ready", help_text)
            self.assertEqual(status.reason, "dependency_ready", help_text)

    def test_leaf_help_accepts_choices_on_indented_continuation_line(self):
        executable = sys.executable
        runner = verified_runner(executable)
        runner.responses[(executable, "auth", "status", "--help")] = CommandResult(
            "Options:\n"
            "  --format <format>  Select output encoding\n"
            "      choices: text, json\n"
            "  --profile <profile>  Select a profile"
        )

        status = verify_dws(executable, runner)

        self.assertEqual(status.status, "ready")
        self.assertEqual(status.reason, "dependency_ready")

    def test_leaf_help_rejects_json_only_inside_parenthetical_note(self):
        executable = sys.executable
        runner = verified_runner(executable)
        runner.responses[(executable, "auth", "status", "--help")] = CommandResult(
            "Options:\n"
            "  --format <format> [choices: text, yaml (no json support)]"
        )

        status = verify_dws(executable, runner)

        self.assertEqual(status.status, "unavailable")
        self.assertEqual(status.reason, "dependency_verification_failed")

    def test_leaf_help_accepts_multiline_allowed_values_and_default_fields(self):
        executable = sys.executable
        help_forms = (
            "Options:\n"
            "  --format <format>  Select output encoding\n"
            "      allowed values: text | json",
            "Options:\n"
            "  --format <format>  Select output encoding\n"
            "      default: json",
        )

        for help_text in help_forms:
            runner = verified_runner(executable)
            runner.responses[
                (executable, "auth", "status", "--help")
            ] = CommandResult(help_text)

            status = verify_dws(executable, runner)

            self.assertEqual(status.status, "ready", help_text)
            self.assertEqual(status.reason, "dependency_ready", help_text)

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


class DependencyMetadataTests(unittest.TestCase):
    def test_manifest_keeps_python_unconditional_and_dws_conditional(self):
        with open(MANIFEST_PATH, "r") as handle:
            manifest = json.load(handle)

        self.assertEqual(manifest["requirements"], ["python>=3.7"])
        self.assertEqual(
            manifest["conditional_requirements"],
            {"dingtalk:dws-cli": ["dws>=1.0.15"]},
        )

    def test_skill_yaml_keeps_python_unconditional_and_dws_conditional(self):
        with open(SKILL_YAML_PATH, "r") as handle:
            lines = [line.rstrip("\n") for line in handle]

        self.assertIn("requirements: [python>=3.7]", lines)
        section = lines.index("conditional_requirements:")
        self.assertEqual(
            lines[section + 1], "  dingtalk:dws-cli: [dws>=1.0.15]"
        )


if __name__ == "__main__":
    unittest.main()
