from __future__ import absolute_import

import copy
from datetime import datetime
import hashlib
import json
import os
import re
import shlex
import subprocess
import tempfile

from . import __version__
from .output import (
    ReportContractError,
    validate_standard_json,
    validate_standard_report,
)


RFC3339_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


class NotificationResult(object):
    def __init__(self, status, reason=""):
        self.status = status
        self.reason = reason

    @property
    def requires_attention(self):
        return self.status not in (
            "delivered", "notification_disabled", "recipient_not_configured",
            "skipped",
        )

    @property
    def message(self):
        detail = " ({0})".format(self.reason) if self.reason else ""
        return "Enterprise notification: {0}{1}".format(self.status, detail)


def trigger_notification(markdown, report_json, summary=None, bridge_command=None):
    language = _report_language(markdown)
    validate_standard_report(markdown, language)
    validate_standard_json(report_json)
    envelope = _build_envelope(markdown, report_json, summary)
    command = _normalize_bridge_command(bridge_command)
    if command is None:
        return NotificationResult("skipped", "bridge_unavailable")

    envelope_path = None
    try:
        with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", suffix=".json", delete=False) as handle:
            envelope_path = handle.name
            json.dump(envelope, handle, ensure_ascii=False, separators=(",", ":"))
        completed = subprocess.run(
            command + ["deliver", "--envelope", envelope_path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
            check=False,
            shell=False,
            timeout=30,
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


def _build_envelope(markdown, report_json, summary):
    checked_at = report_json["sections"]["system"]["checked_at"]["value"]
    _validate_generated_at(checked_at)
    if summary is None:
        summary = os.environ.get("ENTERPRISE_NOTIFICATION_SUMMARY", "")
    if not isinstance(summary, str):
        raise ReportContractError("notification summary must be text")
    summary_mode = "host_agent" if summary else "deterministic"
    return {
        "schema_version": "1",
        "report_id": _report_id(markdown, report_json),
        "generated_at": checked_at,
        "detector": {"name": "wifi-health-detector", "version": __version__},
        "report": {
            "markdown": markdown,
            "json": copy.deepcopy(report_json),
        },
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
    if bridge_command is None:
        bridge_command = _discover_bridge_command()
    if isinstance(bridge_command, str):
        bridge_command = shlex.split(bridge_command, posix=True)
    if not isinstance(bridge_command, (list, tuple)) or not bridge_command:
        return None
    if not all(isinstance(part, str) and part for part in bridge_command):
        return None
    return list(bridge_command)


def _discover_bridge_command():
    override = os.environ.get("ENTERPRISE_NOTIFICATION_BRIDGE")
    if override:
        return override
    skill_directory = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    bridge_directory = os.path.join(
        os.path.dirname(skill_directory), "enterprise-notification-bridge"
    )
    launcher_name = "run.bat" if os.name == "nt" else "run.sh"
    launcher = os.path.join(bridge_directory, launcher_name)
    if os.path.isfile(launcher):
        return [launcher]
    return None


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
    if not isinstance(payload.get("status"), str):
        return NotificationResult("bridge_failed", "invalid_bridge_response")
    reason = payload.get("reason", "")
    if not isinstance(reason, str):
        reason = "invalid_bridge_response"
    return NotificationResult(payload["status"], reason)
