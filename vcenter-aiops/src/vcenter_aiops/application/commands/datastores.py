from ...providers.vsphere.datastores import Datastores
from ..searches import Searches


def decorate(ctx, result):
    result.warnings.append("开发候选版：vSphere 6.5–8.0 实机兼容尚未验证")
    if not ctx.profiles.get(ctx.profile).get("verify_tls", True):
        result.warnings.append("本 Profile 显式关闭 TLS 证书验证")
    return result


def start(ctx, p, images_only):
    params = {k: p[k] for k in ("datastore_id", "path", "limit", "recursive")}
    params["images_only"] = images_only
    with ctx.session() as si, ctx.store() as store:
        result = Searches(store, Datastores(si), ctx.profile).start(params, p.get("request_id"), ctx.timeout if p["wait"] else 0)
        return decorate(ctx, result)


def browse(ctx, p):
    return start(ctx, p, False)


def scan(ctx, p):
    return start(ctx, p, True)


def search_status(ctx, p):
    with ctx.session() as si, ctx.store() as store:
        return decorate(ctx, Searches(store, Datastores(si), ctx.profile).reconcile(p["search_id"], ctx.timeout if p["wait"] else 0))


def search_inspect(ctx, p):
    with ctx.store() as store:
        return Searches(store, None, ctx.profile).result(p["search_id"])


def search_list(ctx, p):
    with ctx.store() as store:
        return Searches(store, None, ctx.profile).list(p["limit"])
