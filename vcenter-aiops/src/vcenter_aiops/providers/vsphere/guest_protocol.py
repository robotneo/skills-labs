"""Guest protocol construction and bounded marker parsing; no remote calls."""
import base64
import hashlib
import ntpath
import posixpath
from pathlib import Path
import re
import shlex
import uuid

from ...domain.models import fail
from ...infrastructure.store import canonical
from . import guest_wrapper


def validate_path(value, family):
    if not isinstance(value, str) or not value or len(value) > 512 or any(ord(c) < 32 for c in value):
        fail("guest_path_invalid", "Guest 路径须为明确的绝对路径", 2)
    if family == "linux":
        valid = value.startswith("/") and value != "/" and all(p not in ("", ".", "..") for p in value[1:].split("/"))
    else:
        valid = bool(re.fullmatch(r"[A-Za-z]:\\[^<>:\"/|?*]+", value)) and all(
            p not in ("", ".", "..") and not p.endswith((" ", ".")) and
            not re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p)
            for p in value[3:].split("\\"))
    if not valid:
        fail("guest_path_invalid", "Guest 路径不符合所选系统的本地绝对路径规则", 2)
    return value


def build_run(identity, params, run_id=None, capture=False, mode="exec"):
    run_id = run_id or uuid.uuid4().hex
    if not isinstance(run_id, str) or not re.fullmatch("[0-9a-f]{32}", run_id):
        fail("guest_identity_invalid", "运行标识无效", 4)
    capture = bool(capture)
    if mode == "customize":
        # A customization run carries the validated declarative spec, not an
        # argv program. Identity/run markers/observation are shared with exec.
        run_fields = ("vm_id", "os_family", "guest_username", "credential_ref",
                      "run_parent", "python_path")
        payload = {key: params[key] for key in run_fields}
        payload.update({"customize_spec": params["customize_spec"]})
    else:
        payload = {**params}
    payload.update({"capture_output": capture, "run_id": run_id,
                    "mode": mode, "protocol": "guest-wrapper-v1",
                    **identity})
    source = Path(guest_wrapper.__file__).read_text(encoding="utf-8")
    payload["wrapper_sha256"] = hashlib.sha256(source.encode()).hexdigest()
    digest = hashlib.sha256(canonical(payload).encode()).hexdigest()
    payload["digest"] = digest
    # User text is decoded as data; never interpolate user parameters into code/shell.
    data = base64.b64encode(canonical(payload).encode()).decode("ascii")
    source += "\nimport base64, json\ntry:\n    run_wrapper(json.loads(base64.b64decode('" + data + "')))\nexcept BaseException:\n    sys.exit(125)\n"
    encoded = base64.b64encode(source.encode()).decode("ascii")
    bootstrap = "import base64;exec(base64.b64decode('" + encoded + "'))"
    arguments = '-I -c "' + bootstrap + '"' if params["os_family"] == "windows" else "-I -c " + shlex.quote(bootstrap)
    if len(arguments) > 30000:
        fail("guest_arguments_too_large", "包装器和参数超过保守启动长度限制", 2)
    path = ntpath if params["os_family"] == "windows" else posixpath
    return {"run_id": run_id, "digest": digest, "directory": path.join(params["run_parent"], run_id),
            "source": source, "program_path": params["python_path"], "arguments": arguments,
            "working_directory": params.get("working_directory") or params["run_parent"],
            "stdio": "PIPE" if capture else "DEVNULL", "shell": False,
            "capture_output": capture, "mode": mode,
            "stdout_name": guest_wrapper.STDOUT_NAME if capture else None,
            "stderr_name": guest_wrapper.STDERR_NAME if capture else None,
            "protocol": "guest-wrapper-v1"}


def parse_markers(listing, run, family):
    files = getattr(listing, "files", None)
    if getattr(listing, "remaining", None) != 0 or not isinstance(files, (list, tuple)) or len(files) > 8:
        fail("guest_result_invalid", "结果目录不是完整有界列表", 6)
    prefix = run["run_id"] + "-" + run["digest"]
    claimed = "claimed-v1-" + prefix
    done_prefix = "done-v1-" + prefix + "-"
    allowed_data = {name for name in (run.get("stdout_name"), run.get("stderr_name")) if name}
    seen, code = set(), None
    for item in files:
        name = getattr(item, "path", None)
        # open-vm-tools explicitly includes dot entries for directory queries.
        if name in (".", "..") and name not in seen and getattr(item, "type", None) == "directory":
            seen.add(name)
            continue
        if (not isinstance(name, str) or len(name) > 160 or name in seen or
                getattr(item, "type", None) != "file"):
            fail("guest_result_invalid", "结果目录含不可信条目", 6)
        seen.add(name)
        if name in ("claimed.tmp", "done.tmp", claimed):
            continue
        if name in allowed_data:
            # Output data files carry bounded base64 payload (nonzero size); a
            # zero-size or oversized output record is treated as corrupt.
            size = getattr(item, "size", None)
            if not isinstance(size, int) or not (0 < size <= guest_wrapper.MAX_OUTPUT_BYTES * 2):
                fail("guest_result_invalid", "输出记录大小不可信", 6)
            continue
        if getattr(item, "size", None) != 0:
            fail("guest_result_invalid", "结果目录含不可信条目", 6)
        if not name.startswith(done_prefix) or code is not None:
            fail("guest_result_invalid", "结果身份不匹配或有未知条目", 6)
        raw = name[len(done_prefix):]
        if not re.fullmatch(r"(?:0|[1-9][0-9]{0,9}|-[1-9][0-9]{0,2})", raw):
            fail("guest_result_invalid", "结果退出码不符合协议", 6)
        code = int(raw)
        if not ((0 <= code <= 4294967295) if family == "windows" else (-127 <= code <= 255)):
            fail("guest_result_invalid", "结果退出码超出系统范围", 6)
    if claimed not in seen:
        fail("guest_result_missing", "尚无可信认领记录，执行结果未知", 6)
    if run.get("capture_output") and code is not None and not allowed_data <= seen:
        fail("guest_result_invalid", "声明捕获但输出记录缺失或不完整", 6)
    return code
