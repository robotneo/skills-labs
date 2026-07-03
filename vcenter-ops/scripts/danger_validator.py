"""
Module: scripts.danger_validator
Description: 危险词二次校验。对目标名称做关键词/模式扫描，命中则强制要求二次确认。
Author: 运枢
Date: 2026-05-22
Version: 1.3.0

设计要点：
- 内置危险词库（prod/db/master/redis/nginx/mysql/oracle/核心/生产）
- 支持从 config.yaml.danger_words 自定义扩展
- 匹配模式：精确 / 前缀 / 后缀 / 正则
- 命中后抛出 DangerConfirmedRequired，由 handler 层做二次交互
- 提供 confirm_danger() 标记确认，避免重复校验
- 白名单机制：某些前缀即使匹配也放行
"""

import re
import json
import time
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Set

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = SKILL_DIR / "config.yaml"
CONFIRM_FILE = SKILL_DIR / "data" / "danger_confirms.json"
CONFIRM_FILE.parent.mkdir(parents=True, exist_ok=True)


# ============================================================
# 异常
# ============================================================

class DangerConfirmRequired(Exception):
    """危险词命中，需要二次确认。"""
    def __init__(self, target: str, matched: List[str], action: str = ""):
        self.target = target
        self.matched = matched
        self.action = action
        words_str = "、".join(matched)
        super().__init__(
            f"⚠️ 危险词命中 [{target}]：匹配到「{words_str}」。"
            f"此操作需要二次确认。"
        )


# ============================================================
# 内置危险词库
# ============================================================

BUILT_IN_PATTERNS: List[Dict[str, Any]] = [
    # 生产环境标识
    {"pattern": "prod", "mode": "contains", "reason": "生产环境"},
    {"pattern": "production", "mode": "contains", "reason": "生产环境"},
    {"pattern": "生产", "mode": "contains", "reason": "生产环境"},
    {"pattern": "核心", "mode": "contains", "reason": "核心服务"},
    {"pattern": "core", "mode": "contains", "reason": "核心服务"},

    # 数据库标识
    {"pattern": "db-", "mode": "prefix", "reason": "数据库"},
    {"pattern": "mysql", "mode": "contains", "reason": "MySQL数据库"},
    {"pattern": "redis", "mode": "contains", "reason": "Redis缓存"},
    {"pattern": "oracle", "mode": "contains", "reason": "Oracle数据库"},
    {"pattern": "postgres", "mode": "contains", "reason": "PostgreSQL数据库"},
    {"pattern": "mongo", "mode": "contains", "reason": "MongoDB数据库"},
    {"pattern": "es-", "mode": "prefix", "reason": "Elasticsearch"},

    # 关键服务
    {"pattern": "master", "mode": "contains", "reason": "主节点"},
    {"pattern": "primary", "mode": "contains", "reason": "主节点"},
    {"pattern": "nginx", "mode": "contains", "reason": "Nginx网关"},
    {"pattern": "gateway", "mode": "contains", "reason": "网关服务"},
    {"pattern": "api-", "mode": "prefix", "reason": "API服务"},

    # K8s / 中间件
    {"pattern": "k8s-", "mode": "prefix", "reason": "K8s节点"},
    {"pattern": "etcd", "mode": "contains", "reason": "Etcd集群"},
    {"pattern": "zk-", "mode": "prefix", "reason": "ZooKeeper"},
    {"pattern": "kafka", "mode": "contains", "reason": "Kafka消息队列"},
    {"pattern": "rabbitmq", "mode": "contains", "reason": "RabbitMQ消息队列"},
]

# 默认白名单（即使命中也不拦截）
DEFAULT_WHITELIST: List[str] = [
    "dev-*", "test-*", "staging-*", "tmp-*", "temp-*",
    "uat-*", "demo-*", "backup-*",
]


# ============================================================
# 配置加载
# ============================================================

def load_danger_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "enabled": True,
        "actions": ["delete_vm", "power_vm", "reconfigure", "migrate"],
        "patterns": list(BUILT_IN_PATTERNS),
        "whitelist": list(DEFAULT_WHITELIST),
        "confirm_ttl_seconds": 300,  # 确认后 5 分钟内免再次确认
    }
    if not (HAS_YAML and CONFIG_FILE.exists()):
        return cfg
    try:
        all_cfg = yaml.safe_load(CONFIG_FILE.read_text()) or {}
        dw = all_cfg.get("danger_words") or {}
        for k, v in dw.items():
            if k == "patterns" and isinstance(v, list):
                cfg["patterns"] = BUILT_IN_PATTERNS + v
            elif k == "whitelist" and isinstance(v, list):
                cfg["whitelist"] = DEFAULT_WHITELIST + v
            else:
                cfg[k] = v
    except Exception as e:
        logger.warning(f"加载危险词配置失败，使用内置词库: {e}")
    return cfg


# ============================================================
# 匹配引擎
# ============================================================

def _match_pattern(target: str, pattern: str, mode: str) -> bool:
    t = target.lower()
    p = pattern.lower()
    if mode == "exact":
        return t == p
    elif mode == "prefix":
        return t.startswith(p) or t.startswith(f"{p}-") or t.startswith(f"{p}_")
    elif mode == "suffix":
        return t.endswith(p) or t.endswith(f"-{p}") or t.endswith(f"_{p}")
    elif mode == "contains":
        return p in t
    elif mode == "regex":
        try:
            return bool(re.search(p, target, re.IGNORECASE))
        except re.error:
            return False
    return False


def _is_whitelisted(target: str, whitelist: List[str]) -> bool:
    t = target.lower()
    for wl in whitelist:
        wl_low = wl.lower()
        if "*" in wl_low:
            # 简单通配：dev-* 匹配 dev-xxx
            regex = "^" + wl_low.replace("*", ".*") + "$"
            if re.match(regex, t):
                return True
        elif t == wl_low:
            return True
    return False


def scan_danger(
    target: str,
    action: str = "",
    cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    扫描目标名称是否命中危险词。返回命中列表。
    """
    config = cfg or load_danger_config()
    if not config.get("enabled", True):
        return []

    # 只对指定 action 生效
    if action and config.get("actions"):
        if action not in config["actions"]:
            return []

    # 白名单跳过
    if _is_whitelisted(target, config.get("whitelist", [])):
        return []

    matched = []
    for p_def in config.get("patterns", []):
        pattern = p_def.get("pattern", "")
        mode = p_def.get("mode", "contains")
        if _match_pattern(target, pattern, mode):
            matched.append({
                "pattern": pattern,
                "mode": mode,
                "reason": p_def.get("reason", ""),
            })
    return matched


# ============================================================
# 确认管理
# ============================================================

def _load_confirms() -> Dict[str, Any]:
    if not CONFIRM_FILE.exists():
        return {"confirms": {}}
    try:
        return json.loads(CONFIRM_FILE.read_text())
    except Exception:
        return {"confirms": {}}


def _save_confirms(data: Dict[str, Any]) -> None:
    CONFIRM_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def confirm_danger(target: str, action: str, user: str = "agent") -> None:
    """记录用户已确认该操作。"""
    data = _load_confirms()
    key = f"{action}:{target}"
    data["confirms"][key] = {
        "user": user,
        "confirmed_at": int(time.time()),
    }
    _save_confirms(data)
    logger.info(f"✅ 危险确认已记录: {key} by {user}")


def is_confirmed(target: str, action: str) -> bool:
    """检查该操作是否已被确认（且在 TTL 内）。"""
    cfg = load_danger_config()
    ttl = cfg.get("confirm_ttl_seconds", 300)
    data = _load_confirms()
    key = f"{action}:{target}"
    entry = data["confirms"].get(key)
    if not entry:
        return False
    elapsed = int(time.time()) - entry.get("confirmed_at", 0)
    return elapsed < ttl


def validate_danger(
    target: str,
    action: str,
    user: str = "agent",
    skip_confirmed: bool = True,
) -> None:
    """
    完整的危险校验流程：
    1. 扫描危险词
    2. 已确认则放行
    3. 未确认则抛出 DangerConfirmRequired

    handler 调用此函数，捕获异常后做二次交互。
    """
    matched = scan_danger(target, action)
    if not matched:
        return

    if skip_confirmed and is_confirmed(target, action):
        logger.info(f"⚠️ 危险词命中 [{target}]，但已确认，放行")
        return

    raise DangerConfirmRequired(target, [m["pattern"] for m in matched], action=action)


# ============================================================
# CLI
# ============================================================

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="危险词二次校验")
    sub = parser.add_subparsers(dest="cmd")

    p_scan = sub.add_parser("scan", help="扫描目标名")
    p_scan.add_argument("target")
    p_scan.add_argument("--action", default="delete_vm")

    p_confirm = sub.add_parser("confirm", help="确认危险操作")
    p_confirm.add_argument("target")
    p_confirm.add_argument("--action", default="delete_vm")

    sub.add_parser("config", help="查看当前配置")
    sub.add_parser("patterns", help="列出所有危险词模式")

    args = parser.parse_args()

    if args.cmd == "scan":
        matched = scan_danger(args.target, args.action)
        if not matched:
            print(f"✅ [{args.target}] 未命中危险词")
        else:
            print(f"⚠️ [{args.target}] 命中 {len(matched)} 个危险词:")
            for m in matched:
                print(f"  • 模式: {m['pattern']} ({m['mode']}) | 原因: {m['reason']}")
    elif args.cmd == "confirm":
        confirm_danger(args.target, args.action)
        print(f"✅ 已确认: {args.action} → {args.target}")
    elif args.cmd == "config":
        print(json.dumps(load_danger_config(), ensure_ascii=False, indent=2))
    elif args.cmd == "patterns":
        cfg = load_danger_config()
        for p in cfg.get("patterns", []):
            print(f"  {p.get('mode','?'):10s} | {p['pattern']:20s} | {p.get('reason','')}")
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
