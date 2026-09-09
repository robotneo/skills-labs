from __future__ import absolute_import

import json
import os
import stat
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.continuation import (
    ContinuationError,
    PendingStateStore,
    create_action,
    normalize_capabilities,
    validate_operation_result,
)
from notification_bridge.contract import build_envelope


FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
with open(os.path.join(FIXTURES, "standard-report.md"), "r", encoding="utf-8") as handle:
    STANDARD_MARKDOWN = handle.read()
with open(os.path.join(FIXTURES, "standard-report.json"), "r", encoding="utf-8") as handle:
    STANDARD_REPORT = json.load(handle)


def envelope():
    return build_envelope(
        STANDARD_MARKDOWN, STANDARD_REPORT, "", "deterministic", "2.5.0"
    )


def capability_bundle(platform="feishu"):
    return {
        "schema_version": "1",
        "capabilities": [{
            "schema_version": "1",
            "platform": platform,
            "provider": "native",
            "operations": [
                "auth_status", "login", "list_profiles",
                "resolve_recipient", "send_report", "delivery_status",
            ],
        }],
    }


def context():
    return {
        "kind": "deliver",
        "stage": "auth_status",
        "channel_index": 0,
        "recipient_index": 0,
        "resolved_recipients": [],
        "claim": None,
        "request_host_summary": False,
        "platform": "feishu",
        "provider": "native",
    }


class ContinuationContractTests(unittest.TestCase):
    def test_capabilities_are_versioned_allowlisted_and_unique_per_platform(self):
        normalized = normalize_capabilities(capability_bundle())
        self.assertEqual(normalized[0]["platform"], "feishu")

        invalid = (
            {"schema_version": "2", "capabilities": []},
            {"schema_version": "1", "capabilities": [{
                "schema_version": "1", "platform": "slack",
                "provider": "native", "operations": ["auth_status"],
            }]},
            {"schema_version": "1", "capabilities": [{
                "schema_version": "1", "platform": "feishu",
                "provider": "native", "operations": ["delete_message"],
            }]},
            {"schema_version": "1", "capabilities": [
                capability_bundle()["capabilities"][0],
                capability_bundle()["capabilities"][0],
            ]},
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ContinuationError):
                    normalize_capabilities(value)

    def test_operation_result_requires_exact_versioned_correlation(self):
        current = envelope()
        action = create_action(
            current.report_id, "feishu", "native", "auth_status",
            {"profile": None},
        )
        result = {
            "schema_version": "1",
            "action_id": action["action_id"],
            "report_id": current.report_id,
            "platform": "feishu",
            "provider": "native",
            "operation": "auth_status",
            "status": "succeeded",
            "reason": "",
            "retryable": False,
            "data": {"authorization": "authorized"},
        }

        validated = validate_operation_result(result, action)

        self.assertEqual(validated["data"]["authorization"], "authorized")
        for mutation in (
                dict(result, action_id="0" * 32),
                dict(result, report_id="0" * 64),
                dict(result, operation="login"),
                dict(result, unexpected=True)):
            with self.subTest(mutation=mutation):
                with self.assertRaises(ContinuationError):
                    validate_operation_result(mutation, action)

    def test_success_results_require_operation_specific_nonempty_identifiers(self):
        current = envelope()
        send = create_action(
            current.report_id, "feishu", "native", "send_report", {
                "profile": "tenant:user", "recipient": "group:network",
                "envelope": current.to_dict(), "claim_id": "claim-1",
            },
        )
        invalid = {
            "schema_version": "1", "action_id": send["action_id"],
            "report_id": send["report_id"], "platform": "feishu",
            "provider": "native", "operation": "send_report",
            "status": "succeeded", "reason": "", "retryable": False,
            "data": {"external_id": ""},
        }

        with self.assertRaises(ContinuationError):
            validate_operation_result(invalid, send)

    def test_pending_action_and_context_provider_identity_must_match(self):
        current = envelope()
        action = create_action(
            current.report_id, "dingtalk", "native", "auth_status",
            {"profile": None},
        )
        with tempfile.TemporaryDirectory() as directory:
            store = PendingStateStore(directory)
            with self.assertRaises(ContinuationError):
                store.save_pending(
                    action, current.to_dict(),
                    normalize_capabilities(capability_bundle()), context(),
                )

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are unavailable")
    def test_pending_and_retry_state_are_utf8_durable_and_user_only(self):
        current = envelope()
        capabilities = normalize_capabilities(capability_bundle())
        action = create_action(
            current.report_id, "feishu", "native", "auth_status",
            {"profile": "企业:用户"},
        )
        with tempfile.TemporaryDirectory() as directory:
            state_directory = os.path.join(directory, "state")
            store = PendingStateStore(state_directory)
            store.save_pending(
                action, current.to_dict(), capabilities, context()
            )
            store.save_retry(current.to_dict(), capabilities, True)

            pending = store.load_pending(action["action_id"])
            retry = store.load_retry(current.report_id)

            self.assertEqual(pending["action"]["data"]["profile"], "企业:用户")
            self.assertEqual(retry["envelope"]["report"]["markdown"], STANDARD_MARKDOWN)
            self.assertTrue(retry["request_host_summary"])
            self.assertEqual(stat.S_IMODE(os.stat(state_directory).st_mode), 0o700)
            for root, _, files in os.walk(state_directory):
                for filename in files:
                    self.assertEqual(
                        stat.S_IMODE(os.stat(os.path.join(root, filename)).st_mode),
                        0o600,
                    )

    def test_first_delivery_confirmation_is_scoped_to_all_destination_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            store = PendingStateStore(directory)
            scope = {
                "platform": "feishu", "provider": "native",
                "profile": "tenant:user", "recipients": ["group:网络运维"],
            }

            self.assertFalse(store.is_confirmed(scope))
            store.confirm(scope)

            self.assertTrue(store.is_confirmed(scope))
            changed = dict(scope, recipients=["group:安全运维"])
            self.assertFalse(store.is_confirmed(changed))


if __name__ == "__main__":
    unittest.main()
