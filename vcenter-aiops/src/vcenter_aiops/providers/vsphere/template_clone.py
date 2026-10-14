"""Full template clone provider (equivalent flow to vcenter-ops clone_vm).

One atomic CloneVM_Task carries placement, optional NIC remap, CPU/memory and
disk resize, and optional fixed-IP Linux guest customization (power-on). When
no fixed IP is supplied the clone stays powered off. SDK objects never leave
this boundary; the shared preview/plan/confirm engine supplies deduplication,
identity binding and reconciliation.
"""
import ipaddress
import re

from ...domain.models import OperationError, SubmissionRejected, fail
from .clusters import Clusters
from .hosts import Hosts

# Fixed-IP clones boot and run Linux guest customization; off clones do not.
TOOLS_HINT = "克隆任务成功仅表示 VM 已创建；静态 IP 克隆已开机并下发定制，VMware Tools/IP 就绪请用 vm wait-tools 或 task wait 核对，不假定已就绪"
NAME_RE = re.compile(r"[/\\%\x00-\x1f]")
IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


class TemplateClone:
    def __init__(self, si, resolver=None):
        self.si = si
        self.content = si.RetrieveContent()
        self.server_uuid = getattr(getattr(self.content, "about", None), "instanceUuid", None)
        self.resolver = resolver or self.object

    # Reuse the proven identity/permission primitives instead of forking them.
    _server = Hosts._server
    matches = staticmethod(Hosts.matches)
    _id = staticmethod(Clusters._id)
    _list = staticmethod(Clusters._list)

    def object(self, kind, object_id):
        from pyVmomi import vim
        classes = {"folder": vim.Folder, "pool": vim.ResourcePool, "host": vim.HostSystem,
                   "datastore": vim.Datastore, "network": vim.Network, "vm": vim.VirtualMachine,
                   "task": vim.Task}
        cls = vim.dvs.DistributedVirtualPortgroup if kind == "network" and object_id.startswith("dvportgroup-") else classes[kind]
        return cls(object_id, self.si._stub)

    # -- helpers -----------------------------------------------------------

    def _vm(self, vm_id):
        if not re.fullmatch(r"vm-\d+", vm_id):
            fail("target_invalid", "必须提供精确 vm-N 模板对象 ID，不支持名称或通配符", 2)
        vm = self.resolver("vm", vm_id)
        if vm._moId != vm_id or getattr(vm, "config", None) is None or not vm.config.instanceUuid:
            fail("target_unavailable", "模板对象身份不可读或不匹配", 4)
        if getattr(vm, "runtime", None) is not None and vm.runtime.connectionState != "connected":
            fail("target_unavailable", "模板不处于已连接状态", 4)
        if vm.config.template is not True:
            fail("precondition_failed", "clone-template 要求源对象为模板；普通 VM 克隆请用 vm clone", 4)
        return vm

    def _resolve_id(self, kind, object_id, pattern, typename):
        obj = self.resolver(kind, object_id)
        if self._id(obj, pattern, typename) != object_id:
            fail("placement_invalid", typename + " 精确 ID 不匹配", 4)
        return obj

    def _ip(self, value, field):
        if not isinstance(value, str) or not IPV4.fullmatch(value):
            fail("invalid_arguments", field + " 必须是点分十进制 IPv4 地址", 2)
        try:
            ipaddress.IPv4Address(value)
        except ValueError:
            fail("invalid_arguments", field + " 不是合法 IPv4 地址", 2)
        return value

    def _source_nic(self, vm):
        from pyVmomi import vim
        nics = [d for d in vm.config.hardware.device if isinstance(d, vim.vm.device.VirtualEthernetCard)]
        if not nics:
            fail("capability_unsupported", "模板没有可改网的以太网卡；不改网时请省略 network_id", 4)
        return nics[0]

    def _network_binding(self, network):
        from pyVmomi import vim
        binding = {"id": network._moId, "name": network.name}
        if isinstance(network, vim.dvs.DistributedVirtualPortgroup):
            key = getattr(network, "key", None)
            uuid = getattr(getattr(getattr(network, "config", None), "distributedVirtualSwitch", None), "uuid", None)
            if not isinstance(key, str) or not key or not isinstance(uuid, str) or not uuid:
                fail("placement_invalid", "分布式端口组或交换机身份不可确定", 4)
            binding.update(kind="dvportgroup", portgroup_key=key, switch_uuid=uuid)
        else:
            binding["kind"] = "standard"
        return binding

    def _disk(self, vm):
        from pyVmomi import vim
        disks = [d for d in vm.config.hardware.device if isinstance(d, vim.vm.device.VirtualDisk)]
        if not disks:
            fail("capability_unsupported", "模板没有可扩容的虚拟磁盘", 4)
        return sorted(disks, key=lambda d: int(d.key))[0]

    # -- engine contract ---------------------------------------------------

    def preflight(self, command, params):
        from ...application.registry import lookup
        from pyVmomi import vim
        self._server()
        if command != "deploy clone-template":
            fail("invalid_arguments", "模板克隆 Provider 仅接受 deploy clone-template", 2)
        p = lookup(command).validate(params)
        vm = self._vm(p["vm_id"])

        # Name rules (same vocabulary as the rest of the product).
        if NAME_RE.search(p["name"]) or len(p["name"]) > 80 or p["name"].strip() != p["name"]:
            fail("name_invalid", "VM 名称须为 1–80 字符，不含路径、百分号、控制符或边缘空白", 2)

        # Placement: pool/ds/folder mandatory; host optional -> cluster DRS.
        folder = self._resolve_id("folder", p["folder_id"], r"group-v\d+", "Folder")
        pool = self._resolve_id("pool", p["pool_id"], r"resgroup-\d+", "ResourcePool")
        ds = self._resolve_id("datastore", p["datastore_id"], r"datastore-\d+", "Datastore")
        host = None
        if p.get("host_id"):
            host = self._resolve_id("host", p["host_id"], r"host-\d+", "HostSystem")

        owner = getattr(pool, "owner", None)
        if getattr(owner, "_wsdlName", None) not in ("ComputeResource", "ClusterComputeResource"):
            fail("placement_invalid", "资源池的计算资源身份不可确定", 4)
        if host is not None and getattr(host, "parent", None) is not None and host.parent._moId != owner._moId:
            fail("placement_invalid", "指定主机与资源池不属于同一计算资源", 4)
        if host is not None and (host.runtime.connectionState != "connected" or host.runtime.inMaintenanceMode):
            fail("placement_invalid", "目标主机必须已连接且不在维护模式", 4)

        # Folder belongs to the same datacenter as the compute resource.
        dc_id = self._datacenter(folder)
        if self._datacenter(owner) != dc_id:
            fail("placement_invalid", "VM 文件夹与计算资源不属于同一数据中心", 4)
        if not any(str(t).rsplit(".", 1)[-1].lower() == "virtualmachine" for t in self._list(folder, "childType")):
            fail("placement_invalid", "目标不是 VM 文件夹", 4)
        children = self._list(folder, "childEntity")
        if any(getattr(c, "name", None) == p["name"] for c in children):
            fail("target_exists", "目标文件夹已有同名对象", 4)

        # Datastore accessibility + capacity for the template's disks.
        summary = getattr(ds, "summary", None)
        if getattr(summary, "accessible", None) is not True or getattr(summary, "maintenanceMode", None) != "normal":
            fail("placement_invalid", "目标数据存储不可访问或处于维护模式", 4)
        if host is not None and ds._moId not in [d._moId for d in self._list(host, "datastore")]:
            fail("placement_invalid", "目标主机不能使用指定数据存储", 4)
        disks = [d for d in vm.config.hardware.device if isinstance(d, vim.vm.device.VirtualDisk)]
        requested_disk_gb = p.get("disk_gb")
        need_bytes = 0
        disk_evidence = None
        if disks:
            source_disk = sorted(disks, key=lambda d: int(d.key))[0]
            target_kb = requested_disk_gb * 1024**2 if requested_disk_gb else int(source_disk.capacityInKB)
            if requested_disk_gb is not None and target_kb <= int(source_disk.capacityInKB):
                fail("invalid_arguments", "disk_gb 只能大于模板首盘当前容量（仅支持扩容）", 2)
            need_bytes = target_kb * 1024
            disk_evidence = {"key": int(source_disk.key), "controller_key": int(source_disk.controllerKey),
                             "unit_number": int(source_disk.unitNumber), "source_kb": int(source_disk.capacityInKB),
                             "target_kb": target_kb}
        if requested_disk_gb is not None and disk_evidence is None:
            fail("capability_unsupported", "模板没有可扩容的虚拟磁盘", 4)
        free = getattr(summary, "freeSpace", None)
        if not isinstance(free, int) or isinstance(free, bool) or free < need_bytes:
            fail("capacity_insufficient", "数据存储可用空间不足以容纳克隆磁盘标称容量", 4)

        # Network remap (optional). When absent the clone keeps template NICs.
        nic_evidence = None
        if p.get("network_id"):
            network = self.resolver("network", p["network_id"])
            pattern = r"(?:network|dvportgroup)-\d+"
            if self._id(network, pattern, "Network" if not p["network_id"].startswith("dvportgroup-") else "DistributedVirtualPortgroup") != p["network_id"]:
                fail("placement_invalid", "网络精确 ID 不匹配", 4)
            if host is not None and network._moId not in [n._moId for n in self._list(host, "network")]:
                fail("placement_invalid", "目标主机不能使用指定网络", 4)
            source_nic = self._source_nic(vm)
            nic_evidence = {"key": int(source_nic.key), "network": self._network_binding(network)}

        # Hardware sanity (optional); bounds ultimately enforced by the server.
        if p.get("cpu") is not None and p["cpu"] < 1:
            fail("invalid_arguments", "CPU 核数须为正整数", 2)
        if p.get("memory_gb") is not None and p["memory_gb"] < 1:
            fail("invalid_arguments", "内存 GiB 须为正整数", 2)

        # Fixed IP implies power-on + Linux customization; mask/gateway validated.
        customize = False
        ip_evidence = None
        if p.get("ip_address"):
            customize = True
            self._ip(p["ip_address"], "ip_address")
            mask = p.get("subnet_mask", "255.255.255.0")
            if not isinstance(mask, str) or not IPV4.fullmatch(mask):
                fail("invalid_arguments", "subnet_mask 必须是点分十进制子网掩码", 2)
            try:
                ipaddress.IPv4Address(mask)
            except ValueError:
                fail("invalid_arguments", "subnet_mask 不是合法 IPv4 地址", 2)
            if p.get("gateway"):
                self._ip(p["gateway"], "gateway")
            ip_evidence = {"ip": p["ip_address"], "mask": mask,
                           "gateway": p.get("gateway"), "guest_domain": p.get("guest_domain", "local")}

        # Permissions checked against the entity each privilege actually scopes.
        vm_privs = ["VirtualMachine.Provisioning.DeployTemplate",
                    "VirtualMachine.Inventory.CreateFromExisting"]
        if customize:
            vm_privs += ["VirtualMachine.Interact.PowerOn", "VirtualMachine.Provisioning.Customize"]
        self.privileges(vm, tuple(vm_privs))
        self.privileges(pool, ("Resource.AssignVMToPool",))
        self.privileges(ds, ("Datastore.AllocateSpace",))
        if nic_evidence:
            self.privileges(self.resolver("network", p["network_id"]), ("Network.Assign",))

        before_ids = {self._id(c, r"vm-\d+", "VirtualMachine") for c in children}
        # ResourcePool has no .vm inventory; enumerate the compute resource (DRS)
        # or the explicitly chosen host so a result cannot masquerade as "new".
        vm_scope = host if host is not None else owner
        try:
            before_ids.update(self._id(x, r"vm-\d+", "VirtualMachine") for x in self._list(vm_scope, "vm"))
        except OperationError:
            pass

        placement = {"folder": {"id": folder._moId, "name": folder.name},
                     "pool": {"id": pool._moId, "name": pool.name},
                     "datastore": {"id": ds._moId, "name": ds.name},
                     "compute_id": owner._moId, "host_id": host._moId if host else None}
        if nic_evidence:
            placement["network"] = nic_evidence["network"]
        binding = {
            "target": self.server_uuid + ":" + folder._moId + ":" + p["name"],
            "server_uuid": self.server_uuid, "object_id": vm._moId,
            "instance_uuid": vm.config.instanceUuid,
            "before": {"existing_ids": sorted(before_ids), "template_id": vm._moId},
            "risk": "change", "placement": placement,
            "requested": {"name": p["name"], "cpu": p.get("cpu"), "memory_gb": p.get("memory_gb"),
                          "power_on": customize, "customize": customize},
        }
        if disk_evidence:
            binding["disk"] = disk_evidence
        if nic_evidence:
            binding["nic"] = nic_evidence
        if ip_evidence:
            binding["customization"] = ip_evidence
            # The confirmed clone task must not block on long guest boot; Tools/IP
            # readiness is reconciled afterwards via the existing vm wait-tools.
            binding["warnings"] = [TOOLS_HINT]
        return binding

    def _datacenter(self, obj):
        visited = set()
        while getattr(obj, "_wsdlName", None) != "Datacenter":
            identity = getattr(obj, "_moId", None)
            if not identity or identity in visited or len(visited) >= 100:
                fail("placement_invalid", "数据中心归属不可确定", 4)
            visited.add(identity)
            obj = getattr(obj, "parent", None)
        return self._id(obj, r"datacenter-\d+", "Datacenter")

    def privileges(self, entity, required):
        session = self.content.sessionManager.currentSession
        if not session:
            fail("session_missing", "服务端会话不可用", 3)
        granted = self.content.authorizationManager.HasPrivilegeOnEntity(
            entity=entity, sessionId=session.key, privId=list(required))
        if len(granted) != len(required) or not all(granted):
            fail("permission_denied", "账户缺少此操作所需权限", 4)

    def bind_steps(self, steps):
        if len(steps) != 1:
            fail("plan_dependency_unsupported", "模板克隆不支持多步骤空间状态投影，请独立计划", 4)
        step = steps[0]
        return [{**step, "binding": self.preflight(step["command"], step["params"])}]

    # -- execution ---------------------------------------------------------

    def submit(self, command, params, binding):
        try:
            if not self.matches(binding, self.preflight(command, params)):
                fail("plan_stale", "提交前模板、放置或前提发生变化，请重新预览", 4)
            template = self._vm(params["vm_id"])
        except OperationError as exc:
            # Read/validation scope only: a rejection here happens before the
            # single remote write call below, so it must never read as uncertainty.
            raise SubmissionRejected(exc.code, str(exc), exc.exit_code) from exc
        task = template.CloneVM_Task(
            folder=self.resolver("folder", params["folder_id"]),
            name=params["name"], spec=self._clone_spec(template, params))
        task_id = getattr(task, "_moId", None)
        if not isinstance(task_id, str) or not re.fullmatch(r"task-\d+", task_id):
            fail("receipt_missing", "已调用远端但精确任务回执缺失，禁止重发", 6)
        return {"task_id": self.server_uuid + ":" + task_id}

    def _clone_spec(self, template, p):
        from pyVmomi import vim
        pool = self.resolver("pool", p["pool_id"])
        ds = self.resolver("datastore", p["datastore_id"])
        host = self.resolver("host", p["host_id"]) if p.get("host_id") else None

        location = vim.vm.RelocateSpec(datastore=ds, pool=(host.parent.resourcePool if host is not None else pool))
        if host is not None:
            location.host = host

        config = vim.vm.ConfigSpec()
        device_changes = []
        if p.get("cpu"):
            config.numCPUs = p["cpu"]
        if p.get("memory_gb"):
            config.memoryMB = p["memory_gb"] * 1024
        if p.get("network_id"):
            import copy
            # Clone the template NIC before editing its backing so the managed
            # template object is never mutated while building the spec.
            nic = copy.copy(self._source_nic(template))
            nic_spec = vim.vm.device.VirtualDeviceSpec(
                operation=vim.vm.device.VirtualDeviceSpec.Operation.edit, device=nic)
            if p["network_id"].startswith("dvportgroup-"):
                network = self.resolver("network", p["network_id"])
                port = vim.dvs.PortConnection(
                    portgroupKey=network.key,
                    switchUuid=network.config.distributedVirtualSwitch.uuid)
                nic.backing = vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(port=port)
            else:
                network = self.resolver("network", p["network_id"])
                backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo()
                backing.network = network
                backing.deviceName = network.name
                nic.backing = backing
            device_changes.append(nic_spec)
        if p.get("disk_gb"):
            import copy
            disk = copy.copy(self._disk(template))
            disk.capacityInKB = p["disk_gb"] * 1024**2
            device_changes.append(vim.vm.device.VirtualDeviceSpec(
                operation=vim.vm.device.VirtualDeviceSpec.Operation.edit, device=disk))
        if device_changes:
            config.deviceChange = device_changes

        customization = None
        power_on = False
        if p.get("ip_address"):
            power_on = True
            ip_settings = vim.vm.customization.IPSettings()
            fixed = vim.vm.customization.FixedIp(ipAddress=p["ip_address"])
            ip_settings.ip = fixed
            ip_settings.subnetMask = p.get("subnet_mask", "255.255.255.0")
            if p.get("gateway"):
                ip_settings.gateway = [p["gateway"]]
            mapping = vim.vm.customization.AdapterMapping(adapter=ip_settings)
            identity = vim.vm.customization.LinuxPrep(
                hostName=vim.vm.customization.FixedName(name=p["name"]),
                domain=p.get("guest_domain", "local"))
            customization = vim.vm.customization.Specification(
                nicSettingMap=[mapping], identity=identity,
                globalIPSettings=vim.vm.customization.GlobalIPSettings())

        return vim.vm.CloneSpec(location=location, config=config, customization=customization,
                                powerOn=power_on, template=False)

    def observe(self, receipt, binding):
        from pyVmomi import vmodl
        if binding["server_uuid"] != self.server_uuid:
            fail("server_mismatch", "操作属于其他 vCenter", 4)
        prefix, task_id = receipt["task_id"].split(":", 1)
        if prefix != self.server_uuid or not re.fullmatch(r"task-\d+", task_id):
            fail("task_identity_mismatch", "任务身份不匹配", 4)
        info = self.resolver("task", task_id).info
        error = getattr(info, "error", None)
        result = getattr(info, "result", None)
        return {"state": str(info.state), "cancelled": isinstance(error, vmodl.fault.RequestCanceled),
                "result_id": getattr(result, "_moId", None), "progress": getattr(info, "progress", None),
                "error_type": type(error).__name__ if error else None}

    def verify(self, command, params, binding, observation):
        from pyVmomi import vim
        result_id = observation.get("result_id")
        if not result_id or result_id in binding["before"]["existing_ids"] or result_id == binding["object_id"]:
            return False
        try:
            created = self.resolver("vm", result_id)
            if self._id(created, r"vm-\d+", "VirtualMachine") != result_id:
                return False
            place = binding["placement"]
            expect_on = binding["requested"]["power_on"]
            checks = [
                created.config.instanceUuid != binding["instance_uuid"],
                created.config.template is False,
                created.name == params["name"],
                created.parent._moId == place["folder"]["id"],
                created.resourcePool._moId == place["pool"]["id"],
                created.runtime.powerState == ("poweredOn" if expect_on else "poweredOff"),
                params["datastore_id"] in [d._moId for d in created.datastore],
            ]
            if place.get("host_id"):
                checks.append(created.runtime.host._moId == place["host_id"])
            if not all(checks):
                return False
            if params.get("cpu") and created.config.hardware.numCPU != params["cpu"]:
                return False
            if params.get("memory_gb") and created.config.hardware.memoryMB != params["memory_gb"] * 1024:
                return False
            if params.get("disk_gb"):
                disk = sorted([d for d in created.config.hardware.device
                               if isinstance(d, vim.vm.device.VirtualDisk)], key=lambda d: int(d.key))
                if not disk or int(disk[0].capacityInKB) != params["disk_gb"] * 1024**2:
                    return False
            if params.get("network_id"):
                nics = [d for d in created.config.hardware.device
                        if isinstance(d, vim.vm.device.VirtualEthernetCard)]
                net = place["network"]
                if not nics:
                    return False
                backing = nics[0].backing
                if net["kind"] == "dvportgroup":
                    if not isinstance(backing, vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo):
                        return False
                    port = backing.port
                    if port.portgroupKey != net["portgroup_key"] or port.switchUuid != net["switch_uuid"]:
                        return False
                else:
                    if not isinstance(backing, vim.vm.device.VirtualEthernetCard.NetworkBackingInfo):
                        return False
                    if backing.network._moId != net["id"]:
                        return False
            return True
        except Exception:
            return False

    def cancel(self, receipt, binding):
        if binding.get("server_uuid") != self.server_uuid:
            fail("server_mismatch", "原任务属于其他 vCenter", 4)
        prefix, task_id = receipt["task_id"].split(":", 1)
        if prefix != self.server_uuid or not re.fullmatch(r"task-\d+", task_id):
            fail("task_identity_mismatch", "任务身份不匹配", 4)
        info = self.resolver("task", task_id).info
        if getattr(info, "cancelable", None) is not True or str(info.state) not in ("queued", "running"):
            fail("task_not_cancelable", "原克隆任务当前不可取消", 4)
        self.resolver("task", task_id).CancelTask()
