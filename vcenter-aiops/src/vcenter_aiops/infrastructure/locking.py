"""OS-released local-file lock; no stale PID ownership or import-time IO."""
from contextlib import contextmanager
import os
import stat

from .paths import ensure_private
from ..domain.models import fail


def open_private(path, flags, *, dir_fd=None):
    """POSIX private regular file, checked on the opened fd, never a followed link."""
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW"):
        fail("secret_storage_unsupported", "此平台尚无安全密钥库存储后端", 3)
    fd = os.open(path, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=dir_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            fail("secret_storage_unsafe", "密钥库文件必须是当前用户私有的普通文件且无其他硬链接", 3)
        return fd
    except BaseException:
        os.close(fd)
        raise


def open_lock(path):
    """Open the downgrade lock without following a symlink.

    The lock lives in a 0700 user-private directory, but aligning it with the
    secure path costs nothing: on POSIX refuse a pre-planted symlink and verify,
    on the opened descriptor, that the target is a single-link regular file.
    Non-POSIX keeps the historical open (Windows uses a separate locking API).
    """
    if os.name == "posix" and hasattr(os, "O_NOFOLLOW"):
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                fail("lock_target_unsafe", "锁文件必须是单一硬链接的普通文件，拒绝符号链接", 3)
            return fd
        except BaseException:
            os.close(fd)
            raise
    return os.open(path, os.O_CREAT | os.O_RDWR, 0o600)


@contextmanager
def exclusive(path, blocking=True, *, secure=False, dir_fd=None):
    if dir_fd is None:
        ensure_private(path.parent)
    fd = (open_private(path, os.O_CREAT | os.O_RDWR, dir_fd=dir_fd) if secure
          else open_lock(path))
    with os.fdopen(fd, "r+b") as handle:
        if os.name == "nt":
            import msvcrt
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
            except OSError:
                if blocking:
                    raise
                yield False
                return
            try:
                yield True
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError:
                yield False
                return
            try:
                if secure:
                    try:
                        linked = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
                    except FileNotFoundError:
                        fail("secret_storage_unsafe", "密钥库锁在等待期间被替换", 3)
                    opened = os.fstat(handle.fileno())
                    if (linked.st_dev, linked.st_ino) != (opened.st_dev, opened.st_ino) or opened.st_nlink != 1:
                        fail("secret_storage_unsafe", "密钥库锁在等待期间被替换", 3)
                yield True
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
