from __future__ import absolute_import

import json
import os
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_PATH = os.path.join(ROOT, "SKILL.md")
README_PATH = os.path.join(ROOT, "README.md")
DETECTOR_ROOT = os.path.join(os.path.dirname(ROOT), "wifi-health-detector")


class AgentInstructionContractTests(unittest.TestCase):
    def test_every_agent_instruction_requires_report_validation_before_delivery(self):
        text = _read(SKILL_PATH)
        for agent in ("Codex", "Claude Code", "WorkBuddy", "OpenClaw", "generic"):
            self.assertIn(agent, text)
        self.assertIn("validate", text.lower())
        self.assertIn("one Provider", text)
        self.assertIn("empty", text.lower())
        self.assertIn("non-blocking", text.lower())

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


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


if __name__ == "__main__":
    unittest.main()
