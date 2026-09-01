from __future__ import absolute_import

from .providers.base import UnavailableProvider


def select_provider(platform, configured_name, providers):
    candidates = [
        item for item in providers
        if item.platform == platform and item.capabilities().get("available")
    ]
    if configured_name != "auto":
        matches = [item for item in candidates if item.name == configured_name]
        if len(matches) != 1:
            return UnavailableProvider(platform, "configured_provider_unavailable")
        return matches[0]
    if not candidates:
        return UnavailableProvider(platform, "provider_unavailable")
    return sorted(candidates, key=lambda item: (-item.priority, item.name))[0]
