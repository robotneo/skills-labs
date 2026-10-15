from __future__ import absolute_import

import copy
from datetime import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

from . import __version__
from .html_report import render_html
from .output import (
    ReportContractError,
    validate_standard_json,
    validate_standard_report,
)


RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

# Only codes defined by the Bridge delivery protocol may cross into detector
# diagnostics. Treat the subprocess response as untrusted even when it is JSON.
BRIDGE_DELIVERY_STATUSES = frozenset((
    "action_required",
    "authorization_recheck_failed",
    "authorization_required",
    "configured_provider_unavailable",
    "delivered",
    "delivery_reconciliation_required",
    "delivery_status_failed",
    "dependency_cleanup_failed",
    "dependency_download_failed",
    "dependency_install_declined",
    "dependency_install_failed",
    "dependency_install_required",
    "dependency_integrity_failed",
    "dependency_verification_failed",
    "dependency_version_unsupported",
    "duplicate_resolved_recipient",
    "dry_run",
    "dws_admin_authorization_required",
    "dws_authorization_required",
    "dws_command_failed",
    "dws_executable_invalid",
    "dws_invalid_json",
    "dws_json_format_unconfirmed",
    "dws_json_format_unsupported",
    "dws_profiles_invalid",
    "dws_unavailable",
    "dws_upgrade_required",
    "first_delivery_confirmation_required",
    "host_send_required",
    "login_required",
    "native_operation_required",
    "native_operation_result_invalid",
    "native_operation_unavailable",
    "notification_disabled",
    "notification_failed",
    "platform_not_configured",
    "profile_not_validated",
    "profile_selection_required",
    "provider_auth_status_failed",
    "provider_login_failed",
    "provider_profile_list_failed",
    "provider_recipient_resolution_failed",
    "provider_send_failed",
    "provider_unavailable",
    "provider_unsupported",
    "recipient_ambiguous",
    "recipient_not_configured",
    "recipient_not_found",
    "recipient_not_resolved",
    "recipient_selection_required",
    "reconciled_not_delivered",
    "skipped",
    "stale_delivery_result",
))


class NotificationResult(object):
    def __init__(self, status, reason=""):
        self.status = status
        self.reason = reason

    @property
    def requires_attention(self):
        return self.status not in (
            "delivered", "notification_disabled", "recipient_not_configured",
            "dry_run", "skipped",
        )

    @property
    def message(self):
        # Bridge details may contain provider, Profile, organization, or auth
        # context. The detector emits only the stable status outside stdout.
        return "Enterprise notification: {0}".format(self.status)


def trigger_notification(markdown, report_json, summary=None, bridge_command=None,
                         recipient=None, dry_run=False):
    language = _report_language(markdown)
    validate_standard_report(markdown, language)
    validate_standard_json(report_json)
    html_attachment, html_error = _render_html_attachment(report_json, language)
    if html_error is not None:
        # The Markdown fallback keeps a notification flowing, but a failed HTML
        # render must never be invisible: the recipient would otherwise get a
        # plain-text bubble with no clue why the file attachment is missing.
        print(
            "Wi-Fi notification: HTML attachment unavailable ({0}); "
            "falling back to a Markdown message.".format(html_error),
            file=sys.stderr,
        )
        if _html_required():
            # Verification/acceptance mode: surface the failure instead of
            # silently delivering Markdown, so a broken renderer cannot masquerade
            # as a successful file send.
            return NotificationResult("skipped", "html_attachment_unavailable")
    envelope = _build_envelope(markdown, report_json, summary, html_attachment)
    envelope_path = None
    try:
        try:
            command = _normalize_bridge_command(bridge_command)
        except ValueError:
            return NotificationResult("bridge_failed", "invalid_bridge_command")
        if command is None:
            return NotificationResult("skipped", "bridge_unavailable")
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".json", delete=False) as handle:
            envelope_path = handle.name
            # Envelope contains SSID/MAC/IP; lock it to the owner before writing.
            # NamedTemporaryFile already creates it 0600 via mkstemp, but enforce
            # the intent explicitly so a future creation change cannot weaken it.
            if hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o600)
            json.dump(envelope, handle, ensure_ascii=False, separators=(",", ":"))
        delivery_command = command + ["deliver", "--envelope", envelope_path, "--auto"]
        recipient_name = _recipient_name(recipient)
        if recipient_name:
            delivery_command += ["--to", recipient_name]
        if dry_run:
            delivery_command.append("--dry-run")
        completed = subprocess.run(
            delivery_command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
            timeout=60,
        )
        return _result_from_process(completed)
    except Exception as error:
        reason = "bridge_unavailable" if isinstance(error, OSError) else "bridge_failed"
        status = "skipped" if reason == "bridge_unavailable" else "bridge_failed"
        return NotificationResult(status, reason)
    finally:
        if envelope_path is not None:
            try:
                os.unlink(envelope_path)
            except OSError:
                pass


def _recipient_name(recipient):
    """Validate a conversation-supplied recipient name (plain display name)."""
    if not isinstance(recipient, str):
        return ""
    name = recipient.strip()
    if not name or any(ord(ch) < 32 for ch in name):
        return ""
    # Stable ids are not valid display-name overrides; callers must pass a name.
    if ":" in name:
        return ""
    return name


def _render_html_attachment(report_json, language):
    """Render the standalone, fixed-layout HTML carried as a DingTalk file.

    Returns ``(html, error)``: on success ``(document, None)``; on failure
    ``("", reason)`` so the caller can both log the degraded path and, when
    ``WIFI_HEALTH_REQUIRE_HTML`` is set, refuse to silently deliver Markdown.
    A renderer problem never blocks the on-screen report; by default an empty
    HTML string makes the bridge fall back to the legacy Markdown direct
    message.
    """
    try:
        return render_html(report_json, language), None
    except Exception as error:
        reason = "{0}: {1}".format(type(error).__name__, error)
        return "", reason[:200]


def _html_required():
    """Whether a failed HTML render must fail closed instead of using Markdown."""
    return os.environ.get("WIFI_HEALTH_REQUIRE_HTML", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _build_envelope(markdown, report_json, summary, html_attachment=""):
    checked_at = report_json["sections"]["system"]["checked_at"]["value"]
    _validate_generated_at(checked_at)
    if summary is None:
        summary = os.environ.get("ENTERPRISE_NOTIFICATION_SUMMARY", "")
    if not isinstance(summary, str):
        raise ReportContractError("notification summary must be text")
    summary_mode = "host_agent" if summary else "deterministic"
    report = {
        "markdown": markdown,
        "json": copy.deepcopy(report_json),
    }
    if html_attachment:
        report["html"] = html_attachment
    return {
        "schema_version": "1",
        "report_id": _report_id(markdown, report_json),
        "generated_at": checked_at,
        "detector": {"name": "wifi-health-detector", "version": __version__},
        "report": report,
        "ai_summary": {"mode": summary_mode, "text": summary},
    }


def _report_id(markdown, report_json):
    canonical_json = json.dumps(
        report_json, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256((markdown + "\n" + canonical_json).encode("utf-8")).hexdigest()


def _report_language(markdown):
    if isinstance(markdown, str) and markdown.startswith("# 📶 Wi-Fi Health Report\n"):
        return "en"
    return "zh"


def _validate_generated_at(value):
    if not isinstance(value, str) or not RFC3339_PATTERN.match(value):
        raise ReportContractError("standard report checked_at must be RFC3339 text")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    for timestamp_format in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            datetime.strptime(normalized, timestamp_format)
            return
        except ValueError:
            pass
    raise ReportContractError("standard report checked_at must be RFC3339 text")


def _normalize_bridge_command(bridge_command):
    explicit = bridge_command is not None
    if bridge_command is None:
        bridge_command, explicit = _discover_bridge_command()
    if isinstance(bridge_command, str):
        try:
            bridge_command = json.loads(bridge_command)
        except (TypeError, ValueError):
            raise ValueError("explicit Bridge command must be a JSON vector")
    if not isinstance(bridge_command, (list, tuple)) or not bridge_command:
        if explicit:
            raise ValueError("explicit Bridge command is empty")
        return None
    if not all(isinstance(part, str) and part for part in bridge_command):
        if explicit:
            raise ValueError("explicit Bridge command is invalid")
        return None
    return list(bridge_command)


def _discover_bridge_command():
    if "ENTERPRISE_NOTIFICATION_BRIDGE" in os.environ:
        return os.environ["ENTERPRISE_NOTIFICATION_BRIDGE"], True
    skill_directory = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    launcher_name = "run.bat" if os.name == "nt" else "run.sh"
    for bridge_directory in (
        os.path.join(skill_directory, "integrations", "enterprise-notification-bridge"),
        os.path.join(os.path.dirname(skill_directory), "enterprise-notification-bridge"),
    ):
        launcher = os.path.join(bridge_directory, launcher_name)
        if os.path.isfile(launcher):
            return [launcher], False
    return None, False


def _result_from_process(completed):
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if completed.returncode != 0:
        return NotificationResult(
            "bridge_failed", payload.get("reason", "bridge_failed")
        )
    if payload.get("status") not in BRIDGE_DELIVERY_STATUSES:
        return NotificationResult("bridge_failed", "invalid_bridge_response")
    reason = payload.get("reason", "")
    if not isinstance(reason, str):
        reason = "invalid_bridge_response"
    return NotificationResult(payload["status"], reason)
