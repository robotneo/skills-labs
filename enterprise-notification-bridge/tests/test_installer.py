from __future__ import absolute_import

import hashlib
import os
import stat
import sys
import tempfile
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.installer import (  # noqa: E402
    DownloadReceipt,
    DwsInstallPlan,
    execute_dws_install,
    plan_dws_install,
)


INSTALLER_BYTES = b"#!/bin/sh\nexit 0\n"


class CommandResult(object):
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class ExplodingReceipt(object):
    @property
    def expected_sha256(self):
        raise RuntimeError("receipt-token=top-secret")


class ExplodingCommandResult(object):
    @property
    def returncode(self):
        raise RuntimeError("process-cookie=top-secret")


class DeceptiveReturnCode(object):
    def __ne__(self, unused_other):
        raise RuntimeError("returncode-secret=top-secret")


class RecordingDownloader(object):
    def __init__(self, receipt=None, error=None, write_file=True):
        self.receipt = receipt or DownloadReceipt(None)
        self.error = error
        self.write_file = write_file
        self.calls = []
        self.directory_modes = []

    def download(self, url, destination):
        self.calls.append((url, destination))
        self.directory_modes.append(
            stat.S_IMODE(os.stat(os.path.dirname(destination)).st_mode)
        )
        if self.error is not None:
            raise self.error
        if self.write_file:
            with open(destination, "wb") as stream:
                stream.write(INSTALLER_BYTES)
        return self.receipt


class RecordingRunner(object):
    def __init__(self, result=None, error=None):
        self.result = result or CommandResult()
        self.error = error
        self.calls = []

    def run(self, command, shell=False, cwd=None, env=None):
        self.calls.append((command, shell, cwd, env))
        if self.error is not None:
            raise self.error
        return self.result


class SymlinkDownloader(object):
    def __init__(self, target):
        self.target = target

    def download(self, unused_url, destination):
        os.symlink(self.target, destination)
        return DownloadReceipt(None)


class DeceptivePlan(object):
    platform = "linux"
    source = "official-github"
    url = "https://evil.invalid/payload.sh"
    filename = "payload.sh"
    command = ("sh", "{installer}")
    environment = (("DWS_NO_FALLBACK", "1"),)

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
    def test_macos_and_linux_use_downloaded_local_shell_script(self):
        for platform_name in ("darwin", "linux"):
            plan = plan_dws_install(platform_name, china_mirror=False)

            self.assertEqual(plan.source, "official-github")
            self.assertEqual(plan.filename, "install.sh")
            self.assertEqual(plan.command, ("sh", "{installer}"))
            self.assertTrue(plan.url.startswith(
                "https://raw.githubusercontent.com/"
                "DingTalk-Real-AI/dingtalk-workspace-cli/"
            ))
            self.assertTrue(plan.url.endswith("/main/scripts/install.sh"))
            self.assertNotIn("|", " ".join(plan.command))
            self.assertEqual(plan.environment, (("DWS_NO_FALLBACK", "1"),))

    def test_windows_uses_powershell_file_without_expression_execution(self):
        plan = plan_dws_install("windows", china_mirror=False)

        self.assertEqual(plan.source, "official-github")
        self.assertEqual(plan.filename, "install.ps1")
        self.assertEqual(plan.command, (
            "powershell.exe", "-NoProfile", "-NonInteractive", "-File",
            "{installer}",
        ))
        self.assertNotIn("iex", " ".join(plan.command).lower())
        self.assertNotIn("invoke-expression", " ".join(plan.command).lower())
        self.assertTrue(plan.url.endswith("/main/scripts/install.ps1"))
        self.assertEqual(plan.environment, (("DWS_NO_FALLBACK", "1"),))

    def test_china_mirror_is_an_explicit_gitee_plan_for_each_platform(self):
        for platform_name, filename in (
                ("darwin", "install.sh"),
                ("linux", "install.sh"),
                ("windows", "install.ps1")):
            plan = plan_dws_install(platform_name, china_mirror=True)

            self.assertEqual(plan.source, "official-gitee")
            self.assertEqual(plan.filename, filename)
            self.assertTrue(plan.url.startswith(
                "https://gitee.com/dingtalk-real-ai/"
                "dingtalk-workspace-cli/raw/"
            ))
            self.assertTrue(plan.url.endswith("/main/scripts/" + filename))
            self.assertEqual(plan.environment, (
                ("DWS_GITEE_REPO",
                 "DingTalk-Real-AI/dingtalk-workspace-cli"),
                ("DWS_NO_FALLBACK", "1"),
            ))

    def test_unknown_platform_is_rejected_instead_of_guessing_installer(self):
        with self.assertRaises(ValueError):
            plan_dws_install("freebsd", china_mirror=False)


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
            plan_dws_install("darwin", False), False,
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
                plan_dws_install("darwin", False), approved,
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

    def test_malformed_exact_type_plans_return_stable_install_failure(self):
        canonical = plan_dws_install("linux", False)
        malformed_plans = (
            DwsInstallPlan(
                1, canonical.source, canonical.url, canonical.filename,
                canonical.command, canonical.environment,
            ),
            canonical._replace(source=1),
            canonical._replace(url=1),
            canonical._replace(filename=1),
            canonical._replace(command=["sh", "{installer}"]),
            canonical._replace(environment=(("DWS_NO_FALLBACK", 1),)),
        )

        for plan in malformed_plans:
            downloader = RecordingDownloader()
            runner = RecordingRunner()

            result = execute_dws_install(
                plan, True, downloader, runner, self.temp_root,
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.reason, "dependency_install_failed")
            self.assertNotIn("AttributeError", repr(result))
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
                plan_dws_install("linux", False), True,
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
        self.assertEqual(env["DWS_NO_FALLBACK"], "1")
        self.assertNotIn("DWS_GITEE_REPO", env)
        self._assert_temp_root_empty()

    def test_windows_executes_downloaded_script_with_powershell_file(self):
        downloader = RecordingDownloader()
        runner = RecordingRunner()

        result = execute_dws_install(
            plan_dws_install("windows", False), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.reason, "dependency_ready")
        command, shell, unused_cwd, env = runner.calls[0]
        self.assertEqual(command[:4], (
            "powershell.exe", "-NoProfile", "-NonInteractive", "-File",
        ))
        self.assertTrue(command[4].endswith("install.ps1"))
        self.assertFalse(shell)
        self.assertEqual(env["DWS_NO_FALLBACK"], "1")
        self._assert_temp_root_empty()

    def test_download_exception_returns_stable_code_and_cleans_up(self):
        downloader = RecordingDownloader(error=RuntimeError("token=secret"))
        runner = RecordingRunner()

        result = execute_dws_install(
            plan_dws_install("linux", False), True,
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
            plan_dws_install("linux", False), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.reason, "dependency_download_failed")
        self.assertEqual(runner.calls, [])
        self._assert_temp_root_empty()

    def test_downloaded_installer_must_not_be_a_symbolic_link(self):
        outside_path = os.path.join(self.temp_root, "outside-installer.sh")
        with open(outside_path, "wb") as stream:
            stream.write(INSTALLER_BYTES)
        runner = RecordingRunner()

        result = execute_dws_install(
            plan_dws_install("linux", False), True,
            SymlinkDownloader(outside_path), runner, self.temp_root,
        )

        self.assertEqual(result.reason, "dependency_download_failed")
        self.assertEqual(runner.calls, [])
        self.assertEqual(os.listdir(self.temp_root), ["outside-installer.sh"])

    def test_published_checksum_mismatch_blocks_execution(self):
        expected = hashlib.sha256(b"different installer").hexdigest()
        downloader = RecordingDownloader(DownloadReceipt(expected))
        runner = RecordingRunner()

        result = execute_dws_install(
            plan_dws_install("darwin", False), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.reason, "dependency_integrity_failed")
        self.assertEqual(runner.calls, [])
        self._assert_temp_root_empty()

    def test_matching_published_checksum_allows_execution(self):
        expected = hashlib.sha256(INSTALLER_BYTES).hexdigest()
        downloader = RecordingDownloader(DownloadReceipt(expected))
        runner = RecordingRunner()

        result = execute_dws_install(
            plan_dws_install("darwin", False), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.reason, "dependency_ready")
        self.assertEqual(len(runner.calls), 1)
        self._assert_temp_root_empty()

    def test_invalid_checksum_metadata_fails_closed(self):
        downloader = RecordingDownloader(DownloadReceipt("not-a-sha256"))
        runner = RecordingRunner()

        result = execute_dws_install(
            plan_dws_install("darwin", False), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.reason, "dependency_integrity_failed")
        self.assertEqual(runner.calls, [])
        self._assert_temp_root_empty()

    def test_checksum_read_error_returns_integrity_failure_and_cleans_up(self):
        expected = hashlib.sha256(INSTALLER_BYTES).hexdigest()
        downloader = RecordingDownloader(DownloadReceipt(expected))
        runner = RecordingRunner()

        with mock.patch(
                "notification_bridge.installer._file_sha256",
                side_effect=OSError("secret checksum path")):
            result = execute_dws_install(
                plan_dws_install("darwin", False), True,
                downloader, runner, self.temp_root,
            )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "dependency_integrity_failed")
        self.assertNotIn("secret", repr(result))
        self.assertEqual(runner.calls, [])
        self._assert_temp_root_empty()

    def test_receipt_getter_error_returns_integrity_failure_and_cleans_up(self):
        downloader = RecordingDownloader(ExplodingReceipt())
        runner = RecordingRunner()

        result = execute_dws_install(
            plan_dws_install("darwin", False), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "dependency_integrity_failed")
        self.assertNotIn("top-secret", repr(result))
        self.assertEqual(runner.calls, [])
        self._assert_temp_root_empty()

    def test_nonzero_installer_exit_returns_stable_code_without_stderr(self):
        downloader = RecordingDownloader()
        runner = RecordingRunner(CommandResult(
            returncode=7, stderr="cookie=top-secret",
        ))

        result = execute_dws_install(
            plan_dws_install("linux", False), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.reason, "dependency_install_failed")
        self.assertNotIn("top-secret", repr(result))
        self._assert_temp_root_empty()

    def test_returncode_getter_error_returns_install_failure_and_cleans_up(self):
        downloader = RecordingDownloader()
        runner = RecordingRunner(ExplodingCommandResult())

        result = execute_dws_install(
            plan_dws_install("linux", False), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "dependency_install_failed")
        self.assertNotIn("top-secret", repr(result))
        self._assert_temp_root_empty()

    def test_untrusted_returncode_value_is_not_compared(self):
        downloader = RecordingDownloader()
        runner = RecordingRunner(CommandResult(DeceptiveReturnCode()))

        result = execute_dws_install(
            plan_dws_install("linux", False), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "dependency_install_failed")
        self.assertNotIn("top-secret", repr(result))
        self._assert_temp_root_empty()

    def test_runner_exception_returns_install_failure_and_cleans_up(self):
        downloader = RecordingDownloader()
        runner = RecordingRunner(error=RuntimeError("profile=private"))

        result = execute_dws_install(
            plan_dws_install("linux", False), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.reason, "dependency_install_failed")
        self.assertNotIn("private", repr(result))
        self._assert_temp_root_empty()

    def test_cleanup_restores_permissions_before_removing_installer(self):
        downloader = RecordingDownloader()
        runner = RestrictiveRunner()

        result = execute_dws_install(
            plan_dws_install("linux", False), True,
            downloader, runner, self.temp_root,
        )

        self.assertEqual(result.reason, "dependency_ready")
        self._assert_temp_root_empty()

    def test_cleanup_failure_overrides_success_with_stable_failure(self):
        downloader = RecordingDownloader()
        runner = RecordingRunner()

        with mock.patch(
                "notification_bridge.installer.shutil.rmtree",
                side_effect=OSError("secret cleanup path")) as cleanup:
            result = execute_dws_install(
                plan_dws_install("linux", False), True,
                downloader, runner, self.temp_root,
            )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "dependency_cleanup_failed")
        self.assertNotIn("secret", repr(result))
        self.assertEqual(cleanup.call_count, 2)

    def test_private_directory_creation_failure_returns_stable_install_code(self):
        missing_root = os.path.join(self.temp_root, "missing", "root")
        downloader = RecordingDownloader()
        runner = RecordingRunner()

        result = execute_dws_install(
            plan_dws_install("linux", False), True,
            downloader, runner, missing_root,
        )

        self.assertEqual(result.reason, "dependency_install_failed")
        self.assertEqual(downloader.calls, [])
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
