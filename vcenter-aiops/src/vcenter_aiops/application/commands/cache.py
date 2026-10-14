"""Explicit inventory cache management; ordinary queries never read it."""
import time

from ...domain.models import OperationError, Result
from ...infrastructure.cache import CacheStore
from ...providers.vsphere.connection import server_info
from ...providers.vsphere.inventory import Inventory


def status(ctx, p):
    config = ctx.profiles.get(ctx.profile)
    with ctx.store() as store:
        return Result(data=CacheStore(store).status(ctx.profile, p["kind"], config))


def refresh(ctx, p):
    config = ctx.profiles.get(ctx.profile)
    attempted_at = time.time()
    with ctx.store() as store:
        cache = CacheStore(store)
        generation = cache.begin(ctx.profile, p["kind"])
        try:
            with ctx.session() as si:
                instance_uuid = server_info(si)["instance_uuid"]
                data = Inventory(si).list(p["kind"], 1000)
            publication = cache.publish(ctx.profile, instance_uuid, p["kind"], generation, config, data)
        except OperationError as error:
            return Result(status="failed", data={"attempted_at": attempted_at,
                          "previous": cache.status(ctx.profile, p["kind"], config)},
                          error={"code": error.code, "message": str(error), "retryable": False})
        except Exception:
            return Result(status="failed", data={"attempted_at": attempted_at,
                          "previous": cache.status(ctx.profile, p["kind"], config)},
                          error={"code": "cache_refresh_failed", "message": "只读刷新失败，旧快照已保留", "retryable": False})
        if not publication:
            return Result(status="partial", data={"published": False, "committed": False,
                          "current_at_check": False, "checked_at": time.time(),
                          "previous": cache.status(ctx.profile, p["kind"], config)},
                          warnings=["刷新期间已有更新的刷新或失效操作；本次结果未发布"])
        current = cache.is_current(ctx.profile, instance_uuid, p["kind"], publication)
        checked_at = time.time()
        if not current:
            return Result(status="partial", data={"published": False, "committed": True,
                          "current_at_check": False, "checked_at": checked_at,
                          "previous": cache.status(ctx.profile, p["kind"], config)},
                          warnings=["本次刷新已提交，但随后被更新或失效；结果不再是当前缓存"])
        return Result(data={"published": True, "committed": True, "current_at_check": True,
                            "checked_at": checked_at, **publication["snapshot"]},
                      target={"profile": ctx.profile, "instance_uuid": instance_uuid},
                      warnings=["缓存仅供显式只读用途；当前服务端身份需实时连接核对"])


def invalidate(ctx, p):
    with ctx.store() as store:
        cache = CacheStore(store)
        removed = cache.invalidate(ctx.profile, p["kind"])
    return Result(data={"profile": ctx.profile, "kind": p["kind"], "removed": removed,
                        "scope": "all_recorded_servers_for_profile_and_kind"})
