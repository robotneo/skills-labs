"""Snapshot-only linked clones; SDK objects stay within the Provider boundary."""
import re

from ...domain.models import OperationError, fail
from .placement import preflight as placement, resolve, relocation


WARNING = "链接克隆长期依赖父快照/磁盘；无法排除外部依赖时禁止删除、快照清理/恢复和存储迁移。许可证未能独立证明，最终由服务端校验；不回退完整克隆"
STRICT_COMMANDS = frozenset(("vm delete", "vm snapshot-delete", "vm snapshot-revert"))


def guarded(command, params):
    return command in STRICT_COMMANDS or (command == "vm migrate" and "datastore_id" in params)


def guard(provider, vm, command, params):
    if not guarded(command, params):
        return
    records = getattr(provider, "parent_dependencies", None)
    if records and records(provider.server_uuid, vm.config.instanceUuid):
        fail("dependency_present", "父对象存在已提交或结果未知的链接克隆依赖；禁止破坏父磁盘链", 4)
    # Neither an empty Store nor any inventory/layout scan proves that no
    # consumer exists outside our visibility. There is deliberately no bypass.
    fail("dependency_unproven", "严格保护：无法排除外部链接磁盘依赖，拒绝删除、快照清理/恢复或存储迁移；本地无记录不构成安全证明", 4)


def chain(backing):
    from pyVmomi import vim
    result, seen = [], set()
    while backing is not None:
        if (type(backing) is not vim.vm.device.VirtualDisk.FlatVer2BackingInfo
                or len(result) >= 64 or id(backing) in seen
                or backing.diskMode != "persistent" or backing.keyId is not None
                or backing.sharing not in (None, "sharingNone")
                or not backing.datastore or not backing.uuid or not backing.contentId
                or not re.fullmatch(r"datastore-\d+", backing.datastore._moId)
                or not re.fullmatch(r"\[[^\]\r\n]+\] [^\r\n]+\.vmdk", backing.fileName or "")):
            fail("capability_unsupported", "仅支持身份完整的非加密持久 FlatVer2 磁盘链；不接受 RDM、独立盘、共享盘或未知 backing", 4)
        seen.add(id(backing))
        result.append({"datastore_id": backing.datastore._moId, "file": backing.fileName,
                       "uuid": backing.uuid, "content_id": backing.contentId})
        backing = backing.parent
    return result


def disks(config):
    from pyVmomi import vim
    hardware = getattr(config, "hardware", None)
    devices = getattr(hardware, "device", None)
    if (config.keyId is not None or devices is None
            or any(isinstance(d, vim.vm.device.VirtualNVDIMM) for d in devices)):
        fail("capability_unsupported", "无法证明 VM/快照磁盘配置完整且未加密", 4)
    result = []
    for disk in devices:
        if not isinstance(disk, vim.vm.device.VirtualDisk):
            continue
        value = chain(disk.backing)
        if not value or disk.capacityInKB <= 0:
            fail("capability_unsupported", "磁盘容量或 backing 缺失", 4)
        result.append({"key": int(disk.key), "controller_key": disk.controllerKey,
                       "unit_number": disk.unitNumber, "capacity_kb": int(disk.capacityInKB), "chain": value})
    if not result or len({d["key"] for d in result}) != len(result):
        fail("capability_unsupported", "链接克隆需要至少一块唯一可支持磁盘", 4)
    return sorted(result, key=lambda d: d["key"])


def nics(config):
    from pyVmomi import vim
    result = []
    for device in config.hardware.device:
        if isinstance(device, vim.vm.device.VirtualEthernetCard):
            backing = device.backing
            if isinstance(backing, vim.vm.device.VirtualEthernetCard.NetworkBackingInfo) and backing.network:
                identity = {"network": backing.network._moId}
            elif isinstance(backing, vim.vm.device.VirtualEthernetCard.DistributedVirtualPortBackingInfo) and backing.port:
                identity = {"switch": backing.port.switchUuid, "portgroup": backing.port.portgroupKey,
                            "port": backing.port.portKey}
            else:
                fail("capability_unsupported", "快照包含不支持的网卡 backing", 4)
            result.append({"key": int(device.key), "backing": identity})
    return sorted(result, key=lambda n: n["key"])


def nic_networks(values):
    # Cloning can allocate a new DV port, but must preserve the adapter key,
    # standard network, and distributed switch/portgroup mapping.
    return [{"key": nic["key"], "backing": {k: v for k, v in nic["backing"].items() if k != "port"}}
            for nic in values]


def mount(provider, datastore_id, hosts):
    ds = provider.resolver("datastore", datastore_id)
    if ds._moId != datastore_id:
        fail("target_changed", "数据存储身份变化", 4)
    if (ds.summary.accessible is not True or ds.summary.maintenanceMode != "normal"
            or getattr(ds.summary, "type", None) not in ("VMFS", "NFS", "NFS41")):
        fail("placement_invalid", "链接磁盘的数据存储不可访问", 4)
    for host in hosts:
        mounts = [m.mountInfo for m in ds.host if m.key._moId == host._moId]
        if (datastore_id not in [d._moId for d in host.datastore] or len(mounts) != 1
                or mounts[0].accessible is not True or mounts[0].mounted is False
                or mounts[0].accessMode != "readWrite"):
            fail("placement_invalid", "源与目标主机须可读写访问完整磁盘链", 4)
    provider.privileges(ds, ("Datastore.Browse",))


def compute_disks(provider, vm):
    """Relocate auto-moves PMem even with no datastore in its spec.

    VIM ConfigInfo/VirtualDisk do not expose associated PBM storage profiles.
    Without a trusted PBM connection even VMFS/NFS disks lack exclusion
    evidence. Only an explicitly diskless VM can currently pass this guard.
    """
    from pyVmomi import vim
    devices = getattr(vm.config.hardware, "device", None)
    if devices is None or any(isinstance(d, vim.vm.device.VirtualNVDIMM) for d in devices):
        fail("dependency_unproven", "无法排除计算迁移触发 NVDIMM/持久内存存储移动", 4)
    if any(isinstance(d, vim.vm.device.VirtualDisk) for d in devices):
        fail("dependency_unproven", "缺少可信 PBM 存储策略关联证据，无法排除 PMem 策略引发隐式迁盘；当前仅允许明确无磁盘的计算迁移", 4)
    stores = {ds._moId: ds for ds in vm.datastore}
    if not stores or any(getattr(ds.summary, "type", None) not in ("VMFS", "NFS", "NFS41") for ds in stores.values()):
        fail("dependency_unproven", "计算迁移仅支持明确的 VMFS/NFS 文件存储；未知、PMem 或 vVol 可能隐式移动磁盘", 4)
    return []


def preflight(provider, vm, params):
    if params["parent_uuid"] != vm.config.instanceUuid:
        fail("target_changed", "父 VM UUID 与精确对象不匹配", 4)
    snapshot = provider.snapshot(vm, params["snapshot_id"]).snapshot
    if snapshot.vm._moId != vm._moId:
        fail("target_changed", "快照所属父对象不匹配", 4)
    config = snapshot.config
    if config.instanceUuid != vm.config.instanceUuid:
        fail("target_changed", "快照配置的父 VM UUID 不匹配", 4)
    source = vm.runtime.host
    objects = resolve(provider, params)
    if any(obj._moId != params[kind + "_id"] for kind, obj in objects.items()):
        fail("target_changed", "目标放置对象身份变化", 4)
    target = objects["host"]
    if (source is None or source.runtime.connectionState != "connected" or source.runtime.inMaintenanceMode
            or source.capability.cloneFromSnapshotSupported is not True
            or source.capability.deltaDiskBackingsSupported is not True
            or target.capability.deltaDiskBackingsSupported is not True
            or vm.capability.snapshotConfigSupported is not True
            or vm.capability.snapshotOperationsSupported is not True):
        fail("capability_unsupported", "缺少源快照克隆或源/目标链接磁盘能力的明确证据", 4)
    current, frozen = disks(vm.config), disks(config)
    if ([{k: v for k, v in d.items() if k != "chain"} for d in current]
            != [{k: v for k, v in d.items() if k != "chain"} for d in frozen]
            or nics(vm.config) != nics(config)):
        fail("capability_unsupported", "当前与快照磁盘/网络配置不同，必须重新选择可验证的父快照", 4)
    evidence = placement(provider, vm, params, "deploy linked-clone")
    stores = {b["datastore_id"] for d in current + frozen for b in d["chain"]}
    for ds in sorted(stores):
        mount(provider, ds, (source, target))
    mount(provider, params["datastore_id"], (target,))
    for network in vm.network:
        provider.privileges(network, ("Network.Assign",))
    evidence.update(source_host_id=source._moId, network_ids=sorted(n._moId for n in vm.network),
                    source_disks=current, nics=nics(config), license_verified=False,
                    capabilities={"clone_from_snapshot": True, "source_delta": True, "target_delta": True})
    return evidence, {"server_uuid": provider.server_uuid, "parent_uuid": vm.config.instanceUuid,
                      "parent_id": vm._moId, "snapshot_id": snapshot._moId, "disks": frozen}


def clone(provider, vm, params):
    from pyVmomi import vim
    location = relocation(provider, params)
    location.diskMoveType = vim.vm.RelocateSpec.DiskMoveOptions.createNewChildDiskBacking
    spec = vim.vm.CloneSpec(location=location, powerOn=False, template=False,
                           snapshot=provider.snapshot(vm, params["snapshot_id"]).snapshot)
    return vm.CloneVM_Task(folder=provider.resolver("folder", params["folder_id"]), name=params["name"], spec=spec)


def verify(provider, params, binding, observation):
    result = observation.get("result_id")
    if not result or result == binding["object_id"]:
        return False
    child = provider.vm(result)
    if (child.config.instanceUuid != observation.get("instance_uuid")
            or child.config.instanceUuid == binding["instance_uuid"] or child.config.template is not False
            or child.name != params["name"] or child.parent._moId != params["folder_id"]
            or child.resourcePool._moId != params["pool_id"] or child.runtime.host._moId != params["host_id"]
            or child.runtime.powerState != "poweredOff"
            or sorted(n._moId for n in child.network) != binding["placement"]["network_ids"]):
        return False
    try:
        actual = disks(child.config)
        if nic_networks(nics(child.config)) != nic_networks(binding["placement"]["nics"]):
            return False
    except OperationError:
        return False
    expected = binding["parent_dependency"]["disks"]
    if len(actual) != len(expected):
        return False
    for disk, parent in zip(actual, expected):
        if ({k: v for k, v in disk.items() if k != "chain"} != {k: v for k, v in parent.items() if k != "chain"}
                or disk["chain"][1:] != parent["chain"]
                or disk["chain"][0]["datastore_id"] != params["datastore_id"]
                or disk["chain"][0]["file"] in [b["file"] for b in parent["chain"]]):
            return False
    return True
