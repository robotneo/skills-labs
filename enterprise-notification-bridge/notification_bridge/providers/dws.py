from __future__ import absolute_import

import json

from .base import Provider, ProviderResult


class DwsProvider(Provider):
    """Adapter for the documented, JSON-only surface of the DWS CLI.

    The runner is deliberately injected: the bridge does not start processes
    itself, which keeps command execution and any user-authorized login under
    the host application's control.
    """

    platform = "dingtalk"
    name = "dws-cli"
    priority = 10

    def __init__(self, runner, executable="dws"):
        self._runner = runner
        self.executable = executable
        self._json_help_confirmed = set()

    def capabilities(self):
        result = self._run([self.executable, "--help"])
        if result[0] is not None or result[1] != 0:
            return {"available": False}
        return {
            "available": True,
            "operations": [
                "auth_status", "login", "list_profiles", "resolve_recipient",
                "send_report",
            ],
        }

    def auth_status(self, profile=None):
        return self._json_command([self.executable, "auth", "status", "--format", "json"])

    def login(self):
        return self._json_command([self.executable, "auth", "login", "--format", "json"])

    def list_profiles(self):
        result = self._json_command([self.executable, "profile", "list", "--format", "json"])
        if result.status != "ok":
            return result
        if not isinstance(result.data, dict) or not isinstance(result.data.get("profiles"), list):
            return ProviderResult("unavailable", "dws_profiles_invalid")
        return choose_profile(result.data["profiles"])

    def resolve_recipient(self, profile, selector):
        return ProviderResult(
            "action_required",
            "recipient_selection_required",
            data={
                "operation": "resolve_recipient",
                "profile": profile,
                "selector": selector,
            },
        )

    def send_report(self, profile, recipient, envelope):
        # DWS has no documented send command in this bridge.  Do not guess one;
        # request a correlated host-mediated continuation instead.
        return ProviderResult(
            "action_required", "host_send_required", data={
                "operation": "send_report",
                "profile": profile,
                "recipient": recipient,
            },
        )

    def _json_command(self, command):
        confirmation = self._confirm_json_format(command)
        if confirmation is not None:
            return confirmation
        error, returncode, stdout, stderr = self._run(command)
        if error is not None:
            return ProviderResult("unavailable", "dws_unavailable", retryable=True)
        if returncode != 0:
            return ProviderResult(
                "unavailable", "dws_command_failed", retryable=True,
            )
        try:
            payload = json.loads(stdout)
        except (TypeError, ValueError):
            return ProviderResult("unavailable", "dws_invalid_json")
        if not isinstance(payload, dict):
            return ProviderResult("unavailable", "dws_invalid_json")
        return ProviderResult("ok", data=payload)

    def _confirm_json_format(self, command):
        leaf_command = tuple(command[:-2])
        if leaf_command in self._json_help_confirmed:
            return None

        error, returncode, stdout, stderr = self._run(list(leaf_command) + ["--help"])
        if error is not None:
            return ProviderResult("unavailable", "dws_json_format_unconfirmed", retryable=True)
        if returncode != 0:
            return ProviderResult(
                "unavailable", "dws_json_format_unconfirmed", retryable=True,
            )
        if "--format" not in stdout or "json" not in stdout.lower():
            return ProviderResult("unavailable", "dws_json_format_unsupported")
        self._json_help_confirmed.add(leaf_command)
        return None

    def _run(self, command):
        try:
            if hasattr(self._runner, "run"):
                output = self._runner.run(list(command))
            else:
                output = self._runner(list(command))
        except (OSError, RuntimeError) as error:
            return error, 1, "", ""

        if isinstance(output, tuple):
            returncode = output[0]
            stdout = output[1] if len(output) > 1 else ""
            stderr = output[2] if len(output) > 2 else ""
        else:
            returncode = getattr(output, "returncode", 0)
            stdout = getattr(output, "stdout", output)
            stderr = getattr(output, "stderr", "")
        return None, returncode, _text(stdout), _text(stderr)


def choose_profile(profiles, requested_profile=None):
    """Choose a DWS-returned stable profile without constructing identifiers."""
    valid_profiles = [
        profile for profile in profiles
        if isinstance(profile, dict) and isinstance(profile.get("profile"), str)
    ]
    if requested_profile is not None:
        for profile in valid_profiles:
            if profile["profile"] == requested_profile:
                return ProviderResult("ok", data=profile)
    elif len(valid_profiles) == 1:
        return ProviderResult("ok", data=valid_profiles[0])

    return ProviderResult(
        "action_required",
        "profile_selection_required",
        data={"profiles": valid_profiles},
    )


def _text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value if isinstance(value, str) else str(value)
