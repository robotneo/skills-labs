"""Explicit placement, no implicit power-on or network remapping."""
import re
from ...domain.models import fail


def resource(provider, kind, object_id, pattern):
    if not re.fullmatch(pattern, object_id):
        fail("placement_invalid", "目标资源必须使用精确对象 ID", 2)
    obj = provider.resolver(kind, object_id)
    if not obj.name:
        fail("placement_invalid", "目标资源不可读", 4)
    return obj


def resolve(provider, params):
    objects = {
        "pool": resource(provider, "pool", params["pool_id"], r"resgroup-\d+"),
        "datastore": resource(provider, "datastore", params["datastore_id"], r"datastore-\d+"),
        "host": resource(provider, "host", params["host_id"], r"host-\d+"),
    }
    if "folder_id" in params:
        objects["folder"] = resource(provider, "folder", params["folder_id"], r"group-v\d+")
    return objects


def preflight(provider, vm, params, command):
    from pyVmomi import vim
    if command == "vm migrate" and "datastore_id" not in params:
        from .templates import conversion_placement
        from .linked import compute_disks
        disks = compute_disks(provider, vm)
        return {**conversion_placement(provider, vm, params), "source_disks": disks,
                "source_host_id": vm.runtime.host._moId}
    objects = resolve(provider, params)
    host, ds, pool = objects["host"], objects["datastore"], objects["pool"]
    if host.runtime.connectionState != "connected" or host.runtime.inMaintenanceMode:
        fail("placement_invalid", "目标主机必须已连接且不在维护模式", 4)
    if host.parent._moId != pool.owner._moId or ds._moId not in [d._moId for d in host.datastore]:
        fail("placement_invalid", "主机与资源池或数据存储不匹配", 4)
    if not ds.summary.accessible or ds.summary.maintenanceMode != "normal":
        fail("placement_invalid", "数据存储不可访问或处于维护模式", 4)
    networks = {n._moId for n in host.network}
    if any(n._moId not in networks for n in vm.network):
        fail("placement_invalid", "目标主机缺少源 VM 网络；不会隐式改网", 4)
    disks = [d for d in vm.config.hardware.device if isinstance(d, vim.vm.device.VirtualDisk)]
    estimate = sum(d.capacityInKB * 1024 for d in disks)
    if ds.summary.freeSpace < estimate:
        fail("capacity_insufficient", "目标数据存储可用空间不足以容纳虚拟磁盘标称容量", 4)
    if vm.config.keyId:
        fail("capability_unsupported", "加密 VM 放置尚未通过专项能力验证", 4)
    provider.privileges(pool, ("Resource.AssignVMToPool",))
    provider.privileges(ds, ("Datastore.AllocateSpace",))
    if "folder" in objects:
        folder = objects["folder"]
        if not any(x.rsplit(".", 1)[-1].lower() == "virtualmachine" for x in folder.childType):
            fail("placement_invalid", "目标不是 VM 文件夹", 4)
        if re.search(r"[/\\%\x00-\x1f]", params["name"]) or len(params["name"]) > 80:
            fail("name_invalid", "名称须为 1–80 字符，不含路径、百分号和控制字符", 2)
        if any(child.name == params["name"] for child in folder.childEntity):
            fail("target_exists", "目标文件夹已有同名对象", 4)
        provider.privileges(folder, ("VirtualMachine.Inventory.CreateFromExisting",))
    return {key: {"id": obj._moId, "name": obj.name} for key, obj in objects.items()}


def relocation(provider, p):
    from pyVmomi import vim
    if "datastore_id" not in p:
        return vim.vm.RelocateSpec(pool=provider.resolver("pool", p["pool_id"]), host=provider.resolver("host", p["host_id"]))
    objects = resolve(provider, p)
    return vim.vm.RelocateSpec(pool=objects["pool"], datastore=objects["datastore"], host=objects["host"])


def clone(provider, vm, p):
    from pyVmomi import vim
    spec = vim.vm.CloneSpec(location=relocation(provider, p), powerOn=False, template=False)
    return vm.CloneVM_Task(folder=provider.resolver("folder", p["folder_id"]), name=p["name"], spec=spec)


def migrate(provider, vm, p):
    return vm.RelocateVM_Task(spec=relocation(provider, p), priority="defaultPriority")
