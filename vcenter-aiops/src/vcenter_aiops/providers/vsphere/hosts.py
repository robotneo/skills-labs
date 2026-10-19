"""vCenter host-maintenance provider; SDK objects stay inside this boundary."""
import re

from ...domain.models import OperationError, SubmissionRejected, fail
from .mor import check_privileges


ACTIONS = {
    "host maintenance-enter": ("EnterMaintenanceMode_Task", False),
    "host maintenance-exit": ("ExitMaintenanceMode_Task", True),
}
PRIVILEGE = ("Host.Config.Maintenance",)
SUPPORTED_VERSION = re.compile(r"^(6\.[57]|7\.0|8\.0)(\.|$)")


class Hosts:
    def __init__(self, si, resolver=None):
        self.si = si
        self.content = si.RetrieveContent()
        self.server_uuid = getattr(getattr(self.content, "about", None), "instanceUuid", None)
        self.resolver = resolver or self.object

    def object(self, kind, object_id):
        from pyVmomi import vim

        classes = {"host": vim.HostSystem, "task": vim.Task}
        return classes[kind](object_id, self.si._stub)

    def _server(self):
        about = getattr(self.content, "about", None)
        api_type = getattr(about, "apiType", None)
        api_version = getattr(about, "apiVersion", None)
        server_uuid = getattr(about, "instanceUuid", None)
        if api_type != "VirtualCenter" or not isinstance(api_version, str) or not SUPPORTED_VERSION.match(api_version):
            fail("capability_unsupported", "当前只允许目标范围内的 vCenter 6.5/6.7/7.0/8.0", 4)
        if not isinstance(server_uuid, str) or not server_uuid:
            fail("target_unavailable", "无法确定 vCenter 唯一身份", 4)
        if server_uuid != self.server_uuid:
            fail("target_unavailable", "vCenter 身份在会话期间发生变化", 4)
        return server_uuid

    def _host(self, host_id):
        if not isinstance(host_id, str) or not re.fullmatch(r"host-\d+", host_id):
            fail("target_invalid", "必须提供精确 host-N 对象 ID，不支持名称或通配符", 2)
        host = self.resolver("host", host_id)
        if getattr(host, "_moId", None) != host_id:
            fail("target_unavailable", "主机对象身份与请求不匹配", 4)
        return host

    @staticmethod
    def _identity(host):
        system_info = getattr(getattr(host, "hardware", None), "systemInfo", None)
        hardware_uuid = getattr(system_info, "uuid", None)
        parent = getattr(host, "parent", None)
        parent_id = getattr(parent, "_moId", None)
        runtime = getattr(host, "runtime", None)
        connection = getattr(runtime, "connectionState", None)
        maintenance = getattr(runtime, "inMaintenanceMode", None)
        if not isinstance(hardware_uuid, str) or not hardware_uuid:
            fail("target_unavailable", "无法确定主机硬件 UUID", 4)
        if not isinstance(parent_id, str) or not parent_id:
            fail("target_unavailable", "无法确定主机父对象身份", 4)
        if not isinstance(connection, str) or not isinstance(maintenance, bool):
            fail("target_unavailable", "无法确定主机连接或维护状态", 4)
        return hardware_uuid, parent, parent_id, connection, maintenance

    def _existing_host(self, host_id):
        """Resolve a host and prove it exists before any precondition work.

        A well-formed but dangling MoRef (host-999999) is constructed without a
        fetch; the first property read (inside ``_identity``) raises
        ManagedObjectNotFound on real vCenter. Normalise that to a structured
        preflight failure (exit 4) instead of letting it surface as a top-level
        internal_error (exit 5). Only a fault naming the requested host is
        swallowed; a fault for any other object must propagate.
        """
        from pyVmomi import vmodl
        try:
            # Real resolver constructs lazily (fault fires on first property read);
            # an injected resolver may raise directly -- both are normalised here.
            host = self._host(host_id)
            identity = self._identity(host)
        except vmodl.fault.ManagedObjectNotFound as fault:
            missing = getattr(fault, "obj", None)
            if host_id is not None and getattr(missing, "_moId", None) in (host_id, None):
                fail("host_not_found", "指定主机不存在或已被删除: " + str(host_id), 4)
            raise
        return host, identity

    @staticmethod
    def _inventory(host):
        source = getattr(host, "vm", None)
        if not isinstance(source, (list, tuple)):
            fail("target_unavailable", "无法确定主机上的受影响 VM 集合", 4)
        result = []
        for vm in source:
            object_id = getattr(vm, "_moId", None)
            instance_uuid = getattr(getattr(vm, "config", None), "instanceUuid", None)
            power = getattr(getattr(vm, "runtime", None), "powerState", None)
            if (not isinstance(object_id, str) or not re.fullmatch(r"vm-\d+", object_id)
                    or not isinstance(instance_uuid, str) or not instance_uuid
                    or not isinstance(power, str) or power not in ("poweredOn", "poweredOff")):
                fail("target_unavailable", "受影响 VM 的身份或电源状态不完整", 4)
            result.append({
                "object_id": object_id,
                "instance_uuid": instance_uuid,
                "name": getattr(vm, "name", None),
                "power_state": power,
            })
        return sorted(result, key=lambda value: value["object_id"])

    @staticmethod
    def _drs_mode(parent):
        type_name = getattr(parent, "_wsdlName", type(parent).__name__)
        if type_name == "ComputeResource":
            return "notApplicable"
        configuration = getattr(parent, "configurationEx", None)
        drs = getattr(configuration, "drsConfig", None)
        mode = getattr(drs, "defaultVmBehavior", None)
        if type_name != "ClusterComputeResource" or mode not in (
                "manual", "partiallyAutomated", "fullyAutomated"):
            fail("target_unavailable", "无法确定主机所属计算资源的 DRS 模式", 4)
        return mode

    @staticmethod
    def _drs_enabled(parent):
        if getattr(parent, "_wsdlName", type(parent).__name__) == "ComputeResource":
            return False
        drs = getattr(getattr(parent, "configurationEx", None), "drsConfig", None)
        enabled = getattr(drs, "enabled", None)
        return enabled if isinstance(enabled, bool) else None

    def _privileges(self, host):
        check_privileges(self.content, host, PRIVILEGE,
                         denied="账户缺少 Host.Config.Maintenance 权限",
                         unable="无法核对主机维护权限")

    @staticmethod
    def _options(params):
        timeout = params.get("task_timeout", 300)
        evacuate = params.get("evacuate_powered_off_vms", False)
        allow_drs = params.get("allow_drs_migration", False)
        if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= 86400:
            fail("invalid_arguments", "task_timeout 必须为 1–86400 秒", 2)
        if not isinstance(evacuate, bool) or not isinstance(allow_drs, bool):
            fail("invalid_arguments", "主机维护授权参数必须为布尔值", 2)
        return timeout, evacuate, allow_drs

    def _migration_entitlements(self, host, parent, powered_on):
        from .licenses import Licenses

        members = getattr(parent, "host", None)
        if not isinstance(members, (list, tuple)) or not members:
            fail("target_unavailable", "无法确定 DRS 集群的参与主机集合", 4)
        identities = []
        for member in members:
            object_id = getattr(member, "_moId", None)
            if not isinstance(object_id, str) or not re.fullmatch(r"host-\d+", object_id):
                fail("target_unavailable", "DRS 参与主机身份不可确定", 4)
            uuid, _, parent_id, connection, maintenance = self._identity(member)
            if parent_id != parent._moId:
                fail("target_unavailable", "DRS 参与主机的集群归属不匹配", 4)
            identities.append({"object_id": object_id, "hardware_uuid": uuid,
                               "parent_id": parent_id, "connection_state": connection,
                               "in_maintenance_mode": maintenance})
        ids = [identity["object_id"] for identity in identities]
        if len(ids) != len(set(ids)) or host._moId not in ids:
            fail("target_unavailable", "DRS 集群成员重复或不包含目标主机", 4)
        source = next(identity for identity in identities if identity["object_id"] == host._moId)
        if source["hardware_uuid"] != self._identity(host)[0]:
            fail("target_unavailable", "DRS 集群中的目标主机身份不匹配", 4)
        identities.sort(key=lambda identity: identity["object_id"])
        required = ("drs", "vmotion") if powered_on else ("drs",)
        checker = Licenses(self.content)
        return {"members": identities, "licenses": [
            checker.require(identity["object_id"], required, self.server_uuid) for identity in identities
        ]}

    def preflight(self, command, params):
        if command not in ACTIONS:
            fail("capability_unsupported", "此主机变更尚未实现", 4)
        if not isinstance(params, dict):
            fail("invalid_arguments", "参数必须为对象", 2)
        self._server()
        timeout, evacuate, allow_drs = self._options(params)
        host, (hardware_uuid, parent, parent_id, connection, maintenance) = self._existing_host(
            params.get("host_id"))
        if connection != "connected":
            fail("target_unavailable", "主机不处于 connected 状态", 4)
        method, required_maintenance = ACTIONS[command]
        if maintenance is not required_maintenance:
            fail("precondition_failed", "主机当前维护状态不满足此操作", 4)
        disabled = getattr(host, "disabledMethod", None)
        if not isinstance(disabled, (list, tuple)):
            fail("target_unavailable", "无法确定主机当前禁用的方法集合", 4)
        if method in [str(value) for value in disabled] or not callable(getattr(host, method, None)):
            fail("capability_unsupported", "服务端禁用或不支持此维护方法", 4)
        self._privileges(host)
        vms = self._inventory(host)
        powered_on = [vm["object_id"] for vm in vms if vm["power_state"] == "poweredOn"]
        powered_off = [vm["object_id"] for vm in vms if vm["power_state"] == "poweredOff"]
        drs_mode = self._drs_mode(parent)
        drs_enabled = self._drs_enabled(parent)
        effects = []
        evacuation_scope = []
        capacity_warning = False
        entitlements = None
        if command == "host maintenance-enter":
            vsan = getattr(getattr(host, "config", None), "vsanHostConfig", None)
            vsan_enabled = getattr(vsan, "enabled", None)
            if vsan_enabled is not False:
                fail("precondition_failed", "vSAN 已启用或状态不可确定；当前范围不管理 vSAN 维护数据迁移", 4)
            if powered_on and not allow_drs:
                fail("precondition_failed", "主机存在开机 VM；必须显式允许 DRS 迁移", 4)
            if powered_on and drs_enabled is False:
                fail("precondition_failed", "DRS 已禁用，不能自动迁移开机 VM", 4)
            if powered_on and drs_enabled is None and self.content.about.apiVersion.startswith("6."):
                fail("target_unavailable", "无法确定 DRS 是否启用", 4)
            if powered_on and drs_mode != "fullyAutomated":
                fail("precondition_failed", "开机 VM 仅可在 fullyAutomated DRS 且明确授权时进入维护", 4)
            if evacuate and powered_off and drs_enabled is False:
                fail("precondition_failed", "DRS 未启用，不能自动撤离关机 VM", 4)
            if evacuate and powered_off and drs_enabled is None and self.content.about.apiVersion.startswith("6."):
                fail("target_unavailable", "无法确定 DRS 是否启用，不能确认关机 VM 可自动撤离", 4)
            if powered_on or (evacuate and powered_off):
                entitlements = self._migration_entitlements(host, parent, bool(powered_on))
            if powered_on:
                capacity_warning = True
                effects.append("fullyAutomated DRS may migrate powered-on VMs; VM overrides or insufficient capacity can still prevent completion")
            if evacuate:
                evacuation_scope = powered_off
                effects.append("explicitly evacuate the listed powered-off VMs")
            effects.append("no VM will be implicitly powered off")
        else:
            effects.append("exit maintenance mode without an additional evacuation operation")
        before = {
            "connection_state": connection,
            "in_maintenance_mode": maintenance,
            "vms": vms,
        }
        return {
            "target": self.server_uuid + ":" + host._moId,
            "server_uuid": self.server_uuid,
            "object_id": host._moId,
            "hardware_uuid": hardware_uuid,
            "parent_id": parent_id,
            "before": before,
            "authorization": {
                "allow_drs_migration": allow_drs,
                "evacuate_powered_off_vms": evacuate,
            },
            "impact": {
                "vms": vms,
                "drs_mode": drs_mode,
                "drs_enabled": drs_enabled,
                "powered_on_vm_ids": powered_on,
                "powered_off_evacuation_vm_ids": evacuation_scope,
                "capacity_may_prevent_completion": capacity_warning,
                "effects": effects,
            },
            "task_timeout": timeout,
            "migration_entitlements": entitlements,
            "risk": "change",
        }

    def bind_steps(self, steps):
        host_ids = [step.get("params", {}).get("host_id") for step in steps]
        if len(host_ids) != len(set(host_ids)):
            fail("plan_dependency_unsupported", "同一主机的维护步骤尚无安全状态投影，请拆分计划", 4)
        return [{**step, "binding": self.preflight(step["command"], step["params"])} for step in steps]

    @staticmethod
    def matches(expected, actual):
        return expected == actual

    def submit(self, command, params, binding):
        try:
            if command not in ACTIONS:
                fail("capability_unsupported", "此主机变更尚未实现", 4)
            if not self.matches(binding, self.preflight(command, params)):
                fail("plan_stale", "提交前主机身份、状态或受影响 VM 集合发生变化", 4)
            host = self._host(params["host_id"])
            timeout, evacuate, _ = self._options(params)
        except OperationError as exc:
            # Validation/reads only: no maintenance task was issued, so this is a
            # deterministic rejection safe to retry after a fresh preview.
            raise SubmissionRejected(exc.code, str(exc), exc.exit_code) from exc
        # From here the remote write may have happened: never raise
        # SubmissionRejected; let failures surface as uncertainty (exit 6).
        if command == "host maintenance-enter":
            task = host.EnterMaintenanceMode_Task(
                timeout=timeout,
                evacuatePoweredOffVms=evacuate,
            )
        else:
            task = host.ExitMaintenanceMode_Task(timeout=timeout)
        task_id = getattr(task, "_moId", None)
        if not isinstance(task_id, str) or not re.fullmatch(r"task-\d+", task_id):
            fail("receipt_missing", "远端已调用但未返回可持久化的 task-N 回执，禁止重发", 6)
        return {"server_uuid": self.server_uuid, "task_id": task_id, "entity_id": host._moId}

    def _task(self, receipt, binding):
        from pyVmomi import vmodl
        self._server()
        if not isinstance(receipt, dict) or not isinstance(binding, dict):
            fail("task_identity_mismatch", "任务回执或绑定格式无效", 4)
        server_uuid = receipt.get("server_uuid")
        task_id = receipt.get("task_id")
        entity_id = receipt.get("entity_id")
        if (server_uuid != self.server_uuid or server_uuid != binding.get("server_uuid")
                or not isinstance(task_id, str) or not re.fullmatch(r"task-\d+", task_id)
                or entity_id != binding.get("object_id")):
            fail("task_identity_mismatch", "任务的 vCenter、task-N 或主机绑定不匹配", 4)
        task = self.resolver("task", task_id)
        try:
            # Post-write evidence: the task or its target host may have been
            # removed after submit. A dangling MoRef here means the result cannot
            # be proven (unknown/6), never a deterministic not_found (exit 4).
            info = getattr(task, "info", None)
            key = getattr(info, "key", None)
            owner = getattr(getattr(info, "entity", None), "_moId", None)
        except vmodl.fault.ManagedObjectNotFound:
            fail("task_state_unknown", "任务或其目标主机在写后取证时已不存在，结果未知需人工核对", 6)
        if key != task_id or owner != entity_id:
            fail("task_identity_mismatch", "远端任务 key 或 entity 不属于固定主机", 4)
        return task, info

    def observe(self, receipt, binding):
        from pyVmomi import vmodl

        _, info = self._task(receipt, binding)
        state = getattr(info, "state", None)
        if not isinstance(state, str):
            fail("task_state_unknown", "远端任务状态不可确定", 6)
        error = getattr(info, "error", None)
        return {
            "state": state,
            "cancelled": isinstance(error, vmodl.fault.RequestCanceled),
            "task_key": info.key,
            "entity_id": info.entity._moId,
            "progress": getattr(info, "progress", None),
            "error_type": type(error).__name__ if error else None,
        }

    def verify(self, command, params, binding, observation):
        from pyVmomi import vmodl
        if command not in ACTIONS:
            return False
        try:
            self._server()
            host, (hardware_uuid, _, parent_id, connection, maintenance) = self._existing_host(
                params.get("host_id"))
        except OperationError:
            return False
        except vmodl.fault.ManagedObjectNotFound:
            # Post-write evidence expired (host or related object vanished): the
            # maintenance outcome cannot be proven, so verification stays negative
            # and reconciliation decides; never surface this as internal_error.
            return False
        expected = command == "host maintenance-enter"
        return (
            host._moId == binding.get("object_id")
            and hardware_uuid == binding.get("hardware_uuid")
            and parent_id == binding.get("parent_id")
            and connection == "connected"
            and maintenance is expected
        )

    def cancel(self, receipt, binding):
        task, info = self._task(receipt, binding)
        if getattr(info, "cancelable", None) is not True or getattr(info, "state", None) not in ("queued", "running"):
            fail("task_not_cancelable", "原主机维护任务当前不可取消", 4)
        cancel = getattr(task, "CancelTask", None)
        if not callable(cancel):
            fail("task_not_cancelable", "服务端不支持取消此任务", 4)
        self._server()
        cancel()
        return {
            "cancel_requested": True,
            "server_uuid": receipt["server_uuid"],
            "task_id": receipt["task_id"],
        }
