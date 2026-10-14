"""JSON-friendly local history and preset commands."""
import re

from ...domain.models import Result, fail
from ..history import History
from ..presets import Presets


def history_list(ctx, p):
    with ctx.store() as store:
        return Result(data=History(store).list(ctx.profile, p["after_id"], p["limit"], p.get("snapshot_max_id")))


def history_show(ctx, p):
    with ctx.store() as store:
        return Result(data=History(store).show(p["plan_id"], ctx.profile),
                      warnings=["本地历史状态；不代表当前远端状态或新的执行授权"])


def preset_list(ctx, p):
    with ctx.store() as store:
        return Result(data=Presets(store).list(ctx.profile, p.get("after_name", ""), p["limit"]))


def preset_show(ctx, p):
    with ctx.store() as store:
        return Result(data=Presets(store).show(ctx.profile, p["name"]))


def preset_save(ctx, p):
    with ctx.store() as store:
        return Result(data=Presets(store).save(ctx.profile, p["name"], p["command_path"], p["params"]))


def preset_delete(ctx, p):
    with ctx.store() as store:
        return Result(data=Presets(store).delete(ctx.profile, p["name"]))


def preset_from_history(ctx, p):
    with ctx.store() as store:
        command, params = History(store).reusable_step(p["plan_id"], ctx.profile, p["position"])
        data = Presets(store).save(ctx.profile, p["name"], command, params,
                                   {"type": "history", "plan_id": p["plan_id"], "position": p["position"]})
    return Result(data=data, warnings=["历史只提供参数；创建预设没有恢复原操作或继承确认"])


def preset_from_vm(ctx, p):
    if not isinstance(ctx.profile, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", ctx.profile):
        fail("profile_required", "预设须显式指定有效 --profile", 3)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", p["name"]):
        fail("preset_invalid", "预设名称无效", 2)
    if not all(isinstance(p[key], str) and re.fullmatch(r"vm-\d+", p[key]) for key in ("source_vm_id", "target_vm_id")):
        fail("target_invalid", "来源和目标都须为精确 vm-N ID", 2)
    from ...providers.vsphere.mutations import Mutations
    from ...providers.vsphere.reads import Reads
    with ctx.session() as si:
        hardware = Reads(Mutations(si)).preset_hardware(p["source_vm_id"])
    params = {"vm_id": p["target_vm_id"], **hardware}
    with ctx.store() as store:
        data = Presets(store).save(ctx.profile, p["name"], "vm reconfigure", params,
                                   {"type": "vm", "source_vm_id": p["source_vm_id"]})
    return Result(data=data, warnings=["仅保存 CPU/内存配置预设，不是部署或克隆模板；磁盘、网卡、控制器、存储、UUID、授权均未提取；未来目标由 target_vm_id 明确指定"])
