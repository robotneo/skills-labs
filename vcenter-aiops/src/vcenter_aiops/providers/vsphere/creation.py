"""Create a powered-off empty VM; task result supplies the new VM identity."""
import re

from ...domain.models import OperationError, SubmissionRejected, fail
from ...domain.naming import valid_name
from .clusters import Clusters
from .hosts import Hosts
from . import hardware, placement


class Creation:
    def __init__(self, si, resolver=None):
        self.si = si
        self.content = si.RetrieveContent()
        self.server_uuid = getattr(getattr(self.content, "about", None), "instanceUuid", None)
        self.resolver = resolver or self.object

    _server = Hosts._server
    matches = staticmethod(Hosts.matches)
    _id = staticmethod(Clusters._id)
    _list = staticmethod(Clusters._list)
    _privilege = Clusters._privilege
    _capability = Clusters._capability
    cancel = Hosts.cancel

    def object(self, kind, object_id):
        from pyVmomi import vim
        classes = {"folder": vim.Folder, "pool": vim.ResourcePool, "host": vim.HostSystem,
                   "datastore": vim.Datastore, "network": vim.Network, "vm": vim.VirtualMachine,
                   "task": vim.Task}
        cls = vim.dvs.DistributedVirtualPortgroup if kind == "network" and object_id.startswith("dvportgroup-") else classes[kind]
        return cls(object_id, self.si._stub)

    def _objects(self, params):
        objects = placement.resolve(self, params)
        network_id = params["network_id"]
        objects["network"] = placement.resource(self, "network", network_id, r"(?:network|dvportgroup)-\d+")
        types = {"folder": (r"group-v\d+", "Folder"), "pool": (r"resgroup-\d+", "ResourcePool"),
                 "host": (r"host-\d+", "HostSystem"), "datastore": (r"datastore-\d+", "Datastore"),
                 "network": (r"(?:network|dvportgroup)-\d+",
                             "DistributedVirtualPortgroup" if network_id.startswith("dvportgroup-") else "Network")}
        for kind, (pattern, typename) in types.items():
            if self._id(objects[kind], pattern, typename) != params[kind + "_id"]:
                fail("placement_invalid", "解析对象与指定精确 ID 不匹配", 4)
        return objects

    def _dc(self, obj):
        visited = set()
        while getattr(obj, "_wsdlName", None) != "Datacenter":
            identity = getattr(obj, "_moId", None)
            if not identity or identity in visited or len(visited) >= 100:
                fail("placement_invalid", "数据中心归属不可确定", 4)
            visited.add(identity)
            obj = getattr(obj, "parent", None)
        return self._id(obj, r"datacenter-\d+", "Datacenter")

    def preflight(self, command, params):
        self._server()
        from ...application.registry import lookup
        if command != "vm create":
            fail("invalid_arguments", "创建 Provider 仅接受 vm create", 2)
        p = lookup(command).validate(params)
        if not valid_name(p["name"]):
            fail("name_invalid", "VM 名称须为 1–80 字符，不含路径、百分号、控制符或边缘空白", 2)
        if not re.fullmatch(r"vmx-\d+", p["hardware_version"]):
            fail("invalid_arguments", "必须指定精确 vmx-N 硬件版本", 2)
        objects = self._objects(p)
        host, pool, ds, folder, network = (objects[k] for k in ("host", "pool", "datastore", "folder", "network"))
        owner = getattr(pool, "owner", None)
        if (getattr(owner, "_wsdlName", None) not in ("ComputeResource", "ClusterComputeResource")
                or getattr(getattr(host, "parent", None), "_moId", None) != getattr(owner, "_moId", None)):
            fail("placement_invalid", "指定主机与资源池计算资源不匹配", 4)
        dc_id = self._dc(folder)
        if self._dc(owner) != dc_id:
            fail("placement_invalid", "VM 文件夹与计算资源不属于同一数据中心", 4)
        if not any(str(t).rsplit(".", 1)[-1].lower() == "virtualmachine" for t in self._list(folder, "childType")):
            fail("placement_invalid", "目标不是 VM 文件夹", 4)
        if getattr(host.runtime, "connectionState", None) != "connected" or getattr(host.runtime, "inMaintenanceMode", None) is not False:
            fail("placement_invalid", "目标主机必须已连接且不在维护模式", 4)
        if ds._moId not in [o._moId for o in self._list(host, "datastore")] or network._moId not in [o._moId for o in self._list(host, "network")]:
            fail("placement_invalid", "目标主机不可使用指定数据存储或网络", 4)
        summary = getattr(ds, "summary", None)
        free = getattr(summary, "freeSpace", None)
        if getattr(summary, "accessible", None) is not True or getattr(summary, "maintenanceMode", None) != "normal":
            fail("placement_invalid", "目标数据存储不可访问或处于维护模式", 4)
        if not isinstance(free, int) or isinstance(free, bool) or free < p["disk_gb"] * 1024**3:
            fail("capacity_insufficient", "数据存储空间不能容纳磁盘标称容量", 4)
        if re.search(r"[\[\]\x00-\x1f]", ds.name):
            fail("placement_invalid", "数据存储名称不能安全构造 SDK 路径", 4)
        before_ids, children = set(), []
        for child in self._list(folder, "childEntity"):
            identity, name = getattr(child, "_moId", None), getattr(child, "name", None)
            if not isinstance(identity, str) or not identity or not isinstance(name, str) or not name:
                fail("target_unavailable", "文件夹成员身份或名称缺失", 4)
            if name == p["name"]:
                fail("target_exists", "文件夹已有同名对象", 4)
            children.append({"object_id": identity, "name": name})
            before_ids.add(identity)
        for container in (pool, host):
            before_ids.update(self._id(vm, r"vm-\d+", "VirtualMachine") for vm in self._list(container, "vm"))
        self._capability(folder, "CreateVM_Task", "VirtualMachine.Inventory.Create")
        self._privilege(folder, "VirtualMachine.Config.AddNewDisk")
        self._privilege(pool, "Resource.AssignVMToPool")
        self._privilege(ds, "Datastore.AllocateSpace")
        self._privilege(network, "Network.Assign")
        evidence = hardware.capability(getattr(owner, "environmentBrowser", None), host, p)
        network_binding = {"id": network._moId, "name": network.name}
        if getattr(network, "_wsdlName", None) == "DistributedVirtualPortgroup":
            key = getattr(network, "key", None)
            uuid = getattr(getattr(getattr(network, "config", None), "distributedVirtualSwitch", None), "uuid", None)
            if not isinstance(key, str) or not key or not isinstance(uuid, str) or not uuid:
                fail("placement_invalid", "分布式端口组或交换机身份不可确定", 4)
            network_binding.update(portgroup_key=key, switch_uuid=uuid)
        return {"target": self.server_uuid + ":" + folder._moId + ":" + p["name"],
                "server_uuid": self.server_uuid, "object_id": folder._moId, "risk": "change",
                "before": {"existing_ids": sorted(before_ids), "children": sorted(children, key=lambda x: x["object_id"])},
                "placement": {**{k: {"id": o._moId, "name": o.name} for k, o in objects.items()}, "network": network_binding},
                "datacenter_id": dc_id, "compute_id": owner._moId,
                "spec": {k: p[k] for k in ("name", "guest_id", "hardware_version", "cpu", "memory_gb", "disk_gb")},
                "hardware": evidence, "impact": {"power_on": False, "ip_allocation": False,
                    "disk_bytes": p["disk_gb"] * 1024**3, "capacity_note": "标称磁盘容量；配置元数据与其他并发分配仍可能使服务端拒绝"}}

    def bind_steps(self, steps):
        if len(steps) != 1:
            fail("plan_dependency_unsupported", "创建暂不支持依赖或多步骤空间状态投影，请拆分计划", 4)
        return [{**step, "binding": self.preflight(step["command"], step["params"])} for step in steps]

    def submit(self, command, params, binding):
        try:
            if not self.matches(binding, self.preflight(command, params)):
                fail("plan_stale", "创建的身份、放置或能力前提变化，请重新预览", 4)
            objects = self._objects(params)
        except OperationError as exc:
            # Read-only recheck/resolution only: CreateVM_Task has not been
            # issued, so this is a retryable pre-write rejection (exit 4).
            raise SubmissionRejected(exc.code, str(exc), exc.exit_code) from exc
        # From here the remote create may have happened: failures stay unknown/6.
        task = objects["folder"].CreateVM_Task(config=hardware.spec(params, objects, binding["hardware"]),
                                               pool=objects["pool"], host=objects["host"])
        task_id = getattr(task, "_moId", None)
        if not isinstance(task_id, str) or not re.fullmatch(r"task-\d+", task_id):
            fail("receipt_missing", "已调用远端但精确任务回执缺失，禁止重发", 6)
        # CreateVM returns Task -> info.result VM. TaskInfo.entity is optional;
        # do not fabricate a Folder entity receipt from the method receiver.
        return {"server_uuid": self.server_uuid, "task_id": task_id, "folder_id": objects["folder"]._moId}

    def _task(self, receipt, binding):
        self._server()
        task_id = receipt.get("task_id") if isinstance(receipt, dict) else None
        if (not isinstance(task_id, str) or not re.fullmatch(r"task-\d+", task_id)
                or receipt.get("server_uuid") != self.server_uuid or binding.get("server_uuid") != self.server_uuid
                or receipt.get("folder_id") != binding.get("object_id")):
            fail("task_identity_mismatch", "任务回执的服务器、task-N 或创建文件夹不匹配", 4)
        task = self.resolver("task", task_id)
        info = getattr(task, "info", None)
        if (getattr(task, "_moId", None) != task_id or getattr(info, "key", None) != task_id
                or getattr(getattr(info, "task", None), "_moId", None) != task_id):
            fail("task_identity_mismatch", "远端任务 MoRef、key 或 info.task 不匹配", 4)
        entity = getattr(info, "entity", None)
        if entity is not None:
            identity, typename = getattr(entity, "_moId", None), getattr(entity, "_wsdlName", None)
            result = getattr(info, "result", None)
            folder_entity = typename == "Folder" and identity == binding["object_id"]
            vm_entity = (typename == "VirtualMachine" and getattr(info, "state", None) == "success"
                         and identity == getattr(result, "_moId", None))
            if not folder_entity and not vm_entity:
                fail("task_identity_mismatch", "任务实体不属于创建文件夹或成功结果 VM", 4)
        return task, info

    def observe(self, receipt, binding):
        from pyVmomi import vmodl
        _, info = self._task(receipt, binding)
        state = getattr(info, "state", None)
        if state not in ("queued", "running", "success", "error"):
            fail("task_state_unknown", "任务状态不可确定", 6)
        error = getattr(info, "error", None)
        observation = {"state": state, "task_key": info.key, "cancelled": isinstance(error, vmodl.fault.RequestCanceled),
                       "entity_id": getattr(getattr(info, "entity", None), "_moId", None),
                       "error_type": type(error).__name__ if error else None}
        if state == "success":
            result = getattr(info, "result", None)
            object_id = self._id(result, r"vm-\d+", "VirtualMachine")
            if object_id in binding["before"]["existing_ids"]:
                fail("task_identity_mismatch", "创建结果引用既存对象", 4)
            vm = self.resolver("vm", object_id)
            if self._id(vm, r"vm-\d+", "VirtualMachine") != object_id:
                fail("task_identity_mismatch", "结果 VM 的精确查询身份不匹配", 4)
            config = getattr(vm, "config", None)
            uuids = {"instance_uuid": getattr(config, "instanceUuid", None), "bios_uuid": getattr(config, "uuid", None)}
            if any(not isinstance(value, str) or not value for value in uuids.values()):
                fail("target_unavailable", "新 VM UUID 不可确定", 4)
            observation.update(object_id=object_id, **uuids)
        return observation

    def verify(self, command, params, binding, observation):
        from pyVmomi import vim
        try:
            self._server()
            if command != "vm create" or observation.get("state") != "success":
                return False
            object_id = observation.get("object_id")
            if object_id in binding["before"]["existing_ids"]:
                return False
            vm = self.resolver("vm", object_id)
            if self._id(vm, r"vm-\d+", "VirtualMachine") != object_id:
                return False
            config, runtime, requested = vm.config, vm.runtime, binding["spec"]
            place = binding["placement"]
            if (config.instanceUuid != observation.get("instance_uuid") or config.uuid != observation.get("bios_uuid")
                    or config.template is not False or vm.name != requested["name"]
                    or vm.parent._moId != place["folder"]["id"] or vm.resourcePool._moId != place["pool"]["id"]
                    or runtime.host._moId != place["host"]["id"] or runtime.powerState != "poweredOff"
                    or config.guestId != requested["guest_id"] or config.version != requested["hardware_version"]
                    or config.hardware.numCPU != requested["cpu"] or config.hardware.memoryMB != requested["memory_gb"] * 1024
                    or sorted(o._moId for o in vm.datastore) != [place["datastore"]["id"]]
                    or sorted(o._moId for o in vm.network) != [place["network"]["id"]]):
                return False
            disks = [d for d in config.hardware.device if isinstance(d, vim.vm.device.VirtualDisk)]
            nics = [d for d in config.hardware.device if isinstance(d, vim.vm.device.VirtualEthernetCard)]
            controllers = [d for d in config.hardware.device if isinstance(d, vim.vm.device.VirtualSCSIController)]
            if len(disks) != 1 or len(nics) != 1 or len(controllers) != 1:
                return False
            disk, nic, controller = disks[0], nics[0], controllers[0]
            if (type(controller).__name__ != binding["hardware"]["controller"] or type(nic).__name__ != binding["hardware"]["nic"]
                    or disk.capacityInKB != requested["disk_gb"] * 1024**2 or disk.controllerKey != controller.key
                    or disk.unitNumber != 0 or controller.busNumber != 0 or controller.sharedBus != "noSharing"
                    or not isinstance(disk.backing, vim.vm.device.VirtualDisk.FlatVer2BackingInfo)
                    or disk.backing.datastore._moId != place["datastore"]["id"] or disk.backing.diskMode != "persistent"
                    or disk.backing.thinProvisioned is not False or not disk.backing.fileName or disk.backing.parent is not None
                    or nic.connectable.startConnected is not True or nic.connectable.connected is not False):
                return False
            net = place["network"]
            if "portgroup_key" in net:
                return (isinstance(nic.backing, vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo)
                        and nic.backing.port.portgroupKey == net["portgroup_key"] and nic.backing.port.switchUuid == net["switch_uuid"])
            return isinstance(nic.backing, vim.vm.device.VirtualEthernetCard.NetworkBackingInfo) and nic.backing.network._moId == net["id"]
        except Exception:
            return False
