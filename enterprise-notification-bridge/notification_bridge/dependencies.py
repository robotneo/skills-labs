from __future__ import absolute_import

import json
import ntpath
import os
import re
from collections import namedtuple


MINIMUM_DWS_VERSION = "1.0.15"

_SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class DwsDependency(namedtuple(
        "DwsDependencyBase",
        "executable version minimum_version install_source")):
    """Immutable public metadata for one discovered DWS installation."""

    __slots__ = ()


class DependencyStatus(namedtuple(
        "DependencyStatusBase", "status reason dependency")):
    """Immutable discovery or verification result consumed by setup."""

    __slots__ = ()

    @property
    def executable(self):
        return self.dependency.executable if self.dependency is not None else None

    @property
    def version(self):
        return self.dependency.version if self.dependency is not None else None

    @property
    def minimum_version(self):
        if self.dependency is not None:
            return self.dependency.minimum_version
        return MINIMUM_DWS_VERSION

    @property
    def install_source(self):
        return self.dependency.install_source if self.dependency is not None else None


def discover_dws(environment, platform_name, which):
    """Discover DWS in the documented precedence order without executing it."""
    environment = environment or {}
    explicit = environment.get("DWS_EXE")
    if explicit:
        if not os.path.isabs(explicit):
            return DependencyStatus("unavailable", "dws_executable_invalid", None)
        return _discovered(explicit, "environment")

    resolved = which("dws")
    if resolved:
        return _discovered(resolved, "path")

    for source, candidate in _candidate_paths(environment, platform_name):
        resolved = which(candidate)
        if resolved:
            return _discovered(resolved, source)

    return DependencyStatus("action_required", "dependency_install_required", None)


def verify_dws(executable, runner):
    """Verify DWS version and the JSON-capable setup leaves."""
    if not _is_executable_reference(executable):
        return DependencyStatus("unavailable", "dws_executable_invalid", None)

    version_result = _run(runner, [executable, "--version", "--format", "json"])
    if version_result is None or version_result[0] != 0:
        return _status_for(executable, None, "unavailable", "dependency_verification_failed")

    version = _parse_version(version_result[1])
    if version is None:
        return _status_for(executable, None, "unavailable", "dependency_version_unsupported")
    if _version_key(version) < _version_key(MINIMUM_DWS_VERSION):
        return _status_for(executable, version, "action_required", "dws_upgrade_required")

    required_leaves = (
        ("auth", "status"),
        ("auth", "login"),
        ("profile", "list"),
    )
    for leaf in required_leaves:
        result = _run(runner, [executable] + list(leaf) + ["--help"])
        if (result is None or result[0] != 0
                or not _help_advertises_json_format(result[1])):
            return _status_for(
                executable, version, "unavailable", "dependency_verification_failed"
            )

    return _status_for(executable, version, "ready", "dependency_ready")


def _candidate_paths(environment, platform_name):
    home = environment.get("HOME") or environment.get("USERPROFILE")
    windows = str(platform_name).lower().startswith("win")
    executable_name = "dws.cmd" if windows else "dws"
    path_module = ntpath if windows else os.path

    if home:
        if windows:
            yield "user-local", path_module.join(
                home, ".local", "bin", executable_name
            )
            yield "user-local", path_module.join(
                home, "AppData", "Roaming", "npm", executable_name
            )
        else:
            yield "user-local", path_module.join(
                home, ".local", "bin", executable_name
            )

    if str(platform_name).lower() in ("darwin", "macos", "mac"):
        yield "homebrew", "/opt/homebrew/bin/dws"
        yield "homebrew", "/usr/local/bin/dws"

    npm_prefix = environment.get("NPM_CONFIG_PREFIX")
    if npm_prefix:
        if windows:
            yield "npm-global", path_module.join(npm_prefix, executable_name)
        else:
            yield "npm-global", path_module.join(
                npm_prefix, "bin", executable_name
            )


def _discovered(executable, source):
    dependency = DwsDependency(
        executable, None, MINIMUM_DWS_VERSION, source
    )
    return DependencyStatus("discovered", "dependency_discovered", dependency)


def _is_executable_reference(executable):
    if not isinstance(executable, str) or not executable:
        return False
    if not os.path.isabs(executable):
        return os.path.basename(executable) == executable
    return os.path.isfile(executable) and os.access(executable, os.X_OK)


def _help_advertises_json_format(help_text):
    for line in _text(help_text).splitlines():
        normalized = line.lower()
        option = re.search(r"(?:^|\s)(--format(?:\s|=|,|$).*)", normalized)
        if option is None:
            continue
        for value_region in _format_value_regions(option.group(1)):
            if re.search(r"(?<![0-9a-z_-])json(?![0-9a-z_-])", value_region):
                return True
    return False


def _format_value_regions(option_text):
    argument = re.match(
        r"--format(?:\s+|=)(?:<([^>]+)>|\[([^\]]+)\])", option_text
    )
    if argument is not None:
        value_set = argument.group(1) or argument.group(2)
        if value_set.strip() not in ("format", "value", "string"):
            yield value_set

    field_pattern = re.compile(
        r"\b(?:allowed\s+values?|choices?|one\s+of|values?|default)\s*[:=]\s*"
    )
    for field in field_pattern.finditer(option_text):
        remainder = option_text[field.end():]
        boundaries = [
            position for position in (
                remainder.find(";"), remainder.find("."), remainder.find("]")
            ) if position >= 0
        ]
        end = min(boundaries) if boundaries else len(remainder)
        yield remainder[:end]


def _status_for(executable, version, status, reason):
    dependency = DwsDependency(
        executable, version, MINIMUM_DWS_VERSION, "discovered"
    )
    return DependencyStatus(status, reason, dependency)


def _parse_version(stdout):
    try:
        payload = json.loads(_text(stdout))
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    version = payload.get("version")
    if not isinstance(version, str) or not _is_strict_semver(version):
        return None
    return version


def _is_strict_semver(version):
    if _SEMVER.match(version) is None:
        return False
    version_without_build = version.split("+", 1)[0]
    if "-" not in version_without_build:
        return True
    prerelease = version_without_build.split("-", 1)[1]
    return all(
        not (identifier.isdigit() and len(identifier) > 1
             and identifier.startswith("0"))
        for identifier in prerelease.split(".")
    )


def _version_key(version):
    match = _SEMVER.match(version)
    core = tuple(int(part) for part in match.groups()[:3])
    has_prerelease = "-" in version.split("+", 1)[0]
    return core + (0 if has_prerelease else 1,)


def _run(runner, command):
    try:
        output = runner.run(list(command)) if hasattr(runner, "run") else runner(list(command))
    except (OSError, RuntimeError):
        return None
    if isinstance(output, tuple):
        returncode = output[0]
        stdout = output[1] if len(output) > 1 else ""
    else:
        returncode = getattr(output, "returncode", 0)
        stdout = getattr(output, "stdout", output)
    return returncode, _text(stdout)


def _text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value if isinstance(value, str) else str(value)
