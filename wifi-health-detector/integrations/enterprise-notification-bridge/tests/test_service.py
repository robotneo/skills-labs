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

    def __init__(self, name=None, platform=None):
        if name is not None:
            self.name = name
        if platform is not None:
            self.platform = platform
        self.auth_result = ProviderResult("authorized")
        self.resolve_result = None
        self.next_result = ProviderResult("sent", data={"external_id": "message-1"})
        self.send_error = None
        self.available = True
        self.profile_result = ProviderResult("ok", data={"profile": "corp:user"})
        # Optional selector -> ProviderResult routing for the auto path.
        self.resolve_routes = None
        self.dry_run_calls = []
        self.capabilities_calls = 0
        self.auth_calls = []
        self.profile_calls = 0
        self.resolve_calls = []
        self.send_calls = []

    def capabilities(self):
        self.capabilities_calls += 1
        return {"available": self.available}

    def auth_status(self, profile=None):
        self.auth_calls.append(profile)
        return self.auth_result

    def list_profiles(self):
        self.profile_calls += 1
        return self.profile_result

    def resolve_recipient(self, profile, selector):
        self.resolve_calls.append((profile, selector))
        if self.resolve_routes is not None:
            routed = self.resolve_routes.get(selector)
            return routed if routed is not None else ProviderResult(
                "failed", "recipient_not_found", retryable=False
            )
        if self.resolve_result is not None:
            return self.resolve_result
        return ProviderResult("resolved", data={"recipient": selector})

    def send_report(self, profile, recipient, envelope, dry_run=False):
        self.send_calls.append(SendCall(profile, recipient, envelope))
        if dry_run:
            self.dry_run_calls.append(SendCall(profile, recipient, envelope))
        if self.send_error is not None:
            raise self.send_error
        return self.next_result


def make_envelope(summary_text="AI summary"):
    return build_envelope(
        STANDARD_MARKDOWN, STANDARD_REPORT, summary_text, "host_agent", "2.4.0"
    )


class _Dependency(object):
    def __init__(self, status, reason, executable="/verified/bin/dws"):
        self.status = status
        self.reason = reason
        self.executable = executable


class ReadyDependency(object):
    def discoverer(self, environment, platform, which, minimum_version=None):
        return _Dependency("discovered", "dependency_discovered")

    def verifier(self, executable, runner, minimum_version=None):
        return _Dependency("ready", "dependency_ready", executable)


class DependencyFixture(ReadyDependency):
    def __init__(self, status, reason):
        self.status = status
        self.reason = reason

    def discoverer(self, environment, platform, which, minimum_version=None):
        return _Dependency(self.status, self.reason,
                           executable="/verified/bin/dws")

    def verifier(self, executable, runner, minimum_version=None):
        return _Dependency(self.status, self.reason, executable)


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


class DeliverAutoTests(unittest.TestCase):
    """Default DingTalk auto-delivery with recipient fallback to 杨华."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.ledger = DeliveryLedger(
            os.path.join(self.directory.name, "ledger.sqlite3")
        )
        self.provider = FakeProvider()
        self.state_store = MemoryStateStore()

    def tearDown(self):
        self.directory.cleanup()

    def service(self, provider=None, dependency=None):
        # The auto path is independent of persisted channel configuration.
        config = BridgeConfig(enabled=True, channels=[])
        dependency = dependency if dependency is not None else ReadyDependency()
        return BridgeService(
            config, [provider or self.provider], self.ledger,
            state_store=self.state_store,
            dependency_discoverer=dependency.discoverer,
            dependency_verifier=dependency.verifier,
            environment={"DWS_EXE": "/verified/bin/dws"},
            platform_name="darwin",
            which=lambda name: "/verified/bin/dws" if name == "dws" else None,
        )

    def test_without_dws_dependency_auto_delivery_is_disabled(self):
        dependency = DependencyFixture("action_required",
                                       "dependency_install_required")

        result = self.service(dependency=dependency).deliver_auto(make_envelope())

        self.assertEqual(result.results[0].status, "skipped")
        self.assertEqual(result.results[0].reason, "notification_disabled")
        self.assertEqual(self.provider.send_calls, [])
        self.assertEqual(self.provider.auth_calls, [])

    def test_below_floor_dws_returns_upgrade_required_without_sending(self):
        dependency = DependencyFixture("action_required",
                                       "dws_upgrade_required")

        result = self.service(dependency=dependency).deliver_auto(make_envelope())

        self.assertEqual(result.results[0].status, "skipped")
        self.assertEqual(result.results[0].reason, "dws_upgrade_required")
        self.assertEqual(self.provider.send_calls, [])
        self.assertEqual(self.provider.auth_calls, [])

    def test_explicit_unique_recipient_overrides_default(self):
        envelope = make_envelope()
        self.provider.resolve_routes = {
            "王芳": ProviderResult("resolved", data={"recipient": "王芳"}),
        }

        result = self.service().deliver_auto(envelope, requested_recipient="王芳")

        self.assertEqual(result.status, "delivered")
        self.assertEqual(result.results[0].status, "sent")
        self.assertEqual(
            self.provider.resolve_calls, [("corp:user", "王芳")]
        )
        self.assertEqual(self.provider.send_calls[0].recipient, "王芳")

    def test_unknown_recipient_falls_back_to_default_yanghua(self):
        envelope = make_envelope()
        self.provider.resolve_routes = {
            "钱七": ProviderResult(
                "failed", "recipient_not_found", retryable=False
            ),
            "杨华": ProviderResult("resolved", data={"recipient": "杨华"}),
        }

        result = self.service().deliver_auto(envelope, requested_recipient="钱七")

        self.assertEqual(result.status, "delivered")
        self.assertEqual(self.provider.send_calls[0].recipient, "杨华")
        self.assertEqual(
            [selector for _, selector in self.provider.resolve_calls],
            ["钱七", "杨华"],
        )

    def test_ambiguous_recipient_falls_back_without_picking_candidate(self):
        envelope = make_envelope()
        self.provider.resolve_routes = {
            "李娜": ProviderResult(
                "failed", "recipient_ambiguous", retryable=False
            ),
            "杨华": ProviderResult("resolved", data={"recipient": "杨华"}),
        }

        result = self.service().deliver_auto(envelope, requested_recipient="李娜")

        self.assertEqual(result.status, "delivered")
        self.assertEqual(self.provider.send_calls[0].recipient, "杨华")

    def test_no_requested_recipient_sends_to_default(self):
        envelope = make_envelope()
        self.provider.resolve_routes = {
            "杨华": ProviderResult("resolved", data={"recipient": "杨华"}),
        }

        result = self.service().deliver_auto(envelope)

        self.assertEqual(result.status, "delivered")
        self.assertEqual(self.provider.send_calls[0].recipient, "杨华")
        self.assertEqual(
            self.provider.resolve_calls, [("corp:user", "杨华")]
        )

    def test_identifier_like_recipient_is_ignored_and_uses_default(self):
        envelope = make_envelope()
        self.provider.resolve_routes = {
            "杨华": ProviderResult("resolved", data={"recipient": "杨华"}),
        }

        result = self.service().deliver_auto(
            envelope,
            requested_recipient="dingc96cdb4c99a85452:2014540426841958",
        )

        self.assertEqual(result.status, "delivered")
        self.assertEqual(self.provider.send_calls[0].recipient, "杨华")
        self.assertEqual(
            [selector for _, selector in self.provider.resolve_calls],
            ["杨华"],
        )

    def test_multiple_profiles_skip_without_sending(self):
        self.provider.profile_result = ProviderResult(
            "action_required", "profile_selection_required",
            data={"profiles": [{"profile": "a:u"}, {"profile": "b:u"}]},
        )

        result = self.service().deliver_auto(make_envelope())

        self.assertEqual(result.results[0].status, "skipped")
        self.assertEqual(result.results[0].reason, "profile_selection_required")
        self.assertEqual(self.provider.send_calls, [])

    def test_unauthorized_skips_without_sending(self):
        self.provider.auth_result = ProviderResult(
            "ok", data={"authenticated": False}
        )

        result = self.service().deliver_auto(make_envelope())

        self.assertEqual(result.results[0].status, "skipped")
        self.assertEqual(result.results[0].reason, "login_required")
        self.assertEqual(self.provider.send_calls, [])

    def test_no_dingtalk_dws_provider_skips(self):
        other = FakeProvider(name="native", platform="feishu")

        result = self.service(other).deliver_auto(make_envelope())

        self.assertEqual(result.results[0].status, "skipped")
        self.assertEqual(result.results[0].reason, "provider_unavailable")
        self.assertEqual(other.send_calls, [])

    def test_duplicate_delivery_is_claimed_once(self):
        envelope = make_envelope()
        self.provider.resolve_routes = {
            "杨华": ProviderResult("resolved", data={"recipient": "杨华"}),
        }
        service = self.service()

        first = service.deliver_auto(envelope)
        second = service.deliver_auto(envelope)

        self.assertEqual(first.status, "delivered")
        self.assertEqual(len(self.provider.send_calls), 1)
        self.assertEqual(
            second.results[0].reason, "delivery_already_succeeded"
        )

    def test_dry_run_does_not_mark_success_and_can_send_afterward(self):
        envelope = make_envelope()
        self.provider.resolve_routes = {
            "杨华": ProviderResult("resolved", data={"recipient": "杨华"}),
        }
        self.provider.next_result = ProviderResult(
            "ok", "dry_run", data={"dry_run": True}
        )
        service = self.service()

        preview = service.deliver_auto(envelope, dry_run=True)
        self.assertEqual(preview.results[0].reason, "dry_run")
        self.assertEqual(len(self.provider.dry_run_calls), 1)

        # A real send is still allowed because dry-run never claimed success.
        self.provider.next_result = ProviderResult(
            "sent", data={"external_id": "m-9"}
        )
        delivered = service.deliver_auto(envelope)

        self.assertEqual(delivered.status, "delivered")
        self.assertEqual(len(self.provider.send_calls), 2)
        key = DeliveryKey(
            envelope.report_id, "dingtalk", "dws-cli", "corp:user", "杨华"
        )
        self.assertEqual(self.ledger.get(key)["state"], "succeeded")


if __name__ == "__main__":
    unittest.main()