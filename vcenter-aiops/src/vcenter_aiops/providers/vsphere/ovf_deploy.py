"""OVA/OVF remote deploy provider (SDK boundary).

Local archive safety and descriptor validation live in ``ovf.py``; the NFC lease
state machine lives in ``ovf_lease.py``; the dependency-free HTTP PUT boundary
lives in ``ovf_http.py``. This module orchestrates them against a live vCenter via
OvfManager + ResourcePool.importVapp. SDK objects never leave; only JSON values
cross the engine boundary.

Because importVapp returns an HttpNfcLease (not a pollable Task), submit drives
the lease to its terminal state synchronously and returns a terminal receipt. A
lost response after the remote write is uncertainty; reconcile verifies the entity
rather than resubmitting.
"""
import os
import time

from ...domain.models import OperationError, SubmissionRejected, fail
from .ovf import extract_ova, validate_mapping, validate_placement
from . import ovf_lease

# Upper bound for waiting on HttpNfcLease *state progression*
# (initializing→ready→done). Actual disk byte transfer runs inside the HTTP PUT
# boundary (its own 60s per-connection timeout) and is not charged against this
# window, so a generous fixed ceiling neither hangs forever nor aborts a slow but
# healthy large upload. Timing out is uncertainty: the engine reconciles the
# already-created entity/lease and never resubmits.
NFC_LEASE_WAIT_SECONDS = 1800


class OvfDeploy:
    kind = "ovf"

    def __init__(self, si, resolver=None, upload=None, driver=None,
                 cisp_builder=None, tls=None, lease_wait=NFC_LEASE_WAIT_SECONDS):
        self.si = si
        self.content = si.RetrieveContent()
        self.server_uuid = self.content.about.instanceUuid
        self.resolver = resolver or self._resolve
        self._upload = upload
        self._drive = driver or ovf_lease.drive
        self._cisp_builder = cisp_builder or self._build_cisp
        self._tls = tls or {}
        self._lease_wait = lease_wait

    def _build_cisp(self, params, host, validated):
        """SDK boundary: construct CreateImportSpecParams with typed mappings."""
        from pyVmomi import vim
        network_mapping = [
            vim.OvfManager.NetworkMapping(name=name, network=self.resolver("network", target))
            for name, target in validated["network_mapping"].items()]
        return vim.OvfManager.CreateImportSpecParams(
            entityName=params["name"], hostSystem=host,
            networkMapping=network_mapping)

    def _resolve(self, kind, object_id):
        from pyVmomi import vim
        if kind == "network":
            if object_id.startswith("dvportgroup-"):
                return vim.dvs.DistributedVirtualPortgroup(object_id, self.si._stub)
            return vim.Network(object_id, self.si._stub)
        classes = {"pool": vim.ResourcePool, "host": vim.HostSystem,
                   "folder": vim.Folder, "datastore": vim.Datastore,
                   "vm": vim.VirtualMachine}
        return classes[kind](object_id, self.si._stub)

    def _prepared(self, command, params):
        is_ova = command == "deploy ova"
        if is_ova:
            work = params["source"]
            directory = os.path.join(params["work_dir"], "unpacked")
            extract_ova(work, directory)
            ovf_files = [f for f in os.listdir(directory) if f.endswith(".ovf")]
            if not ovf_files:
                fail("ovf_descriptor_missing", "解包后未找到 .ovf 描述符", 2)
            descriptor_path = os.path.join(directory, ovf_files[0])
        else:
            directory = params["source"]
            descriptor_path = os.path.join(directory, "descriptor.ovf")
            if not os.path.exists(descriptor_path):
                fail("ovf_descriptor_missing", "OVF 目录缺少 descriptor.ovf", 2)
        with open(descriptor_path, encoding="utf-8") as handle:
            descriptor = handle.read()
        present = os.listdir(directory)
        validate_placement(params)
        validated = validate_mapping(descriptor, dict(params["network_mapping"]), present)
        return descriptor, validated, directory

    def preflight(self, command, params):
        if command not in ("deploy ova", "deploy ovf"):
            fail("capability_unsupported", "Ovf Provider 不接受此命令", 4)
        descriptor, validated, directory = self._prepared(command, params)
        return {"target": self.server_uuid + ":" + params["folder_id"],
                "server_uuid": self.server_uuid,
                "object_id": params["folder_id"],
                "risk": "change", "kind": "ovf",
                "before": {"networks": validated["networks"],
                           "files": validated["files"]},
                "scope": {"network_mapping": validated["network_mapping"],
                          "datastore_id": params["datastore_id"]},
                "warnings": ["OVA/OVF 默认不开机、不隐式 Guest 定制",
                             "NFC 传输中断后须核对已创建对象，不盲清"]}

    @staticmethod
    def matches(expected, actual):
        return expected.get("scope") == actual.get("scope")

    def submit(self, command, params, binding):
        # Local safety validation only. Rejections happen before any remote write.
        try:
            if command not in ("deploy ova", "deploy ovf"):
                fail("capability_unsupported", "Ovf Provider 不接受此命令", 4)
            descriptor, validated, directory = self._prepared(command, params)
            if not self.matches(binding, self.preflight(command, params)):
                fail("plan_stale", "提交前目标身份或映射变化，请重新预览", 4)
        except OperationError as exc:
            raise SubmissionRejected(exc.code, str(exc), exc.exit_code) from None

        # From here on the remote write may have happened: never raise a
        # SubmissionRejected, and never resubmit. Let exceptions surface as
        # uncertainty so the caller marks reconciliation_required.
        ovf_manager = self.content.ovfManager
        resource_pool = self.resolver("pool", params["resource_pool_id"])
        host = self.resolver("host", params["host_id"])
        folder = self.resolver("folder", params["folder_id"])
        datastore = self.resolver("datastore", params["datastore_id"])
        cisp = self._cisp_builder(params, host, validated)
        import_spec = ovf_manager.CreateImportSpec(
            ovfDescriptor=descriptor, resourcePool=resource_pool,
            datastore=datastore, cisp=cisp)
        if import_spec.error:
            fail("ovf_import_spec_invalid",
                 "服务端拒绝该 OVF 导入规格，请核对描述符与映射", 6)
        if not import_spec.importSpec:
            fail("ovf_import_spec_invalid",
                 "服务端无法为该 OVF 创建导入规格", 6)
        lease = resource_pool.ImportVApp(
            spec=import_spec.importSpec, folder=folder, host=host)
        upload = self._upload or self._make_upload(params, directory)
        self._drive(lease, validated["files"], upload,
                    deadline=time.monotonic() + self._lease_wait)
        info = lease.info
        entity = getattr(info, "entity", None)
        return {"state": "success", "kind": "ovf_import",
                "task_id": self.server_uuid + ":" + (entity._moId if entity is not None else lease._moId),
                "result_id": entity._moId if entity is not None else None,
                "entity_name": getattr(entity, "name", None)}

    def _make_upload(self, params, directory):
        from . import ovf_http

        context = ovf_http.ssl_context(
            verify_tls=self._tls.get("verify_tls", True),
            ca_file=self._tls.get("ca_file"))

        def upload(target, lease_info):
            source_path = os.path.join(directory, target["file"])
            ovf_http.put_file(target["url"], source_path,
                              headers={"Overwrite": "t"}, context=context)

        return upload

    def observe(self, receipt, binding):
        if binding.get("server_uuid") != self.server_uuid:
            fail("server_mismatch", "操作属于其他 vCenter", 4)
        state = receipt.get("state")
        if state == "success":
            return {"state": "success", "result_id": receipt.get("result_id"),
                    "entity_name": receipt.get("entity_name")}
        # A terminal error receipt; otherwise uncertainty that needs reconcile.
        return {"state": receipt.get("state", "unknown"),
                "error": receipt.get("error")}

    def verify(self, command, params, binding, observation):
        result_id = observation.get("result_id")
        if not result_id:
            return False
        try:
            vm = self.resolver("vm", result_id)
        except Exception:
            return False
        if getattr(vm, "config", None) is None:
            return False
        # Imported object must exist and remain powered off (no implicit power-on).
        return vm.runtime.powerState == "poweredOff"

    def cancel(self, receipt, binding):
        fail("cancellation_unsupported",
             "OVA/OVF 导入取消须核对 NFC lease 与已创建对象，不猜目标", 4)
