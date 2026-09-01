from __future__ import absolute_import

import argparse
import json
import os
import re
import subprocess
import sys

from .config import ChannelConfig, load_config, save_config
from .continuation import (
    ContinuationError, PendingStateStore, normalize_capabilities,
)
from .contract import ContractError, validate_envelope
from .ledger import DeliveryLedger
from .models import Envelope
from .providers.dws import DwsProvider
from .service import BridgeService, DeliveryBatchResult


COMMAND_NAMES = (
    "status", "enable", "bind", "recipients", "deliver", "retry",
    "continue",
)
REPORT_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class CommandError(ValueError):
    def __init__(self, reason, message):
        ValueError.__init__(self, message)
        self.reason = reason


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise CommandError("invalid_arguments", message)


class SubprocessRunner(object):
    """Run an explicit command vector without a shell or interactive stdin."""

    def __init__(self, run_process=None):
        self._run_process = run_process or subprocess.run

    def run(self, command):
        return self._run_process(
            list(command), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
            check=False, shell=False, timeout=30,
        )


class BridgeCommands(object):
    """Shared command adapter for the CLI and MCP transports."""

    def __init__(self, service, config, config_path=None):
        self.service = service
        self.config = config
        self.config_path = config_path

    def status(self):
        state_store = getattr(self.service, "state_store", None)
        pending = []
        if state_store is not None and hasattr(state_store, "pending_actions"):
            pending = state_store.pending_actions()
        return {
            "status": "enabled" if self.config.enabled else "disabled",
            "channels": [channel.to_dict() for channel in self.config.channels],
            "pending_actions": pending,
        }

    def enable(self, platform, provider="auto"):
        if not isinstance(platform, str) or not platform:
            raise CommandError("invalid_arguments", "platform is required")
        if not isinstance(provider, str) or not provider:
            raise CommandError("invalid_arguments", "provider must be a non-empty string")

        channel = self._channel(platform)
        if channel is None:
            channel = ChannelConfig(platform, provider=provider)
            self.config.channels.append(channel)
        else:
            channel.provider = provider
        self.config.enabled = True
        save_config(self.config, self.config_path)
        return {
            "status": "enabled",
            "channel": channel.to_dict(),
        }

    def bind(self, platform, capabilities=None):
        if not isinstance(platform, str) or not platform:
            raise CommandError("invalid_arguments", "platform is required")
        capability_bundle = load_capabilities(capabilities)
        try:
            result = self.service.bind(platform, capability_bundle)
        except ContinuationError as error:
            raise CommandError("malformed_capabilities", str(error))
        profile = result.data.get("profile")
        if result.status == "ok" and isinstance(profile, str) and profile:
            self._store_profile(platform, profile)
        return result_to_dict(result)

    def configure_recipients(self, platform, recipients, profile=None):
        if not isinstance(platform, str) or not platform:
            raise CommandError("invalid_arguments", "platform is required")
        if not isinstance(recipients, list) or not recipients:
            raise CommandError("invalid_arguments", "at least one recipient is required")
        if not all(isinstance(item, str) and item for item in recipients):
            raise CommandError("invalid_arguments", "recipients must be non-empty strings")
        if profile is not None and (not isinstance(profile, str) or not profile):
            raise CommandError("invalid_arguments", "profile must be a non-empty string")

        channel = self._channel(platform)
        if (channel is None or channel.profile is None
                or channel.provider == "auto"
                or (profile is not None and profile != channel.profile)):
            raise CommandError(
                "profile_not_validated",
                "recipients require the exact bound provider profile",
            )
        channel.recipients = list(recipients)
        # Explicit recipient configuration is also an explicit activation
        # action for a fresh, default-disabled Bridge configuration.
        self.config.enabled = True
        save_config(self.config, self.config_path)
        return {
            "status": "configured",
            "platform": platform,
            "profile": channel.profile,
            "recipients": list(channel.recipients),
        }

    def deliver(self, envelope_value, capabilities=None,
                request_host_summary=False):
        envelope = load_envelope(envelope_value)
        capability_bundle = load_capabilities(capabilities)
        try:
            result = self.service.deliver(
                envelope, capability_bundle, request_host_summary
            )
        except ContinuationError as error:
            raise CommandError("malformed_capabilities", str(error))
        return result_to_dict(result)

    def retry(self, report_id, capabilities=None):
        if (not isinstance(report_id, str)
                or not REPORT_ID_PATTERN.match(report_id)):
            raise CommandError(
                "invalid_report_id", "report id must be 64 lowercase hex digits"
            )
        capability_bundle = load_capabilities(capabilities)
        try:
            result = self.service.retry(report_id, capability_bundle)
        except ContinuationError as error:
            raise CommandError("retry_not_available", str(error))
        return result_to_dict(result)

    def continue_operation(self, operation_result):
        value = load_operation_result(operation_result)
        try:
            result = self.service.continue_operation(value)
        except ContinuationError as error:
            raise CommandError("invalid_operation_result", str(error))
        return result_to_dict(result)

    def _channel(self, platform):
        for channel in self.config.channels:
            if channel.platform == platform:
                return channel
        return None

    def _store_profile(self, platform, profile):
        channel = self._channel(platform)
        if channel is None:
            channel = ChannelConfig(platform, profile=profile)
            self.config.channels.append(channel)
        else:
            channel.profile = profile
        save_config(self.config, self.config_path)


def load_envelope(value):
    if isinstance(value, str):
        try:
            with open(value, "r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (IOError, OSError, TypeError, ValueError) as error:
            raise CommandError("malformed_envelope", str(error))
    if not isinstance(value, dict):
        raise CommandError("malformed_envelope", "envelope must be a JSON object")

    required = (
        "schema_version", "report_id", "generated_at", "detector", "report",
        "ai_summary",
    )
    if set(value) != set(required):
        raise CommandError("malformed_envelope", "envelope fields are invalid")
    try:
        envelope = Envelope(
            value["report_id"], value["generated_at"], value["detector"],
            value["report"], value["ai_summary"], value["schema_version"],
        )
        validate_envelope(envelope)
    except (ContractError, KeyError, TypeError, ValueError) as error:
        raise CommandError("malformed_envelope", str(error))
    return envelope


def load_capabilities(value):
    if value is None:
        return None
    value = _load_json_object(
        value, "malformed_capabilities", "capabilities"
    )
    try:
        normalize_capabilities(value)
    except ContinuationError as error:
        raise CommandError("malformed_capabilities", str(error))
    return value


def load_operation_result(value):
    return _load_json_object(
        value, "malformed_operation_result", "operation result"
    )


def _load_json_object(value, reason, label):
    if isinstance(value, str):
        try:
            with open(value, "r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (IOError, OSError, TypeError, ValueError) as error:
            raise CommandError(reason, str(error))
    if not isinstance(value, dict):
        raise CommandError(reason, "{0} must be a JSON object".format(label))
    return value


def result_to_dict(result):
    if isinstance(result, DeliveryBatchResult):
        return {
            "status": result.status,
            "results": [result_to_dict(item) for item in result.results],
        }
    return {
        "status": result.status,
        "reason": result.reason,
        "retryable": result.retryable,
        "data": _json_value(result.data),
    }


def production_providers(run_process=None):
    return [DwsProvider(SubprocessRunner(run_process))]


def build_commands(config_path=None, ledger_path=None, state_path=None,
                   providers=None, run_process=None):
    config_path = config_path or os.environ.get(
        "ENTERPRISE_NOTIFICATION_BRIDGE_CONFIG"
    )
    ledger_path = ledger_path or os.environ.get(
        "ENTERPRISE_NOTIFICATION_BRIDGE_LEDGER"
    ) or _default_state_path("delivery-ledger.sqlite3")
    state_path = state_path or os.environ.get(
        "ENTERPRISE_NOTIFICATION_BRIDGE_STATE"
    ) or _default_state_path("pending-state")
    config = load_config(config_path)
    provider_list = (production_providers(run_process) if providers is None
                     else list(providers))
    service = BridgeService(
        config, provider_list, DeliveryLedger(ledger_path),
        state_store=PendingStateStore(state_path),
        persist_config=lambda: save_config(config, config_path),
    )
    return BridgeCommands(service, config, config_path)


def main(argv=None, commands=None, stdout=None, stderr=None):
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        _write_json(stdout, {"status": "ok", "commands": list(COMMAND_NAMES)})
        return 0
    try:
        arguments = _parser().parse_args(argv)
        if arguments.command is None:
            raise CommandError("invalid_arguments", "a command is required")
        if commands is None:
            commands = build_commands(
                arguments.config, arguments.ledger, arguments.state
            )
        result = _execute(arguments, commands)
        _write_json(stdout, result)
        return 0
    except CommandError as error:
        _write_json(stdout, {"status": "error", "reason": error.reason})
        stderr.write("{0}\n".format(error.reason))
        return 2
    except Exception:
        _write_json(stdout, {"status": "error", "reason": "internal_error"})
        stderr.write("internal_error\n")
        return 1


def _execute(arguments, commands):
    if arguments.command == "status":
        return commands.status()
    if arguments.command == "enable":
        return commands.enable(arguments.platform, arguments.provider)
    if arguments.command == "bind":
        return commands.bind(arguments.platform, arguments.capabilities)
    if arguments.command == "recipients":
        return commands.configure_recipients(
            arguments.platform, arguments.recipient, arguments.profile
        )
    if arguments.command == "deliver":
        return commands.deliver(
            arguments.envelope, arguments.capabilities,
            arguments.request_host_summary,
        )
    if arguments.command == "retry":
        return commands.retry(arguments.report_id, arguments.capabilities)
    if arguments.command == "continue":
        return commands.continue_operation(arguments.operation_result)
    raise CommandError("invalid_arguments", "unsupported command")


def _parser():
    parser = _ArgumentParser(prog="enterprise-notification-bridge")
    parser.add_argument("--config")
    parser.add_argument("--ledger")
    parser.add_argument("--state")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status")

    enable = subparsers.add_parser("enable")
    enable.add_argument("--platform", required=True)
    enable.add_argument("--provider", default="auto")

    bind = subparsers.add_parser("bind")
    bind.add_argument("--platform", required=True)
    bind.add_argument("--capabilities")

    recipients = subparsers.add_parser("recipients")
    recipients.add_argument("--platform", required=True)
    recipients.add_argument("--profile")
    recipients.add_argument("--recipient", action="append", required=True)

    delivery = subparsers.add_parser("deliver")
    delivery.add_argument("--envelope", required=True)
    delivery.add_argument("--capabilities")
    delivery.add_argument("--request-host-summary", action="store_true")

    retry = subparsers.add_parser("retry")
    retry.add_argument("--report-id", required=True)
    retry.add_argument("--capabilities")

    continuation = subparsers.add_parser("continue")
    continuation.add_argument("--operation-result", required=True)
    return parser


def _write_json(stream, value):
    stream.write(json.dumps(
        _json_value(value), ensure_ascii=False, sort_keys=True,
        separators=(",", ":"),
    ))
    stream.write("\n")


def _json_value(value):
    if hasattr(value, "to_dict"):
        return _json_value(value.to_dict())
    if isinstance(value, dict):
        return dict((key, _json_value(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _default_state_path(filename):
    if os.name == "nt":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        root = os.path.join(
            os.path.expanduser("~"), "Library", "Application Support"
        )
    else:
        root = os.path.join(os.path.expanduser("~"), ".local", "state")
    directory = os.path.join(root, "enterprise-notification-bridge")
    if not os.path.exists(directory):
        os.makedirs(directory)
    return os.path.join(directory, filename)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
