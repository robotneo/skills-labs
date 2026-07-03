"""
Module: scripts.quota_enforcer
Description: 资源配额硬限制。克隆/扩容前检查 Cluster/Datastore 是否越限，越限直接拒绝。
Author: 运枢
Date: 2026-05-22
Version: 1.1.0

设计要点：
- 复用 executor.check_resource_quota 的查询能力，本模块只做"拒绝"决策
- 配额配置位于 config.yaml 的 quota_enforce 节点
- 单次操作配额：cpu/memory/disk 单台 VM 上限
- 总量配额：集群/Datastore 已用比例上限（默认 90%）
- 命中拒绝时抛出 QuotaExceeded（含详细原因）
"""

import logging
from typing import Optional, Dict, Any, List
from pathlib import Path

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

class QuotaExceeded(Exception):
    """配额越限。"""
    def __init__(self, msg: str, reasons: Optional[List[str]] = None):
        super().__init__(msg)
        self.reasons = reasons or []


# ============================================================
# 配置加载
# ============================================================

DEFAULT_QUOTA: Dict[str, Any] = {
    "enabled": True,
    "per_vm": {
        "max_cpu": 32,
        "max_memory_gb": 256,
        "max_disk_gb": 4000,
    },
    "cluster_threshold": {
        "cpu_used_pct": 0.90,
        "memory_used_pct": 0.90,
    },
    "datastore_threshold": {
        "used_pct": 0.90,
    },
    "deny_when_threshold": True,  # 越线是否拒绝（false=仅警告）
    "whitelist_users": [],         # 白名单用户名（绕过硬限制）
}


def load_quota_config() -> Dict[str, Any]:
    """从 config.yaml 加载 quota_enforce 节点，缺失走默认值。"""
    cfg = dict(DEFAULT_QUOTA)
    if not (HAS_YAML and CONFIG_FILE.exists()):
        return cfg
    try:
        all_cfg = yaml.safe_load(CONFIG_FILE.read_text()) or {}
        user_q = all_cfg.get("quota_enforce") or {}
        # 深度合并
        for k, v in user_q.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
    except Exception as e:
        logger.warning(f"加载 quota 配置失败，使用默认值: {e}")
    return cfg


# ============================================================
# 检查器
# ============================================================

def check_per_vm_quota(
    cpus: Optional[int],
    memory_gb: Optional[int],
    disk_gb: Optional[int],
    quota_cfg: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """
    单台 VM 配额检查。返回违规原因列表（空=通过）。
    """
    cfg = quota_cfg or load_quota_config()
    if not cfg.get("enabled", True):
        return []

    pv = cfg.get("per_vm") or {}
    reasons: List[str] = []
    if cpus and pv.get("max_cpu") and cpus > pv["max_cpu"]:
        reasons.append(f"CPU 请求 {cpus} 超过单 VM 上限 {pv['max_cpu']}")
    if memory_gb and pv.get("max_memory_gb") and memory_gb > pv["max_memory_gb"]:
        reasons.append(f"内存请求 {memory_gb}GB 超过单 VM 上限 {pv['max_memory_gb']}GB")
    if disk_gb and pv.get("max_disk_gb") and disk_gb > pv["max_disk_gb"]:
        reasons.append(f"磁盘请求 {disk_gb}GB 超过单 VM 上限 {pv['max_disk_gb']}GB")
    return reasons


def check_cluster_usage(
    executor,
    cluster_name: str,
    quota_cfg: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """
    集群使用率检查（基于 executor.check_resource_quota）。
    """
    cfg = quota_cfg or load_quota_config()
    if not cfg.get("enabled", True):
        return []
    ct = cfg.get("cluster_threshold") or {}
    cpu_th = ct.get("cpu_used_pct", 0.9)
    mem_th = ct.get("memory_used_pct", 0.9)
    try:
        result = executor.check_resource_quota(
            cluster_name=cluster_name,
            ds_name="",
            cpu_threshold=cpu_th,
            mem_threshold=mem_th,
            disk_threshold=0.9,
        )
    except Exception as e:
        logger.warning(f"集群配额检查失败 [{cluster_name}]: {e}")
        return []
    reasons: List[str] = []
    for w in (result or {}).get("warnings", []):
        # warnings 已经是字符串
        if "cluster" in (w or "").lower() or cluster_name in (w or ""):
            reasons.append(str(w))
    return reasons


def check_datastore_usage(
    executor,
    ds_name: str,
    quota_cfg: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """
    Datastore 使用率检查。
    """
    cfg = quota_cfg or load_quota_config()
    if not cfg.get("enabled", True):
        return []
    th = (cfg.get("datastore_threshold") or {}).get("used_pct", 0.9)
    try:
        result = executor.check_resource_quota(
            cluster_name="",
            ds_name=ds_name,
            cpu_threshold=0.9,
            mem_threshold=0.9,
            disk_threshold=th,
        )
    except Exception as e:
        logger.warning(f"DS 配额检查失败 [{ds_name}]: {e}")
        return []
    reasons: List[str] = []
    for w in (result or {}).get("warnings", []):
        if "datastore" in (w or "").lower() or "ds" in (w or "").lower() or ds_name in (w or ""):
            reasons.append(str(w))
    return reasons


def enforce_clone_quota(
    executor,
    cluster_name: str,
    ds_name: str,
    cpus: Optional[int],
    memory_gb: Optional[int],
    disk_gb: Optional[int],
    user: str = "agent",
    quota_cfg: Optional[Dict[str, Any]] = None,
) -> None:
    """
    克隆前的配额硬限制检查。

    :raises QuotaExceeded: 配额越限且配置为拒绝
    """
    cfg = quota_cfg or load_quota_config()
    if not cfg.get("enabled", True):
        return

    # 白名单跳过
    if user in (cfg.get("whitelist_users") or []):
        logger.info(f"用户 [{user}] 在白名单中，跳过配额检查")
        return

    reasons: List[str] = []
    reasons += check_per_vm_quota(cpus, memory_gb, disk_gb, quota_cfg=cfg)
    if cluster_name:
        reasons += check_cluster_usage(executor, cluster_name, quota_cfg=cfg)
    if ds_name:
        reasons += check_datastore_usage(executor, ds_name, quota_cfg=cfg)

    if not reasons:
        return

    if cfg.get("deny_when_threshold", True):
        msg = "🚫 配额硬限制拦截：\n  - " + "\n  - ".join(reasons)
        logger.error(msg)
        raise QuotaExceeded(msg, reasons=reasons)
    else:
        logger.warning(f"⚠️ 配额越限（仅警告）: {reasons}")


# ============================================================
# CLI
# ============================================================

def _cli():
    import argparse, json
    parser = argparse.ArgumentParser(description="配额硬限制工具")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("config", help="查看当前配额配置")
    p_check = sub.add_parser("check", help="模拟单 VM 配额检查（仅 per_vm，不连 vCenter）")
    p_check.add_argument("--cpu", type=int)
    p_check.add_argument("--memory", type=int)
    p_check.add_argument("--disk", type=int)

    args = parser.parse_args()
    if args.cmd == "config":
        print(json.dumps(load_quota_config(), ensure_ascii=False, indent=2))
    elif args.cmd == "check":
        reasons = check_per_vm_quota(args.cpu, args.memory, args.disk)
        if not reasons:
            print("✅ 通过配额检查")
        else:
            print("❌ 违规:")
            for r in reasons:
                print(f"  - {r}")
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
