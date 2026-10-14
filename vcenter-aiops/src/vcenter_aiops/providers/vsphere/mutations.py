"""vCenter-only mutation provider; no SDK object escapes this boundary."""
import re
from dataclasses import dataclass

from ...domain.models import OperationError, SubmissionRejected, fail


@dataclass(frozen=True)
class Action:
    method: str
    privilege: tuple
    powers: tuple = ()
    destructive: bool = False


ACTIONS = {
    "vm power-on": Action("PowerOnVM_Task", ("VirtualMachine.Interact.PowerOn",), ("poweredOff", "suspended")),
    "vm shutdown": Action("ShutdownGuest", ("VirtualMachine.Interact.PowerOff",), ("poweredOn",)),
    "vm power-off": Action("PowerOffVM_Task", ("VirtualMachine.Interact.PowerOff",), ("poweredOn", "suspended")),
    "vm reset": Action("ResetVM_Task", ("VirtualMachine.Interact.Reset",), ("poweredOn",)),
    "vm suspend": Action("SuspendVM_Task", ("VirtualMachine.Interact.Suspend",), ("poweredOn",)),
    "vm rename": Action("Rename_Task", ("VirtualMachine.Config.Rename",)),
    "vm reconfigure": Action("ReconfigVM_Task", ("VirtualMachine.Config.CPUCount", "VirtualMachine.Config.Memory"), ("poweredOff",)),
    "vm delete": Action("Destroy_Task", ("VirtualMachine.Inventory.Delete",), ("poweredOff",), True),
    "vm snapshot-create": Action("CreateSnapshot_Task", ("VirtualMachine.State.CreateSnapshot",)),
    "vm snapshot-revert": Action("RevertToSnapshot_Task", ("VirtualMachine.State.RevertToSnapshot",), (), True),
    "vm snapshot-delete": Action("RemoveSnapshot_Task", ("VirtualMachine.State.RemoveSnapshot",), (), True),
    "deploy mark-template": Action("MarkAsTemplate", ("VirtualMachine.Provisioning.MarkAsTemplate",), ("poweredOff",)),
    "template convert": Action("MarkAsVirtualMachine", ("VirtualMachine.Provisioning.MarkAsVM",), ("poweredOff",)),
    "deploy iso": Action("ReconfigVM_Task", ("VirtualMachine.Config.EditDevice", "VirtualMachine.Interact.SetCDMedia", "VirtualMachine.Interact.DeviceConnection"), ("poweredOff",)),
    "deploy unmount-iso": Action("ReconfigVM_Task", ("VirtualMachine.Config.EditDevice", "VirtualMachine.Interact.SetCDMedia", "VirtualMachine.Interact.DeviceConnection"), ("poweredOff",)),
    "vm clone": Action("CloneVM_Task", ("VirtualMachine.Provisioning.Clone",)),
    "deploy linked-clone": Action("CloneVM_Task", ("VirtualMachine.Provisioning.Clone",), ("poweredOff",)),
    "deploy template": Action("CloneVM_Task", ("VirtualMachine.Provisioning.DeployTemplate",)),
    "vm migrate": Action("RelocateVM_Task", ("Resource.ColdMigrate",)),
}


class Mutations:
    def __init__(self, si, resolver=None):
        self.si = si
        self.content = si.RetrieveContent()
        self.server_uuid = self.content.about.instanceUuid
        self.resolver = resolver or self.object

    def configure_evidence(self, store, profile):
        from ...application.dependencies import Dependencies
        from ...application.searches import Searches
        self.parent_dependencies = Dependencies(store).records
        self.search_record = Searches(store, None, profile).record

    def object(self, kind, object_id):
        from pyVmomi import vim
        classes = {"vm": vim.VirtualMachine, "task": vim.Task, "folder": vim.Folder, "pool": vim.ResourcePool,
                   "datastore": vim.Datastore, "host": vim.HostSystem}
        return classes[kind](object_id, self.si._stub)

    def vm(self, object_id):
        if not re.fullmatch(r"vm-\d+", object_id):
            fail("target_invalid", "必须提供精确 vm-N 对象 ID，不支持通配符", 2)
        vm = self.resolver("vm", object_id)
        if vm._moId != object_id:
            fail("target_changed", "解析返回的 VM 对象 ID 与请求不一致", 4)
        if vm.config is None or not vm.config.instanceUuid:
            fail("target_unavailable", "无法获取 VM 唯一身份", 4)
        return vm

    def privileges(self, vm, required):
        session = self.content.sessionManager.currentSession
        if not session:
            fail("session_missing", "服务端会话不可用", 3)
        granted = self.content.authorizationManager.HasPrivilegeOnEntity(entity=vm, sessionId=session.key, privId=list(required))
        if len(granted) != len(required) or not all(granted):
            fail("permission_denied", "账户缺少此操作所需权限", 4)

    def snapshots(self, vm):
        roots = vm.snapshot.rootSnapshotList if vm.snapshot else []
        stack, result = list(roots), []
        while stack:
            node = stack.pop()
            result.append(node)
            stack.extend(node.childSnapshotList or [])
        return result

    def snapshot(self, vm, snapshot_id):
        nodes = [n for n in self.snapshots(vm) if n.snapshot._moId == snapshot_id]
        if len(nodes) != 1:
            fail("snapshot_not_found", "快照不属于此 VM 或不存在", 4)
        return nodes[0]

    def preflight(self, command, params, projected=None):
        if command in ("vm reconfigure", "deploy iso", "deploy unmount-iso", "template convert", "deploy linked-clone", "vm migrate"):
            from ...application.registry import lookup
            params = lookup(command).validate(params)
        if command == "alarm acknowledge":
            from .alarms import Alarms
            return Alarms(self.si).preflight_acknowledge(params)
        if command == "alarm reset":
            from .alarms import Alarms
            return Alarms(self.si).preflight_reset(params)
        if command not in ACTIONS:
            fail("capability_unsupported", "此变更尚未实现", 4)
        if self.content.about.apiType != "VirtualCenter" or not re.match(r"^(6\.[57]|7\.0|8\.0)(\.|$)", self.content.about.apiVersion):
            fail("capability_unsupported", "当前只允许目标范围内的 vCenter 6.5/6.7/7.0/8.0", 4)
        action = ACTIONS[command]
        vm = self.vm(params["vm_id"])
        if vm.runtime.connectionState != "connected":
            fail("target_unavailable", "VM 不处于已连接状态", 4)
        before = {"power": str(vm.runtime.powerState), "name": vm.name,
                  "change_version": vm.config.changeVersion, "template": vm.config.template,
                  "cpu": vm.config.hardware.numCPU, "memory_mb": vm.config.hardware.memoryMB}
        before.update(projected or {})
        if before.get("removed") or before.get("unpredictable"):
            fail("plan_dependency_unsupported", "此步骤依赖删除或快照恢复后的未知状态，请拆分并重新预览", 4)
        if command in ("deploy template", "template convert") and not before["template"]:
            fail("precondition_failed", "模板部署或转换要求源对象为模板", 4)
        if before["template"] and command not in ("deploy template", "template convert"):
            fail("precondition_failed", "该命令要求普通 VM，目标是模板", 4)
        if action.powers and before["power"] not in action.powers:
            fail("precondition_failed", "电源状态不满足操作要求；不会隐式执行其他电源操作", 4)
        from .linked import guard
        guard(self, vm, command, params)
        obj = vm
        if command in ("vm snapshot-revert", "vm snapshot-delete"):
            node = self.snapshot(vm, params["snapshot_id"])
            if command == "vm snapshot-delete" and node.childSnapshotList:
                fail("precondition_failed", "快照含子快照，禁止隐式删除子树", 4)
            obj = node.snapshot
        if (not projected and action.method in [str(x) for x in vm.disabledMethod or []]) or not callable(getattr(obj, action.method, None)):
            fail("capability_unsupported", "服务端禁用或不支持此方法", 4)
        required = action.privilege
        if command == "vm migrate" and before["power"] == "poweredOn":
            required += ("Resource.HotMigrate",)
        if command == "vm reconfigure":
            required = tuple(x for key, x in (("cpu", "VirtualMachine.Config.CPUCount"), ("memory_gb", "VirtualMachine.Config.Memory")) if key in params)
            if "disks" in params:
                required += tuple(x for op, x in (("expand", "VirtualMachine.Config.DiskExtend"), ("add", "VirtualMachine.Config.AddNewDisk"))
                                  if any(d.get("operation") == op for d in params["disks"] if isinstance(d, dict)))
            if not required:
                fail("invalid_arguments", "至少指定 CPU、内存或磁盘", 2)
        self.privileges(vm, required)
        if command == "vm shutdown" or params.get("quiesce"):
            if vm.guest.toolsRunningStatus != "guestToolsRunning":
                fail("tools_unavailable", "VMware Tools 未运行，不会回退为强制操作", 4)
        if params.get("memory") and before["power"] != "poweredOn":
            fail("precondition_failed", "内存快照要求 VM 开机", 4)
        if "snapshot_id" in params:
            before["snapshot_id"] = params["snapshot_id"]
        binding = {"target": self.server_uuid + ":" + vm._moId, "server_uuid": self.server_uuid,
                "object_id": vm._moId, "instance_uuid": vm.config.instanceUuid, "before": before,
                "risk": "destructive" if action.destructive else "change"}
        if command == "template convert":
            from .templates import conversion_placement
            binding["placement"] = conversion_placement(self, vm, params)
        if command == "deploy linked-clone":
            from .linked import preflight, WARNING
            binding["placement"], binding["parent_dependency"] = preflight(self, vm, params)
            binding["warnings"] = [WARNING]
        if command in ("vm clone", "deploy template", "vm migrate"):
            from .placement import preflight
            binding["placement"] = preflight(self, vm, params, command)
        if command == "vm reconfigure" and "disks" in params:
            from .devices import preflight
            binding["disks"] = preflight(self, vm, params["disks"])
            binding["uncompensated"] = ["disks"]
            binding["warnings"] = ["磁盘新增和扩容不可保证补偿；计划回滚不会隐式删除或缩容"]
        if command in ("deploy iso", "deploy unmount-iso"):
            from .media import preflight, WARNING
            binding["media"] = preflight(self, vm, params, command == "deploy iso")
            if command == "deploy iso":
                binding["warnings"] = [WARNING]
        return binding

    def bind_steps(self, steps):
        projected, output = {}, []
        for step in steps:
            command, params = step["command"], step["params"]
            if command == "alarm acknowledge":
                if len(steps) != 1:
                    fail("plan_dependency_unsupported", "告警确认当前要求独立计划", 4)
                output.append({**step, "binding": self.preflight(command, params)})
                continue
            if command == "alarm reset":
                if len(steps) != 1:
                    fail("plan_dependency_unsupported", "告警重置为批量写，要求独立计划", 4)
                output.append({**step, "binding": self.preflight(command, params)})
                continue
            binding = self.preflight(command, params, projected.get(params["vm_id"]))
            output.append({**step, "binding": binding})
            after = dict(binding["before"])
            after.pop("snapshot_id", None)
            power = {"vm power-on": "poweredOn", "vm power-off": "poweredOff", "vm shutdown": "poweredOff", "vm suspend": "suspended"}
            if command in power:
                after["power"] = power[command]
            if command == "vm rename":
                after.update(name=params["new_name"], change_version="$previous_step")
            if command == "vm reconfigure":
                after.update(cpu=params.get("cpu", after["cpu"]), memory_mb=params["memory_gb"] * 1024 if "memory_gb" in params else after["memory_mb"], change_version="$previous_step")
                if "disks" in params:
                    after["unpredictable"] = True
            if command == "deploy mark-template":
                after["template"] = True
            if command == "template convert":
                after["unpredictable"] = True
            if command == "vm delete":
                after["removed"] = True
            if command == "vm snapshot-revert":
                after["unpredictable"] = True
            if command in ("deploy iso", "deploy unmount-iso"):
                after["unpredictable"] = True
            projected[params["vm_id"]] = after
        return output

    @staticmethod
    def matches(expected, actual):
        actual = {**actual, "before": dict(actual["before"])}
        if expected["before"].get("change_version") == "$previous_step":
            actual["before"]["change_version"] = "$previous_step"
        return expected == actual

    def submit(self, command, params, binding):
        if command == "alarm acknowledge":
            from .alarms import Alarms
            return Alarms(self.si).submit_acknowledge(params, binding)
        if command == "alarm reset":
            from .alarms import Alarms
            try:
                return Alarms(self.si).submit_reset(params, binding)
            except OperationError as exc:
                # submit_reset re-runs read-only preflight before the single bulk
                # write; a failure there is a rejection before any remote write.
                raise SubmissionRejected(exc.code, str(exc), exc.exit_code) from exc
        try:
            if not self.matches(binding, self.preflight(command, params)):
                fail("plan_stale", "提交前目标身份或状态变化", 4)
            vm = self.vm(params["vm_id"])
        except OperationError as exc:
            # This scope contains validation/reads only. The write method and
            # its response handling below must never emit this guarantee.
            raise SubmissionRejected(exc.code, str(exc), exc.exit_code) from exc
        task = getattr(self, "submit_" + command.replace(" ", "_").replace("-", "_"))(vm, params)
        return {"task_id": self.server_uuid + ":" + task._moId} if task is not None else {"acknowledged": True, "command": command}

    def submit_vm_power_on(self, vm, p):
        return vm.PowerOnVM_Task()

    def submit_vm_shutdown(self, vm, p):
        return vm.ShutdownGuest()

    def submit_vm_power_off(self, vm, p):
        return vm.PowerOffVM_Task()

    def submit_vm_reset(self, vm, p):
        return vm.ResetVM_Task()

    def submit_vm_suspend(self, vm, p):
        return vm.SuspendVM_Task()

    def submit_vm_rename(self, vm, p):
        return vm.Rename_Task(newName=p["new_name"])

    def submit_vm_reconfigure(self, vm, p):
        from pyVmomi import vim
        spec = vim.vm.ConfigSpec(changeVersion=vm.config.changeVersion)
        if "cpu" in p:
            spec.numCPUs = p["cpu"]
        if "memory_gb" in p:
            spec.memoryMB = p["memory_gb"] * 1024
        if "disks" in p:
            from .devices import changes
            spec.deviceChange = changes(self, vm, p["disks"])
        return vm.ReconfigVM_Task(spec=spec)

    def submit_vm_delete(self, vm, p):
        return vm.Destroy_Task()

    def submit_vm_snapshot_create(self, vm, p):
        return vm.CreateSnapshot_Task(name=p["snapshot_name"], description=p.get("description", ""), memory=p.get("memory", False), quiesce=p.get("quiesce", False))

    def submit_vm_snapshot_revert(self, vm, p):
        return self.snapshot(vm, p["snapshot_id"]).snapshot.RevertToSnapshot_Task(suppressPowerOn=True)

    def submit_vm_snapshot_delete(self, vm, p):
        return self.snapshot(vm, p["snapshot_id"]).snapshot.RemoveSnapshot_Task(removeChildren=False)

    def submit_deploy_mark_template(self, vm, p):
        return vm.MarkAsTemplate()

    def submit_template_convert(self, vm, p):
        return vm.MarkAsVirtualMachine(pool=self.resolver("pool", p["pool_id"]), host=self.resolver("host", p["host_id"]))

    def submit_deploy_iso(self, vm, p):
        from pyVmomi import vim
        from .media import changes
        return vm.ReconfigVM_Task(spec=vim.vm.ConfigSpec(changeVersion=vm.config.changeVersion, deviceChange=changes(self, vm, p, True)))

    def submit_deploy_unmount_iso(self, vm, p):
        from pyVmomi import vim
        from .media import changes
        return vm.ReconfigVM_Task(spec=vim.vm.ConfigSpec(changeVersion=vm.config.changeVersion, deviceChange=changes(self, vm, p, False)))

    def submit_vm_clone(self, vm, p):
        from .placement import clone
        return clone(self, vm, p)

    def submit_deploy_linked_clone(self, vm, p):
        from .linked import clone
        return clone(self, vm, p)

    def submit_deploy_template(self, vm, p):
        from .placement import clone
        return clone(self, vm, p)

    def submit_vm_migrate(self, vm, p):
        from .placement import migrate
        return migrate(self, vm, p)

    def observe(self, receipt, binding):
        from pyVmomi import vmodl
        if binding["server_uuid"] != self.server_uuid:
            fail("server_mismatch", "操作属于其他 vCenter", 4)
        if "task_id" not in receipt:
            if receipt.get("command") == "vm shutdown":
                vm = self.vm(binding["object_id"])
                if vm.config.instanceUuid != binding["instance_uuid"]:
                    fail("target_changed", "VM 身份已变化", 4)
                return {"state": "success" if vm.runtime.powerState == "poweredOff" else "running"}
            if receipt.get("command") == "alarm reset":
                # ClearTriggeredAlarms is synchronous and void with no Task: the
                # call returning without a fault means the bulk reset was accepted.
                # Final evidence that the bound set actually turned green is the
                # separate verify() read below (engine poll calls both).
                return {"state": "success", "reset": True}
            return {"state": "success", "acknowledged": receipt.get("acknowledged", False)}
        prefix, task_id = receipt["task_id"].split(":", 1)
        if prefix != self.server_uuid or not re.fullmatch(r"task-\d+", task_id):
            fail("task_identity_mismatch", "任务身份不匹配", 4)
        info = self.resolver("task", task_id).info
        error = info.error
        result = info.result
        observation = {"state": str(info.state), "cancelled": isinstance(error, vmodl.fault.RequestCanceled),
                "result_id": getattr(result, "_moId", None), "progress": info.progress,
                "error_type": type(error).__name__ if error else None}
        if "parent_dependency" in binding and str(info.state) == "success":
            from pyVmomi import vim
            if not isinstance(result, vim.VirtualMachine):
                observation["result_id"] = None
            else:
                observation["instance_uuid"] = self.vm(result._moId).config.instanceUuid
        return observation

    def verify(self, command, params, binding, observation):
        if command == "alarm acknowledge":
            from .alarms import Alarms
            return Alarms(self.si).verify_acknowledge(params, binding)
        if command == "alarm reset":
            from .alarms import Alarms
            return Alarms(self.si).verify_reset(params, binding)
        from pyVmomi import vmodl
        try:
            vm = self.vm(params["vm_id"])
        except vmodl.fault.ManagedObjectNotFound:
            return command == "vm delete"
        if vm.config.instanceUuid != binding["instance_uuid"]:
            return False
        expected = {"vm power-on": "poweredOn", "vm shutdown": "poweredOff", "vm power-off": "poweredOff", "vm suspend": "suspended", "vm reset": "poweredOn"}
        if command in expected:
            return vm.runtime.powerState == expected[command]
        if command == "vm rename":
            return vm.name == params["new_name"]
        if command == "vm reconfigure":
            from .devices import verify
            return (("cpu" not in params or vm.config.hardware.numCPU == params["cpu"])
                    and ("memory_gb" not in params or vm.config.hardware.memoryMB == params["memory_gb"] * 1024)
                    and ("disks" not in params or verify(vm, binding["disks"])))
        if command == "vm snapshot-create":
            return any(n.snapshot._moId == observation.get("result_id") for n in self.snapshots(vm))
        if command == "vm snapshot-delete":
            return not any(n.snapshot._moId == params["snapshot_id"] for n in self.snapshots(vm))
        if command == "vm snapshot-revert":
            return vm.snapshot is not None and vm.snapshot.currentSnapshot._moId == params["snapshot_id"]
        if command == "deploy mark-template":
            return vm.config.template is True
        if command == "template convert":
            return (vm.config.template is False and vm.name == binding["before"]["name"]
                    and vm.runtime.powerState == "poweredOff" and vm.resourcePool._moId == params["pool_id"]
                    and vm.runtime.host._moId == params["host_id"])
        if command in ("deploy iso", "deploy unmount-iso"):
            from .media import verify
            return verify(vm, params, binding["media"], command == "deploy iso")
        if command in ("vm clone", "deploy template"):
            if not observation.get("result_id"):
                return False
            created = self.vm(observation["result_id"])
            return (created.config.instanceUuid != binding["instance_uuid"] and created.name == params["name"]
                    and created.parent._moId == params["folder_id"] and created.resourcePool._moId == params["pool_id"]
                    and created.runtime.host._moId == params["host_id"] and created.runtime.powerState == "poweredOff"
                    and params["datastore_id"] in [d._moId for d in created.datastore])
        if command == "deploy linked-clone":
            from .linked import verify
            return verify(self, params, binding, observation)
        if command == "vm migrate":
            if "datastore_id" not in params:
                from .linked import compute_disks
                try:
                    if compute_disks(self, vm) != binding["placement"]["source_disks"]:
                        return False
                except OperationError:
                    return False
            return (vm.runtime.host._moId == params["host_id"] and vm.resourcePool._moId == params["pool_id"]
                    and (params["datastore_id"] in [d._moId for d in vm.datastore] if "datastore_id" in params
                         else sorted(d._moId for d in vm.datastore) == binding["placement"]["datastore_ids"]))
        return False

    def cancel(self, receipt, binding):
        if binding["server_uuid"] != self.server_uuid:
            fail("server_mismatch", "原任务属于其他 vCenter", 4)
        prefix, task_id = receipt["task_id"].split(":", 1)
        if prefix != self.server_uuid or not re.fullmatch(r"task-\d+", task_id):
            fail("task_identity_mismatch", "任务身份不匹配", 4)
        task = self.resolver("task", task_id)
        info = task.info
        if not info.cancelable or info.state not in ("queued", "running"):
            fail("task_not_cancelable", "原任务当前不可取消", 4)
        task.CancelTask()
