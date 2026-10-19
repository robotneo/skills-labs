"""L-11 regression: disk/resource capacities must fail as invalid_arguments
(exit 2) on non-numeric, boolean, zero or negative input — never reach the
provider and surface as a generic internal error (exit 5).

The protection lives in the transport-neutral contract layer (strict integer
check that also rejects bool, plus minimum=1) and the CLI argparse ``type=int``.
No production code change is required; these tests lock that boundary against
regression (the original report flagged an ``int()`` coercion concern that is
already covered by the schema + argparse design).
"""
import unittest

from vcenter_aiops.application.registry import lookup
from vcenter_aiops.domain.contracts import Command, Parameter
from vcenter_aiops.domain.models import OperationError


class IntegerParameterContractTests(unittest.TestCase):
    def test_integer_parameter_rejects_non_integer_string(self):
        spec = Command("t", "remote_write", "d", "x:y",
                       (Parameter("capacity_gb", "integer", required=True, minimum=1),))
        for bad in ("40", "40.5", "abc", [40], None, True, False):
            with self.subTest(bad=bad):
                with self.assertRaises(OperationError) as error:
                    spec.validate({"capacity_gb": bad})
                self.assertEqual(error.exception.code, "invalid_arguments")
                self.assertEqual(error.exception.exit_code, 2)

    def test_integer_parameter_rejects_zero_and_negative_via_minimum(self):
        spec = Command("t", "remote_write", "d", "x:y",
                       (Parameter("capacity_gb", "integer", required=True, minimum=1),))
        for bad in (0, -1, -100):
            with self.subTest(bad=bad):
                with self.assertRaises(OperationError) as error:
                    spec.validate({"capacity_gb": bad})
                self.assertEqual(error.exception.code, "invalid_arguments")
                self.assertEqual(error.exception.exit_code, 2)

    def test_positive_integer_accepted(self):
        spec = Command("t", "remote_write", "d", "x:y",
                       (Parameter("capacity_gb", "integer", required=True, minimum=1),))
        self.assertEqual(spec.validate({"capacity_gb": 40})["capacity_gb"], 40)


class VmReconfigureCapacityTests(unittest.TestCase):
    def setUp(self):
        self.spec = lookup("vm reconfigure")

    def test_top_level_cpu_memory_reject_bad_input(self):
        for key in ("cpu", "memory_gb"):
            for bad in ("2", 0, -1, True):
                with self.subTest(key=key, bad=bad):
                    with self.assertRaises(OperationError) as error:
                        self.spec.validate({"vm_id": "vm-1", key: bad})
                    self.assertEqual(error.exception.code, "invalid_arguments")
                    self.assertEqual(error.exception.exit_code, 2)

    def _add_disk(self, capacity):
        return {"vm_id": "vm-1",
                "disks": [{"operation": "add", "device_key": -1, "controller_key": 0,
                           "unit_number": 0, "datastore_id": "datastore-1",
                           "capacity_gb": capacity}]}

    def test_nested_disk_capacity_rejects_string_zero_negative_bool(self):
        for bad in ("40", 0, -5, True):
            with self.subTest(bad=bad):
                with self.assertRaises(OperationError) as error:
                    self.spec.validate(self._add_disk(bad))
                self.assertEqual(error.exception.code, "invalid_arguments")
                self.assertEqual(error.exception.exit_code, 2)

    def test_nested_disk_capacity_accepts_positive_integer(self):
        validated = self.spec.validate(self._add_disk(40))
        self.assertEqual(validated["disks"][0]["capacity_gb"], 40)


if __name__ == "__main__":
    unittest.main()
