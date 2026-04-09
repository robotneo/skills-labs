#!/usr/bin/env python3
"""
操作审计日志模块。
所有 vCenter 操作（含用户拒绝的）记录到 JSONL 文件。
"""

import json
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any

SKILL_DIR = Path(__file__).resolve().parent.parent
AUDIT_DIR = SKILL_DIR / "logs"
AUDIT_FILE = AUDIT_DIR / "audit.log"

logger = logging.getLogger(__name__)


def _ensure_dir():
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)


def record(
    action: str,                    # 操作类型: clone_vm, power_vm, delete_vm, snapshot, reconfigure 等
    target: str,                    # 目标 VM 名称
    status: str,                    # success / failed / rejected / dry_run
    operator: str = "agent",        # 操作者
    details: Optional[Dict] = None, # 额外详情（参数、前后状态等）
    error: Optional[str] = None,    # 错误信息
):
    """记录一条审计日志到 JSONL 文件。"""
    _ensure_dir()
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "target": target,
        "status": status,
        "operator": operator,
        "details": details or {},
    }
    if error:
        entry["error"] = error

    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with open(AUDIT_FILE, "a", encoding="utf-8") as f:
        f.write(line)
    logger.info(f"Audit: [{status}] {action} -> {target}")


def query(action: Optional[str] = None, target: Optional[str] = None, limit: int = 50) -> list:
    """查询审计日志。"""
    if not AUDIT_FILE.exists():
        return []
    results = []
    with open(AUDIT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                if action and entry.get("action") != action:
                    continue
                if target and entry.get("target") != target:
                    continue
                results.append(entry)
            except json.JSONDecodeError:
                continue
    return results[-limit:]
