from __future__ import absolute_import

from collections import OrderedDict


SECTION_FIELDS = OrderedDict([
    ("system", ("os", "os_version", "build", "architecture", "checked_at", "privilege", "python_version")),
    ("adapter", ("interface", "description", "status", "mac", "driver", "firmware", "country_code", "supported_phy", "current_phy")),
    ("connection", ("ssid", "bssid", "state", "security", "authentication", "cipher", "band", "channel", "center_channel", "channel_width")),
    ("radio", ("rssi", "noise", "snr", "signal_percent", "signal_level", "same_channel_networks", "adjacent_channel_networks")),
    ("link", ("tx_rate", "rx_rate", "max_rate", "mcs", "nss", "guard_interval")),
    ("ip", ("ipv4", "ipv6", "subnet", "gateway", "dns_servers", "dhcp_enabled", "dhcp_lease")),
    ("local_quality", ("target", "reachable", "latency", "jitter", "packet_loss")),
    ("public_quality", ("target", "reachable", "dns_latency", "latency", "jitter", "packet_loss", "download_speed")),
])


class Field(object):
    def __init__(self, value=None, unit="", availability="available", source="", reason=""):
        self.value = value
        self.unit = unit
        self.availability = availability
        self.source = source
        self.reason = reason

    @property
    def available(self):
        return self.availability == "available" and self.value is not None

    def to_dict(self):
        return OrderedDict([
            ("value", self.value),
            ("unit", self.unit),
            ("availability", self.availability),
            ("source", self.source),
            ("reason", self.reason),
        ])


def unavailable(reason="not provided by operating system", source=""):
    return Field(None, availability="unavailable", source=source, reason=reason)


def field(value, unit="", source="", reason=""):
    if value is None or value == "":
        return unavailable(reason or "not found", source)
    return Field(value, unit=unit, source=source)


class Report(object):
    schema_version = "2.0"

    def __init__(self, sections=None, diagnosis=None, warnings=None):
        self.sections = sections or OrderedDict()
        self.diagnosis = diagnosis or {}
        self.warnings = warnings or []

    @classmethod
    def empty(cls):
        sections = OrderedDict()
        for section, names in SECTION_FIELDS.items():
            sections[section] = OrderedDict((name, unavailable()) for name in names)
        return cls(sections=sections)

    def set(self, section, name, value, unit="", source="", reason=""):
        self.sections[section][name] = field(value, unit, source, reason)

    def mark_unavailable(self, section, name, reason, source=""):
        self.sections[section][name] = unavailable(reason, source)

    def get(self, section, name):
        return self.sections[section][name]

    def to_dict(self):
        return OrderedDict([
            ("schema_version", self.schema_version),
            ("sections", OrderedDict(
                (section, OrderedDict((name, item.to_dict()) for name, item in values.items()))
                for section, values in self.sections.items()
            )),
            ("diagnosis", self.diagnosis),
            ("warnings", list(self.warnings)),
        ])
