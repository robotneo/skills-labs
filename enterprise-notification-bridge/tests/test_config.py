from __future__ import absolute_import

import os
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.config import BridgeConfig, ConfigError, load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_config_rejects_secret_fields(self):
        with self.assertRaisesRegex(ConfigError, "secret"):
            BridgeConfig.from_dict({"notification": {"token": "secret"}})

    def test_config_rejects_nested_refresh_field(self):
        with self.assertRaisesRegex(ConfigError, "secret"):
            BridgeConfig.from_dict({
                "notification": {"channels": [{"recipients": [{"refresh_key": "x"}]}]}
            })

    def test_config_accepts_only_the_documented_notification_fields(self):
        config = BridgeConfig.from_dict({
            "version": "1",
            "notification": {
                "enabled": True,
                "failure_policy": "continue",
                "ai_summary": False,
                "channels": [{
                    "platform": "dingtalk",
                    "provider": "native",
                    "profile": "work",
                    "recipients": ["team-a"],
                }],
            },
        })
        self.assertEqual(config.to_dict()["notification"]["channels"][0]["provider"], "native")

    def test_config_rejects_unknown_fields(self):
        with self.assertRaisesRegex(ConfigError, "unsupported"):
            BridgeConfig.from_dict({"notification": {"unexpected": True}})

    def test_save_and_load_round_trip_at_the_injected_path(self):
        config = BridgeConfig.from_dict({
            "notification": {"enabled": True, "channels": [{"platform": "dingtalk", "recipients": ["ops"]}]}
        })
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.json")
            save_config(config, path)
            self.assertEqual(load_config(path).to_dict(), config.to_dict())


if __name__ == "__main__":
    unittest.main()
