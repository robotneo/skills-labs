from __future__ import absolute_import

import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.providers.base import Provider
from notification_bridge.selector import select_provider


class AvailableProvider(Provider):
    def __init__(self, name, priority):
        self.platform = "dingtalk"
        self.name = name
        self.priority = priority

    def capabilities(self):
        return {"available": True}


def native_provider():
    return AvailableProvider("native", 100)


def dws_provider():
    return AvailableProvider("dws-cli", 10)


class SelectorTests(unittest.TestCase):
    def test_explicit_provider_wins(self):
        chosen = select_provider("dingtalk", "dws-cli", [native_provider(), dws_provider()])
        self.assertEqual(chosen.name, "dws-cli")

    def test_native_wins_over_cli_in_auto_mode(self):
        chosen = select_provider("dingtalk", "auto", [dws_provider(), native_provider()])
        self.assertEqual(chosen.name, "native")

    def test_selector_returns_unavailable_without_invoking_login(self):
        chosen = select_provider("feishu", "auto", [])
        self.assertEqual(chosen.availability, "unavailable")

    def test_explicit_unavailable_provider_returns_a_non_interactive_fallback(self):
        chosen = select_provider("dingtalk", "missing", [native_provider()])
        self.assertEqual(chosen.reason, "configured_provider_unavailable")


if __name__ == "__main__":
    unittest.main()
