import argparse
import json
import sys
from ..application.context import Context
from ..application.registry import COMMANDS, lookup
from ..domain.models import OperationError, Result
from ..domain import risk


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse may echo an accidentally supplied credential or malformed value.
        raise OperationError("invalid_arguments", "参数无效；请使用对应命令 --help 查看格式", 2)


def build_parser():
    parser = Parser(prog="vcenter-aiops", description="vCenter AIops 3.0 开发候选版：原子化运维入口")
    parser.add_argument("--profile")
    # Distinct dest: a leaf command (e.g. `inventory export`) may itself define
    # --format for the *file* format (json/csv); that parameter keeps dest
    # "format", while the global console rendering choice must not collide with
    # it. Sharing one dest made `--format csv` also switch console rendering to
    # the table branch, prefixing JSON errors with "状态 | failed".
    parser.add_argument("--format", dest="output_format", choices=("json", "table"), default="json")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--yes", "-y", action="store_true", dest="assume_yes_global",
                        help="跳过中/高风险直接生效命令的交互式确认（仅限自动化场景；高风险仍须参数本身精确）")
    parser.add_argument("--debug-log", action="store_true", dest="debug_log",
                        help="内部错误(exit5)时把脱敏的 fault 类型/本地代码堆栈/operation_id 写入 0700 数据目录下的 0600 日志（不含参数/凭据/端点）；也可用 VCENTER_AIOPS_DEBUG_LOG=1 开启")
    root = parser.add_subparsers(dest="group", required=True)
    groups = {}
    for spec in COMMANDS:
        parts = spec.path.split()
        if len(parts) == 1:
            leaf = root.add_parser(parts[0], help=spec.description, description=spec.description)
        else:
            if parts[0] not in groups:
                groups[parts[0]] = root.add_parser(parts[0]).add_subparsers(dest="verb", required=True)
            leaf = groups[parts[0]].add_parser(parts[1], help=spec.description, description=spec.description)
        leaf.set_defaults(command=spec.path, assume_yes=False)
        # Also accept the confirmation bypass after the verb (natural order).
        leaf.add_argument("--yes", "-y", action="store_true", dest="assume_yes",
                          help="跳过中/高风险直接生效命令的交互式确认（仅限自动化）")
        for p in spec.parameters:
            name = p.name if p.positional else "--" + p.name.replace("_", "-")
            options = {"help": p.description, "default": argparse.SUPPRESS}
            if not p.positional:
                options["required"] = p.required
            if p.type == "boolean":
                options["action"] = argparse.BooleanOptionalAction
            else:
                options["type"] = {"string": str, "integer": int, "number": float, "object": json.loads, "array": json.loads}[p.type]
                if p.choices:
                    options["choices"] = p.choices
            leaf.add_argument(name, **options)
    return parser


TLS_DISABLED_WARNING = "本 Profile 显式关闭 TLS 证书验证；变更与凭据通信可能被中间人截获，生产环境建议配置 ca_file"
# Commands whose successful result means a remote mutation happened or is about
# to happen, so the disabled-certificate-verification risk must be surfaced
# (read commands already warn from their own result builder).
_TLS_WARN_PATHS = frozenset(("plan apply", "plan reconcile"))


def invoke(command, params, ctx):
    spec = lookup(command)
    return spec.handler()(ctx, spec.validate(params))


def append_tls_warning(ctx, spec, result):
    """Surface verify_tls=false on every remote-write result, preview or apply."""
    if (result is None or result.error or
            not (spec.category == "remote_write" or spec.path in _TLS_WARN_PATHS)):
        return result
    try:
        insecure = not ctx.profiles.get(ctx.profile).get("verify_tls", True)
    except OperationError:
        # No resolvable profile at this layer; the command path owns the error.
        return result
    if insecure and TLS_DISABLED_WARNING not in result.warnings:
        result.warnings.append(TLS_DISABLED_WARNING)
    return result


def interactive_apply(ctx, spec, params, result):
    is_engine_plan = spec.category == "remote_write" or spec.path.startswith("batch ")
    if not is_engine_plan or params.get("dry_run") or result.status != "awaiting_confirmation" or not sys.stdin.isatty():
        return result
    if spec.path.startswith("batch "):
        _print_bulk_banner(spec, params)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), file=sys.stderr)
    print("确认执行以上精确计划？请输入完整 digest；其他输入取消：", file=sys.stderr, flush=True)
    digest = sys.stdin.readline().strip()
    if digest != result.data["digest"]:
        return result
    confirmation = {"plan_id": result.data["id"], "confirm": digest, "wait": params.get("wait", True)}
    if "second_confirmation" in result.data:
        print("不可逆操作二次确认，请输入上方 second_confirmation：", file=sys.stderr, flush=True)
        second = sys.stdin.readline().strip()
        if second != result.data["second_confirmation"]:
            return result
        confirmation["confirm_destruction"] = second
    elif spec.path.startswith("batch "):
        # Bulk power is high risk but its steps are ordinary (non-destructive)
        # power actions, so the engine issues no DESTROY token. Enforce a second,
        # count-bound confirmation at the CLI: the operator must retype the
        # exact enumerated VM count after reviewing each precise target.
        count = len(params.get("vm_ids") or [])
        token = "BATCH-%d" % count
        print(f"批量变更二次确认：将影响 {count} 台 VM。请输入 {token} 继续；其他输入取消：",
              file=sys.stderr, flush=True)
        if sys.stdin.readline().strip() != token:
            return result
    return invoke("plan apply", confirmation, ctx)


_LEVEL_TITLE = {risk.MEDIUM: "中风险敏感操作", risk.HIGH: "高风险不可逆操作"}
_IRREVERSIBLE_WORD = {
    risk.IRREVERSIBLE_DELETE: "DELETE",
    risk.IRREVERSIBLE_CLEAR: "CLEAR",
    risk.IRREVERSIBLE_OVERWRITE: "OVERWRITE",
    risk.IRREVERSIBLE_TERMINATE: "TERMINATE",
}
_SENSITIVE_WORD = {
    risk.PERMISSION_CHANGE: "权限/凭据变更",
    risk.DATA_EXPORT: "数据外发/导出",
    risk.SYSTEM_CONFIG: "系统配置修改",
    risk.OUTBOUND_SEND: "对外发送/来宾执行",
    risk.PROCESS_TERMINATION: "终止进程/任务",
}


def _print_targets(targets):
    for item in targets["resources"]:
        index = f"#{item['index']} " if "index" in item else ""
        print(f"  - 资源 {index}[{item['kind']}] {item['id']}", file=sys.stderr)
    for item in targets["paths"]:
        print(f"  - 路径 [{item['field']}] {item['path']}", file=sys.stderr)
    for item in targets["scopes"]:
        print(f"  - 范围 [{item['kind']}] {item['value']}", file=sys.stderr)
    if targets["bulk"]:
        print(f"  - 数量：共 {targets['count']} 台 VM（逐个枚举，无范围/通配）", file=sys.stderr)


def _print_bulk_banner(spec, params):
    targets = risk.validate_exact_targets(spec, params)
    print(f"【{_LEVEL_TITLE[risk.HIGH]}】{spec.path}：{spec.description}", file=sys.stderr)
    print("影响范围：将对以下精确目标批量下发变更：", file=sys.stderr)
    _print_targets(targets)
    print("完整逐对象计划与 digest 随后展示，请据此核对。", file=sys.stderr, flush=True)


def direct_effect_gate(spec, params, assume_yes, profile=None):
    """Pre-invocation control for commands that take effect without the engine.

    Low risk runs directly. Medium risk explains its blast radius and needs an
    explicit confirmation. High risk additionally lists precise targets
    (resource/path/scope/count), rejects fuzzy or broad targeting, and requires
    a second exact confirmation. ``--yes`` only skips the interactive prompt
    (automation); exact-target validation is always enforced.
    """
    level = risk.risk_level(spec, params)
    if level == risk.LOW or not risk.is_direct_effect(spec, params):
        return
    sensitive, irreversible = risk.risk_tags(spec, params)
    try:
        targets = risk.validate_exact_targets(spec, params)
    except ValueError as exc:
        raise OperationError("target_not_exact", "目标不精确，已拒绝：" + str(exc), 2)
    print(f"【{_LEVEL_TITLE[level]}】{spec.path}：{spec.description}", file=sys.stderr)
    if sensitive:
        print("敏感类别：" + "、".join(_SENSITIVE_WORD.get(c, c) for c in sensitive), file=sys.stderr)
    if irreversible:
        print("不可逆类别：" + "、".join(_IRREVERSIBLE_WORD.get(c, c) for c in irreversible), file=sys.stderr)
    print("影响范围 / 精确目标：", file=sys.stderr)
    _print_targets(targets)
    try:
        token = risk.confirmation_token(spec, params, profile=profile)
    except ValueError as exc:
        raise OperationError("target_not_exact", "目标不精确，已拒绝：" + str(exc), 2)
    if assume_yes:
        print(f"已由 --yes 授权跳过交互确认（精确目标：{token}）。", file=sys.stderr, flush=True)
        return
    if not sys.stdin.isatty():
        raise OperationError(
            "confirmation_required",
            "此为敏感/不可逆操作，非交互环境须显式加 --yes 授权，或在终端中确认；本次未执行", 4)
    if level == risk.HIGH:
        print(f"高风险不可逆操作。请逐字输入精确目标 {token!r} 后回车；其他输入取消：",
              file=sys.stderr, flush=True)
        if sys.stdin.readline().strip() != token:
            raise OperationError("confirmation_declined", "目标确认不一致，已取消，未执行任何变更", 4)
        word = next((_IRREVERSIBLE_WORD[c] for c in irreversible if c in _IRREVERSIBLE_WORD), None)
        if word:
            print(f"二次确认：请输入 {word} 继续；其他输入取消：", file=sys.stderr, flush=True)
            if sys.stdin.readline().strip() != word:
                raise OperationError("confirmation_declined", "二次确认不一致，已取消，未执行任何变更", 4)
    else:
        print(f"请输入精确目标 {token!r} 确认执行；其他输入取消：", file=sys.stderr, flush=True)
        if sys.stdin.readline().strip() != token:
            raise OperationError("confirmation_declined", "确认不一致，已取消，未执行任何变更", 4)



def main(argv=None):
    output_format = "json"
    debug_log = None
    operation_id = None
    # L-5: both a business failure and an unexpected internal error exit 5. A
    # stable top-level ``category`` lets automation distinguish them in --json
    # without changing the exit-code contract. It is added only at render time
    # (never persisted to the Result/canonical/ledger) and only for exit 5.
    failure_category = None
    try:
        args = build_parser().parse_args(argv)
        output_format = args.output_format
        debug_log = getattr(args, "debug_log", False)
        if not 1 <= args.timeout <= 3600:
            raise OperationError("invalid_arguments", "timeout 必须为 1–3600 秒", 2)
        spec = lookup(args.command)
        raw_params = {p.name: getattr(args, p.name) for p in spec.parameters if hasattr(args, p.name)}
        ctx = Context(args.profile, args.timeout)
        # The risk gate never validates parameters (the command handler owns
        # that, including legitimate empty-string defaults); it only reads the
        # exact targeting values the caller already supplied.
        assume_yes = getattr(args, "assume_yes", False) or getattr(args, "assume_yes_global", False)
        direct_effect_gate(spec, raw_params, assume_yes, profile=args.profile)
        result = invoke(spec.path, raw_params, ctx)
        result = interactive_apply(ctx, spec, raw_params, result)
        result = append_tls_warning(ctx, spec, result)
        operation_id = getattr(result, "operation_id", None)
        code = {"awaiting_confirmation": 4, "failed": 5, "partial": 5, "reconciliation_required": 6}.get(result.status, 0)
        if code == 5:
            # A handler-reported failed/partial is an expected business outcome.
            failure_category = "business_failure"
    except OperationError as exc:
        code = exc.exit_code
        result = Result(status="failed", error={"code": exc.code, "message": str(exc), "retryable": False})
        # A deterministic/expected rejection that maps to exit 5 is still a
        # business failure, not an internal defect; other codes carry no tag.
        if code == 5:
            failure_category = "business_failure"
    except Exception as exc:
        code = 5
        failure_category = "internal_error"
        result = Result(status="failed", error={"code": "internal_error", "message": "内部执行失败", "retryable": False})
        # M-5: best-effort redacted diagnostics. Never echo the fault, never let
        # a logging failure change the exit-5 result; only the exception type,
        # local code frames and an already-known operation_id are persisted.
        try:
            from ..infrastructure import diagnostics
            diagnostics.record_internal_error(exc, operation_id=operation_id, explicit=debug_log)
        except Exception:
            pass
    payload = result.to_dict()
    if failure_category:
        payload["category"] = failure_category
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print("状态 | " + result.status)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code
