from __future__ import absolute_import

import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.config import BridgeConfig, ChannelConfig
from notification_bridge.continuation import ContinuationError, MemoryStateStore
from notification_bridge.dependencies import DependencyStatus, DwsDependency
from notification_bridge.installer import DwsInstallResult
from notification_bridge.ledger import DeliveryLedger
from notification_bridge.providers.base import ProviderResult
from notification_bridge.service import BridgeService


def native_bundle():
    return {"schema_version": "1", "capabilities": [{
        "schema_version": "1", "platform": "dingtalk",
        "provider": "native", "operations": [
            "auth_status", "login", "list_profiles",
        ],
    }]}


class ReadyProvider(object):
    platform = "dingtalk"
    name = "dws-cli"
    priority = 10
    availability = "available"
    supports_device_login = True

    def __init__(self):
        self.auth_calls = 0
        self.login_calls = 0
        self.login_modes = []
        self.authorizations = []

    def capabilities(self):
        return {"available": True}

    def auth_status(self, profile=None):
        self.auth_calls += 1
        if self.authorizations:
            return self.authorizations.pop(0)
        return ProviderResult("authorized")

    def login(self, device_login=False):
        self.login_calls += 1
        self.login_modes.append(device_login)
        return ProviderResult("ok")

    def list_profiles(self):
        return ProviderResult("ok", data={"profile": "corp:user"})


class SetupWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.calls = []
        self.provider = ReadyProvider()
        self.config = BridgeConfig(enabled=True, channels=[
            ChannelConfig("dingtalk", provider="auto")
        ])

    def tearDown(self):
        self.directory.cleanup()

    def service(self, discovery=None, verification=None, installation=None):
        discovery = discovery or DependencyStatus(
            "discovered", "dependency_discovered",
            DwsDependency("/opt/dws", None, "1.0.15", "path"),
        )
        verification = verification or DependencyStatus(
            "ready", "dependency_ready",
            DwsDependency("/opt/dws", "1.0.15", "1.0.15", "path"),
        )

        def discover(*unused):
            self.calls.append("discover")
            return discovery

        def verify(*unused):
            self.calls.append("verify")
            return verification

        def install(*unused, **unused_kwargs):
            self.calls.append("install")
            return installation or DwsInstallResult(
                "ready", "dependency_ready", "official-github"
            )

        return BridgeService(
            self.config, [self.provider], DeliveryLedger(
                os.path.join(self.directory.name, "ledger.sqlite3")
            ), state_store=MemoryStateStore(),
            dependency_discoverer=discover,
            dependency_verifier=verify,
            dependency_installer=install,
            dependency_plan=lambda platform, mirror: object(),
            environment={}, platform_name="darwin", which=lambda unused: None,
        )

    def test_native_provider_never_requests_dws_install(self):
        result = self.service().setup_dependency(
            "dingtalk", "native", capabilities=native_bundle()
        )
        self.assertEqual(result.reason, "native_provider_selected")
        self.assertEqual(self.calls, [])

    def test_non_dingtalk_never_requests_dws_install(self):
        result = self.service().setup_dependency("feishu", "auto")
        self.assertEqual(result.reason, "dws_dependency_not_applicable")
        self.assertEqual(self.calls, [])

    def test_auto_prefers_declared_native_capability(self):
        result = self.service().setup_dependency(
            "dingtalk", "auto", capabilities=native_bundle()
        )
        self.assertEqual(result.reason, "native_provider_selected")
        self.assertEqual(self.calls, [])

    def test_auto_falls_back_to_dws_when_native_has_only_send_report(self):
        capabilities = {"schema_version": "1", "capabilities": [{
            "schema_version": "1", "platform": "dingtalk",
            "provider": "native", "operations": ["send_report"],
        }]}

        result = self.service().setup_dependency(
            "dingtalk", "auto", capabilities=capabilities
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(self.calls, ["discover", "verify"])

    def test_auto_falls_back_to_dws_when_native_setup_is_partial(self):
        capabilities = {"schema_version": "1", "capabilities": [{
            "schema_version": "1", "platform": "dingtalk",
            "provider": "native",
            "operations": ["auth_status", "login", "send_report"],
        }]}

        result = self.service().setup_dependency(
            "dingtalk", "auto", capabilities=capabilities
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(self.calls, ["discover", "verify"])

    def test_explicit_native_with_partial_setup_capabilities_is_unavailable(self):
        capabilities = {"schema_version": "1", "capabilities": [{
            "schema_version": "1", "platform": "dingtalk",
            "provider": "native",
            "operations": ["auth_status", "login", "send_report"],
        }]}

        result = self.service().setup_dependency(
            "dingtalk", "native", capabilities=capabilities
        )

        self.assertEqual(result.status, "unavailable")
        self.assertEqual(result.reason, "configured_provider_unavailable")
        self.assertEqual(self.calls, [])

    def test_missing_dws_returns_correlated_install_action(self):
        missing = DependencyStatus(
            "action_required", "dependency_install_required", None
        )
        service = self.service(discovery=missing)
        result = service.setup_dependency("dingtalk", "auto")
        self.assertEqual(result.status, "action_required")
        self.assertEqual(result.reason, "dependency_install_required")
        self.assertEqual(result.data["action"]["operation"], "install_dependency")
        self.assertEqual(len(service.state_store.pending_actions()), 1)
        self.assertEqual(self.calls, ["discover"])

    def test_missing_dws_setup_is_idempotent_and_reuses_pending_action(self):
        missing = DependencyStatus(
            "action_required", "dependency_install_required", None
        )
        service = self.service(discovery=missing)
        first = service.setup_dependency("dingtalk", "auto")
        second = service.setup_dependency("dingtalk", "auto")
        self.assertEqual(
            first.data["action"]["action_id"], second.data["action"]["action_id"]
        )
        self.assertEqual(len(service.state_store.pending_actions()), 1)

    def test_native_without_declared_capability_never_installs(self):
        result = self.service().setup_dependency("dingtalk", "native")
        self.assertEqual(result.reason, "configured_provider_unavailable")
        self.assertEqual(self.calls, [])

    def test_install_requires_both_request_and_approval(self):
        missing = DependencyStatus(
            "action_required", "dependency_install_required", None
        )
        result = self.service(discovery=missing).setup_dependency(
            "dingtalk", "dws-cli", install_dws=True, approved=False
        )
        self.assertEqual(result.reason, "dependency_install_declined")
        self.assertNotIn("install", self.calls)

    def test_approved_install_rediscovers_reverifies_then_binds(self):
        states = [
            DependencyStatus("action_required", "dependency_install_required", None),
            DependencyStatus("discovered", "dependency_discovered",
                             DwsDependency("/opt/dws", None, "1.0.15", "path")),
        ]

        service = self.service()
        service._dependency_discoverer = lambda *unused: (
            self.calls.append("discover") or states.pop(0)
        )
        result = service.setup_dependency(
            "dingtalk", "dws-cli", install_dws=True, approved=True
        )
        self.assertEqual(result.status, "ok")
        self.assertEqual(result.data["profile"], "corp:user")
        self.assertEqual(self.calls, ["discover", "install", "discover", "verify"])
        self.assertEqual(self.provider.auth_calls, 1)

    def test_correlated_install_continuation_runs_the_same_setup_service(self):
        states = [
            DependencyStatus("action_required", "dependency_install_required", None),
            DependencyStatus("action_required", "dependency_install_required", None),
            DependencyStatus("discovered", "dependency_discovered",
                             DwsDependency("/opt/dws", None, "1.0.15", "path")),
        ]
        service = self.service()
        service._dependency_discoverer = lambda *unused: (
            self.calls.append("discover") or states.pop(0)
        )
        required = service.setup_dependency("dingtalk", "dws-cli")
        action = required.data["action"]
        continued = service.continue_operation({
            "schema_version": "1", "action_id": action["action_id"],
            "report_id": action["report_id"], "platform": "dingtalk",
            "provider": "dws-cli", "operation": "install_dependency",
            "status": "succeeded", "reason": "", "retryable": False,
            "data": {},
        })
        self.assertEqual(continued.results[0].status, "ok")
        self.assertEqual(self.calls, ["discover", "discover", "install",
                                      "discover", "verify"])
        self.assertEqual(service.state_store.pending_actions(), [])

    def test_new_native_auto_setup_invalidates_older_auto_install_action(self):
        missing = DependencyStatus(
            "action_required", "dependency_install_required", None
        )
        service = self.service(discovery=missing)
        required = service.setup_dependency("dingtalk", "auto")
        action = required.data["action"]

        selected = service.setup_dependency(
            "dingtalk", "auto", capabilities=native_bundle()
        )

        self.assertEqual(selected.reason, "native_provider_selected")
        self.assertEqual(service.state_store.pending_actions(), [])
        with self.assertRaises(ContinuationError):
            service.continue_operation({
                "schema_version": "1", "action_id": action["action_id"],
                "report_id": action["report_id"], "platform": "dingtalk",
                "provider": "dws-cli", "operation": "install_dependency",
                "status": "succeeded", "reason": "", "retryable": False,
                "data": {},
            })
        self.assertEqual(self.calls, ["discover"])

    def test_explicit_native_setup_invalidates_older_auto_install_action(self):
        missing = DependencyStatus(
            "action_required", "dependency_install_required", None
        )
        service = self.service(discovery=missing)
        required = service.setup_dependency("dingtalk", "auto")
        action = required.data["action"]

        selected = service.setup_dependency(
            "dingtalk", "native", capabilities=native_bundle()
        )

        self.assertEqual(selected.reason, "native_provider_selected")
        self.assertEqual(service.state_store.pending_actions(), [])
        with self.assertRaises(ContinuationError):
            service.continue_operation({
                "schema_version": "1", "action_id": action["action_id"],
                "report_id": action["report_id"], "platform": "dingtalk",
                "provider": "dws-cli", "operation": "install_dependency",
                "status": "succeeded", "reason": "", "retryable": False,
                "data": {},
            })
        self.assertEqual(self.calls, ["discover"])

    def test_explicit_native_only_invalidates_same_platform_auto_actions(self):
        missing = DependencyStatus(
            "action_required", "dependency_install_required", None
        )
        service = self.service(discovery=missing)
        stale_auto = service.setup_dependency("dingtalk", "auto")
        explicit_dws = service.setup_dependency("dingtalk", "dws-cli")
        other_platform = service._dependency_install_action(
            "feishu", "auto", False, []
        )

        selected = service.setup_dependency(
            "dingtalk", "native", capabilities=native_bundle()
        )

        self.assertEqual(selected.reason, "native_provider_selected")
        pending_ids = {
            action["action_id"]
            for action in service.state_store.pending_actions()
        }
        self.assertNotIn(stale_auto.data["action"]["action_id"], pending_ids)
        self.assertIn(explicit_dws.data["action"]["action_id"], pending_ids)
        self.assertIn(other_platform.data["action"]["action_id"], pending_ids)
        self.assertEqual(self.calls, ["discover", "discover"])

    def test_direct_approved_install_invalidates_older_install_action(self):
        states = [
            DependencyStatus("action_required", "dependency_install_required", None),
            DependencyStatus("action_required", "dependency_install_required", None),
            DependencyStatus("discovered", "dependency_discovered",
                             DwsDependency("/opt/dws", None, "1.0.15", "path")),
        ]
        service = self.service()
        service._dependency_discoverer = lambda *unused: (
            self.calls.append("discover") or states.pop(0)
        )
        required = service.setup_dependency("dingtalk", "dws-cli")
        action = required.data["action"]

        installed = service.setup_dependency(
            "dingtalk", "dws-cli", install_dws=True, approved=True
        )

        self.assertEqual(installed.status, "ok")
        self.assertEqual(service.state_store.pending_actions(), [])
        with self.assertRaises(ContinuationError):
            service.continue_operation({
                "schema_version": "1", "action_id": action["action_id"],
                "report_id": action["report_id"], "platform": "dingtalk",
                "provider": "dws-cli", "operation": "install_dependency",
                "status": "succeeded", "reason": "", "retryable": False,
                "data": {},
            })
        self.assertEqual(self.calls.count("install"), 1)

    def test_continuation_consumes_action_without_install_when_dws_is_now_ready(self):
        states = [
            DependencyStatus("action_required", "dependency_install_required", None),
            DependencyStatus("discovered", "dependency_discovered",
                             DwsDependency("/opt/dws", None, "1.0.15", "path")),
        ]
        service = self.service()
        service._dependency_discoverer = lambda *unused: (
            self.calls.append("discover") or states.pop(0)
        )
        required = service.setup_dependency("dingtalk", "dws-cli")
        action = required.data["action"]

        continued = service.continue_operation({
            "schema_version": "1", "action_id": action["action_id"],
            "report_id": action["report_id"], "platform": "dingtalk",
            "provider": "dws-cli", "operation": "install_dependency",
            "status": "succeeded", "reason": "", "retryable": False,
            "data": {},
        })

        self.assertEqual(continued.results[0].status, "ok")
        self.assertNotIn("install", self.calls)
        self.assertEqual(service.state_store.pending_actions(), [])

    def test_ready_dependency_does_not_install_or_repeat_login(self):
        self.config.channels[0].profile = "corp:user"
        service = self.service()
        first = service.setup_dependency("dingtalk", "dws-cli")
        second = service.setup_dependency("dingtalk", "dws-cli")
        self.assertEqual(first.status, "ok")
        self.assertEqual(second.status, "ok")
        self.assertNotIn("install", self.calls)
        self.assertEqual(self.provider.auth_calls, 2)

    def test_expired_authorization_logs_in_once_then_reuses_authorization(self):
        self.provider.authorizations = [
            ProviderResult("expired"), ProviderResult("authorized"),
            ProviderResult("authorized"),
        ]
        service = self.service()
        self.assertEqual(
            service.setup_dependency("dingtalk", "dws-cli").status, "ok"
        )
        self.assertEqual(
            service.setup_dependency("dingtalk", "dws-cli").status, "ok"
        )
        self.assertEqual(self.provider.login_calls, 1)

    def test_device_login_uses_documented_dws_device_flow(self):
        self.provider.authorizations = [
            ProviderResult("missing"), ProviderResult("authorized"),
        ]

        result = self.service().setup_dependency(
            "dingtalk", "dws-cli", device_login=True
        )

        self.assertEqual(result.status, "ok")
        self.assertEqual(self.provider.login_modes, [True])


if __name__ == "__main__":
    unittest.main()
