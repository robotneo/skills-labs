from __future__ import absolute_import

import json
import os
import re
import shutil
import tempfile

from .base import Provider, ProviderResult


# Maximum single-message length we hand to DWS. The fixed health report is
# short; this only guards a pathological payload without truncating content
# silently (an over-long report is reported as a send failure instead).
_MAX_MESSAGE_CHARS = 12000

# The standalone HTML attachment is delivered as a file message. DWS only
# accepts a safe path relative to the process working directory, so the report
# is materialized inside a private outbox (the runner's cwd) and referenced by
# its basename. Bounds mirror the bridge contract's attachment limit.
_MAX_HTML_CHARS = 200_000
_ATTACHMENT_PREFIX = "wifi-report-"
_ATTACHMENT_NAME = "health"
_ATTACHMENT_SUFFIX = ".html"


def report_message_text(envelope):
    """Return the validated report Markdown carried by an envelope/dict."""
    if hasattr(envelope, "report"):
        report = envelope.report
    elif isinstance(envelope, dict):
        report = envelope.get("report", {})
    else:
        report = {}
    markdown = report.get("markdown", "") if isinstance(report, dict) else ""
    return markdown if isinstance(markdown, str) else ""


def report_html_text(envelope):
    """Return the optional standalone HTML report, or '' when absent."""
    if hasattr(envelope, "report"):
        report = envelope.report
    elif isinstance(envelope, dict):
        report = envelope.get("report", {})
    else:
        report = {}
    html_text = report.get("html", "") if isinstance(report, dict) else ""
    return html_text if isinstance(html_text, str) else ""


def clean_recipient_name(value):
    if not isinstance(value, str):
        return ""
    name = value.strip()
    # A stable id (corpId:userId / openDingTalkId) must never flow into the
    # name-based auto path; only plain display names are accepted here.
    if not name or any(ord(ch) < 32 for ch in name):
        return ""
    if ":" in name or re.match(r"^[A-Za-z0-9+/=_-]{20,}$", name):
        return ""
    return name


def _parse_json_object(stdout):
    try:
        payload = json.loads(stdout)
    except (TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _lookup_outcome(result):
    # Newer ``contact +lookup`` JSON uses ok/outcome; tolerate simple shapes.
    if result.status != "ok" or not isinstance(result.data, dict):
        error = result.data.get("error", {}) if isinstance(result.data, dict) else {}
        subtype = error.get("subtype") if isinstance(error, dict) else None
        if subtype == "ambiguous_match":
            return "ambiguous"
        if subtype in ("not_found", "not_found_user"):
            return "not_found"
        return "error"
    if result.data.get("ok") is False:
        subtype = (result.data.get("error") or {}).get("subtype")
        if subtype == "ambiguous_match":
            return "ambiguous"
        if subtype in ("not_found", "not_found_user"):
            return "not_found"
        return "error"
    profile = (result.data.get("data") or {}).get("profile")
    if isinstance(profile, dict) and profile.get("orgUserName"):
        return "unique"
    return "error"


def _dm_ambiguity(payload):
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    details = error.get("details")
    reason = error.get("reason")
    subtype = details.get("subtype") if isinstance(details, dict) else None
    if reason == "resolution_ambiguous" or subtype == "ambiguous":
        return "recipient_ambiguous"
    if subtype == "not_found" or reason == "resolution_not_found":
        return "recipient_not_found"
    return None


def _dm_error_reason(payload):
    error = payload.get("error") if isinstance(payload, dict) else None
    category = error.get("category") if isinstance(error, dict) else None
    if category in ("validation", "client"):
        # Map client-side resolution problems to recipient reasons; the
        # ambiguity case is already handled by _dm_ambiguity.
        return "recipient_not_resolved"
    return "provider_send_failed"


def _external_id(payload):
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("messageId", "message_id", "openDingTalkId", "id"):
            value = data.get(key)
            if isinstance(value, (str, int)) and str(value):
                return str(value)
    for key in ("messageId", "message_id", "id"):
        value = payload.get(key)
        if isinstance(value, (str, int)) and str(value):
            return str(value)
    return ""


class DwsProvider(Provider):
    """Adapter for the documented, JSON-only surface of the DWS CLI.

    The runner is deliberately injected: the bridge does not start processes
    itself, which keeps command execution and any user-authorized login under
    the host application's control.
    """

    platform = "dingtalk"
    name = "dws-cli"
    priority = 10
    supports_device_login = True

    def __init__(self, runner, executable="dws"):
        self._runner = runner
        self.executable = executable
        self._json_help_confirmed = set()

    def prime_json_help(self, leaves):
        """Pre-mark leaves whose ``--help`` JSON support was already verified.

        Dependency verification probes leaf help before this provider runs. On a
        cold DWS install the first leaf invocation builds an MCP discovery
        cache, so sharing the verified result here avoids re-launching the same
        probes (and contending for that cache lock) during one send. Each leaf
        is given relative to the current executable, matching the key that
        ``_confirm_json_format`` builds, e.g. ("auth", "status").
        """
        for leaf in leaves or ():
            self._json_help_confirmed.add(
                (self.executable,) + tuple(leaf)
            )

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

    def login(self, device_login=False):
        command = [self.executable, "auth", "login"]
        if device_login:
            command.append("--device")
        command.extend(["--format", "json"])
        return self._json_command(command)

    def list_profiles(self):
        result = self._json_command([self.executable, "profile", "list", "--format", "json"])
        if result.status != "ok":
            return result
        if not isinstance(result.data, dict) or not isinstance(result.data.get("profiles"), list):
            return ProviderResult("unavailable", "dws_profiles_invalid")
        return choose_profile(result.data["profiles"])

    def resolve_recipient(self, profile, selector):
        """Resolve a display name to a unique contact (default auto path).

        Uses the documented read-only ``contact +lookup`` leaf. A name that is
        unknown or matches several people is reported as an unresolvable
        selector so the caller can fall back to its default recipient instead
        of guessing among candidates.
        """
        name = clean_recipient_name(selector)
        if not name:
            return ProviderResult("failed", "recipient_not_resolved")
        result = self._json_command(
            [self.executable, "contact", "+lookup", "--name", name,
             "--format", "json"]
        )
        outcome = _lookup_outcome(result)
        if outcome == "unique":
            profile_data = result.data.get("data", {}).get("profile", {})
            resolved = profile_data.get("orgUserName") or name
            return ProviderResult(
                "resolved", data={"recipient": resolved, "selector": name}
            )
        if outcome == "ambiguous":
            return ProviderResult("failed", "recipient_ambiguous", retryable=False)
        if outcome == "not_found":
            return ProviderResult("failed", "recipient_not_found", retryable=False)
        return ProviderResult("failed", "provider_recipient_resolution_failed")

    def host_resolve_recipient(self, profile, selector):
        """Legacy host-mediated resolution request (continuation path)."""
        return ProviderResult(
            "action_required",
            "recipient_selection_required",
            data={
                "operation": "resolve_recipient",
                "profile": profile,
                "selector": selector,
            },
        )

    def send_report(self, profile, recipient, envelope, dry_run=False):
        """Send one report to a resolved display name.

        Preferred transport (cross-client consistency): when the envelope
        carries a standalone, fixed-layout HTML document, deliver it as a
        ``file`` message via ``chat +messages-send``; DingTalk opens the
        attachment in the system webview/browser, so the layout is identical
        across desktop/mobile/web instead of depending on each client's
        Markdown rendering. When no HTML is present (older producers), fall
        back to the legacy Markdown ``chat +dm`` bubble.
        """
        name = clean_recipient_name(recipient)
        if not name:
            return ProviderResult("failed", "recipient_not_resolved")
        html_text = report_html_text(envelope)
        if html_text:
            return self._send_html_report(name, html_text, dry_run)
        return self._send_markdown_report(name, envelope, dry_run)

    def _send_markdown_report(self, name, envelope, dry_run):
        content = report_message_text(envelope)
        if not content or len(content) > _MAX_MESSAGE_CHARS:
            return ProviderResult("failed", "provider_send_failed")
        command = [
            self.executable, "chat", "+dm", "--to", name,
            "--content", content, "--format", "json",
        ]
        if dry_run:
            command.append("--dry-run")
        else:
            command.append("--yes")
        return self._dm_command(command)

    def _send_html_report(self, name, html_text, dry_run):
        if len(html_text) > _MAX_HTML_CHARS:
            return ProviderResult("failed", "provider_send_failed")
        # DWS accepts only a safe path relative to the process working
        # directory. Materialize the attachment in a private 0700 outbox, run
        # the upload with that directory as cwd, and remove it immediately
        # afterwards (a dry-run never reads the network either).
        outbox = tempfile.mkdtemp(prefix="dws-outbox-")
        attachment = _ATTACHMENT_PREFIX + _ATTACHMENT_NAME + _ATTACHMENT_SUFFIX
        # The attachment name is a compile-time constant, never derived from
        # recipient or report input, so the child path cannot escape the
        # private outbox. Build it by simple concatenation under the outbox and
        # reject anything that does not resolve back inside that directory.
        target = outbox + os.sep + attachment
        resolved_outbox = os.path.realpath(outbox)
        if os.path.dirname(os.path.realpath(target)) != resolved_outbox:
            shutil.rmtree(outbox, ignore_errors=True)
            return ProviderResult("failed", "provider_send_failed")
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        try:
            os.chmod(outbox, 0o700)
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow,
                0o600,
            )
            try:
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(html_text)
            except Exception:
                return ProviderResult("failed", "provider_send_failed")
            command = [
                self.executable, "chat", "+messages-send",
                "--as", "user", "--user-query", name,
                "--msg-type", "file", "--file", attachment,
                "--format", "json",
            ]
            if dry_run:
                command.append("--dry-run")
            else:
                command.append("--yes")
            return self._dm_command(command, cwd=outbox)
        except OSError:
            return ProviderResult("failed", "provider_send_failed", retryable=True)
        finally:
            shutil.rmtree(outbox, ignore_errors=True)

    def host_send_report(self, profile, recipient, envelope):
        """Legacy host-mediated send request (continuation path)."""
        return ProviderResult(
            "action_required", "host_send_required", data={
                "operation": "send_report",
                "profile": profile,
                "recipient": recipient,
            },
        )

    def _dm_command(self, command, cwd=None):
        # Both ``chat +dm`` and ``chat +messages-send`` emit a JSON envelope
        # for execution and dry-run, plus a JSON resolution-error object for
        # ambiguous names. These shortcut leaves are not stable JSON-format
        # probes, so they bypass the help gate. Parse them explicitly and
        # never trust the process exit code alone (dry-run ambiguity exits 0).
        # A file send runs with ``cwd`` pointing at the private outbox because
        # DWS only accepts a path relative to the process working directory.
        error, returncode, stdout, stderr = self._run(command, cwd=cwd)
        if error is not None:
            return ProviderResult("unavailable", "dws_unavailable", retryable=True)
        payload = _parse_json_object(stdout)
        if payload is None:
            if returncode != 0:
                return ProviderResult("unavailable", "dws_command_failed",
                                      retryable=True)
            return ProviderResult("unavailable", "dws_invalid_json")
        ambiguity = _dm_ambiguity(payload)
        if ambiguity is not None:
            return ProviderResult("failed", ambiguity, retryable=False)
        if payload.get("error") is not None:
            reason = _dm_error_reason(payload)
            retryable = reason not in ("recipient_not_found",
                                       "recipient_ambiguous")
            return ProviderResult("failed", reason, retryable=retryable)
        if payload.get("dry_run") is True and payload.get("executed") is False:
            # Preview path: prove name resolution and renderability without
            # sending. Treated as a non-delivered, non-erroring dry run.
            return ProviderResult("ok", "dry_run", data={"dry_run": True})
        if returncode != 0:
            return ProviderResult("failed", "provider_send_failed", retryable=True)
        external_id = _external_id(payload)
        return ProviderResult("sent", data={"external_id": external_id})

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
        leaf_command = tuple(
            item for item in command[:-2] if item != "--device"
        )
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

    def _run(self, command, cwd=None):
        try:
            if hasattr(self._runner, "run"):
                # The file-attachment send passes a private outbox as cwd; the
                # injected runner accepts it as a keyword. Plain calls keep the
                # historical single-argument invocation so existing hosts/fakes
                # that only model read commands stay compatible.
                if cwd is not None:
                    try:
                        output = self._runner.run(list(command), cwd=cwd)
                    except TypeError:
                        output = self._runner.run(list(command))
                else:
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
