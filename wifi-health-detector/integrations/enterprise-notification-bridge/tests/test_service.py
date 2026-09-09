from __future__ import absolute_import

import copy
import json
import os
import sys
import tempfile
import unittest
from collections import namedtuple


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.config import BridgeConfig, ChannelConfig
from notification_bridge.continuation import MemoryStateStore
from notification_bridge.contract import build_envelope
from notification_bridge.ledger import DeliveryKey, DeliveryLedger
from notification_bridge.providers.base import Provider, ProviderResult
from notification_bridge.service import BridgeService, deterministic_summary


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
with open(os.path.join(FIXTURES, "standard-report.md"), "r") as handle:
    STANDARD_MARKDOWN = handle.read()
with open(os.path.join(FIXTURES, "standard-report.json"), "r") as handle:
    STANDARD_REPORT = json.load(handle)


SendCall = namedtuple("SendCall", "profile recipient envelope")


class FakeProvider(Provider):
    availability = "available"
    platform = "dingtalk"
    name = "dws-cli"
    priority = 100

    def __init__(self, name=None):
        if name is not None:
            self.name = name
        self.auth_result = ProviderResult("authorized")
        self.resolve_result = None
        self.next_result = ProviderResult("sent", data={"external_id": "message-1"})
        self.send_error = None
        self.capabilities_calls = 0
        self.auth_calls = []
        self.profile_calls = 0
        self.resolve_calls = []
        self.send_calls = []

    def capabilities(self):
        self.capabilities_calls += 1
        return {"available": True}

    def auth_status(self, profile=None):
        self.auth_calls.append(profile)
        return self.auth_result

    def list_profiles(self):
        self.profile_calls += 1
        return ProviderResult("ok", data={"profile": "corp:user"})

    def resolve_recipient(self, profile, selector):
        self.resolve_calls.append((profile, selector))
        if self.resolve_result is not None:
            return self.resolve_result
        return ProviderResult("resolved", data={"recipient": selector})

    def send_report(self, profile, recipient, envelope):
        self.send_calls.append(SendCall(profile, recipient, envelope))
        if self.send_error is not None:
            raise self.send_error
        return self.next_result


def make_envelope(summary_text="AI summary"):
    return build_envelope(
        STANDARD_MARKDOWN, STANDARD_REPORT, summary_text, "host_agent", "2.4.0"
    )


def make_config(recipients=None, profile="corp:user"):
    if recipients is None:
        recipients = [] if profile is None else ["ops"]
    return BridgeConfig(
        enabled=True,
        channels=[ChannelConfig(
            "dingtalk", provider="dws-cli", profile=profile,
            recipients=recipients,
        )],
    )


class BridgeServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.ledger = DeliveryLedger(os.path.join(self.directory.name, "ledger.sqlite3"))
        self.provider = FakeProvider()
        self.state_store = MemoryStateStore()

    def tearDown(self):
        self.directory.cleanup()

    def service(self, config=None):
        config = config or make_config()
        for channel in config.channels:
            if channel.profile is not None and channel.recipients:
                self.state_store.confirm({
                    "platform": channel.platform,
                    "provider": channel.provider,
                    "profile": channel.profile,
                    "recipients": list(channel.recipients),
                })
        return BridgeService(
            config, [self.provider], self.ledger,
            state_store=self.state_store,
        )

    def test_no_recipient_skips_without_calling_send(self):
        result = self.service(make_config(recipients=[])).deliver(make_envelope())

        self.assertEqual(result.results[0].reason, "recipient_not_configured")
        self.assertEqual(self.provider.resolve_calls, [])
        self.assertEqual(self.provider.send_calls, [])

    def test_host_summary_and_complete_report_are_preserved(self):
        envelope = make_envelope()

        self.service().deliver(envelope)

        sent = self.provider.send_calls[0].envelope
        self.assertIsNot(sent, envelope)
        self.assertEqual(sent.ai_summary["text"], "AI summary")
        self.assertEqual(sent.report["markdown"], STANDARD_MARKDOWN)
        self.assertEqual(sent.report["json"], STANDARD_REPORT)

    def test_failed_send_is_non_blocking_and_retryable(self):
        envelope = make_envelope()
        self.provider.next_result = ProviderResult("failed", "timeout", retryable=True)

        result = self.service().deliver(envelope)

        self.assertEqual(result.status, "notification_failed")
        self.assertTrue(result.results[0].retryable)
        key = DeliveryKey(
            envelope.report_id, "dingtalk", "dws-cli", "corp:user", "ops"
        )
        self.assertEqual(self.ledger.get(key)["state"], "retryable_failure")

    def test_envelope_summary_cannot_be_replaced_after_construction(self):
        envelope = make_envelope()

        with self.assertRaises(AttributeError):
            envelope.ai_summary = {"mode": "deterministic", "text": ""}

    def test_deterministic_summary_uses_only_report_diagnosis_content(self):
        report = copy.deepcopy(STANDARD_REPORT)
        report["diagnosis"].update({
            "verdict": "warning",
            "score": 63,
            "issues": ["weak_signal"],
            "recommendations": [{
                "id": "weak_signal",
                "priority": "high",
                "reason": "RSSI -78 dBm",
                "action": "Move closer.",
            }],
        })

        summary = deterministic_summary(report)

        self.assertEqual(
            summary,
            "Wi-Fi health status: warning. Score: 63. "
            "Issues: weak_signal. Recommendations: Move closer.",
        )
        self.assertNotIn("interference", summary)
        self.assertNotIn("router", summary)

    def test_each_resolved_recipient_has_an_independent_ledger_claim(self):
        envelope = make_envelope()
        config = make_config(recipients=["ops", "network"])

        first = self.service(config).deliver(envelope)
        second = self.service(config).deliver(envelope)

        self.assertEqual(first.status, "delivered")
        self.assertEqual(len(self.provider.send_calls), 2)
        self.assertEqual([call.recipient for call in self.provider.send_calls], [
            "ops", "network",
        ])
        self.assertEqual(
            [item.reason for item in second.results],
            ["delivery_already_succeeded", "delivery_already_succeeded"],
        )

    def test_missing_profile_binds_without_resolving_or_sending(self):
        result = self.service(make_config(profile=None)).deliver(make_envelope())

        self.assertEqual(result.results[0].reason, "recipient_not_configured")
        self.assertEqual(self.provider.profile_calls, 1)
        self.assertEqual(self.provider.resolve_calls, [])
        self.assertEqual(self.provider.send_calls, [])

    def test_unauthorized_channel_returns_status_without_binding_or_sending(self):
        self.provider.auth_result = ProviderResult("action_required", "login_required")

        result = self.service().deliver(make_envelope())

        self.assertEqual(result.results[0].reason, "auth_status_required")
        self.assertEqual(
            result.results[0].data["action"]["operation"], "auth_status"
        )
        self.assertEqual(self.provider.profile_calls, 0)
        self.assertEqual(self.provider.resolve_calls, [])
        self.assertEqual(self.provider.send_calls, [])

    def test_authenticated_dws_result_reaches_recipient_and_send_path(self):
        self.provider.auth_result = ProviderResult(
            "ok", data={"authenticated": True}
        )

        result = self.service().deliver(make_envelope())

        self.assertEqual(result.status, "delivered")
        self.assertEqual(self.provider.resolve_calls, [("corp:user", "ops")])
        self.assertEqual(len(self.provider.send_calls), 1)

    def test_raising_send_is_retryable_and_same_key_can_be_reclaimed(self):
        envelope = make_envelope()
        self.provider.send_error = RuntimeError("provider unavailable")

        failed = self.service().deliver(envelope)

        key = DeliveryKey(
            envelope.report_id, "dingtalk", "dws-cli", "corp:user", "ops"
        )
        failed_row = self.ledger.get(key)
        self.assertEqual(failed.status, "notification_failed")
        self.assertEqual(failed.results[0].reason, "provider_send_failed")
        self.assertTrue(failed.results[0].retryable)
        self.assertEqual(failed_row["state"], "retryable_failure")

        self.provider.send_error = None
        retried = self.service().deliver(envelope)

        succeeded_row = self.ledger.get(key)
        self.assertEqual(retried.status, "delivered")
        self.assertEqual(succeeded_row["state"], "succeeded")
        self.assertNotEqual(failed_row["claim_id"], succeeded_row["claim_id"])
        self.assertEqual(len(self.provider.send_calls), 2)

    def test_missing_profile_binds_with_the_already_selected_provider(self):
        selected = FakeProvider("native")
        alternative = FakeProvider("dws-cli")
        alternative.priority = 10
        config = BridgeConfig(
            enabled=True,
            channels=[ChannelConfig(
                "dingtalk", provider="native", profile=None, recipients=[]
            )],
        )
        service = BridgeService(config, [selected, alternative], self.ledger)

        result = service.deliver(make_envelope())

        self.assertEqual(result.results[0].reason, "recipient_not_configured")
        self.assertEqual(config.channels[0].profile, "corp:user")
        self.assertEqual(config.channels[0].provider, "native")
        self.assertEqual(selected.profile_calls, 1)
        self.assertEqual(alternative.profile_calls, 0)
        self.assertEqual(selected.capabilities_calls, 1)
        self.assertEqual(alternative.capabilities_calls, 1)


if __name__ == "__main__":
    unittest.main()
