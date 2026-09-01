from __future__ import absolute_import

import copy
from collections.abc import Mapping

from .contract import validate_envelope
from .ledger import DeliveryKey
from .providers.base import ProviderResult
from .selector import select_provider


class DeliveryBatchResult(object):
    def __init__(self, results):
        self.results = list(results)
        self.status = self._status()

    def _status(self):
        if not self.results:
            return "notification_disabled"
        if any(result.status == "failed" for result in self.results):
            return "notification_failed"
        if any(result.status in ("sent", "delivered", "succeeded", "success")
               for result in self.results):
            return "delivered"
        reasons = [result.reason for result in self.results if result.reason]
        if reasons and all(reason == reasons[0] for reason in reasons):
            return reasons[0]
        if any(result.status == "action_required" for result in self.results):
            return "action_required"
        return self.results[0].status


class BridgeService(object):
    def __init__(self, config, providers, ledger):
        self.config = config
        self.providers = list(providers)
        self.ledger = ledger

    def deliver(self, envelope):
        validate_envelope(envelope)
        results = []
        for channel in self.config.enabled_channels():
            provider = select_provider(
                channel.platform, channel.provider, self.providers
            )
            if getattr(provider, "availability", "available") == "unavailable":
                results.append(ProviderResult("skipped", provider.reason))
                continue
            auth = provider.auth_status(channel.profile)
            if auth.status != "authorized":
                results.append(auth)
                continue
            if not channel.profile:
                results.append(self.bind(channel.platform))
                continue
            if not channel.recipients:
                results.append(ProviderResult("skipped", "recipient_not_configured"))
                continue
            for selector in channel.recipients:
                results.append(self._deliver_one(
                    provider, channel.profile, selector, envelope
                ))
        return DeliveryBatchResult(results)

    def bind(self, platform):
        channels = [
            channel for channel in self.config.enabled_channels()
            if channel.platform == platform
        ]
        if not channels:
            return ProviderResult("skipped", "platform_not_configured")
        channel = channels[0]
        provider = select_provider(
            channel.platform, channel.provider, self.providers
        )
        if getattr(provider, "availability", "available") == "unavailable":
            return ProviderResult("skipped", provider.reason)
        return provider.list_profiles()

    def _deliver_one(self, provider, profile, selector, envelope):
        resolved = provider.resolve_recipient(profile, selector)
        if resolved.status not in ("ok", "resolved"):
            return resolved
        recipient = resolved.data.get("recipient")
        if not isinstance(recipient, str) or not recipient:
            return ProviderResult("skipped", "recipient_not_resolved")

        key = DeliveryKey(
            envelope.report_id, provider.platform, provider.name,
            profile, recipient,
        )
        claim = self.ledger.claim(key)
        if not claim.acquired:
            return ProviderResult("skipped", "delivery_already_claimed")

        result = provider.send_report(
            profile, recipient, _with_summary(envelope)
        )
        if result.status in (
                "ok", "sent", "delivered", "succeeded", "success"):
            self.ledger.mark_success(
                claim, result.data.get("external_id", "")
            )
        else:
            retryable = result.retryable or result.status == "action_required"
            self.ledger.mark_failure(claim, result.reason, retryable)
        return result


def deterministic_summary(report_json):
    diagnosis = report_json.get("diagnosis", {})
    parts = []

    verdict = diagnosis.get("verdict")
    if verdict is not None:
        parts.append("Wi-Fi health status: {0}.".format(verdict))

    score = diagnosis.get("score")
    if score is not None:
        parts.append("Score: {0}.".format(score))

    issues = [_summary_value(item) for item in diagnosis.get("issues", [])]
    issues = [item for item in issues if item]
    if issues:
        parts.append("Issues: {0}.".format(", ".join(issues)))

    recommendations = [
        _recommendation_value(item)
        for item in diagnosis.get("recommendations", [])
    ]
    recommendations = [item for item in recommendations if item]
    if recommendations:
        recommendation_text = "; ".join(recommendations)
        suffix = "" if recommendation_text.endswith((".", "!", "?")) else "."
        parts.append("Recommendations: {0}{1}".format(
            recommendation_text, suffix
        ))

    return " ".join(parts)


def _with_summary(envelope):
    summary = getattr(envelope, "ai_summary", None)
    if (isinstance(summary, Mapping)
            and isinstance(summary.get("text"), str)
            and summary.get("text").strip()):
        return envelope
    prepared = copy.deepcopy(envelope)
    prepared.ai_summary = {
        "mode": "deterministic",
        "text": deterministic_summary(prepared.report["json"]),
    }
    return prepared


def _summary_value(value):
    if isinstance(value, str):
        return value
    return "" if value is None else str(value)


def _recommendation_value(value):
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return "" if value is None else str(value)
    for key in ("action", "recommendation", "text", "id"):
        item = value.get(key)
        if isinstance(item, str) and item:
            return item
    return ""
