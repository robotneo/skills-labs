import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from vcenter_aiops.domain.models import SubmissionRejected
from vcenter_aiops.providers.vsphere.ovf_deploy import OvfDeploy


DESCRIPTOR = """<?xml version="1.0"?>
<Envelope xmlns="http://schemas.dmtf.org/ovf/envelope/1"
 xmlns:ovf="http://schemas.dmtf.org/ovf/envelope/1">
  <NetworkSection>
    <Network ovf:name="VM Network"/>
  </NetworkSection>
  <References>
    <File ovf:href="disk1.vmdk"/>
  </References>
</Envelope>"""


def base_params(source, work):
    return {"source": source, "work_dir": work, "name": "imported-vm",
            "resource_pool_id": "resgroup-1", "host_id": "host-1",
            "folder_id": "group-v1", "datastore_id": "datastore-1",
            "network_mapping": {"VM Network": "network-1"}}


class FakeOvfManager:
    def __init__(self, reject=False):
        self.reject = reject
        self.calls = []

    def CreateImportSpec(self, ovfDescriptor, resourcePool, datastore, cisp):
        self.calls.append({"descriptor": ovfDescriptor, "pool": resourcePool,
                           "datastore": datastore, "cisp": cisp})
        if self.reject:
            return NS(error=[NS(localizedMessage="bad")], importSpec=None)
        return NS(error=[], importSpec=NS(marker=True))


class FakePool:
    def __init__(self):
        self.imports = []

    def ImportVApp(self, spec, folder, host):
        self.imports.append({"spec": spec, "folder": folder, "host": host})
        return NS(_moId="HttpNfcLease-1",
                  info=NS(entity=NS(_moId="vm-100", name="imported-vm")))


class FakeSi:
    def __init__(self, reject=False):
        self.pool = FakePool()
        self.ovf_manager = FakeOvfManager(reject)
        self._stub = object()
        self.content = NS(
            about=NS(instanceUuid="uuid-1"),
            ovfManager=self.ovf_manager)

    def RetrieveContent(self):
        return self.content


class OvfDeployTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.ovf_dir = root / "pkg"
        self.ovf_dir.mkdir()
        (self.ovf_dir / "descriptor.ovf").write_text(DESCRIPTOR, encoding="utf-8")
        (self.ovf_dir / "disk1.vmdk").write_text("diskbytes", encoding="utf-8")
        self.work = str(root / "work")
        self.si = FakeSi()

    def tearDown(self):
        self.temp.cleanup()

    def make(self):
        resolved = {"pool": self.si.pool, "host": NS(_moId="host-1"),
                    "folder": NS(_moId="group-v1"), "datastore": NS(_moId="datastore-1"),
                    "network": NS(_moId="network-1"),
                    "vm": None}

        def resolver(kind, object_id):
            if kind == "vm":
                return self.vm_obj
            return resolved[kind]

        driven = []

        def driver(lease, files, upload, deadline=None):
            driven.append({"lease": lease, "files": files})
            return lease.info

        def builder(params, host, validated):
            return NS(entityName=params["name"], hostSystem=host,
                      networkMapping=[NS(name=name, network=target)
                                      for name, target in validated["network_mapping"].items()])

        provider = OvfDeploy(self.si, resolver=resolver,
                             upload=lambda t, i: None, driver=driver,
                             cisp_builder=builder)
        provider._driven = driven
        return provider

    def test_preflight_returns_scope_and_warnings(self):
        provider = self.make()
        binding = provider.preflight("deploy ovf", base_params(str(self.ovf_dir), self.work))
        self.assertEqual(binding["kind"], "ovf")
        self.assertEqual(binding["before"]["files"], ["disk1.vmdk"])
        self.assertEqual(binding["scope"]["datastore_id"], "datastore-1")
        self.assertTrue(binding["warnings"])

    def test_submit_drives_import_and_returns_terminal_receipt(self):
        provider = self.make()
        self.vm_obj = NS(_moId="vm-100")
        binding = provider.preflight("deploy ovf", base_params(str(self.ovf_dir), self.work))
        receipt = provider.submit("deploy ovf",
                                  base_params(str(self.ovf_dir), self.work), binding)
        self.assertEqual(receipt["state"], "success")
        self.assertEqual(receipt["result_id"], "vm-100")
        # Server import spec created with explicit network mapping.
        cisp = self.si.ovf_manager.calls[0]["cisp"]
        self.assertEqual(len(cisp.networkMapping), 1)
        self.assertEqual(cisp.networkMapping[0].name, "VM Network")
        # Lease driven once with descriptor files.
        self.assertEqual(provider._driven[0]["files"], ["disk1.vmdk"])
        # ImportVApp invoked with folder/host.
        self.assertEqual(len(self.si.pool.imports), 1)

    def test_submit_rejects_incomplete_mapping_before_remote_write(self):
        provider = self.make()
        params = base_params(str(self.ovf_dir), self.work)
        params["network_mapping"] = {}
        with self.assertRaises(SubmissionRejected) as ctx:
            provider.submit("deploy ovf", params, {})
        self.assertEqual(ctx.exception.code, "ovf_network_mapping_incomplete")
        self.assertEqual(self.si.pool.imports, [])  # no remote write attempted

    def test_server_spec_error_is_uncertainty_not_rejection(self):
        si = FakeSi(reject=True)

        def builder(params, host, validated):
            return NS(networkMapping=list(validated["network_mapping"]))

        provider = OvfDeploy(si,
                             resolver=lambda k, i: NS(_moId=i),
                             upload=lambda t, i: None,
                             driver=lambda l, f, u, deadline=None: None,
                             cisp_builder=builder)
        params = base_params(str(self.ovf_dir), self.work)
        binding = provider.preflight("deploy ovf", params)
        # This happens after validation; it surfaces as a plain OperationError.
        from vcenter_aiops.domain.models import OperationError
        with self.assertRaises(OperationError) as ctx:
            provider.submit("deploy ovf", params, binding)
        self.assertEqual(ctx.exception.code, "ovf_import_spec_invalid")

    def test_observe_and_verify_powered_off_entity(self):
        provider = self.make()
        self.vm_obj = NS(_moId="vm-100",
                         config=NS(instanceUuid="uuid-vm"),
                         runtime=NS(powerState="poweredOff"))
        receipt = {"state": "success", "result_id": "vm-100",
                   "entity_name": "imported-vm"}
        binding = {"server_uuid": "uuid-1"}
        observation = provider.observe(receipt, binding)
        self.assertEqual(observation["state"], "success")
        self.assertTrue(provider.verify("deploy ovf", {}, binding, observation))

    def test_verify_fails_when_powered_on(self):
        provider = self.make()
        self.vm_obj = NS(_moId="vm-100", config=NS(instanceUuid="x"),
                         runtime=NS(powerState="poweredOn"))
        observation = {"state": "success", "result_id": "vm-100"}
        binding = {"server_uuid": "uuid-1"}
        self.assertFalse(provider.verify("deploy ovf", {}, binding, observation))

    def test_observe_rejects_foreign_server(self):
        provider = self.make()
        from vcenter_aiops.domain.models import OperationError
        with self.assertRaises(OperationError) as ctx:
            provider.observe({"state": "success"}, {"server_uuid": "other"})
        self.assertEqual(ctx.exception.code, "server_mismatch")


if __name__ == "__main__":
    unittest.main()
