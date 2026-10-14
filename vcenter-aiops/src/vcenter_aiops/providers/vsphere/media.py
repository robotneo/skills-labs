"""Mount recently observed datastore paths without creating preview search tasks."""
from copy import deepcopy
import json
import math
import time

from ...domain.models import OperationError, fail
from .datastores import Datastores, valid_task_id
from .devices import datastore, is_integer, layout


WARNING = "ISO 仅依据最近搜索观察的路径元数据；不能保证内容不可变或消除外部替换竞态；后置仅核对光驱配置，不验证启动或内容完整性"


def identity(cdrom):
    from pyVmomi import vim
    b, c = cdrom.backing, cdrom.connectable
    supported = (vim.vm.device.VirtualCdrom.IsoBackingInfo,
                 vim.vm.device.VirtualCdrom.RemotePassthroughBackingInfo,
                 vim.vm.device.VirtualCdrom.RemoteAtapiBackingInfo,
                 vim.vm.device.VirtualCdrom.AtapiBackingInfo,
                 vim.vm.device.VirtualCdrom.PassthroughBackingInfo)
    if not isinstance(b, supported) or c is None:
        fail("capability_unsupported", "光驱 backing 或连接配置不可确定", 4)
    return {"key": cdrom.key, "controller_key": cdrom.controllerKey, "unit_number": cdrom.unitNumber,
            "backing_type": type(b).__name__, "file_name": getattr(b, "fileName", None),
            "datastore_id": getattr(getattr(b, "datastore", None), "_moId", None),
            "device_name": getattr(b, "deviceName", None), "auto_detect": getattr(b, "useAutoDetect", None),
            "connected": c.connected, "start_connected": c.startConnected, "allow_guest_control": c.allowGuestControl}


def drive(vm, key):
    from pyVmomi import vim
    candidates = [d for d in layout(vm) if d.key == key and isinstance(d, vim.vm.device.VirtualCdrom)]
    if len(candidates) != 1:
        fail("target_invalid", "指定 device key 不是唯一现有光驱；不会新增设备", 4)
    return candidates[0]


def evidence(provider, params, ds):
    resolver = getattr(provider, "search_record", None)
    if not callable(resolver):
        fail("search_evidence_required", "须通过现有 Engine 使用已持久化成功搜索 search_id", 4)
    row = resolver(params["search_id"])
    created = row["created"]
    if (type(created) not in (int, float) or not math.isfinite(created)
            or not 0 <= time.time() - created <= 300):
        fail("search_evidence_expired", "搜索证据创建时间超过300秒或在未来；请完成新搜索并重新预览", 4)
    if row["state"] != "succeeded" or not row["receipt"] or not row["result"]:
        fail("search_evidence_required", "先使用 datastore browse/scan 与 search-status 完成搜索", 4)
    scope, receipt, result = (json.loads(row[k]) for k in ("scope", "receipt", "result"))
    if any(value.get("server_uuid") != provider.server_uuid or value.get("datastore_id") != ds._moId
           or value.get("datastore_name") != ds.name for value in (scope, receipt, result)):
        fail("search_scope_changed", "搜索证据服务端或存储绑定已变化", 4)
    task_id = receipt.get("task_id")
    if not valid_task_id(task_id):
        fail("task_identity_mismatch", "原搜索任务身份无效", 4)
    info = provider.resolver("task", task_id).info
    if info.key != task_id or str(info.state) != "success" or info.result is None:
        fail("search_evidence_changed", "无法核对原成功搜索任务", 4)
    wanted_folder, _, wanted_name = params["path"].rpartition("/")
    full_folder = "[" + ds.name + "]" + (" " + wanted_folder + "/" if wanted_folder else " ")
    def same_folder(folder):
        # Only the API's one structural suffix is optional; directory-name
        # whitespace is part of the verified path and must remain exact.
        return isinstance(folder, str) and folder in (full_folder, full_folder[:-1])
    saved = [item for item in result.get("items", []) if item.get("name") == wanted_name and same_folder(item.get("folder"))]
    folders = info.result if scope.get("recursive") else [info.result]
    observed = [f for folder in folders if same_folder(folder.folderPath) for f in (folder.file or []) if f.path == wanted_name]
    if len(saved) != 1 or len(observed) != 1:
        fail("iso_not_observed", "原成功搜索中没有唯一精确 ISO 文件；请完成新搜索", 4)
    file = observed[0]
    metadata = {"name": file.path, "folder": saved[0]["folder"], "size_bytes": file.fileSize,
                "modified_at": file.modification.isoformat() if file.modification else None, "type": type(file).__name__}
    if (metadata != saved[0] or not is_integer(file.fileSize) or file.fileSize <= 0 or file.modification is None):
        fail("search_evidence_changed", "文件元数据缺失或与已保存证据不一致", 4)
    return {"search_id": row["id"], "task_id": task_id, "created_at": created,
            "freshness_basis": "persisted_search_created_at_conservative_completion_lower_bound", "file": metadata}


def preflight(provider, vm, params, mount):
    cdrom = drive(vm, params["cdrom_key"])
    bound = {"before": identity(cdrom)}
    if mount:
        # Reuse the exact datastore browse path boundary; never submit a search.
        scope = Datastores(provider.si, resolver=lambda oid: provider.resolver("datastore", oid)).prepare(params["datastore_id"], params["path"])
        if not params["path"].lower().endswith(".iso") or any(not p for p in params["path"].split("/")):
            fail("path_invalid", "需要精确相对 ISO 文件路径", 2)
        ds = datastore(provider, vm, params["datastore_id"])
        provider.privileges(ds, ("Datastore.Browse",))
        bound.update(evidence(provider, params, ds), datastore_id=ds._moId, datastore_name=ds.name,
                     host_id=vm.runtime.host._moId, file_name="[" + scope["datastore_name"] + "] " + params["path"])
    return bound


def changes(provider, vm, params, mount):
    from pyVmomi import vim
    cdrom = deepcopy(drive(vm, params["cdrom_key"]))
    if mount:
        ds = provider.resolver("datastore", params["datastore_id"])
        cdrom.backing = vim.vm.device.VirtualCdrom.IsoBackingInfo(datastore=ds, fileName="[" + ds.name + "] " + params["path"])
    else:
        cdrom.backing = vim.vm.device.VirtualCdrom.RemotePassthroughBackingInfo(deviceName="", useAutoDetect=True)
    cdrom.connectable = vim.vm.device.VirtualDevice.ConnectInfo(connected=False, startConnected=mount, allowGuestControl=False)
    return [vim.vm.device.VirtualDeviceSpec(operation="edit", device=cdrom)]


def verify(vm, params, bound, mount):
    from pyVmomi import vim
    try:
        cdrom = drive(vm, params["cdrom_key"])
        c = cdrom.connectable
        if (cdrom.controllerKey != bound["before"]["controller_key"] or cdrom.unitNumber != bound["before"]["unit_number"]
                or c is None or c.connected is not False or c.startConnected is not mount or c.allowGuestControl is not False):
            return False
        if mount:
            return (isinstance(cdrom.backing, vim.vm.device.VirtualCdrom.IsoBackingInfo)
                    and cdrom.backing.fileName == bound["file_name"] and cdrom.backing.datastore is not None
                    and cdrom.backing.datastore._moId == bound["datastore_id"])
        return (isinstance(cdrom.backing, vim.vm.device.VirtualCdrom.RemotePassthroughBackingInfo)
                and cdrom.backing.deviceName == "" and cdrom.backing.useAutoDetect is True)
    except (AttributeError, TypeError, OperationError):
        return False
