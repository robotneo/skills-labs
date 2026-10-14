from ...domain.models import Result
from ...providers.vsphere.connection import server_info
from ...providers.vsphere.inventory import Inventory


def read(ctx, kind, p, inspect=False):
    with ctx.session() as si:
        inventory = Inventory(si)
        data = inventory.resolve(kind, p.get("name"), p.get("id")) if inspect else inventory.list(kind, p["limit"])
        return result(ctx, si, data, inventory.content)


def result(ctx, si, data, content=None):
    warnings = ["开发候选版：vSphere 6.5–8.0 实机兼容尚未验证"]
    if not ctx.profiles.get(ctx.profile).get("verify_tls", True):
        warnings.append("本 Profile 显式关闭 TLS 证书验证")
    return Result(data=data, target={"profile": ctx.profile, "instance_uuid": server_info(si, content)["instance_uuid"]}, warnings=warnings)


def profile_test(ctx, p):
    with ctx.session() as si:
        return result(ctx, si, {"connected": True, "server": server_info(si)})


def inventory_list(ctx, p):
    return read(ctx, p["kind"], p)


def vm_list(ctx, p):
    return read(ctx, "vm", p)


def vm_inspect(ctx, p):
    return read(ctx, "vm", p, True)


def template_list(ctx, p):
    return read(ctx, "template", p)


def template_inspect(ctx, p):
    return read(ctx, "template", p, True)


def host_info(ctx, p):
    return read(ctx, "host", p, True)


def cluster_list(ctx, p):
    return read(ctx, "cluster", p)


def cluster_info(ctx, p):
    return read(ctx, "cluster", p, True)


def datastore_list(ctx, p):
    return read(ctx, "datastore", p)


def datastore_inspect(ctx, p):
    return read(ctx, "datastore", p, True)


def alarm_list(ctx, p):
    from ...providers.vsphere.alarms import Alarms
    with ctx.session() as si:
        provider = Alarms(si)
        return result(ctx, si, provider.list(p.get("entity_id"), p.get("status"), p["limit"]),
                      provider.content)


def events_list(ctx, p):
    from ...providers.vsphere.ops import OpsReads
    with ctx.session() as si:
        provider = OpsReads(si)
        return result(ctx, si, provider.events(p), provider.content)


def ip_check(ctx, p):
    with ctx.session() as si, ctx.store() as store:
        from ...application.ipsignals import IpSignals
        inventory = Inventory(si)
        items = inventory.list("vm", 1000)["items"]
        signals = IpSignals(store, items)
        return result(ctx, si, signals.check(p["address"], p["scope"]), inventory.content)


def ip_available(ctx, p):
    with ctx.session() as si, ctx.store() as store:
        from ...application.ipsignals import IpSignals
        inventory = Inventory(si)
        items = inventory.list("vm", 1000)["items"]
        signals = IpSignals(store, items)
        return result(ctx, si, signals.available(p["address"], p["scope"]), inventory.content)


def quota_check(ctx, p):
    from ...providers.vsphere.ops import OpsReads
    with ctx.session() as si:
        provider = OpsReads(si)
        return result(ctx, si, provider.quota(p), provider.content)


def inventory_export(ctx, p):
    import csv
    import io as _io
    import os
    from ...domain.models import fail
    file_path = p["file"]
    if os.path.exists(file_path) or os.path.islink(file_path):
        fail("file_exists", "目标文件已存在或为符号链接，拒绝覆盖", 2)
    with ctx.session() as si:
        inventory = Inventory(si)
        data = inventory.list(p.get("kind", "vm"), p["limit"])
        response = result(ctx, si, {**data, "file": file_path,
                                    "format": p.get("format", "json")}, inventory.content)
        items = data["items"]
        if p.get("format", "json") == "csv":
            buffer = _io.StringIO()
            columns = sorted({key for row in items for key in row})
            writer = csv.writer(buffer)
            writer.writerow(columns)
            for row in items:
                writer.writerow([_csv_cell(row.get(column)) for column in columns])
            content = buffer.getvalue()
        else:
            import json
            content = json.dumps(items, ensure_ascii=False, indent=2)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(file_path, flags, 0o600)
        try:
            os.write(descriptor, content.encode("utf-8"))
        finally:
            os.close(descriptor)
    return response


def _csv_cell(value):
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@"):
        return "'" + text
    return text


def vm_snapshot_list(ctx, p):
    from ...providers.vsphere.mutations import Mutations
    from ...providers.vsphere.reads import Reads
    with ctx.session() as si:
        reader = Reads(Mutations(si))
        return result(ctx, si, reader.snapshots(p["vm_id"], p["limit"]), reader.provider.content)


def vm_tools_status(ctx, p):
    from ...providers.vsphere.mutations import Mutations
    from ...providers.vsphere.reads import Reads
    with ctx.session() as si:
        reader = Reads(Mutations(si))
        return result(ctx, si, reader.tools(p["vm_id"]), reader.provider.content)


def vm_wait_tools(ctx, p):
    import time
    from ...providers.vsphere.mutations import Mutations
    from ...providers.vsphere.reads import Reads
    deadline = time.monotonic() + ctx.timeout
    with ctx.session() as si:
        reader = Reads(Mutations(si))
        content = reader.provider.content
        while True:
            data = reader.tools(p["vm_id"])
            if data["ready"] or time.monotonic() >= deadline:
                response = result(ctx, si, data, content)
                if not data["ready"]:
                    response.status = "running"
                    response.next_action = {"command": "vm tools-status", "vm_id": p["vm_id"]}
                return response
            time.sleep(min(1, max(0, deadline - time.monotonic())))
