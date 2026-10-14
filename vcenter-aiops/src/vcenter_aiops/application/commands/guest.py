"""Guest entry points reuse the shared plan/execution engine."""
import os
from pathlib import Path

from ...domain.models import fail
from ..execution import Engine
from ..providers import ProviderRouter
from .changes import preview


def _tls(ctx):
    """Client TLS config for the active profile (never persisted)."""
    get_profile = getattr(ctx, "profiles", None)
    if get_profile is None:
        return {}
    profile = get_profile.get(ctx.profile)
    return {"verify_tls": profile.get("verify_tls", True),
            "ca_file": profile.get("ca_file")}


def _router(ctx, si):
    return ProviderRouter(si, tls=_tls(ctx))


def guest_exec(ctx, params):
    return preview(ctx, "vm guest-exec", params)


def guest_exec_output(ctx, params):
    return preview(ctx, "vm guest-exec-output", params)


def guest_process_status(ctx, params):
    with ctx.session() as si, ctx.store() as store:
        engine = Engine(store, _router(ctx, si), ctx.profile, ctx.timeout)
        store.operation(params["operation_id"])
        row = store.db.execute("SELECT plan_id,position FROM execution_steps WHERE operation_id=?",
                               (params["operation_id"],)).fetchone()
        if not row:
            fail("guest_operation_invalid", "操作没有可核对的 Guest 执行意图", 4)
        step = engine.checked_plan(row["plan_id"])["payload"]["steps"][row["position"]]
        if step["command"] not in ("vm guest-exec", "vm guest-exec-output", "vm guest-customize") or \
                step["binding"].get("provider_kind") != "guest":
            fail("guest_operation_invalid", "操作不是固定的 Guest 执行意图", 4)
        return engine.reconcile(row["plan_id"], params.get("wait", False))


def guest_output(ctx, params):
    with ctx.session() as si, ctx.store() as store:
        located = store.guest_run(params["run_id"], ctx.profile)
        guest = _router(ctx, si)._provider("guest")
        return guest.fetch_output(located["binding"])


def guest_download(ctx, params):
    target = Path(params["file"])
    if target.exists() or target.is_symlink():
        fail("file_exists", "本地目标文件已存在或为符号链接，拒绝覆盖", 2)
    with ctx.session() as si:
        guest = _router(ctx, si)._provider("guest")
        result = guest.download_file(
            params["vm_id"], params["guest_username"],
            params["credential_ref"], params["guest_path"],
            params["os_family"])
    target.parent.mkdir(parents=True, exist_ok=True)
    # Atomic exclusive create with private perms; O_NOFOLLOW (POSIX) refuses a
    # symlink swapped in between the check above and the open (TOCTU hardening).
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if os.name == "posix":
        flags |= os.O_NOFOLLOW
    payload = result.pop("payload")
    descriptor = os.open(target, flags, 0o600)
    try:
        os.write(descriptor, payload)
    finally:
        os.close(descriptor)
    result["file"] = str(target)
    return {"data": result}


def guest_upload(ctx, params):
    source = Path(params["file"])
    if not source.is_file():
        fail("file_not_found", "本地源文件不存在", 2)
    # Reject an oversized file before reading it into memory; the transfer
    # layer enforces the same bound again on the in-memory payload.
    from ...providers.vsphere.guest_transfer import MAX_TRANSFER_BYTES
    try:
        size = source.stat().st_size
    except OSError:
        fail("file_not_found", "无法读取本地源文件", 2)
    if size > MAX_TRANSFER_BYTES:
        fail("guest_file_too_large", "本地文件超过允许的传输上限（4MiB）", 2)
    payload = source.read_bytes()
    with ctx.session() as si:
        guest = _router(ctx, si)._provider("guest")
        result = guest.upload_file(
            params["vm_id"], params["guest_username"],
            params["credential_ref"], params["guest_path"],
            params["os_family"], payload, params["overwrite"])
    return {"data": result}


def guest_customize(ctx, params):
    return preview(ctx, "vm guest-customize", params)
