"""Offline SDK transport fixtures; no vCenter connections."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest

from pyVmomi import vim, vmodl
from vcenter_aiops.application.execution import Engine
from vcenter_aiops.application.providers import ProviderRouter
from vcenter_aiops.application.registry import lookup
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store
from test_license_entitlements import assignment


class ClusterFixture:
    def __init__(self):
        self.calls, self.allowed = [], True
        self.lose, self.update, self.deleted = False, True, False
        self.read_fault = None
        self.dc = NS(_moId="datacenter-1", _wsdlName="Datacenter")
        self.folder = NS(_moId="group-h1", _wsdlName="Folder", parent=self.dc,
                         childType=["vim.Folder", "vim.ComputeResource"], childEntity=[], disabledMethod=[])
        self.dc.hostFolder = self.folder
        self.pool = NS(_moId="resgroup-1", _wsdlName="ResourcePool", vm=[], resourcePool=[])
        self.cluster = NS(_moId="domain-c1", _wsdlName="ClusterComputeResource", name="lab",
                          parent=self.folder, host=[], resourcePool=self.pool, disabledMethod=[],
                          configurationEx=NS(dasConfig=NS(enabled=False), drsConfig=NS(
                              enabled=False, defaultVmBehavior="manual", vmotionRate=3)))
        self.pool.owner = self.cluster
        self.folder.CreateClusterEx = vim.Folder("group-h1", self).CreateClusterEx
        sdk = vim.ClusterComputeResource("domain-c1", self)
        self.cluster.ReconfigureComputeResource_Task = sdk.ReconfigureComputeResource_Task
        self.cluster.Destroy_Task = sdk.Destroy_Task
        self.task = NS(info=NS(key="task-1", entity=self.cluster, state="success", error=None,
                               progress=100, cancelable=True), CancelTask=lambda: None)
        self.content = NS(about=NS(instanceUuid="server-1", apiVersion="8.0.3", apiType="VirtualCenter"),
                          sessionManager=NS(currentSession=NS(key="session-1")),
                          authorizationManager=NS(HasPrivilegeOnEntity=lambda **kw: [self.allowed] * len(kw["privId"])),
                          licenseManager=NS(licenseAssignmentManager=NS(QueryAssignedLicenses=lambda **kw:
                              [assignment(kw["entityId"], ("das", "drs", "vmotion"))])))
        self.si = NS(RetrieveContent=lambda: self.content, _stub=self)

    def InvokeMethod(self, obj, info, args):
        self.calls.append((info.wsdlName, list(args)))
        if self.update:
            if info.wsdlName == "CreateClusterEx":
                self.cluster.name = args[0]
                self.folder.childEntity.append(self.cluster)
                spec = args[1]
            elif info.wsdlName == "ReconfigureComputeResource_Task":
                spec = args[0]
            else:
                self.deleted = True
                spec = None
            if spec:
                for part in ("dasConfig", "drsConfig"):
                    source = getattr(spec, part)
                    if source:
                        for key in ("enabled", "defaultVmBehavior", "vmotionRate"):
                            value = getattr(source, key, None)
                            if value is not None:
                                setattr(getattr(self.cluster.configurationEx, part), key, value)
        if self.lose:
            raise OSError("response lost")
        return vim.ClusterComputeResource("domain-c1", self) if info.wsdlName == "CreateClusterEx" else vim.Task("task-1", self)

    def resolve(self, kind, object_id):
        if kind == "cluster":
            if self.read_fault:
                raise self.read_fault
            if self.deleted:
                raise vmodl.fault.ManagedObjectNotFound(obj=vim.ClusterComputeResource(object_id, self))
            return self.cluster
        return {"folder": self.folder, "task": self.task}[kind]

    def provider(self):
        if importlib.util.find_spec("vcenter_aiops.providers.vsphere.clusters") is None:
            raise AssertionError("cluster lifecycle provider missing")
        from vcenter_aiops.providers.vsphere.clusters import Clusters
        return Clusters(self.si, resolver=self.resolve)


class ClusterTests(unittest.TestCase):
    def engine(self, fixture):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = Store(Path(temporary.name) / "state.db")
        self.addCleanup(store.close)
        return Engine(store, ProviderRouter(None, providers={"cluster": fixture.provider()}), "lab", timeout=0)

    def test_create_configure_delete_through_engine(self):
        cases = [("cluster create", {"folder_id": "group-h1", "name": "new"}),
                 ("cluster configure", {"cluster_id": "domain-c1", "ha_enabled": False}),
                 ("cluster delete", {"cluster_id": "domain-c1"})]
        for command, params in cases:
            with self.subTest(command=command):
                fixture = ClusterFixture()
                engine = self.engine(fixture)
                plan = engine.preview(command, params).data
                self.assertEqual(fixture.calls, [])
                result = engine.apply(plan["id"], plan["digest"], plan.get("second_confirmation"))
                self.assertEqual(result.status, "succeeded")
                receipt = result.data["execution"][0]["receipt"]
                if command == "cluster create":
                    self.assertNotIn("task_id", receipt)
                    self.assertEqual(receipt["object_id"], "domain-c1")
                    self.assertIsNone(result.data["execution"][0]["remote_task"])
                    spec = fixture.calls[0][1][1]
                    self.assertFalse(spec.dasConfig.enabled)
                    self.assertEqual(spec.drsConfig.defaultVmBehavior, "manual")
                elif command == "cluster configure":
                    spec, modify = fixture.calls[0][1]
                    self.assertTrue(modify)
                    self.assertIsInstance(spec, vim.cluster.ConfigSpecEx)
                    self.assertIsNone(spec.drsConfig)

    def test_contracts_are_strict_and_default_create_is_safe(self):
        self.assertEqual(lookup("cluster create").validate({"folder_id": "group-h1", "name": "new"})["drs_automation"], "manual")
        self.assertEqual(lookup("cluster delete").risk, "destructive")
        self.assertEqual(lookup("cluster configure").provider_kind, "cluster")

    def test_bare_host_folder_child_types_support_all_cluster_operations(self):
        for command, params in (("cluster create", {"folder_id": "group-h1", "name": "new"}),
                                ("cluster configure", {"cluster_id": "domain-c1", "ha_enabled": False}),
                                ("cluster delete", {"cluster_id": "domain-c1"})):
            with self.subTest(command=command):
                fixture = ClusterFixture()
                fixture.folder.childType = ["Folder", "ComputeResource"]
                engine = self.engine(fixture)
                plan = engine.preview(command, params).data
                self.assertEqual(fixture.calls, [])
                result = engine.apply(plan["id"], plan["digest"], plan.get("second_confirmation"))
                self.assertEqual(result.status, "succeeded")
                self.assertEqual(len(fixture.calls), 1)

    def test_license_ha_token(self):
        from test_license_entitlements import LicenseEntitlementTests
        checker = LicenseEntitlementTests().checker([assignment(features=("das",))])
        self.assertEqual(checker.require("host-1", ("das",), "server-1")["features"], ["das"])

    def test_rejects_invalid_configuration_and_empty_enable(self):
        for changes in ({}, {"drs_enabled": False}, {"drs_enabled": True}, {"ha_enabled": True},
                        {"drs_automation": "fullyAutomated"}, {"drs_vmotion_rate": 0}, {"ha_enabled": 1}):
            with self.subTest(changes=changes):
                fixture = ClusterFixture()
                with self.assertRaises(OperationError):
                    fixture.provider().preflight("cluster configure", {"cluster_id": "domain-c1", **changes})
                self.assertEqual(fixture.calls, [])

    def test_identity_permission_version_disabled_and_nonempty_rejections(self):
        mutations = [lambda f: setattr(f, "allowed", False),
                     lambda f: setattr(f.content.about, "apiVersion", "9.0"),
                     lambda f: setattr(f.cluster, "_wsdlName", "ComputeResource"),
                     lambda f: setattr(f.cluster, "disabledMethod", ["Destroy_Task"]),
                     lambda f: setattr(f.cluster, "host", [NS(_moId="host-1")]),
                     lambda f: setattr(f.pool, "vm", [NS(_moId="vm-1")]),
                     lambda f: setattr(f.pool, "resourcePool", [NS(_moId="resgroup-2")]),
                     lambda f: setattr(f.pool, "vm", None)]
        for mutate in mutations:
            fixture = ClusterFixture()
            mutate(fixture)
            with self.assertRaises(OperationError):
                fixture.provider().preflight("cluster delete", {"cluster_id": "domain-c1"})
            self.assertEqual(fixture.calls, [])

    def test_create_rejects_wrong_folder_conflicts_or_missing_permission(self):
        for mutate in (lambda f: setattr(f.folder, "childType", ["vim.VirtualMachine"]),
                       lambda f: f.folder.childEntity.append(f.cluster),
                       lambda f: setattr(f.dc, "hostFolder", NS(_moId="group-h2")),
                       lambda f: setattr(f, "allowed", False)):
            fixture = ClusterFixture()
            mutate(fixture)
            with self.assertRaises(OperationError):
                fixture.provider().preflight("cluster create", {"folder_id": "group-h1", "name": "lab"})

    def test_lost_receipts_and_wrong_confirmation_never_repeat_writes(self):
        for command, params in (("cluster create", {"folder_id": "group-h1", "name": "new"}),
                                ("cluster configure", {"cluster_id": "domain-c1", "ha_enabled": False}),
                                ("cluster delete", {"cluster_id": "domain-c1"})):
            fixture = ClusterFixture()
            engine = self.engine(fixture)
            plan = engine.preview(command, params).data
            with self.assertRaises(OperationError):
                engine.apply(plan["id"], "wrong")
            self.assertEqual(fixture.calls, [])
            fixture.lose = True
            self.assertEqual(engine.apply(plan["id"], plan["digest"], plan.get("second_confirmation")).status, "reconciliation_required")
            self.assertEqual(engine.reconcile(plan["id"]).status, "reconciliation_required")
            engine.apply(plan["id"], plan["digest"], plan.get("second_confirmation"))
            self.assertEqual(len(fixture.calls), 1)

    def test_postverification_does_not_treat_sdk_errors_as_deleted(self):
        fixture = ClusterFixture()
        provider = fixture.provider()
        binding = provider.preflight("cluster delete", {"cluster_id": "domain-c1"})
        for fault in (vim.fault.NoPermission(), vmodl.RuntimeFault(), OSError()):
            fixture.read_fault = fault
            self.assertFalse(provider.verify("cluster delete", {"cluster_id": "domain-c1"}, binding, {}))
        fixture.read_fault = None
        fixture.deleted = True
        self.assertTrue(provider.verify("cluster delete", {"cluster_id": "domain-c1"}, binding, {}))

    def test_task_owner_postconditions_and_stale_binding(self):
        fixture = ClusterFixture()
        provider = fixture.provider()
        params = {"cluster_id": "domain-c1", "ha_enabled": False}
        binding = provider.preflight("cluster configure", params)
        receipt = provider.submit("cluster configure", params, binding)
        fixture.task.info.entity = NS(_moId="domain-c2")
        with self.assertRaises(OperationError):
            provider.observe(receipt, binding)
        fixture.cluster.configurationEx.dasConfig.enabled = True
        self.assertFalse(provider.verify("cluster configure", params, binding, {}))
        with self.assertRaises(OperationError):
            provider.submit("cluster configure", params, binding)
        self.assertEqual(len(fixture.calls), 1)

    def test_same_target_plan_is_rejected(self):
        fixture = ClusterFixture()
        with self.assertRaises(OperationError):
            fixture.provider().bind_steps([{"command": "cluster configure", "params": {"cluster_id": "domain-c1", "ha_enabled": False}}] * 2)

    def member(self, fixture):
        host = NS(_moId="host-1", _wsdlName="HostSystem", parent=fixture.cluster,
                  hardware=NS(systemInfo=NS(uuid="host-uuid-1")),
                  runtime=NS(connectionState="connected", inMaintenanceMode=False), vm=[])
        fixture.cluster.host = [host]
        return host

    def test_enable_features_bind_all_host_entitlements_and_migration_impact(self):
        fixture = ClusterFixture()
        self.member(fixture)
        provider = fixture.provider()
        params = {"cluster_id": "domain-c1", "ha_enabled": True,
                  "drs_automation": "fullyAutomated", "drs_vmotion_rate": 5}
        binding = provider.preflight("cluster configure", params)
        self.assertEqual(binding["license_evidence"][0]["features"], ["das", "drs", "vmotion"])
        self.assertIn("may migrate", " ".join(binding["impact"]["effects"]))
        receipt = provider.submit("cluster configure", params, binding)
        self.assertTrue(provider.verify("cluster configure", params, binding, provider.observe(receipt, binding)))
        spec, modify = fixture.calls[0][1]
        self.assertTrue(modify)
        self.assertIsNone(spec.drsConfig.enabled)
        self.assertEqual(spec.drsConfig.vmotionRate, 5)
        fixture.content.licenseManager.licenseAssignmentManager.QueryAssignedLicenses = lambda **kw: []
        with self.assertRaises(OperationError):
            provider.preflight("cluster configure", params)

    def test_legacy_disabled_semantics_are_explicit_and_contradictions_rejected(self):
        fixture = ClusterFixture()
        fixture.content.about.apiVersion = "6.7.0"
        self.member(fixture)
        provider = fixture.provider()
        params = {"cluster_id": "domain-c1", "drs_enabled": False}
        binding = provider.preflight("cluster configure", params)
        provider.submit("cluster configure", params, binding)
        spec = fixture.calls[0][1][0]
        self.assertFalse(spec.drsConfig.enabled)
        self.assertIsNone(spec.drsConfig.defaultVmBehavior)
        for changes in ({"drs_enabled": False, "drs_automation": "fullyAutomated"},
                        {"drs_automation": "fullyAutomated"}):
            with self.assertRaises(OperationError):
                provider.preflight("cluster configure", {"cluster_id": "domain-c1", **changes})

    def test_success_without_postconditions_is_uncertain_for_every_operation(self):
        cases = [("cluster create", {"folder_id": "group-h1", "name": "new"}),
                 ("cluster configure", {"cluster_id": "domain-c1", "ha_enabled": True}),
                 ("cluster delete", {"cluster_id": "domain-c1"})]
        for command, params in cases:
            fixture = ClusterFixture()
            if command == "cluster configure":
                self.member(fixture)
            fixture.update = False
            engine = self.engine(fixture)
            plan = engine.preview(command, params).data
            result = engine.apply(plan["id"], plan["digest"], plan.get("second_confirmation"))
            self.assertEqual(result.status, "reconciliation_required")
            self.assertEqual(len(fixture.calls), 1)

    def test_missing_cluster_preflight_is_structured_not_found_d2(self):
        # A well-formed but dangling MoRef (domain-c999999) must surface as a
        # structured preflight failure (exit 4), not a top-level internal_error.
        for command, params in (("cluster delete", {"cluster_id": "domain-c999999"}),
                                ("cluster configure", {"cluster_id": "domain-c999999", "ha_enabled": False})):
            with self.subTest(command=command):
                fixture = ClusterFixture()
                fixture.read_fault = vmodl.fault.ManagedObjectNotFound(
                    obj=vim.ClusterComputeResource("domain-c999999", fixture))
                with self.assertRaises(OperationError) as error:
                    fixture.provider().preflight(command, params)
                self.assertEqual(error.exception.code, "cluster_not_found")
                self.assertEqual(error.exception.exit_code, 4)
                self.assertIn("domain-c999999", str(error.exception))
                self.assertEqual(fixture.calls, [])

    def test_unrelated_managed_object_fault_is_not_swallowed_d2(self):
        # Only a missing reference for the exact requested id is normalised;
        # a fault naming a different object must still propagate.
        fixture = ClusterFixture()
        fixture.read_fault = vmodl.fault.ManagedObjectNotFound(
            obj=vim.ClusterComputeResource("domain-c777", fixture))
        with self.assertRaises(vmodl.fault.ManagedObjectNotFound):
            fixture.provider().preflight("cluster delete", {"cluster_id": "domain-c999999"})

    def test_exact_missing_identity_required_for_delete(self):
        fixture = ClusterFixture()
        provider = fixture.provider()
        binding = provider.preflight("cluster delete", {"cluster_id": "domain-c1"})
        fixture.read_fault = vmodl.fault.ManagedObjectNotFound(obj=vim.ClusterComputeResource("domain-c2", fixture))
        self.assertFalse(provider.verify("cluster delete", {}, binding, {}))

    def test_create_receipt_mismatch_and_cancel_rejected(self):
        fixture = ClusterFixture()
        provider = fixture.provider()
        params = {"folder_id": "group-h1", "name": "new"}
        binding = provider.preflight("cluster create", params)
        receipt = provider.submit("cluster create", params, binding)
        with self.assertRaises(OperationError):
            provider.cancel(receipt, binding)
        for key, value in (("server_uuid", "server-2"), ("folder_id", "group-h2"),
                           ("name", "other"), ("object_id", "task-1")):
            with self.assertRaises(OperationError):
                provider.observe({**receipt, key: value}, binding)

    def test_delete_requires_second_confirmation(self):
        fixture = ClusterFixture()
        engine = self.engine(fixture)
        plan = engine.preview("cluster delete", {"cluster_id": "domain-c1"}).data
        with self.assertRaises(OperationError):
            engine.apply(plan["id"], plan["digest"])
        self.assertEqual(fixture.calls, [])

    def test_license_unknown_metadata_keys_ignored_but_expiry_still_enforced(self):
        # H-6: unknown future/8.0.3 property keys are ignored rather than failing
        # the whole read; a present-but-invalid/expired expirationDate still denies.
        from test_license_entitlements import LicenseEntitlementTests
        for key, value in (("expirationHours", "0"), ("expirationMinutes", -1),
                           ("startDate", "2098-01-01T00:00:00Z"), ("system_time", "garbage")):
            row = assignment(features=("das",))
            row.assignedLicense.properties.append(NS(key=key, value=value))
            evidence = LicenseEntitlementTests().checker([row]).require(
                "host-1", ("das",), "server-1")
            self.assertEqual(evidence["features"], ["das"])
        for bad_value in ("not-a-date", "2020-01-01T00:00:00Z"):
            row = assignment(features=("das",))
            row.assignedLicense.properties[-1].value = bad_value
            with self.assertRaises(OperationError):
                LicenseEntitlementTests().checker([row]).require("host-1", ("das",), "server-1")

    def test_delete_requires_parent_permission_and_legacy_disable_preserves_pools(self):
        fixture = ClusterFixture()
        fixture.content.authorizationManager.HasPrivilegeOnEntity = lambda **kw: [kw["entity"]._moId != "group-h1"]
        with self.assertRaises(OperationError):
            fixture.provider().preflight("cluster delete", {"cluster_id": "domain-c1"})
        fixture = ClusterFixture()
        fixture.content.about.apiVersion = "6.7.0"
        fixture.pool.resourcePool = [NS(_moId="resgroup-2", _wsdlName="ResourcePool")]
        with self.assertRaises(OperationError):
            fixture.provider().preflight("cluster configure", {"cluster_id": "domain-c1", "drs_enabled": False})

    def test_create_name_whitelist_rejected_before_remote_read(self):
        # L-1: deterministic name validation happens before any folder read.
        # Empty/control names may already be rejected by the command schema
        # (invalid_arguments); provider-level whitelist is the second line of
        # defence (name_invalid). Both are exit 2 with zero remote calls.
        bad_names = ("", "   ", "a/b", "a\\b", "100%", "a\x00b", " leading",
                     "trailing ", "x" * 81, "vm\u200b", "\ufeffname")
        for bad in bad_names:
            with self.subTest(name=repr(bad)):
                fixture = ClusterFixture()
                with self.assertRaises(OperationError) as ctx:
                    fixture.provider().preflight(
                        "cluster create", {"folder_id": "group-h1", "name": bad})
                self.assertIn(ctx.exception.code, ("name_invalid", "invalid_arguments"))
                self.assertEqual(ctx.exception.exit_code, 2)
                # Rejected before any remote folder enumeration.
                self.assertEqual(fixture.calls, [])

    def test_create_name_accepts_valid_untrimmed_inner_space(self):
        # 80 chars, inner spaces, unicode and dots are legitimate cluster names.
        for good in ("new", "Production Cluster 01", "a" * 80, "集群.A-1_B2"):
            with self.subTest(name=good):
                fixture = ClusterFixture()
                binding = fixture.provider().preflight(
                    "cluster create", {"folder_id": "group-h1", "name": good})
                self.assertEqual(binding["target"].split(":", 1)[1], "group-h1")
