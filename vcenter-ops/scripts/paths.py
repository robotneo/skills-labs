"""
Module: scripts.paths

Centralizes filesystem constants shared across the Skill. Historically each
module recomputed ``Path(__file__).resolve().parent.parent`` to locate the
Skill root; that pattern is now consolidated here so any layout change flows
through a single file.

Exports
-------
- SKILL_DIR: absolute path of the Skill root (folder containing ``SKILL.md``).
- SCRIPTS_DIR: ``SKILL_DIR / "scripts"``.
- CONFIG_FILE: ``SKILL_DIR / "config.yaml"``.
- ENV_FILE: ``SKILL_DIR / ".env"``.
- DATA_DIR / LOGS_DIR / PLANS_DIR / PRESETS_DIR / REFERENCES_DIR: common
  subdirectories, created on demand via :func:`ensure_dirs`.

Side effects
------------
No I/O at import time. Call :func:`ensure_dirs` explicitly if you need the
writable directories to exist.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Root anchors
# ---------------------------------------------------------------------------

# ``scripts/paths.py`` -> ``scripts/`` -> Skill root
SCRIPTS_DIR: Path = Path(__file__).resolve().parent
SKILL_DIR: Path = SCRIPTS_DIR.parent

# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
CONFIG_FILE: Path = SKILL_DIR / "config.yaml"
ENV_FILE: Path = SKILL_DIR / ".env"

# ---------------------------------------------------------------------------
# Writable directories (created lazily)
# ---------------------------------------------------------------------------
DATA_DIR: Path = SKILL_DIR / "data"
LOGS_DIR: Path = SKILL_DIR / "logs"
PLANS_DIR: Path = SKILL_DIR / "plans"
PRESETS_DIR: Path = SKILL_DIR / "presets"
REFERENCES_DIR: Path = SKILL_DIR / "references"

# Common subdirectories under DATA_DIR
AUDIT_DIR: Path = DATA_DIR / "audit"
TASKS_DIR: Path = DATA_DIR / "tasks"
LOCKS_DIR: Path = DATA_DIR / "locks"
SECRETS_DIR: Path = DATA_DIR / "secrets"
CACHE_DIR: Path = DATA_DIR / "cache"


def ensure_dirs(*extra: Path) -> None:
    """Create the writable directories used by the Skill if they do not exist.

    Args:
        *extra: Additional paths that must exist. Each is created with
            ``parents=True, exist_ok=True``.
    """
    for directory in (DATA_DIR, LOGS_DIR, PLANS_DIR, AUDIT_DIR,
                       TASKS_DIR, LOCKS_DIR, SECRETS_DIR, CACHE_DIR, *extra):
        directory.mkdir(parents=True, exist_ok=True)
