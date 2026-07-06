"""
Module: scripts.config_loader

Loading, saving and resolving ``config.yaml`` into a strongly-typed
``VCenterConnection`` instance.

Password precedence (highest first)
-----------------------------------
1. ``--pwd`` command-line argument.
2. ``vcenter.password`` in ``config.yaml`` (plaintext, discouraged).
3. ``secret_manager`` (Fernet-encrypted store) via ``vcenter.password_ref``.
4. ``.env`` file loaded through ``python-dotenv`` (env var name in
   ``vcenter.password_ref``).
5. Process environment variable named by ``vcenter.password_ref``.

Exports
-------
- :class:`VCenterConnection`
- :func:`load_config`
- :func:`save_config`
- :func:`resolve_connection`
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

import yaml

from scripts import secret_manager
from scripts.paths import CONFIG_FILE, ENV_FILE

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VCenterConnection:
    """Immutable container for a resolved vCenter connection tuple."""

    host: str
    user: str
    password: str
    port: int = 443

    def as_tuple(self) -> tuple:
        """Return the connection as a 4-tuple ``(host, user, password, port)``.

        Kept for backwards compatibility with legacy call sites still using
        positional arguments (e.g. ``VCenterClient(host, user, pwd, port)``).
        """
        return self.host, self.user, self.password, self.port


# ---------------------------------------------------------------------------
# YAML load / save
# ---------------------------------------------------------------------------

def load_config() -> Dict[str, Any]:
    """Read ``config.yaml`` and return its content as a dictionary.

    Missing or malformed files are logged and mapped to an empty dictionary
    so callers can degrade gracefully.
    """
    if not CONFIG_FILE.exists():
        logger.warning("配置文件不存在: %s", CONFIG_FILE)
        return {}

    try:
        with CONFIG_FILE.open("r", encoding="utf-8") as fp:
            data = yaml.safe_load(fp) or {}
        logger.info("已加载配置文件: %s", CONFIG_FILE)
        return data
    except Exception as error:  # pragma: no cover - defensive
        logger.warning("读取 config.yaml 失败: %s", error)
        return {}


def save_config(cfg: Dict[str, Any]) -> bool:
    """Persist ``cfg`` back to ``config.yaml``.

    Returns ``True`` on success and logs the exception on failure.
    """
    try:
        with CONFIG_FILE.open("w", encoding="utf-8") as fp:
            yaml.dump(cfg, fp, default_flow_style=False, allow_unicode=True)
        logger.info("配置已保存到: %s", CONFIG_FILE)
        return True
    except Exception as error:
        logger.error("保存 config.yaml 失败: %s", error)
        return False


# ---------------------------------------------------------------------------
# Password resolution
# ---------------------------------------------------------------------------

def _load_env_file() -> None:
    """Load ``.env`` file into ``os.environ`` if present.

    Uses ``python-dotenv`` when available. Import failures are ignored so the
    Skill still works without the optional dependency.
    """
    if not ENV_FILE.exists():
        return
    try:
        from dotenv import load_dotenv  # pylint: disable=import-outside-toplevel

        load_dotenv(ENV_FILE)
    except ImportError:  # pragma: no cover - optional dep
        logger.debug("python-dotenv 未安装，跳过 .env 自动加载")


def _resolve_password(cli_pwd: Optional[str], vc_cfg: Dict[str, Any]) -> str:
    """Return the vCenter password following the module-level precedence table."""
    if cli_pwd:
        return cli_pwd

    plaintext = vc_cfg.get("password", "")
    if plaintext:
        return plaintext

    ref = vc_cfg.get("password_ref", "")
    if not ref:
        return ""

    # 1) encrypted secret store
    try:
        encrypted = secret_manager.resolve_password(ref)
        if encrypted:
            logger.debug("密码从 secret_manager 加载 (%s)", ref)
            return encrypted
    except Exception as error:  # pragma: no cover - defensive
        logger.debug("secret_manager 读取失败，回退环境变量: %s", error)

    # 2) environment variable (loading .env lazily first)
    _load_env_file()
    return os.environ.get(ref, "")


def resolve_connection(args, cfg: Dict[str, Any]) -> VCenterConnection:
    """Merge CLI arguments and ``config.yaml`` into a :class:`VCenterConnection`.

    Args:
        args: An ``argparse.Namespace`` exposing ``host / user / pwd / port``.
        cfg: Parsed ``config.yaml`` dictionary (see :func:`load_config`).

    Raises:
        ValueError: When ``host``, ``user`` or ``password`` cannot be resolved.
    """
    vc_cfg = cfg.get("vcenter", {})

    host = args.host or vc_cfg.get("host", "")
    user = args.user or vc_cfg.get("user", "")
    port = args.port or vc_cfg.get("port", 443)
    password = _resolve_password(args.pwd, vc_cfg)

    missing = [name for name, value in
               (("host", host), ("user", user), ("password", password))
               if not value]
    if missing:
        raise ValueError(
            "vCenter 连接信息缺失: "
            f"{', '.join(missing)}。请检查 .env 文件或 config.yaml。"
        )

    return VCenterConnection(host=host, user=user, password=password, port=port)
