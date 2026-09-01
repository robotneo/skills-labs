from __future__ import absolute_import

try:
    from collections.abc import Mapping
except ImportError:  # pragma: no cover - Python 3.7 compatibility
    from collections import Mapping

from .base import Provider, ProviderResult
from ..continuation import (
    ContinuationError, validate_capability_list, validate_operation_result,
)


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
        try:
            validated = validate_capability_list([descriptor])[0]
        except ContinuationError:
            validated = None
        self._operations = _operations_for(platform, validated)

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
        envelope_value = envelope.to_dict() if hasattr(envelope, "to_dict") else envelope
        return self._request("send_report", {
            "profile": profile,
            "recipient": recipient,
            "envelope": envelope_value,
        })

    def delivery_status(self, profile, recipient, claim_id):
        return self._request("delivery_status", {
            "profile": profile, "recipient": recipient, "claim_id": claim_id,
        })

    def resume(self, expected_action, operation_result):
        """Validate exact action correlation before accepting a host result."""
        operation = (expected_action.get("operation")
                     if isinstance(expected_action, Mapping) else None)
        if self._operations is None or operation not in self._operations:
            return ProviderResult("unavailable", "native_operation_unavailable")
        if (expected_action.get("platform") != self.platform
                or expected_action.get("provider") != self.name):
            return ProviderResult("unavailable", "native_operation_result_invalid")
        try:
            result = validate_operation_result(
                dict(operation_result), dict(expected_action)
            )
        except (ContinuationError, TypeError, ValueError):
            return ProviderResult("unavailable", "native_operation_result_invalid")
        if result["status"] == "succeeded":
            return ProviderResult("ok", data=result["data"])
        status = "failed" if result["status"] == "failed" else "unavailable"
        reason = result["reason"] or "native_operation_{0}".format(
            result["status"]
        )
        return ProviderResult(
            status, reason, result["retryable"], data=result["data"]
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
    if (descriptor.get("schema_version") != "1"
            or descriptor.get("platform") != platform
            or descriptor.get("provider") != "native"):
        return None
    operations = descriptor.get("operations")
    if not isinstance(operations, list) or not all(isinstance(item, str) for item in operations):
        return None
    return tuple(operations)
