from __future__ import absolute_import

import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.providers.dws import (
    DwsProvider,
    choose_profile,
    clean_recipient_name,
)


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
    def test_verified_executable_is_used_and_leaf_help_gate_is_preserved(self):
        executable = "/verified/bin/dws"
        help_command = [executable, "auth", "status", "--help"]
        business_command = [
            executable, "auth", "status", "--format", "json"
        ]
        runner = FakeRunner("", responses={
            tuple(help_command): CommandResult("--format json"),
            tuple(business_command): CommandResult('{"authenticated":true}'),
        })
        result = DwsProvider(runner, executable=executable).auth_status()
        self.assertEqual(result.status, "ok")
        self.assertEqual(runner.calls, [help_command, business_command])

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

    def test_device_login_uses_documented_device_flag(self):
        help_command = ["dws", "auth", "login", "--help"]
        business_command = [
            "dws", "auth", "login", "--device", "--format", "json"
        ]
        runner = FakeRunner("", responses={
            tuple(help_command): CommandResult("Usage: login --device --format json"),
            tuple(business_command): CommandResult('{"authenticated":true}'),
        })

        result = DwsProvider(runner).login(device_login=True)

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

    def test_failed_dws_command_never_exposes_opaque_stderr(self):
        help_command = ["dws", "auth", "status", "--help"]
        business_command = ["dws", "auth", "status", "--format", "json"]
        runner = FakeRunner("", responses={
            tuple(help_command): CommandResult("--format json"),
            tuple(business_command): CommandResult(
                "", returncode=9, stderr="token=opaque-secret traceback"
            ),
        })

        result = DwsProvider(runner).auth_status()

        self.assertEqual(result.reason, "dws_command_failed")
        self.assertNotIn("stderr", result.data)
        self.assertNotIn("opaque-secret", repr(result.data))

    def test_undocumented_dws_send_requests_correlated_host_continuation(self):
        result = DwsProvider(FakeRunner("{}")).host_send_report(
            "corp:user", "ops", {"report_id": "report"}
        )

        self.assertEqual(result.status, "action_required")
        self.assertEqual(result.reason, "host_send_required")
        self.assertEqual(result.data["operation"], "send_report")
        self.assertEqual(result.data["profile"], "corp:user")
        self.assertEqual(result.data["recipient"], "ops")

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

    def test_primed_leaf_help_skips_the_cold_start_probe(self):
        # Dependency verification already probed this leaf serially (which
        # warms a cold DWS MCP discovery cache). Priming the provider must make
        # the first business call skip its own leaf --help, so a single send no
        # longer relaunches the same expensive probe and contends on the lock.
        executable = "/verified/bin/dws"
        business_command = [
            executable, "auth", "status", "--format", "json"
        ]
        runner = FakeRunner("", responses={
            tuple(business_command): CommandResult('{"authenticated":true}'),
        })
        provider = DwsProvider(runner, executable=executable)
        provider.prime_json_help([("auth", "status")])

        result = provider.auth_status()

        self.assertEqual(result.status, "ok")
        self.assertEqual(runner.calls, [business_command])

    def test_primed_help_is_keyed_to_the_current_executable(self):
        # Retargeting the provider after priming (a freshly installed path)
        # must not reuse stale confirmations keyed to a different executable.
        runner = FakeRunner("", responses={
            ("dws", "profile", "list", "--help"): CommandResult("--format json"),
            ("dws", "profile", "list", "--format", "json"): CommandResult(
                '{"profiles":[{"profile":"corp:user"}]}'
            ),
        })
        provider = DwsProvider(runner, executable="/old/dws")
        provider.prime_json_help([("profile", "list")])
        provider.executable = "dws"

        result = provider.list_profiles()

        self.assertEqual(result.status, "ok")
        self.assertEqual(runner.calls, [
            ["dws", "profile", "list", "--help"],
            ["dws", "profile", "list", "--format", "json"],
        ])

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
        result = DwsProvider(FakeRunner("{}")).host_resolve_recipient(
            "corp:user", "ops"
        )

        self.assertEqual(result.status, "action_required")
        self.assertEqual(result.reason, "recipient_selection_required")
        self.assertEqual(result.data["operation"], "resolve_recipient")
        self.assertEqual(result.data["profile"], "corp:user")
        self.assertEqual(result.data["selector"], "ops")

    # --- Real default auto path: contact +lookup resolution ---

    @staticmethod
    def _lookup_commands(name, executable="dws"):
        help_command = [
            executable, "contact", "+lookup", "--name", name, "--help"
        ]
        business_command = [
            executable, "contact", "+lookup", "--name", name,
            "--format", "json",
        ]
        return help_command, business_command

    def test_resolve_recipient_unique_lookup_returns_resolved_name(self):
        help_command, business_command = self._lookup_commands("杨华")
        runner = FakeRunner("", responses={
            tuple(help_command): CommandResult("--format json"),
            tuple(business_command): CommandResult(
                '{"ok":true,"outcome":"success","data":{"profile":{'
                '"orgUserId":"201454","orgUserName":"杨华"}}}'
            ),
        })

        result = DwsProvider(runner).resolve_recipient("corp:user", " 杨华 ")

        self.assertEqual(result.status, "resolved")
        self.assertEqual(result.data["recipient"], "杨华")
        self.assertEqual(result.data["selector"], "杨华")
        self.assertEqual(runner.calls, [help_command, business_command])

    def test_resolve_recipient_not_found_is_classified(self):
        help_command, business_command = self._lookup_commands("钱七")
        runner = FakeRunner("", responses={
            tuple(help_command): CommandResult("--format json"),
            tuple(business_command): CommandResult(
                '{"ok":false,"error":{"subtype":"not_found"}}'
            ),
        })

        result = DwsProvider(runner).resolve_recipient("corp:user", "钱七")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "recipient_not_found")
        self.assertFalse(result.retryable)

    def test_resolve_recipient_ambiguous_match_is_classified(self):
        help_command, business_command = self._lookup_commands("李娜")
        runner = FakeRunner("", responses={
            tuple(help_command): CommandResult("--format json"),
            tuple(business_command): CommandResult(
                '{"ok":false,"error":{"subtype":"ambiguous_match"}}'
            ),
        })

        result = DwsProvider(runner).resolve_recipient("corp:user", "李娜")

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "recipient_ambiguous")
        self.assertFalse(result.retryable)

    def test_resolve_recipient_rejects_identifier_selector_without_lookup(self):
        runner = FakeRunner("{}")

        result = DwsProvider(runner).resolve_recipient(
            "corp:user", "dingc96cdb4c99a85452:2014540426841958"
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "recipient_not_resolved")
        self.assertEqual(runner.calls, [])

    # --- Real default auto path: chat +dm send ---

    @staticmethod
    def _dm_command(name, content, dry_run=False, executable="dws"):
        command = [
            executable, "chat", "+dm", "--to", name,
            "--content", content, "--format", "json",
        ]
        command.append("--dry-run" if dry_run else "--yes")
        return command

    def test_send_report_executes_real_dm_with_yes_flag(self):
        envelope = {"report": {"markdown": "# WiFi 报告"}}
        command = self._dm_command("杨华", "# WiFi 报告", dry_run=False)
        runner = FakeRunner("", responses={
            tuple(command): CommandResult(
                '{"ok":true,"executed":true,"data":{"messageId":"m-1"}}'
            ),
        })

        result = DwsProvider(runner).send_report(
            "corp:user", "杨华", envelope, dry_run=False
        )

        self.assertEqual(result.status, "sent")
        self.assertEqual(result.data["external_id"], "m-1")
        self.assertEqual(runner.calls, [command])

    def test_send_report_dry_run_previews_without_delivering(self):
        envelope = {"report": {"markdown": "# WiFi 报告"}}
        command = self._dm_command("杨华", "# WiFi 报告", dry_run=True)
        runner = FakeRunner("", responses={
            tuple(command): CommandResult(
                '{"dry_run":true,"executed":false,'
                '"tool":"send_personal_message",'
                '"arguments":{"receiverOpenDingTalkId":"DfoZ"}}'
            ),
        })

        result = DwsProvider(runner).send_report(
            "corp:user", "杨华", envelope, dry_run=True
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.reason, "dry_run")
        self.assertTrue(result.data["dry_run"])

    def test_send_report_dry_run_ambiguity_is_classified_even_on_rc_zero(self):
        envelope = {"report": {"markdown": "# WiFi 报告"}}
        command = self._dm_command("李娜", "# WiFi 报告", dry_run=True)
        runner = FakeRunner("", responses={
            tuple(command): CommandResult(
                '{"error":{"reason":"resolution_ambiguous",'
                '"details":{"subtype":"ambiguous","candidates":['
                '{"name":"李娜 A"},{"name":"李娜 B"}]}}}',
                returncode=0,
            ),
        })

        result = DwsProvider(runner).send_report(
            "corp:user", "李娜", envelope, dry_run=True
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "recipient_ambiguous")
        self.assertFalse(result.retryable)

    def test_send_report_rejects_id_like_recipient_without_running_command(self):
        runner = FakeRunner("{}")

        result = DwsProvider(runner).send_report(
            "corp:user", "DfoZCRADiS6Pl43m8iiNbBE2pwJQHNUsBsN",
            {"report": {"markdown": "# x"}},
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "recipient_not_resolved")
        self.assertEqual(runner.calls, [])

    def test_send_report_rejects_empty_and_oversized_content(self):
        runner = FakeRunner("{}")

        empty = DwsProvider(runner).send_report(
            "corp:user", "杨华", {"report": {"markdown": ""}}
        )
        oversized = DwsProvider(runner).send_report(
            "corp:user", "杨华",
            {"report": {"markdown": "x" * 12001}},
        )

        self.assertEqual((empty.status, empty.reason),
                         ("failed", "provider_send_failed"))
        self.assertEqual((oversized.status, oversized.reason),
                         ("failed", "provider_send_failed"))
        self.assertEqual(runner.calls, [])

    def test_clean_recipient_name_accepts_plain_display_names(self):
        self.assertEqual(clean_recipient_name("  杨华 "), "杨华")
        self.assertEqual(clean_recipient_name("Li Na"), "Li Na")
        for invalid in ("", "   ", "a:b", "line\nbreak",
                        "DfoZCRADiS6Pl43m8iiNbBE2pwJQHNUsBsN", None):
            self.assertEqual(clean_recipient_name(invalid), "")

    # --- Standalone HTML attachment path: chat +messages-send file ---

    def _html_envelope(self, html_text="<!doctype html><html><body>报告</body></html>"):
        return {"report": {"markdown": "# WiFi 报告", "html": html_text}}

    def test_send_html_report_uploads_file_from_private_outbox(self):
        runner = FileSendRunner(
            '{"ok":true,"executed":true,"data":{"messageId":"m-9"}}'
        )
        result = DwsProvider(runner).send_report(
            "corp:user", "杨华", self._html_envelope("<html>精排报告</html>"),
            dry_run=False,
        )

        self.assertEqual(result.status, "sent")
        self.assertEqual(result.data["external_id"], "m-9")
        command, cwd = runner.calls[-1]
        # Identity-independent command vector; the file is a basename relative
        # to the private outbox so it cannot traverse outside cwd.
        self.assertEqual(
            command,
            ["dws", "chat", "+messages-send", "--as", "user",
             "--user-query", "杨华", "--msg-type", "file",
             "--file", "wifi-report-health.html", "--format", "json", "--yes"],
        )
        self.assertTrue(os.path.basename(cwd).startswith("dws-outbox-"))
        # The runner saw the attachment materialized with exact content and the
        # outbox is removed immediately after the send.
        self.assertTrue(runner.last_file_existed)
        self.assertIn("精排报告", runner.last_file_content)
        self.assertFalse(os.path.exists(cwd))

    def test_send_html_report_dry_run_uses_preview_flag_and_cleans_outbox(self):
        runner = FileSendRunner('{"dry_run":true,"executed":false}')
        result = DwsProvider(runner).send_report(
            "corp:user", "杨华", self._html_envelope(), dry_run=True
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.reason, "dry_run")
        command, cwd = runner.calls[-1]
        self.assertIn("--dry-run", command)
        self.assertNotIn("--yes", command)
        self.assertFalse(os.path.exists(cwd))

    def test_send_html_report_rejects_oversized_attachment_without_running(self):
        runner = FileSendRunner("{}")
        from notification_bridge.providers.dws import _MAX_HTML_CHARS
        result = DwsProvider(runner).send_report(
            "corp:user", "杨华", self._html_envelope("x" * (_MAX_HTML_CHARS + 1))
        )
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "provider_send_failed")
        self.assertEqual(runner.calls, [])

    def test_envelope_without_html_still_uses_legacy_markdown_dm(self):
        runner = FileSendRunner("{}")
        DwsProvider(runner).send_report(
            "corp:user", "杨华", {"report": {"markdown": "# WiFi 报告"}}
        )
        command, cwd = runner.calls[-1]
        self.assertIn("+dm", command)
        self.assertNotIn("+messages-send", command)
        self.assertIsNone(cwd)


class FileSendRunner(object):
    """Records (command, cwd) and inspects the attachment while it exists."""

    def __init__(self, stdout):
        self.stdout = stdout
        self.calls = []
        self.last_file_existed = False
        self.last_file_content = ""

    def run(self, command, cwd=None):
        self.calls.append((list(command), cwd))
        if "--file" in command:
            name = command[command.index("--file") + 1]
            path = os.path.join(cwd, name)
            self.last_file_existed = os.path.exists(path)
            with open(path, "r", encoding="utf-8") as handle:
                self.last_file_content = handle.read()

        class _Result(object):
            returncode = 0
            stderr = ""
            def __init__(self, text):
                self.stdout = text
        return _Result(self.stdout)


if __name__ == "__main__":
    unittest.main()
