"""Single domain name vocabulary (dedup matrix, refactor 3).

All create/rename paths share ``domain.naming.valid_name`` instead of four
copies of the same regex. Interior spaces stay legal (paths never reach a
shell), while pure whitespace, edge whitespace and invisible/zero-width
characters are rejected like any other non-exact target.
"""
import unittest

from vcenter_aiops.domain.naming import (
    valid_name, valid_snapshot_name, NAME_MAX, SNAPSHOT_NAME_MAX)


class ValidNameTests(unittest.TestCase):
    def test_plain_and_interior_space_accepted(self):
        for good in ("web-01", "My VM", "a", "VM_100 (prod)", "100台"):
            self.assertTrue(valid_name(good), repr(good))

    def test_length_bounds(self):
        self.assertTrue(valid_name("x" * 80))
        self.assertFalse(valid_name("x" * 81))
        self.assertTrue(valid_name("x", max_len=1))
        self.assertFalse(valid_name("xy", max_len=1))

    def test_empty_or_non_string_rejected(self):
        for bad in ("", None, 123, b"vm", ["vm"], {}):
            self.assertFalse(valid_name(bad), repr(bad))

    def test_pure_or_edge_whitespace_rejected(self):
        for bad in (" ", "   ", "\t", "\n", "\u3000", " x", "x ", "x\n"):
            self.assertFalse(valid_name(bad), repr(bad))

    def test_path_percent_and_control_chars_rejected(self):
        for bad in ("a/b", "a\\b", "100%", "a\x00b", "a\x1fb", "a\rb"):
            self.assertFalse(valid_name(bad), repr(bad))

    def test_zero_width_and_invisible_rejected(self):
        # ZWSP/ZWNJ/ZWJ, word joiner, BOM, soft hyphen, Mongolian separator,
        # invisible math operators — including when embedded mid-name.
        for ch in ("\u200b", "\u200c", "\u200d", "\u2060", "\ufeff",
                   "\u00ad", "\u180e", "\u2061", "\u2062", "\u2063", "\u2064"):
            self.assertFalse(valid_name("vm" + ch), repr(ch))
            self.assertFalse(valid_name(ch + "vm"), repr(ch))
            self.assertFalse(valid_name("a" + ch + "b"), repr(ch))

    def test_name_max_constant(self):
        self.assertEqual(NAME_MAX, 80)


class ValidSnapshotNameTests(unittest.TestCase):
    def test_path_and_percent_allowed_in_snapshot_label(self):
        # vCenter snapshot labels may carry separators that object names reject.
        for good in ("baseline", "pre/upgrade", "C:\\backup", "100% done", "a b"):
            self.assertTrue(valid_snapshot_name(good), repr(good))

    def test_snapshot_bounds_and_shape(self):
        self.assertTrue(valid_snapshot_name("x" * 80))
        self.assertFalse(valid_snapshot_name("x" * 81))
        for bad in ("", None, 5, " ", "  x", "x  ", "\tx", "\u200bx", "a\x00b"):
            self.assertFalse(valid_snapshot_name(bad), repr(bad))

    def test_snapshot_max_constant(self):
        self.assertEqual(SNAPSHOT_NAME_MAX, 80)


if __name__ == "__main__":
    unittest.main()
