from __future__ import absolute_import

import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.providers.dws import DwsProvider, choose_profile


class CommandResult(object):
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


class FakeRunner(object):
    def __init__(self, stdout, returncode=0, responses=None):
        self.stdout = stdout
        self.returncode = returncode
        self.responses = responses or {}
        self.calls = []

    def run(self, command):
        self.calls.append(command)
        response = self.responses.get(tuple(command))
        if response is not None:
            return response
        return CommandResult(self.stdout, self.returncode)


class DwsProviderTests(unittest.TestCase):
    def test_dws_profile_list_uses_json_and_stable_profile(self):
        help_command = ["dws", "profile", "list", "--help"]
        business_command = ["dws", "profile", "list", "--format", "json"]
        runner = FakeRunner("", responses={
            tuple(help_command): CommandResult("--format json"),
            tuple(business_command): CommandResult(
                '{"profiles":[{"profile":"corp:user","isCurrent":true}]}'
            ),
        })
        result = DwsProvider(runner).list_profiles()

        self.assertEqual(runner.calls, [help_command, business_command])
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.data["profile"], "corp:user")

    def test_dws_profile_list_requires_selection_for_multiple_profiles(self):
        help_command = ["dws", "profile", "list", "--help"]
        business_command = ["dws", "profile", "list", "--format", "json"]
        profiles = [{"profile": "corp:one"}, {"profile": "corp:two"}]
        runner = FakeRunner("", responses={
            tuple(help_command): CommandResult("--format json"),
            tuple(business_command): CommandResult('{"profiles":['
                '{"profile":"corp:one"},{"profile":"corp:two"}]}'),
        })

        result = DwsProvider(runner).list_profiles()

        self.assertEqual(runner.calls, [help_command, business_command])
        self.assertEqual(result.status, "action_required")
        self.assertEqual(result.reason, "profile_selection_required")
        self.assertEqual(result.data["profiles"], profiles)

    def test_auth_status_uses_the_documented_json_command(self):
        help_command = ["dws", "auth", "status", "--help"]
        business_command = ["dws", "auth", "status", "--format", "json"]
        runner = FakeRunner("", responses={
            tuple(help_command): CommandResult("Usage: status --format json"),
            tuple(business_command): CommandResult('{"authenticated":true}'),
        })

        result = DwsProvider(runner).auth_status("corp:user")

        self.assertEqual(runner.calls, [help_command, business_command])
        self.assertEqual(result.data, {"authenticated": True})

    def test_login_checks_its_leaf_help_before_running_json_login(self):
        help_command = ["dws", "auth", "login", "--help"]
        business_command = ["dws", "auth", "login", "--format", "json"]
        runner = FakeRunner("", responses={
            tuple(help_command): CommandResult("Usage: login --format json"),
            tuple(business_command): CommandResult('{"authenticated":true}'),
        })

        result = DwsProvider(runner).login()

        self.assertEqual(runner.calls, [help_command, business_command])
        self.assertEqual(result.status, "ok")

    def test_missing_json_flag_in_leaf_help_blocks_business_command(self):
        help_command = ["dws", "auth", "status", "--help"]
        runner = FakeRunner("", responses={
            tuple(help_command): CommandResult("Usage: status"),
        })

        result = DwsProvider(runner).auth_status()

        self.assertEqual(runner.calls, [help_command])
        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason, "dws_json_format_unsupported")

    def test_successful_leaf_help_confirmation_is_cached(self):
        help_command = ["dws", "auth", "status", "--help"]
        business_command = ["dws", "auth", "status", "--format", "json"]
        runner = FakeRunner("", responses={
            tuple(help_command): CommandResult("--format json"),
            tuple(business_command): CommandResult('{"authenticated":true}'),
        })
        provider = DwsProvider(runner)

        provider.auth_status()
        provider.auth_status()

        self.assertEqual(runner.calls, [help_command, business_command, business_command])

    def test_capability_discovery_never_attempts_login(self):
        runner = FakeRunner("DWS command line help")

        capabilities = DwsProvider(runner).capabilities()

        self.assertEqual(runner.calls, [["dws", "--help"]])
        self.assertTrue(capabilities["available"])

    def test_multiple_profiles_require_selection(self):
        result = choose_profile([{"profile": "a:u"}, {"profile": "b:u"}])

        self.assertEqual(result.status, "action_required")
        self.assertEqual(result.reason, "profile_selection_required")
        self.assertEqual(result.data["profiles"], [{"profile": "a:u"}, {"profile": "b:u"}])

    def test_explicit_stable_profile_is_selected_without_reformatting(self):
        result = choose_profile(
            [{"profile": "corp:user", "isCurrent": True}], "corp:user"
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.data["profile"], "corp:user")

    def test_recipient_resolution_requires_a_human_supplied_choice(self):
        result = DwsProvider(FakeRunner("{}")).resolve_recipient("corp:user", "ops")

        self.assertEqual(result.status, "action_required")
        self.assertEqual(result.reason, "recipient_selection_required")
        self.assertEqual(result.data["profile"], "corp:user")
        self.assertEqual(result.data["selector"], "ops")


if __name__ == "__main__":
    unittest.main()
