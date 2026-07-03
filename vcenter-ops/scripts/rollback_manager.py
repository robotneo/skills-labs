"""
Module: scripts.rollback_manager
Description: 关键操作的自动回滚 / 补偿机制。
Author: 运枢
Date: 2026-05-21
Version: 0.9.0

设计要点：
- 上下文管理器风格：with RollbackContext(...) as rb: rb.register(action)
- 支持「成功提交」与「异常自动回滚」两条路径
- 内置常见场景：删除前快照、克隆失败清理、迁移失败回滚、重配置失败恢复
- 所有回滚动作可关闭（auto=False）便于 dry-run 与调试
"""

import logging
from datetime import datetime
from typing import Callable, List, Optional, Any, Dict

logger = logging.getLogger(__name__)


class RollbackAction:
    """单条回滚动作。"""

    def __init__(self, name: str, undo: Callable[[], Any], description: str = ""):
        self.name = name
        self.undo = undo
        self.description = description or name
        self.executed = False
        self.error: Optional[str] = None
        self.created_at = datetime.now().isoformat(timespec="seconds")

    def run(self) -> bool:
        try:
            self.undo()
            self.executed = True
            logger.info(f"↩️ 回滚成功: {self.description}")
            return True
        except Exception as e:
            self.error = str(e)
            logger.error(f"⚠️ 回滚失败: {self.description} -> {e}")
            return False


class RollbackContext:
    """
    回滚上下文管理器。

    用法：
        with RollbackContext("clone_vm:test01") as rb:
            new_vm = executor.clone_vm_advanced(...)
            rb.register("cleanup_clone",
                        lambda: executor.delete_vm(new_vm.name),
                        description="清理克隆失败的半成品 VM")

            executor.configure_network(new_vm, ...)
            rb.register("rollback_network",
                        lambda: executor.restore_network(new_vm, ...),
                        description="恢复网络配置")

            # 若以上任意一步抛异常，按 LIFO 顺序自动回滚
            rb.commit()  # 显式提交后不再回滚
    """

    def __init__(self, op_name: str, auto_rollback: bool = True, dry_run: bool = False):
        self.op_name = op_name
        self.auto_rollback = auto_rollback
        self.dry_run = dry_run
        self.actions: List[RollbackAction] = []
        self.committed = False
        self.rolled_back = False

    def register(self, name: str, undo: Callable[[], Any], description: str = "") -> None:
        """登记一个回滚动作。LIFO 顺序，最后登记的先执行。"""
        if self.dry_run:
            logger.info(f"[DRY-RUN] 登记回滚动作: {name} ({description})")
            return
        action = RollbackAction(name, undo, description or name)
        self.actions.append(action)
        logger.debug(f"📌 已登记回滚动作: {name}")

    def commit(self) -> None:
        """提交：标记操作成功，不再触发回滚。"""
        self.committed = True
        logger.info(f"✅ 操作提交: {self.op_name} (跳过 {len(self.actions)} 条回滚动作)")

    def rollback(self) -> Dict[str, Any]:
        """显式触发回滚。"""
        if self.committed:
            logger.warning(f"操作 [{self.op_name}] 已提交，跳过回滚")
            return {"rolled_back": False, "reason": "committed"}

        logger.warning(f"🔄 开始回滚 [{self.op_name}]，共 {len(self.actions)} 步")
        success, failed = 0, 0
        for action in reversed(self.actions):
            if action.run():
                success += 1
            else:
                failed += 1
        self.rolled_back = True
        return {
            "rolled_back": True,
            "total": len(self.actions),
            "success": success,
            "failed": failed,
            "actions": [
                {"name": a.name, "executed": a.executed, "error": a.error}
                for a in self.actions
            ],
        }

    def __enter__(self):
        logger.info(f"🚦 进入回滚上下文: {self.op_name}")
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            if not self.committed:
                logger.debug(f"操作 [{self.op_name}] 正常结束但未 commit，仍执行回滚以确保安全")
                if self.auto_rollback:
                    self.rollback()
        else:
            logger.error(f"❌ 操作 [{self.op_name}] 异常: {exc}")
            if self.auto_rollback:
                self.rollback()
        # 不吞异常，交给上层
        return False


# ---------- 常见回滚模板 ----------


def make_pre_delete_snapshot(executor, vm_name: str, retention_tag: str = "auto-rollback") -> Dict[str, Any]:
    """
    删除 VM 前自动创建一个保留快照。
    返回 {snapshot_name, created_at}，供 audit 记录。
    """
    snap_name = f"pre-delete-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    try:
        executor.create_snapshot(
            vm_name=vm_name,
            snap_name=snap_name,
            description=f"[{retention_tag}] 删除前自动快照，保留供回滚",
        )
        logger.info(f"📸 已创建删除前快照: {vm_name}@{snap_name}")
        return {"snapshot_name": snap_name, "created_at": datetime.now().isoformat()}
    except Exception as e:
        logger.error(f"创建删除前快照失败: {e}")
        return {"snapshot_name": None, "error": str(e)}


def cleanup_partial_clone(executor, vm_name: str) -> Callable[[], None]:
    """生成「清理半成品 VM」的回滚动作。"""
    def _undo():
        try:
            executor.delete_vm(vm_name)
            logger.info(f"🧹 已清理半成品 VM: {vm_name}")
        except Exception as e:
            logger.warning(f"清理半成品 VM [{vm_name}] 失败（可能不存在）: {e}")
    return _undo


def rollback_migration(executor, vm_name: str, original_host: str) -> Callable[[], None]:
    """生成「迁移回滚到原宿主机」的回滚动作。"""
    def _undo():
        executor.migrate_vm(vm_name=vm_name, target_host=original_host)
        logger.info(f"🔙 已回滚迁移: {vm_name} → {original_host}")
    return _undo


def restore_vm_config(executor, vm_name: str, original_spec: Dict[str, Any]) -> Callable[[], None]:
    """生成「恢复 VM 硬件配置」的回滚动作。"""
    def _undo():
        executor.reconfigure_vm(
            vm_name=vm_name,
            cpus=original_spec.get("cpus"),
            memory_gb=original_spec.get("memory_gb"),
        )
        logger.info(f"🔙 已恢复 VM 配置: {vm_name} → {original_spec}")
    return _undo
