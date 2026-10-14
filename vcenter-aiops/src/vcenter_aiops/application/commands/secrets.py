"""Local global namespace; values never enter command parameters or the Store."""
import getpass
import sys
import warnings

from ...domain.models import Result, fail
from ...infrastructure.secrets import MAX_SECRET_BYTES, validate_name, validate_value


def _vault(ctx):
    if ctx.profile is not None:
        fail("secret_scope_unsupported", "密钥库为本地全局命名空间，不支持 --profile 过滤", 2)
    return ctx.secrets


def _input(use_stdin):
    try:
        if use_stdin:
            stream = getattr(sys.stdin, "buffer", sys.stdin)
            value = stream.read(MAX_SECRET_BYTES + 3)
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            if value.endswith("\r\n"):
                value = value[:-2]
            elif value.endswith(("\n", "\r")):
                value = value[:-1]
        else:
            if not sys.stdin.isatty():
                fail("secret_input_required", "非终端输入须显式使用 --stdin；不接受命令行秘密值", 2)
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                value = getpass.getpass("秘密值（隐藏输入，最多 4096 UTF-8 字节）：")
    except UnicodeError:
        fail("secret_value_invalid", "秘密值须为非空 UTF-8 文本，最多 4096 字节", 2)
    except (getpass.GetPassWarning, EOFError, OSError):
        fail("secret_input_unavailable", "无法安全读取秘密值；输入未保存", 2)
    validate_value(value)
    return value


def list_secrets(ctx, p):
    return Result(data={"items": _vault(ctx).list()})


def set_secret(ctx, p):
    vault = _vault(ctx)
    validate_name(p["name"])
    return Result(data=vault.set(p["name"], _input(p["stdin"])))


def rotate_secret(ctx, p):
    vault = _vault(ctx)
    validate_name(p["name"])
    return Result(data=vault.rotate(p["name"], _input(p["stdin"])))


def delete_secret(ctx, p):
    _vault(ctx).delete(p["name"])
    return Result(data={"deleted": p["name"]})
