"""M-8: OVA descriptor uniqueness and post-import verify placement evidence."""
import io
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.providers.vsphere.ovf_deploy import OvfDeploy

from test_ovf_deploy import FakeSi, healthy_topology, base_params, DESCRIPTOR


def ova_bytes(entries):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for name, data in entries:
            info = tarfile.TarInfo(name=name)
            payload = data.encode("utf-8")
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


class DescriptorUniquenessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.work = str(root / "work")
        self.si = FakeSi()

    def tearDown(self):
        self.temp.cleanup()

    def _provider(self):
        return OvfDeploy(self.si, resolver=lambda kind, oid: None)

    def test_multiple_descriptors_rejected(self):
        ova = Path(self.work).parent / "two.ova"
        ova.parent.mkdir(parents=True, exist_ok=True)
        ova.write_bytes(ova_bytes([("a.ovf", DESCRIPTOR), ("b.ovf", DESCRIPTOR),
                                   ("disk1.vmdk", "x")]))
        params = base_params(str(ova), self.work)
        with self.assertRaises(OperationError) as error:
            self._provider()._prepared("deploy ova", params)
        self.assertEqual(error.exception.code, "ovf_descriptor_ambiguous")
        self.assertEqual(error.exception.exit_code, 2)

    def test_single_descriptor_accepted(self):
        ova = Path(self.work).parent / "one.ova"
        ova.parent.mkdir(parents=True, exist_ok=True)
        ova.write_bytes(ova_bytes([("app.ovf", DESCRIPTOR), ("disk1.vmdk", "x")]))
        params = base_params(str(ova), self.work)
        descriptor, validated, directory = self._provider()._prepared("deploy ova", params)
        self.assertEqual(validated["files"], ["disk1.vmdk"])


def placement_provider(vm_overrides=None):
    topo = healthy_topology()
    attrs = {
        "_moId": "vm-100",
        "config": NS(instanceUuid="uuid-vm"),
        "runtime": NS(powerState="poweredOff", host=topo["host"]),
        "name": "imported-vm",
        "parent": topo["folder"],
        "resourcePool": topo["pool"],
        "datastore": [topo["datastore"]],
        "network": [topo["network"]],
    }
    attrs.update(vm_overrides or {})
    vm = NS(**attrs)

    def resolver(kind, object_id):
        if kind == "vm":
            return vm
        return {"pool": topo["pool"], "host": topo["host"], "folder": topo["folder"],
                "datastore": topo["datastore"], "network": topo["network"]}[kind]

    return OvfDeploy(FakeSi(), resolver=resolver), topo, vm


class VerifyPlacementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.ovf_dir = root / "pkg"
        self.ovf_dir.mkdir()
        (self.ovf_dir / "descriptor.ovf").write_text(DESCRIPTOR, encoding="utf-8")
        (self.ovf_dir / "disk1.vmdk").write_text("disk", encoding="utf-8")
        self.work = str(root / "work")

    def tearDown(self):
        self.temp.cleanup()

    def _params(self):
        return base_params(str(self.ovf_dir), self.work)

    def _success(self, provider):
        binding = provider.preflight("deploy ovf", self._params())
        observation = {"state": "success", "result_id": "vm-100",
                       "entity_name": "imported-vm"}
        return binding, observation

    def test_verify_passes_when_entity_matches_placement_snapshot(self):
        provider, _, _ = placement_provider({})
        binding, observation = self._success(provider)
        self.assertTrue(provider.verify("deploy ovf", self._params(), binding, observation))

    def test_verify_fails_when_folder_differs(self):
        provider, _, _ = placement_provider({"parent": NS(_moId="group-v999")})
        binding, observation = self._success(provider)
        self.assertFalse(provider.verify("deploy ovf", self._params(), binding, observation))

    def test_verify_fails_when_pool_differs(self):
        provider, _, _ = placement_provider({"resourcePool": NS(_moId="resgroup-999")})
        binding, observation = self._success(provider)
        self.assertFalse(provider.verify("deploy ovf", self._params(), binding, observation))

    def test_verify_fails_when_host_differs(self):
        provider, topo, _ = placement_provider({})
        other_host = NS(_moId="host-999")
        # rebuild vm runtime to point elsewhere
        provider.resolver = (lambda kind, oid:
                             NS(_moId="vm-100", config=NS(instanceUuid="u"),
                                runtime=NS(powerState="poweredOff", host=other_host),
                                name="imported-vm", parent=topo["folder"],
                                resourcePool=topo["pool"], datastore=[topo["datastore"]],
                                network=[topo["network"]]) if kind == "vm"
                             else {"pool": topo["pool"], "host": topo["host"],
                                   "folder": topo["folder"], "datastore": topo["datastore"],
                                   "network": topo["network"]}[kind])
        binding, observation = self._success(provider)
        self.assertFalse(provider.verify("deploy ovf", self._params(), binding, observation))

    def test_verify_fails_when_datastore_differs(self):
        provider, _, _ = placement_provider({"datastore": [NS(_moId="datastore-999")]})
        binding, observation = self._success(provider)
        self.assertFalse(provider.verify("deploy ovf", self._params(), binding, observation))

    def test_verify_fails_when_network_missing(self):
        provider, _, _ = placement_provider({"network": []})
        binding, observation = self._success(provider)
        self.assertFalse(provider.verify("deploy ovf", self._params(), binding, observation))

    def test_verify_fails_when_name_differs(self):
        provider, _, _ = placement_provider({"name": "renamed-vm"})
        binding, observation = self._success(provider)
        self.assertFalse(provider.verify("deploy ovf", self._params(), binding, observation))

    def test_verify_without_placement_snapshot_keeps_poweredoff_check(self):
        # Backward compatibility: a binding with no preview placement snapshot
        # falls back to existence + poweredOff only.
        provider, _, _ = placement_provider({})
        observation = {"state": "success", "result_id": "vm-100"}
        self.assertTrue(provider.verify("deploy ovf", {}, {"server_uuid": "uuid-1"}, observation))


if __name__ == "__main__":
    unittest.main()
