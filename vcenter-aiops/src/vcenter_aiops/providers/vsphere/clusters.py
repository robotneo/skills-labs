"""Cluster lifecycle boundary with exact identity and conservative license checks."""
import re

from ...domain.models import fail
from .hosts import Hosts
from .licenses import Licenses


ACTIONS = {
    "cluster create": ("CreateClusterEx", "Host.Inventory.CreateCluster"),
    "cluster configure": ("ReconfigureComputeResource_Task", "Host.Inventory.EditCluster"),
    "cluster delete": ("Destroy_Task", "Host.Inventory.DeleteCluster"),
}
FIELDS = ("ha_enabled", "drs_enabled", "drs_automation", "drs_vmotion_rate")
MODES = ("manual", "partiallyAutomated", "fullyAutomated")


class Clusters:
    def __init__(self, si, resolver=None, licenses=None):
        self.si = si
        self.content = si.RetrieveContent()
        self.server_uuid = getattr(getattr(self.content, "about", None), "instanceUuid", None)
        self.resolver = resolver or self.object
        self.licenses = licenses or Licenses(self.content)

    _server = Hosts._server
    _task = Hosts._task
    matches = staticmethod(Hosts.matches)
    cancel = Hosts.cancel

    def object(self, kind, object_id):
        from pyVmomi import vim
        return {"cluster": vim.ClusterComputeResource, "folder": vim.Folder,
                "task": vim.Task}[kind](object_id, self.si._stub)

    @staticmethod
    def _id(obj, pattern, kind):
        object_id = getattr(obj, "_moId", None)
        if not isinstance(object_id, str) or not re.fullmatch(pattern, object_id):
            fail("target_unavailable", "对象身份不可确定", 4)
        if getattr(obj, "_wsdlName", type(obj).__name__) != kind:
            fail("target_invalid", "对象类型不匹配", 4)
        return object_id

    def _resolve(self, kind, object_id):
        pattern, typename = {"folder": (r"group-\w+", "Folder"),
                             "cluster": (r"domain-c\d+", "ClusterComputeResource")}[kind]
        if not isinstance(object_id, str) or not re.fullmatch(pattern, object_id):
            fail("target_invalid", "必须提供精确对象 ID", 2)
        obj = self.resolver(kind, object_id)
        if self._id(obj, pattern, typename) != object_id:
            fail("target_unavailable", "对象身份与请求不匹配", 4)
        return obj

    @staticmethod
    def _list(obj, attribute):
        value = getattr(obj, attribute, None)
        if not isinstance(value, (list, tuple)):
            fail("target_unavailable", "关键对象集合不可确定", 4)
        return value

    def _folder(self, folder):
        folder_id = self._id(folder, r"group-\w+", "Folder")
        # vCenter inventory uses both bare WSDL names and qualified SDK names.
        child_types = self._list(folder, "childType")
        if not any(value in ("ComputeResource", "vim.ComputeResource") for value in child_types):
            fail("target_invalid", "目标不是 host folder", 4)
        chain, current, visited = [], folder, set()
        while getattr(current, "_wsdlName", type(current).__name__) == "Folder":
            identity = self._id(current, r"group-\w+", "Folder")
            if identity in visited or len(visited) >= 100:
                fail("target_unavailable", "目录归属存在循环或过深", 4)
            visited.add(identity)
            chain.append(identity)
            current = getattr(current, "parent", None)
        dc_id = self._id(current, r"datacenter-\d+", "Datacenter")
        if getattr(getattr(current, "hostFolder", None), "_moId", None) != chain[-1]:
            fail("target_invalid", "目录不属于精确数据中心的 host folder", 4)
        return {"folder_id": folder_id, "datacenter_id": dc_id, "folder_chain": chain}

    def _configuration(self, cluster):
        config = getattr(cluster, "configurationEx", None)
        das, drs = getattr(config, "dasConfig", None), getattr(config, "drsConfig", None)
        values = {"ha_enabled": getattr(das, "enabled", None),
                  "drs_enabled": getattr(drs, "enabled", None),
                  "drs_automation": getattr(drs, "defaultVmBehavior", None),
                  "drs_vmotion_rate": getattr(drs, "vmotionRate", None)}
        rate = values["drs_vmotion_rate"]
        if (not isinstance(values["ha_enabled"], bool) or values["drs_automation"] not in MODES
                or not isinstance(rate, int) or isinstance(rate, bool) or not 1 <= rate <= 5
                or (self.content.about.apiVersion.startswith("6.") and not isinstance(values["drs_enabled"], bool))
                or (values["drs_enabled"] is not None and not isinstance(values["drs_enabled"], bool))):
            fail("target_unavailable", "关键 HA/DRS 配置不可确定", 4)
        return values

    def _state(self, cluster):
        parent = self._folder(getattr(cluster, "parent", None))
        pool = getattr(cluster, "resourcePool", None)
        pool_id = self._id(pool, r"resgroup-\d+", "ResourcePool")
        if getattr(getattr(pool, "owner", None), "_moId", None) != cluster._moId:
            fail("target_unavailable", "根资源池归属不匹配", 4)
        hosts = []
        for host in self._list(cluster, "host"):
            host_id = self._id(host, r"host-\d+", "HostSystem")
            uuid, _, parent_id, connection, maintenance = Hosts._identity(host)
            if parent_id != cluster._moId:
                fail("target_unavailable", "主机集群归属不匹配", 4)
            hosts.append({"object_id": host_id, "hardware_uuid": uuid, "connection_state": connection,
                          "in_maintenance_mode": maintenance, "vms": Hosts._inventory(host)})
        if len(hosts) != len({host["object_id"] for host in hosts}):
            fail("target_unavailable", "集群主机身份重复", 4)
        def identities(attribute, pattern, kind):
            ids = [self._id(obj, pattern, kind) for obj in self._list(pool, attribute)]
            if len(ids) != len(set(ids)):
                fail("target_unavailable", "根资源池集合身份重复", 4)
            return sorted(ids)
        name = getattr(cluster, "name", None)
        if not isinstance(name, str) or not name:
            fail("target_unavailable", "集群名称不可确定", 4)
        return {**parent, "name": name, "resource_pool_id": pool_id,
                "hosts": sorted(hosts, key=lambda host: host["object_id"]),
                "vm_ids": identities("vm", r"vm-\d+", "VirtualMachine"),
                "child_pool_ids": identities("resourcePool", r"resgroup-\d+", "ResourcePool"),
                "configuration": self._configuration(cluster)}

    def _changes(self, command, params):
        changes = {key: params[key] for key in FIELDS if key in params}
        if command == "cluster create":
            changes = {"ha_enabled": False, "drs_automation": "manual", **changes}
        elif not changes:
            fail("invalid_arguments", "至少指定一个 HA/DRS 配置字段", 2)
        for key in ("ha_enabled", "drs_enabled"):
            if key in changes and not isinstance(changes[key], bool):
                fail("invalid_arguments", "HA/DRS enabled 必须为布尔值", 2)
        if "drs_automation" in changes and changes["drs_automation"] not in MODES:
            fail("invalid_arguments", "DRS automation 无效", 2)
        rate = changes.get("drs_vmotion_rate")
        if "drs_vmotion_rate" in changes and (not isinstance(rate, int) or isinstance(rate, bool) or not 1 <= rate <= 5):
            fail("invalid_arguments", "DRS vmotion rate 必须为 1–5", 2)
        if "drs_enabled" in changes and not self.content.about.apiVersion.startswith("6."):
            fail("capability_unsupported", "vSphere 7/8 的 drs_enabled 已弃用；请明确设置 drs_automation", 4)
        if changes.get("drs_enabled") is False and changes.get("drs_automation", "manual") != "manual":
            fail("invalid_arguments", "禁用 DRS 与自动模式矛盾", 2)
        return changes

    def _capability(self, obj, method, privilege):
        disabled = self._list(obj, "disabledMethod")
        if method in [str(value) for value in disabled] or not callable(getattr(obj, method, None)):
            fail("capability_unsupported", "方法被禁用或不可用", 4)
        self._privilege(obj, privilege)

    def _privilege(self, obj, privilege):
        session = getattr(getattr(self.content, "sessionManager", None), "currentSession", None)
        key = getattr(session, "key", None)
        check = getattr(getattr(self.content, "authorizationManager", None), "HasPrivilegeOnEntity", None)
        if not isinstance(key, str) or not key or not callable(check):
            fail("permission_denied", "无法核对集群权限", 4)
        granted = check(entity=obj, sessionId=key, privId=[privilege])
        if not isinstance(granted, (list, tuple)) or len(granted) != 1 or granted[0] is not True:
            fail("permission_denied", "账户缺少集群操作权限", 4)

    def preflight(self, command, params):
        self._server()
        if command not in ACTIONS or not isinstance(params, dict):
            fail("invalid_arguments", "集群命令或参数无效", 2)
        from ...application.registry import lookup
        params = lookup(command).validate(params)
        method, privilege = ACTIONS[command]
        changes, evidence, effects = {}, [], []
        if command == "cluster create":
            obj = self._resolve("folder", params.get("folder_id"))
            state = self._folder(obj)
            children = []
            for child in self._list(obj, "childEntity"):
                identity, name = getattr(child, "_moId", None), getattr(child, "name", None)
                if not isinstance(identity, str) or not identity or not isinstance(name, str) or not name:
                    fail("target_unavailable", "目录成员身份或名称不可读", 4)
                if name == params["name"]:
                    fail("precondition_failed", "目标目录已存在同名对象", 4)
                children.append({"object_id": identity, "name": name})
            state["children"] = sorted(children, key=lambda child: child["object_id"])
            changes = self._changes(command, params)
            hosts = []
        else:
            obj = self._resolve("cluster", params.get("cluster_id"))
            state = self._state(obj)
            hosts = state["hosts"]
            if command == "cluster delete":
                if hosts or state["vm_ids"] or state["child_pool_ids"]:
                    fail("precondition_failed", "只允许删除无主机、无 VM、无子资源池的空集群", 4)
                effects.append("destroy only the bound empty cluster; no implicit resource evacuation")
            else:
                changes = self._changes(command, params)
                if changes.get("drs_enabled") is False and state["child_pool_ids"]:
                    fail("precondition_failed", "有子资源池时拒绝禁用旧版 DRS，禁止隐式折叠资源层级", 4)
                current = state["configuration"]
                if current["drs_enabled"] is False and changes.get("drs_automation", "manual") != "manual" and self.content.about.apiVersion.startswith("6.") and changes.get("drs_enabled") is not True:
                    fail("precondition_failed", "旧版 DRS 已禁用，自动模式须明确启用 DRS", 4)
        self._capability(obj, method, privilege)
        if command == "cluster delete":
            self._privilege(obj.parent, privilege)
        required = set()
        if changes.get("ha_enabled") is True:
            required.add("das")
            effects.append("enabling HA can restart protected VMs after host failures")
        if changes.get("drs_enabled") is True or "drs_automation" in changes or "drs_vmotion_rate" in changes:
            if command != "cluster create" or changes.get("drs_automation") != "manual" or changes.get("drs_enabled") is True:
                required.add("drs")
        effective = {**state.get("configuration", {}), **changes}
        if effective.get("drs_automation") == "fullyAutomated" and any(key in changes for key in ("drs_enabled", "drs_automation", "drs_vmotion_rate")):
            required.add("vmotion")
            effects.append("fullyAutomated DRS may migrate the listed VMs; overrides and capacity can prevent completion")
        elif changes.get("drs_automation") == "partiallyAutomated":
            effects.append("partiallyAutomated DRS may select initial VM placement and recommend migrations")
        if required:
            if not hosts:
                fail("license_unknown", "空集群没有精确主机许可证据，拒绝启用或改变授权功能", 4)
            evidence = [self.licenses.require(host["object_id"], required, self.server_uuid) for host in hosts]
        return {"target": self.server_uuid + ":" + obj._moId, "server_uuid": self.server_uuid,
                "object_id": obj._moId, "before": state, "changes": changes,
                "name": params.get("name"), "impact": {"hosts": hosts, "effects": effects},
                "license_evidence": evidence, "risk": "destructive" if command == "cluster delete" else "change"}

    def bind_steps(self, steps):
        targets = [step["params"].get("cluster_id", step["params"].get("folder_id")) for step in steps]
        if len(targets) != len(set(targets)):
            fail("plan_dependency_unsupported", "同目标集群计划尚无安全状态投影，请拆分计划", 4)
        return [{**step, "binding": self.preflight(step["command"], step["params"])} for step in steps]

    @staticmethod
    def _spec(changes):
        from pyVmomi import vim
        spec = vim.cluster.ConfigSpecEx()
        if "ha_enabled" in changes:
            spec.dasConfig = vim.cluster.DasConfigInfo(enabled=changes["ha_enabled"])
        drs = {sdk: changes[key] for key, sdk in (("drs_enabled", "enabled"), ("drs_automation", "defaultVmBehavior"),
                                                ("drs_vmotion_rate", "vmotionRate")) if key in changes}
        if drs:
            spec.drsConfig = vim.cluster.DrsConfigInfo(**drs)
        return spec

    def submit(self, command, params, binding):
        if not self.matches(binding, self.preflight(command, params)):
            fail("plan_stale", "集群身份、集合或配置发生变化，请重新预览", 4)
        if command == "cluster create":
            obj = self._resolve("folder", params["folder_id"])
            result = obj.CreateClusterEx(name=params["name"], spec=self._spec(binding["changes"]))
            object_id = self._id(result, r"domain-c\d+", "ClusterComputeResource")
            return {"kind": "object", "server_uuid": self.server_uuid, "object_id": object_id,
                    "folder_id": obj._moId, "name": params["name"]}
        obj = self._resolve("cluster", params["cluster_id"])
        task = obj.Destroy_Task() if command == "cluster delete" else obj.ReconfigureComputeResource_Task(spec=self._spec(binding["changes"]), modify=True)
        task_id = getattr(task, "_moId", None)
        if not isinstance(task_id, str) or not re.fullmatch(r"task-\d+", task_id):
            fail("receipt_missing", "远端已调用但 task-N 回执缺失，禁止重发", 6)
        return {"server_uuid": self.server_uuid, "task_id": task_id, "entity_id": obj._moId}

    def observe(self, receipt, binding):
        if isinstance(receipt, dict) and receipt.get("kind") == "object":
            self._server()
            if (receipt.get("server_uuid") != self.server_uuid or binding.get("server_uuid") != self.server_uuid
                    or receipt.get("folder_id") != binding.get("object_id") or receipt.get("name") != binding.get("name")
                    or not isinstance(receipt.get("object_id"), str) or not re.fullmatch(r"domain-c\d+", receipt["object_id"])):
                fail("receipt_identity_mismatch", "同步对象回执归属不匹配", 4)
            return {"state": "success", "receipt_kind": "object", "object_id": receipt["object_id"]}
        return Hosts.observe(self, receipt, binding)

    def verify(self, command, params, binding, observation):
        from pyVmomi import vmodl
        try:
            self._server()
            if command == "cluster delete":
                try:
                    obj = self._resolve("cluster", binding["object_id"])
                    # Reading a property forces an SDK lookup of the exact MoRef.
                    _ = obj.name
                except vmodl.fault.ManagedObjectNotFound as fault:
                    missing = getattr(fault, "obj", None)
                    return (getattr(missing, "_moId", None) == binding["object_id"]
                            and getattr(missing, "_wsdlName", None) == "ClusterComputeResource")
                return False
            object_id = observation.get("object_id") if command == "cluster create" else binding["object_id"]
            obj = self._resolve("cluster", object_id)
            state = self._state(obj)
            if command == "cluster create":
                if (state["folder_id"] != binding["object_id"] or state["name"] != params["name"]
                        or state["datacenter_id"] != binding["before"]["datacenter_id"]
                        or state["hosts"] or state["vm_ids"] or state["child_pool_ids"]):
                    return False
            else:
                for key in ("folder_id", "datacenter_id", "folder_chain", "resource_pool_id", "hosts", "vm_ids", "child_pool_ids", "name"):
                    if state[key] != binding["before"][key]:
                        return False
            expected = {**binding["before"].get("configuration", {}), **binding["changes"]}
            return all(state["configuration"][key] == value for key, value in expected.items())
        except Exception:
            return False
