import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest
from unittest.mock import patch

from pyVmomi import vim, vmodl

from vcenter_aiops.application.execution import Engine
from vcenter_aiops.application.providers import ProviderRouter
from vcenter_aiops.application.registry import lookup
from vcenter_aiops.domain.models import OperationError
from vcenter_aiops.infrastructure.store import Store
from test_license_entitlements import assignment, SECRET


def params(host_id="host-1", **changes):
    value = {
        "host_id": host_id,
        "task_timeout": 300,
        "evacuate_powered_off_vms": False,
        "allow_drs_migration": False,
    }
    value.update(changes)
    return value


class RecordingHostStub:
    """Offline transport double used by the real pyVmomi method descriptors."""

    def __init__(self, fixture):
        self.fixture = fixture
        self.calls = []
        self.update_maintenance_state = True
        self.lose_response = False

    def InvokeMethod(self, managed_object, method_info, arguments):
        self.calls.append((method_info.wsdlName, list(arguments)))
        if self.update_maintenance_state:
            if method_info.wsdlName == "EnterMaintenanceMode_Task":
                self.fixture.host.runtime.inMaintenanceMode = True
            elif method_info.wsdlName == "ExitMaintenanceMode_Task":
                self.fixture.host.runtime.inMaintenanceMode = False
        if self.lose_response:
            raise OSError("response lost after remote submission")
        return vim.Task("task-1", self)


class HostFixture:
    def __init__(self, maintenance=False, vm_powers=()):
        self.permissions = True
        self.parent = NS(
            _moId="domain-c7",
            _wsdlName="ClusterComputeResource",
            configurationEx=NS(drsConfig=NS(enabled=True, defaultVmBehavior="fullyAutomated")),
        )
        self.vms = [
            NS(
                _moId=f"vm-{index}",
                name=f"vm-{index}",
                config=NS(instanceUuid=f"vm-uuid-{index}"),
                runtime=NS(powerState=power),
            )
            for index, power in enumerate(vm_powers, 1)
        ]
        self.host = NS(
            _moId="host-1",
            name="esx-1",
            disabledMethod=[],
            hardware=NS(systemInfo=NS(uuid="host-uuid-1")),
            parent=self.parent,
            runtime=NS(connectionState="connected", inMaintenanceMode=maintenance),
            config=NS(vsanHostConfig=NS(enabled=False)),
            vm=self.vms,
        )
        self.stub = RecordingHostStub(self)
        sdk_host = vim.HostSystem("host-1", self.stub)
        self.host.EnterMaintenanceMode_Task = sdk_host.EnterMaintenanceMode_Task
        self.host.ExitMaintenanceMode_Task = sdk_host.ExitMaintenanceMode_Task
        self.parent.host = [self.host]
        self.license_rows = {"host-1": [assignment()]}
        self.task = NS(
            info=NS(
                key="task-1",
                entity=self.host,
                state="success",
                error=None,
                progress=100,
                cancelable=True,
            ),
            CancelTask=lambda: self.stub.calls.append(("CancelTask", [])),
        )
        self.content = NS(
            about=NS(instanceUuid="server-1", apiVersion="8.0.3", apiType="VirtualCenter"),
            sessionManager=NS(currentSession=NS(key="session-1")),
            authorizationManager=NS(
                HasPrivilegeOnEntity=lambda **kwargs: [self.permissions for _ in kwargs["privId"]]
            ),
            licenseManager=NS(licenseAssignmentManager=NS(
                QueryAssignedLicenses=lambda **kwargs: self.license_rows.get(kwargs["entityId"], [])
            )),
        )
        self.si = NS(RetrieveContent=lambda: self.content, _stub=None)

    def provider(self):
        self.assert_provider_module()
        from vcenter_aiops.providers.vsphere.hosts import Hosts

        def resolve(kind, object_id):
            if kind == "host" and object_id == self.host._moId:
                return self.host
            if kind == "task" and object_id == "task-1":
                return self.task
            raise AssertionError((kind, object_id))

        return Hosts(self.si, resolver=resolve)

    @staticmethod
    def assert_provider_module():
        if importlib.util.find_spec("vcenter_aiops.providers.vsphere.hosts") is None:
            raise AssertionError("host maintenance provider is missing")


class HostMaintenanceContractTests(unittest.TestCase):
    def test_registry_aggregates_strict_host_contracts(self):
        enter = lookup("host maintenance-enter")
        exit_ = lookup("host maintenance-exit")
        self.assertEqual(enter.provider_kind, "host")
        self.assertEqual(exit_.provider_kind, "host")
        self.assertEqual(enter.privileges, ("Host.Config.Maintenance",))
        self.assertTrue(enter.asynchronous)
        self.assertTrue(exit_.asynchronous)
        self.assertTrue(callable(enter.handler()))
        self.assertTrue(callable(exit_.handler()))
        self.assertEqual(
            enter.validate({"host_id": "host-1"}),
            {
                "host_id": "host-1",
                "task_timeout": 300,
                "evacuate_powered_off_vms": False,
                "allow_drs_migration": False,
                "dry_run": False,
                "wait": True,
            },
        )
        self.assertEqual(exit_.validate({"host_id": "host-1"})["task_timeout"], 300)
        for timeout in (0, 86401, True):
            with self.subTest(timeout=timeout):
                with self.assertRaises(OperationError):
                    enter.validate({"host_id": "host-1", "task_timeout": timeout})

    def test_default_host_provider_is_lazy_and_injected_mapping_replaces_defaults(self):
        fixture = HostFixture()
        with patch("vcenter_aiops.providers.vsphere.hosts.Hosts") as constructor:
            router = ProviderRouter(fixture.si)
            self.assertNotIn("host", router.providers)
            constructor.assert_not_called()
        injected = ProviderRouter(None, providers={"host": fixture.provider()})
        with self.assertRaises(OperationError) as error:
            injected.preflight("vm power-on", {"vm_id": "vm-1"})
        self.assertEqual(error.exception.code, "provider_unknown")


class HostMaintenanceProviderTests(unittest.TestCase):
    def test_license_and_membership_evidence_is_bound_for_migration_only(self):
        fixture = HostFixture(vm_powers=("poweredOn",))
        binding = fixture.provider().preflight("host maintenance-enter", params(allow_drs_migration=True))
        self.assertEqual(binding["migration_entitlements"]["members"][0]["object_id"], "host-1")
        self.assertEqual(binding["migration_entitlements"]["licenses"][0]["features"], ["drs", "vmotion"])
        self.assertNotIn(SECRET, json.dumps(binding))
        plain = HostFixture()
        plain.content.licenseManager = None
        self.assertIsNone(plain.provider().preflight("host maintenance-enter", params())["migration_entitlements"])

    def test_license_failure_blocks_submission_including_powered_off_evacuation(self):
        for powers, p in ((("poweredOn",), params(allow_drs_migration=True)),
                          (("poweredOff",), params(evacuate_powered_off_vms=True))):
            fixture = HostFixture(vm_powers=powers)
            fixture.license_rows = {}
            with self.assertRaises(OperationError):
                fixture.provider().preflight("host maintenance-enter", p)
            self.assertEqual(fixture.stub.calls, [])
        for defect in ("unavailable", "mismatch", "expired", "missing_feature"):
            with self.subTest(defect=defect):
                fixture = HostFixture(vm_powers=("poweredOn",))
                provider = fixture.provider()
                p = params(allow_drs_migration=True)
                binding = provider.preflight("host maintenance-enter", p)
                if defect == "unavailable":
                    fixture.content.licenseManager = None
                elif defect == "mismatch":
                    fixture.license_rows["host-1"] = [assignment("host-2")]
                elif defect == "expired":
                    fixture.license_rows["host-1"][0].assignedLicense.properties[-1].value = "2020-01-01T00:00:00Z"
                else:
                    fixture.license_rows["host-1"] = [assignment(features=("vmotion",))]
                with self.assertRaises(OperationError):
                    provider.submit("host maintenance-enter", p, binding)
                self.assertEqual(fixture.stub.calls, [])

    def test_every_cluster_host_requires_entitlement_before_migration(self):
        fixture = HostFixture(vm_powers=("poweredOn",))
        second = HostFixture().host
        second._moId = "host-2"
        second.hardware.systemInfo.uuid = "host-uuid-2"
        second.parent = fixture.parent
        fixture.parent.host.append(second)
        p = params(allow_drs_migration=True)
        with self.assertRaises(OperationError):
            fixture.provider().preflight("host maintenance-enter", p)
        fixture.license_rows["host-2"] = [assignment("host-2")]
        binding = fixture.provider().preflight("host maintenance-enter", p)
        self.assertEqual([row["entity_id"] for row in binding["migration_entitlements"]["licenses"]],
                         ["host-1", "host-2"])
        self.assertEqual(fixture.stub.calls, [])

    def test_changed_cluster_membership_or_entitlement_blocks_submit(self):
        for change in ("membership", "entitlement"):
            with self.subTest(change=change):
                fixture = HostFixture(vm_powers=("poweredOn",))
                provider = fixture.provider()
                p = params(allow_drs_migration=True)
                binding = provider.preflight("host maintenance-enter", p)
                if change == "membership":
                    second = HostFixture().host
                    second._moId = "host-2"
                    second.hardware.systemInfo.uuid = "host-uuid-2"
                    second.parent = fixture.parent
                    fixture.parent.host.append(second)
                    fixture.license_rows["host-2"] = [assignment("host-2")]
                else:
                    fixture.license_rows["host-1"][0].assignedLicense.total = 16
                with self.assertRaises(OperationError) as error:
                    provider.submit("host maintenance-enter", p, binding)
                self.assertEqual(error.exception.code, "plan_stale")
                self.assertEqual(fixture.stub.calls, [])

    def test_current_server_change_blocks_observe_and_cancel_before_resolution(self):
        fixture = HostFixture()
        provider = fixture.provider()
        binding = provider.preflight("host maintenance-enter", params())
        receipt = {"server_uuid": "server-1", "task_id": "task-1", "entity_id": "host-1"}
        fixture.task.info.state = "running"
        fixture.content.about.instanceUuid = "server-2"
        provider.resolver = lambda *args: self.fail("task must not be resolved on changed server")
        for operation in (provider.observe, provider.cancel):
            with self.assertRaises(OperationError) as error:
                operation(receipt, binding)
            self.assertEqual(error.exception.code, "target_unavailable")
        self.assertEqual(fixture.stub.calls, [])

    def test_server_change_during_task_resolution_still_prevents_cancellation(self):
        fixture = HostFixture()
        provider = fixture.provider()
        binding = provider.preflight("host maintenance-enter", params())
        receipt = {"server_uuid": "server-1", "task_id": "task-1", "entity_id": "host-1"}
        fixture.task.info.state = "running"
        def resolve(*args):
            fixture.content.about.instanceUuid = "server-2"
            return fixture.task
        provider.resolver = resolve
        with self.assertRaises(OperationError) as error:
            provider.cancel(receipt, binding)
        self.assertEqual(error.exception.code, "target_unavailable")
        self.assertEqual(fixture.stub.calls, [])

    def test_enter_preflight_is_read_only_and_binds_serializable_impact(self):
        fixture = HostFixture(vm_powers=("poweredOn", "poweredOff"))
        provider = fixture.provider()
        binding = provider.preflight(
            "host maintenance-enter",
            params(allow_drs_migration=True, evacuate_powered_off_vms=True),
        )
        self.assertEqual(binding["target"], "server-1:host-1")
        self.assertEqual(binding["server_uuid"], "server-1")
        self.assertEqual(binding["object_id"], "host-1")
        self.assertEqual(binding["hardware_uuid"], "host-uuid-1")
        self.assertEqual(binding["parent_id"], "domain-c7")
        self.assertEqual(binding["before"]["connection_state"], "connected")
        self.assertFalse(binding["before"]["in_maintenance_mode"])
        self.assertEqual(binding["authorization"], {
            "allow_drs_migration": True,
            "evacuate_powered_off_vms": True,
        })
        self.assertEqual(binding["impact"]["drs_mode"], "fullyAutomated")
        self.assertTrue(binding["impact"]["drs_enabled"])
        self.assertEqual(binding["impact"]["powered_on_vm_ids"], ["vm-1"])
        self.assertEqual(binding["impact"]["powered_off_evacuation_vm_ids"], ["vm-2"])
        self.assertTrue(binding["impact"]["capacity_may_prevent_completion"])
        self.assertEqual(json.loads(json.dumps(binding)), binding)
        self.assertEqual(fixture.stub.calls, [])

    def test_enter_requires_explicit_drs_authorization_and_full_automation(self):
        fixture = HostFixture(vm_powers=("poweredOn",))
        provider = fixture.provider()
        with self.assertRaises(OperationError) as error:
            provider.preflight("host maintenance-enter", params())
        self.assertEqual(error.exception.code, "precondition_failed")
        fixture.parent.configurationEx.drsConfig.defaultVmBehavior = "manual"
        with self.assertRaises(OperationError) as error:
            provider.preflight("host maintenance-enter", params(allow_drs_migration=True))
        self.assertEqual(error.exception.code, "precondition_failed")
        self.assertEqual(fixture.stub.calls, [])

    def test_enter_rejects_explicitly_disabled_drs_despite_full_automation_mode(self):
        fixture = HostFixture(vm_powers=("poweredOn",))
        fixture.parent.configurationEx.drsConfig.enabled = False
        with self.assertRaises(OperationError) as error:
            fixture.provider().preflight("host maintenance-enter", params(allow_drs_migration=True))
        self.assertEqual(error.exception.code, "precondition_failed")
        self.assertEqual(fixture.stub.calls, [])

    def test_legacy_drs_enabled_must_be_known_for_powered_on_migration(self):
        fixture = HostFixture(vm_powers=("poweredOn",))
        fixture.content.about.apiVersion = "6.7.0"
        fixture.parent.configurationEx.drsConfig.enabled = None
        with self.assertRaises(OperationError) as error:
            fixture.provider().preflight("host maintenance-enter", params(allow_drs_migration=True))
        self.assertEqual(error.exception.code, "target_unavailable")
        fixture.content.about.apiVersion = "8.0.3"
        binding = fixture.provider().preflight("host maintenance-enter", params(allow_drs_migration=True))
        self.assertIsNone(binding["impact"]["drs_enabled"])

    def test_powered_off_evacuation_requires_drs_when_vms_are_present(self):
        fixture = HostFixture(vm_powers=("poweredOff",))
        fixture.parent.configurationEx.drsConfig.enabled = False
        with self.assertRaises(OperationError) as error:
            fixture.provider().preflight("host maintenance-enter", params(evacuate_powered_off_vms=True))
        self.assertEqual(error.exception.code, "precondition_failed")
        self.assertEqual(fixture.stub.calls, [])
        fixture.content.about.apiVersion = "6.7.0"
        fixture.parent.configurationEx.drsConfig.enabled = None
        with self.assertRaises(OperationError) as error:
            fixture.provider().preflight("host maintenance-enter", params(evacuate_powered_off_vms=True))
        self.assertEqual(error.exception.code, "target_unavailable")

    def test_standalone_parent_with_configuration_ex_is_not_mistaken_for_cluster(self):
        fixture = HostFixture()
        fixture.parent._wsdlName = "ComputeResource"
        fixture.parent.configurationEx = NS(vmSwapPlacement="vmDirectory")
        binding = fixture.provider().preflight("host maintenance-enter", params())
        self.assertEqual(binding["impact"]["drs_mode"], "notApplicable")
        self.assertEqual(fixture.stub.calls, [])

    def test_enter_rejects_enabled_or_indeterminate_vsan(self):
        for vsan_config in (NS(enabled=True), None, NS(enabled=None)):
            with self.subTest(vsan_config=vsan_config):
                fixture = HostFixture()
                fixture.host.config.vsanHostConfig = vsan_config
                with self.assertRaises(OperationError) as error:
                    fixture.provider().preflight("host maintenance-enter", params())
                self.assertEqual(error.exception.code, "precondition_failed")
                self.assertEqual(fixture.stub.calls, [])

    def test_exit_does_not_require_or_create_evacuation_scope(self):
        fixture = HostFixture(maintenance=True, vm_powers=("poweredOn", "poweredOff"))
        fixture.host.config.vsanHostConfig = None
        provider = fixture.provider()
        binding = provider.preflight("host maintenance-exit", params())
        self.assertEqual(binding["impact"]["powered_off_evacuation_vm_ids"], [])
        provider.submit("host maintenance-exit", params(), binding)
        self.assertEqual(fixture.stub.calls, [("ExitMaintenanceMode_Task", [300])])

    def test_preflight_rejects_invalid_version_identity_permission_method_and_state(self):
        mutations = (
            (lambda f: setattr(f.content.about, "apiVersion", "9.0"), "capability_unsupported"),
            (lambda f: setattr(f.content.about, "apiType", "HostAgent"), "capability_unsupported"),
            (lambda f: setattr(f.content.about, "instanceUuid", None), "target_unavailable"),
            (lambda f: setattr(f.host.hardware.systemInfo, "uuid", None), "target_unavailable"),
            (lambda f: setattr(f.host, "parent", None), "target_unavailable"),
            (lambda f: setattr(f.host.runtime, "connectionState", "disconnected"), "target_unavailable"),
            (lambda f: setattr(f, "permissions", False), "permission_denied"),
            (lambda f: setattr(f.host, "disabledMethod", None), "target_unavailable"),
            (lambda f: setattr(f.host, "disabledMethod", ["EnterMaintenanceMode_Task"]), "capability_unsupported"),
            (lambda f: setattr(f.host.runtime, "inMaintenanceMode", True), "precondition_failed"),
        )
        for mutate, code in mutations:
            with self.subTest(code=code, mutation=mutate):
                fixture = HostFixture()
                mutate(fixture)
                with self.assertRaises(OperationError) as error:
                    fixture.provider().preflight("host maintenance-enter", params())
                self.assertEqual(error.exception.code, code)
                self.assertEqual(fixture.stub.calls, [])
        fixture = HostFixture(maintenance=True)
        fixture.host.disabledMethod = ["ExitMaintenanceMode_Task"]
        with self.assertRaises(OperationError) as error:
            fixture.provider().preflight("host maintenance-exit", params())
        self.assertEqual(error.exception.code, "capability_unsupported")
        with self.assertRaises(OperationError) as error:
            HostFixture().provider().preflight("host maintenance-exit", params())
        self.assertEqual(error.exception.code, "precondition_failed")
        with self.assertRaises(OperationError) as error:
            HostFixture().provider().preflight("host maintenance-enter", params(host_id="esx.example"))
        self.assertEqual(error.exception.code, "target_invalid")

    def test_missing_or_unknown_vm_state_is_never_treated_as_safe(self):
        for change in ("missing_uuid", "unknown_power", "missing_inventory"):
            with self.subTest(change=change):
                fixture = HostFixture(vm_powers=("poweredOff",))
                if change == "missing_uuid":
                    fixture.vms[0].config.instanceUuid = None
                elif change == "unknown_power":
                    fixture.vms[0].runtime.powerState = None
                else:
                    fixture.host.vm = None
                with self.assertRaises(OperationError) as error:
                    fixture.provider().preflight("host maintenance-enter", params())
                self.assertEqual(error.exception.code, "target_unavailable")

    def test_submit_rechecks_affected_vm_set_before_real_sdk_write(self):
        fixture = HostFixture(vm_powers=("poweredOff",))
        provider = fixture.provider()
        p = params(evacuate_powered_off_vms=True)
        binding = provider.preflight("host maintenance-enter", p)
        fixture.host.vm.append(NS(
            _moId="vm-2", name="vm-2", config=NS(instanceUuid="vm-uuid-2"),
            runtime=NS(powerState="poweredOff"),
        ))
        with self.assertRaises(OperationError) as error:
            provider.submit("host maintenance-enter", p, binding)
        self.assertEqual(error.exception.code, "plan_stale")
        self.assertEqual(fixture.stub.calls, [])

    def test_real_sdk_methods_receive_server_timeout_and_explicit_evacuation_only(self):
        enter_fixture = HostFixture(vm_powers=("poweredOff",))
        enter = enter_fixture.provider()
        p = params(task_timeout=721, evacuate_powered_off_vms=True)
        receipt = enter.submit("host maintenance-enter", p, enter.preflight("host maintenance-enter", p))
        self.assertEqual(enter_fixture.stub.calls, [
            ("EnterMaintenanceMode_Task", [721, True, None]),
        ])
        self.assertEqual(receipt, {
            "server_uuid": "server-1", "task_id": "task-1", "entity_id": "host-1",
        })

        exit_fixture = HostFixture(maintenance=True)
        exit_provider = exit_fixture.provider()
        exit_params = params(task_timeout=19)
        exit_receipt = exit_provider.submit(
            "host maintenance-exit",
            exit_params,
            exit_provider.preflight("host maintenance-exit", exit_params),
        )
        self.assertEqual(exit_fixture.stub.calls, [("ExitMaintenanceMode_Task", [19])])
        self.assertEqual(json.loads(json.dumps(exit_receipt)), exit_receipt)

    def test_bind_steps_allows_independent_hosts_but_rejects_same_host_projection(self):
        first = HostFixture()
        second = HostFixture()
        second.host._moId = "host-2"
        second.host.hardware.systemInfo.uuid = "host-uuid-2"
        provider = first.provider()
        provider.resolver = lambda kind, object_id: (
            first.task if kind == "task" else first.host if object_id == "host-1" else second.host
        )
        bound = provider.bind_steps([
            {"command": "host maintenance-enter", "params": params("host-1")},
            {"command": "host maintenance-enter", "params": params("host-2")},
        ])
        self.assertEqual([step["binding"]["object_id"] for step in bound], ["host-1", "host-2"])
        self.assertEqual(first.stub.calls + second.stub.calls, [])
        with self.assertRaises(OperationError) as error:
            provider.bind_steps([
                {"command": "host maintenance-enter", "params": params("host-1")},
                {"command": "host maintenance-exit", "params": params("host-1")},
            ])
        self.assertEqual(error.exception.code, "plan_dependency_unsupported")

    def test_observe_checks_server_task_key_and_entity_ownership(self):
        fixture = HostFixture()
        provider = fixture.provider()
        binding = provider.preflight("host maintenance-enter", params())
        receipt = {"server_uuid": "server-1", "task_id": "task-1", "entity_id": "host-1"}
        observation = provider.observe(receipt, binding)
        self.assertEqual(observation["state"], "success")
        self.assertEqual(observation["task_key"], "task-1")
        self.assertEqual(observation["entity_id"], "host-1")
        self.assertEqual(json.loads(json.dumps(observation)), observation)
        for mutation in (
            {**receipt, "server_uuid": "server-2"},
            {**receipt, "task_id": "bogus"},
            {**receipt, "entity_id": "host-2"},
        ):
            with self.subTest(receipt=mutation):
                with self.assertRaises(OperationError):
                    provider.observe(mutation, binding)
        fixture.task.info.key = "task-2"
        with self.assertRaises(OperationError):
            provider.observe(receipt, binding)
        fixture.task.info.key = "task-1"
        fixture.task.info.entity = NS(_moId="host-2")
        with self.assertRaises(OperationError):
            provider.observe(receipt, binding)

    def test_only_remote_request_canceled_sets_cancelled(self):
        fixture = HostFixture()
        provider = fixture.provider()
        binding = provider.preflight("host maintenance-enter", params())
        receipt = {"server_uuid": "server-1", "task_id": "task-1", "entity_id": "host-1"}
        fixture.task.info.state = "error"
        fixture.task.info.error = RuntimeError("not remote cancellation")
        self.assertFalse(provider.observe(receipt, binding)["cancelled"])
        fixture.task.info.error = vmodl.fault.RequestCanceled()
        self.assertTrue(provider.observe(receipt, binding)["cancelled"])

    def test_verify_requires_bound_identity_and_actual_maintenance_state(self):
        fixture = HostFixture()
        provider = fixture.provider()
        binding = provider.preflight("host maintenance-enter", params())
        self.assertFalse(provider.verify("host maintenance-enter", params(), binding, {"state": "success"}))
        fixture.host.runtime.inMaintenanceMode = True
        self.assertTrue(provider.verify("host maintenance-enter", params(), binding, {"state": "success"}))
        fixture.host.hardware.systemInfo.uuid = "replacement-host"
        self.assertFalse(provider.verify("host maintenance-enter", params(), binding, {"state": "success"}))

    def test_cancel_checks_task_ownership_before_request(self):
        fixture = HostFixture()
        provider = fixture.provider()
        binding = provider.preflight("host maintenance-enter", params())
        fixture.task.info.state = "running"
        receipt = {"server_uuid": "server-1", "task_id": "task-1", "entity_id": "host-1"}
        self.assertEqual(provider.cancel(receipt, binding), {
            "cancel_requested": True, "server_uuid": "server-1", "task_id": "task-1",
        })
        self.assertEqual(fixture.stub.calls, [("CancelTask", [])])
        fixture.stub.calls.clear()
        fixture.task.info.entity = NS(_moId="host-2")
        with self.assertRaises(OperationError):
            provider.cancel(receipt, binding)
        self.assertEqual(fixture.stub.calls, [])


class HostMaintenanceEngineTests(unittest.TestCase):
    def run_engine(self, fixture, command, p):
        router = ProviderRouter(None, providers={"host": fixture.provider()})
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = Store(Path(temporary.name) / "state.db")
        self.addCleanup(store.close)
        return Engine(store, router, "lab", timeout=0), store

    def test_enter_and_exit_succeed_through_router_and_engine(self):
        for command, fixture, p, method in (
            ("host maintenance-enter", HostFixture(), params(), "EnterMaintenanceMode_Task"),
            ("host maintenance-exit", HostFixture(maintenance=True), params(), "ExitMaintenanceMode_Task"),
        ):
            with self.subTest(command=command):
                engine, _ = self.run_engine(fixture, command, p)
                plan = engine.preview(command, p).data
                self.assertEqual(plan["payload"]["steps"][0]["binding"]["provider_kind"], "host")
                self.assertEqual(fixture.stub.calls, [])
                result = engine.apply(plan["id"], plan["digest"])
                self.assertEqual(result.status, "succeeded")
                self.assertEqual(fixture.stub.calls[0][0], method)
                self.assertEqual(result.data["execution"][0]["receipt"]["server_uuid"], "server-1")
                self.assertEqual(result.data["execution"][0]["observation"]["entity_id"], "host-1")

    def test_wrong_confirmation_causes_zero_remote_writes(self):
        fixture = HostFixture()
        engine, _ = self.run_engine(fixture, "host maintenance-enter", params())
        plan = engine.preview("host maintenance-enter", params()).data
        with self.assertRaises(OperationError):
            engine.apply(plan["id"], "wrong")
        self.assertEqual(fixture.stub.calls, [])

    def test_lost_receipt_is_not_resubmitted(self):
        fixture = HostFixture()
        fixture.stub.lose_response = True
        engine, _ = self.run_engine(fixture, "host maintenance-enter", params())
        plan = engine.preview("host maintenance-enter", params()).data
        self.assertEqual(engine.apply(plan["id"], plan["digest"]).status, "reconciliation_required")
        self.assertEqual(engine.reconcile(plan["id"]).status, "reconciliation_required")
        self.assertEqual(engine.apply(plan["id"], plan["digest"]).status, "reconciliation_required")
        self.assertEqual([call[0] for call in fixture.stub.calls], ["EnterMaintenanceMode_Task"])

    def test_task_success_without_postcondition_requires_reconciliation(self):
        fixture = HostFixture()
        fixture.stub.update_maintenance_state = False
        engine, _ = self.run_engine(fixture, "host maintenance-enter", params())
        plan = engine.preview("host maintenance-enter", params()).data
        self.assertEqual(engine.apply(plan["id"], plan["digest"]).status, "reconciliation_required")
        self.assertEqual([call[0] for call in fixture.stub.calls], ["EnterMaintenanceMode_Task"])


if __name__ == "__main__":
    unittest.main()
