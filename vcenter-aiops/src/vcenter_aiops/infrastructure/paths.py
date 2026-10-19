import os
import stat
import sys
from pathlib import Path

from ..domain.models import fail


def data_home(*, preserve_links=False) -> Path:
    override = os.environ.get("VCENTER_AIOPS_HOME")
    if override:
        path = Path(override).expanduser()
        return path.absolute() if preserve_links else path.resolve()
    if sys.platform == "win32":
        root = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return root / "vcenter-aiops"


def ensure_private(path: Path):
    # mode= only applies to freshly created leaves. An existing directory left
    # world/group-accessible (or pre-created with loose umask) must be tightened,
    # otherwise the 0o600 files inside still sit in a traversable folder. Only
    # the leaf is hardened; ancestor directories are left untouched.
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix":
        info = os.lstat(path)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            fail("data_directory_invalid", "数据目录不能是符号链接或非目录", 3)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            os.chmod(path, 0o700)
