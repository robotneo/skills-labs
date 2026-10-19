"""Local, redacted diagnostics for otherwise-unhandled internal errors (M-5).

The CLI catch-all keeps returning the generic ``internal_error/exit5`` payload
without echoing the fault (which is correct — remote messages and arguments may
carry sensitive data). Real-vCenter triage, however, needs *something* to go on
without forcing a reproduction. This module optionally persists a strictly
redacted record:

* the exception **type name** only (never ``str(exc)`` — remote fault messages
  can embed endpoints, object paths or identifiers);
* the local code stack: per frame only file/function/line, never frame locals
  or arguments (those may contain credentials or parameters);
* the operation id when one is already known (it is an unguessable local
  correlation id, not user input);
* a timestamp and schema marker.

It never reads ``sys.argv``, profiles, environment connection settings, or the
exception message. The log lives under the 0700-protected data directory and is
written 0600. Opt-in via ``--debug-log`` or ``VCENTER_AIOPS_DEBUG_LOG=1`` and
intended to be invoked only from the exit-5 path, so normal runs produce no
file at all.

Growth is bounded (M-6): once ``debug.log`` reaches the byte threshold
(``VCENTER_AIOPS_DEBUG_LOG_MAX_BYTES``, default 1 MiB, capped at 10 MiB) it is
rotated to a single ``debug.log.1`` backup before the next record, keeping total
disk use around two files.
"""
import json
import os
import stat
import traceback
from datetime import datetime, timezone

from .paths import data_home, ensure_private

_DEBUG_ENV = "VCENTER_AIOPS_DEBUG_LOG"
_MAX_BYTES_ENV = "VCENTER_AIOPS_DEBUG_LOG_MAX_BYTES"
# Frame fields that are safe: they name local code locations only. We never
# include f_locals/f_globals or the argument tuple.
_MAX_FRAMES = 50

# Bounded log growth (M-6): once the current log reaches this size it is rotated
# to a single debug.log.1 backup before the next record, so total disk use stays
# around two files. Override via the env var (positive bytes, capped at the max);
# an invalid/non-positive value falls back to the default.
_DEFAULT_MAX_BYTES = 1 * 1024 * 1024
_HARD_MAX_BYTES = 10 * 1024 * 1024


def debug_log_enabled(explicit=None):
    """Whether redacted diagnostics should be persisted.

    ``explicit`` reflects the CLI ``--debug-log`` flag. The environment variable
    accepts the usual truthy spellings; anything else (including unset) is off.
    """
    if explicit:
        return True
    return os.environ.get(_DEBUG_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _redacted_frames(exc):
    frames = traceback.extract_tb(exc.__traceback__)
    redacted = []
    for frame in frames[-_MAX_FRAMES:]:
        redacted.append({
            "file": os.path.basename(frame.filename),
            "function": frame.name,
            "line": frame.lineno,
        })
    return redacted


def _fault_type(exc):
    # Qualified module-qualified name for non-builtin types (e.g.
    # "pyVmomi.vim.fault.ManagedObjectNotFound"), bare name for builtins. Never
    # the message.
    cls = type(exc)
    module = getattr(cls, "__module__", "")
    name = getattr(cls, "__qualname__", cls.__name__)
    if module and module not in ("builtins", "exceptions"):
        return module + "." + name
    return name


def _max_bytes():
    """Resolve the rotation threshold from the env var, clamped to a safe range.

    Invalid / non-positive values fall back to the default so a misconfiguration
    can neither disable bounding nor force an impractically small file.
    """
    raw = os.environ.get(_MAX_BYTES_ENV, "").strip()
    if not raw:
        return _DEFAULT_MAX_BYTES
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_MAX_BYTES
    if value <= 0:
        return _DEFAULT_MAX_BYTES
    return min(value, _HARD_MAX_BYTES)


def _rotate_if_needed(log_path):
    """Rotate to a single ``debug.log.1`` once the current log crosses the
    threshold. Best-effort: any failure is swallowed by the caller so it can
    never mask the original fault or change the exit-5 result.
    """
    try:
        try:
            current = os.lstat(log_path)
        except FileNotFoundError:
            return
        # Never rename a pre-planted symlink/special file into the backup slot.
        if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
            raise OSError("refuse to rotate an unsafe debug-log target")
        if current.st_size < _max_bytes():
            return
        backup = log_path.with_name(log_path.name + ".1")
        os.replace(log_path, backup)  # atomically replace any prior backup
        if os.name == "posix":
            os.chmod(backup, stat.S_IRUSR | stat.S_IWUSR)  # 0600, owner only
    except OSError:
        pass


def _open_log_append(log_path):
    """Open ``debug.log`` for append without following a symlink (POSIX).

    Best-effort diagnostics must never be redirected through a planted link:
    open with O_NOFOLLOW and confirm on the descriptor a single-link regular
    file, tightening loose group/other bits to 0600. Non-POSIX keeps the
    historical open. Any OSError propagates to the caller's best-effort guard.
    """
    if os.name == "posix" and hasattr(os, "O_NOFOLLOW"):
        fd = os.open(log_path,
                     os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise OSError("debug log must be a single-link regular file")
            if info.st_mode & 0o077:
                os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)  # tighten to 0600
            return fd
        except BaseException:
            os.close(fd)
            raise
    return os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)


def record_internal_error(exc, *, operation_id=None, explicit=None):
    """Append one redacted internal-error record.

    Returns the log Path on success, or None when diagnostics are disabled. Any
    failure here must never mask the original error or alter the exit-5 result,
    so callers wrap this in a best-effort try/except.
    """
    if not debug_log_enabled(explicit):
        return None
    directory = data_home() / "logs"
    ensure_private(directory)
    log_path = directory / "debug.log"
    _rotate_if_needed(log_path)
    record = {
        "schema_version": "1",
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "event": "internal_error",
        "fault_type": _fault_type(exc),
        "frames": _redacted_frames(exc),
        "operation_id": operation_id,
    }
    # Append-only so concurrent/process-separated CLI runs do not truncate prior
    # evidence; a single JSON object per line keeps records machine-parseable.
    # The descriptor is opened without following a symlink and written via an
    # os.fdopen wrapper so no separate chmod() follows a possibly-swapped path.
    fd = _open_log_append(log_path)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    # Mode is enforced on the opened descriptor (0600 at creation, fchmod when
    # tightening), so no path-based chmod that could follow a later swapped link.
    return log_path
