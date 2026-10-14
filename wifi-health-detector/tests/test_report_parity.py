"""Cross-deliverable wording parity for the standard Wi-Fi report.

The detector (``wifi_health/output.py``) renders the canonical report; the
bundled bridge (``notification_bridge/standard_report.py``) re-renders the same
report from JSON on a configured host. They are *independently deliverable* and
must stay runtime-decoupled, so the shared Chinese/English wording is mirrored
rather than imported. This test makes that mirroring an explicit contract: if
one side changes a label/badge/issue/recommendation, the other must move in the
same change or delivery fails.
"""
from __future__ import absolute_import

import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE_ROOT = os.path.join(
    ROOT, "integrations", "enterprise-notification-bridge"
)
if BRIDGE_ROOT not in sys.path:
    sys.path.insert(0, BRIDGE_ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from wifi_health import output as detector_output  # noqa: E402
from notification_bridge import standard_report as bridge_output  # noqa: E402


# Fixed table row labels and self-contained wording maps that must be byte
# identical across the producer renderer and the bridge re-renderer.
SHARED_TUPLES = (
    "ZH_CORE_ROW_LABELS", "EN_CORE_ROW_LABELS",
    "ZH_LOCAL_ROW_LABELS", "EN_LOCAL_ROW_LABELS",
    "ZH_PUBLIC_ROW_LABELS", "EN_PUBLIC_ROW_LABELS",
)
SHARED_MAPS = (
    "ZH_ISSUES", "EN_ISSUES", "BADGES",
    "ZH_RECOMMENDATIONS", "REASON_ZH",
)
# Quality-table field labels shared by both renderers (the detector's
# FIELD_LABELS dictionaries are wider; only these keys appear in the bridge).
SHARED_QUALITY_FIELDS = (
    "target", "reachable", "latency", "jitter", "packet_loss",
    "dns_latency", "download_speed",
)


class ReportWordingParityTests(unittest.TestCase):
    def test_fixed_row_labels_match_across_detector_and_bridge(self):
        for name in SHARED_TUPLES:
            with self.subTest(name=name):
                self.assertEqual(
                    getattr(detector_output, name),
                    getattr(bridge_output, name),
                )

    def test_wording_maps_match_across_detector_and_bridge(self):
        for name in SHARED_MAPS:
            with self.subTest(name=name):
                self.assertEqual(
                    getattr(detector_output, name),
                    getattr(bridge_output, name),
                )

    def test_quality_field_labels_match_across_detector_and_bridge(self):
        for field in SHARED_QUALITY_FIELDS:
            with self.subTest(field=field):
                self.assertEqual(
                    detector_output.FIELD_LABELS_ZH[field],
                    bridge_output.FIELD_LABELS_ZH[field],
                )
                self.assertEqual(
                    detector_output.FIELD_LABELS_EN[field],
                    bridge_output.FIELD_LABELS_EN[field],
                )


if __name__ == "__main__":
    unittest.main()
