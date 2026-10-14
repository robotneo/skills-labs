"""Template conversion retains name, storage and power state."""
from ...domain.models import fail
from .placement import resource


def conversion_placement(provider, vm, params):
    pool = resource(provider, "pool", params["pool_id"], r"resgroup-\d+")
    host = resource(provider, "host", params["host_id"], r"host-\d+")
    if pool._moId != params["pool_id"] or host._moId != params["host_id"]:
        fail("target_changed", "目标资源身份变化", 4)
    if (host.runtime.connectionState != "connected" or host.runtime.inMaintenanceMode
            or host.parent._moId != pool.owner._moId):
        fail("placement_invalid", "目标主机必须可用且属于目标资源池", 4)
    datastores = list(vm.datastore)
    host_datastores = {ds._moId for ds in host.datastore}
    if not datastores or any(ds._moId not in host_datastores for ds in datastores):
        fail("placement_invalid", "目标主机无法访问模板现有数据存储", 4)
    for ds in datastores:
        summary = ds.summary
        mounts = [mount.mountInfo for mount in ds.host if mount.key._moId == host._moId]
        if (summary.accessible is not True or summary.maintenanceMode != "normal" or len(mounts) != 1
                # SDK documents an omitted mounted flag as true. Accessibility
                # must be established for this host, not inferred globally.
                or mounts[0].accessible is not True or mounts[0].mounted is False
                or mounts[0].accessMode != "readWrite"):
            fail("placement_invalid", "模板数据存储在目标主机上须已挂载、可读写且状态正常", 4)
    networks = sorted(n._moId for n in vm.network)
    if not set(networks).issubset(n._moId for n in host.network):
        fail("placement_invalid", "目标主机缺少模板网络", 4)
    provider.privileges(pool, ("Resource.AssignVMToPool",))
    return {"pool_id": pool._moId, "host_id": host._moId, "owner_id": pool.owner._moId,
            "datastore_ids": sorted(ds._moId for ds in datastores), "network_ids": networks}
