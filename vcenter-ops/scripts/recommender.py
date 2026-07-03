"""
Module: scripts.recommender
Description: 资源推荐引擎。基于宿主机负载、DS 空闲、IP 余量、亲和性，给出 Top-N 推荐 + 评分。
Author: 运枢
Date: 2026-05-22
Version: 1.4.0

设计要点：
- 多因子综合评分（0-100）：
    cluster_load * 40%  +  ds_free * 30%  +  ip_avail * 20%  +  affinity * 10%
- 输入：克隆请求（cpus/memory_gb/disk_gb/可选 IP 段）
- 输出：Top-N 推荐 [{cluster, host, ds, network, score, reasons}]
- 数据源：executor inventory + metrics_collector 历史
- 亲和性：相同前缀的 VM 尽量分散（防止单点）
"""

import logging
from typing import Optional, Dict, Any, List

try:
    from .metrics_collector import query_history
except ImportError:
    from metrics_collector import query_history

logger = logging.getLogger(__name__)


# ============================================================
# 评分子函数
# ============================================================

def _score_cluster_load(usage_pct: float) -> float:
    """
    集群负载评分：使用率越低分越高。
    0% → 100 分，90% → 10 分，100% → 0 分
    """
    if usage_pct >= 1.0:
        return 0
    return round((1 - usage_pct) * 100, 1)


def _score_ds_free(free_gb: float, requested_gb: float) -> float:
    """
    DS 容量评分：剩余 >= 请求 3x → 100 分；2x → 60；<1x → 0
    """
    if requested_gb <= 0 or free_gb < requested_gb:
        return 0 if free_gb < requested_gb else 50
    ratio = free_gb / requested_gb
    if ratio >= 3:
        return 100
    if ratio >= 2:
        return 70
    if ratio >= 1.5:
        return 50
    return 30


def _score_ip_availability(avail: int, requested: int) -> float:
    """
    IP 余量评分：剩余 >= 请求 5x → 100；3x → 70；<1x → 0
    """
    if avail < requested:
        return 0
    ratio = avail / max(requested, 1)
    if ratio >= 5:
        return 100
    if ratio >= 3:
        return 70
    if ratio >= 2:
        return 50
    return 30


def _score_affinity(same_prefix_count: int, total: int) -> float:
    """
    亲和性评分：同前缀越分散越好。
    单宿主机同前缀比例 < 20% → 100；30% → 70；50%+ → 30
    """
    if total <= 0:
        return 100
    ratio = same_prefix_count / total
    if ratio < 0.2:
        return 100
    if ratio < 0.3:
        return 70
    if ratio < 0.5:
        return 50
    return 30


# ============================================================
# 推荐主流程
# ============================================================

def recommend(
    executor,
    cpus: int,
    memory_gb: int,
    disk_gb: int,
    name_prefix: str = "",
    target_count: int = 1,
    top_n: int = 3,
    weights: Optional[Dict[str, float]] = None,
) -> List[Dict[str, Any]]:
    """
    生成 Top-N 资源放置推荐。

    :param executor: VCenterExecutor 实例
    :param cpus / memory_gb / disk_gb: 单 VM 资源请求
    :param name_prefix: VM 名前缀（用于亲和性分析）
    :param target_count: 计划部署的 VM 数量（用于 IP 池/容量预估）
    :param top_n: 返回前 N 个推荐
    :param weights: 评分权重，默认 cluster=0.4 ds=0.3 ip=0.2 affinity=0.1
    """
    from pyVmomi import vim

    w = weights or {"cluster": 0.4, "ds": 0.3, "ip": 0.2, "affinity": 0.1}
    content = executor.content

    # 采集候选集群 + DS + 网络
    candidates: List[Dict[str, Any]] = []

    # 1) 集群 → 主机
    cl_view = content.viewManager.CreateContainerView(
        content.rootFolder, [vim.ClusterComputeResource], True)
    cluster_infos = []
    try:
        for cl in cl_view.view:
            try:
                summary = cl.summary
                if not summary:
                    continue
                total_cpu = getattr(summary, "totalCpu", 0) or 1
                # ClusterComputeResource.Summary 不提供 usedCpu，需从主机汇总
                used_cpu = 0
                for h in cl.host:
                    try:
                        qs = h.summary.quickStats if h.summary else None
                        if qs:
                            used_cpu += int(getattr(qs, "overallCpuUsage", 0) or 0)
                    except Exception:
                        pass
                cpu_pct = used_cpu / total_cpu

                hosts = [h for h in cl.host if str(h.runtime.connectionState) == "connected"]
                cluster_infos.append({
                    "cluster": cl,
                    "name": cl.name,
                    "cpu_pct": round(cpu_pct, 3),
                    "hosts": hosts,
                })
            except Exception:
                continue
    finally:
        cl_view.Destroy()

    # 2) Datastore（按容量过滤）
    ds_view = content.viewManager.CreateContainerView(
        content.rootFolder, [vim.Datastore], True)
    ds_infos = []
    try:
        required_gb = disk_gb * target_count
        for ds in ds_view.view:
            try:
                if not ds.summary or not ds.summary.accessible:
                    continue
                total = ds.summary.capacity or 0
                free = ds.summary.freeSpace or 0
                free_gb = free // (1024**3)
                if free_gb < required_gb:
                    continue
                ds_infos.append({
                    "ds": ds,
                    "name": ds.name,
                    "free_gb": free_gb,
                    "total_gb": total // (1024**3),
                })
            except Exception:
                continue
    finally:
        ds_view.Destroy()

    # 3) 同前缀 VM 分布（亲和性）
    prefix_count_by_host: Dict[str, int] = {}
    total_same = 0
    if name_prefix:
        vm_view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim.VirtualMachine], True)
        try:
            for vm in vm_view.view:
                try:
                    if vm.config and vm.config.template:
                        continue
                    if vm.name.startswith(name_prefix):
                        total_same += 1
                        host_name = vm.runtime.host.name if vm.runtime.host else "?"
                        prefix_count_by_host[host_name] = prefix_count_by_host.get(host_name, 0) + 1
                except Exception:
                    continue
        finally:
            vm_view.Destroy()

    # 组合候选并打分
    for c_info in cluster_infos:
        if not c_info["hosts"]:
            continue
        score_cluster = _score_cluster_load(c_info["cpu_pct"])

        for ds_info in ds_infos:
            score_ds = _score_ds_free(ds_info["free_gb"], disk_gb * target_count)
            # 选第一个未满主机
            best_host = None
            best_aff_score = 0
            for h in c_info["hosts"]:
                same = prefix_count_by_host.get(h.name, 0)
                aff = _score_affinity(same, total_same)
                if aff > best_aff_score:
                    best_aff_score = aff
                    best_host = h.name
            if best_host is None and c_info["hosts"]:
                best_host = c_info["hosts"][0].name

            # IP 暂用占位（实际由 IP 池决定）
            score_ip = 70

            total_score = round(
                w["cluster"] * score_cluster +
                w["ds"] * score_ds +
                w["ip"] * score_ip +
                w["affinity"] * best_aff_score, 1)

            reasons = [
                f"集群 CPU 使用 {c_info['cpu_pct']*100:.1f}% (评分 {score_cluster})",
                f"DS 剩余 {ds_info['free_gb']}GB / 需 {disk_gb*target_count}GB (评分 {score_ds})",
                f"亲和性 (评分 {best_aff_score})",
            ]

            candidates.append({
                "cluster": c_info["name"],
                "host": best_host,
                "datastore": ds_info["name"],
                "score": total_score,
                "scores": {
                    "cluster_load": score_cluster,
                    "ds_free": score_ds,
                    "ip_avail": score_ip,
                    "affinity": best_aff_score,
                },
                "reasons": reasons,
                "free_gb": ds_info["free_gb"],
                "cluster_cpu_pct": c_info["cpu_pct"],
            })

    candidates.sort(key=lambda x: -x["score"])
    return candidates[:top_n]


def format_recommendations(recs: List[Dict[str, Any]]) -> str:
    if not recs:
        return "📭 暂无可推荐的资源组合"
    lines = [
        "| 排名 | 集群 | 宿主机 | Datastore | 评分 | 说明 |",
        "|------|------|--------|-----------|------|------|",
    ]
    for i, r in enumerate(recs, 1):
        reason_str = " · ".join(r["reasons"])[:60]
        lines.append(
            f"| {i} | {r['cluster']} | {r['host']} | {r['datastore']} | "
            f"**{r['score']}** | {reason_str} |"
        )
    return "\n".join(lines)


# ============================================================
# CLI（连真实 vCenter）
# ============================================================

def _cli():
    import argparse, json
    import os
    parser = argparse.ArgumentParser(description="资源推荐 CLI")
    parser.add_argument("--cpus", type=int, default=2)
    parser.add_argument("--memory", type=int, default=4)
    parser.add_argument("--disk", type=int, default=40)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--prefix", default="")
    parser.add_argument("--top", type=int, default=3)
    args = parser.parse_args()

    import yaml as _yaml
    from pathlib import Path
    from client import VCenterClient
    from executor import VCenterExecutor
    sd = Path(__file__).resolve().parent.parent
    cfg = _yaml.safe_load((sd / "config.yaml").read_text())["vcenter"]
    from dotenv import load_dotenv
    load_dotenv(sd / ".env")
    pwd = os.environ.get(cfg["password_ref"], "")
    with VCenterClient(cfg["host"], cfg["user"], pwd, cfg.get("port", 443)) as si:
        ex = VCenterExecutor(si)
        recs = recommend(ex, cpus=args.cpus, memory_gb=args.memory,
                         disk_gb=args.disk, name_prefix=args.prefix,
                         target_count=args.count, top_n=args.top)
        print(format_recommendations(recs))
        print()
        print(json.dumps(recs, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    _cli()
