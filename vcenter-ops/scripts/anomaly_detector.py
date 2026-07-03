"""
Module: scripts.anomaly_detector
Description: 资源水位异常检测。基于历史移动平均 + 标准差计算基线，越界触发 alarm 事件。
Author: 运枢
Date: 2026-05-22
Version: 1.4.0

设计要点：
- 基线：最近 N 个采样点的均值 + 标准差
- 阈值：动态 (mean + k*std)，k 默认 3，可配置
- 静态兜底：每种指标可指定硬阈值（如 ds_used > 0.9 必触发）
- 异常事件发布到 event_bus（Topics.ALARM），由 webhook 投递
- 支持滑窗去抖：连续 N 次越界才触发，防止毛刺
"""

import logging
import statistics
from typing import Optional, Dict, Any, List

try:
    from .metrics_collector import query_history
    from .event_bus import publish as bus_publish, Topics
except ImportError:
    from metrics_collector import query_history
    from event_bus import publish as bus_publish, Topics

logger = logging.getLogger(__name__)


# ============================================================
# 默认阈值（可被 config 覆盖）
# ============================================================

DEFAULT_THRESHOLDS: Dict[str, Dict[str, Any]] = {
    "cluster_cpu": {
        "hard_max": 0.92,    # 硬阈值
        "k_sigma": 3,        # 动态阈值倍数
        "min_samples": 10,   # 启用动态阈值的最少样本数
        "consecutive": 2,    # 连续多少次越界才触发
    },
    "cluster_mem": {
        "hard_max": 0.92,
        "k_sigma": 3,
        "min_samples": 10,
        "consecutive": 2,
    },
    "ds_used": {
        "hard_max": 0.90,
        "k_sigma": 2.5,
        "min_samples": 10,
        "consecutive": 1,
    },
}


# ============================================================
# 检测逻辑
# ============================================================

def compute_baseline(values: List[float]) -> Optional[Dict[str, float]]:
    """计算基线统计量。样本太少返回 None。"""
    if len(values) < 5:
        return None
    try:
        mean = statistics.mean(values)
        std = statistics.stdev(values) if len(values) > 1 else 0
        return {
            "mean": round(mean, 4),
            "std": round(std, 4),
            "min": round(min(values), 4),
            "max": round(max(values), 4),
            "samples": len(values),
        }
    except Exception:
        return None


def detect_one(
    metric_type: str,
    target: str,
    since_days: int = 7,
    thresholds: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    检测某指标 + 目标 是否异常。

    :return: {
        "anomaly": bool,
        "reason": str,
        "current": float,
        "baseline": {...},
        "threshold": float,
    }
    """
    cfg = (thresholds or {}).get(metric_type) or DEFAULT_THRESHOLDS.get(metric_type, {})
    if not cfg:
        return {"anomaly": False, "reason": f"未配置 {metric_type} 的阈值"}

    history = query_history(metric_type=metric_type, target=target, since_days=since_days)
    if not history:
        return {"anomaly": False, "reason": "无历史数据"}

    values = [float(h.get("value") or 0) for h in history]
    current = values[-1]
    baseline = compute_baseline(values)

    # 硬阈值
    hard_max = cfg.get("hard_max")
    if hard_max and current > hard_max:
        return {
            "anomaly": True,
            "reason": f"硬阈值越界: {current:.3f} > {hard_max}",
            "current": current,
            "baseline": baseline,
            "threshold": hard_max,
            "type": "hard_threshold",
        }

    # 动态阈值（需要足够样本）
    if baseline and baseline["samples"] >= cfg.get("min_samples", 10):
        k = cfg.get("k_sigma", 3)
        dyn_threshold = baseline["mean"] + k * baseline["std"]
        if current > dyn_threshold:
            # 连续性检查
            consec = cfg.get("consecutive", 1)
            if consec > 1 and len(values) >= consec:
                if not all(values[-i] > dyn_threshold for i in range(1, consec + 1)):
                    return {
                        "anomaly": False,
                        "reason": f"单点越界但未连续 {consec} 次",
                        "current": current,
                        "baseline": baseline,
                        "threshold": dyn_threshold,
                    }
            return {
                "anomaly": True,
                "reason": f"动态阈值越界: {current:.3f} > mean+{k}σ = {dyn_threshold:.3f}",
                "current": current,
                "baseline": baseline,
                "threshold": dyn_threshold,
                "type": "dynamic_threshold",
            }

    return {
        "anomaly": False,
        "reason": "正常",
        "current": current,
        "baseline": baseline,
    }


def detect_all(
    metric_types: Optional[List[str]] = None,
    since_days: int = 7,
    publish_events: bool = True,
) -> List[Dict[str, Any]]:
    """
    扫描所有目标的所有指标类型，返回异常列表。

    :param metric_types: 限定类型，None=全部
    :param publish_events: 发现异常时是否发布到 event_bus
    """
    types_to_check = metric_types or list(DEFAULT_THRESHOLDS.keys())

    # 找出每个 type 下涉及的 targets
    anomalies: List[Dict[str, Any]] = []
    for mt in types_to_check:
        all_history = query_history(metric_type=mt, since_days=since_days)
        targets = {h.get("target") for h in all_history if h.get("target")}
        for target in targets:
            result = detect_one(mt, target, since_days=since_days)
            if result.get("anomaly"):
                rec = {
                    "metric_type": mt,
                    "target": target,
                    **result,
                }
                anomalies.append(rec)
                if publish_events:
                    try:
                        bus_publish(Topics.ALARM, {
                            "kind": "metric_anomaly",
                            "metric": mt,
                            "target": target,
                            "current": result.get("current"),
                            "threshold": result.get("threshold"),
                            "reason": result.get("reason"),
                            "type": result.get("type"),
                        })
                    except Exception:
                        pass

    if anomalies:
        logger.warning(f"⚠️ 检测到 {len(anomalies)} 项资源异常")
    return anomalies


def format_anomalies(anomalies: List[Dict[str, Any]]) -> str:
    if not anomalies:
        return "✅ 全部指标正常，未检测到异常"
    lines = [
        "| 指标 | 目标 | 当前值 | 阈值 | 原因 |",
        "|------|------|--------|------|------|",
    ]
    for a in anomalies:
        lines.append(
            f"| {a['metric_type']} | {a['target']} | {a.get('current','?'):.3f} | "
            f"{a.get('threshold','?')} | {a.get('reason','')} |"
        )
    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def _cli():
    import argparse, json
    parser = argparse.ArgumentParser(description="资源异常检测")
    sub = parser.add_subparsers(dest="cmd")

    p_one = sub.add_parser("one", help="检测单个目标")
    p_one.add_argument("--type", dest="metric_type", required=True)
    p_one.add_argument("--target", required=True)
    p_one.add_argument("--days", type=int, default=7)

    p_all = sub.add_parser("all", help="检测所有目标")
    p_all.add_argument("--days", type=int, default=7)
    p_all.add_argument("--no-publish", action="store_true")

    args = parser.parse_args()
    if args.cmd == "one":
        r = detect_one(args.metric_type, args.target, since_days=args.days)
        print(json.dumps(r, ensure_ascii=False, indent=2))
    elif args.cmd == "all":
        anomalies = detect_all(since_days=args.days, publish_events=not args.no_publish)
        print(format_anomalies(anomalies))
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
