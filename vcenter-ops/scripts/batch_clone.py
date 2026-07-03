"""
Module: scripts.batch_clone
Description: 批量克隆引擎。并行创建多台 VM，支持 IP 池、限额、进度汇总。
Author: 运枢
Date: 2026-05-22
Version: 1.1.0

设计要点：
- 基于 executor.clone_vm_advanced 的并行包装
- 支持 IP 池自动分配（ip_pool.py）或手动列表
- 并发度控制（默认 3 并行，避免 vCenter 过载）
- 实时进度汇总 + 最终结果统计
- 失败不阻断：记录失败项，最后汇总，部分成功部分失败可重试
"""

import time
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List, Callable

from pyVmomi import vim

try:
    from .executor import VCenterExecutor
    from .ip_pool import IPPool, reserve_ip, release_ip
    from .progress_reporter import ProgressReporter, stdout_sink
    from .error_dictionary import format_error_oneline
except ImportError:
    from executor import VCenterExecutor
    from ip_pool import IPPool, reserve_ip, release_ip
    from progress_reporter import ProgressReporter, stdout_sink
    from error_dictionary import format_error_oneline

logger = logging.getLogger(__name__)


class CloneSpec:
    """单次克隆的完整参数。"""

    def __init__(
        self,
        template_name: str,
        new_name: str,
        dc_name: str,
        cluster_name: str,
        ds_name: str,
        network_name: str,
        host_name: Optional[str] = None,
        cpus: Optional[int] = None,
        memory_gb: Optional[int] = None,
        disk_gb: Optional[int] = None,
        ip_address: Optional[str] = None,
        subnet: str = "255.255.255.0",
        gateway: Optional[str] = None,
    ):
        self.template_name = template_name
        self.new_name = new_name
        self.dc_name = dc_name
        self.cluster_name = cluster_name
        self.ds_name = ds_name
        self.network_name = network_name
        self.host_name = host_name
        self.cpus = cpus
        self.memory_gb = memory_gb
        self.disk_gb = disk_gb
        self.ip_address = ip_address
        self.subnet = subnet
        self.gateway = gateway

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if v is not None}


# ============================================================
# 规格生成器
# ============================================================

def generate_clone_specs(
    template_name: str,
    dc_name: str,
    cluster_name: str,
    ds_name: str,
    network_name: str,
    host_name: Optional[str] = None,
    cpus: Optional[int] = None,
    memory_gb: Optional[int] = None,
    disk_gb: Optional[int] = None,
    subnet: str = "255.255.255.0",
    gateway: Optional[str] = None,
    # 批量参数
    count: int = 1,
    name_prefix: str = "vm-",
    name_start: int = 1,
    ip_pool_spec: Optional[str] = None,
    ip_list: Optional[List[str]] = None,
    ip_reserve_ttl: int = 60,
) -> List[CloneSpec]:
    """
    生成批量克隆规格列表。

    :param count: 克隆总数
    :param name_prefix: VM 名前缀，最终名 = {prefix}{start+i:02d}
    :param name_start: 编号起始（默认 1）
    :param ip_pool_spec: IP 池声明（CIDR/范围），自动分配
    :param ip_list: 手动 IP 列表（优先于 ip_pool_spec）
    :param ip_reserve_ttl: IP 预留 TTL（分钟），默认 60
    """
    if count <= 0:
        raise ValueError("count 必须 > 0")
    if count > 50:
        raise ValueError("单次批量克隆上限 50 台，请分批执行")

    # IP 分配
    ips: List[Optional[str]] = [None] * count
    if ip_list:
        if len(ip_list) < count:
            raise ValueError(f"手动 IP 列表 ({len(ip_list)}) 少于 count ({count})")
        ips = ip_list[:count]
    elif ip_pool_spec:
        pool = IPPool(ip_pool_spec, skip_alive=True)
        allocated = pool.allocate(count, vm_name_prefix=name_prefix, ttl_minutes=ip_reserve_ttl)
        ips = [a["ip"] for a in allocated]

    specs: List[CloneSpec] = []
    for i in range(count):
        specs.append(CloneSpec(
            template_name=template_name,
            new_name=f"{name_prefix}{name_start + i:02d}",
            dc_name=dc_name,
            cluster_name=cluster_name,
            ds_name=ds_name,
            network_name=network_name,
            host_name=host_name,
            cpus=cpus,
            memory_gb=memory_gb,
            disk_gb=disk_gb,
            ip_address=ips[i],
            subnet=subnet,
            gateway=gateway,
        ))
    return specs


# ============================================================
# 执行引擎
# ============================================================

def batch_clone(
    executor: VCenterExecutor,
    specs: List[CloneSpec],
    max_workers: int = 3,
    wait_tools: bool = True,
    tools_timeout: int = 300,
    on_vm_done: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """
    并行批量克隆。

    :param executor: VCenterExecutor 实例（需已连接）
    :param specs: 克隆规格列表
    :param max_workers: 最大并行数（默认 3，建议 1~5）
    :param wait_tools: 是否等待 Tools 就绪
    :param tools_timeout: Tools 等待超时
    :param on_vm_done: 每个 VM 完成时的回调（成功/失败均触发）
    :return: {"total": N, "success": M, "failed": K, "results": [...]}
    """
    total = len(specs)
    results: List[Dict[str, Any]] = []
    lock = threading.Lock()

    def _clone_one(spec: CloneSpec) -> Dict[str, Any]:
        rec: Dict[str, Any] = {
            "vm_name": spec.new_name,
            "ip": spec.ip_address,
            "status": "pending",
            "message": "",
            "elapsed": 0,
        }
        t0 = time.time()
        try:
            msg = executor.clone_vm_advanced(
                template_name=spec.template_name,
                new_name=spec.new_name,
                dc_name=spec.dc_name,
                cluster_name=spec.cluster_name,
                ds_name=spec.ds_name,
                network_name=spec.network_name,
                host_name=spec.host_name,
                cpus=spec.cpus,
                memory_gb=spec.memory_gb,
                disk_gb=spec.disk_gb,
                ip_address=spec.ip_address,
                subnet=spec.subnet,
                gateway=spec.gateway,
                wait_tools=wait_tools,
                tools_timeout=tools_timeout,
            )
            rec["status"] = "success"
            rec["message"] = msg
        except Exception as e:
            rec["status"] = "error"
            rec["message"] = format_error_oneline(e, op_name=f"克隆 {spec.new_name}")
            # IP 预留释放（失败不占用）
            if spec.ip_address:
                try:
                    release_ip(spec.ip_address)
                except Exception:
                    pass
        rec["elapsed"] = round(time.time() - t0, 1)

        if on_vm_done:
            try:
                on_vm_done(rec)
            except Exception:
                pass

        return rec

    logger.info(f"🚀 批量克隆启动：{total} 台，并行度 {max_workers}")
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_clone_one, s): s for s in specs}
        for future in as_completed(futures):
            rec = future.result()
            with lock:
                results.append(rec)
            status_icon = "✅" if rec["status"] == "success" else "❌"
            logger.info(f"  {status_icon} {rec['vm_name']} ({rec['elapsed']}s): {rec['message'][:80]}")

    # 排序保持原始顺序
    name_order = {s.new_name: i for i, s in enumerate(specs)}
    results.sort(key=lambda r: name_order.get(r["vm_name"], 999))

    success_count = sum(1 for r in results if r["status"] == "success")
    failed_count = sum(1 for r in results if r["status"] == "error")

    summary = {
        "total": total,
        "success": success_count,
        "failed": failed_count,
        "results": results,
    }
    logger.info(f"🏁 批量克隆完成：{success_count}/{total} 成功，{failed_count} 失败")
    return summary


def format_batch_summary(summary: Dict[str, Any]) -> str:
    """渲染批量克隆结果为 markdown。"""
    lines = [
        f"## 批量克隆结果",
        f"**总数**: {summary['total']} | **成功**: {summary['success']} | **失败**: {summary['failed']}",
        "",
        "| # | VM 名 | IP | 状态 | 耗时 | 信息 |",
        "|---|-------|------|------|------|------|",
    ]
    for i, r in enumerate(summary.get("results", []), 1):
        icon = "✅" if r["status"] == "success" else "❌"
        lines.append(
            f"| {i} | {r['vm_name']} | {r.get('ip') or '-'} | "
            f"{icon} {r['status']} | {r.get('elapsed', 0)}s | {r['message'][:60]} |"
        )
    if summary["failed"] > 0:
        lines.append("")
        lines.append("⚠️ 失败项可使用 `--retry-failed` 重试（待实现）")
    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="批量克隆 CLI（测试用）")
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--template", required=True)
    parser.add_argument("--dc", required=True)
    parser.add_argument("--cluster", required=True)
    parser.add_argument("--ds", required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--prefix", default="batch-")
    parser.add_argument("--cpu", type=int)
    parser.add_argument("--memory", type=int)
    parser.add_argument("--disk", type=int)
    parser.add_argument("--ip-pool", dest="ip_pool", help="IP 池（CIDR/范围）")
    parser.add_argument("--gw")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()

    specs = generate_clone_specs(
        template_name=args.template,
        dc_name=args.dc,
        cluster_name=args.cluster,
        ds_name=args.ds,
        network_name=args.network,
        cpus=args.cpu,
        memory_gb=args.memory,
        disk_gb=args.disk,
        count=args.count,
        name_prefix=args.prefix,
        ip_pool_spec=args.ip_pool,
        gateway=args.gw,
    )
    print(f"生成了 {len(specs)} 个克隆规格（dry-run，未连接 vCenter）:")
    for s in specs:
        print(f"  • {s.new_name}: IP={s.ip_address or '-'} | {s.cpus or '默认'}C/{s.memory_gb or '默认'}G")


if __name__ == "__main__":
    _cli()
