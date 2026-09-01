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
    name = "fake"
    priority = 100

    def __init__(self):
        self.auth_result = ProviderResult("authorized")
        self.resolve_result = None
        self.next_result = ProviderResult("sent", data={"external_id": "message-1"})
        self.auth_calls = []
        self.profile_calls = 0
        self.resolve_calls = []
        self.send_calls = []

    def capabilities(self):
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
        return self.next_result


def make_envelope(summary_text="AI summary"):
    return build_envelope(
        STANDARD_MARKDOWN, STANDARD_REPORT, summary_text, "host_agent", "2.4.0"
    )


def make_config(recipients=None, profile="corp:user"):
    return BridgeConfig(
        enabled=True,
        channels=[ChannelConfig(
            "dingtalk", provider="fake", profile=profile,
            recipients=["ops"] if recipients is None else recipients,
        )],
    )


class BridgeServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.ledger = DeliveryLedger(os.path.join(self.directory.name, "ledger.sqlite3"))
        self.provider = FakeProvider()

    def tearDown(self):
        self.directory.cleanup()

    def service(self, config=None):
        return BridgeService(
            config or make_config(), [self.provider], self.ledger
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
        self.assertIs(sent, envelope)
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
            envelope.report_id, "dingtalk", "fake", "corp:user", "ops"
        )
        self.assertEqual(self.ledger.get(key)["state"], "retryable_failure")

    def test_missing_ai_summary_uses_deterministic_fallback(self):
        envelope = make_envelope()
        envelope.ai_summary = None

        self.service().deliver(envelope)

        sent = self.provider.send_calls[0].envelope
        self.assertIn("Wi-Fi", sent.ai_summary["text"])
        self.assertEqual(sent.ai_summary["mode"], "deterministic")
        self.assertIsNone(envelope.ai_summary)

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
            ["delivery_already_claimed", "delivery_already_claimed"],
        )

    def test_missing_profile_binds_without_resolving_or_sending(self):
        result = self.service(make_config(profile=None)).deliver(make_envelope())

        self.assertEqual(result.results[0].status, "ok")
        self.assertEqual(self.provider.profile_calls, 1)
        self.assertEqual(self.provider.resolve_calls, [])
        self.assertEqual(self.provider.send_calls, [])

    def test_unauthorized_channel_returns_status_without_binding_or_sending(self):
        self.provider.auth_result = ProviderResult("action_required", "login_required")

        result = self.service().deliver(make_envelope())

        self.assertEqual(result.results[0].reason, "login_required")
        self.assertEqual(self.provider.profile_calls, 0)
        self.assertEqual(self.provider.resolve_calls, [])
        self.assertEqual(self.provider.send_calls, [])


if __name__ == "__main__":
    unittest.main()
