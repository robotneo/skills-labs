"""Conservative offline disk specifications using live target capability evidence."""
from copy import deepcopy
import re

from ...domain.models import OperationError, fail
from .hardware import bounds, select_new_disk_option
from .mor import existing


def is_integer(value):
    # Real vCenter returns xsd:long/xsd:byte/xsd:short fields (capacity, free
    # space, unit numbers) as pyVmomi int subclasses; bool is an int subclass too.
    return isinstance(value, int) and not isinstance(value, bool)


def layout(vm):
    devices = list(vm.config.hardware.device or [])
    if len({d.key for d in devices}) != len(devices):
        fail("capability_unsupported", "设备 key 不唯一", 4)
    return devices


def disk_identity(disk):
    from pyVmomi import vim
    b = disk.backing
    if (not isinstance(b, vim.vm.device.VirtualDisk.FlatVer2BackingInfo)
            or b.diskMode != "persistent" or b.parent is not None or b.keyId is not None
            or disk.nativeUnmanagedLinkedClone is True
            or b.sharing not in (None, "sharingNone") or not b.datastore or not b.fileName):
        fail("capability_unsupported", "仅支持未加密、无父链、非共享 persistent FlatVer2 磁盘", 4)
    return {"device_key": disk.key, "controller_key": disk.controllerKey, "unit_number": disk.unitNumber,
            "datastore_id": b.datastore._moId, "file_name": b.fileName, "uuid": b.uuid,
            "disk_mode": b.diskMode, "thin_provisioned": b.thinProvisioned, "eagerly_scrub": b.eagerlyScrub,
            "sharing": b.sharing, "backing_object_id": b.backingObjectId}


def datastore(provider, vm, object_id):
    if not isinstance(object_id, str) or not re.fullmatch(r"datastore-\d+", object_id):
        fail("target_invalid", "需要精确 datastore-N 对象 ID", 2)
    ds = provider.resolver("datastore", object_id)
    if ds._moId != object_id or getattr(ds, "_wsdlName", None) != "Datastore":
        fail("target_changed", "数据存储对象身份或类型错误", 4)
    existing(lambda: ds.summary, object_id, "datastore_not_found",
             "指定数据存储不存在或已被删除: " + object_id)
    host = vm.runtime.host
    if not host or object_id not in [d._moId for d in host.datastore]:
        fail("datastore_unavailable", "VM 所在主机不能访问指定数据存储", 4)
    if not ds.summary.accessible or ds.summary.maintenanceMode != "normal":
        fail("datastore_unavailable", "数据存储不可访问或处于维护状态", 4)
    return ds


def preflight(provider, vm, requests):
    from pyVmomi import vim
    from ...application.registry import lookup
    lookup("vm reconfigure").validate({"vm_id": vm._moId, "disks": requests})
    if vm.snapshot is not None or getattr(vm.config, "keyId", None) is not None:
        fail("precondition_failed", "磁盘变更拒绝含快照或加密 VM", 4)
    current = layout(vm)
    host = vm.runtime.host
    if not host:
        fail("capability_unsupported", "无法获取 VM 所在主机", 4)
    option = host.parent.environmentBrowser.QueryConfigOption(key=vm.config.version, host=host)
    if option is None or option.version != vm.config.version or option.hardwareOptions is None:
        fail("capability_unsupported", "目标没有返回 VM 硬件版本能力", 4)
    options = list(option.hardwareOptions.virtualDeviceOption or [])
    # Capability-based selection (shared with vm create): a target may expose
    # several equivalent disk options (8.0.3 returns 4). Expand only ever edits an
    # existing disk and never shrinks/removes, so we only need a representative
    # option whose FlatVer2 new-disk bounds are valid; zero qualified -> failure.
    disk_option, _, _ = select_new_disk_option(options)
    output, keys, slots, allocations = [], set(), set(), {}
    controllers = (vim.vm.device.VirtualBusLogicController, vim.vm.device.VirtualLsiLogicController,
                   vim.vm.device.VirtualLsiLogicSASController, vim.vm.device.ParaVirtualSCSIController)
    for request in requests:
        key, capacity = request["device_key"], request["capacity_gb"] * 1024**2
        if key in keys:
            fail("invalid_arguments", "磁盘请求 device_key 重复", 2)
        keys.add(key)
        evidence = {**request, "after_kb": capacity, "after_bytes": capacity * 1024,
                    "capacity_bounds_kb": bounds(disk_option.capacityInKB, capacity)}
        if request["operation"] == "expand":
            matches = [d for d in current if d.key == key and isinstance(d, vim.vm.device.VirtualDisk)]
            if len(matches) != 1:
                fail("target_invalid", "指定 key 不是唯一现有磁盘", 4)
            disk = matches[0]
            identity = disk_identity(disk)
            if not is_integer(disk.capacityInKB) or capacity <= disk.capacityInKB:
                fail("precondition_failed", "扩容目标必须大于原容量；不允许缩容或隐式删除", 4)
            if disk.capacityInBytes not in (None, disk.capacityInKB * 1024):
                fail("capability_unsupported", "磁盘字节/KB 容量不一致，禁止猜测原容量", 4)
            evidence.update(identity, before_kb=disk.capacityInKB, before_bytes=disk.capacityInKB * 1024)
        else:
            if any(d.key == key for d in current):
                fail("target_invalid", "新增磁盘 key 已被使用", 4)
            evidence.update(before_kb=0, before_bytes=0)
            backings = [b for b in disk_option.backingOption if isinstance(b, vim.vm.device.VirtualDiskOption.FlatVer2BackingOption)
                        and b.type == vim.vm.device.VirtualDisk.FlatVer2BackingInfo]
            if (len(backings) != 1 or "persistent" not in [d.key for d in backings[0].diskMode.choiceInfo]
                    or not (backings[0].thinProvisioned.supported is True or backings[0].thinProvisioned.defaultValue is False)):
                fail("capability_unsupported", "目标不支持 persistent 厚置备 FlatVer2", 4)
        ctl = [d for d in current if d.key == evidence["controller_key"] and type(d) in controllers]
        if len(ctl) != 1 or ctl[0].sharedBus != "noSharing":
            fail("capability_unsupported", "需要现有非共享 SCSI 控制器", 4)
        ctl = ctl[0]
        if not is_integer(ctl.scsiCtlrUnitNumber) or not 0 <= ctl.scsiCtlrUnitNumber <= 15:
            fail("capability_unsupported", "控制器保留槽位不可确定", 4)
        ctl_options = [o for o in options if o.type == type(ctl) and o.deprecated is not True]
        if (len(ctl_options) != 1 or vim.vm.device.VirtualDisk not in ctl_options[0].supportedDevice
                or "noSharing" not in ctl_options[0].sharing):
            fail("capability_unsupported", "控制器能力缺失", 4)
        slot = (ctl.key, evidence["unit_number"])
        if (slot in slots or not 0 <= slot[1] <= 15 or slot[1] == ctl.scsiCtlrUnitNumber
                or request["operation"] == "add" and any((d.controllerKey, d.unitNumber) == slot for d in current)):
            fail("precondition_failed", "磁盘槽位重复、已占用或保留", 4)
        slots.add(slot)
        count = sum(isinstance(d, vim.vm.device.VirtualDisk) and d.controllerKey == ctl.key for d in current)
        count += sum(e["operation"] == "add" and e["controller_key"] == ctl.key for e in output)
        count += request["operation"] == "add"
        evidence["controller"] = {"key": ctl.key, "type": type(ctl).__name__, "bus_number": ctl.busNumber,
                                  "reserved_unit": ctl.scsiCtlrUnitNumber,
                                  "disk_count_bounds": bounds(ctl_options[0].numSCSIDisks, count)}
        ds = datastore(provider, vm, evidence["datastore_id"])
        if request["operation"] == "expand":
            capability = ds.capability
            if not isinstance(capability, vim.Datastore.Capability):
                fail("capability_unsupported", "数据存储 Capability 对象缺失或类型错误", 4)
            expand = capability.vmdkExpandSupported
            # The API explicitly defines an absent optional flag as supported.
            # This does not apply to an absent/malformed capability object.
            if expand is not True and expand is not None:
                fail("capability_unsupported", "数据存储未明确支持 VMDK 扩容", 4)
            evidence["expand_support"] = "documented_undefined_means_supported" if expand is None else "explicit_datastore_capability"
        maximum = getattr(ds.info, "maxVirtualDiskCapacity", None)
        if not is_integer(maximum) or maximum < evidence["after_bytes"]:
            fail("capability_unsupported", "数据存储磁盘容量上限缺失或超限", 4)
        needed = evidence["after_bytes"] - evidence["before_bytes"]
        allocations[ds._moId] = allocations.get(ds._moId, 0) + needed
        if not is_integer(ds.summary.freeSpace) or ds.summary.freeSpace < allocations[ds._moId]:
            fail("precondition_failed", "数据存储可用空间不足", 4)
        provider.privileges(ds, ("Datastore.AllocateSpace",))
        evidence["datastore"] = {"id": ds._moId, "name": ds.name, "max_disk_bytes": maximum,
                                 "free_bytes": ds.summary.freeSpace, "host_id": host._moId}
        evidence["existing_keys"] = [d.key for d in current]
        output.append(evidence)
    return output


def changes(provider, vm, requests):
    from pyVmomi import vim
    result = []
    for request in requests:
        if request["operation"] == "expand":
            disk = deepcopy(next(d for d in layout(vm) if d.key == request["device_key"]))
            disk.capacityInKB = request["capacity_gb"] * 1024**2
            # All supported targets (6.5+) use the authoritative byte capacity.
            disk.capacityInBytes = request["capacity_gb"] * 1024**3
            result.append(vim.vm.device.VirtualDeviceSpec(operation="edit", device=disk))
        else:
            ds = provider.resolver("datastore", request["datastore_id"])
            disk = vim.vm.device.VirtualDisk(key=request["device_key"], controllerKey=request["controller_key"],
                unitNumber=request["unit_number"], capacityInKB=request["capacity_gb"] * 1024**2,
                capacityInBytes=request["capacity_gb"] * 1024**3,
                backing=vim.vm.device.VirtualDisk.FlatVer2BackingInfo(fileName="", datastore=ds,
                    diskMode="persistent", thinProvisioned=False))
            result.append(vim.vm.device.VirtualDeviceSpec(operation="add", fileOperation="create", device=disk))
    return result


def verify(vm, evidence):
    from pyVmomi import vim
    try:
        current = layout(vm)
        for e in evidence:
            controllers = [d for d in current if d.key == e["controller_key"]]
            if (len(controllers) != 1 or type(controllers[0]).__name__ != e["controller"]["type"]
                    or controllers[0].busNumber != e["controller"]["bus_number"]
                    or controllers[0].scsiCtlrUnitNumber != e["controller"]["reserved_unit"]
                    or controllers[0].sharedBus != "noSharing"):
                return False
            candidates = [d for d in current if isinstance(d, vim.vm.device.VirtualDisk)
                          and d.controllerKey == e["controller_key"] and d.unitNumber == e["unit_number"]]
            if len(candidates) != 1:
                return False
            d = candidates[0]
            if d.capacityInKB != e["after_kb"] or d.capacityInBytes not in (None, e["after_bytes"]):
                return False
            identity = disk_identity(d)
            if e["operation"] == "expand":
                if any(identity[k] != e[k] for k in identity):
                    return False
            elif (d.key in e["existing_keys"] or identity["datastore_id"] != e["datastore_id"]
                  or identity["thin_provisioned"] is not False):
                return False
        return True
    except (AttributeError, StopIteration, OperationError):
        return False
