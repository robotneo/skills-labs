#!/usr/bin/env python3
"""
Module: scripts.cache_manager
Description: vCenter 数据会话缓存管理器。
功能：
1. 首次查询 vCenter 后将全量数据保存到本地 JSON。
2. 后续查询优先从本地读取。
3. 大幅减少 API 调用次数（30s → <1s），降低 token 消耗。

Author: xiaofei
Date: 2026-03-21

使用方式：
  # 首次查询（API 调用，约 30s）
  python3 scripts/cache_manager.py --refresh

  # 读取缓存（本地 JSON，<1s）
  python3 scripts/cache_manager.py

  # 提取摘要（仅关键统计，最少 token）
  python3 scripts/cache_manager.py --summary

  # 提取指定类别
  python3 scripts/cache_manager.py --section templates
  python3 scripts/cache_manager.py --section hosts --cluster "共享存储"
  python3 scripts/cache_manager.py --section datastores --top 10

  # 检查缓存状态
  python3 scripts/cache_manager.py --status

  # 按条件搜索 VM
  python3 scripts/cache_manager.py --search "nginx"
  python3 scripts/cache_manager.py --search "172.17.40" --section vms

缓存文件：
  /tmp/vc_session_cache.json  — 全量数据
  /tmp/vc_session_meta.json   — 元信息（时间、统计）
"""

import json
import os
import sys
import time
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

# 缓存路径
CACHE_DIR = Path("/tmp")
CACHE_FILE = CACHE_DIR / "vc_session_cache.json"
META_FILE = CACHE_DIR / "vc_session_meta.json"
LOG_FILE = CACHE_DIR / "vc_cache.log"

# 缓存有效期（秒），0 = 不自动过期，需手动刷新
CACHE_TTL = 0

logger = logging.getLogger("cache_manager")

# ============================================================
# 核心读写
# ============================================================

def save_cache(data: Dict, source: str = "list_all") -> Dict:
    """保存全量数据到缓存。"""
    now = datetime.now()
    meta = {
        "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "updated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "source": source,
        "stats": {
            "vms": len(data.get("data", {}).get("vms", [])),
            "hosts": len(data.get("data", {}).get("hosts", [])),
            "templates": len(data.get("data", {}).get("templates", [])),
            "datastores": len(data.get("data", {}).get("datastores", [])),
            "clusters": len(data.get("data", {}).get("clusters", [])),
            "networks": len(data.get("data", {}).get("networks", [])),
        },
        "file_size_kb": 0,
    }

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

    meta["file_size_kb"] = round(os.path.getsize(CACHE_FILE) / 1024, 1)

    with open(META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    logger.info(f"缓存已保存: {meta['stats']}, {meta['file_size_kb']}KB")
    return meta


def load_cache() -> Optional[Dict]:
    """加载全量缓存数据。"""
    if not CACHE_FILE.exists():
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"缓存读取失败: {e}")
        return None


def load_meta() -> Optional[Dict]:
    """加载缓存元信息。"""
    if not META_FILE.exists():
        return None
    try:
        with open(META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def is_cache_valid() -> bool:
    """检查缓存是否有效。"""
    if not CACHE_FILE.exists():
        return False
    if CACHE_TTL > 0:
        mtime = os.path.getmtime(CACHE_FILE)
        return (time.time() - mtime) < CACHE_TTL
    return True  # TTL=0 时不自动过期


# ============================================================
# 数据提取（按需读取，减少 token 消耗）
# ============================================================

def extract_section(data: Dict, section: str, **filters) -> Dict:
    """从全量缓存中提取指定类别的数据，返回精简结构。"""

    result = {"status": "ok", "section": section, "items": [], "total": 0}

    if not data or "data" not in data:
        result["status"] = "no_cache"
        return result

    d = data["data"]

    if section == "templates":
        items = d.get("templates", [])
        result["items"] = [
            {
                "name": t["metadata"]["name"],
                "guest_os": t["metadata"]["guest_os"],
                "cpu": t["hardware"]["cpu_cores"],
                "ram_gb": t["hardware"]["ram_gb"],
                "disk_gb": t["hardware"]["disk_gb"],
            }
            for t in items
        ]

    elif section == "clusters":
        items = d.get("clusters", [])
        result["items"] = [
            {"name": c["name"], "status": c["overall_status"]}
            for c in items
        ]

    elif section == "datastores":
        items = d.get("datastores", [])
        # 过滤小容量本地盘
        items = [ds for ds in items if ds["total_gb"] >= 1000]
        items.sort(key=lambda x: x["free_gb"], reverse=True)
        top_n = filters.get("top", len(items))
        result["items"] = [
            {
                "name": ds["name"],
                "total_gb": round(ds["total_gb"], 0),
                "free_gb": round(ds["free_gb"], 0),
                "free_percent": round(ds["free_percent"], 1),
                "is_low_space": ds.get("is_low_space", False),
            }
            for ds in items[:top_n]
        ]

    elif section == "networks":
        result["items"] = [{"name": n} for n in d.get("networks", [])]

    elif section == "hosts":
        items = d.get("hosts", [])
        # 可选集群过滤
        cluster = filters.get("cluster")
        if cluster:
            items = [h for h in items if h.get("cluster_parent") == cluster]
        # 排除不可用
        items = [
            h for h in items
            if not h.get("maintenance_mode") and h.get("power_state") == "poweredOn"
        ]
        # 计算评分
        mx = max((h.get("vm_count", 0) for h in items), default=1) or 1
        for h in items:
            score = (
                h.get("cpu_free_pct", 0) * 0.4
                + h.get("memory_free_pct", 0) * 0.35
                + ((mx - h.get("vm_count", 0)) / mx * 100) * 0.25
            )
            h["_score"] = round(score, 1)
        items.sort(key=lambda x: x["_score"], reverse=True)
        top_n = filters.get("top", len(items))
        result["items"] = [
            {
                "name": h["name"],
                "cluster": h.get("cluster_parent", ""),
                "cpu_free_pct": round(h.get("cpu_free_pct", 0), 1),
                "mem_free_pct": round(h.get("memory_free_pct", 0), 1),
                "vm_count": h.get("vm_count", 0),
                "score": h["_score"],
            }
            for h in items[:top_n]
        ]

    elif section == "vms":
        items = d.get("vms", [])
        keyword = filters.get("keyword", "")
        if keyword:
            items = [
                v for v in items
                if keyword.lower() in v["metadata"]["name"].lower()
            ]
        result["items"] = [
            {
                "name": v["metadata"]["name"],
                "power": v["runtime"]["power_state"],
                "ip": v["runtime"]["ip_address"],
                "host": v["runtime"]["host_node"],
                "cpu": v["hardware"]["cpu_cores"],
                "ram_gb": v["hardware"]["ram_gb"],
                "disk_gb": round(v["hardware"]["disk_gb"], 1),
            }
            for v in items
        ]

    elif section == "vm_ips":
        """提取全量 VM IP（含名称提取），用于 IP 扫描排除。"""
        import re
        ip_pattern = re.compile(r"^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")
        ips = set()
        for vm in d.get("vms", []):
            ip = vm["runtime"]["ip_address"]
            if ip and ip != "N/A":
                ips.add(ip)
            m = ip_pattern.match(vm["metadata"]["name"])
            if m:
                ips.add(m.group(1))
        result["items"] = sorted(ips)
        result["count"] = len(ips)

    result["total"] = len(result["items"])
    return result


def extract_summary(data: Dict) -> Dict:
    """提取极简摘要，最小 token 消耗。"""
    if not data or "data" not in data:
        return {"status": "no_cache"}

    d = data["data"]
    hosts = d.get("hosts", [])
    avail_hosts = [
        h for h in hosts
        if not h.get("maintenance_mode") and h.get("power_state") == "poweredOn"
    ]

    return {
        "status": "ok",
        "datacenters": d.get("datacenters", []),
        "clusters": [c["name"] for c in d.get("clusters", [])],
        "templates": len(d.get("templates", [])),
        "datastores": len(d.get("datastores", [])),
        "networks": len(d.get("networks", [])),
        "hosts": {"total": len(hosts), "available": len(avail_hosts), "maintenance": sum(1 for h in hosts if h.get("maintenance_mode"))},
        "vms": {"total": len(d.get("vms", []))},
    }


def search_vms(data: Dict, keyword: str) -> Dict:
    """搜索 VM（按名称/IP）。"""
    if not data or "data" not in data:
        return {"status": "no_cache", "results": []}

    keyword = keyword.lower()
    results = []
    for vm in data["data"].get("vms", []):
        name = vm["metadata"]["name"].lower()
        ip = vm["runtime"]["ip_address"].lower()
        if keyword in name or keyword in ip:
            results.append({
                "name": vm["metadata"]["name"],
                "power": vm["runtime"]["power_state"],
                "ip": vm["runtime"]["ip_address"],
                "host": vm["runtime"]["host_node"],
                "cpu": vm["hardware"]["cpu_cores"],
                "ram_gb": vm["hardware"]["ram_gb"],
                "disk_gb": round(vm["hardware"]["disk_gb"], 1),
            })

    return {"status": "ok", "keyword": keyword, "count": len(results), "results": results[:20]}


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="vCenter 会话缓存管理器")
    parser.add_argument("--refresh", action="store_true", help="强制刷新缓存（调用 API）")
    parser.add_argument("--summary", action="store_true", help="输出极简摘要")
    parser.add_argument("--section", choices=["templates", "clusters", "datastores", "networks", "hosts", "vms", "vm_ips"],
                        help="提取指定类别")
    parser.add_argument("--cluster", help="按集群筛选（配合 --section hosts）")
    parser.add_argument("--top", type=int, default=0, help="返回前 N 条（0=全部）")
    parser.add_argument("--search", help="搜索 VM（按名称/IP）")
    parser.add_argument("--status", action="store_true", help="检查缓存状态")

    args = parser.parse_args()

    # --- 状态检查 ---
    if args.status:
        meta = load_meta()
        if not meta:
            print(json.dumps({"cached": False, "message": "无缓存，请执行 --refresh"}, ensure_ascii=False))
            return
        print(json.dumps({"cached": True, **meta}, ensure_ascii=False, indent=2))
        return

    # --- 刷新缓存 ---
    if args.refresh:
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from scripts.handler import main as handler_main
        from scripts.client import VCenterClient
        from scripts.inventory import VCenterInventory
        import yaml

        with open(Path(__file__).parent.parent / "config.yaml") as f:
            cfg = yaml.safe_load(f)
        vc = cfg["vcenter"]

        with VCenterClient(vc["host"], vc["user"], vc["password"]) as si:
            inventory = VCenterInventory(si)
            data = inventory.fetch_all_inventory()

        report = {"status": "success", "data": data}
        meta = save_cache(report)
        print(json.dumps({"status": "refreshed", "meta": meta}, ensure_ascii=False, indent=2))
        return

    # --- 读取缓存 ---
    data = load_cache()
    if not data:
        print(json.dumps({"status": "no_cache", "message": "缓存不存在，请先执行 --refresh"}, ensure_ascii=False))
        return

    filters = {}
    if args.cluster:
        filters["cluster"] = args.cluster
    if args.top > 0:
        filters["top"] = args.top

    # --- 搜索 ---
    if args.search:
        result = search_vms(data, args.search)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # --- 摘要 ---
    if args.summary:
        result = extract_summary(data)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # --- 指定类别 ---
    if args.section:
        result = extract_section(data, args.section, **filters)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # --- 默认：输出摘要 ---
    meta = load_meta()
    result = extract_summary(data)
    result["cached_at"] = meta.get("updated_at", "unknown") if meta else "unknown"
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
