"""
Module: scripts.capacity_forecaster
Description: 容量预测。基于历史数据线性回归，预测 DS/集群资源剩余天数。
Author: 运枢
Date: 2026-05-22
Version: 1.4.0

设计要点：
- 线性回归预测使用率何时到达阈值（默认 90%）
- 输出：剩余天数（days_until_full）+ 预计到达日期
- 触发 quota.breach 事件（剩余 < 30 天）到 event_bus
- 无需 numpy/scipy，纯 Python 实现
"""

import logging
import statistics
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple

try:
    from .metrics_collector import query_history
    from .event_bus import publish as bus_publish, Topics
except ImportError:
    from metrics_collector import query_history
    from event_bus import publish as bus_publish, Topics

logger = logging.getLogger(__name__)

DEFAULT_FORECAST_CONFIG: Dict[str, Any] = {
    "threshold": 0.90,          # 预测何时达到此阈值
    "min_samples": 10,          # 最少样本数
    "warning_days": 30,         # 剩余天数 <= 此值时触发预警
    "critical_days": 7,         # 剩余天数 <= 此值时触发严重预警
}


# ============================================================
# 简易线性回归
# ============================================================

def linear_regression(x: List[float], y: List[float]) -> Tuple[float, float, float]:
    """
    简易最小二乘线性回归。返回 (slope, intercept, r_squared)。
    y = slope * x + intercept
    """
    n = len(x)
    if n < 2:
        return 0, 0, 0

    mean_x = statistics.mean(x)
    mean_y = statistics.mean(y)

    ss_xy = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    ss_xx = sum((xi - mean_x) ** 2 for xi in x)
    ss_yy = sum((yi - mean_y) ** 2 for yi in y)

    if ss_xx == 0:
        return 0, mean_y, 0

    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x

    r_squared = (ss_xy ** 2 / (ss_xx * ss_yy)) if ss_yy else 0
    return slope, intercept, r_squared


# ============================================================
# 预测
# ============================================================

def forecast_one(
    metric_type: str,
    target: str,
    since_days: int = 30,
    threshold: float = 0.90,
    min_samples: int = 10,
) -> Dict[str, Any]:
    """
    预测某指标何时达到阈值。

    :return: {
        "metric_type": str,
        "target": str,
        "current": float,
        "slope_per_day": float,
        "r_squared": float,
        "days_until_threshold": float or None,
        "estimated_date": str or None,
        "status": "normal" / "warning" / "critical" / "insufficient_data",
    }
    """
    history = query_history(metric_type=metric_type, target=target, since_days=since_days)
    if len(history) < min_samples:
        return {
            "metric_type": metric_type, "target": target,
            "status": "insufficient_data",
            "samples": len(history),
            "message": f"样本不足 ({len(history)}/{min_samples})，无法预测",
        }

    # 提取时间轴（天为单位）和值
    ref_ts = None
    x_days: List[float] = []
    y_values: List[float] = []
    for h in history:
        try:
            ts = datetime.fromisoformat(h.get("ts", ""))
            if ref_ts is None:
                ref_ts = ts
            delta = (ts - ref_ts).total_seconds() / 86400
            x_days.append(delta)
            y_values.append(float(h.get("value") or 0))
        except Exception:
            continue

    if len(x_days) < min_samples:
        return {
            "metric_type": metric_type, "target": target,
            "status": "insufficient_data",
            "samples": len(x_days),
        }

    current = y_values[-1]
    slope, intercept, r_sq = linear_regression(x_days, y_values)

    # 计算达到阈值的天数
    days_until = None
    est_date = None
    if slope > 0:
        # y = slope * x + intercept, 求 x when y = threshold
        x_at_threshold = (threshold - intercept) / slope
        days_until = round(x_at_threshold - x_days[-1], 1)
        if days_until > 0:
            est_date = (datetime.now() + timedelta(days=days_until)).strftime("%Y-%m-%d")
        else:
            days_until = 0
            est_date = "已超过"

    # 状态
    status = "normal"
    if days_until is not None:
        if days_until <= 7:
            status = "critical"
        elif days_until <= 30:
            status = "warning"

    return {
        "metric_type": metric_type,
        "target": target,
        "current": round(current, 4),
        "slope_per_day": round(slope, 6),
        "r_squared": round(r_sq, 3),
        "days_until_threshold": days_until,
        "estimated_date": est_date,
        "threshold": threshold,
        "status": status,
        "samples": len(x_days),
    }


def forecast_all(
    metric_types: Optional[List[str]] = None,
    since_days: int = 30,
    publish_events: bool = True,
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    预测所有目标，返回超限预警列表。
    """
    cfg = config or DEFAULT_FORECAST_CONFIG
    types = metric_types or ["ds_used", "cluster_cpu", "cluster_mem"]
    threshold = cfg.get("threshold", 0.9)
    min_samples = cfg.get("min_samples", 10)
    warn_days = cfg.get("warning_days", 30)
    crit_days = cfg.get("critical_days", 7)

    results: List[Dict[str, Any]] = []
    for mt in types:
        all_history = query_history(metric_type=mt, since_days=since_days)
        targets = {h.get("target") for h in all_history if h.get("target")}
        for target in targets:
            fc = forecast_one(mt, target, since_days=since_days,
                              threshold=threshold, min_samples=min_samples)
            results.append(fc)

            if fc.get("status") in ("warning", "critical") and publish_events:
                try:
                    bus_publish(Topics.QUOTA_BREACH, {
                        "kind": "capacity_forecast",
                        "metric": mt,
                        "target": target,
                        "days_until": fc.get("days_until_threshold"),
                        "estimated_date": fc.get("estimated_date"),
                        "status": fc.get("status"),
                    })
                except Exception:
                    pass

    # 排序：critical > warning > normal
    order = {"critical": 0, "warning": 1, "insufficient_data": 2, "normal": 3}
    results.sort(key=lambda x: order.get(x.get("status", "normal"), 9))
    return results


def format_forecasts(results: List[Dict[str, Any]]) -> str:
    if not results:
        return "📭 暂无预测数据"
    lines = ["| 指标 | 目标 | 当前 | 日增速 | R² | 剩余天数 | 预计超限日期 | 状态 |",
             "|------|------|------|--------|-----|----------|-------------|------|"]
    for r in results:
        status_icon = {"critical": "🔴", "warning": "🟡", "normal": "🟢"}.get(r.get("status", ""), "⚪")
        lines.append(
            f"| {r.get('metric_type','')} | {r.get('target','')} | "
            f"{r.get('current','?')} | {r.get('slope_per_day',0):.4f} | "
            f"{r.get('r_squared',0):.2f} | {r.get('days_until_threshold','-')} | "
            f"{r.get('estimated_date','-')} | {status_icon} {r.get('status','')} |"
        )
    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def _cli():
    import argparse, json
    parser = argparse.ArgumentParser(description="容量预测")
    sub = parser.add_subparsers(dest="cmd")

    p_one = sub.add_parser("one", help="预测单个目标")
    p_one.add_argument("--type", dest="metric_type", required=True)
    p_one.add_argument("--target", required=True)
    p_one.add_argument("--days", type=int, default=30)
    p_one.add_argument("--threshold", type=float, default=0.9)

    p_all = sub.add_parser("all", help="预测所有目标")
    p_all.add_argument("--days", type=int, default=30)
    p_all.add_argument("--no-publish", action="store_true")

    args = parser.parse_args()
    if args.cmd == "one":
        r = forecast_one(args.metric_type, args.target, since_days=args.days,
                         threshold=args.threshold)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.cmd == "all":
        results = forecast_all(since_days=args.days, publish_events=not args.no_publish)
        print(format_forecasts(results))
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
