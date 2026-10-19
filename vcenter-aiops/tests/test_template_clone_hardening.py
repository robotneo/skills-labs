"""H-2 / H-3 / L-6 hardening for deploy clone-template.

H-2: an explicit host must not silently swap the requested resource pool for the
     host's parent default resource pool in the CloneVM RelocateSpec.
H-3: before-identity enumeration of a VM folder must tolerate nested Folders/vApps
     in childEntity instead of failing their non ``vm-N`` ids as target_invalid.
L-6: duplicate-name detection must only consider direct VirtualMachine children; a
     nested folder/vApp sharing the display name is not a VM namespace conflict.
"""
from types import SimpleNamespace as NS
import unittest

from pyVmomi import vim

from vcenter_aiops.domain.models import OperationError
from test_template_clone import CloneFixture, BASE


class TemplateCloneHardeningTests(unittest.TestCase):
    def setUp(self):
        self.fx = CloneFixture()

    # -- H-2 ---------------------------------------------------------------

    def test_h2_explicit_host_keeps_requested_pool_not_host_default(self):
        fx = self.fx
        # The host's parent compute resource advertises a *different* default
        # resource pool than the one explicitly requested/validated in preflight.
        default_pool = vim.ResourcePool("resgroup-default", fx.stub)
        fx.stub.values[("domain-c1", "resourcePool")] = default_pool
        provider = fx.provider()
        binding = provider.preflight("deploy clone-template", dict(BASE))
        provider.submit("deploy clone-template", dict(BASE), binding)
        location = fx.clone_kwargs()["spec"].location
        self.assertEqual(location.pool._moId, "resgroup-1",
                         "Clone must land in the explicitly validated pool")
        self.assertNotEqual(location.pool._moId, "resgroup-default")
        self.assertEqual(location.host._moId, "host-1")
        self.assertEqual(location.datastore._moId, "datastore-1")

    def test_h2_drs_clone_uses_requested_pool_without_host(self):
        fx = self.fx
        p = {k: v for k, v in BASE.items() if k != "host_id"}
        provider = fx.provider()
        binding = provider.preflight("deploy clone-template", p)
        provider.submit("deploy clone-template", p, binding)
        location = fx.clone_kwargs()["spec"].location
        self.assertEqual(location.pool._moId, "resgroup-1")
        self.assertIsNone(location.host)

    # -- H-3 ---------------------------------------------------------------

    def test_h3_folder_with_nested_folder_and_vapp_does_not_break_before_set(self):
        fx = self.fx
        nested_folder = vim.Folder("group-v2", fx.stub)
        fx.stub.values[("group-v2", "name")] = "nested"
        vapp = NS(_moId="resgroup-v9", _wsdlName="VirtualApp", name="some-vapp")
        direct_vm = vim.VirtualMachine("vm-7", fx.stub)
        fx.stub.values[("vm-7", "name")] = "other-vm"
        fx.stub.values[("group-v1", "childEntity")] = [nested_folder, vapp, direct_vm]
        binding = fx.provider().preflight("deploy clone-template", dict(BASE))
        existing = binding["before"]["existing_ids"]
        self.assertIn("vm-7", existing)
        self.assertNotIn("group-v2", existing)
        self.assertNotIn("resgroup-v9", existing)

    def test_h3_non_vm_folder_children_without_vm_ids_are_skipped_not_rejected(self):
        # Previously every childEntity went through the strict vm-N identity check
        # and a nested folder aborted the whole preflight as target_invalid.
        fx = self.fx
        nested_folder = vim.Folder("group-v3", fx.stub)
        fx.stub.values[("group-v3", "name")] = "nested-3"
        fx.stub.values[("group-v1", "childEntity")] = [nested_folder]
        binding = fx.provider().preflight("deploy clone-template", dict(BASE))
        self.assertEqual(binding["before"]["existing_ids"], [])

    # -- L-6 ---------------------------------------------------------------

    def test_l6_nested_folder_sharing_name_is_not_a_vm_conflict(self):
        fx = self.fx
        nested_folder = vim.Folder("group-v4", fx.stub)
        fx.stub.values[("group-v4", "name")] = "target"
        fx.stub.values[("group-v1", "childEntity")] = [nested_folder]
        # Must not raise target_exists: a folder named "target" is not a VM.
        binding = fx.provider().preflight("deploy clone-template", dict(BASE))
        self.assertEqual(binding["requested"]["name"], "target")

    def test_l6_vapp_sharing_name_is_not_a_vm_conflict(self):
        fx = self.fx
        vapp = NS(_moId="resgroup-v8", _wsdlName="VirtualApp", name="target")
        fx.stub.values[("group-v1", "childEntity")] = [vapp]
        binding = fx.provider().preflight("deploy clone-template", dict(BASE))
        self.assertEqual(binding["requested"]["name"], "target")

    def test_l6_direct_vm_with_same_name_still_rejected(self):
        fx = self.fx
        other = vim.VirtualMachine("vm-9", fx.stub)
        fx.stub.values[("vm-9", "name")] = "target"
        fx.stub.values[("group-v1", "childEntity")] = [other]
        with self.assertRaises(OperationError) as e:
            fx.provider().preflight("deploy clone-template", dict(BASE))
        self.assertEqual(e.exception.code, "target_exists")
        self.assertEqual(e.exception.exit_code, 4)


if __name__ == "__main__":
    unittest.main()
