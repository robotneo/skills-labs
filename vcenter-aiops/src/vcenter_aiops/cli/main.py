import argparse
import json
import sys
from ..application.context import Context
from ..application.registry import COMMANDS, lookup
from ..domain.models import OperationError, Result


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
        leaf.set_defaults(command=spec.path)
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


def invoke(command, params, ctx):
    spec = lookup(command)
    return spec.handler()(ctx, spec.validate(params))


def interactive_apply(ctx, spec, params, result):
    if spec.category != "remote_write" or params.get("dry_run") or result.status != "awaiting_confirmation" or not sys.stdin.isatty():
        return result
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
    return invoke("plan apply", confirmation, ctx)


def main(argv=None):
    output_format = "json"
    try:
        args = build_parser().parse_args(argv)
        output_format = args.output_format
        if not 1 <= args.timeout <= 3600:
            raise OperationError("invalid_arguments", "timeout 必须为 1–3600 秒", 2)
        spec = lookup(args.command)
        params = {p.name: getattr(args, p.name) for p in spec.parameters if hasattr(args, p.name)}
        ctx = Context(args.profile, args.timeout)
        result = invoke(spec.path, params, ctx)
        result = interactive_apply(ctx, spec, params, result)
        code = {"awaiting_confirmation": 4, "failed": 5, "partial": 5, "reconciliation_required": 6}.get(result.status, 0)
    except OperationError as exc:
        code = exc.exit_code
        result = Result(status="failed", error={"code": exc.code, "message": str(exc), "retryable": False})
    except Exception:
        code = 5
        result = Result(status="failed", error={"code": "internal_error", "message": "内部执行失败", "retryable": False})
    payload = result.to_dict()
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    else:
        print("状态 | " + result.status)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return code
