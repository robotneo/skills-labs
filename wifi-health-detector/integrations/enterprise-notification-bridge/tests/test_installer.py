from __future__ import absolute_import

import os
import stat
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.installer import (  # noqa: E402
    candidate_plans,
    execute_dws_install,
    plan_dws_install,
)


INSTALLER_BYTES = b"#!/bin/sh\nexit 0\n"


class CommandResult(object):
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class RecordingDownloader(object):
    def __init__(self, error=None, write_file=True, failing_hosts=None):
        self.error = error
        self.write_file = write_file
        self.failing_hosts = set(failing_hosts or ())
        self.calls = []
        self.directory_modes = []

    def download(self, url, destination):
        self.calls.append((url, destination))
        self.directory_modes.append(
            stat.S_IMODE(os.stat(os.path.dirname(destination)).st_mode)
        )
        if any(host in url for host in self.failing_hosts):
            raise RuntimeError("host unreachable")
        if self.error is not None:
            raise self.error
        if self.write_file:
            with open(destination, "wb") as stream:
                stream.write(INSTALLER_BYTES)
        return None


class RecordingRunner(object):
    def __init__(self, result=None, error=None, failing_commands=False):
        self.result = result or CommandResult()
        self.error = error
        self.failing_commands = failing_commands
        self.calls = []

    def run(self, command, shell=False, cwd=None, env=None):
        self.calls.append((command, shell, cwd, env))
        if self.error is not None:
            raise self.error
        if self.failing_commands:
            return CommandResult(returncode=7)
        return self.result


class DeceptivePlan(object):
    platform = "linux"
    source = "official-github"
    url = "https://evil.invalid/payload.sh"
    filename = "payload.sh"
    command = ("sh", "{installer}")
    environment = (("DWS_NO_SKILLS", "1"),)

    def __eq__(self, unused_other):
        return True


class RestrictiveRunner(RecordingRunner):
    def run(self, command, shell=False, cwd=None, env=None):
        result = super(RestrictiveRunner, self).run(
            command, shell=shell, cwd=cwd, env=env
        )
        os.chmod(cwd, 0)
        return result


class DwsInstallPlanningTests(unittest.TestCase):
    def test_macos_and_linux_default_to_gitee_with_github_fallback(self):
        for platform_name in ("darwin", "linux"):
            plans = candidate_plans(platform_name, china_mirror=False)

            self.assertEqual([item.source for item in plans],
                             ["official-gitee", "official-github"])
            first = plans[0]
            self.assertEqual(first.filename, "install.sh")
            self.assertEqual(first.command, ("sh", "{installer}"))
            self.assertTrue(first.url.startswith(
                "https://gitee.com/dingtalk-real-ai/"
                "dingtalk-workspace-cli/raw/main/scripts/"
            ))
            self.assertTrue(first.url.endswith("/scripts/install.sh"))
            self.assertNotIn("|", " ".join(first.command))
            self.assertEqual(first.environment, (
                ("DWS_GITEE_REPO",
                 "DingTalk-Real-AI/dingtalk-workspace-cli"),
                ("DWS_NO_SKILLS", "1"),
            ))
            self.assertEqual(plans[1].source, "official-github")
            self.assertTrue(plans[1].url.startswith(
                "https://raw.githubusercontent.com/"
                "DingTalk-Real-AI/dingtalk-workspace-cli/main/scripts/"
            ))

    def test_default_plan_is_the_fastest_official_source(self):
        plan = plan_dws_install("darwin")
        self.assertEqual(plan.source, "official-gitee")

    def test_windows_uses_powershell_file_without_expression_execution(self):
        plan = plan_dws_install("windows")

        self.assertEqual(plan.source, "official-gitee")
        self.assertEqual(plan.filename, "install.ps1")
        self.assertEqual(plan.command, (
            "powershell.exe", "-NoProfile", "-NonInteractive", "-File",
            "{installer}",
        ))
        self.assertNotIn("iex", " ".join(plan.command).lower())
        self.assertNotIn("invoke-expression", " ".join(plan.command).lower())
        self.assertTrue(plan.url.endswith("/scripts/install.ps1"))

    def test_china_mirror_is_gitee_only(self):
        for platform_name, filename in (
                ("darwin", "install.sh"),
                ("linux", "install.sh"),
                ("windows", "install.ps1")):
            plans = candidate_plans(platform_name, china_mirror=True)

            self.assertEqual(len(plans), 1)
            plan = plans[0]
            self.assertEqual(plan.source, "official-gitee")
            self.assertEqual(plan.filename, filename)
            self.assertTrue(plan.url.startswith(
                "https://gitee.com/dingtalk-real-ai/"
                "dingtalk-workspace-cli/raw/main/scripts/"
            ))
            self.assertEqual(plan.environment, (
                ("DWS_GITEE_REPO",
                 "DingTalk-Real-AI/dingtalk-workspace-cli"),
                ("DWS_NO_SKILLS", "1"),
            ))

    def test_unknown_platform_is_rejected_instead_of_guessing_installer(self):
        with self.assertRaises(ValueError):
            plan_dws_install("freebsd")


class DwsInstallExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp_root = tempfile.mkdtemp(prefix="dws-install-test-")

    def tearDown(self):
        for root, directories, unused_files in os.walk(
                self.temp_root, topdown=True):
            os.chmod(root, 0o700)
            for directory in directories:
                path = os.path.join(root, directory)
                if not os.path.islink(path):
                    os.chmod(path, 0o700)
        for root, directories, files in os.walk(self.temp_root, topdown=False):
            for filename in files:
                os.unlink(os.path.join(root, filename))
            for directory in directories:
                os.rmdir(os.path.join(root, directory))
        os.rmdir(self.temp_root)

    def _assert_temp_root_empty(self):
        self.assertEqual(os.listdir(self.temp_root), [])

    def test_installer_refuses_execution_without_explicit_approval(self):
        downloader = RecordingDownloader()
        runner = RecordingRunner()

        result = execute_dws_install(
            plan_dws_install("darwin"), False,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.status, "action_required")
        self.assertEqual(result.reason, "dependency_install_declined")
        self.assertEqual(downloader.calls, [])
        self.assertEqual(runner.calls, [])
        self._assert_temp_root_empty()

    def test_installer_requires_literal_boolean_true_approval(self):
        for approved in ("false", 1, None, [], {}):
            downloader = RecordingDownloader()
            runner = RecordingRunner()

            result = execute_dws_install(
                plan_dws_install("darwin"), approved,
                downloader, runner, self.temp_root,
            )

            self.assertEqual(result.status, "action_required")
            self.assertEqual(result.reason, "dependency_install_declined")
            self.assertEqual(downloader.calls, [])
            self.assertEqual(runner.calls, [])
            self._assert_temp_root_empty()

    def test_deceptive_equality_cannot_bypass_official_plan_allowlist(self):
        downloader = RecordingDownloader()
        runner = RecordingRunner()

        result = execute_dws_install(
            DeceptivePlan(), True, downloader, runner, self.temp_root,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "dependency_install_failed")
        self.assertEqual(downloader.calls, [])
        self.assertEqual(runner.calls, [])
        self._assert_temp_root_empty()

    def test_download_uses_private_directory_and_runner_uses_shell_false(self):
        downloader = RecordingDownloader()
        runner = RecordingRunner()
        previous = os.environ.get("DWS_GITEE_REPO")
        os.environ["DWS_GITEE_REPO"] = "untrusted/fork"
        try:
            result = execute_dws_install(
                plan_dws_install("linux"), True,
                downloader, runner, self.temp_root,
            )
        finally:
            if previous is None:
                os.environ.pop("DWS_GITEE_REPO", None)
            else:
                os.environ["DWS_GITEE_REPO"] = previous

        self.assertEqual(result.reason, "dependency_ready")
        self.assertEqual(downloader.directory_modes, [0o700])
        command, shell, cwd, env = runner.calls[0]
        self.assertEqual(command[0], "sh")
        self.assertTrue(os.path.isabs(command[1]))
        self.assertFalse(shell)
        self.assertEqual(os.path.dirname(command[1]), cwd)
        self.assertEqual(env["DWS_NO_SKILLS"], "1")
        self._assert_temp_root_empty()

    def test_windows_executes_downloaded_script_with_powershell_file(self):
        downloader = RecordingDownloader()
        runner = RecordingRunner()

        result = execute_dws_install(
            plan_dws_install("windows"), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.reason, "dependency_ready")
        command, shell, unused_cwd, env = runner.calls[0]
        self.assertEqual(command[:4], (
            "powershell.exe", "-NoProfile", "-NonInteractive", "-File",
        ))
        self.assertTrue(command[4].endswith("install.ps1"))
        self.assertFalse(shell)

    def test_fallback_to_github_when_gitee_download_fails(self):
        downloader = RecordingDownloader(failing_hosts=("gitee.com",))
        runner = RecordingRunner()

        result = execute_dws_install(
            plan_dws_install("linux"), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.status, "ready")
        self.assertEqual(result.source, "official-github")
        self.assertEqual(len(downloader.calls), 2)
        self.assertIn("gitee.com", downloader.calls[0][0])
        self.assertIn("githubusercontent.com", downloader.calls[1][0])
        self.assertEqual(len(runner.calls), 1)
        self._assert_temp_root_empty()

    def test_failure_when_both_official_sources_fail(self):
        downloader = RecordingDownloader(
            failing_hosts=("gitee.com", "githubusercontent.com")
        )
        runner = RecordingRunner()

        result = execute_dws_install(
            plan_dws_install("linux"), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "dependency_download_failed")
        self.assertEqual(len(downloader.calls), 2)
        self.assertEqual(runner.calls, [])
        self._assert_temp_root_empty()

    def test_download_exception_returns_stable_code(self):
        downloader = RecordingDownloader(error=RuntimeError("token=secret"))
        runner = RecordingRunner()

        result = execute_dws_install(
            plan_dws_install("linux"), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.reason, "dependency_download_failed")
        self.assertNotIn("secret", repr(result))
        self.assertEqual(runner.calls, [])
        self._assert_temp_root_empty()

    def test_missing_downloaded_file_is_a_download_failure(self):
        downloader = RecordingDownloader(write_file=False)
        runner = RecordingRunner()

        result = execute_dws_install(
            plan_dws_install("linux"), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.reason, "dependency_download_failed")
        self.assertEqual(runner.calls, [])
        self._assert_temp_root_empty()

    def test_nonzero_installer_exit_returns_stable_code(self):
        downloader = RecordingDownloader()
        runner = RecordingRunner(failing_commands=True)

        result = execute_dws_install(
            plan_dws_install("linux"), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.reason, "dependency_install_failed")
        self._assert_temp_root_empty()

    def test_cleanup_restores_permissions_before_removing_installer(self):
        downloader = RecordingDownloader()
        runner = RestrictiveRunner()

        result = execute_dws_install(
            plan_dws_install("linux"), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.reason, "dependency_ready")
        self._assert_temp_root_empty()

    def test_private_directory_creation_failure_returns_stable_install_code(self):
        missing_root = os.path.join(self.temp_root, "missing", "root")
        downloader = RecordingDownloader()
        runner = RecordingRunner()

        result = execute_dws_install(
            plan_dws_install("linux"), True,
            downloader, runner, missing_root,
        )

        self.assertEqual(result.reason, "dependency_install_failed")
        self.assertEqual(downloader.calls, [])
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
