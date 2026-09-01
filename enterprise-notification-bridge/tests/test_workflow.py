from __future__ import absolute_import

from datetime import datetime, timedelta, timezone
import json
import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.config import (
    BridgeConfig, ChannelConfig, ConfigError, load_config, save_config,
)
from notification_bridge.continuation import ContinuationError, PendingStateStore
from notification_bridge.contract import build_envelope
from notification_bridge.ledger import DeliveryKey, DeliveryLedger
from notification_bridge.providers.base import Provider, ProviderResult
from notification_bridge.providers.dws import DwsProvider
from notification_bridge.service import BridgeService


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
with open(os.path.join(FIXTURES, "standard-report.md"), "r", encoding="utf-8") as handle:
    STANDARD_MARKDOWN = handle.read()
with open(os.path.join(FIXTURES, "standard-report.json"), "r", encoding="utf-8") as handle:
    STANDARD_REPORT = json.load(handle)


def make_envelope(summary="AI summary"):
    return build_envelope(
        STANDARD_MARKDOWN, STANDARD_REPORT, summary,
        "host_agent" if summary else "deterministic", "2.5.0",
    )


def capability_bundle(platform="feishu"):
    return {
        "schema_version": "1",
        "capabilities": [{
            "schema_version": "1", "platform": platform,
            "provider": "native",
            "operations": [
                "auth_status", "login", "list_profiles",
                "resolve_recipient", "send_report", "delivery_status",
            ],
        }],
    }


def action_from(result):
    actions = [item.data.get("action") for item in result.results
               if item.status == "action_required"]
    if not actions:
        raise AssertionError("result did not contain an action")
    return actions[-1]


def success(action, data):
    return {
        "schema_version": "1",
        "action_id": action["action_id"],
        "report_id": action["report_id"],
        "platform": action["platform"],
        "provider": action["provider"],
        "operation": action["operation"],
        "status": "succeeded",
        "reason": "",
        "retryable": False,
        "data": data,
    }


class SynchronousProvider(Provider):
    availability = "available"
    platform = "dingtalk"
    name = "native"
    priority = 100

    def __init__(self):
        self.send_results = [ProviderResult("sent", data={"external_id": "message"})]
        self.sent = []

    def capabilities(self):
        return {"available": True, "operations": [
            "auth_status", "login", "list_profiles", "resolve_recipient",
            "send_report", "delivery_status",
        ]}

    def auth_status(self, profile=None):
        return ProviderResult("authorized")

    def login(self):
        return ProviderResult("authorized")

    def list_profiles(self):
        return ProviderResult("ok", data={
            "profiles": [{"profile": "corp:user"}],
        })

    def resolve_recipient(self, profile, selector):
        return ProviderResult("resolved", data={"recipient": "resolved:" + selector})

    def send_report(self, profile, recipient, envelope):
        self.sent.append((profile, recipient, envelope))
        return self.send_results.pop(0)

    def delivery_status(self, profile, recipient, claim_id):
        return ProviderResult("unavailable", "delivery_status_unavailable")


class RecordingDwsProvider(SynchronousProvider):
    name = "dws-cli"
    priority = 10


class DwsCommandResult(object):
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


class AuthorizedDwsRunner(object):
    def run(self, command):
        values = tuple(command)
        if values == ("dws", "--help"):
            return DwsCommandResult("DWS help")
        if values in (
                ("dws", "auth", "status", "--help"),
                ("dws", "profile", "list", "--help")):
            return DwsCommandResult("--format json")
        if values == ("dws", "auth", "status", "--format", "json"):
            return DwsCommandResult('{"authenticated":true}')
        if values == ("dws", "profile", "list", "--format", "json"):
            return DwsCommandResult(
                '{"profiles":[{"profile":"corp:user"}]}'
            )
        return DwsCommandResult("", 1)


class NativeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.directory.name, "config.json")
        self.ledger_path = os.path.join(self.directory.name, "ledger.sqlite3")
        self.state_path = os.path.join(self.directory.name, "state")

    def tearDown(self):
        self.directory.cleanup()

    def service(self, providers=None, ledger=None):
        config = load_config(self.config_path)
        return BridgeService(
            config, providers or [], ledger or DeliveryLedger(self.ledger_path),
            state_store=PendingStateStore(self.state_path),
            persist_config=lambda: save_config(config, self.config_path),
        )

    def test_native_authorization_binding_confirmation_and_send_resume_end_to_end(self):
        save_config(BridgeConfig(
            enabled=True,
            channels=[ChannelConfig("feishu", provider="auto")],
        ), self.config_path)
        capabilities = capability_bundle("feishu")
        service = self.service()

        action = action_from(service.deliver(make_envelope(), capabilities))
        self.assertEqual(action["operation"], "auth_status")
        action = action_from(service.continue_operation(success(
            action, {"authorization": "missing"}
        )))
        self.assertEqual(action["operation"], "login")
        action = action_from(service.continue_operation(success(action, {})))
        self.assertEqual(action["operation"], "auth_status")
        action = action_from(service.continue_operation(success(
            action, {"authorization": "authorized"}
        )))
        self.assertEqual(action["operation"], "list_profiles")
        action = action_from(service.continue_operation(success(action, {
            "profiles": [
                {"profile": "tenant:alpha", "display_name": "Alpha"},
                {"profile": "tenant:beta", "display_name": "Beta"},
            ],
        })))
        self.assertEqual(action["operation"], "select_profile")
        with self.assertRaises(ContinuationError):
            service.continue_operation(success(
                action, {"profile": "tenant:not-offered"}
            ))
        self.assertEqual(
            PendingStateStore(self.state_path).load_pending(
                action["action_id"]
            )["action"],
            action,
        )
        bound = service.continue_operation(success(
            action, {"profile": "tenant:beta"}
        ))
        self.assertEqual(bound.status, "recipient_not_configured")
        saved = load_config(self.config_path)
        self.assertEqual(saved.channels[0].provider, "native")
        self.assertEqual(saved.channels[0].profile, "tenant:beta")

        saved.channels[0].recipients = ["network-team"]
        save_config(saved, self.config_path)
        service = self.service()
        action = action_from(service.deliver(make_envelope(), capabilities))
        action = action_from(service.continue_operation(success(
            action, {"authorization": "authorized"}
        )))
        action = action_from(service.continue_operation(success(action, {
            "profiles": [{"profile": "tenant:beta", "display_name": "Beta"}],
        })))
        self.assertEqual(action["operation"], "resolve_recipient")
        action = action_from(service.continue_operation(success(
            action, {"recipient": "group:network"}
        )))
        self.assertEqual(action["operation"], "confirm_delivery")
        action = action_from(service.continue_operation(success(
            action, {"confirmed": True}
        )))
        self.assertEqual(action["operation"], "send_report")
        delivered = service.continue_operation(success(
            action, {"external_id": "native-message-1"}
        ))

        self.assertEqual(delivered.status, "delivered")
        row = DeliveryLedger(self.ledger_path).get(DeliveryKey(
            make_envelope().report_id, "feishu", "native", "tenant:beta",
            "group:network",
        ))
        self.assertEqual(row["state"], "succeeded")
        self.assertEqual(row["external_id"], "native-message-1")

    def test_dws_host_mediated_recipient_and_send_resume_end_to_end(self):
        save_config(BridgeConfig(
            enabled=True,
            channels=[ChannelConfig(
                "dingtalk", provider="dws-cli", profile="corp:user",
                recipients=["network-team"],
            )],
        ), self.config_path)
        service = self.service([DwsProvider(AuthorizedDwsRunner())])
        current = make_envelope()

        action = action_from(service.deliver(current))
        self.assertEqual(action["provider"], "dws-cli")
        self.assertEqual(action["operation"], "resolve_recipient")
        action = action_from(service.continue_operation(success(
            action, {"recipient": "conversation:network"}
        )))
        self.assertEqual(action["operation"], "confirm_delivery")
        action = action_from(service.continue_operation(success(
            action, {"confirmed": True}
        )))
        self.assertEqual(action["operation"], "send_report")
        delivered = service.continue_operation(success(
            action, {"external_id": "dws-host-message-1"}
        ))

        self.assertEqual(delivered.status, "delivered")
        row = DeliveryLedger(self.ledger_path).get(DeliveryKey(
            current.report_id, "dingtalk", "dws-cli", "corp:user",
            "conversation:network",
        ))
        self.assertEqual(row["state"], "succeeded")
        self.assertEqual(row["external_id"], "dws-host-message-1")

    def test_summary_is_a_report_correlated_two_stage_continuation(self):
        save_config(BridgeConfig(
            enabled=True,
            channels=[ChannelConfig("feishu", provider="auto")],
        ), self.config_path)
        service = self.service()

        summary_action = action_from(service.deliver(
            make_envelope(summary=""), capability_bundle("feishu"),
            request_host_summary=True,
        ))

        self.assertEqual(summary_action["operation"], "summarize_report")
        self.assertEqual(summary_action["report_id"], make_envelope("").report_id)
        next_action = action_from(service.continue_operation(success(
            summary_action, {"text": "主机生成的摘要"}
        )))
        self.assertEqual(next_action["operation"], "auth_status")
        retry = PendingStateStore(self.state_path).load_retry(
            make_envelope("").report_id
        )
        self.assertEqual(retry["envelope"]["ai_summary"]["text"], "主机生成的摘要")

    def test_mismatched_continuation_is_rejected_and_remains_pending(self):
        save_config(BridgeConfig(
            enabled=True,
            channels=[ChannelConfig("feishu", provider="auto")],
        ), self.config_path)
        service = self.service()
        action = action_from(service.deliver(make_envelope(), capability_bundle()))
        invalid = success(action, {"authorization": "authorized"})
        invalid["report_id"] = "0" * 64

        with self.assertRaises(ContinuationError):
            service.continue_operation(invalid)

        self.assertEqual(
            PendingStateStore(self.state_path).load_pending(action["action_id"])["action"],
            action,
        )

    def test_retry_uses_durable_envelope_without_redetection(self):
        config = BridgeConfig(
            enabled=True,
            channels=[ChannelConfig(
                "dingtalk", provider="native", profile="corp:user",
                recipients=["ops"],
            )],
        )
        save_config(config, self.config_path)
        provider = SynchronousProvider()
        provider.send_results = [
            ProviderResult("failed", "timeout", retryable=True),
            ProviderResult("sent", data={"external_id": "message-2"}),
        ]
        store = PendingStateStore(self.state_path)
        store.confirm({
            "platform": "dingtalk", "provider": "native",
            "profile": "corp:user", "recipients": ["resolved:ops"],
        })
        service = self.service([provider])
        current = make_envelope()

        failed = service.deliver(current)
        retried = service.retry(current.report_id)

        self.assertEqual(failed.status, "notification_failed")
        self.assertEqual(retried.status, "delivered")
        self.assertEqual(len(provider.sent), 2)
        self.assertEqual(provider.sent[0][2].report_id, provider.sent[1][2].report_id)

    def test_service_rejects_duplicate_platforms_after_config_mutation(self):
        config = BridgeConfig(enabled=True, channels=[ChannelConfig("dingtalk")])
        save_config(config, self.config_path)
        service = self.service([SynchronousProvider()])
        service.config.channels.append(ChannelConfig("dingtalk"))

        with self.assertRaises(ConfigError):
            service.deliver(make_envelope())

    def test_stale_native_claim_reconciles_before_a_new_send(self):
        save_config(BridgeConfig(
            enabled=True,
            channels=[ChannelConfig(
                "dingtalk", provider="native", profile="corp:user",
                recipients=["ops"],
            )],
        ), self.config_path)
        current_time = [datetime(2026, 8, 31, tzinfo=timezone.utc)]
        ledger = DeliveryLedger(
            self.ledger_path, lease_seconds=30,
            clock=lambda: current_time[0],
        )
        current = make_envelope()
        key = DeliveryKey(
            current.report_id, "dingtalk", "native", "corp:user",
            "resolved:ops",
        )
        old_claim = ledger.claim(key)
        current_time[0] += timedelta(seconds=31)
        store = PendingStateStore(self.state_path)
        store.confirm({
            "platform": "dingtalk", "provider": "native",
            "profile": "corp:user", "recipients": ["resolved:ops"],
        })
        service = self.service(ledger=ledger)
        capabilities = capability_bundle("dingtalk")

        action = action_from(service.deliver(current, capabilities))
        action = action_from(service.continue_operation(success(
            action, {"authorization": "authorized"}
        )))
        action = action_from(service.continue_operation(success(action, {
            "profiles": [{"profile": "corp:user"}],
        })))
        action = action_from(service.continue_operation(success(
            action, {"recipient": "resolved:ops"}
        )))

        self.assertEqual(action["operation"], "delivery_status")
        self.assertEqual(action["data"]["claim_id"], old_claim.claim_id)
        send_action = action_from(service.continue_operation(success(action, {
            "delivery": "not_delivered", "external_id": "",
        })))
        self.assertEqual(send_action["operation"], "send_report")
        self.assertNotEqual(send_action["data"]["claim_id"], old_claim.claim_id)


if __name__ == "__main__":
    unittest.main()
