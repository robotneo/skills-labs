from __future__ import absolute_import

import json
import io
import os
import re
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_PATH = os.path.join(ROOT, "OPERATIONS.md")
README_PATH = os.path.join(ROOT, "README.md")
DETECTOR_ROOT = os.path.dirname(os.path.dirname(ROOT))
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.config import BridgeConfig, ChannelConfig
from notification_bridge.cli import BridgeCommands, main as cli_main
from notification_bridge.continuation import MemoryStateStore
from notification_bridge.contract import build_envelope
from notification_bridge.dependencies import DependencyStatus, DwsDependency
from notification_bridge.installer import DwsInstallResult
from notification_bridge.ledger import DeliveryLedger
from notification_bridge.providers.base import Provider, ProviderResult
from notification_bridge.service import BridgeService


class FixtureProvider(Provider):
    platform = "dingtalk"
    name = "native"
    priority = 50

    def __init__(self):
        self.sent = []

    def capabilities(self):
        return {"available": True}

    def auth_status(self, profile=None):
        return ProviderResult("authorized")

    def login(self):
        return ProviderResult("authorized")

    def list_profiles(self):
        return ProviderResult("ok", data={"profile": "corp:user"})

    def resolve_recipient(self, profile, selector):
        return ProviderResult("resolved", data={"recipient": selector})

    def send_report(self, profile, recipient, envelope):
        self.sent.append(envelope)
        return ProviderResult("sent", data={"external_id": "fixture-message"})


class SetupFixtureProvider(Provider):
    platform = "dingtalk"
    name = "dws-cli"
    priority = 10

    def __init__(self, authorizations=None):
        self.authorizations = list(authorizations or ["authorized"])
        self.login_calls = 0

    def capabilities(self):
        return {"available": True}

    def auth_status(self, profile=None):
        status = self.authorizations.pop(0) if self.authorizations else "authorized"
        return ProviderResult(status)

    def login(self):
        self.login_calls += 1
        return ProviderResult("ok")

    def list_profiles(self):
        return ProviderResult("ok", data={"profile": "corp:user"})


class AgentInstructionContractTests(unittest.TestCase):
    def _setup_cli(self, provider=None, discovery=None, verification=None,
                   installation=None, argv=None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        calls = []
        provider = provider or SetupFixtureProvider()
        config = BridgeConfig(enabled=True, channels=[
            ChannelConfig("dingtalk", provider="auto")
        ])
        ready_dependency = DwsDependency(
            "/opt/dws", "1.0.15", "1.0.15", "path"
        )
        discovery_values = list(discovery or [
            DependencyStatus("discovered", "dependency_discovered",
                             ready_dependency)
        ])

        def discover(*unused):
            calls.append("discover")
            return discovery_values.pop(0)

        def verify(*unused):
            calls.append("verify")
            return verification or DependencyStatus(
                "ready", "dependency_ready", ready_dependency
            )

        def install(*unused, **unused_kwargs):
            calls.append("install")
            return installation or DwsInstallResult(
                "ready", "dependency_ready", "official-github"
            )

        service = BridgeService(
            config, [provider], DeliveryLedger(
                os.path.join(directory.name, "ledger.sqlite3")
            ), state_store=MemoryStateStore(),
            dependency_discoverer=discover,
            dependency_verifier=verify,
            dependency_installer=install,
            dependency_plan=lambda platform, mirror: (platform, mirror),
            environment={}, platform_name="darwin", which=lambda unused: None,
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        exit_code = cli_main(
            argv=argv or ["setup", "--platform", "dingtalk"],
            commands=BridgeCommands(service, config),
            stdout=stdout, stderr=stderr,
        )
        return exit_code, json.loads(stdout.getvalue()), calls, provider

    def test_setup_cli_native_path_never_discovers_or_installs_dws(self):
        capabilities = {"schema_version": "1", "capabilities": [{
            "schema_version": "1", "platform": "dingtalk",
            "provider": "native", "operations": [
                "auth_status", "login", "list_profiles",
            ],
        }]}
        capability_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        self.addCleanup(lambda: os.path.exists(capability_file.name)
                        and os.unlink(capability_file.name))
        json.dump(capabilities, capability_file)
        capability_file.close()
        code, result, calls, unused = self._setup_cli(argv=[
            "setup", "--platform", "dingtalk", "--provider", "native",
            "--capabilities", capability_file.name,
        ])
        self.assertEqual(code, 0)
        self.assertEqual(result["reason"], "native_provider_selected")
        self.assertEqual(calls, [])

    def test_setup_cli_auto_falls_back_from_send_only_native_capability(self):
        capabilities = {"schema_version": "1", "capabilities": [{
            "schema_version": "1", "platform": "dingtalk",
            "provider": "native", "operations": ["send_report"],
        }]}
        capability_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        )
        self.addCleanup(lambda: os.path.exists(capability_file.name)
                        and os.unlink(capability_file.name))
        json.dump(capabilities, capability_file)
        capability_file.close()

        code, result, calls, unused = self._setup_cli(argv=[
            "setup", "--platform", "dingtalk", "--provider", "auto",
            "--capabilities", capability_file.name,
        ])

        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(calls, ["discover", "verify"])

    def test_setup_cli_missing_dws_returns_install_action_without_installing(self):
        missing = DependencyStatus(
            "action_required", "dependency_install_required", None
        )
        code, result, calls, unused = self._setup_cli(discovery=[missing])
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "action_required")
        self.assertEqual(result["reason"], "dependency_install_required")
        self.assertEqual(result["data"]["action"]["operation"],
                         "install_dependency")
        self.assertEqual(calls, ["discover"])

    def test_setup_cli_declined_install_does_not_invoke_installer(self):
        missing = DependencyStatus(
            "action_required", "dependency_install_required", None
        )
        code, result, calls, unused = self._setup_cli(
            discovery=[missing], argv=[
                "setup", "--platform", "dingtalk", "--provider", "dws-cli",
                "--install-dws",
            ])
        self.assertEqual(code, 2)
        self.assertEqual(result["reason"], "dependency_install_declined")
        self.assertEqual(calls, [])

    def test_setup_cli_fake_install_rediscovers_verifies_and_binds(self):
        missing = DependencyStatus(
            "action_required", "dependency_install_required", None
        )
        discovered = DependencyStatus(
            "discovered", "dependency_discovered",
            DwsDependency("/opt/dws", None, "1.0.15", "path"),
        )
        code, result, calls, unused = self._setup_cli(
            discovery=[missing, discovered], argv=[
                "setup", "--platform", "dingtalk", "--provider", "dws-cli",
                "--install-dws", "--yes",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["profile"], "corp:user")
        self.assertEqual(calls, ["discover", "install", "discover", "verify"])

    def test_setup_cli_expired_auth_logs_in_once_before_profile_binding(self):
        provider = SetupFixtureProvider(["expired", "authorized"])
        code, result, calls, provider = self._setup_cli(provider=provider)
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["profile"], "corp:user")
        self.assertEqual(provider.login_calls, 1)
        self.assertEqual(calls, ["discover", "verify"])

    def test_every_agent_instruction_requires_report_validation_before_delivery(self):
        text = _read(SKILL_PATH)
        for agent in ("Codex", "Claude Code", "WorkBuddy", "OpenClaw", "generic"):
            self.assertIn(agent, text)
        self.assertIn("validate", text.lower())
        self.assertIn("one Provider", text)
        self.assertIn("empty", text.lower())
        self.assertIn("non-blocking", text.lower())

    def test_internal_component_has_one_skill_entry_and_ordered_workflow(self):
        text = _read(SKILL_PATH)
        self.assertFalse(os.path.exists(os.path.join(ROOT, "SKILL.md")))
        self.assertTrue(os.path.isfile(os.path.join(DETECTOR_ROOT, "SKILL.md")))
        workflow = (
            "Validate both report representations",
            "Read the Bridge configuration",
            "Declare native platform capabilities",
            "Check authorization before delivery",
            "Bind an organization only from Provider-returned Profiles",
            "Resolve recipients only from configured recipient selectors",
            "Send the validated envelope through the selected Provider",
            "Keep delivery diagnostics outside the report",
        )
        positions = [text.index(item) for item in workflow]
        self.assertEqual(positions, sorted(positions))

    def test_instructions_forbid_report_mutation_and_guessed_recipient(self):
        text = _read(SKILL_PATH).lower()
        self.assertIn("never add", text)
        self.assertIn("never infer", text)
        self.assertIn("explicit", text)
        self.assertIn("multiple", text)
        self.assertIn("--format json", text)
        self.assertIn("corpid:userid", text)
        self.assertIn("no direct http/browser fallback", text)

    def test_detector_declares_bridge_as_optional_integration(self):
        with open(os.path.join(DETECTOR_ROOT, "manifest.json")) as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["version"], "2.5.0")
        self.assertIn("enterprise-notification-bridge", manifest["optional_integrations"])
        skill = _read(os.path.join(DETECTOR_ROOT, "SKILL.md"))
        self.assertIn("enterprise-notification-bridge", skill)

    def test_metadata_describes_python_free_bridge_package(self):
        with open(os.path.join(ROOT, "manifest.json")) as handle:
            manifest = json.load(handle)
        self.assertEqual(manifest["id"], "enterprise-notification-bridge")
        self.assertEqual(manifest["entry"]["macos"], "run.sh")
        self.assertIn("python>=3.7", manifest["requirements"])
        self.assertNotIn("dependencies", manifest)
        self.assertIn("--format json", _read(README_PATH))

    def test_setup_recipe_is_explicit_and_ordered(self):
        text = _read(SKILL_PATH)
        setup = text.split("### Fresh installation setup", 1)[1]
        setup = setup.split("The CLI emits exactly one JSON document", 1)[0]
        recipe = (
            "run.sh status",
            "run.sh enable --platform dingtalk --provider auto",
            "run.sh setup --platform dingtalk --provider auto",
            "run.sh recipients --platform dingtalk",
            "run.sh deliver --envelope",
        )
        positions = [setup.index(item) for item in recipe]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("no login or delivery", setup)
        self.assertIn("six tools", setup)
        self.assertIn("continue_enterprise_notification", setup)

    def test_behavioral_fixture_preserves_envelope_and_never_sends_empty_recipients(self):
        with open(os.path.join(FIXTURES, "standard-report.md"), encoding="utf-8") as handle:
            markdown = handle.read()
        with open(os.path.join(FIXTURES, "standard-report.json"), encoding="utf-8") as handle:
            report_json = json.load(handle)
        envelope = build_envelope(markdown, report_json, "fixture summary", "host_agent", "2.5.0")
        provider = FixtureProvider()
        with tempfile.TemporaryDirectory() as directory:
            ledger = DeliveryLedger(os.path.join(directory, "ledger.sqlite3"))
            config = BridgeConfig(
                enabled=True,
                channels=[ChannelConfig(
                    "dingtalk", provider="native", profile="corp:user", recipients=[]
                )],
            )
            state_store = MemoryStateStore()
            service = BridgeService(
                config, [provider], ledger, state_store=state_store
            )
            skipped = service.deliver(envelope)
            self.assertEqual(skipped.results[0].reason, "recipient_not_configured")
            self.assertEqual(provider.sent, [])

            config.channels[0].recipients = ["ops"]
            state_store.confirm({
                "platform": "dingtalk", "provider": "native",
                "profile": "corp:user", "recipients": ["ops"],
            })
            delivered = service.deliver(envelope)
            repeated = service.deliver(envelope)
            self.assertEqual(delivered.status, "delivered")
            self.assertEqual(repeated.results[0].reason, "delivery_already_succeeded")
            self.assertEqual(len(provider.sent), 1)
            self.assertEqual(provider.sent[0].report["markdown"], markdown)
            self.assertEqual(provider.sent[0].report["json"], report_json)
            self.assertEqual(provider.sent[0].ai_summary["text"], "fixture summary")


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


if __name__ == "__main__":
    unittest.main()
