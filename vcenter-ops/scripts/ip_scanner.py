#!/usr/bin/env python3
"""
Module: scripts/ip_scanner
Description: 基于 ICMP Ping 的网段 IP 可用性扫描工具。
支持并发扫描、结果缓存，输出标准 JSON。
Author: xiaofei
Date: 2026-03-20
"""

import sys
import json
import argparse
import subprocess
import ipaddress
import logging
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Tuple

# 日志输出至 stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# 默认配置
DEFAULT_CIDR = "172.17.40.0/23"
DEFAULT_TIMEOUT = 1        # ping 超时（秒）
DEFAULT_WORKERS = 64       # 并发线程数
DEFAULT_COUNT = 2          # 每个IP ping 次数
SCAN_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"


def ping_host(ip: str, timeout: int = DEFAULT_TIMEOUT, count: int = DEFAULT_COUNT) -> Tuple[str, bool, float]:
    """
    对单个 IP 执行 ping 测试。
    返回 (ip, is_reachable, avg_latency_ms)
    """
    try:
        cmd = ["ping", "-c", str(count), "-W", str(timeout), ip]
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout * count + 2
        )
        reachable = result.returncode == 0

        # 解析延迟
        latency = -1.0
        if reachable:
            for line in result.stdout.decode().splitlines():
                if "min/avg/max" in line:
                    parts = line.split("=")[-1].strip().split("/")
                    try:
                        latency = float(parts[1])
                    except (IndexError, ValueError):
                        pass

        return (ip, reachable, latency)
    except subprocess.TimeoutExpired:
        return (ip, False, -1.0)
    except Exception:
        return (ip, False, -1.0)


def scan_network(cidr: str, workers: int = DEFAULT_WORKERS,
                 timeout: int = DEFAULT_TIMEOUT, count: int = DEFAULT_COUNT,
                 skip_reserved: bool = True) -> Dict:
    """
    扫描整个网段，返回可用/不可用 IP 列表。
    """
    network = ipaddress.ip_network(cidr, strict=False)
    total_hosts = network.num_addresses

    # 生成 IP 列表（跳过网络地址和广播地址）
    hosts = [str(ip) for ip in network.hosts()]
    if skip_reserved:
        # 跳过网关（通常为 .1）
        hosts = [ip for ip in hosts if not ip.endswith(".1")]

    logger.info(f"开始扫描网段 {cidr}，共 {len(hosts)} 个地址，并发 {workers}")

    available = []
    unreachable = []
    scanned = 0

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(ping_host, ip, timeout, count): ip for ip in hosts}
        for future in as_completed(futures):
            scanned += 1
            if scanned % 50 == 0 or scanned == len(hosts):
                logger.info(f"扫描进度: {scanned}/{len(hosts)}")

            ip, reachable, latency = future.result()
            entry = {
                "ip": ip,
                "latency_ms": round(latency, 1) if latency >= 0 else None
            }
            if reachable:
                # ping 通 = 已占用
                unreachable.append(entry)
            else:
                # ping 不通 = 可用
                available.append(entry)

    # 按 IP 从小到大排序
    available.sort(key=lambda x: tuple(int(p) for p in x["ip"].split(".")))
    unreachable.sort(key=lambda x: tuple(int(p) for p in x["ip"].split(".")))

    report = {
        "status": "success",
        "cidr": cidr,
        "total": len(hosts),
        "scanned": scanned,
        "available": available,
        "unavailable": unreachable,
        "available_count": len(available),
        "unavailable_count": len(unreachable),
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    logger.info(f"扫描完成: 可用 {len(available)} / 不可用 {len(unreachable)} / 总计 {len(hosts)}")
    return report


def save_cache(report: Dict, cidr: str) -> Path:
    """保存扫描结果到缓存文件。"""
    SCAN_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = cidr.replace("/", "_")
    cache_file = SCAN_CACHE_DIR / f"scan_{safe_name}.json"
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"扫描结果已缓存: {cache_file}")
    return cache_file


def load_cache(cidr: str, max_age_minutes: int = 30) -> Dict:
    """加载缓存结果，超时则返回空。"""
    safe_name = cidr.replace("/", "_")
    cache_file = SCAN_CACHE_DIR / f"scan_{safe_name}.json"
    if not cache_file.exists():
        return {}

    try:
        import time
        mtime = cache_file.stat().st_mtime
        age = (time.time() - mtime) / 60
        if age > max_age_minutes:
            logger.info(f"缓存已过期（{age:.0f} 分钟），需重新扫描")
            return {}

        with open(cache_file, "r", encoding="utf-8") as f:
            report = json.load(f)
        logger.info(f"已加载缓存: {cache_file}（{age:.0f} 分钟前）")
        return report
    except Exception as e:
        logger.warning(f"读取缓存失败: {e}")
        return {}


def find_available_ip(report: Dict, preferred_ip: str = None) -> Dict:
    """
    从扫描结果中找可用 IP。
    如果指定了 preferred_ip，检查该 IP 是否可用。
    否则返回第一个可用 IP。
    """
    if not report:
        return {"available": False, "ip": None, "message": "无扫描数据"}

    # 检查指定 IP
    if preferred_ip:
        for entry in report.get("available", []):
            if entry["ip"] == preferred_ip:
                return {"available": True, "ip": preferred_ip, "latency_ms": entry["latency_ms"]}
        return {"available": False, "ip": preferred_ip, "message": f"IP {preferred_ip} 已被占用或不可达"}

    # 返回第一个可用 IP
    avail = report.get("available", [])
    if avail:
        return {"available": True, "ip": avail[0]["ip"], "latency_ms": avail[0]["latency_ms"]}
    return {"available": False, "ip": None, "message": "该网段无可用 IP"}


def main():
    parser = argparse.ArgumentParser(description="IP 网段扫描工具")
    parser.add_argument("--cidr", default=DEFAULT_CIDR, help=f"扫描网段（默认: {DEFAULT_CIDR}）")
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="并发线程数")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="ping 超时秒数")
    parser.add_argument("--count", type=int, default=DEFAULT_COUNT, help="每个IP ping 次数")
    parser.add_argument("--check", help="仅检查指定 IP 是否可用（快速模式）")
    parser.add_argument("--exclude-ips", help="排除的 IP 列表（逗号分隔），如 '10.0.0.1,10.0.0.2'")
    parser.add_argument("--exclude-file", help="排除的 IP 列表文件路径（每行一个 IP）")
    parser.add_argument("--use-cache", action="store_true", help="优先使用缓存（30分钟内有效）")
    parser.add_argument("--cache-only", action="store_true", help="仅读取缓存，不扫描")

    args = parser.parse_args()

    response = {"status": "success", "data": None, "message": ""}

    try:
        # 快速检查单个 IP
        if args.check:
            ip, reachable, latency = ping_host(args.check, args.timeout, args.count)
            response["data"] = {
                "ip": ip,
                "available": not reachable,  # ping 不通 = 可分配
                "reachable": reachable,
                "latency_ms": round(latency, 1) if latency >= 0 else None
            }
            response["message"] = f"IP {ip}: {'已被占用' if reachable else '可用'}"
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return

        # 仅缓存模式
        if args.cache_only:
            cached = load_cache(args.cidr)
            if cached:
                response["data"] = cached
                response["message"] = "已加载缓存数据"
            else:
                response["status"] = "fail"
                response["message"] = "无有效缓存，请先执行扫描"
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return

        # 尝试加载缓存
        if args.use_cache:
            cached = load_cache(args.cidr)
            if cached:
                response["data"] = cached
                response["message"] = "已加载缓存（30分钟内有效）"
                print(json.dumps(response, ensure_ascii=False, indent=2))
                return

        # 执行全量扫描
        report = scan_network(args.cidr, args.workers, args.timeout, args.count)

        # 排除指定 IP（如集群下已有 VM 使用的 IP）
        exclude_set = set()
        if args.exclude_ips:
            exclude_set.update(ip.strip() for ip in args.exclude_ips.split(",") if ip.strip())
        if args.exclude_file:
            try:
                with open(args.exclude_file) as f:
                    exclude_set.update(line.strip() for line in f if line.strip())
            except Exception as e:
                logger.warning(f"读取排除文件失败: {e}")

        if exclude_set:
            before_count = len(report["available"])
            report["available"] = [ip for ip in report["available"] if ip["ip"] not in exclude_set]
            report["available_count"] = len(report["available"])
            report["excluded_count"] = before_count - len(report["available"])
            report["excluded_ips"] = sorted(exclude_set, key=lambda x: tuple(int(p) for p in x.split(".")))
            logger.info(f"已排除 {report['excluded_count']} 个 IP（集群已有 VM 占用）")
        save_cache(report, args.cidr)
        response["data"] = report
        response["message"] = f"扫描完成: 可用 {report['available_count']} 个 IP"

    except Exception as e:
        logger.error(f"扫描异常: {e}", exc_info=True)
        response["status"] = "error"
        response["message"] = f"扫描异常: {e}"

    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
