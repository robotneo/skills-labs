"""Build a reproducible runtime ZIP; the bundled notification component stays intact."""
import argparse
import hashlib
import json
from pathlib import Path
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'wifi-health-detector'


def package(destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = []
    for path in sorted(SKILL.rglob('*')):
        relative = path.relative_to(SKILL)
        if any(part.startswith('.') or part in ('tests', '__pycache__') for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError('Symlinks are not allowed in releases: ' + str(relative))
        if not path.is_file() or path.name == 'README.md' or path.suffix in ('.pyc', '.pyo'):
            continue
        if path.suffix not in ('.md', '.py', '.js', '.cjs', '.json', '.yaml', '.sh', '.ps1', '.bat'):
            raise ValueError('Unexpected release file: ' + str(relative))
        files.append(path)
    with zipfile.ZipFile(str(destination), 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            entry = zipfile.ZipInfo('wifi-health-detector/' + path.relative_to(SKILL).as_posix(), (2026, 1, 1, 0, 0, 0))
            entry.create_system = 3
            entry.external_attr = (stat.S_IFREG | (0o755 if path.suffix == '.sh' else 0o644)) << 16
            entry.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(entry, path.read_bytes())
    return len(files), hashlib.sha256(destination.read_bytes()).hexdigest()


if __name__ == '__main__':
    version = json.loads((SKILL / 'manifest.json').read_text())['version']
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / ('wifi-health-detector-v' + version + '.zip'))
    args = parser.parse_args()
    count, digest = package(args.output)
    print(str(args.output))
    print('{} files; SHA256 {}'.format(count, digest))
