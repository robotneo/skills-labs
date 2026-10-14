"""Direct unit tests for notification_bridge.models (previously covered only
indirectly through contract/service flows)."""
from __future__ import absolute_import

import copy
import json
import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.models import Envelope


def sample_payload():
    detector = {"name": "wifi-health-detector", "version": "2.6.4"}
    report = {
        "markdown": "# 📶 Wi-Fi Health Report\n",
        "json": {"schema_version": "2.0", "sections": {}},
    }
    summary = {"mode": "host_agent", "text": "healthy"}
    return detector, report, summary


class EnvelopeModelTests(unittest.TestCase):
    def _envelope(self):
        detector, report, summary = sample_payload()
        return Envelope(
            "a" * 64, "2026-10-14T01:00:00+00:00",
            detector, report, summary,
        )

    def test_exposes_constructor_fields(self):
        envelope = self._envelope()
        self.assertEqual(envelope.schema_version, "1")
        self.assertEqual(envelope.report_id, "a" * 64)
        self.assertEqual(envelope.generated_at, "2026-10-14T01:00:00+00:00")
        self.assertEqual(envelope.detector["version"], "2.6.4")
        self.assertEqual(envelope.ai_summary["text"], "healthy")

    def test_constructor_inputs_are_defensively_copied(self):
        detector, report, summary = sample_payload()
        envelope = Envelope("b" * 64, "2026-10-14T01:00:00Z",
                            detector, report, summary)
        detector["version"] = "9.9.9"
        report["markdown"] = "mutated"
        summary["text"] = "mutated"
        self.assertEqual(envelope.detector["version"], "2.6.4")
        self.assertEqual(envelope.report["markdown"],
                         "# 📶 Wi-Fi Health Report\n")
        self.assertEqual(envelope.ai_summary["text"], "healthy")

    def test_accessors_return_defensive_copies(self):
        envelope = self._envelope()
        envelope.detector["version"] = "9.9.9"
        envelope.report["markdown"] = "mutated"
        envelope.ai_summary["text"] = "mutated"
        # A second read still returns the original values.
        self.assertEqual(envelope.detector["version"], "2.6.4")
        self.assertEqual(envelope.report["markdown"],
                         "# 📶 Wi-Fi Health Report\n")
        self.assertEqual(envelope.ai_summary["text"], "healthy")

    def test_to_dict_is_ordered_and_json_serializable(self):
        data = self._envelope().to_dict()
        self.assertEqual(list(data.keys()), [
            "schema_version", "report_id", "generated_at",
            "detector", "report", "ai_summary",
        ])
        encoded = json.dumps(data, ensure_ascii=False)
        self.assertEqual(json.loads(encoded)["report_id"], "a" * 64)

    def test_to_dict_is_a_copy(self):
        envelope = self._envelope()
        data = envelope.to_dict()
        data["detector"]["version"] = "9.9.9"
        self.assertEqual(envelope.detector["version"], "2.6.4")

    def test_with_ai_summary_preserves_other_fields(self):
        envelope = self._envelope()
        updated = envelope.with_ai_summary("deterministic", "auto text")
        self.assertEqual(updated.ai_summary,
                         {"mode": "deterministic", "text": "auto text"})
        # Identity/report fields are unchanged and the original is untouched.
        self.assertEqual(updated.report_id, envelope.report_id)
        self.assertEqual(updated.generated_at, envelope.generated_at)
        self.assertEqual(updated.report, envelope.report)
        self.assertEqual(envelope.ai_summary["text"], "healthy")

    def test_slots_prevent_unknown_attributes(self):
        envelope = self._envelope()
        with self.assertRaises(AttributeError):
            envelope.unexpected = True

    def test_deepcopy_roundtrip_is_equal_data(self):
        envelope = self._envelope()
        duplicate = copy.deepcopy(envelope)
        self.assertEqual(duplicate.to_dict(), envelope.to_dict())


if __name__ == "__main__":
    unittest.main()
