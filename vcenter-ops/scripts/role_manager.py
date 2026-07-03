"""
Module: scripts.role_manager
Description: RBAC 角色权限管理。用户 → 角色 → 操作权限。
Author: 运枢
Date: 2026-05-22
Version: 1.3.0

设计要点：
- 角色定义放在 config.yaml 的 rbac 节点
- 内置三级角色：guest（只读）/ operator（常规运维）/ admin（全权）
- 用户绑定持久化在 data/rbac_users.json
- 提供 check_permission(user, action) → bool，handler 调用
- 未匹配的用户走默认角色（默认 guest 或 deny）
"""

import json
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
USERS_FILE = SKILL_DIR / "data" / "rbac_users.json"
USERS_FILE.parent.mkdir(parents=True, exist_ok=True)


# ============================================================
# 异常
# ============================================================

class PermissionDenied(Exception):
    """权限不足。"""
    def __init__(self, user: str, action: str, role: str = ""):
        super().__init__(
            f"🚫 用户 [{user}] (角色={role or '未知'}) 无权执行操作 [{action}]"
        )
        self.user = user
        self.action = action
        self.role = role


# ============================================================
# 内置角色定义
# ============================================================

BUILT_IN_ROLES: Dict[str, Dict[str, Any]] = {
    "guest": {
        "description": "只读访客：仅可查询",
        "actions": [
            "list_all", "get_vm", "history", "preset", "audit_query",
            "ip_pool", "events", "quota", "export", "template", "datastore",
            "audit_report",
        ],
    },
    "operator": {
        "description": "运维操作员：常规变更",
        "actions": [
            "list_all", "get_vm", "clone_vm", "batch_clone",
            "snapshot", "reconfigure", "power_vm",
            "history", "preset", "ip_pool", "events", "quota", "export",
            "template", "datastore", "guest_exec", "migrate",
            "plan", "ttl", "audit_query", "audit_report", "webhook",
            "approval",
        ],
    },
    "admin": {
        "description": "管理员：全权（含删除/审批/RBAC）",
        "actions": ["*"],  # 通配
    },
}


# ============================================================
# 配置加载（从 config.yaml.rbac 合并自定义角色）
# ============================================================

def load_rbac_config() -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "enabled": False,                 # 默认关闭，需用户显式启用
        "default_role": "guest",          # 未绑定用户默认角色
        "deny_when_unknown": False,       # 未知用户是否直接拒绝
        "roles": dict(BUILT_IN_ROLES),
    }
    if not (HAS_YAML and CONFIG_FILE.exists()):
        return cfg
    try:
        all_cfg = yaml.safe_load(CONFIG_FILE.read_text()) or {}
        rbac = all_cfg.get("rbac") or {}
        for k, v in rbac.items():
            if k == "roles" and isinstance(v, dict):
                # 合并自定义角色
                merged = dict(cfg["roles"])
                merged.update(v)
                cfg["roles"] = merged
            else:
                cfg[k] = v
    except Exception as e:
        logger.warning(f"加载 RBAC 配置失败，使用默认: {e}")
    return cfg


def list_roles() -> List[Dict[str, Any]]:
    cfg = load_rbac_config()
    return [
        {"name": k, "description": v.get("description", ""),
         "actions": v.get("actions", []), "action_count": (
             "ALL" if v.get("actions") == ["*"] else len(v.get("actions", [])))}
        for k, v in cfg["roles"].items()
    ]


def get_role(name: str) -> Optional[Dict[str, Any]]:
    cfg = load_rbac_config()
    return cfg["roles"].get(name)


# ============================================================
# 用户 ↔ 角色绑定
# ============================================================

def _load_users() -> Dict[str, Any]:
    if not USERS_FILE.exists():
        return {"users": {}}
    try:
        return json.loads(USERS_FILE.read_text())
    except Exception:
        return {"users": {}}


def _save_users(data: Dict[str, Any]) -> None:
    USERS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    USERS_FILE.chmod(0o600)


def bind_user(user: str, role: str, description: str = "") -> Dict[str, Any]:
    """绑定用户到角色。"""
    if not get_role(role):
        raise ValueError(f"角色 [{role}] 不存在")
    data = _load_users()
    data["users"][user] = {
        "role": role,
        "description": description,
    }
    _save_users(data)
    logger.info(f"👤 用户 [{user}] 已绑定角色 [{role}]")
    return data["users"][user]


def unbind_user(user: str) -> bool:
    data = _load_users()
    if user in data["users"]:
        del data["users"][user]
        _save_users(data)
        return True
    return False


def get_user_role(user: str) -> str:
    """查询用户角色。未绑定返回默认角色。"""
    cfg = load_rbac_config()
    data = _load_users()
    entry = data["users"].get(user)
    if entry:
        return entry["role"]
    if cfg.get("deny_when_unknown", False):
        return ""
    return cfg.get("default_role", "guest")


def list_users() -> List[Dict[str, Any]]:
    data = _load_users()
    return [{"user": k, **v} for k, v in data["users"].items()]


# ============================================================
# 权限检查
# ============================================================

def get_role_actions(role: str) -> Set[str]:
    role_def = get_role(role)
    if not role_def:
        return set()
    actions = role_def.get("actions") or []
    return set(actions)


def has_permission(user: str, action: str) -> bool:
    cfg = load_rbac_config()
    if not cfg.get("enabled", False):
        return True  # 未启用 RBAC 时全放行

    role = get_user_role(user)
    if not role:
        return False

    actions = get_role_actions(role)
    if "*" in actions:
        return True
    return action in actions


def check_permission(user: str, action: str) -> None:
    """检查并在无权限时抛出 PermissionDenied。"""
    cfg = load_rbac_config()
    if not cfg.get("enabled", False):
        return

    role = get_user_role(user)
    if not has_permission(user, action):
        raise PermissionDenied(user, action, role=role)


# ============================================================
# 渲染
# ============================================================

def format_users_table() -> str:
    users = list_users()
    if not users:
        return "📭 暂无 RBAC 用户绑定（未绑定用户走默认角色）"
    lines = ["| 用户 | 角色 | 说明 |", "|------|------|------|"]
    for u in users:
        lines.append(f"| {u['user']} | {u['role']} | {u.get('description', '-')} |")
    return "\n".join(lines)


def format_roles_table() -> str:
    roles = list_roles()
    lines = ["| 角色 | 描述 | 操作数 |", "|------|------|--------|"]
    for r in roles:
        lines.append(f"| {r['name']} | {r['description']} | {r['action_count']} |")
    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="RBAC 角色权限管理")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("roles", help="列出所有角色")
    sub.add_parser("users", help="列出所有用户绑定")
    sub.add_parser("config", help="查看当前 RBAC 配置")

    p_bind = sub.add_parser("bind", help="绑定用户到角色")
    p_bind.add_argument("user")
    p_bind.add_argument("role")
    p_bind.add_argument("--desc", default="")

    p_unbind = sub.add_parser("unbind", help="解绑用户")
    p_unbind.add_argument("user")

    p_check = sub.add_parser("check", help="检查用户操作权限")
    p_check.add_argument("user")
    p_check.add_argument("action")

    args = parser.parse_args()

    if args.cmd == "roles":
        print(format_roles_table())
    elif args.cmd == "users":
        print(format_users_table())
    elif args.cmd == "config":
        print(json.dumps(load_rbac_config(), ensure_ascii=False, indent=2))
    elif args.cmd == "bind":
        d = bind_user(args.user, args.role, description=args.desc)
        print(f"✅ {args.user} → {args.role}: {d}")
    elif args.cmd == "unbind":
        ok = unbind_user(args.user)
        print(f"{'✅ 已解绑' if ok else '⚠️ 未找到用户'}: {args.user}")
    elif args.cmd == "check":
        try:
            check_permission(args.user, args.action)
            role = get_user_role(args.user)
            print(f"✅ 通过：用户 [{args.user}] (角色={role}) 可执行 [{args.action}]")
        except PermissionDenied as e:
            print(str(e))
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
