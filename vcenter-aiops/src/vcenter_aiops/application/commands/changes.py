from ..execution import Engine
from ..providers import ProviderRouter


def preview(ctx, command, params):
    options = dict(params)
    request_id = options.pop("request_id", None)
    options.pop("dry_run", None)  # Preview is always non-mutating.
    options.pop("wait", None)
    with ctx.session() as si, ctx.store() as store:
        return Engine(store, ProviderRouter(si), ctx.profile, ctx.timeout).preview(command, options, request_id)


def vm_power_on(ctx, p):
    return preview(ctx, "vm power-on", p)


def alarm_acknowledge(ctx, p):
    return preview(ctx, "alarm acknowledge", p)


def alarm_reset(ctx, p):
    return preview(ctx, "alarm reset", p)


def vm_shutdown(ctx, p):
    return preview(ctx, "vm shutdown", p)


def vm_power_off(ctx, p):
    return preview(ctx, "vm power-off", p)


def vm_reset(ctx, p):
    return preview(ctx, "vm reset", p)


def vm_suspend(ctx, p):
    return preview(ctx, "vm suspend", p)


def vm_delete(ctx, p):
    return preview(ctx, "vm delete", p)


def vm_rename(ctx, p):
    return preview(ctx, "vm rename", p)


def vm_reconfigure(ctx, p):
    return preview(ctx, "vm reconfigure", p)


def vm_snapshot_create(ctx, p):
    return preview(ctx, "vm snapshot-create", p)


def vm_snapshot_revert(ctx, p):
    return preview(ctx, "vm snapshot-revert", p)


def vm_snapshot_delete(ctx, p):
    return preview(ctx, "vm snapshot-delete", p)


def deploy_mark_template(ctx, p):
    return preview(ctx, "deploy mark-template", p)


def template_convert(ctx, p):
    return preview(ctx, "template convert", p)


def deploy_iso(ctx, p):
    return preview(ctx, "deploy iso", p)


def deploy_unmount_iso(ctx, p):
    return preview(ctx, "deploy unmount-iso", p)


def vm_clone(ctx, p):
    return preview(ctx, "vm clone", p)


def deploy_template(ctx, p):
    return preview(ctx, "deploy template", p)


def deploy_clone_template(ctx, p):
    return preview(ctx, "deploy clone-template", p)


def vm_migrate(ctx, p):
    return preview(ctx, "vm migrate", p)


def plan_apply(ctx, p):
    with ctx.session() as si, ctx.store() as store:
        return Engine(store, ProviderRouter(si), ctx.profile, ctx.timeout).apply(p["plan_id"], p.get("confirm"), p.get("confirm_destruction"), p["wait"])


def plan_reconcile(ctx, p):
    with ctx.session() as si, ctx.store() as store:
        return Engine(store, ProviderRouter(si), ctx.profile, ctx.timeout).reconcile(p["plan_id"], p["wait"])
