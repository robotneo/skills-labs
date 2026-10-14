"""Fail release verification when a wheel contains stale or mismatched Python modules."""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile


def verify(wheel, source):
    source = Path(source)
    expected = {path.relative_to(source).as_posix(): path.read_bytes() for path in source.rglob("*.py") if "__pycache__" not in path.parts}
    with ZipFile(wheel) as archive:
        names = [name for name in archive.namelist() if name.endswith(".py")]
        if len(names) != len(set(names)):
            raise ValueError("安装包含重复 Python 模块")
        extra, missing = sorted(set(names) - expected.keys()), sorted(expected.keys() - set(names))
        changed = sorted(name for name in set(names) & expected.keys() if archive.read(name) != expected[name])
        if extra or missing or changed:
            raise ValueError(json.dumps({"unexpected": extra, "missing": missing, "changed": changed}, ensure_ascii=False))
    return {"verified": True, "modules": len(expected), "wheel": str(Path(wheel).absolute())}


def main():
    parser = argparse.ArgumentParser(description="核对 wheel 内 Python 模块与当前源码完全一致")
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1] / "src")
    args = parser.parse_args()
    try:
        result = verify(args.wheel, args.source)
    except (OSError, ValueError) as exc:
        parser.exit(1, str(exc) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
