"""Offline invariants for the three-tier risk classification model."""
import unittest

from vcenter_aiops.application.registry import COMMANDS, lookup
from vcenter_aiops.domain import risk


class RiskLevelTests(unittest.TestCase):
    def test_every_command_has_a_known_level_and_describe_carries_it(self):
        for spec in COMMANDS:
            with self.subTest(command=spec.path):
                level = risk.risk_level(spec)
                self.assertIn(level, risk.RISK_LEVELS)
                described = spec.describe()
                self.assertEqual(described["risk_level"], level)
                self.assertIsInstance(described["sensitive_categories"], list)
                self.assertIsInstance(described["irreversible_categories"], list)

    def test_destructive_commands_are_always_high(self):
        for spec in COMMANDS:
            if spec.risk == "destructive":
                with self.subTest(command=spec.path):
                    self.assertEqual(risk.risk_level(spec), risk.HIGH)

    def test_known_destructive_set(self):
        destructive = {s.path for s in COMMANDS if s.risk == "destructive"}
        self.assertEqual(destructive, {
            "vm delete", "vm snapshot-revert", "vm snapshot-delete",
            "cluster remove-host", "cluster delete"})

    def test_bulk_power_is_high_and_bulk_irreversible(self):
        for verb in ("power-on", "power-off", "shutdown", "reset"):
            spec = lookup("batch " + verb)
            with self.subTest(command=spec.path):
                self.assertEqual(risk.risk_level(spec), risk.HIGH)
                self.assertIn(risk.IRREVERSIBLE_BULK, risk.risk_tags(spec)[1])

    def test_overrides_reference_real_commands(self):
        for path in risk._OVERRIDES:
            self.assertIsNotNone(lookup(path), path)


class DirectEffectTests(unittest.TestCase):
    def test_local_writes_are_direct_effect(self):
        for spec in COMMANDS:
            if spec.category == "local_write":
                with self.subTest(command=spec.path):
                    self.assertTrue(risk.is_direct_effect(spec))

    def test_read_only_commands_are_low(self):
        # A read-only remote/local command must never be gated as mutating
        # unless it performs an egress (export/transfer) or param-driven write.
        egress = {"audit export", "inventory export", "vm guest-download",
                  "vm guest-upload"}
        for spec in COMMANDS:
            if spec.risk == "read_only" and spec.category in (
                    "local_read", "remote_read") and spec.path not in egress:
                with self.subTest(command=spec.path):
                    self.assertEqual(risk.risk_level(spec), risk.LOW)


class PreciseTargetTests(unittest.TestCase):
    def test_bulk_enumerates_every_id_with_count(self):
        targets = risk.validate_exact_targets(
            lookup("batch power-off"), {"vm_ids": ["vm-3", "vm-1", "vm-9"]})
        self.assertTrue(targets["bulk"])
        self.assertEqual(targets["count"], 3)
        self.assertEqual([r["id"] for r in targets["resources"]],
                         ["vm-3", "vm-1", "vm-9"])
        self.assertTrue(all("index" in r for r in targets["resources"]))

    def test_bulk_rejects_wildcard_duplicate_empty_and_oversize(self):
        for ids in (["vm-1", "vm-*"], ["vm-1", "vm-1"], [], ["vm-%d" % i for i in range(101)]):
            with self.subTest(ids=ids):
                with self.assertRaises(ValueError):
                    risk.validate_exact_targets(lookup("batch reset"), {"vm_ids": ids})

    def test_single_target_rejects_globs(self):
        # Empty string is rejected by the command contract itself; the exact
        # target gate focuses on fuzzy / wildcard selection.
        for bad in ("vm-*", "vm-?", "vm[0]", "vms%", "vm-{1,2}", ".*"):
            with self.subTest(bad=bad):
                self.assertTrue(risk.is_wildcard(bad))
                with self.assertRaises(ValueError):
                    risk.validate_exact_targets(lookup("vm delete"), {"vm_id": bad})
        # An empty supplied target yields no usable resource for direct commands.
        self.assertTrue(risk.is_wildcard(""))

    def test_exact_identifier_accepted_and_paths_may_contain_spaces(self):
        self.assertFalse(risk.is_wildcard("vm-123"))
        self.assertFalse(risk.is_wildcard("/tmp/my report/export.json"))
        targets = risk.validate_exact_targets(
            lookup("audit export"), {"file": "/tmp/my report/export.json"})
        self.assertEqual(targets["paths"][0]["path"], "/tmp/my report/export.json")

    def test_dynamic_level_guest_upload_overwrite(self):
        spec = lookup("vm guest-upload")
        self.assertEqual(risk.risk_level(spec, {"overwrite": False}), risk.MEDIUM)
        self.assertEqual(risk.risk_level(spec, {"overwrite": True}), risk.HIGH)
        self.assertIn(risk.IRREVERSIBLE_OVERWRITE,
                      risk.risk_tags(spec, {"overwrite": True})[1])

    def test_dynamic_level_ip_expire_apply(self):
        spec = lookup("ip expire")
        self.assertEqual(risk.risk_level(spec, {}), risk.LOW)
        self.assertFalse(risk.is_direct_effect(spec, {}))
        params = {"apply": True, "lease_id": "lease-7"}
        self.assertEqual(risk.risk_level(spec, params), risk.HIGH)
        self.assertTrue(risk.is_direct_effect(spec, params))
        targets = risk.validate_exact_targets(spec, params)
        self.assertIn("lease-7", [r["id"] for r in targets["resources"]])


if __name__ == "__main__":
    unittest.main()
