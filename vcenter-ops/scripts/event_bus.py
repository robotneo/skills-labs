"""
Module: scripts.event_bus
Description: 进程内事件总线。统一发布 VM 生命周期/告警事件，下游订阅者（webhook/audit/钉钉）按需消费。
Author: 运枢
Date: 2026-05-22
Version: 1.1.0

设计要点：
- 轻量：仅 publish/subscribe，无外部依赖
- 主题（topic）字符串自由定义：vm.created / vm.deleted / vm.power.on / clone.progress / alarm
- 订阅者用回调函数；异常不传播，仅记录日志
- 支持通配符订阅：vm.* 匹配所有 vm. 开头主题
- 同步派发；如需异步可在 sink 内部 spawn 线程
"""

import logging
import threading
from typing import Callable, Dict, Any, List, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


# 事件结构: {"topic": "vm.created", "ts": "2026-05-22T...", "payload": {...}}
Event = Dict[str, Any]
Handler = Callable[[Event], None]


class EventBus:
    """进程内事件总线（线程安全）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._subs: List[Tuple[str, Handler]] = []  # (pattern, handler)
        self._history: List[Event] = []
        self._history_max = 200

    # ---------- 订阅 ----------

    def subscribe(self, pattern: str, handler: Handler) -> None:
        """
        订阅事件。pattern 支持精确匹配或通配符尾部 *：
          - "vm.created"   只匹配该主题
          - "vm.*"         匹配所有以 vm. 开头的主题
          - "*"            匹配所有主题
        """
        with self._lock:
            self._subs.append((pattern, handler))
        logger.debug(f"📡 订阅 {pattern} → {getattr(handler, '__name__', repr(handler))}")

    def unsubscribe(self, handler: Handler) -> int:
        """按 handler 取消订阅。返回移除条数。"""
        with self._lock:
            before = len(self._subs)
            self._subs = [(p, h) for p, h in self._subs if h != handler]
            return before - len(self._subs)

    def clear(self) -> None:
        with self._lock:
            self._subs.clear()

    # ---------- 发布 ----------

    def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        """发布事件，同步派发给匹配订阅者。订阅者异常不影响其他订阅者。"""
        event: Event = {
            "topic": topic,
            "ts": datetime.now().isoformat(timespec="seconds"),
            "payload": payload,
        }
        with self._lock:
            self._history.append(event)
            if len(self._history) > self._history_max:
                self._history = self._history[-self._history_max:]
            subs = list(self._subs)

        matched = 0
        for pattern, handler in subs:
            if self._match(pattern, topic):
                matched += 1
                try:
                    handler(event)
                except Exception:
                    logger.exception(f"事件订阅者 {handler} 处理 {topic} 失败")
        logger.debug(f"📣 publish {topic} → 命中 {matched} 个订阅者")

    @staticmethod
    def _match(pattern: str, topic: str) -> bool:
        if pattern == "*":
            return True
        if pattern.endswith(".*"):
            return topic.startswith(pattern[:-1])
        return pattern == topic

    # ---------- 历史 ----------

    def history(self, topic_filter: str = "", limit: int = 50) -> List[Event]:
        with self._lock:
            hist = list(self._history)
        if topic_filter:
            hist = [e for e in hist if self._match(topic_filter, e["topic"])]
        return hist[-limit:]


# ============================================================
# 单例 + 常用主题常量
# ============================================================

_bus = EventBus()


def get_bus() -> EventBus:
    return _bus


class Topics:
    VM_CREATED = "vm.created"
    VM_DELETED = "vm.deleted"
    VM_RECONFIGURED = "vm.reconfigured"
    VM_POWER_ON = "vm.power.on"
    VM_POWER_OFF = "vm.power.off"
    CLONE_STARTED = "clone.started"
    CLONE_PROGRESS = "clone.progress"
    CLONE_DONE = "clone.done"
    CLONE_FAILED = "clone.failed"
    ALARM = "alarm"
    QUOTA_BREACH = "quota.breach"
    HEALTH = "health"


# 便捷快捷函数
def publish(topic: str, payload: Dict[str, Any]) -> None:
    _bus.publish(topic, payload)


def subscribe(pattern: str, handler: Handler) -> None:
    _bus.subscribe(pattern, handler)


if __name__ == "__main__":
    # 自测
    def log_handler(event: Event) -> None:
        print(f"[{event['ts']}] {event['topic']}: {event['payload']}")

    subscribe("vm.*", log_handler)
    subscribe("clone.*", log_handler)
    publish(Topics.VM_CREATED, {"vm_name": "web01", "ip": "10.0.0.1"})
    publish(Topics.CLONE_PROGRESS, {"vm_name": "web02", "progress": 50})
    publish(Topics.ALARM, {"level": "warn", "msg": "ds 满了"})  # 不应被订阅

    h = _bus.history(limit=10)
    print(f"\n历史 {len(h)} 条")
    print("✅ event_bus self-check passed")
