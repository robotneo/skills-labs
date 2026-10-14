"""Guest output/transfer orchestration logic (no SDK import).

Hard, testable bounds live here: path validation, max transfer size, overwrite
policy and the pairing of a server-issued transfer URL with an HTTP boundary.
Real SDK calls (InitiateFileTransfer{From,To}Guest, ListFilesInGuest) and HTTP
fetch/put are injected, so the whole flow runs offline with doubles.
"""
import base64

from ...domain.models import OperationError, fail
from .guest_protocol import validate_path


MAX_TRANSFER_BYTES = 4 * 1024 * 1024


def validate_local_path(path):
    if not isinstance(path, str) or not path:
        fail("invalid_arguments", "本地路径不能为空", 2)
    return path


def read_output(listing, run, family, fetch):
    """Validate markers, then fetch & decode bounded stdout/stderr files.

    ``fetch(guest_path)`` returns the raw base64 bytes already downloaded for a
    named result file in the run directory. Returns stdout/stderr/exit_code, or
    None while the run is still in progress.
    """
    from .guest_protocol import parse_markers
    code = parse_markers(listing, run, family)
    if code is None:
        return None
    sep = "\\" if family == "windows" else "/"
    base = run["directory"].rstrip("/\\")
    stdout_b64 = fetch(base + sep + run["stdout_name"])
    stderr_b64 = fetch(base + sep + run["stderr_name"])
    return {"exit_code": code,
            "stdout": _decode_bounded(stdout_b64),
            "stderr": _decode_bounded(stderr_b64)}


def _decode_bounded(raw):
    if raw is None:
        fail("guest_result_missing", "输出记录缺失，结果不确定", 6)
    try:
        value = base64.b64decode(raw, validate=True)
    except Exception:
        fail("guest_result_invalid", "输出记录无法解码，结果不确定", 6)
    if len(value) > 65536:
        fail("guest_result_invalid", "输出超过捕获上限", 6)
    return value.decode("utf-8", errors="replace")


def download(initiate, fetch, *, guest_path, family, max_bytes=MAX_TRANSFER_BYTES):
    """Initiate a from-Guest transfer and stream it via the HTTP boundary."""
    validate_path(guest_path, family)
    info = initiate(guest_path)
    url = getattr(info, "url", None)
    size = getattr(info, "size", None)
    if not url:
        fail("guest_transfer_invalid", "服务端未返回下载地址", 6)
    if isinstance(size, int) and size > max_bytes:
        fail("guest_file_too_large", "Guest 文件超过允许的传输上限", 2)
    payload = fetch(url, max_bytes=max_bytes)
    if isinstance(size, int) and len(payload) != size:
        fail("guest_transfer_invalid", "下载字节数与服务端声明不一致，结果不确定", 6)
    return {"guest_path": guest_path, "bytes": len(payload), "payload": payload}


def upload(initiate, put, *, guest_path, family, payload, overwrite=False,
           max_bytes=MAX_TRANSFER_BYTES):
    """Validate, initiate a to-Guest transfer and put bytes via HTTP boundary."""
    validate_path(guest_path, family)
    if not isinstance(payload, (bytes, bytearray)):
        fail("invalid_arguments", "上传内容须为字节", 2)
    if len(payload) > max_bytes:
        fail("guest_file_too_large", "本地文件超过允许的传输上限", 2)
    url = initiate(guest_path, len(payload), bool(overwrite))
    if not url:
        fail("guest_transfer_invalid", "服务端未返回上传地址", 6)
    put(url, bytes(payload))
    return {"guest_path": guest_path, "bytes": len(payload)}
