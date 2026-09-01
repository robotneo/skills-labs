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
_AI_SUMMARY_KEYS = set(("provider", "fallback"))
_PLATFORMS = frozenset(("dingtalk", "feishu", "wecom"))
_PROVIDERS = frozenset(("auto", "native", "dws-cli"))


class ChannelConfig(object):
    def __init__(self, platform, provider="auto", profile=None, recipients=None):
        recipients = list(recipients or [])
        _validate_channel_data({
            "platform": platform,
            "provider": provider,
            "profile": profile,
            "recipients": recipients,
        })
        self.platform = platform
        self.provider = provider
        self.profile = profile
        self.recipients = recipients

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
        self.enabled = enabled
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
    with open(path, "r", encoding="utf-8") as handle:
        return BridgeConfig.from_dict(json.load(handle))


def save_config(config, path=None):
    if not isinstance(config, BridgeConfig):
        raise ConfigError("config must be a BridgeConfig")
    payload = config.to_dict()
    _validate_config_data(payload)
    path = path or _default_config_path()
    directory = os.path.dirname(path)
    if directory:
        _ensure_private_directory(directory)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".config-", dir=directory or "."
    )
    try:
        _chmod(descriptor, 0o600, descriptor=True)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                payload, handle, ensure_ascii=False, indent=2, sort_keys=True
            )
            handle.write("\n")
        _replace(temporary_path, path)
        _chmod(path, 0o600)
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
    elif isinstance(value, (list, tuple)):
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
    version = value.get("version", 1)
    if isinstance(version, bool) or not isinstance(version, int) or version != 1:
        raise ConfigError("configuration version must be 1")
    notification = value.get("notification", {})
    if not isinstance(notification, dict):
        raise ConfigError("notification must be an object")
    _reject_unknown(notification, _NOTIFICATION_KEYS)
    enabled = notification.get("enabled", False)
    if not isinstance(enabled, bool):
        raise ConfigError("notification enabled must be a boolean")
    if notification.get("failure_policy", "non_blocking") != "non_blocking":
        raise ConfigError("notification failure_policy must be non_blocking")
    ai_summary = notification.get("ai_summary", {
        "provider": "host_agent", "fallback": "deterministic",
    })
    if not isinstance(ai_summary, dict):
        raise ConfigError("notification ai_summary must be an object")
    _reject_secrets(ai_summary)
    _reject_unknown(ai_summary, _AI_SUMMARY_KEYS)
    if set(ai_summary) != _AI_SUMMARY_KEYS:
        raise ConfigError("notification ai_summary fields are required")
    if (ai_summary["provider"] != "host_agent"
            or ai_summary["fallback"] != "deterministic"):
        raise ConfigError("notification ai_summary values are unsupported")
    channels = notification.get("channels", [])
    if not isinstance(channels, list):
        raise ConfigError("notification channels must be a list")
    platforms = []
    for channel in channels:
        _validate_channel_data(channel)
        platforms.append(channel["platform"])
    if len(platforms) != len(set(platforms)):
        raise ConfigError("duplicate channel platform is not allowed")


def _validate_channel_data(value):
    if not isinstance(value, dict):
        raise ConfigError("channel must be an object")
    _reject_secrets(value)
    _reject_unknown(value, _CHANNEL_KEYS)
    platform = value.get("platform")
    if platform not in _PLATFORMS:
        raise ConfigError("channel platform is unsupported")
    provider = value.get("provider", "auto")
    if provider not in _PROVIDERS:
        raise ConfigError("channel provider is unsupported")
    if provider == "dws-cli" and platform != "dingtalk":
        raise ConfigError("dws-cli is supported only for dingtalk")
    profile = value.get("profile")
    if profile is not None:
        _validate_identifier(profile, "channel profile")
    recipients = value.get("recipients", [])
    if not isinstance(recipients, list):
        raise ConfigError("channel recipients must be a list")
    for recipient in recipients:
        _validate_identifier(recipient, "channel recipient")
    if len(recipients) != len(set(recipients)):
        raise ConfigError("duplicate channel recipient is not allowed")
    if recipients and (profile is None or provider == "auto"):
        raise ConfigError(
            "channel recipients require a bound profile and provider"
        )


def _validate_identifier(value, label):
    if (not isinstance(value, str) or not value.strip()
            or any(ord(character) < 32 for character in value)):
        raise ConfigError("{0} must be a non-empty string".format(label))


def _ensure_private_directory(path):
    if not os.path.exists(path):
        os.makedirs(path, mode=0o700)
    _chmod(path, 0o700)


def _chmod(target, mode, descriptor=False):
    try:
        if descriptor and hasattr(os, "fchmod"):
            os.fchmod(target, mode)
        elif not descriptor:
            os.chmod(target, mode)
    except (AttributeError, OSError):
        pass
