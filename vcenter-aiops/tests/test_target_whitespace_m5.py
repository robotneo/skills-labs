"""M-5: exact-target gating must reject pure-whitespace and zero-width values.

A targeting value of only spaces/tabs previously slipped past ``is_wildcard``
(the wildcard regex deliberately allows spaces because legitimate paths may
contain them). Invisible/zero-width characters likewise defeat human
verification. A value that *contains* spaces alongside real characters (a valid
path) must still be accepted.
"""
import unittest

from vcenter_aiops.application.registry import lookup
from vcenter_aiops.domain import risk


class WhitespaceTargetTests(unittest.TestCase):
    def test_pure_whitespace_is_fuzzy(self):
        for value in ("", "   ", "\t", "\n", " \t\r\n", "\u3000"):  # incl. ideographic space
            with self.subTest(repr=repr(value)):
                self.assertTrue(risk.is_wildcard(value))

    def test_zero_width_characters_are_fuzzy_even_amid_text(self):
        base = "vm-123"
        for zw in ("\u200b", "\u200c", "\u200d", "\ufeff", "\u2060", "\u00ad"):
            for value in (zw, base + zw, zw + base, "vm" + zw + "-123"):
                with self.subTest(value=value, zw=hex(ord(zw))):
                    self.assertTrue(risk.is_wildcard(value))

    def test_value_with_real_chars_and_spaces_still_exact(self):
        for value in ("/tmp/my report/export.json", "vm-123", "a b", "lab vm"):
            with self.subTest(value=value):
                self.assertFalse(risk.is_wildcard(value))

    def test_high_risk_scope_rejects_blank_and_zero_width(self):
        # cache invalidate is HIGH and its kind passes through exact-target
        # validation as a scope; a blank/zero-width scope must be refused.
        for bad_kind in ("   ", "vm\u200b", "\ufeffvm"):
            with self.subTest(bad_kind=repr(bad_kind)):
                with self.assertRaises(ValueError):
                    risk.validate_exact_targets(lookup("cache invalidate"), {"kind": bad_kind})

    def test_high_risk_scope_accepts_clean_enum(self):
        targets = risk.validate_exact_targets(lookup("cache invalidate"), {"kind": "vm"})
        self.assertEqual(targets["scopes"][0]["value"], "vm")

    def test_non_string_is_fuzzy(self):
        for value in (None, 123, ["vm-1"], {"x": 1}):
            with self.subTest(value=value):
                self.assertTrue(risk.is_wildcard(value))


if __name__ == "__main__":
    unittest.main()
