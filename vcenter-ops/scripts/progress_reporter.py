"""
Module: scripts.progress_reporter
Description: 进度推送适配器。统一封装"克隆/电源/删除"等长任务的进度回调，
             支持去抖、阈值过滤、多通道（stdout / 钉钉 / 日志）。
Author: 运枢
Date: 2026-05-22
Version: 1.0.0

设计要点：
- 与 task_manager.wait() 的 on_progress 回调接口对齐
- 默认 5% 步长 + 5s 最小间隔的去抖，避免刷屏
- 多种格式化（短消息 / 卡片 / 日志行）
- 支持注入"消息发送函数"，由上层 handler 提供（不直接依赖钉钉 SDK）
"""

import time
import logging
from typing import Callable, Optional, Dict, Any, List

logger = logging.getLogger(__name__)


# 推送通道函数签名：fn(message: str, extra: dict) -> None
SinkFn = Callable[[str, Dict[str, Any]], None]


class ProgressReporter:
    """
    进度报告器，可挂接到 task_manager.wait(on_progress=reporter.on_update)。

    用法:
        rpt = ProgressReporter(op_name="克隆 web01", sinks=[stdout_sink, dingtalk_sink])
        task_mgr.wait(task_id, on_progress=rpt.on_update)
        rpt.on_done(final_record)
    """

    def __init__(
        self,
        op_name: str = "vCenter 操作",
        sinks: Optional[List[SinkFn]] = None,
        progress_step: int = 5,
        min_interval: float = 5.0,
        report_milestones: bool = True,
    ):
        self.op_name = op_name
        self.sinks = sinks or [stdout_sink]
        self.progress_step = max(1, progress_step)
        self.min_interval = max(0.0, min_interval)
        self.report_milestones = report_milestones

        self._last_reported_progress = -1
        self._last_reported_at = 0.0
        self._reported_milestones: set = set()
        self._start_at = time.time()

    # ---------- 主入口 ----------

    def on_update(self, record: Dict[str, Any]) -> None:
        """task_manager 的 on_progress 回调钩子。"""
        progress = int(record.get("progress") or 0)
        state = record.get("state", "")

        now = time.time()

        # 终态强制推送
        is_terminal = state in ("success", "error", "cancelled", "timeout")

        # 步长 / 时间双重去抖
        delta = progress - self._last_reported_progress
        step_ok = delta >= self.progress_step
        time_ok = (now - self._last_reported_at) >= self.min_interval

        should_emit = is_terminal or (step_ok and time_ok)

        # milestone 强制推送（25/50/75）
        if self.report_milestones:
            for ms in (25, 50, 75):
                if progress >= ms and ms not in self._reported_milestones:
                    should_emit = True
                    self._reported_milestones.add(ms)
                    break

        if not should_emit:
            return

        self._last_reported_progress = progress
        self._last_reported_at = now
        self._emit(self._format_progress(record))

    def on_done(self, record: Dict[str, Any]) -> None:
        """任务完成时主动调用，输出总结。"""
        self._emit(self._format_done(record))

    def on_error(self, exc: BaseException) -> None:
        """任务失败时主动调用。"""
        try:
            from .error_dictionary import format_error_oneline
        except ImportError:
            from error_dictionary import format_error_oneline
        msg = f"❌ [{self.op_name}] 失败：{format_error_oneline(exc)}"
        self._emit(msg, extra={"event": "error", "exc_type": type(exc).__name__})

    # ---------- 渲染 ----------

    def _format_progress(self, record: Dict[str, Any]) -> str:
        progress = int(record.get("progress") or 0)
        state = record.get("state", "?")
        elapsed = int(time.time() - self._start_at)

        bar_len = 20
        filled = int(bar_len * progress / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        return f"⏳ [{self.op_name}] {bar} {progress}% | state={state} | {elapsed}s"

    def _format_done(self, record: Dict[str, Any]) -> str:
        elapsed = int(time.time() - self._start_at)
        state = record.get("state")
        if state == "success":
            return f"✅ [{self.op_name}] 完成 | 用时 {elapsed}s"
        return (
            f"⚠️ [{self.op_name}] 结束状态={state} | 用时 {elapsed}s | "
            f"error={record.get('error')}"
        )

    # ---------- 推送 ----------

    def _emit(self, message: str, extra: Optional[Dict[str, Any]] = None) -> None:
        ex = extra or {"op": self.op_name}
        for sink in self.sinks:
            try:
                sink(message, ex)
            except Exception:
                logger.debug("sink 推送失败", exc_info=True)


# ============================================================
# 内置 Sink
# ============================================================

def stdout_sink(message: str, extra: Dict[str, Any]) -> None:
    print(message, flush=True)


def logging_sink(message: str, extra: Dict[str, Any]) -> None:
    logger.info(message)


def file_sink(path: str) -> SinkFn:
    """返回一个写文件的 sink。"""
    def _sink(message: str, extra: Dict[str, Any]) -> None:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(message + "\n")
        except Exception:
            logger.debug(f"file_sink 写入失败 {path}", exc_info=True)
    return _sink


def dingtalk_sink(send_fn: Callable[[str], None]) -> SinkFn:
    """
    钉钉推送通道工厂。

    :param send_fn: 上层 handler 提供的消息发送函数（已绑定群/用户）
    """
    def _sink(message: str, extra: Dict[str, Any]) -> None:
        try:
            send_fn(message)
        except Exception:
            logger.debug("dingtalk_sink 推送失败", exc_info=True)
    return _sink


if __name__ == "__main__":
    # 自测：模拟一个任务的进度更新流
    rpt = ProgressReporter(op_name="测试克隆 demo01", min_interval=0)
    for p in [0, 3, 8, 15, 27, 50, 60, 78, 95, 100]:
        rpt.on_update({"progress": p, "state": "running" if p < 100 else "success"})
        time.sleep(0.01)
    rpt.on_done({"state": "success", "progress": 100})
    print("\n✅ progress_reporter self-check passed")
