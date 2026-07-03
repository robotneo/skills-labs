"""
Module: scripts.history_manager
Description: 历史克隆/操作复用管理器。读取 data/tasks/ 任务记录，提取参数用于"按上次配置克隆"。
Author: 运枢
Date: 2026-05-22
Version: 1.0.0

设计要点：
- 复用 task_manager 已有的 data/tasks/*.json，不引入新存储
- 提取 meta 字段中的 clone 参数，按 VM 名/模板/时间检索
- 提供 last_clone_params() 一行调用，CLI 友好
- 支持 "按上次克隆 web01" / "按 dev-small 预设克隆" 两种入口
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).resolve().parent.parent
TASK_DIR = SKILL_DIR / "data" / "tasks"
HISTORY_INDEX = SKILL_DIR / "data" / "history_index.json"


# 哪些任务类型可以作为"复用源"
REPLAYABLE_OPS = {"clone_vm", "Clone-", "reconfigure_vm", "Reconfigure-"}


def _is_replayable(record: Dict[str, Any]) -> bool:
    name = record.get("name", "")
    for key in REPLAYABLE_OPS:
        if key in name:
            return True
    meta = record.get("meta") or {}
    if meta.get("op") in REPLAYABLE_OPS:
        return True
    return False


def list_history(
    limit: int = 20,
    op: Optional[str] = None,
    only_success: bool = True,
) -> List[Dict[str, Any]]:
    """
    列出最近的可复用历史记录。

    :param limit: 返回条数
    :param op: 限定操作类型（如 clone_vm）
    :param only_success: 仅成功的任务
    """
    records: List[Dict[str, Any]] = []
    if not TASK_DIR.exists():
        return records

    for f in TASK_DIR.glob("*.json"):
        try:
            r = json.loads(f.read_text())
        except Exception:
            continue
        if only_success and r.get("state") != "success":
            continue
        if not _is_replayable(r):
            continue
        if op and op not in r.get("name", "") and (r.get("meta") or {}).get("op") != op:
            continue
        records.append(r)

    records.sort(key=lambda x: x.get("end_at") or x.get("submit_at") or "", reverse=True)
    return records[:limit]


def find_last_by_vm_name(vm_name: str) -> Optional[Dict[str, Any]]:
    """根据 VM 名查找最近一次涉及该 VM 的操作记录。"""
    candidates = list_history(limit=200, only_success=True)
    for r in candidates:
        meta = r.get("meta") or {}
        # 匹配 meta.new_name / meta.vm_name / 或任务名中包含 vm_name
        if meta.get("new_name") == vm_name or meta.get("vm_name") == vm_name:
            return r
        if vm_name in r.get("name", ""):
            return r
    return None


def find_last_by_template(template_name: str) -> Optional[Dict[str, Any]]:
    """根据模板名找最近一次克隆。"""
    for r in list_history(limit=200, only_success=True, op="clone_vm"):
        meta = r.get("meta") or {}
        if meta.get("template_name") == template_name:
            return r
    return None


def last_clone_params(vm_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    获取最近一次克隆的参数（用于"按上次配置克隆"）。

    :param vm_name: 若提供，则定位该 VM 最近一次克隆参数；否则取全局最新一次克隆
    :return: 参数字典（去掉 new_name 字段，便于用户修改）；找不到返回 None
    """
    record = None
    if vm_name:
        record = find_last_by_vm_name(vm_name)
    else:
        recent = list_history(limit=1, op="clone_vm", only_success=True)
        record = recent[0] if recent else None

    if not record:
        return None

    meta = dict(record.get("meta") or {})
    if not meta:
        return None

    # 返回结果包含来源信息，便于用户确认
    return {
        "source_task_id": record.get("task_id"),
        "source_end_at": record.get("end_at"),
        "source_name": record.get("name"),
        "params": {
            k: v for k, v in meta.items()
            if k in {
                "template_name", "dc_name", "cluster_name", "ds_name",
                "network_name", "host_name", "cpus", "memory_gb", "disk_gb",
                "subnet", "gateway",
            }
        },
        "previous_new_name": meta.get("new_name"),
        "previous_ip": meta.get("ip_address"),
    }


def format_history_summary(records: List[Dict[str, Any]]) -> str:
    """渲染为表格文本，适合钉钉/CLI 输出。"""
    if not records:
        return "📭 暂无可复用的历史记录"

    lines = ["| # | 任务 | VM | 模板 | 规格 | 时间 |", "|---|------|------|------|------|------|"]
    for i, r in enumerate(records, 1):
        meta = r.get("meta") or {}
        spec = []
        if meta.get("cpus"): spec.append(f"{meta['cpus']}C")
        if meta.get("memory_gb"): spec.append(f"{meta['memory_gb']}G")
        if meta.get("disk_gb"): spec.append(f"{meta['disk_gb']}GB盘")
        spec_str = "/".join(spec) or "-"
        lines.append(
            f"| {i} | {r.get('name','')[:24]} | {meta.get('new_name','-')} | "
            f"{meta.get('template_name','-')} | {spec_str} | {(r.get('end_at') or '')[:16]} |"
        )
    return "\n".join(lines)


def format_clone_params(info: Dict[str, Any]) -> str:
    """格式化最近一次克隆参数。"""
    if not info:
        return "❌ 未找到可复用的克隆记录"
    p = info.get("params") or {}
    lines = [
        f"📜 来源任务: {info.get('source_name')} ({info.get('source_task_id')})",
        f"⏰ 完成时间: {info.get('source_end_at')}",
        f"🗂️  上次 VM 名: {info.get('previous_new_name')} | IP: {info.get('previous_ip') or '-'}",
        "──",
        "可复用参数:",
    ]
    for k in ("template_name", "dc_name", "cluster_name", "host_name", "ds_name",
              "network_name", "cpus", "memory_gb", "disk_gb", "subnet", "gateway"):
        if k in p and p[k] is not None:
            lines.append(f"  • {k}: {p[k]}")
    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="vCenter 历史操作复用工具")
    sub = parser.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="列出可复用历史")
    p_list.add_argument("--limit", type=int, default=10)
    p_list.add_argument("--op", default=None, help="操作类型，如 clone_vm")

    p_last = sub.add_parser("last", help="查看最近一次克隆参数")
    p_last.add_argument("--vm", default=None, help="按 VM 名定位")

    args = parser.parse_args()

    if args.cmd == "list":
        recs = list_history(limit=args.limit, op=args.op)
        print(format_history_summary(recs))
    elif args.cmd == "last":
        info = last_clone_params(args.vm)
        print(format_clone_params(info or {}))
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
