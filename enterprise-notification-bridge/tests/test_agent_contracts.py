from __future__ import absolute_import

import json
import os
import re
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_PATH = os.path.join(ROOT, "SKILL.md")
README_PATH = os.path.join(ROOT, "README.md")
DETECTOR_ROOT = os.path.join(os.path.dirname(ROOT), "wifi-health-detector")
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.config import BridgeConfig, ChannelConfig
from notification_bridge.continuation import MemoryStateStore
from notification_bridge.contract import build_envelope
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


class AgentInstructionContractTests(unittest.TestCase):
    def test_every_agent_instruction_requires_report_validation_before_delivery(self):
        text = _read(SKILL_PATH)
        for agent in ("Codex", "Claude Code", "WorkBuddy", "OpenClaw", "generic"):
            self.assertIn(agent, text)
        self.assertIn("validate", text.lower())
        self.assertIn("one Provider", text)
        self.assertIn("empty", text.lower())
        self.assertIn("non-blocking", text.lower())

    def test_skill_frontmatter_and_workflow_are_structured_and_ordered(self):
        text = _read(SKILL_PATH)
        match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
        self.assertIsNotNone(match)
        fields = dict(
            line.split(":", 1) for line in match.group(1).splitlines()
            if ":" in line
        )
        self.assertEqual(fields["name"].strip(), "enterprise-notification-bridge")
        self.assertTrue(fields["description"].strip().startswith("Use when"))
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
            "run.sh bind --platform dingtalk",
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
