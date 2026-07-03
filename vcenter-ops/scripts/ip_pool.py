"""
Module: scripts.ip_pool
Description: IP 池管理器。从段/CIDR 分配可用 IP，自动避免冲突，支持持久化预留。
Author: 运枢
Date: 2026-05-22
Version: 1.1.0

设计要点：
- 支持 CIDR / 范围 / 单 IP 三种声明方式
- 预留持久化（data/ip_reservations.json），重启不丢
- 释放 / 清理 / 列出 三个核心操作
- 与 ip_scanner 协作：分配前可选 ping 验活/避开已占用 IP
"""

import os
import json
import socket
import struct
import ipaddress
import logging
import time
from pathlib import Path
from typing import List, Optional, Dict, Any, Iterable, Set

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).resolve().parent.parent
RESERVE_FILE = SKILL_DIR / "data" / "ip_reservations.json"
RESERVE_FILE.parent.mkdir(parents=True, exist_ok=True)


# ============================================================
# 工具函数
# ============================================================

def parse_pool_spec(spec: str) -> List[str]:
    """
    解析 IP 池声明。

    支持：
      - CIDR：10.0.0.0/24
      - 范围：10.0.0.10-10.0.0.50
      - 单个：10.0.0.5
      - 逗号组合：10.0.0.5,10.0.0.10-10.0.0.20,10.0.1.0/28
    """
    result: List[str] = []
    if not spec:
        return result
    for part in spec.split(","):
        p = part.strip()
        if not p:
            continue
        try:
            if "/" in p:
                net = ipaddress.ip_network(p, strict=False)
                # 跳过网络/广播地址
                result.extend(str(h) for h in net.hosts())
            elif "-" in p:
                start_s, end_s = p.split("-", 1)
                start = int(ipaddress.IPv4Address(start_s.strip()))
                end = int(ipaddress.IPv4Address(end_s.strip()))
                if end < start:
                    start, end = end, start
                for i in range(start, end + 1):
                    result.append(str(ipaddress.IPv4Address(i)))
            else:
                ipaddress.IPv4Address(p)  # validate
                result.append(p)
        except Exception as e:
            logger.warning(f"无法解析 IP 段 [{p}]: {e}")
    return result


# ============================================================
# 持久化预留
# ============================================================

def _load_reservations() -> Dict[str, Any]:
    if not RESERVE_FILE.exists():
        return {"reservations": {}}
    try:
        return json.loads(RESERVE_FILE.read_text())
    except Exception:
        return {"reservations": {}}


def _save_reservations(data: Dict[str, Any]) -> None:
    RESERVE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))


def list_reservations() -> List[Dict[str, Any]]:
    data = _load_reservations()
    return list(data.get("reservations", {}).values())


def reserve_ip(ip: str, vm_name: str, owner: str = "agent", ttl_minutes: int = 0) -> Dict[str, Any]:
    """登记一个 IP 预留。ttl_minutes=0 表示永久。"""
    data = _load_reservations()
    rec = {
        "ip": ip,
        "vm_name": vm_name,
        "owner": owner,
        "reserved_at": int(time.time()),
        "expires_at": int(time.time()) + ttl_minutes * 60 if ttl_minutes else 0,
    }
    data["reservations"][ip] = rec
    _save_reservations(data)
    return rec


def release_ip(ip: str) -> bool:
    data = _load_reservations()
    if ip in data.get("reservations", {}):
        del data["reservations"][ip]
        _save_reservations(data)
        return True
    return False


def cleanup_expired() -> int:
    """清理过期的预留，返回清理数量。"""
    data = _load_reservations()
    now = int(time.time())
    expired = [ip for ip, r in data.get("reservations", {}).items()
               if r.get("expires_at") and r["expires_at"] < now]
    for ip in expired:
        del data["reservations"][ip]
    if expired:
        _save_reservations(data)
        logger.info(f"🧹 清理过期 IP 预留 {len(expired)} 个")
    return len(expired)


def reserved_ip_set() -> Set[str]:
    cleanup_expired()
    return set(_load_reservations().get("reservations", {}).keys())


# ============================================================
# 在线验活（可选）
# ============================================================

def is_ip_alive(ip: str, timeout: float = 1.0) -> bool:
    """
    使用系统 ping 检测 IP 是否存活。
    Linux/macOS 通用；返回 True 表示有响应（占用）。
    """
    cmd = f"ping -c 1 -W {int(timeout)} {ip} >/dev/null 2>&1"
    return os.system(cmd) == 0


# ============================================================
# IP 池
# ============================================================

class IPPool:
    """
    IP 池：从 spec 派生候选 IP，结合预留 + 在线验活分配可用 IP。
    """

    def __init__(
        self,
        spec: str,
        skip_alive: bool = True,
        extra_blocked: Optional[Iterable[str]] = None,
    ):
        self.spec = spec
        self.candidates: List[str] = parse_pool_spec(spec)
        self.skip_alive = skip_alive
        self.extra_blocked: Set[str] = set(extra_blocked or [])

    def size(self) -> int:
        return len(self.candidates)

    def available(self, limit: Optional[int] = None) -> List[str]:
        """返回当前可用 IP 列表（已剔除预留 + 在线 + extra_blocked）。"""
        blocked = reserved_ip_set() | self.extra_blocked
        result: List[str] = []
        for ip in self.candidates:
            if ip in blocked:
                continue
            if self.skip_alive and is_ip_alive(ip):
                continue
            result.append(ip)
            if limit and len(result) >= limit:
                break
        return result

    def allocate(
        self,
        count: int,
        vm_name_prefix: str,
        owner: str = "agent",
        ttl_minutes: int = 60,
    ) -> List[Dict[str, Any]]:
        """
        分配 count 个 IP 并登记预留。
        返回 [{"ip": ..., "vm_name": ..., ...}, ...]
        """
        if count <= 0:
            return []
        candidates = self.available(limit=count * 3)  # 多取 3 倍冗余
        if len(candidates) < count:
            raise RuntimeError(
                f"❌ IP 池 [{self.spec}] 可用 IP 不足：需求 {count}，可用 {len(candidates)}"
            )

        results = []
        for i, ip in enumerate(candidates[:count]):
            vm_name = f"{vm_name_prefix}{i+1:02d}"
            rec = reserve_ip(ip, vm_name, owner=owner, ttl_minutes=ttl_minutes)
            results.append(rec)
            logger.info(f"📌 预留 IP {ip} → {vm_name}")
        return results


# ============================================================
# CLI
# ============================================================

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="IP 池管理工具")
    sub = parser.add_subparsers(dest="cmd")

    p_parse = sub.add_parser("parse", help="解析 IP 段 → 候选列表")
    p_parse.add_argument("spec")
    p_parse.add_argument("--limit", type=int, default=20)

    p_avail = sub.add_parser("available", help="查可用 IP（排除预留+在线）")
    p_avail.add_argument("spec")
    p_avail.add_argument("--limit", type=int, default=10)
    p_avail.add_argument("--skip-alive", action="store_true", default=True)
    p_avail.add_argument("--no-skip-alive", action="store_false", dest="skip_alive")

    p_alloc = sub.add_parser("allocate", help="分配并预留 IP")
    p_alloc.add_argument("spec")
    p_alloc.add_argument("--count", type=int, required=True)
    p_alloc.add_argument("--prefix", default="vm-")
    p_alloc.add_argument("--ttl", type=int, default=60, help="预留 TTL（分钟）")

    p_reserve = sub.add_parser("reservations", help="查看所有预留")
    p_release = sub.add_parser("release", help="释放某 IP")
    p_release.add_argument("ip")
    p_cleanup = sub.add_parser("cleanup", help="清理过期预留")

    args = parser.parse_args()

    if args.cmd == "parse":
        ips = parse_pool_spec(args.spec)
        print(f"共 {len(ips)} 个候选 IP（显示前 {args.limit}）:")
        for ip in ips[:args.limit]:
            print(f"  {ip}")
    elif args.cmd == "available":
        pool = IPPool(args.spec, skip_alive=args.skip_alive)
        ips = pool.available(limit=args.limit)
        print(f"可用 IP {len(ips)} 个（共 {pool.size()} 候选）:")
        for ip in ips:
            print(f"  ✅ {ip}")
    elif args.cmd == "allocate":
        pool = IPPool(args.spec, skip_alive=True)
        recs = pool.allocate(args.count, vm_name_prefix=args.prefix, ttl_minutes=args.ttl)
        print(json.dumps(recs, ensure_ascii=False, indent=2))
    elif args.cmd == "reservations":
        recs = list_reservations()
        print(f"共 {len(recs)} 条预留:")
        for r in recs:
            exp = r.get("expires_at")
            exp_s = "永久" if not exp else f"在 {max(0, exp - int(time.time()))}s 后到期"
            print(f"  {r['ip']:18s} → {r['vm_name']:25s} | {r['owner']:10s} | {exp_s}")
    elif args.cmd == "release":
        ok = release_ip(args.ip)
        print(f"{'✅ 已释放' if ok else '⚠️ 未找到该预留'}: {args.ip}")
    elif args.cmd == "cleanup":
        n = cleanup_expired()
        print(f"清理过期预留 {n} 个")
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
