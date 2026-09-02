from __future__ import absolute_import

import hashlib
import os
import re
import shutil
import tempfile
from collections import namedtuple


_GITHUB_ROOT = (
    "https://raw.githubusercontent.com/"
    "DingTalk-Real-AI/dingtalk-workspace-cli/main/scripts/"
)
_GITEE_ROOT = (
    "https://gitee.com/dingtalk-real-ai/"
    "dingtalk-workspace-cli/raw/main/scripts/"
)
_INSTALLER_TOKEN = "{installer}"
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class DwsInstallPlan(namedtuple(
        "DwsInstallPlanBase",
        "platform source url filename command environment")):
    """Immutable, public-only plan for an approved official installer."""

    __slots__ = ()


class DownloadReceipt(namedtuple(
        "DownloadReceiptBase", "expected_sha256")):
    """Optional integrity metadata published for a downloaded installer."""

    __slots__ = ()


class DwsInstallResult(namedtuple(
        "DwsInstallResultBase", "status reason source")):
    """Stable installer outcome that never includes subprocess output."""

    __slots__ = ()


def plan_dws_install(platform_name, china_mirror=False):
    """Return a fixed official install plan without downloading anything."""
    platform_key = _platform_key(platform_name)
    source = "official-gitee" if china_mirror else "official-github"
    root = _GITEE_ROOT if china_mirror else _GITHUB_ROOT
    if china_mirror:
        environment = (
            ("DWS_GITEE_REPO", "DingTalk-Real-AI/dingtalk-workspace-cli"),
            ("DWS_NO_FALLBACK", "1"),
        )
    else:
        environment = (("DWS_NO_FALLBACK", "1"),)

    if platform_key == "windows":
        filename = "install.ps1"
        command = (
            "powershell.exe", "-NoProfile", "-NonInteractive", "-File",
            _INSTALLER_TOKEN,
        )
    else:
        filename = "install.sh"
        command = ("sh", _INSTALLER_TOKEN)

    return DwsInstallPlan(
        platform_key, source, root + filename, filename, command, environment
    )


def execute_dws_install(
        plan, approved, downloader, process_runner, temp_root=None):
    """Download and locally execute one fixed plan after explicit approval."""
    source = _public_source(plan)
    if approved is not True:
        return DwsInstallResult(
            "action_required", "dependency_install_declined", source
        )

    if not _is_official_plan(plan):
        return DwsInstallResult(
            "failed", "dependency_install_failed", source
        )

    private_dir = None
    try:
        try:
            private_dir = tempfile.mkdtemp(
                prefix="dws-install-", dir=temp_root
            )
            os.chmod(private_dir, 0o700)
        except Exception:
            return DwsInstallResult(
                "failed", "dependency_install_failed", plan.source
            )
        installer_path = os.path.join(private_dir, plan.filename)

        try:
            receipt = _download(downloader, plan.url, installer_path)
        except Exception:
            return DwsInstallResult(
                "failed", "dependency_download_failed", plan.source
            )

        if (not os.path.isfile(installer_path) or
                os.path.islink(installer_path)):
            return DwsInstallResult(
                "failed", "dependency_download_failed", plan.source
            )

        try:
            expected_sha256 = getattr(receipt, "expected_sha256", None)
        except Exception:
            return DwsInstallResult(
                "failed", "dependency_integrity_failed", plan.source
            )
        if expected_sha256 is not None:
            try:
                checksum_matches = (
                    isinstance(expected_sha256, str) and
                    _SHA256.fullmatch(expected_sha256) is not None and
                    _file_sha256(installer_path) == expected_sha256.lower()
                )
            except Exception:
                checksum_matches = False
            if not checksum_matches:
                return DwsInstallResult(
                    "failed", "dependency_integrity_failed", plan.source
                )

        command = tuple(
            installer_path if item == _INSTALLER_TOKEN else item
            for item in plan.command
        )
        try:
            process_result = _run(
                process_runner, command, cwd=private_dir,
                environment=plan.environment,
            )
        except Exception:
            return DwsInstallResult(
                "failed", "dependency_install_failed", plan.source
            )
        try:
            returncode = getattr(process_result, "returncode", None)
        except Exception:
            return DwsInstallResult(
                "failed", "dependency_install_failed", plan.source
            )
        if type(returncode) is not int or returncode != 0:
            return DwsInstallResult(
                "failed", "dependency_install_failed", plan.source
            )
        return DwsInstallResult("ready", "dependency_ready", plan.source)
    finally:
        if private_dir is not None and not _remove_private_dir(private_dir):
            return DwsInstallResult(
                "failed", "dependency_cleanup_failed", plan.source
            )


def _platform_key(platform_name):
    value = (platform_name or "").strip().lower()
    aliases = {
        "darwin": "darwin",
        "mac": "darwin",
        "macos": "darwin",
        "linux": "linux",
        "win32": "windows",
        "windows": "windows",
    }
    if value not in aliases:
        raise ValueError("unsupported DWS installer platform")
    return aliases[value]


def _is_official_plan(plan):
    if type(plan) is not DwsInstallPlan:
        return False
    if type(plan.platform) is not str:
        return False
    try:
        github_plan = plan_dws_install(plan.platform, False)
        gitee_plan = plan_dws_install(plan.platform, True)
    except (TypeError, ValueError):
        return False
    return (_plan_fields_match(plan, github_plan) or
            _plan_fields_match(plan, gitee_plan))


def _plan_fields_match(candidate, expected):
    scalar_fields = ("platform", "source", "url", "filename")
    for field in scalar_fields:
        candidate_value = getattr(candidate, field)
        expected_value = getattr(expected, field)
        if (type(candidate_value) is not str or
                not str.__eq__(candidate_value, expected_value)):
            return False
    return (_trusted_string_tuple_matches(candidate.command, expected.command)
            and _trusted_environment_matches(
                candidate.environment, expected.environment
            ))


def _trusted_string_tuple_matches(candidate, expected):
    if type(candidate) is not tuple or len(candidate) != len(expected):
        return False
    for candidate_value, expected_value in zip(candidate, expected):
        if (type(candidate_value) is not str or
                not str.__eq__(candidate_value, expected_value)):
            return False
    return True


def _trusted_environment_matches(candidate, expected):
    if type(candidate) is not tuple or len(candidate) != len(expected):
        return False
    for candidate_pair, expected_pair in zip(candidate, expected):
        if (type(candidate_pair) is not tuple or
                not _trusted_string_tuple_matches(
                    candidate_pair, expected_pair
                )):
            return False
    return True


def _public_source(plan):
    if type(plan) is DwsInstallPlan and type(plan.source) is str:
        if plan.source in ("official-github", "official-gitee"):
            return plan.source
    return None


def _remove_private_dir(private_dir):
    for unused_attempt in range(2):
        try:
            if os.path.isdir(private_dir) and not os.path.islink(private_dir):
                os.chmod(private_dir, 0o700)
                for root, directories, unused_files in os.walk(private_dir):
                    os.chmod(root, 0o700)
                    for directory in directories:
                        path = os.path.join(root, directory)
                        if not os.path.islink(path):
                            os.chmod(path, 0o700)
            shutil.rmtree(private_dir)
            return True
        except Exception:
            continue
    return not os.path.lexists(private_dir)


def _download(downloader, url, destination):
    method = getattr(downloader, "download", None)
    if method is not None:
        return method(url, destination)
    return downloader(url, destination)


def _run(process_runner, command, cwd, environment):
    process_environment = os.environ.copy()
    process_environment.pop("DWS_GITEE_REPO", None)
    process_environment.pop("DWS_GITEE_FALLBACK_REPO", None)
    process_environment.update(dict(environment))
    method = getattr(process_runner, "run", None)
    if method is not None:
        return method(
            command, shell=False, cwd=cwd, env=process_environment
        )
    return process_runner(
        command, shell=False, cwd=cwd, env=process_environment
    )


def _file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            block = stream.read(65536)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()
