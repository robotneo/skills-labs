"""
Module: scripts.approval_policy
Description: 审批策略引擎。根据操作类型+目标+成本自动路由审批级别，
             支持多人会签、自动过期、策略热加载。
Author: 运枢
Date: 2026-05-22
Version: 1.3.0

设计要点：
- 策略定义在 config.yaml.approval_policy 节点
- 三级路由：auto_approve / single_approver / multi_approver（会签）
- 路由因子：action + target_pattern + resource_cost
- 复用已有 approval_manager 的存储，本模块只做策略决策
- 策略变更只需改 config.yaml，无需重启
"""

import re
import json
import time
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = SKILL_DIR / "config.yaml"
POLICY_FILE = SKILL_DIR / "data" / "approval_policies.json"


# ============================================================
# 异常
# ============================================================

class ApprovalRequired(Exception):
    """操作需要审批。"""
    def __init__(self, action: str, target: str, level: str, approvers: List[str]):
        self.action = action
        self.target = target
        self.level = level
        self.approvers = approvers
        super().__init__(
            f"📋 操作 [{action}] → [{target}] 需要审批（级别={level}，"
            f"审批人={','.join(approvers) or '(待分配)'}）"
        )


# ============================================================
# 默认策略
# ============================================================

DEFAULT_POLICIES: List[Dict[str, Any]] = [
    {
        "name": "低风险操作自动通过",
        "action": ["list_all", "get_vm", "history", "preset", "audit_query",
                    "export", "events", "quota", "ip_pool", "audit_report"],
        "target_pattern": ".*",
        "level": "auto_approve",
        "approvers": [],
    },
    {
        "name": "常规运维需单人审批",
        "action": ["clone_vm", "batch_clone", "snapshot", "reconfigure",
                    "power_vm", "migrate", "ttl"],
        "target_pattern": "^(dev-|test-|staging-|tmp-|uat-|demo-).*$",
        "level": "single_approver",
        "approvers": ["ops-lead"],
    },
    {
        "name": "生产/关键目标需会签",
        "action": ["clone_vm", "batch_clone", "power_vm", "reconfigure", "migrate"],
        "target_pattern": "^(prod-|db-|mysql|redis|master|primary|nginx|gateway|core).*$",
        "level": "multi_approver",
        "approvers": ["ops-lead", "arch-lead"],
        "min_approvals": 2,
    },
    {
        "name": "删除必须会签",
        "action": ["delete_vm"],
        "target_pattern": ".*",
        "level": "multi_approver",
        "approvers": ["ops-lead", "arch-lead", "security-lead"],
        "min_approvals": 2,
    },
]


# ============================================================
# 配置加载
# ============================================================

def load_policies() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "enabled": False,
        "policies": list(DEFAULT_POLICIES),
        "default_level": "single_approver",
        "default_approvers": ["ops-lead"],
        "expire_minutes": 1440,  # 审批 24h 过期
    }
    if not (HAS_YAML and CONFIG_FILE.exists()):
        return cfg
    try:
        all_cfg = yaml.safe_load(CONFIG_FILE.read_text()) or {}
        ap = all_cfg.get("approval_policy") or {}
        for k, v in ap.items():
            if k == "policies" and isinstance(v, list):
                cfg["policies"] = DEFAULT_POLICIES + v
            else:
                cfg[k] = v
    except Exception as e:
        logger.warning(f"加载审批策略失败: {e}")
    return cfg


# ============================================================
# 策略路由
# ============================================================

def route_approval(
    action: str,
    target: str = "",
    resource_cost: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    根据策略路由审批级别。

    :return: {
        "level": "auto_approve" / "single_approver" / "multi_approver",
        "approvers": [...],
        "min_approvals": int,
        "matched_policy": str,
    }
    """
    cfg = load_policies()
    if not cfg.get("enabled", False):
        return {"level": "auto_approve", "approvers": [], "min_approvals": 0,
                "matched_policy": "(RBAC未启用)"}

    for policy in cfg.get("policies", []):
        actions = policy.get("action") or []
        # action 匹配
        if action not in actions and "*" not in actions:
            continue
        # target_pattern 匹配
        pattern = policy.get("target_pattern", ".*")
        try:
            if re.match(pattern, target or ""):
                return {
                    "level": policy.get("level", cfg.get("default_level")),
                    "approvers": policy.get("approvers", cfg.get("default_approvers")),
                    "min_approvals": policy.get("min_approvals", 1),
                    "matched_policy": policy.get("name", ""),
                }
        except re.error:
            continue

    # 无匹配走默认
    return {
        "level": cfg.get("default_level", "single_approver"),
        "approvers": cfg.get("default_approvers", []),
        "min_approvals": 1,
        "matched_policy": "(默认策略)",
    }


def check_approval_needed(
    action: str,
    target: str = "",
    resource_cost: Optional[Dict[str, Any]] = None,
) -> Optional[ApprovalRequired]:
    """
    检查操作是否需要审批。

    - auto_approve → 返回 None（直接放行）
    - single/multi → 返回 ApprovalRequired 异常
    """
    result = route_approval(action, target, resource_cost)
    if result["level"] == "auto_approve":
        return None
    return ApprovalRequired(
        action=action,
        target=target,
        level=result["level"],
        approvers=result["approvers"],
    )


def validate_approval(
    action: str,
    target: str = "",
) -> None:
    """
    handler 调用入口：检查是否需要审批，需要则抛异常。
    已审批通过的（通过 approval_manager）不在此拦截。
    """
    cfg = load_policies()
    if not cfg.get("enabled", False):
        return

    needed = check_approval_needed(action, target)
    if needed:
        raise needed


# ============================================================
# 渲染
# ============================================================

def format_policies_table(policies: Optional[List[Dict[str, Any]]] = None) -> str:
    if policies is None:
        policies = load_policies().get("policies", [])
    lines = ["| 策略名 | 级别 | 操作 | 目标模式 | 审批人 |", "|--------|------|------|----------|--------|"]
    for p in policies:
        acts = ", ".join(p.get("action", []))[:30]
        lines.append(
            f"| {p.get('name','')[:20]} | {p.get('level','')} | "
            f"{acts} | {p.get('target_pattern','.*')[:20]} | "
            f"{','.join(p.get('approvers',[]))} |"
        )
    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="审批策略引擎")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出所有策略")

    p_route = sub.add_parser("route", help="模拟路由")
    p_route.add_argument("action")
    p_route.add_argument("--target", default="")

    sub.add_parser("config", help="查看当前配置")

    args = parser.parse_args()

    if args.cmd == "list":
        print(format_policies_table())
    elif args.cmd == "route":
        result = route_approval(args.action, args.target)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.cmd == "config":
        print(json.dumps(load_policies(), ensure_ascii=False, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
