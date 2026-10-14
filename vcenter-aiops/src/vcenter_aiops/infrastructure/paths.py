import os
import sys
from pathlib import Path


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
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
