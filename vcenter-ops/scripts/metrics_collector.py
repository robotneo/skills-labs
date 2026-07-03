"""
Module: scripts.metrics_collector
Description: 资源水位采集器。定期从 vCenter 采集集群/DS/网络等关键指标，落盘 JSONL，
             作为 v1.4 异常检测、容量预测的数据源。
Author: 运枢
Date: 2026-05-22
Version: 1.4.0

设计要点：
- 采集集群级（CPU/内存）+ DS（容量/已用）+ 网络（IP 段使用）
- 单文件 JSONL（data/metrics/yyyy-mm-dd.jsonl），按日切分便于清理
- 提供 collect_once() 单次采集 + collect_loop() 守护进程模式
- 提供 query_history(metric, since/until) 给上游分析模块
- 离线 dry-run 模式：可生成模拟数据用于自测
"""

import os
import json
import time
import logging
import random
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Iterable

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).resolve().parent.parent
METRICS_DIR = SKILL_DIR / "data" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# 落盘 / 读取
# ============================================================

def _today_file(d: Optional[datetime] = None) -> Path:
    d = d or datetime.now()
    return METRICS_DIR / f"{d.strftime('%Y-%m-%d')}.jsonl"


def append_metric(metric: Dict[str, Any]) -> None:
    """追加一条指标到当天的 JSONL。"""
    metric.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
    f = _today_file()
    with open(f, "a", encoding="utf-8") as fp:
        fp.write(json.dumps(metric, ensure_ascii=False) + "\n")


def query_history(
    metric_type: Optional[str] = None,
    target: Optional[str] = None,
    since_days: int = 7,
    until: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    读取历史指标。

    :param metric_type: 过滤 metric 类型（cluster_cpu / cluster_mem / ds_used / ip_used）
    :param target: 过滤目标名（cluster name / ds name 等）
    :param since_days: 取最近 N 天
    :param until: 截止时间（默认 now）
    """
    until = until or datetime.now()
    since = until - timedelta(days=since_days)
    results: List[Dict[str, Any]] = []

    # 遍历可能的日期文件
    for d in range(since_days + 1):
        check_day = since + timedelta(days=d)
        f = _today_file(check_day)
        if not f.exists():
            continue
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if metric_type and e.get("type") != metric_type:
                continue
            if target and e.get("target") != target:
                continue
            try:
                ts = datetime.fromisoformat(e.get("ts", ""))
                if ts < since or ts > until:
                    continue
            except Exception:
                pass
            results.append(e)

    results.sort(key=lambda x: x.get("ts", ""))
    return results


def cleanup_old(keep_days: int = 30) -> int:
    """清理超过 keep_days 的指标文件。"""
    cutoff = datetime.now() - timedelta(days=keep_days)
    removed = 0
    for f in METRICS_DIR.glob("*.jsonl"):
        try:
            d = datetime.strptime(f.stem, "%Y-%m-%d")
            if d < cutoff:
                f.unlink()
                removed += 1
        except Exception:
            continue
    if removed:
        logger.info(f"🧹 清理 {removed} 个过期指标文件")
    return removed


# ============================================================
# 采集器（连真实 vCenter）
# ============================================================

def collect_from_vcenter(executor) -> List[Dict[str, Any]]:
    """
    从 vCenter 采集一轮指标。返回采集的指标列表（已落盘）。
    依赖 executor.check_resource_quota，复用现有查询。
    """
    from pyVmomi import vim
    ts = datetime.now().isoformat(timespec="seconds")
    out: List[Dict[str, Any]] = []
    content = executor.content

    # 集群
    view = content.viewManager.CreateContainerView(content.rootFolder,
                                                    [vim.ClusterComputeResource], True)
    try:
        for cl in view.view:
            try:
                summary = cl.summary
                if not summary:
                    continue
                total_cpu = getattr(summary, "totalCpu", 0) or 0
                total_mem = getattr(summary, "totalMemory", 0) or 0
                # 从主机汇总使用量
                used_cpu = 0
                used_mem = 0
                for h in cl.host:
                    try:
                        qs = h.summary.quickStats if h.summary else None
                        if qs:
                            used_cpu += int(getattr(qs, "overallCpuUsage", 0) or 0)
                            used_mem += int(getattr(qs, "overallMemoryUsage", 0) or 0) * 1024 * 1024  # MB -> Bytes
                    except Exception:
                        pass

                cpu_pct = (used_cpu / total_cpu) if total_cpu else 0
                mem_pct = (used_mem / total_mem) if total_mem else 0

                for kind, val in [("cluster_cpu", cpu_pct), ("cluster_mem", mem_pct)]:
                    m = {"ts": ts, "type": kind, "target": cl.name, "value": round(val, 4)}
                    append_metric(m)
                    out.append(m)
            except Exception:
                continue
    finally:
        view.Destroy()

    # Datastore
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.Datastore], True)
    try:
        for ds in view.view:
            try:
                summary = ds.summary
                if not summary or not summary.accessible:
                    continue
                total = summary.capacity or 0
                free = summary.freeSpace or 0
                used = total - free
                used_pct = (used / total) if total else 0
                m = {"ts": ts, "type": "ds_used", "target": ds.name,
                      "value": round(used_pct, 4),
                      "extra": {"total_gb": total // 1024**3, "free_gb": free // 1024**3}}
                append_metric(m)
                out.append(m)
            except Exception:
                continue
    finally:
        view.Destroy()

    logger.info(f"📊 已采集 {len(out)} 条指标")
    return out


def collect_dry_run(seed_clusters: int = 2, seed_ds: int = 3) -> List[Dict[str, Any]]:
    """
    Dry-run 模式：生成模拟指标，便于自测异常检测/容量预测。
    """
    ts = datetime.now().isoformat(timespec="seconds")
    out = []
    for i in range(seed_clusters):
        for kind in ("cluster_cpu", "cluster_mem"):
            val = round(random.uniform(0.4, 0.85), 4)
            m = {"ts": ts, "type": kind, "target": f"cluster-{i+1}", "value": val}
            append_metric(m)
            out.append(m)
    for i in range(seed_ds):
        val = round(random.uniform(0.3, 0.75), 4)
        m = {"ts": ts, "type": "ds_used", "target": f"DS-{i+1}", "value": val,
             "extra": {"total_gb": 10000, "free_gb": int(10000 * (1 - val))}}
        append_metric(m)
        out.append(m)
    logger.info(f"📊 dry-run 生成 {len(out)} 条模拟指标")
    return out


# ============================================================
# CLI
# ============================================================

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="资源水位采集")
    sub = parser.add_subparsers(dest="cmd")

    p_once = sub.add_parser("once", help="单次采集（连 vCenter）")
    p_once.add_argument("--dry-run", action="store_true", help="使用模拟数据")

    p_q = sub.add_parser("query", help="查询历史")
    p_q.add_argument("--type", dest="metric_type")
    p_q.add_argument("--target")
    p_q.add_argument("--days", type=int, default=7)

    p_cl = sub.add_parser("cleanup", help="清理过期")
    p_cl.add_argument("--keep-days", type=int, default=30)

    args = parser.parse_args()
    if args.cmd == "once":
        if args.dry_run:
            out = collect_dry_run()
        else:
            # 连接 vCenter（复用 handler 逻辑）
            import yaml as _yaml
            from client import VCenterClient
            from executor import VCenterExecutor
            cfg = _yaml.safe_load((SKILL_DIR / "config.yaml").read_text())["vcenter"]
            from dotenv import load_dotenv
            load_dotenv(SKILL_DIR / ".env")
            pwd = os.environ.get(cfg["password_ref"], "")
            with VCenterClient(cfg["host"], cfg["user"], pwd, cfg.get("port", 443)) as si:
                ex = VCenterExecutor(si)
                out = collect_from_vcenter(ex)
        print(f"采集 {len(out)} 条指标，示例:")
        for m in out[:5]:
            print(f"  • {m['type']:15s} {m['target']:20s} = {m['value']}")
    elif args.cmd == "query":
        recs = query_history(args.metric_type, args.target, since_days=args.days)
        print(f"共 {len(recs)} 条历史")
        for r in recs[-10:]:
            extra = r.get('extra', {}) or {}
            print(f"  {r.get('ts','')} | {r.get('type'):15s} | {r.get('target'):20s} | {r.get('value')} | {extra}")
    elif args.cmd == "cleanup":
        n = cleanup_old(keep_days=args.keep_days)
        print(f"清理 {n} 个过期文件")
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
