#!/usr/bin/env python3
"""
操作审批管理器。
高危操作（删除/批量/迁移）需要审批后才能执行。
审批数据存储在: {SKILL_DIR}/data/approvals.json（相对路径）
"""

import json
import time
import uuid
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Optional, List

SKILL_DIR = Path(__file__).resolve().parent.parent
APPROVAL_DIR = SKILL_DIR / "data"
APPROVAL_FILE = APPROVAL_DIR / "approvals.json"
APPROVAL_TTL_SECONDS = 24 * 3600  # 24 小时未审批自动过期

logger = logging.getLogger(__name__)


def _ensure_dir():
    APPROVAL_DIR.mkdir(parents=True, exist_ok=True)


def _load_approvals() -> Dict:
    _ensure_dir()
    if not APPROVAL_FILE.exists():
        return {}
    with open(APPROVAL_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_approvals(approvals: Dict):
    _ensure_dir()
    with open(APPROVAL_FILE, "w", encoding="utf-8") as f:
        json.dump(approvals, f, ensure_ascii=False, indent=2)


def create_request(action: str, target: str, params: dict, requested_by: str = "agent", timeout_minutes: int = 60) -> Dict:
    """
    创建审批请求。
    返回包含 approval_id 的审批记录。
    """
    approvals = _load_approvals()
    approval_id = str(uuid.uuid4())[:8]
    now = time.time()

    record = {
        "approval_id": approval_id,
        "action": action,
        "target": target,
        "params": params,
        "requested_by": requested_by,
        "status": "pending",  # pending / approved / rejected / expired / cancelled
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expire_at": datetime.fromtimestamp(now + timeout_minutes * 60, tz=timezone.utc).isoformat(),
        "expire_timestamp": now + timeout_minutes * 60,
        "resolved_at": None,
        "resolved_by": None,
        "comment": "",
    }

    approvals[approval_id] = record
    _save_approvals(approvals)
    logger.info(f"Approval [{approval_id}] created: {action} -> {target}")
    return record


def approve(approval_id: str, approved_by: str = "admin", comment: str = "") -> Optional[Dict]:
    """审批通过。"""
    approvals = _load_approvals()
    record = approvals.get(approval_id)
    if not record:
        return None

    if record["status"] != "pending":
        raise ValueError(f"审批 [{approval_id}] 状态为 [{record['status']}]，无法审批")

    # 检查是否过期
    if time.time() > record["expire_timestamp"]:
        record["status"] = "expired"
        _save_approvals(approvals)
        raise ValueError(f"审批 [{approval_id}] 已过期")

    record["status"] = "approved"
    record["resolved_at"] = datetime.now(timezone.utc).isoformat()
    record["resolved_by"] = approved_by
    record["comment"] = comment
    _save_approvals(approvals)
    logger.info(f"Approval [{approval_id}] approved by {approved_by}")
    return record


def reject(approval_id: str, rejected_by: str = "admin", comment: str = "") -> Optional[Dict]:
    """审批拒绝。"""
    approvals = _load_approvals()
    record = approvals.get(approval_id)
    if not record:
        return None

    if record["status"] != "pending":
        raise ValueError(f"审批 [{approval_id}] 状态为 [{record['status']}]，无法审批")

    record["status"] = "rejected"
    record["resolved_at"] = datetime.now(timezone.utc).isoformat()
    record["resolved_by"] = rejected_by
    record["comment"] = comment
    _save_approvals(approvals)
    logger.info(f"Approval [{approval_id}] rejected by {rejected_by}")
    return record


def get_request(approval_id: str) -> Optional[Dict]:
    """获取审批详情。"""
    approvals = _load_approvals()
    return approvals.get(approval_id)


def list_requests(status: Optional[str] = None) -> List[Dict]:
    """列出所有审批请求。"""
    approvals = _load_approvals()
    now = time.time()
    results = []

    for approval_id, record in approvals.items():
        # 自动过期检查
        if record["status"] == "pending" and now > record["expire_timestamp"]:
            record["status"] = "expired"

        if status and record["status"] != status:
            continue
        results.append(record)

    _save_approvals(approvals)  # 保存可能的过期状态更新
    results.sort(key=lambda x: x["created_at"], reverse=True)
    return results


def cancel_request(approval_id: str) -> bool:
    """取消审批请求。"""
    approvals = _load_approvals()
    record = approvals.get(approval_id)
    if not record:
        return False
    if record["status"] != "pending":
        return False
    record["status"] = "cancelled"
    record["resolved_at"] = datetime.now(timezone.utc).isoformat()
    _save_approvals(approvals)
    return True


def cleanup_expired():
    """清理已过期/已处理超过 24 小时的审批记录。"""
    approvals = _load_approvals()
    now = time.time()
    to_delete = []

    for approval_id, record in approvals.items():
        # 过期超过 24 小时的删除
        if record["status"] in ("expired", "rejected", "cancelled", "approved"):
            resolved = record.get("resolved_at", record["created_at"])
            if resolved:
                from datetime import datetime as dt
                resolved_ts = dt.fromisoformat(resolved).timestamp()
                if now - resolved_ts > APPROVAL_TTL_SECONDS:
                    to_delete.append(approval_id)

    for approval_id in to_delete:
        del approvals[approval_id]

    if to_delete:
        _save_approvals(approvals)
        logger.info(f"Cleaned {len(to_delete)} old approval(s)")

    return len(to_delete)
