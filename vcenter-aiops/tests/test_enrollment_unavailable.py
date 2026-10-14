"""Strict-pin policy: automatic enrollment is absent, never a bypassable stub."""
import contextlib
import hashlib
import importlib.util
import io
import os
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from vcenter_aiops.application.registry import COMMANDS, capabilities, lookup
from vcenter_aiops.application.providers import ProviderRouter
from vcenter_aiops.cli.main import build_parser, invoke
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import canonical
from test_membership import MembershipFixture, REMOVE
import test_membership as membership_tests

ADD = dict(cluster_id="domain-c1", hostname="esxi.example.test", username="root",
           password_ref="env:UNUSED_ENROLLMENT_PASSWORD", ssl_thumbprint=":".join(["AB"] * 20),
           expected_host_uuid="AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE")


class EnrollmentUnavailableTests(unittest.TestCase):
    def test_add_is_absent_from_registry_capabilities_handlers_and_help(self):
        from vcenter_aiops.application.commands import clusters
        from vcenter_aiops.providers.vsphere.licenses import Licenses
        self.assertNotIn("cluster add-host", [spec.path for spec in COMMANDS])
        self.assertNotIn("cluster add-host", str(capabilities()))
        self.assertFalse(hasattr(clusters, "cluster_add_host"))
        self.assertFalse(hasattr(Licenses, "connection"))
        self.assertIsNone(importlib.util.find_spec("vcenter_aiops.providers.vsphere.enrollment_probe"))
        with self.assertRaises(OperationError) as caught:
            lookup("cluster add-host")
        self.assertEqual(caught.exception.code, "command_unknown")
        output = io.StringIO()
        with contextlib.redirect_stdout(output), self.assertRaises(SystemExit):
            build_parser().parse_args(["cluster", "--help"])
        self.assertNotIn("add-host", output.getvalue())
        self.assertIn("remove-host", output.getvalue())

    def test_application_and_plan_lookup_refuse_before_session_or_credentials(self):
        fixture = MembershipFixture()
        router = ProviderRouter(None, {"membership": fixture.provider()})
        ctx = NS(session=Mock(side_effect=AssertionError("no session allowed")))
        with patch.object(os.environ, "get", side_effect=AssertionError("no credential lookup")) as environment:
            for action in (lambda: invoke("cluster add-host", ADD, ctx),
                           lambda: router.bind_steps([{"command": "cluster add-host", "params": ADD}])):
                with self.subTest(action=action):
                    with self.assertRaises(OperationError) as caught:
                        action()
                    self.assertEqual(caught.exception.code, "command_unknown")
            environment.assert_not_called()
        ctx.session.assert_not_called()
        self.assertEqual(fixture.calls, [])

    def test_direct_provider_add_refuses_before_credential_lookup_or_sdk_access(self):
        fixture = MembershipFixture()
        provider = fixture.provider()
        with patch.object(os.environ, "get", side_effect=AssertionError("no credential lookup")) as environment, \
                patch.object(provider, "resolver", side_effect=AssertionError("no SDK lookup")) as resolver:
            for action in (lambda: provider.preflight("cluster add-host", ADD),
                           lambda: provider.submit("cluster add-host", ADD, {"command": "cluster add-host"}),
                           lambda: provider.observe({}, {"command": "cluster add-host"}),
                           lambda: provider.cancel({}, {"command": "cluster add-host"})):
                with self.subTest(action=action):
                    with self.assertRaises(OperationError) as caught:
                        action()
                    self.assertEqual(caught.exception.code, "command_unknown")
            environment.assert_not_called()
            resolver.assert_not_called()
            self.assertFalse(provider.verify("cluster add-host", ADD, {"command": "cluster add-host"}, {}))
        self.assertEqual(fixture.calls, [])

    def test_stale_add_plan_is_refused_without_any_resubmission_or_credential_lookup(self):
        fixture = MembershipFixture(True)
        # Reuse only the temporary-store helper, not its tests.
        helper = membership_tests.MembershipTests()
        self.addCleanup(helper.doCleanups)
        engine = helper.engine(fixture)
        plan = engine.preview("cluster remove-host", REMOVE).data
        payload = plan["payload"]
        payload["steps"][0]["command"] = "cluster add-host"
        payload["steps"][0]["params"] = ADD
        payload["steps"][0]["binding"]["command"] = "cluster add-host"
        digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
        engine.store.db.execute("UPDATE plans SET payload=?, digest=? WHERE id=?", (canonical(payload), digest, plan["id"]))
        fixture.calls.clear()
        with patch.object(os.environ, "get", side_effect=AssertionError("no credential lookup")) as environment, \
                patch.object(fixture, "InvokeMethod", side_effect=AssertionError("no SDK call")) as sdk:
            with self.assertRaises(OperationError) as caught:
                engine.apply(plan["id"], digest, "DESTROY:" + digest)
            self.assertEqual(caught.exception.code, "command_unknown")
            environment.assert_not_called()
            sdk.assert_not_called()
        self.assertEqual(fixture.calls, [])
