from __future__ import absolute_import

try:
    from collections.abc import Mapping
except ImportError:  # pragma: no cover - Python 3.7 compatibility
    from collections import Mapping

from .base import Provider, ProviderResult


class NativeProvider(Provider):
    """Host-agent handshake provider.

    Native integrations are described by the host.  This adapter only returns
    semantic operation requests and validates results returned by that host;
    it never guesses or invokes an agent-specific tool.
    """

    name = "native"
    priority = 100

    def __init__(self, platform, descriptor):
        self.platform = platform
        self._descriptor = descriptor
        self._operations = _operations_for(platform, descriptor)

    def capabilities(self):
        if self._operations is None:
            return {"available": False}
        return {"available": True, "operations": list(self._operations)}

    def auth_status(self, profile=None):
        data = {}
        if profile is not None:
            data["profile"] = profile
        return self._request("auth_status", data)

    def login(self):
        return self._request("login", {})

    def list_profiles(self):
        return self._request("list_profiles", {})

    def resolve_recipient(self, profile, selector):
        return self._request("resolve_recipient", {
            "profile": profile,
            "selector": selector,
        })

    def send_report(self, profile, recipient, envelope):
        return self._request("send_report", {
            "profile": profile,
            "recipient": recipient,
            "envelope": envelope,
        })

    def resume(self, operation_result):
        """Accept a result only when it matches this host-advertised provider."""
        if not isinstance(operation_result, Mapping):
            return ProviderResult("unavailable", "native_operation_result_invalid")
        if (operation_result.get("platform") != self.platform
                or operation_result.get("provider") != self.name):
            return ProviderResult("unavailable", "native_operation_result_invalid")
        operation = operation_result.get("operation")
        if self._operations is None or operation not in self._operations:
            return ProviderResult("unavailable", "native_operation_unavailable")
        status = operation_result.get("status")
        if not isinstance(status, str):
            return ProviderResult("unavailable", "native_operation_result_invalid")
        data = operation_result.get("data", {})
        if not isinstance(data, Mapping):
            return ProviderResult("unavailable", "native_operation_result_invalid")
        reason = operation_result.get("reason", "")
        if not isinstance(reason, str):
            return ProviderResult("unavailable", "native_operation_result_invalid")
        return ProviderResult(
            status, reason, operation_result.get("retryable", False), data=dict(data)
        )

    def _request(self, operation, data):
        if self._operations is None or operation not in self._operations:
            return ProviderResult("unavailable", "native_operation_unavailable")
        request = {
            "platform": self.platform,
            "provider": self.name,
            "operation": operation,
        }
        request.update(data)
        return ProviderResult("action_required", "native_operation_required", data=request)


def _operations_for(platform, descriptor):
    if not isinstance(descriptor, Mapping):
        return None
    if descriptor.get("platform") != platform or descriptor.get("provider") != "native":
        return None
    operations = descriptor.get("operations")
    if not isinstance(operations, list) or not all(isinstance(item, str) for item in operations):
        return None
    return tuple(operations)
