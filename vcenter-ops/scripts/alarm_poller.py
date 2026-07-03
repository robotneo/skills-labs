"""
Module: scripts.alarm_poller
Description: vCenter 原生告警轮询器。定期拉取 triggeredAlarmState，转发到 event_bus。
Author: 运枢
Date: 2026-05-22
Version: 1.2.0

设计要点：
- 通过 alarmManager.GetAlarm() / 各对象的 triggeredAlarmState 获取告警
- 去重：基于 alarm_key + entity，已发送过的告警不重复
- 状态去重持久化（data/alarms_seen.json），重启不丢
- 自动转换为 event_bus 的 ALARM 主题
- 适合 cron 每 5 分钟跑一次
"""

import os
import json
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List, Set

try:
    from .event_bus import publish as bus_publish, Topics
except ImportError:
    from event_bus import publish as bus_publish, Topics

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).resolve().parent.parent
SEEN_FILE = SKILL_DIR / "data" / "alarms_seen.json"
SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)

# 严重程度映射
SEVERITY_MAP = {
    "red": "critical",
    "yellow": "warning",
    "green": "ok",
    "gray": "unknown",
}


# ============================================================
# 去重存储
# ============================================================

def _load_seen() -> Set[str]:
    if not SEEN_FILE.exists():
        return set()
    try:
        data = json.loads(SEEN_FILE.read_text())
        return set(data.get("seen", []))
    except Exception:
        return set()


def _save_seen(seen: Set[str]) -> None:
    # 仅保留最近 1000 条
    seen_list = list(seen)[-1000:]
    SEEN_FILE.write_text(json.dumps({
        "seen": seen_list,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2))


def _alarm_signature(entity_name: str, alarm_key: str, status: str) -> str:
    """生成告警唯一签名（entity + alarm + status）。"""
    return f"{entity_name}|{alarm_key}|{status}"


# ============================================================
# 采集
# ============================================================

def poll_alarms(executor, publish_events: bool = True) -> List[Dict[str, Any]]:
    """
    扫描 vCenter 当前触发的告警，新告警转发到 event_bus。

    :return: 新告警列表
    """
    from pyVmomi import vim

    seen = _load_seen()
    new_alarms: List[Dict[str, Any]] = []
    content = executor.content

    # 1. 主机告警
    host_view = content.viewManager.CreateContainerView(
        content.rootFolder, [vim.HostSystem], True
    )
    # 2. VM 告警
    vm_view = content.viewManager.CreateContainerView(
        content.rootFolder, [vim.VirtualMachine], True
    )
    # 3. Datastore 告警
    ds_view = content.viewManager.CreateContainerView(
        content.rootFolder, [vim.Datastore], True
    )
    # 4. Cluster 告警
    cl_view = content.viewManager.CreateContainerView(
        content.rootFolder, [vim.ClusterComputeResource], True
    )

    def _scan(view, entity_type: str):
        for entity in view.view:
            try:
                triggered = getattr(entity, "triggeredAlarmState", None) or []
                for ta in triggered:
                    try:
                        alarm_name = ta.alarm.info.name if ta.alarm and ta.alarm.info else "?"
                        alarm_key = ta.key
                        status = str(ta.overallStatus or "unknown")
                        severity = SEVERITY_MAP.get(status, status)
                        sig = _alarm_signature(entity.name, alarm_key, status)

                        if sig in seen:
                            continue

                        # 仅推送 red/yellow（critical/warning）
                        if status not in ("red", "yellow"):
                            seen.add(sig)
                            continue

                        rec = {
                            "entity_type": entity_type,
                            "entity_name": entity.name,
                            "alarm_name": alarm_name,
                            "alarm_key": alarm_key,
                            "status": status,
                            "severity": severity,
                            "time": ta.time.isoformat() if ta.time else "",
                        }
                        new_alarms.append(rec)
                        seen.add(sig)

                        if publish_events:
                            try:
                                bus_publish(Topics.ALARM, {
                                    "kind": "vcenter_native",
                                    **rec,
                                })
                            except Exception:
                                pass
                    except Exception:
                        continue
            except Exception:
                continue

    try:
        _scan(host_view, "host")
        _scan(vm_view, "vm")
        _scan(ds_view, "datastore")
        _scan(cl_view, "cluster")
    finally:
        host_view.Destroy()
        vm_view.Destroy()
        ds_view.Destroy()
        cl_view.Destroy()

    _save_seen(seen)
    if new_alarms:
        logger.warning(f"⚠️ 发现 {len(new_alarms)} 条新告警")
    return new_alarms


def list_active_alarms(executor) -> List[Dict[str, Any]]:
    """列出当前所有活动告警（不做去重，用于巡检）。"""
    from pyVmomi import vim

    result: List[Dict[str, Any]] = []
    content = executor.content

    for vim_type, label in [
        (vim.HostSystem, "host"),
        (vim.VirtualMachine, "vm"),
        (vim.Datastore, "datastore"),
        (vim.ClusterComputeResource, "cluster"),
    ]:
        view = content.viewManager.CreateContainerView(
            content.rootFolder, [vim_type], True)
        try:
            for entity in view.view:
                try:
                    for ta in (getattr(entity, "triggeredAlarmState", None) or []):
                        try:
                            status = str(ta.overallStatus or "unknown")
                            if status not in ("red", "yellow"):
                                continue
                            result.append({
                                "entity_type": label,
                                "entity_name": entity.name,
                                "alarm_name": ta.alarm.info.name if ta.alarm and ta.alarm.info else "?",
                                "status": status,
                                "severity": SEVERITY_MAP.get(status, status),
                                "time": ta.time.isoformat() if ta.time else "",
                            })
                        except Exception:
                            continue
                except Exception:
                    continue
        finally:
            view.Destroy()
    return result


def format_alarms(alarms: List[Dict[str, Any]]) -> str:
    if not alarms:
        return "✅ 当前无活动告警"
    lines = ["| 时间 | 严重 | 实体 | 告警名 |", "|------|------|------|--------|"]
    sev_icon = {"critical": "🔴", "warning": "🟡", "ok": "🟢"}
    for a in alarms:
        ts = (a.get("time") or "")[:19]
        icon = sev_icon.get(a.get("severity", ""), "⚪")
        lines.append(
            f"| {ts} | {icon} {a.get('severity','?')} | "
            f"{a.get('entity_type','?')}:{a.get('entity_name','?')} | "
            f"{a.get('alarm_name','?')} |"
        )
    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="vCenter 告警轮询")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("poll", help="轮询新告警并发布事件")
    sub.add_parser("list", help="列出当前所有活动告警")

    args = parser.parse_args()
    import yaml as _yaml
    from client import VCenterClient
    from executor import VCenterExecutor
    cfg = _yaml.safe_load((SKILL_DIR / "config.yaml").read_text())["vcenter"]
    from dotenv import load_dotenv
    load_dotenv(SKILL_DIR / ".env")
    pwd = os.environ.get(cfg["password_ref"], "")

    with VCenterClient(cfg["host"], cfg["user"], pwd, cfg.get("port", 443)) as si:
        ex = VCenterExecutor(si)
        if args.cmd == "poll":
            new = poll_alarms(ex, publish_events=True)
            print(f"发现 {len(new)} 条新告警")
            print(format_alarms(new))
        elif args.cmd == "list":
            alarms = list_active_alarms(ex)
            print(f"当前活动告警 {len(alarms)} 条")
            print(format_alarms(alarms))
        else:
            parser.print_help()


if __name__ == "__main__":
    _cli()
