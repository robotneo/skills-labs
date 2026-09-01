from __future__ import absolute_import


class Provider(object):
    platform = None
    name = None
    priority = 0

    def capabilities(self):
        raise NotImplementedError

    def auth_status(self, profile=None):
        raise NotImplementedError

    def login(self):
        raise NotImplementedError

    def list_profiles(self):
        raise NotImplementedError

    def resolve_recipient(self, profile, selector):
        raise NotImplementedError

    def send_report(self, profile, recipient, envelope):
        raise NotImplementedError


class ProviderResult(object):
    def __init__(self, status, reason="", retryable=False, data=None):
        self.status = status
        self.reason = reason
        self.retryable = bool(retryable)
        self.data = data or {}


class UnavailableProvider(Provider):
    availability = "unavailable"
    name = "unavailable"

    def __init__(self, platform, reason):
        self.platform = platform
        self.reason = reason

    def capabilities(self):
        return {"available": False}
