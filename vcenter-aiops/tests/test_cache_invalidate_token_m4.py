"""M-4: the confirmation token for `cache invalidate` (HIGH/CLEAR, direct local
write) must bind to the exact profile + asset kind. Previously it fell through to
the constant ``spec.path`` ("cache invalidate"), so one confirmed string could be
replayed against a different profile/kind scope.
"""
import unittest

from vcenter_aiops.application.registry import lookup
from vcenter_aiops.domain import risk


class CacheInvalidateTokenTests(unittest.TestCase):
    def test_token_binds_profile_and_kind(self):
        spec = lookup("cache invalidate")
        token = risk.confirmation_token(spec, {"kind": "vm"}, profile="lab")
        self.assertEqual(token, "cache invalidate:lab:vm")

    def test_token_differs_across_profile(self):
        spec = lookup("cache invalidate")
        lab = risk.confirmation_token(spec, {"kind": "vm"}, profile="lab")
        prod = risk.confirmation_token(spec, {"kind": "vm"}, profile="prod")
        self.assertNotEqual(lab, prod)
        self.assertEqual(prod, "cache invalidate:prod:vm")

    def test_token_differs_across_kind(self):
        spec = lookup("cache invalidate")
        vm = risk.confirmation_token(spec, {"kind": "vm"}, profile="lab")
        hosts = risk.confirmation_token(spec, {"kind": "host"}, profile="lab")
        self.assertNotEqual(vm, hosts)
        self.assertEqual(hosts, "cache invalidate:lab:host")

    def test_token_is_not_the_bare_command_path(self):
        spec = lookup("cache invalidate")
        self.assertNotEqual(
            risk.confirmation_token(spec, {"kind": "vm"}, profile="lab"),
            "cache invalidate")

    def test_other_commands_unaffected_without_profile(self):
        # Backward-compatible default: callers that pass no profile keep the
        # previous behaviour for resource/path-scoped commands.
        spec = lookup("vm delete")
        self.assertEqual(risk.confirmation_token(spec, {"vm_id": "vm-9"}), "vm-9")
        ip_spec = lookup("ip reserve")
        self.assertEqual(
            risk.confirmation_token(ip_spec, {"ip": "10.0.0.1"}, None), "10.0.0.1")


if __name__ == "__main__":
    unittest.main()
