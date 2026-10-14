"""Remove a cluster member while preserving it in vCenter as a standalone host.

Automatic enrollment is unavailable: no verified delegated strict-pin API is
established for the supported vSphere versions. No host credential path exists.
"""
from ...domain.models import OperationError, fail
from .clusters import Clusters
from .hosts import Hosts


class Membership(Clusters):
    def object(self, kind, object_id):
        if kind == "host":
            from pyVmomi import vim
            return vim.HostSystem(object_id, self.si._stub)
        return super().object(kind, object_id)

    @staticmethod
    def _command(command):
        if command != "cluster remove-host":
            fail("command_unknown", "成员命令尚未实现或不存在", 2)

    def preflight(self, command, params):
        self._command(command)
        try:
            return self._preflight(command, params)
        except OperationError:
            raise
        except Exception:
            raise OperationError("membership_preflight_failed", "无法安全读取成员管理的身份、权限或状态", 4) from None

    def _preflight(self, command, params):
        from ...application.registry import lookup
        self._command(command)
        params = lookup(command).validate(params)
        self._server()
        cluster = self._resolve("cluster", params["cluster_id"])
        state = self._state(cluster)
        host = Hosts._host(self, params["host_id"])
        self._id(host, r"host-\d+", "HostSystem")
        uuid, _, parent_id, connection, maintenance = Hosts._identity(host)
        if (parent_id != cluster._moId or connection != "connected" or not maintenance
                or not any(h["object_id"] == host._moId and h["hardware_uuid"] == uuid for h in state["hosts"])):
            fail("precondition_failed", "主机须为目标集群中 connected 且处于维护模式的精确成员", 4)
        if Hosts._inventory(host) or state["child_pool_ids"]:
            fail("precondition_failed", "主机有 VM 或集群有子资源层级，请先独立处理", 4)
        folder = self._resolve("folder", params["folder_id"])
        destination = self._folder(folder)
        if destination["datacenter_id"] != state["datacenter_id"]:
            fail("precondition_failed", "仅允许移至同一数据中心的 host folder", 4)
        self._capability(folder, "MoveIntoFolder_Task", "Host.Inventory.AddStandaloneHost")
        self._privilege(host, "Host.Inventory.MoveHost")
        self._privilege(cluster, "Host.Inventory.EditCluster")
        return {"target": self.server_uuid + ":" + host._moId, "server_uuid": self.server_uuid,
                "object_id": folder._moId, "host_id": host._moId, "command": command,
                "hardware_uuid": uuid, "before": state, "destination": destination,
                "impact": {"effects": ["保留在 vCenter，转为独立主机", "不注销主机、不迁移 VM、不退出维护模式"]},
                "risk": "destructive"}

    def bind_steps(self, steps):
        # Membership changes affect shared cluster topology; no projected model.
        if len(steps) != 1:
            fail("plan_dependency_unsupported", "成员变更须分为独立单步计划", 4)
        return [{**step, "binding": self.preflight(step["command"], step["params"])} for step in steps]

    def submit(self, command, params, binding):
        self._command(command)
        if not self.matches(binding, self.preflight(command, params)):
            fail("plan_stale", "提交前主机身份、资源集合或集群状态变化，请重新预览", 4)
        try:
            task = self._resolve("folder", params["folder_id"]).MoveIntoFolder_Task(
                list=[Hosts._host(self, params["host_id"])])
            task_id = self._id(task, r"task-\d+", "Task")
        except Exception:
            # The common Engine persists unknown and never automatically retries.
            raise OperationError("membership_submission_unknown", "远端调用结果不确定；必须核对原操作，禁止重发", 6) from None
        return {"server_uuid": self.server_uuid, "task_id": task_id, "entity_id": binding["object_id"]}

    def observe(self, receipt, binding):
        self._command(binding.get("command") if isinstance(binding, dict) else None)
        try:
            return Hosts.observe(self, receipt, binding)
        except OperationError:
            raise
        except Exception:
            raise OperationError("membership_observation_failed", "无法安全读取原成员任务结果", 6) from None

    def cancel(self, receipt, binding):
        self._command(binding.get("command") if isinstance(binding, dict) else None)
        return Hosts.cancel(self, receipt, binding)

    def verify(self, command, params, binding, observation):
        if command != "cluster remove-host" or binding.get("command") != command:
            return False
        try:
            self._server()
            host_id = binding["host_id"]
            host = Hosts._host(self, host_id)
            self._id(host, r"host-\d+", "HostSystem")
            uuid, parent, _, connection, maintenance = Hosts._identity(host)
            if uuid != binding["hardware_uuid"] or connection != "connected" or Hosts._inventory(host):
                return False
            self._id(parent, r"domain-s\d+", "ComputeResource")
            return (maintenance and self._folder(parent.parent) == binding["destination"]
                    and [h._moId for h in self._list(parent, "host")] == [host_id]
                    and not self._list(parent.resourcePool, "vm")
                    and not self._list(parent.resourcePool, "resourcePool"))
        except Exception:
            return False
