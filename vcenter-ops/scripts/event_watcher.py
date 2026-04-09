#!/usr/bin/env python3
"""
vCenter 事件监控器。
支持查询最近的 vCenter 事件（VM 创建/删除/电源变更/告警等）。
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def get_recent_events(content, minutes: int = 60, event_types: Optional[List[str]] = None, max_events: int = 50) -> List[Dict]:
    """
    查询最近的 vCenter 事件。

    :param content: vCenter ServiceInstance content
    :param minutes: 查询最近多少分钟的事件
    :param event_types: 事件类型过滤（如 ["VmPoweredOnEvent", "VmPoweredOffEvent"]）
    :param max_events: 最多返回事件数
    """
    from pyVmomi import vim

    # 计算开始时间
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=minutes)

    # 使用 EventManager 的 QueryEvents
    event_manager = content.eventManager

    # 构建过滤条件
    filter_spec = vim.event.EventFilterSpec()
    filter_spec.time = vim.event.EventFilterSpec.ByTime()
    filter_spec.time.beginTime = start_time
    filter_spec.time.endTime = end_time

    if event_types:
        filter_spec.eventTypeId = event_types

    # 查询事件
    events = event_manager.QueryEvents(filter_spec)

    result = []
    for event in events[:max_events]:
        entry = {
            "type": event.__class__.__name__,
            "time": event.createdTime.strftime("%Y-%m-%d %H:%M:%S") if event.createdTime else "",
            "message": event.fullFormattedMessage or "",
            "severity": getattr(event, 'severity', ''),
        }

        # 提取 VM 名称
        if hasattr(event, 'vm') and event.vm:
            entry["vm"] = event.vm.name
        if hasattr(event, 'host') and event.host:
            entry["host"] = event.host.name
        if hasattr(event, 'userName') and event.userName:
            entry["user"] = event.userName

        result.append(entry)

    return result


# 常用事件类型
EVENT_TYPES = {
    "power": ["VmPoweredOnEvent", "VmPoweredOffEvent", "VmSuspendedEvent", "VmResettingEvent"],
    "create_delete": ["VmCreatedEvent", "VmRemovedEvent", "VmBeingClonedEvent", "VmBeingDeployedEvent"],
    "migration": ["VmMigratedEvent", "VmRelocatedEvent"],
    "snapshot": ["VmSnapshotCreatedEvent", "VmSnapshotRemovedEvent", "VmRevertedToSnapshotEvent"],
    "alarm": ["AlarmStatusChangedEvent"],
}
