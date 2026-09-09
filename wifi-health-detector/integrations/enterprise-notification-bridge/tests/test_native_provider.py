from __future__ import absolute_import

import os
import sys
import unittest
import copy


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.providers.native import NativeProvider


ENVELOPE = {"report_id": "report-1", "report": {"markdown": "# report"}}


def capability_descriptor():
    return {
        "schema_version": "1",
        "platform": "feishu",
        "provider": "native",
        "operations": [
            "auth_status", "login", "list_profiles", "resolve_recipient", "send_report",
        ],
    }


class NativeProviderTests(unittest.TestCase):
    def test_native_provider_emits_tool_request_without_guessing_tool_name(self):
        result = NativeProvider("feishu", capability_descriptor()).send_report(
            "tenant:user", "recipient", ENVELOPE
        )

        self.assertEqual(result.status, "action_required")
        self.assertEqual(result.reason, "native_operation_required")
        self.assertEqual(result.data["operation"], "send_report")
        self.assertNotIn("tool", result.data)
        self.assertEqual(result.data["profile"], "tenant:user")
        self.assertEqual(result.data["recipient"], "recipient")

    def test_native_capabilities_come_from_the_host_descriptor(self):
        provider = NativeProvider("feishu", capability_descriptor())

        self.assertEqual(provider.capabilities(), {
            "available": True,
            "operations": capability_descriptor()["operations"],
        })

    def test_unsupported_native_operation_is_never_dispatched(self):
        descriptor = capability_descriptor()
        descriptor["operations"] = ["auth_status"]

        result = NativeProvider("feishu", descriptor).send_report("tenant:user", "r", ENVELOPE)

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason, "native_operation_unavailable")

    def test_native_resume_accepts_only_exactly_correlated_operation_result(self):
        provider = NativeProvider("feishu", capability_descriptor())
        action = {
            "schema_version": "1", "action_id": "a" * 32,
            "report_id": "b" * 64,
            "platform": "feishu",
            "provider": "native",
            "operation": "send_report",
            "data": {
                "profile": "tenant:user", "recipient": "recipient",
                "envelope": {}, "claim_id": "claim-1",
            },
        }
        operation_result = dict(action)
        operation_result.update({
            "status": "succeeded", "reason": "", "retryable": False,
            "data": {"external_id": "host-returned-id"},
        })

        result = provider.resume(action, operation_result)

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.data["external_id"], "host-returned-id")

        mismatched = copy.deepcopy(operation_result)
        mismatched["action_id"] = "c" * 32
        rejected = provider.resume(action, mismatched)
        self.assertEqual(rejected.status, "unavailable")
        self.assertEqual(rejected.reason, "native_operation_result_invalid")

    def test_native_resume_rejects_an_operation_not_advertised_by_host(self):
        provider = NativeProvider("feishu", capability_descriptor())

        action = {
            "schema_version": "1", "action_id": "a" * 32,
            "report_id": "b" * 64,
            "platform": "feishu",
            "provider": "native",
            "operation": "delete_message",
            "data": {},
        }
        operation_result = dict(action)
        operation_result.update({
            "status": "succeeded", "reason": "", "retryable": False,
        })

        result = provider.resume(action, operation_result)

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason, "native_operation_unavailable")


if __name__ == "__main__":
    unittest.main()
