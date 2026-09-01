from __future__ import absolute_import

import json
import os
import sys
import tempfile


class ConfigError(ValueError):
    pass


_SECRET_MARKERS = ("token", "secret", "password", "credential", "refresh")
_CONFIG_KEYS = set(("version", "notification"))
_NOTIFICATION_KEYS = set(("enabled", "failure_policy", "ai_summary", "channels"))
_CHANNEL_KEYS = set(("platform", "provider", "profile", "recipients"))


class ChannelConfig(object):
    def __init__(self, platform, provider="auto", profile=None, recipients=None):
        _validate_channel_data({
            "platform": platform,
            "provider": provider,
            "profile": profile,
            "recipients": list(recipients or []),
        })
        self.platform = platform
        self.provider = provider
        self.profile = profile
        self.recipients = list(recipients or [])

    @classmethod
    def from_dict(cls, value):
        _validate_channel_data(value)
        recipients = value.get("recipients", [])
        return cls(value["platform"], value.get("provider", "auto"),
                   value.get("profile"), recipients)

    def to_dict(self):
        return {
            "platform": self.platform,
            "provider": self.provider,
            "profile": self.profile,
            "recipients": list(self.recipients),
        }


class BridgeConfig(object):
    def __init__(self, version=1, enabled=False, failure_policy="non_blocking",
                 ai_summary=None, channels=None):
        self.version = version
        self.enabled = bool(enabled)
        self.failure_policy = failure_policy
        self.ai_summary = ai_summary if ai_summary is not None else {
            "provider": "host_agent", "fallback": "deterministic"
        }
        self.channels = list(channels or [])
        _validate_config_data(self.to_dict())

    @classmethod
    def from_dict(cls, value):
        _validate_config_data(value)
        notification = value.get("notification", {})
        channels = notification.get("channels", [])
        return cls(
            version=value.get("version", 1),
            enabled=notification.get("enabled", False),
            failure_policy=notification.get("failure_policy", "non_blocking"),
            ai_summary=notification.get("ai_summary"),
            channels=[ChannelConfig.from_dict(channel) for channel in channels],
        )

    def enabled_channels(self):
        if not self.enabled:
            return []
        return list(self.channels)

    def to_dict(self):
        return {
            "version": self.version,
            "notification": {
                "enabled": self.enabled,
                "failure_policy": self.failure_policy,
                "ai_summary": self.ai_summary,
                "channels": [channel.to_dict() for channel in self.channels],
            },
        }


def load_config(path=None):
    path = path or _default_config_path()
    if not os.path.exists(path):
        return BridgeConfig()
    with open(path, "r") as handle:
        return BridgeConfig.from_dict(json.load(handle))


def save_config(config, path=None):
    if not isinstance(config, BridgeConfig):
        raise ConfigError("config must be a BridgeConfig")
    payload = config.to_dict()
    _validate_config_data(payload)
    path = path or _default_config_path()
    directory = os.path.dirname(path)
    if directory and not os.path.exists(directory):
        os.makedirs(directory)
    descriptor, temporary_path = tempfile.mkstemp(prefix=".config-", dir=directory or None)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        _replace(temporary_path, path)
    except Exception:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)
        raise


def _default_config_path():
    if os.name == "nt":
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        root = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        root = os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(root, "enterprise-notification-bridge", "config.json")


def _replace(source, destination):
    replace = getattr(os, "replace", None)
    if replace is not None:
        replace(source, destination)
    else:
        os.rename(source, destination)


def _reject_secrets(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if any(marker in str(key).lower() for marker in _SECRET_MARKERS):
                raise ConfigError("secret fields are not allowed")
            _reject_secrets(item)
    elif isinstance(value, list):
        for item in value:
            _reject_secrets(item)


def _reject_unknown(value, allowed):
    unknown = set(value) - allowed
    if unknown:
        raise ConfigError("unsupported configuration field: {0}".format(sorted(unknown)[0]))


def _validate_config_data(value):
    if not isinstance(value, dict):
        raise ConfigError("configuration must be an object")
    _reject_secrets(value)
    _reject_unknown(value, _CONFIG_KEYS)
    notification = value.get("notification", {})
    if not isinstance(notification, dict):
        raise ConfigError("notification must be an object")
    _reject_unknown(notification, _NOTIFICATION_KEYS)
    channels = notification.get("channels", [])
    if not isinstance(channels, list):
        raise ConfigError("notification channels must be a list")
    for channel in channels:
        _validate_channel_data(channel)


def _validate_channel_data(value):
    if not isinstance(value, dict):
        raise ConfigError("channel must be an object")
    _reject_secrets(value)
    _reject_unknown(value, _CHANNEL_KEYS)
    if not value.get("platform"):
        raise ConfigError("channel platform is required")
    recipients = value.get("recipients", [])
    if not isinstance(recipients, list):
        raise ConfigError("channel recipients must be a list")
