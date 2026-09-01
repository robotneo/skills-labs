from __future__ import absolute_import

import argparse
import json
import os
import sys

from .config import ChannelConfig, load_config, save_config
from .contract import ContractError, validate_envelope
from .ledger import DeliveryLedger
from .models import Envelope
from .service import BridgeService, DeliveryBatchResult


COMMAND_NAMES = ("status", "bind", "recipients", "deliver", "retry")


class CommandError(ValueError):
    def __init__(self, reason, message):
        ValueError.__init__(self, message)
        self.reason = reason


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise CommandError("invalid_arguments", message)


class BridgeCommands(object):
    """Shared command adapter for the CLI and MCP transports."""

    def __init__(self, service, config, config_path=None):
        self.service = service
        self.config = config
        self.config_path = config_path

    def status(self):
        return {
            "status": "enabled" if self.config.enabled else "disabled",
            "channels": [channel.to_dict() for channel in self.config.channels],
        }

    def bind(self, platform):
        if not isinstance(platform, str) or not platform:
            raise CommandError("invalid_arguments", "platform is required")
        result = self.service.bind(platform)
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
        if channel is None:
            channel = ChannelConfig(
                platform, profile=profile, recipients=list(recipients)
            )
            self.config.channels.append(channel)
        else:
            if profile is not None:
                channel.profile = profile
            channel.recipients = list(recipients)
        save_config(self.config, self.config_path)
        return {
            "status": "configured",
            "platform": platform,
            "profile": channel.profile,
            "recipients": list(channel.recipients),
        }

    def deliver(self, envelope_value):
        envelope = load_envelope(envelope_value)
        return result_to_dict(self.service.deliver(envelope))

    def retry(self, envelope_value):
        return self.deliver(envelope_value)

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
            with open(value, "r") as handle:
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
            value["report"], value["ai_summary"],
        )
        envelope.schema_version = value["schema_version"]
        validate_envelope(envelope)
    except (ContractError, KeyError, TypeError, ValueError) as error:
        raise CommandError("malformed_envelope", str(error))
    return envelope


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


def build_commands(config_path=None, ledger_path=None, providers=None):
    config_path = config_path or os.environ.get(
        "ENTERPRISE_NOTIFICATION_BRIDGE_CONFIG"
    )
    ledger_path = ledger_path or os.environ.get(
        "ENTERPRISE_NOTIFICATION_BRIDGE_LEDGER"
    ) or _default_state_path("delivery-ledger.sqlite3")
    config = load_config(config_path)
    service = BridgeService(
        config, list(providers or []), DeliveryLedger(ledger_path)
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
            commands = build_commands(arguments.config, arguments.ledger)
        result = _execute(arguments, commands)
        _write_json(stdout, result)
        return 0
    except CommandError as error:
        _write_json(stdout, {"status": "error", "reason": error.reason})
        stderr.write("{0}: {1}\n".format(error.reason, error))
        return 2
    except Exception as error:
        _write_json(stdout, {"status": "error", "reason": "internal_error"})
        stderr.write("internal_error: {0}\n".format(error))
        return 1


def _execute(arguments, commands):
    if arguments.command == "status":
        return commands.status()
    if arguments.command == "bind":
        return commands.bind(arguments.platform)
    if arguments.command == "recipients":
        return commands.configure_recipients(
            arguments.platform, arguments.recipient, arguments.profile
        )
    if arguments.command == "deliver":
        return commands.deliver(arguments.envelope)
    if arguments.command == "retry":
        return commands.retry(arguments.envelope)
    raise CommandError("invalid_arguments", "unsupported command")


def _parser():
    parser = _ArgumentParser(prog="enterprise-notification-bridge")
    parser.add_argument("--config")
    parser.add_argument("--ledger")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("status")

    bind = subparsers.add_parser("bind")
    bind.add_argument("--platform", required=True)

    recipients = subparsers.add_parser("recipients")
    recipients.add_argument("--platform", required=True)
    recipients.add_argument("--profile")
    recipients.add_argument("--recipient", action="append", required=True)

    for name in ("deliver", "retry"):
        delivery = subparsers.add_parser(name)
        delivery.add_argument("--envelope", required=True)
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
