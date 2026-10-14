"""Offline removal contract; automatic enrollment intentionally unavailable."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest

from pyVmomi import vim
from vcenter_aiops.application.execution import Engine
from vcenter_aiops.application.providers import ProviderRouter
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store
from test_cluster_lifecycle import ClusterFixture

UUID = "11111111-2222-3333-4444-555555555555"
REMOVE = dict(cluster_id="domain-c1", host_id="host-1", folder_id="group-h1")


class MembershipFixture(ClusterFixture):
    def __init__(self, enrolled=True):
        super().__init__()
        self.host = vim.HostSystem("host-1", self)
        self.host_data = dict(hardware=NS(systemInfo=NS(uuid=UUID)), parent=self.cluster,
                              runtime=NS(connectionState="connected", inMaintenanceMode=True), vm=[])
        self.cluster.host = [self.host] if enrolled else []
        self.folder.MoveIntoFolder_Task = vim.Folder("group-h1", self).MoveIntoFolder_Task

    def InvokeAccessor(self, obj, info):
        return self.host_data[info.name]

    def InvokeMethod(self, obj, info, args):
        self.calls.append((info.wsdlName, list(args)))
        if info.wsdlName != "MoveIntoFolder_Task":
            raise AssertionError("unexpected mutation")
        standalone = NS(_moId="domain-s2", _wsdlName="ComputeResource", parent=self.folder,
                        host=[self.host], resourcePool=NS(vm=[], resourcePool=[]))
        self.host_data["parent"] = standalone
        self.cluster.host = []
        self.task.info.entity = self.folder
        if self.lose:
            raise OSError("response lost")
        return vim.Task("task-1", self)

    def resolve(self, kind, object_id):
        return {"cluster": self.cluster, "folder": self.folder, "host": self.host, "task": self.task}[kind]

    def provider(self):
        from vcenter_aiops.providers.vsphere.membership import Membership
        return Membership(self.si, resolver=self.resolve)


class MembershipTests(unittest.TestCase):
    def engine(self, fixture):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store = Store(Path(directory.name) / "state.db")
        self.addCleanup(store.close)
        return Engine(store, ProviderRouter(None, {"membership": fixture.provider()}), "lab", timeout=0)

    def test_remove_requires_both_confirmations_and_preserves_host(self):
        fixture = MembershipFixture()
        engine = self.engine(fixture)
        plan = engine.preview("cluster remove-host", REMOVE).data
        self.assertEqual(fixture.calls, [])
        for confirmation, second in (("wrong", plan["second_confirmation"]), (plan["digest"], None)):
            with self.assertRaises(OperationError):
                engine.apply(plan["id"], confirmation, second)
        self.assertEqual(fixture.calls, [])
        self.assertIn("保留在 vCenter，转为独立主机", json.dumps(plan, ensure_ascii=False))
        result = engine.apply(plan["id"], plan["digest"], plan["second_confirmation"])
        self.assertEqual(result.status, "succeeded")
        self.assertIn("保留在 vCenter，转为独立主机", json.dumps(result.data, ensure_ascii=False))
        self.assertEqual(len(fixture.calls), 1)
        method, args = fixture.calls[0]
        self.assertEqual(method, "MoveIntoFolder_Task")
        self.assertEqual([h._moId for h in args[0]], ["host-1"])
        self.assertEqual(fixture.host_data["parent"]._wsdlName, "ComputeResource")

    def test_remove_rejects_vms_pools_nonmaintenance_and_wrong_cluster(self):
        mutations = [lambda f: setattr(f.host_data["runtime"], "inMaintenanceMode", False),
                     lambda f: f.host_data.update(vm=[vim.VirtualMachine("vm-2", f)]),
                     lambda f: f.pool.resourcePool.append(NS(_moId="resgroup-2", _wsdlName="ResourcePool")),
                     lambda f: f.host_data.update(parent=NS(_moId="domain-c9")),
                     lambda f: setattr(f.host_data["runtime"], "connectionState", "disconnected"),
                     lambda f: setattr(f.cluster, "host", [])]
        for mutate in mutations:
            fixture = MembershipFixture()
            mutate(fixture)
            with self.subTest(mutate=mutate), self.assertRaises(OperationError):
                fixture.provider().preflight("cluster remove-host", REMOVE)
            self.assertEqual(fixture.calls, [])

    def test_cross_datacenter_destination_is_refused(self):
        fixture = MembershipFixture()
        other_dc = NS(_moId="datacenter-2", _wsdlName="Datacenter")
        other = NS(_moId="group-h2", _wsdlName="Folder", parent=other_dc,
                   childType=["ComputeResource"], disabledMethod=[])
        other_dc.hostFolder = other
        provider = fixture.provider()
        resolve = provider.resolver
        provider.resolver = lambda kind, identity: other if identity == "group-h2" else resolve(kind, identity)
        with self.assertRaises(OperationError):
            provider.preflight("cluster remove-host", {**REMOVE, "folder_id": "group-h2"})
        self.assertEqual(fixture.calls, [])

    def test_changed_uuid_and_cluster_state_block_submit(self):
        for mutate in (lambda f: setattr(f.host_data["hardware"].systemInfo, "uuid", "changed"),
                       lambda f: setattr(f.cluster, "name", "renamed")):
            fixture = MembershipFixture()
            provider = fixture.provider()
            binding = provider.preflight("cluster remove-host", REMOVE)
            mutate(fixture)
            with self.assertRaises(OperationError):
                provider.submit("cluster remove-host", REMOVE, binding)
            self.assertEqual(fixture.calls, [])

    def test_response_loss_stays_unknown_and_never_resubmits(self):
        fixture = MembershipFixture()
        engine = self.engine(fixture)
        plan = engine.preview("cluster remove-host", REMOVE).data
        fixture.lose = True
        result = engine.apply(plan["id"], plan["digest"], plan["second_confirmation"])
        self.assertEqual(result.status, "reconciliation_required")
        self.assertEqual(engine.reconcile(plan["id"]).status, "reconciliation_required")
        engine.apply(plan["id"], plan["digest"], plan["second_confirmation"])
        self.assertEqual(len(fixture.calls), 1)

    def test_wrong_task_key_or_entity_is_refused(self):
        for mutate in (lambda f: setattr(f.task.info, "key", "task-2"),
                       lambda f: setattr(f.task.info, "entity", NS(_moId="group-h9"))):
            fixture = MembershipFixture()
            provider = fixture.provider()
            binding = provider.preflight("cluster remove-host", REMOVE)
            receipt = provider.submit("cluster remove-host", REMOVE, binding)
            mutate(fixture)
            with self.assertRaises(OperationError):
                provider.observe(receipt, binding)

    def test_each_required_privilege_is_checked_on_its_exact_entity(self):
        cases = [("group-h1", "Host.Inventory.AddStandaloneHost"),
                 ("host-1", "Host.Inventory.MoveHost"), ("domain-c1", "Host.Inventory.EditCluster")]
        for entity, privilege in cases:
            fixture = MembershipFixture()
            fixture.content.authorizationManager.HasPrivilegeOnEntity = lambda **kw: [
                not (kw["entity"]._moId == entity and key == privilege) for key in kw["privId"]]
            with self.subTest(entity=entity, privilege=privilege), self.assertRaises(OperationError) as caught:
                fixture.provider().preflight("cluster remove-host", REMOVE)
            self.assertEqual(caught.exception.code, "permission_denied")
            self.assertEqual(fixture.calls, [])

    def test_remove_postcondition_checks_standalone_parent_uuid_and_destination(self):
        for mutate in (lambda f: setattr(f.host_data["parent"], "_wsdlName", "ClusterComputeResource"),
                       lambda f: setattr(f.host_data["hardware"].systemInfo, "uuid", "changed"),
                       lambda f: setattr(f.host_data["parent"], "parent", NS(_moId="group-h9")),
                       lambda f: f.host_data["parent"].resourcePool.resourcePool.append(NS()),
                       lambda f: setattr(f.host_data["runtime"], "inMaintenanceMode", False)):
            fixture = MembershipFixture()
            provider = fixture.provider()
            binding = provider.preflight("cluster remove-host", REMOVE)
            receipt = provider.submit("cluster remove-host", REMOVE, binding)
            observation = provider.observe(receipt, binding)
            self.assertTrue(provider.verify("cluster remove-host", REMOVE, binding, observation))
            mutate(fixture)
            self.assertFalse(provider.verify("cluster remove-host", REMOVE, binding, observation))
