"""
Module: scripts.healthcheck
Description: 一键健康自检。检查所有依赖、配置、缓存、锁、秘密、连通性。
Author: 运枢
Date: 2026-05-22
Version: 1.2.0
"""

import os
import sys
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR))

logger = logging.getLogger(__name__)


# ============================================================
# 检查项
# ============================================================

def check_python_deps() -> Dict[str, Any]:
    """检查必要 Python 包。"""
    required = ["pyVmomi", "yaml", "cryptography", "dotenv"]
    missing = []
    for mod in required:
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    return {
        "name": "Python 依赖",
        "ok": len(missing) == 0,
        "detail": f"缺失: {missing}" if missing else "全部就绪",
    }


def check_config_files() -> Dict[str, Any]:
    """检查关键配置文件。"""
    required = ["config.yaml", "requirements.txt"]
    optional = [".env", "data/secrets.json", "data/.master_key"]
    missing_req = [f for f in required if not (SKILL_DIR / f).exists()]
    found_opt = [f for f in optional if (SKILL_DIR / f).exists()]
    return {
        "name": "配置文件",
        "ok": len(missing_req) == 0,
        "detail": f"必需缺失: {missing_req} | 可选已有: {found_opt}",
    }


def check_data_dirs() -> Dict[str, Any]:
    """检查 data 目录权限 + 子目录。"""
    data_dir = SKILL_DIR / "data"
    if not data_dir.exists():
        return {"name": "data 目录", "ok": False, "detail": "data/ 不存在"}
    sub = []
    for d in ["tasks", "locks", "metrics"]:
        p = data_dir / d
        if p.exists():
            sub.append(f"{d}({len(list(p.glob('*')))})")
    return {
        "name": "data 目录",
        "ok": True,
        "detail": f"子目录: {', '.join(sub) if sub else '空'}",
    }


def check_secrets() -> Dict[str, Any]:
    """检查 secret_manager 主密钥和加密存储。"""
    try:
        from scripts.secret_manager import load_master_key, list_secret_keys
        key = load_master_key(auto_create=False)
        keys = list_secret_keys()
        return {
            "name": "密码加密 (secret_manager)",
            "ok": True,
            "detail": f"主密钥 OK ({len(key)} bytes), 加密项 {len(keys)} 个",
        }
    except Exception as e:
        return {"name": "密码加密 (secret_manager)", "ok": False, "detail": str(e)}


def check_locks() -> Dict[str, Any]:
    """检查 VM 锁状态。"""
    lock_dir = SKILL_DIR / "data" / "locks"
    if not lock_dir.exists():
        return {"name": "VM 锁", "ok": True, "detail": "无锁文件"}
    locks = list(lock_dir.glob("*.json"))
    stale = []
    for f in locks:
        try:
            data = json.loads(f.read_text())
            ttl = data.get("ttl", 300)
            acquired = data.get("acquired_at", 0)
            if datetime.now().timestamp() - acquired > ttl + 60:
                stale.append(f.stem)
        except Exception:
            pass
    return {
        "name": "VM 锁",
        "ok": len(stale) == 0,
        "detail": f"活动锁 {len(locks)}, 过期残留 {len(stale)}",
    }


def check_cache() -> Dict[str, Any]:
    """检查缓存文件。"""
    cache_file = SKILL_DIR / "data" / "vc_session_cache.json"
    if not cache_file.exists():
        return {"name": "vCenter 会话缓存", "ok": True, "detail": "无缓存"}
    size = cache_file.stat().st_size
    age = datetime.now().timestamp() - cache_file.stat().st_mtime
    return {
        "name": "vCenter 会话缓存",
        "ok": True,
        "detail": f"大小 {size} bytes, 年龄 {age:.0f}s",
    }


def check_audit_log() -> Dict[str, Any]:
    """检查审计日志。"""
    audit_file = SKILL_DIR / "logs" / "audit.log"
    if not audit_file.exists():
        return {"name": "审计日志", "ok": False, "detail": "未生成"}
    size = audit_file.stat().st_size
    return {"name": "审计日志", "ok": True, "detail": f"大小 {size} bytes"}


def check_vcenter_connectivity() -> Dict[str, Any]:
    """检查 vCenter 可连通性。"""
    try:
        import yaml
        from dotenv import load_dotenv
        load_dotenv(SKILL_DIR / ".env")
        cfg = yaml.safe_load((SKILL_DIR / "config.yaml").read_text())["vcenter"]
        from scripts.client import VCenterClient
        from scripts import secret_manager
        pwd = secret_manager.resolve_password(cfg.get("password_ref", ""))
        with VCenterClient(cfg["host"], cfg["user"], pwd, cfg.get("port", 443)) as si:
            content = si.RetrieveContent()
            ver = content.about.fullName
            return {"name": "vCenter 连通性", "ok": True, "detail": ver}
    except Exception as e:
        return {"name": "vCenter 连通性", "ok": False, "detail": str(e)[:80]}


# ============================================================
# 汇总
# ============================================================

CHECKS = [
    check_python_deps,
    check_config_files,
    check_data_dirs,
    check_secrets,
    check_locks,
    check_cache,
    check_audit_log,
    check_vcenter_connectivity,
]


def run_all(include_vcenter: bool = True) -> List[Dict[str, Any]]:
    results = []
    for fn in CHECKS:
        if not include_vcenter and fn.__name__ == "check_vcenter_connectivity":
            continue
        try:
            results.append(fn())
        except Exception as e:
            results.append({"name": fn.__name__, "ok": False, "detail": str(e)})
    return results


def format_results(results: List[Dict[str, Any]]) -> str:
    ok_count = sum(1 for r in results if r.get("ok"))
    total = len(results)
    lines = [f"# vCenter Ops 健康自检报告",
             f"通过 {ok_count}/{total}", ""]
    lines.append("| # | 检查项 | 状态 | 详情 |")
    lines.append("|---|--------|------|------|")
    for i, r in enumerate(results, 1):
        icon = "✅" if r.get("ok") else "❌"
        lines.append(f"| {i} | {r.get('name','?')} | {icon} | {r.get('detail','-')} |")
    return "\n".join(lines)


def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="健康自检")
    parser.add_argument("--no-vcenter", action="store_true",
                        help="跳过 vCenter 连通性检查")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args()

    results = run_all(include_vcenter=not args.no_vcenter)
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(format_results(results))

    fail = sum(1 for r in results if not r.get("ok"))
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    _cli()
