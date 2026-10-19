import unittest
from types import SimpleNamespace

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.providers.vsphere.reads import Reads


class _Long(int):
    """Stand-in for vmodl xsd:long/xsd:int values decoded as int subclasses."""


class _FakeProvider:
    def __init__(self, cpu, memory_mb):
        self._cpu = cpu
        self._memory = memory_mb

    def vm(self, vm_id):
        return SimpleNamespace(
            _moId=vm_id,
            config=SimpleNamespace(
                instanceUuid="uuid-1",
                hardware=SimpleNamespace(numCPU=self._cpu, memoryMB=self._memory),
            ),
        )


class PresetHardwareTypeTests(unittest.TestCase):
    def _reader(self, cpu, memory_mb):
        return Reads(_FakeProvider(cpu, memory_mb))

    def test_plain_ints_are_represented(self):
        self.assertEqual(
            self._reader(4, 8192).preset_hardware("vm-1"),
            {"cpu": 4, "memory_gb": 8},
        )

    def test_vmodl_64bit_long_subclasses_are_accepted_h7(self):
        # Real vCenter decodes xsd:long numeric fields as int subclasses; the old
        # ``type(x) is int`` guard wrongly rejected them as preset_hardware_unsupported.
        reader = self._reader(_Long(16), _Long(65536))
        self.assertEqual(
            reader.preset_hardware("vm-1"), {"cpu": 16, "memory_gb": 64}
        )

    def test_bool_cpu_is_rejected_even_though_bool_is_int_subclass(self):
        with self.assertRaises(OperationError) as failure:
            self._reader(True, 8192).preset_hardware("vm-1")
        self.assertEqual(failure.exception.code, "preset_hardware_unsupported")
        self.assertEqual(failure.exception.exit_code, 4)

    def test_bool_memory_is_rejected(self):
        with self.assertRaises(OperationError) as failure:
            self._reader(4, True).preset_hardware("vm-1")
        self.assertEqual(failure.exception.code, "preset_hardware_unsupported")
        self.assertEqual(failure.exception.exit_code, 4)

    def test_none_values_are_rejected(self):
        with self.assertRaises(OperationError) as failure:
            self._reader(None, None).preset_hardware("vm-1")
        self.assertEqual(failure.exception.code, "preset_hardware_unsupported")
        self.assertEqual(failure.exception.exit_code, 4)

    def test_non_numeric_strings_are_rejected(self):
        with self.assertRaises(OperationError) as failure:
            self._reader("4", "8192").preset_hardware("vm-1")
        self.assertEqual(failure.exception.code, "preset_hardware_unsupported")
        self.assertEqual(failure.exception.exit_code, 4)

    def test_zero_and_negative_cpu_are_rejected(self):
        for bad_cpu in (0, -2):
            with self.assertRaises(OperationError) as failure:
                self._reader(bad_cpu, 8192).preset_hardware("vm-1")
            self.assertEqual(failure.exception.code, "preset_hardware_unsupported")

    def test_fractional_gib_and_sub_minimum_memory_are_rejected(self):
        for bad_memory in (1536, 512, 8191):
            with self.assertRaises(OperationError) as failure:
                self._reader(2, bad_memory).preset_hardware("vm-1")
            self.assertEqual(
                failure.exception.code, "preset_hardware_unsupported",
                "memory_mb=%r must stay fail-closed" % (bad_memory,),
            )


if __name__ == "__main__":
    unittest.main()
