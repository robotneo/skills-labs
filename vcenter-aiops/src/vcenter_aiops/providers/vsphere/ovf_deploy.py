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
import re
import time
import urllib.parse

from ...domain.models import OperationError, SubmissionRejected, fail
from .ovf import extract_ova, validate_mapping, validate_placement
from .mor import existing, check_privileges
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

    # -- M-6: read-only remote placement evidence (no import/lease side effects)

    _NOT_FOUND = {
        "pool": ("resource_pool_not_found", "指定资源池不存在或已被删除: "),
        "host": ("host_not_found", "指定主机不存在或已被删除: "),
        "folder": ("folder_not_found", "指定文件夹不存在或已被删除: "),
        "datastore": ("datastore_not_found", "指定数据存储不存在或已被删除: "),
        "network": ("network_not_found", "指定网络不存在或已被删除: "),
    }

    def _existing(self, kind, object_id, attr):
        code, message = self._NOT_FOUND.get(
            kind, ("target_not_found", "指定目标对象不存在或已被删除: "))
        # resolve + first controlled fetch live in the same probe so a resolver
        # that raises ManagedObjectNotFound at construction time is normalized
        # too (same convention as clusters/hosts); mor.existing re-raises a
        # dangling-MONF fault that names a different object than the one asked for.
        resolved = {}

        def probe():
            obj = self.resolver(kind, object_id)
            resolved["obj"] = obj
            return getattr(obj, attr)

        existing(probe, object_id, code, message + object_id)
        return resolved["obj"]

    def _datacenter(self, obj):
        visited = set()
        while getattr(obj, "_wsdlName", type(obj).__name__) != "Datacenter":
            identity = getattr(obj, "_moId", None)
            if not identity or identity in visited or len(visited) >= 100:
                fail("placement_invalid", "数据中心归属不可确定", 4)
            visited.add(identity)
            obj = getattr(obj, "parent", None)
        dc_id = getattr(obj, "_moId", None)
        if not isinstance(dc_id, str) or not re.fullmatch(r"datacenter-\d+", dc_id):
            fail("placement_invalid", "数据中心身份不可确定", 4)
        return dc_id

    def _privileges(self, entity, required):
        check_privileges(self.content, entity, required,
                         denied="账户缺少 OVF 导入所需权限",
                         unable="无法核对 OVF 导入权限")

    def _remote_placement(self, params, validated):
        """Read-only verification that every remote placement object exists, is
        reachable/coherent (same datacenter, host↔pool, host-visible datastore and
        networks) and that the session holds the per-entity import privileges.

        Performs no ImportVapp / CreateImportSpec / HttpNfcLease call, so it is
        safe in preview. Returns a compact identity snapshot used to detect
        preview→submit drift.
        """
        pool = self._existing("pool", params["resource_pool_id"], "name")
        host = self._existing("host", params["host_id"], "name")
        folder = self._existing("folder", params["folder_id"], "name")
        datastore = self._existing("datastore", params["datastore_id"], "summary")

        owner = getattr(pool, "owner", None)
        if getattr(owner, "_wsdlName", type(owner).__name__) not in ("ComputeResource", "ClusterComputeResource"):
            fail("placement_invalid", "资源池的计算资源身份不可确定", 4)
        if getattr(host, "parent", None) is None or host.parent._moId != owner._moId:
            fail("placement_invalid", "指定主机与资源池不属于同一计算资源", 4)
        runtime = getattr(host, "runtime", None)
        if getattr(runtime, "connectionState", None) != "connected" or getattr(runtime, "inMaintenanceMode", False):
            fail("placement_invalid", "目标主机必须已连接且不在维护模式", 4)

        dc_id = self._datacenter(folder)
        if self._datacenter(owner) != dc_id:
            fail("placement_invalid", "VM 文件夹与计算资源不属于同一数据中心", 4)
        if not any(str(t).rsplit(".", 1)[-1].lower() == "virtualmachine"
                   for t in (getattr(folder, "childType", None) or [])):
            fail("placement_invalid", "目标不是 VM 文件夹", 4)

        summary = getattr(datastore, "summary", None)
        if getattr(summary, "accessible", None) is not True or getattr(summary, "maintenanceMode", None) != "normal":
            fail("placement_invalid", "目标数据存储不可访问或处于维护模式", 4)
        host_datastores = getattr(host, "datastore", None) or []
        if datastore._moId not in [d._moId for d in host_datastores]:
            fail("placement_invalid", "目标主机不能使用指定数据存储", 4)

        # Every descriptor-mapped network must exist and be reachable on host.
        host_networks = {n._moId for n in (getattr(host, "network", None) or [])}
        networks = {}
        for target_id in validated["network_mapping"].values():
            network = self._existing("network", target_id, "name")
            networks[target_id] = network
            if network._moId not in host_networks:
                fail("placement_invalid", "目标主机不能使用指定网络: " + target_id, 4)

        # Per-entity ImportVApp entitlements (fail-closed, read-only SOAP).
        self._privileges(pool, ("Resource.AssignVMToPool",))
        self._privileges(datastore, ("Datastore.AllocateSpace",))
        self._privileges(folder, ("vApp.Import",))
        for network in networks.values():
            self._privileges(network, ("Network.Assign",))

        return {
            "datacenter_id": dc_id, "compute_id": owner._moId,
            "pool": {"id": pool._moId, "name": getattr(pool, "name", None)},
            "host": {"id": host._moId, "name": getattr(host, "name", None)},
            "folder": {"id": folder._moId, "name": getattr(folder, "name", None)},
            "datastore": {"id": datastore._moId, "name": getattr(datastore, "name", None)},
            "networks": {target_id: getattr(network, "name", None)
                         for target_id, network in networks.items()},
        }


    def _prepared(self, command, params):
        is_ova = command == "deploy ova"
        if is_ova:
            work = params["source"]
            directory = os.path.join(params["work_dir"], "unpacked")
            extract_ova(work, directory)
            ovf_files = sorted(f for f in os.listdir(directory) if f.endswith(".ovf"))
            if not ovf_files:
                fail("ovf_descriptor_missing", "解包后未找到 .ovf 描述符", 2)
            if len(ovf_files) > 1:
                fail("ovf_descriptor_ambiguous",
                     f"解包后存在多个 .ovf 描述符：{ovf_files}；须仅含一个，拒绝解包后的部署", 2)
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
        # M-6: gather read-only remote placement evidence in preview so a stale
        # folder/network/pool/host/datastore, a cross-datacenter/incoherent
        # target, an unreachable network/datastore, or a missing privilege is
        # reported before any ImportVapp/CreateImportSpec/HttpNfcLease side effect.
        placement = self._remote_placement(params, validated)
        return {"target": self.server_uuid + ":" + params["folder_id"],
                "server_uuid": self.server_uuid,
                "object_id": params["folder_id"],
                "risk": "change", "kind": "ovf",
                "before": {"networks": validated["networks"],
                           "files": validated["files"]},
                "scope": {"network_mapping": validated["network_mapping"],
                          "datastore_id": params["datastore_id"],
                          # Identity snapshot; submit re-runs preflight and a
                          # changed placement (DC/host/visibility) fails plan_stale.
                          "placement": placement},
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

    def _connection_host(self):
        """Lower-cased vCenter endpoint host this provider is bound to, or None.

        Used to seed the NFC redirect allow-set so a legitimate vCenter -> ESXi
        redirect is accepted while a redirect anywhere else is rejected. Defensive
        about stub shapes (fake sessions in tests carry no usable host).
        """
        raw = getattr(getattr(self.si, "_stub", None), "host", None)
        if not isinstance(raw, str) or not raw:
            return None
        candidate = raw if "://" in raw else "https://" + raw
        host = urllib.parse.urlsplit(candidate).hostname
        return host.lower() if host else None

    def _make_upload(self, params, directory):
        from . import ovf_http

        context = ovf_http.ssl_context(
            verify_tls=self._tls.get("verify_tls", True),
            ca_file=self._tls.get("ca_file"))

        # Trust anchor for NFC redirects: the connected vCenter endpoint plus the
        # initial host of every SOAP-issued deviceUrl for this import. A redirect
        # may move between those authorized endpoints but never to an unrelated
        # host, and never downgrade to plain http (NFC always uses https).
        allowed_hosts = set()
        anchor = self._connection_host()
        if anchor:
            allowed_hosts.add(anchor)

        def upload(target, lease_info):
            source_path = os.path.join(directory, target["file"])
            first_host = urllib.parse.urlsplit(target["url"]).hostname
            per_target = set(allowed_hosts)
            if first_host:
                per_target.add(first_host.lower())
            ovf_http.put_file(target["url"], source_path,
                              headers={"Overwrite": "t"}, context=context,
                              allowed_hosts=per_target)

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
        runtime = getattr(vm, "runtime", None)
        if runtime is None or getattr(runtime, "powerState", None) != "poweredOff":
            return False
        # M-8: when a preview placement snapshot exists, prove the imported entity
        # landed exactly where previewed (name / folder / pool / host / datastore /
        # networks) rather than merely existing and being off. A missing snapshot
        # (older records resumed across versions) keeps the powered-off check only.
        placement = None
        if isinstance(binding, dict):
            scope = binding.get("scope")
            if isinstance(scope, dict):
                placement = scope.get("placement")
        if placement:
            try:
                expected_name = params.get("name") if isinstance(params, dict) else None
                if expected_name and getattr(vm, "name", None) != expected_name:
                    return False
                if self._mor_id(getattr(vm, "parent", None)) != placement["folder"]["id"]:
                    return False
                if self._mor_id(getattr(vm, "resourcePool", None)) != placement["pool"]["id"]:
                    return False
                if self._mor_id(getattr(runtime, "host", None)) != placement["host"]["id"]:
                    return False
                want_datastore = placement["datastore"]["id"]
                have_datastores = [self._mor_id(d) for d in (getattr(vm, "datastore", None) or [])]
                if want_datastore not in have_datastores:
                    return False
                want_networks = set((placement.get("networks") or {}).keys())
                have_networks = {self._mor_id(n) for n in (getattr(vm, "network", None) or [])}
                if want_networks and not want_networks.issubset(have_networks):
                    return False
            except Exception:
                # Insufficient/unreadable evidence is not proof of success.
                return False
        return True

    @staticmethod
    def _mor_id(obj):
        return getattr(obj, "_moId", None)

    def cancel(self, receipt, binding):
        fail("cancellation_unsupported",
             "OVA/OVF 导入取消须核对 NFC lease 与已创建对象，不猜目标", 4)
