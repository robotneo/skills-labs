from __future__ import absolute_import

import json
import os
import stat
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from notification_bridge.config import ChannelConfig, BridgeConfig, ConfigError, load_config, save_config


class ConfigTests(unittest.TestCase):
    def test_config_rejects_secret_fields(self):
        with self.assertRaisesRegex(ConfigError, "secret"):
            BridgeConfig.from_dict({"notification": {"token": "secret"}})

    def test_direct_secret_construction_is_rejected_without_creating_a_target(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.json")
            with self.assertRaisesRegex(ConfigError, "secret"):
                BridgeConfig(ai_summary={"nested": {"token": "secret"}})
            self.assertFalse(os.path.exists(path))

    def test_tuple_nested_secret_is_rejected_without_overwriting_a_target(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.json")
            save_config(BridgeConfig(), path)
            with open(path, "r") as handle:
                original = handle.read()

            config = BridgeConfig()
            config.ai_summary = ({"refresh_token": "secret"},)
            with self.assertRaisesRegex(ConfigError, "secret"):
                save_config(config, path)

            with open(path, "r") as handle:
                self.assertEqual(handle.read(), original)

    def test_one_shot_recipients_iterable_is_retained(self):
        recipients = (recipient for recipient in ("ops", "network"))
        channel = ChannelConfig(
            "dingtalk", provider="native", profile="corp:user",
            recipients=recipients,
        )
        self.assertEqual(channel.recipients, ["ops", "network"])

    def test_config_rejects_nested_refresh_field(self):
        with self.assertRaisesRegex(ConfigError, "secret"):
            BridgeConfig.from_dict({
                "notification": {"channels": [{"recipients": [{"refresh_key": "x"}]}]}
            })

    def test_config_accepts_only_the_documented_notification_fields(self):
        config = BridgeConfig.from_dict({
            "version": 1,
            "notification": {
                "enabled": True,
                "failure_policy": "non_blocking",
                "ai_summary": {
                    "provider": "host_agent", "fallback": "deterministic",
                },
                "channels": [{
                    "platform": "dingtalk",
                    "provider": "native",
                    "profile": "work",
                    "recipients": ["team-a"],
                }],
            },
        })
        self.assertEqual(config.to_dict()["notification"]["channels"][0]["provider"], "native")

    def test_config_rejects_invalid_scalar_and_summary_types(self):
        invalid_values = (
            {"version": "1"},
            {"version": 2},
            {"notification": {"enabled": 1}},
            {"notification": {"enabled": "false"}},
            {"notification": {"failure_policy": "continue"}},
            {"notification": {"ai_summary": False}},
            {"notification": {"ai_summary": {
                "provider": "external", "fallback": "deterministic",
            }}},
            {"notification": {"channels": {}}},
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ConfigError):
                    BridgeConfig.from_dict(value)

    def test_config_rejects_unsupported_duplicate_or_malformed_channels(self):
        invalid_channels = (
            [{"platform": "slack"}],
            [{"platform": "feishu", "provider": "dws-cli"}],
            [{"platform": "dingtalk", "provider": "invented"}],
            [{"platform": "dingtalk", "profile": ""}],
            [{"platform": "dingtalk", "profile": 7}],
            [{"platform": "dingtalk", "recipients": [""]}],
            [{"platform": "dingtalk", "recipients": ["ops", "ops"]}],
            [{"platform": "dingtalk", "recipients": [7]}],
            [{"platform": "dingtalk"}, {"platform": "dingtalk"}],
        )
        for channels in invalid_channels:
            with self.subTest(channels=channels):
                with self.assertRaises(ConfigError):
                    BridgeConfig.from_dict({"notification": {"channels": channels}})

    def test_recipients_require_a_bound_profile_and_provider(self):
        for provider, profile in (("native", None), ("auto", "tenant:user")):
            with self.subTest(provider=provider, profile=profile):
                with self.assertRaises(ConfigError):
                    ChannelConfig(
                        "feishu", provider=provider, profile=profile,
                        recipients=["group:network"],
                    )

    def test_config_rejects_unknown_fields(self):
        with self.assertRaisesRegex(ConfigError, "unsupported"):
            BridgeConfig.from_dict({"notification": {"unexpected": True}})

    def test_save_and_load_round_trip_at_the_injected_path(self):
        config = BridgeConfig.from_dict({
            "notification": {"enabled": True, "channels": [{
                "platform": "dingtalk", "provider": "native",
                "profile": "corp:user", "recipients": ["ops"],
            }]}
        })
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.json")
            save_config(config, path)
            self.assertEqual(load_config(path).to_dict(), config.to_dict())

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are unavailable")
    def test_config_is_utf8_and_user_only(self):
        config = BridgeConfig.from_dict({
            "notification": {
                "enabled": True,
                "channels": [{
                    "platform": "dingtalk", "provider": "native",
                    "profile": "企业:用户",
                    "recipients": ["网络运维"],
                }],
            },
        })
        with tempfile.TemporaryDirectory() as directory:
            target_directory = os.path.join(directory, "private")
            path = os.path.join(target_directory, "config.json")
            save_config(config, path)

            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), config.to_dict())
            self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(os.stat(target_directory).st_mode), 0o700)

    def test_save_rejects_post_construction_secret_mutation_without_overwriting(self):
        config = BridgeConfig()
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "config.json")
            save_config(config, path)
            with open(path, "r") as handle:
                original = handle.read()

            config.ai_summary["refresh_token"] = "secret"
            with self.assertRaisesRegex(ConfigError, "secret"):
                save_config(config, path)

            with open(path, "r") as handle:
                self.assertEqual(handle.read(), original)


if __name__ == "__main__":
    unittest.main()
