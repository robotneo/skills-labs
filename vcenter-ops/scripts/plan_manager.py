#!/usr/bin/env python3
"""
操作计划管理器。
支持创建、审查、执行、回滚多步骤操作计划。

计划文件存储在: {SKILL_DIR}/plans/（相对路径）
自动清理：成功后删除，失败后 24 小时自动清理。
"""

import json
import os
import time
import uuid
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

SKILL_DIR = Path(__file__).resolve().parent.parent
PLAN_DIR = SKILL_DIR / "plans"
PLAN_TTL_SECONDS = 24 * 3600  # 24 小时

logger = logging.getLogger(__name__)


def _ensure_dir():
    PLAN_DIR.mkdir(parents=True, exist_ok=True)


def create_plan(steps: List[Dict], description: str = "") -> Dict:
    """
    创建操作计划。
    每个步骤格式: {"action": str, "params": dict, "reversible": bool, "rollback": str}
    """
    _ensure_dir()
    plan_id = str(uuid.uuid4())[:8]
    plan = {
        "plan_id": plan_id,
        "description": description,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "pending",  # pending / executing / completed / failed / rolled_back
        "steps": steps,
        "results": [],
        "current_step": 0,
    }

    plan_file = PLAN_DIR / f"{plan_id}.json"
    with open(plan_file, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)

    logger.info(f"Plan [{plan_id}] created with {len(steps)} steps")
    return plan


def get_plan(plan_id: str) -> Optional[Dict]:
    """获取计划详情。"""
    plan_file = PLAN_DIR / f"{plan_id}.json"
    if not plan_file.exists():
        return None
    with open(plan_file, "r", encoding="utf-8") as f:
        return json.load(f)


def list_plans(status: Optional[str] = None) -> List[Dict]:
    """列出所有计划。"""
    _ensure_dir()
    plans = []
    for f in sorted(PLAN_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                plan = json.load(fp)
            if status and plan.get("status") != status:
                continue
            plans.append(plan)
        except Exception:
            continue
    return plans


def execute_plan(plan_id: str, executor) -> Dict:
    """
    执行计划。按顺序执行每个步骤，失败时停止。
    executor 是 VCenterExecutor 实例，用于实际执行操作。

    步骤支持的 action: power_vm, reconfigure, snapshot, migrate
    """
    plan = get_plan(plan_id)
    if not plan:
        raise ValueError(f"计划 [{plan_id}] 不存在")
    if plan["status"] not in ("pending", "failed"):
        raise ValueError(f"计划 [{plan_id}] 状态为 [{plan['status']}]，无法执行")

    plan["status"] = "executing"
    plan["results"] = []
    plan["current_step"] = 0
    _save_plan(plan)

    for i, step in enumerate(plan["steps"]):
        plan["current_step"] = i + 1
        action = step["action"]
        params = step.get("params", {})
        target = params.get("hostname", params.get("vm_name", "(unknown)"))

        step_result = {
            "step": i + 1,
            "action": action,
            "target": target,
            "status": "pending",
            "message": "",
        }

        try:
            msg = _dispatch_action(executor, action, params)
            step_result["status"] = "success"
            step_result["message"] = msg
            logger.info(f"Plan [{plan_id}] Step {i+1}: {action} -> {target} SUCCESS")
        except Exception as e:
            step_result["status"] = "failed"
            step_result["message"] = str(e)
            plan["results"].append(step_result)
            plan["status"] = "failed"
            plan["current_step"] = i + 1
            _save_plan(plan)
            logger.error(f"Plan [{plan_id}] Step {i+1}: {action} -> {target} FAILED: {e}")
            return plan

        plan["results"].append(step_result)
        _save_plan(plan)

    plan["status"] = "completed"
    _save_plan(plan)
    logger.info(f"Plan [{plan_id}] completed successfully")
    return plan


def rollback_plan(plan_id: str, executor) -> Dict:
    """
    回滚计划。逆序执行已成功的可逆步骤。
    不可逆步骤（如 delete_vm）会跳过并记录警告。
    """
    plan = get_plan(plan_id)
    if not plan:
        raise ValueError(f"计划 [{plan_id}] 不存在")

    # 只回滚已成功且可逆的步骤
    successful = [r for r in plan["results"] if r["status"] == "success"]
    if not successful:
        plan["status"] = "rolled_back"
        _save_plan(plan)
        return plan

    plan["status"] = "rolling_back"
    _save_plan(plan)

    # 逆序回滚
    rolled_back = 0
    skipped = 0
    for result in reversed(successful):
        step_idx = result["step"] - 1
        step = plan["steps"][step_idx]
        action = step["action"]
        rollback = step.get("rollback", "")

        if not step.get("reversible", False) or not rollback:
            logger.warning(f"Plan [{plan_id}] Step {result['step']}: {action} 不可逆，跳过回滚")
            skipped += 1
            continue

        try:
            msg = _dispatch_action(executor, rollback, step.get("rollback_params", step.get("params", {})))
            rolled_back += 1
            logger.info(f"Plan [{plan_id}] Rollback Step {result['step']}: {rollback} SUCCESS")
        except Exception as e:
            logger.error(f"Plan [{plan_id}] Rollback Step {result['step']}: FAILED: {e}")

    plan["status"] = "rolled_back"
    _save_plan(plan)
    logger.info(f"Plan [{plan_id}] rolled back: {rolled_back} succeeded, {skipped} skipped")
    return plan


def delete_plan(plan_id: str) -> bool:
    """删除计划文件。"""
    plan_file = PLAN_DIR / f"{plan_id}.json"
    if plan_file.exists():
        plan_file.unlink()
        return True
    return False


def cleanup_expired():
    """清理超过 24 小时的计划文件。"""
    _ensure_dir()
    now = time.time()
    cleaned = 0
    for f in PLAN_DIR.glob("*.json"):
        if now - f.stat().st_mtime > PLAN_TTL_SECONDS:
            f.unlink()
            cleaned += 1
    if cleaned:
        logger.info(f"Cleaned {cleaned} expired plan(s)")
    return cleaned


def _save_plan(plan: Dict):
    """保存计划到文件。"""
    plan_file = PLAN_DIR / f"{plan['plan_id']}.json"
    with open(plan_file, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)


def _dispatch_action(executor, action: str, params: Dict) -> str:
    """根据 action 分发到 executor 的对应方法。"""
    if action == "power_vm":
        return executor.set_vm_power(params["hostname"], params["state"])
    elif action == "reconfigure":
        return executor.reconfigure_vm(
            params["hostname"],
            cpus=params.get("cpu"),
            memory_gb=params.get("memory"),
            disk_gb=params.get("disk"),
        )
    elif action == "snapshot_create":
        return executor.create_snapshot(params["hostname"], params.get("snap_name", f"snap-{params['hostname']}"))
    elif action == "snapshot_delete":
        return executor.remove_snapshot(params["hostname"], params["snap_name"])
    elif action == "migrate":
        return executor.migrate_vm(params["hostname"], params["target_host"])
    else:
        raise ValueError(f"Plan 不支持的 action: {action}")
