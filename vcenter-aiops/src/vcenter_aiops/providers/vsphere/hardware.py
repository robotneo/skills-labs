"""Build empty VM hardware from the requested host's QueryConfigOption."""
from ...domain.models import fail


def bounds(option, value):
    low, high = getattr(option, "min", None), getattr(option, "max", None)
    return range_bounds(low, high, value)


def range_bounds(low, high, value):
    if (not isinstance(low, int) or isinstance(low, bool) or not isinstance(high, int)
            or isinstance(high, bool) or low < 0 or high < low or not low <= value <= high):
        fail("capability_unsupported", "目标能力范围缺失或请求超出范围", 4)
    return {"min": low, "max": high}


def select_new_disk_option(device_options):
    """Pick a VirtualDiskOption that can create an ordinary FlatVer2 persistent disk.

    Real vCenter (8.0.3) returns several *equivalent* non-deprecated disk options
    (one per attachable bus); offline stubs historically returned exactly one.
    Selecting by capability instead of asserting a cardinality of one keeps the
    conservative FlatVer2 + persistent + thick/thin guarantees without failing on
    equivalent duplicates. Returns (option, candidate_count, qualified_count).
    """
    from pyVmomi import vim
    disk_options = [o for o in device_options if isinstance(o, vim.vm.device.VirtualDiskOption)
                    and o.type == vim.vm.device.VirtualDisk and getattr(o, "deprecated", None) is not True]

    def qualified(option):
        backings = [b for b in (getattr(option, "backingOption", None) or [])
                    if isinstance(b, vim.vm.device.VirtualDiskOption.FlatVer2BackingOption)
                    and b.type == vim.vm.device.VirtualDisk.FlatVer2BackingInfo]
        if len(backings) != 1:
            return None
        backing = backings[0]
        modes = [d.key for d in (getattr(backing.diskMode, "choiceInfo", None) or [])]
        thin = getattr(backing, "thinProvisioned", None)
        if "persistent" not in modes or not (getattr(thin, "supported", None) is True
                                             or getattr(thin, "defaultValue", None) is False):
            return None
        return backing

    qualified_options = [o for o in disk_options if qualified(o) is not None]
    if not qualified_options:
        # 0 usable FlatVer2 backing means the target genuinely cannot create a
        # normal disk; equivalent duplicates (4 on 8.0.3) must not reach here.
        fail("capability_unsupported", "目标不提供明确的 FlatVer2 新磁盘 backing", 4)
    # Equivalent options: pick deterministically (first in service order), never
    # "take any first disk" -- every candidate above proved FlatVer2+persistent.
    return qualified_options[0], len(disk_options), len(qualified_options)


def capability(browser, host, params):
    from pyVmomi import vim
    query = getattr(browser, "QueryConfigOption", None)
    if not callable(query):
        fail("capability_unsupported", "目标无可用硬件能力查询", 4)
    option = query(key=params["hardware_version"], host=host)
    hardware = getattr(option, "hardwareOptions", None)
    if (getattr(option, "version", None) != params["hardware_version"]
            or getattr(hardware, "hwVersion", None) != int(params["hardware_version"].split("-")[1])):
        fail("capability_unsupported", "目标没有返回指定硬件版本", 4)
    cpus = list(getattr(hardware, "numCPU", []) or [])
    if not cpus or any(not isinstance(n, int) or isinstance(n, bool) or n < 1 for n in cpus) or params["cpu"] not in cpus:
        fail("capability_unsupported", "CPU 数量不在目标硬件允许整数列表中", 4)
    memory = params["memory_gb"] * 1024
    memory_bounds = bounds(getattr(hardware, "memoryMB", None), memory)
    guests = [g for g in (getattr(option, "guestOSDescriptor", []) or []) if g.id == params["guest_id"]]
    if len(guests) != 1:
        fail("capability_unsupported", "指定 Guest ID 不可用或不唯一", 4)
    guest = guests[0]
    max_cpu = getattr(guest, "supportedMaxCPUs", None)
    if not isinstance(max_cpu, int) or isinstance(max_cpu, bool) or max_cpu < params["cpu"]:
        fail("capability_unsupported", "CPU 超出 Guest 能力或上限不可确定", 4)
    guest_bounds = range_bounds(getattr(guest, "supportedMinMemMB", None), getattr(guest, "supportedMaxMemMB", None), memory)
    if getattr(guest, "supportedForCreate", None) is False:
        fail("capability_unsupported", "目标 Guest 不支持创建", 4)
    controller = getattr(guest, "recommendedDiskController", None) or getattr(guest, "recommendedSCSIController", None)
    nic = getattr(guest, "recommendedEthernetCard", None)
    controllers = (vim.vm.device.VirtualBusLogicController, vim.vm.device.VirtualLsiLogicController,
                   vim.vm.device.VirtualLsiLogicSASController, vim.vm.device.ParaVirtualSCSIController)
    nics = (vim.vm.device.VirtualE1000, vim.vm.device.VirtualE1000e, vim.vm.device.VirtualVmxnet,
            vim.vm.device.VirtualVmxnet2, vim.vm.device.VirtualVmxnet3, vim.vm.device.VirtualPCNet32)
    device_options = list(getattr(hardware, "virtualDeviceOption", []) or [])
    available = {getattr(o, "type", None) for o in device_options if getattr(o, "deprecated", None) is not True}
    if (controller not in controllers or controller not in (getattr(guest, "supportedDiskControllerList", []) or [])
            or controller not in available or nic not in nics
            or nic not in (getattr(guest, "supportedEthernetCard", []) or []) or nic not in available):
        fail("capability_unsupported", "推荐控制器或网卡不在目标与 Guest 支持列表中", 4)
    # Capability-based selection: a target may expose several equivalent disk
    # options (8.0.3 returns 4). Choose one that proves FlatVer2 + persistent;
    # only a target with zero usable FlatVer2 backing is a real hard failure.
    disk_option, disk_candidates, disk_qualified = select_new_disk_option(device_options)
    controller_options = [o for o in device_options if o.type == controller]
    if len(controller_options) != 1:
        fail("capability_unsupported", "控制器能力不可确定", 4)
    ctl = controller_options[0]
    if (vim.vm.device.VirtualDisk not in (getattr(ctl, "supportedDevice", []) or [])
            or "noSharing" not in (getattr(ctl, "sharing", []) or [])):
        fail("capability_unsupported", "控制器不支持普通磁盘或非共享模式", 4)
    controller_disk_bounds = bounds(getattr(ctl, "numSCSIDisks", None), 1)
    disk_bounds = bounds(disk_option.capacityInKB, params["disk_gb"] * 1024**2)
    return {"cpu_values": cpus, "memory_mb": memory_bounds, "guest_max_cpu": max_cpu,
            "guest_memory_mb": guest_bounds, "disk_kb": disk_bounds,
            "controller_disks": controller_disk_bounds, "disk_mode": "persistent", "thin_provisioned": False,
            "disk_option_candidates": disk_candidates, "disk_option_qualified": disk_qualified,
            "controller": controller.__name__, "nic": nic.__name__}


def spec(params, objects, evidence):
    from pyVmomi import vim
    controller_type = getattr(vim.vm.device, evidence["controller"].rsplit(".", 1)[-1])
    nic_type = getattr(vim.vm.device, evidence["nic"].rsplit(".", 1)[-1])
    controller = controller_type(key=-100, busNumber=0, sharedBus="noSharing")
    ds, network = objects["datastore"], objects["network"]
    backing = vim.vm.device.VirtualDisk.FlatVer2BackingInfo(
        fileName="", datastore=ds, diskMode="persistent", thinProvisioned=False)
    disk = vim.vm.device.VirtualDisk(key=-101, controllerKey=-100, unitNumber=0,
        capacityInKB=params["disk_gb"] * 1024**2, capacityInBytes=params["disk_gb"] * 1024**3, backing=backing)
    if getattr(network, "_wsdlName", None) == "DistributedVirtualPortgroup":
        port = vim.dvs.PortConnection(portgroupKey=network.key, switchUuid=network.config.distributedVirtualSwitch.uuid)
        nic_backing = vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo(port=port)
    else:
        nic_backing = vim.vm.device.VirtualEthernetCard.NetworkBackingInfo(deviceName=network.name, network=network)
    nic = nic_type(key=-102, backing=nic_backing, addressType="generated",
        connectable=vim.vm.device.VirtualDevice.ConnectInfo(startConnected=True, connected=False, allowGuestControl=True))
    changes = [vim.vm.device.VirtualDeviceSpec(operation="add", device=controller),
               vim.vm.device.VirtualDeviceSpec(operation="add", fileOperation="create", device=disk),
               vim.vm.device.VirtualDeviceSpec(operation="add", device=nic)]
    return vim.vm.ConfigSpec(name=params["name"], guestId=params["guest_id"], version=params["hardware_version"],
        numCPUs=params["cpu"], memoryMB=params["memory_gb"] * 1024,
        files=vim.vm.FileInfo(vmPathName="[" + ds.name + "]"), deviceChange=changes)
