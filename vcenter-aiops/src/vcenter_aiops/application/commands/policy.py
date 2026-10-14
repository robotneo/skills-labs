"""Static registry policy views without execution authority."""
from ...domain.models import OperationError, Result
from ..registry import lookup


def inspect(ctx, p):
    spec = lookup(p["command_path"])
    return Result(data={"command": spec.path, "category": spec.category, "risk": spec.risk,
                        "input_schema": spec.input_schema(), "required_privileges": list(spec.privileges),
                        "authorization": "not_checked", "remote_capability": "not_checked"},
                  warnings=["仅注册表静态信息；执行前仍须远端实时预检及独立确认"])


def check(ctx, p):
    spec = lookup(p["command_path"])
    try:
        spec.validate(p["params"])
    except OperationError as error:
        valid, reason = False, error.code
    else:
        valid, reason = True, None
    return Result(data={"command": spec.path, "static_valid": valid, "reason": reason,
                        "risk": spec.risk, "required_privileges": list(spec.privileges),
                        "authorization": "not_checked", "remote_capability": "not_checked"},
                  warnings=["静态参数通过不代表远端权限、能力或执行确认；本命令没有远端连接"])
