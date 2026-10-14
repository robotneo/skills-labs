import importlib.util
from ... import __version__
from ...domain.models import Result, fail


def version(ctx, p):
    return Result(data={"version": __version__, "product": "vcenter-aiops"})


def doctor(ctx, p):
    if p["connect"]:
        from .queries import profile_test
        return profile_test(ctx, {})
    dependencies = {m: importlib.util.find_spec(m) is not None for m in ("pyVmomi", "yaml")}
    return Result(data={"dependencies": dependencies, "data_home": str(ctx.home), "connected": False},
                  warnings=[] if all(dependencies.values()) else ["请安装项目依赖"])


def capabilities_list(ctx, p):
    from ..registry import capabilities
    return Result(data=capabilities())


def capabilities_show(ctx, p):
    from ..registry import lookup
    return Result(data=lookup(p["command_path"]).describe())


def profile_list(ctx, p):
    return Result(data=ctx.profiles.load()["profiles"])


def profile_show(ctx, p):
    return Result(data=ctx.profiles.get(p["name"]))


def profile_values(p):
    values = {k: v for k, v in p.items() if k not in ("name", "insecure")}
    if "insecure" in p:
        values["verify_tls"] = not p["insecure"]
    return values


def profile_add(ctx, p):
    value = profile_values(p)
    ctx.profiles.put(p["name"], value)
    return Result(data={"name": p["name"], **value})


def profile_update(ctx, p):
    value = ctx.profiles.update(p["name"], profile_values(p))
    return Result(data={"name": p["name"], **value})


def profile_delete(ctx, p):
    ctx.profiles.delete(p["name"])
    return Result(data={"deleted": p["name"]})


def ip_reserve(ctx, p):
    with ctx.store() as store:
        return Result(data=store.reserve(p["scope"], p["ip"], p["owner"], p.get("minutes")))


def ip_release(ctx, p):
    with ctx.store() as store:
        store.release(p["lease_id"])
    return Result(data={"released": p["lease_id"]})


def ip_list(ctx, p):
    with ctx.store() as store:
        return Result(data=store.leases(p.get("scope")))


def ip_expire(ctx, p):
    from ..ipsignals import IpSignals
    with ctx.store() as store:
        signals = IpSignals(store, [])
        if p.get("apply"):
            return Result(data=signals.expire_release(p["lease_id"]))
        return Result(data=signals.expired())


def plan_list(ctx, p):
    with ctx.store() as store:
        return Result(data=store.plans())


def plan_show(ctx, p):
    with ctx.store() as store:
        return Result(data=store.plan(p["plan_id"]))


def audit_list(ctx, p):
    from ..audit import AuditLog
    if ctx.profile is not None:
        fail("audit_scope_unsupported", "当前审计库覆盖全部本地 Profile，不支持按 Profile 过滤；请移除 --profile 后明确查询全库", 2)
    with ctx.store() as store:
        return Result(data=AuditLog(store).list(p["after_id"], p["limit"], p.get("snapshot_max_id")))


def audit_export(ctx, p):
    from ..audit import AuditLog
    if ctx.profile is not None:
        fail("audit_scope_unsupported", "当前审计库覆盖全部本地 Profile，不支持按 Profile 过滤；请移除 --profile 后明确导出全库", 2)
    with ctx.store() as store:
        data = AuditLog(store).export(p["file"], p["after_id"], p["limit"], p.get("snapshot_max_id"))
        return Result(status=data["status"], data=data, warnings=data["warnings"] + ["导出仅包含事件元数据和主体关联代号；本地文件未发送到外部平台"])
