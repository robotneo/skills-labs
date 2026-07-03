"""
Module: scripts.change_window
Description: 变更窗口管理。在指定时间段允许/禁止变更操作（如工作日 9-18 允许、夜间禁止）。
Author: 运枢
Date: 2026-05-22
Version: 1.3.0

设计要点：
- 配置位于 config.yaml.change_window
- 支持 allow_windows / block_windows / blackout_dates 三种规则
- 命中 block 强制拒绝；命中 blackout 强制拒绝
- 白名单用户/操作可绕过
- 提供 is_change_allowed / validate_change_window 两个核心 API
- 时区：默认本地时区（Asia/Shanghai）
"""

import re
import json
import logging
from pathlib import Path
from datetime import datetime, time, date
from typing import Dict, Any, List, Optional, Tuple

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = SKILL_DIR / "config.yaml"


# ============================================================
# 异常
# ============================================================

class ChangeWindowBlocked(Exception):
    """当前时间不在允许变更窗口内。"""
    def __init__(self, action: str, target: str, reason: str, next_allowed: str = ""):
        self.action = action
        self.target = target
        self.reason = reason
        self.next_allowed = next_allowed
        msg = f"⛔ 变更窗口拒绝 [{action}] → [{target}]：{reason}"
        if next_allowed:
            msg += f"。下一个允许窗口：{next_allowed}"
        super().__init__(msg)


# ============================================================
# 默认配置
# ============================================================

WEEKDAYS_ALL = [0, 1, 2, 3, 4, 5, 6]  # Mon=0...Sun=6
WEEKDAYS_WORKDAY = [0, 1, 2, 3, 4]
WEEKDAYS_WEEKEND = [5, 6]

# 默认：禁用，所有时间允许
DEFAULT_CONFIG: Dict[str, Any] = {
    "enabled": False,
    "actions": [
        "clone_vm", "batch_clone", "delete_vm", "power_vm",
        "reconfigure", "migrate", "snapshot",
    ],
    # 允许窗口（未配置 = 全时段允许）
    "allow_windows": [
        # {"weekdays": [0,1,2,3,4], "start": "09:00", "end": "18:00"},
    ],
    # 禁止窗口（优先级高）
    "block_windows": [
        # {"weekdays": [0,1,2,3,4], "start": "00:00", "end": "06:00",
        #  "reason": "夜间静默期"},
    ],
    # 单日黑名单
    "blackout_dates": [
        # "2026-01-01",  # 元旦
    ],
    # 白名单（即使在 block 窗口也允许）
    "whitelist_users": [],
    "whitelist_actions": ["list_all", "get_vm", "history", "audit_query",
                          "events", "audit_report"],
}


def load_window_config() -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    if not (HAS_YAML and CONFIG_FILE.exists()):
        return cfg
    try:
        all_cfg = yaml.safe_load(CONFIG_FILE.read_text()) or {}
        cw = all_cfg.get("change_window") or {}
        for k, v in cw.items():
            cfg[k] = v
    except Exception as e:
        logger.warning(f"加载 change_window 配置失败: {e}")
    return cfg


# ============================================================
# 工具
# ============================================================

def _parse_time(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def _is_in_window(now: datetime, window: Dict[str, Any]) -> bool:
    """判断当前时间是否落在窗口内。"""
    weekdays = window.get("weekdays", WEEKDAYS_ALL)
    if now.weekday() not in weekdays:
        return False

    try:
        start = _parse_time(window.get("start", "00:00"))
        end = _parse_time(window.get("end", "23:59"))
    except Exception:
        return False

    cur = now.time()
    if start <= end:
        return start <= cur <= end
    else:
        # 跨午夜（如 22:00 → 06:00）
        return cur >= start or cur <= end


def _next_window_start(now: datetime, windows: List[Dict[str, Any]]) -> str:
    """寻找下一个允许窗口的开始时间（简化：返回今天剩余/明天首个）。"""
    if not windows:
        return ""
    # 简单实现：遍历未来 7 天，找第一个能命中的时段
    from datetime import timedelta
    for d in range(0, 7):
        check_day = now.date() + timedelta(days=d)
        for w in windows:
            weekdays = w.get("weekdays", WEEKDAYS_ALL)
            if check_day.weekday() not in weekdays:
                continue
            try:
                start = _parse_time(w.get("start", "00:00"))
            except Exception:
                continue
            candidate = datetime.combine(check_day, start)
            if candidate > now:
                return candidate.strftime("%Y-%m-%d %H:%M")
    return ""


# ============================================================
# 核心 API
# ============================================================

def is_change_allowed(
    action: str,
    target: str = "",
    user: str = "agent",
    now: Optional[datetime] = None,
    cfg: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str, str]:
    """
    判断当前时间是否允许执行变更。

    :return: (allowed, reason, next_allowed_time)
    """
    config = cfg or load_window_config()
    if not config.get("enabled", False):
        return True, "(变更窗口未启用)", ""

    # 白名单 action 永远放行
    if action in (config.get("whitelist_actions") or []):
        return True, f"(白名单操作: {action})", ""

    # action 不在管控范围内
    if action not in (config.get("actions") or []):
        return True, "(操作未在管控范围)", ""

    # 白名单用户绕过
    if user in (config.get("whitelist_users") or []):
        return True, f"(白名单用户: {user})", ""

    now = now or datetime.now()

    # 检查黑名单日期
    today_str = now.strftime("%Y-%m-%d")
    if today_str in (config.get("blackout_dates") or []):
        return False, f"今日 {today_str} 为黑名单日期（禁止变更）", ""

    # 检查 block 窗口（优先级高）
    for block in (config.get("block_windows") or []):
        if _is_in_window(now, block):
            reason = block.get("reason", "处于禁止窗口")
            next_allowed = _next_window_start(now, config.get("allow_windows") or [])
            return False, reason, next_allowed

    # 检查 allow 窗口（未配置 = 全时段允许）
    allow_windows = config.get("allow_windows") or []
    if allow_windows:
        for w in allow_windows:
            if _is_in_window(now, w):
                return True, "在允许窗口内", ""
        next_allowed = _next_window_start(now, allow_windows)
        return False, "不在任何允许窗口内", next_allowed

    return True, "默认允许（无 allow_windows 配置）", ""


def validate_change_window(
    action: str,
    target: str = "",
    user: str = "agent",
) -> None:
    """
    handler 调用入口：不允许变更则抛 ChangeWindowBlocked。
    """
    allowed, reason, next_t = is_change_allowed(action, target, user)
    if not allowed:
        raise ChangeWindowBlocked(action, target, reason, next_allowed=next_t)


# ============================================================
# 渲染
# ============================================================

def format_status() -> str:
    cfg = load_window_config()
    enabled = "✅ 已启用" if cfg.get("enabled") else "❌ 未启用"
    allow_n = len(cfg.get("allow_windows") or [])
    block_n = len(cfg.get("block_windows") or [])
    blackout_n = len(cfg.get("blackout_dates") or [])

    lines = [
        f"变更窗口状态: {enabled}",
        f"  受管 actions: {', '.join(cfg.get('actions', []))}",
        f"  允许窗口: {allow_n} 条",
        f"  禁止窗口: {block_n} 条",
        f"  黑名单日期: {blackout_n} 个",
        f"  白名单用户: {cfg.get('whitelist_users') or '(无)'}",
        "",
        "当前时间检测："
    ]
    now = datetime.now()
    for act in ["clone_vm", "delete_vm", "power_vm"]:
        allowed, reason, nxt = is_change_allowed(act, "test-vm")
        icon = "✅" if allowed else "⛔"
        lines.append(f"  {icon} {act}: {reason}" + (f" → {nxt}" if nxt else ""))
    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="变更窗口管理")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="查看变更窗口状态")
    sub.add_parser("config", help="查看完整配置")

    p_check = sub.add_parser("check", help="检查指定操作")
    p_check.add_argument("action")
    p_check.add_argument("--target", default="")
    p_check.add_argument("--user", default="agent")

    args = parser.parse_args()
    if args.cmd == "status":
        print(format_status())
    elif args.cmd == "config":
        print(json.dumps(load_window_config(), ensure_ascii=False, indent=2))
    elif args.cmd == "check":
        allowed, reason, nxt = is_change_allowed(args.action, args.target, args.user)
        icon = "✅" if allowed else "⛔"
        print(f"{icon} action={args.action} target={args.target} user={args.user}")
        print(f"  原因: {reason}")
        if nxt:
            print(f"  下一个窗口: {nxt}")
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
