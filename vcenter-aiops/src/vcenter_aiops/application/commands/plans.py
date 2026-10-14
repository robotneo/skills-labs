import json
from pathlib import Path

from ...domain.models import Result, fail
from ..execution import Engine
from ..providers import ProviderRouter
from ..registry import lookup


def plan_create(ctx, p):
    import yaml
    source = Path(p["file"])
    if not source.is_file() or source.stat().st_size > 1024 * 1024:
        fail("plan_file_invalid", "计划文件不存在或超过 1 MiB", 2)
    try:
        data = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (ValueError, yaml.YAMLError):
        fail("plan_file_invalid", "计划文件不是有效 YAML/JSON", 2)
    if not isinstance(data, dict) or set(data) != {"steps"} or not isinstance(data["steps"], list):
        fail("plan_invalid", "计划文件必须只有 steps 数组", 2)
    steps = []
    for step in data["steps"]:
        if not isinstance(step, dict) or set(step) != {"command", "params"}:
            fail("plan_invalid", "步骤须包含 command 与 params", 2)
        spec = lookup(step["command"])
        if spec.category != "remote_write":
            fail("plan_command_invalid", "当前编排仅接受已注册远端原子写命令", 2)
        params = spec.validate(step["params"])
        if any(k in step["params"] for k in ("dry_run", "request_id", "wait")):
            fail("plan_invalid", "步骤不能覆盖编排执行控制参数", 2)
        params.pop("dry_run", None)
        params.pop("wait", None)
        steps.append({"command": spec.path, "params": params})
    with ctx.session() as si, ctx.store() as store:
        return Engine(store, ProviderRouter(si), ctx.profile, ctx.timeout).preview_steps(steps, p.get("request_id"))


def plan_validate(ctx, p):
    with ctx.session() as si, ctx.store() as store:
        engine = Engine(store, ProviderRouter(si), ctx.profile, ctx.timeout)
        return engine.validate(p["plan_id"])


def plan_archive(ctx, p):
    with ctx.store() as store:
        return Engine(store, None, ctx.profile).archive(p["plan_id"])


def plan_rollback(ctx, p):
    with ctx.session() as si, ctx.store() as store:
        return Engine(store, ProviderRouter(si), ctx.profile, ctx.timeout).rollback(p["plan_id"])


def batch(ctx, command, p):
    ids = p["vm_ids"]
    if not ids or len(ids) > 100 or any(not isinstance(x, str) for x in ids) or len(set(ids)) != len(ids):
        fail("batch_invalid", "提供 1–100 个不重复的精确 VM ID", 2)
    with ctx.session() as si, ctx.store() as store:
        return Engine(store, ProviderRouter(si), ctx.profile, ctx.timeout).preview_steps(
            [{"command": command, "params": {"vm_id": x}} for x in ids], p.get("request_id"))


def batch_power_on(ctx, p):
    return batch(ctx, "vm power-on", p)


def batch_power_off(ctx, p):
    return batch(ctx, "vm power-off", p)


def batch_shutdown(ctx, p):
    return batch(ctx, "vm shutdown", p)


def batch_reset(ctx, p):
    return batch(ctx, "vm reset", p)


def task_list(ctx, p):
    with ctx.store() as store:
        return Result(data=[dict(r) for r in store.db.execute("SELECT id,request_id,target,state,remote_task FROM operations ORDER BY rowid DESC LIMIT ?", (p["limit"],))])


def task_inspect(ctx, p):
    with ctx.store() as store:
        op = store.operation(p["operation_id"])
        op["payload"] = json.loads(op["payload"])
        return Result(data=op, warnings=["本地持久化状态；实时核对使用 task reconcile"])


def task_reconcile(ctx, p):
    with ctx.session() as si, ctx.store() as store:
        engine = Engine(store, ProviderRouter(si), ctx.profile, ctx.timeout)
        store.operation(p["operation_id"])
        row = store.db.execute("SELECT plan_id FROM execution_steps WHERE operation_id=?", (p["operation_id"],)).fetchone()
        if not row:
            fail("reconciliation_required", "此操作没有可核对的执行记录，禁止重新提交", 6)
        return engine.reconcile(row[0], False)


def task_wait(ctx, p):
    with ctx.session() as si, ctx.store() as store:
        engine = Engine(store, ProviderRouter(si), ctx.profile, ctx.timeout)
        store.operation(p["operation_id"])
        row = store.db.execute("SELECT plan_id FROM execution_steps WHERE operation_id=?", (p["operation_id"],)).fetchone()
        if not row:
            fail("reconciliation_required", "此操作没有可核对的执行记录", 6)
        return engine.reconcile(row[0], True)


def task_cancel(ctx, p):
    with ctx.session() as si, ctx.store() as store:
        return Engine(store, ProviderRouter(si), ctx.profile, ctx.timeout).cancel(p["operation_id"], p.get("confirm"))
