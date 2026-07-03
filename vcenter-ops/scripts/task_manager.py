"""
Module: scripts.task_manager
Description: vCenter Task 异步管理器。支持提交-查询-等待-取消，长任务不阻塞会话。
Author: 运枢
Date: 2026-05-21
Version: 0.9.0

设计要点：
- 替代原 executor._wait_for_task 的纯阻塞实现
- 支持 task_id 持久化（JSON 文件），跨进程查询
- 支持进度回调（on_progress），用于钉钉消息实时刷新
- 兼容旧调用：wait() 默认行为与 _wait_for_task 一致
"""

import os
import json
import time
import uuid
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Dict, Any, List

from pyVmomi import vim, vmodl

logger = logging.getLogger(__name__)

# Task 持久化目录
SKILL_DIR = Path(__file__).resolve().parent.parent
TASK_DIR = SKILL_DIR / "data" / "tasks"
TASK_DIR.mkdir(parents=True, exist_ok=True)


class TaskState(str):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class TaskManager:
    """vCenter 任务管理器。"""

    def __init__(self, si: Optional[vim.ServiceInstance] = None):
        self.si = si

    # ---------- 持久化 ----------

    @staticmethod
    def _task_file(task_id: str) -> Path:
        return TASK_DIR / f"{task_id}.json"

    @staticmethod
    def _save(record: Dict[str, Any]) -> None:
        path = TaskManager._task_file(record["task_id"])
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2))

    @staticmethod
    def _load(task_id: str) -> Optional[Dict[str, Any]]:
        path = TaskManager._task_file(task_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception as e:
            logger.warning(f"加载 task {task_id} 失败: {e}")
            return None

    # ---------- 核心 API ----------

    def submit(self, task: vim.Task, name: str, meta: Optional[Dict[str, Any]] = None) -> str:
        """
        登记一个 vCenter Task，返回本地 task_id。不阻塞。
        """
        task_id = f"vct-{uuid.uuid4().hex[:12]}"
        record = {
            "task_id": task_id,
            "name": name,
            "vc_task_key": task.info.key if task and task.info else None,
            "state": TaskState.QUEUED,
            "progress": 0,
            "submit_at": datetime.now().isoformat(timespec="seconds"),
            "start_at": None,
            "end_at": None,
            "result": None,
            "error": None,
            "meta": meta or {},
        }
        self._save(record)
        # 缓存 vim.Task 引用（仅当前进程可用，跨进程通过 vc_task_key 重新定位）
        self._tasks_cache = getattr(self, "_tasks_cache", {})
        self._tasks_cache[task_id] = task
        logger.info(f"📝 Task 已登记: {task_id} ({name})")
        return task_id

    def query(self, task_id: str) -> Dict[str, Any]:
        """查询任务状态，自动刷新进度。"""
        record = self._load(task_id)
        if not record:
            raise ValueError(f"任务 {task_id} 不存在")

        # 终态直接返回
        if record["state"] in (TaskState.SUCCESS, TaskState.ERROR, TaskState.CANCELLED, TaskState.TIMEOUT):
            return record

        # 尝试从 cache 取 vim.Task
        task = getattr(self, "_tasks_cache", {}).get(task_id)
        if task is None:
            # 跨进程场景：通过 vc_task_key 重新定位
            task = self._relocate_task(record.get("vc_task_key"))
            if task is None:
                logger.debug(f"无法定位 vim.Task {record.get('vc_task_key')}，仅返回本地记录")
                return record

        # 刷新状态
        info = task.info
        state_map = {
            vim.TaskInfo.State.queued: TaskState.QUEUED,
            vim.TaskInfo.State.running: TaskState.RUNNING,
            vim.TaskInfo.State.success: TaskState.SUCCESS,
            vim.TaskInfo.State.error: TaskState.ERROR,
        }
        new_state = state_map.get(info.state, str(info.state))
        record["state"] = new_state
        record["progress"] = int(info.progress or 0)

        if new_state == TaskState.RUNNING and not record["start_at"]:
            record["start_at"] = datetime.now().isoformat(timespec="seconds")

        if new_state == TaskState.SUCCESS:
            record["end_at"] = datetime.now().isoformat(timespec="seconds")
            record["progress"] = 100
            # 不存储复杂对象，存简短描述
            record["result"] = self._summarize_result(info.result)
        elif new_state == TaskState.ERROR:
            record["end_at"] = datetime.now().isoformat(timespec="seconds")
            record["error"] = str(info.error.msg) if info.error else "unknown error"

        self._save(record)
        return record

    def wait(
        self,
        task_id: str,
        timeout: int = 600,
        poll_interval: float = 3.0,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        同步等待任务完成（兼容原 _wait_for_task 用法）。
        :param on_progress: 进度回调，参数为最新 record；建议节流（如每变化 5% 调一次）
        """
        elapsed = 0.0
        last_progress = -1
        while elapsed < timeout:
            record = self.query(task_id)
            state = record["state"]

            # 进度回调（去抖）
            if on_progress and record["progress"] != last_progress:
                last_progress = record["progress"]
                try:
                    on_progress(record)
                except Exception:
                    logger.debug("on_progress 回调异常", exc_info=True)

            if state == TaskState.SUCCESS:
                logger.info(f"✅ 任务 [{record['name']}] 完成 ({task_id})")
                return record
            if state == TaskState.ERROR:
                logger.error(f"❌ 任务 [{record['name']}] 失败: {record['error']}")
                raise RuntimeError(f"vCenter 操作失败: {record['error']}")
            if state == TaskState.CANCELLED:
                raise RuntimeError(f"任务 [{record['name']}] 已被取消")

            time.sleep(poll_interval)
            elapsed += poll_interval

        # 超时
        record = self.query(task_id)
        record["state"] = TaskState.TIMEOUT
        record["end_at"] = datetime.now().isoformat(timespec="seconds")
        record["error"] = f"等待超时 ({timeout}s)"
        self._save(record)
        raise RuntimeError(f"任务 [{record['name']}] 超时（{timeout}s）")

    def cancel(self, task_id: str) -> bool:
        """尝试取消任务。"""
        record = self._load(task_id)
        if not record:
            raise ValueError(f"任务 {task_id} 不存在")
        if record["state"] in (TaskState.SUCCESS, TaskState.ERROR, TaskState.CANCELLED):
            return False

        task = getattr(self, "_tasks_cache", {}).get(task_id)
        if task is None:
            task = self._relocate_task(record.get("vc_task_key"))
        if task is None:
            logger.warning(f"无法定位 vim.Task，仅标记本地状态为 cancelled")
            record["state"] = TaskState.CANCELLED
            record["end_at"] = datetime.now().isoformat(timespec="seconds")
            self._save(record)
            return False

        try:
            task.CancelTask()
            record["state"] = TaskState.CANCELLED
            record["end_at"] = datetime.now().isoformat(timespec="seconds")
            self._save(record)
            logger.info(f"🛑 任务 [{task_id}] 已请求取消")
            return True
        except Exception as e:
            logger.error(f"取消任务失败: {e}")
            return False

    def list(self, limit: int = 50, state: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出最近任务，按提交时间倒序。"""
        records = []
        for f in TASK_DIR.glob("*.json"):
            try:
                r = json.loads(f.read_text())
                if state and r.get("state") != state:
                    continue
                records.append(r)
            except Exception:
                continue
        records.sort(key=lambda x: x.get("submit_at", ""), reverse=True)
        return records[:limit]

    def cleanup(self, keep_days: int = 7) -> int:
        """清理过期 task 记录。"""
        now = time.time()
        removed = 0
        for f in TASK_DIR.glob("*.json"):
            if (now - f.stat().st_mtime) > keep_days * 86400:
                f.unlink()
                removed += 1
        if removed:
            logger.info(f"🧹 清理 {removed} 个过期 task 记录")
        return removed

    # ---------- 内部辅助 ----------

    def _relocate_task(self, vc_task_key: Optional[str]) -> Optional[vim.Task]:
        """跨进程场景下，通过 TaskManager 重新定位 vim.Task。"""
        if not vc_task_key or not self.si:
            return None
        try:
            tm = self.si.content.taskManager
            # 通过 RecentTask 列表筛选（生产建议改为 CreateCollectorForTasks）
            for t in tm.recentTask:
                if t.info.key == vc_task_key:
                    return t
        except Exception as e:
            logger.debug(f"重新定位 task 失败: {e}")
        return None

    @staticmethod
    def _summarize_result(result: Any) -> Any:
        """vim 对象不可序列化，仅保留简短摘要。"""
        if result is None:
            return None
        try:
            if hasattr(result, "name"):
                return {"type": type(result).__name__, "name": result.name}
            return str(result)[:200]
        except Exception:
            return str(type(result).__name__)
