#!/usr/bin/env python3
"""
VM TTL (Time-To-Live) 管理器。
支持设置/取消/列出 VM 的自动清理时间。
TTL 数据存储在: {SKILL_DIR}/data/ttl.json（相对路径）
"""

import json
import time
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional, List

SKILL_DIR = Path(__file__).resolve().parent.parent
TTL_DIR = SKILL_DIR / "data"
TTL_FILE = TTL_DIR / "ttl.json"

logger = logging.getLogger(__name__)


def _ensure_dir():
    TTL_DIR.mkdir(parents=True, exist_ok=True)


def _load_ttls() -> Dict[str, Dict]:
    """加载所有 TTL 记录。"""
    _ensure_dir()
    if not TTL_FILE.exists():
        return {}
    with open(TTL_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_ttls(ttls: Dict):
    """保存 TTL 记录。"""
    _ensure_dir()
    with open(TTL_FILE, "w", encoding="utf-8") as f:
        json.dump(ttls, f, ensure_ascii=False, indent=2)


def set_ttl(vm_name: str, minutes: int, creator: str = "agent") -> Dict:
    """设置 VM 的 TTL（自动清理时间）。"""
    ttls = _load_ttls()
    now = time.time()
    expire_at = now + minutes * 60

    ttls[vm_name] = {
        "set_at": datetime.now(timezone.utc).isoformat(),
        "expire_at": datetime.fromtimestamp(expire_at, tz=timezone.utc).isoformat(),
        "expire_timestamp": expire_at,
        "ttl_minutes": minutes,
        "creator": creator,
    }
    _save_ttls(ttls)
    logger.info(f"TTL set: [{vm_name}] will expire in {minutes} minutes")
    return ttls[vm_name]


def cancel_ttl(vm_name: str) -> bool:
    """取消 VM 的 TTL。"""
    ttls = _load_ttls()
    if vm_name in ttls:
        del ttls[vm_name]
        _save_ttls(ttls)
        logger.info(f"TTL cancelled: [{vm_name}]")
        return True
    return False


def list_ttls() -> List[Dict]:
    """列出所有 TTL 记录。"""
    ttls = _load_ttls()
    now = time.time()
    result = []
    for vm_name, info in ttls.items():
        remaining = max(0, info["expire_timestamp"] - now)
        result.append({
            "vm_name": vm_name,
            "set_at": info["set_at"],
            "expire_at": info["expire_at"],
            "ttl_minutes": info["ttl_minutes"],
            "remaining_minutes": round(remaining / 60, 1),
            "is_expired": remaining <= 0,
            "creator": info["creator"],
        })
    return result


def get_expired() -> List[str]:
    """获取所有已过期但未清理的 VM 列表。"""
    return [r["vm_name"] for r in list_ttls() if r["is_expired"]]


def cleanup_expired(executor) -> List[Dict]:
    """
    清理所有已过期的 VM。
    executor 是 VCenterExecutor 实例。
    返回清理结果列表。
    """
    expired = get_expired()
    results = []
    for vm_name in expired:
        try:
            msg = executor.remove_vm(vm_name)
            results.append({"vm": vm_name, "status": "deleted", "message": msg})
            # 清理 TTL 记录
            cancel_ttl(vm_name)
            logger.info(f"TTL cleanup: [{vm_name}] deleted")
        except Exception as e:
            results.append({"vm": vm_name, "status": "failed", "message": str(e)})
            logger.error(f"TTL cleanup failed: [{vm_name}]: {e}")
    return results
