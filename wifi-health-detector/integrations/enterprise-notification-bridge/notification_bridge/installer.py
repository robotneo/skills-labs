from __future__ import absolute_import

import os
import shutil
import tempfile
from collections import namedtuple


# Official installers always resolve the newest stable release; the upstream
# installer verifies each release binary against its published checksum, so we
# intentionally do not pin a mutable installer-script digest here.
_MAIN_REF = "main"

# Mainland China first (fast, official), then the official GitHub source.
_GITEE_ROOT = (
    "https://gitee.com/dingtalk-real-ai/"
    "dingtalk-workspace-cli/raw/" + _MAIN_REF + "/scripts/"
)
_GITHUB_ROOT = (
    "https://raw.githubusercontent.com/"
    "DingTalk-Real-AI/dingtalk-workspace-cli/" + _MAIN_REF + "/scripts/"
)
_INSTALLER_TOKEN = "{installer}"


class DwsInstallPlan(namedtuple(
        "DwsInstallPlanBase",
        "platform source url filename command environment")):
    """Immutable, public-only plan for an approved official installer."""

    __slots__ = ()


class DwsInstallResult(namedtuple(
        "DwsInstallResultBase", "status reason source")):
    """Stable installer outcome that never includes subprocess output."""

    __slots__ = ()


def plan_dws_install(platform_name, china_mirror=False):
    """Return the newest-stable official plan without downloading.

    Default order is the official Gitee mirror followed by official GitHub.
    Selecting ``china_mirror`` restricts execution to Gitee only.
    """
    plans = candidate_plans(platform_name, china_mirror)
    return plans[0]


def candidate_plans(platform_name, china_mirror=False):
    """Ordered official plans: China-first, with GitHub fallback unless pinned."""
    platform_key = _platform_key(platform_name)
    if platform_key == "windows":
        filename = "install.ps1"
        command = (
            "powershell.exe", "-NoProfile", "-NonInteractive", "-File",
            _INSTALLER_TOKEN,
        )
    else:
        filename = "install.sh"
        command = ("sh", _INSTALLER_TOKEN)

    gitee_environment = (
        ("DWS_GITEE_REPO", "DingTalk-Real-AI/dingtalk-workspace-cli"),
        ("DWS_NO_SKILLS", "1"),
    )
    github_environment = (("DWS_NO_SKILLS", "1"),)

    gitee_plan = DwsInstallPlan(
        platform_key, "official-gitee", _GITEE_ROOT + filename, filename,
        command, gitee_environment,
    )
    github_plan = DwsInstallPlan(
        platform_key, "official-github", _GITHUB_ROOT + filename, filename,
        command, github_environment,
    )
    if china_mirror:
        return (gitee_plan,)
    return (gitee_plan, github_plan)


def execute_dws_install(
        plan, approved, downloader, process_runner, temp_root=None):
    """Download and locally execute official plans after explicit approval.

    Tries each official candidate in order; only fails once every source has
    been attempted. Nothing is piped straight into a shell.
    """
    if approved is not True:
        source = _public_source(plan)
        return DwsInstallResult(
            "action_required", "dependency_install_declined", source
        )

    platform_name = getattr(plan, "platform", None)
    try:
        # Always Gitee-first with official GitHub fallback; both are official.
        plans = candidate_plans(platform_name, False)
    except ValueError:
        return DwsInstallResult(
            "failed", "dependency_install_failed", _public_source(plan)
        )

    # The supplied plan itself must be an official one; never silently replace
    # a deceptive plan with a trusted one.
    if not any(_plan_fields_match(plan, item) for item in plans):
        return DwsInstallResult(
            "failed", "dependency_install_failed", _public_source(plan)
        )

    private_dir = None
    last_result = None
    try:
        for candidate in plans:
            private_dir = None
            try:
                private_dir = tempfile.mkdtemp(prefix="dws-install-", dir=temp_root)
                os.chmod(private_dir, 0o700)
            except Exception:
                last_result = DwsInstallResult(
                    "failed", "dependency_install_failed", candidate.source
                )
                continue
            outcome = _install_one(
                candidate, private_dir, downloader, process_runner
            )
            last_result = outcome
            if outcome.status == "ready":
                return outcome
            # This source failed; remove its directory before trying the next.
            if not _remove_private_dir(private_dir):
                return DwsInstallResult(
                    "failed", "dependency_cleanup_failed", candidate.source
                )
            private_dir = None
        return last_result
    finally:
        if private_dir is not None and not _remove_private_dir(private_dir):
            return DwsInstallResult(
                "failed", "dependency_cleanup_failed",
                getattr(last_result, "source", None),
            )


def _install_one(plan, private_dir, downloader, process_runner):
    if not _is_official_plan(plan):
        return DwsInstallResult(
            "failed", "dependency_install_failed", _public_source(plan)
        )

    installer_path = os.path.join(private_dir, plan.filename)
    try:
        _download(downloader, plan.url, installer_path)
    except Exception:
        return DwsInstallResult(
            "failed", "dependency_download_failed", plan.source
        )

    if (not os.path.isfile(installer_path) or
            os.path.islink(installer_path)):
        return DwsInstallResult(
            "failed", "dependency_download_failed", plan.source
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
        expected = candidate_plans(plan.platform, False) + candidate_plans(
            plan.platform, True
        )
    except (TypeError, ValueError):
        return False
    return any(_plan_fields_match(plan, item) for item in expected)


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
    # The installer needs OS paths and explicit proxy settings, not agent tokens.
    inherited_names = (
        "PATH", "HOME", "USERPROFILE", "SystemRoot", "SYSTEMROOT", "WINDIR",
        "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "APPDATA", "LOCALAPPDATA",
        "LANG", "LC_ALL", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "no_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR",
    )
    process_environment = {name: os.environ[name] for name in inherited_names
                           if name in os.environ}
    process_environment.update(dict(environment))
    method = getattr(process_runner, "run", None)
    if method is not None:
        return method(
            command, shell=False, cwd=cwd, env=process_environment
        )
    return process_runner(
        command, shell=False, cwd=cwd, env=process_environment
    )
