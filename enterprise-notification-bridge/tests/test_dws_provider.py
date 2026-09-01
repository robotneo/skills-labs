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
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode
        self.calls = []

    def run(self, command):
        self.calls.append(command)
        return CommandResult(self.stdout, self.returncode)


class DwsProviderTests(unittest.TestCase):
    def test_dws_profile_list_uses_json_and_stable_profile(self):
        runner = FakeRunner('{"profiles":[{"profile":"corp:user","isCurrent":true}]}')
        result = DwsProvider(runner).list_profiles()

        self.assertEqual(runner.calls[0], ["dws", "profile", "list", "--format", "json"])
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.data[0]["profile"], "corp:user")

    def test_auth_status_uses_the_documented_json_command(self):
        runner = FakeRunner('{"authenticated":true}')

        result = DwsProvider(runner).auth_status("corp:user")

        self.assertEqual(runner.calls, [["dws", "auth", "status", "--format", "json"]])
        self.assertEqual(result.data, {"authenticated": True})

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
