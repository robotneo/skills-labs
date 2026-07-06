"""
Module: scripts.lock_manager
Description: 基于文件 fcntl 的本地并发锁，防止同一 VM 同时被多个动作操作。
Author: 运枢
Date: 2026-05-21
Version: 0.9.0

设计要点：
- 锁粒度：单个 VM + 动作类型（hostname 维度），简单可靠
- 实现：fcntl flock（POSIX）+ 锁元信息 JSON 文件
- 支持 TTL，避免崩溃后残留锁
- 提供上下文管理器：with VMLock(name, action): ...
"""

import os
import json
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 跨平台文件锁：优先使用 POSIX ``fcntl.flock``，Windows 上回退到 ``msvcrt``
# 的字节级锁；若两者都不可用，则退化为"文件存在即已占用"的软锁，保证
# Skill 在任何 Agent 运行时（macOS / Linux / Windows）都能加载。
# ---------------------------------------------------------------------------

try:  # POSIX：Linux、macOS
    import fcntl  # type: ignore

    def _flock_ex_nb(fp) -> None:
        """Acquire exclusive, non-blocking lock on ``fp``."""
        fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _funlock(fp) -> None:
        fcntl.flock(fp.fileno(), fcntl.LOCK_UN)

    _LOCK_BACKEND = "fcntl"
except ImportError:  # pragma: no cover - Windows only
    try:
        import msvcrt  # type: ignore

        def _flock_ex_nb(fp) -> None:
            """Acquire exclusive, non-blocking lock on ``fp`` (Windows)."""
            # 锁定 1 字节即可达到互斥效果；文件为空时先写占位符。
            try:
                msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                # 与 POSIX 分支保持相同异常类型，便于上层统一捕获。
                raise BlockingIOError(str(error)) from error

        def _funlock(fp) -> None:
            try:
                fp.seek(0)
                msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass

        _LOCK_BACKEND = "msvcrt"
    except ImportError:  # pragma: no cover - exotic runtime
        # 最后兜底：无内核级锁；进程内串行仍由 handler 保证。
        def _flock_ex_nb(fp) -> None:
            return None

        def _funlock(fp) -> None:
            return None

        _LOCK_BACKEND = "noop"

SKILL_DIR = Path(__file__).resolve().parent.parent
LOCK_DIR = SKILL_DIR / "data" / "locks"
LOCK_DIR.mkdir(parents=True, exist_ok=True)


class LockBusy(Exception):
    """锁已被占用。"""

    def __init__(self, meta: Dict[str, Any]):
        self.meta = meta
        super().__init__(
            f"VM [{meta.get('vm')}] 已被 [{meta.get('action')}] 锁定 "
            f"(自 {meta.get('since')}, by {meta.get('locked_by')})"
        )


class VMLock:
    """
    单 VM 并发锁。

    使用示例：
        with VMLock("172.17.40.10-test01", "power_vm"):
            # 临界区
            ...

    或显式控制：
        lock = VMLock("vm-name", "delete_vm", ttl=600)
        lock.acquire()
        try:
            ...
        finally:
            lock.release()
    """

    def __init__(
        self,
        vm: str,
        action: str,
        ttl: int = 600,
        locked_by: str = "agent",
        wait: bool = False,
        wait_timeout: int = 30,
    ):
        self.vm = vm
        self.action = action
        self.ttl = ttl
        self.locked_by = locked_by
        self.wait = wait
        self.wait_timeout = wait_timeout

        self.lock_path = LOCK_DIR / f"{self._safe_name(vm)}.lock"
        self.meta_path = LOCK_DIR / f"{self._safe_name(vm)}.json"
        self._fp = None

    @staticmethod
    def _safe_name(name: str) -> str:
        return "".join(c if c.isalnum() or c in "-_." else "_" for c in name)

    # ---------- 核心 ----------

    def acquire(self) -> "VMLock":
        # 自动清理已过期锁
        self._gc_expired()

        deadline = time.time() + self.wait_timeout if self.wait else 0
        while True:
            self._fp = open(self.lock_path, "w")
            try:
                # 写入占位符再上锁，确保 msvcrt 分支上有字节可锁。
                self._fp.write(" ")
                self._fp.flush()
                _flock_ex_nb(self._fp)
                self._write_meta()
                logger.info(f"🔒 已获取锁: vm={self.vm} action={self.action}")
                return self
            except BlockingIOError:
                self._fp.close()
                self._fp = None
                meta = self._read_meta()
                if self.wait and time.time() < deadline:
                    time.sleep(1)
                    continue
                raise LockBusy(meta or {"vm": self.vm, "action": "unknown"})

    def release(self) -> None:
        if self._fp is None:
            return
        try:
            _funlock(self._fp)
            self._fp.close()
        except Exception as e:
            logger.warning(f"释放锁异常: {e}")
        finally:
            self._fp = None
            try:
                if self.meta_path.exists():
                    self.meta_path.unlink()
                if self.lock_path.exists():
                    self.lock_path.unlink()
            except Exception:
                pass
            logger.info(f"🔓 已释放锁: vm={self.vm} action={self.action}")

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc, tb):
        self.release()

    # ---------- 元信息 ----------

    def _write_meta(self):
        meta = {
            "vm": self.vm,
            "action": self.action,
            "since": datetime.now().isoformat(timespec="seconds"),
            "ttl": self.ttl,
            "expire_at": time.time() + self.ttl,
            "locked_by": self.locked_by,
            "pid": os.getpid(),
        }
        self.meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2))

    def _read_meta(self) -> Optional[Dict[str, Any]]:
        if not self.meta_path.exists():
            return None
        try:
            return json.loads(self.meta_path.read_text())
        except Exception:
            return None

    def _gc_expired(self):
        meta = self._read_meta()
        if not meta:
            return
        if time.time() > meta.get("expire_at", 0):
            logger.warning(f"⏰ 清理过期锁: vm={self.vm} (expired at {meta.get('expire_at')})")
            try:
                self.meta_path.unlink()
                if self.lock_path.exists():
                    self.lock_path.unlink()
            except Exception:
                pass


# ---------- 全局工具方法 ----------


def list_locks() -> list:
    """列出当前所有持有的锁。"""
    result = []
    for f in LOCK_DIR.glob("*.json"):
        try:
            meta = json.loads(f.read_text())
            meta["_expired"] = time.time() > meta.get("expire_at", 0)
            result.append(meta)
        except Exception:
            continue
    return result


def force_unlock(vm: str) -> bool:
    """强制解锁（仅紧急情况下使用）。"""
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in vm)
    lock_path = LOCK_DIR / f"{safe}.lock"
    meta_path = LOCK_DIR / f"{safe}.json"
    removed = False
    for p in (lock_path, meta_path):
        if p.exists():
            try:
                p.unlink()
                removed = True
            except Exception as e:
                logger.error(f"删除 {p} 失败: {e}")
    if removed:
        logger.warning(f"🔓⚠️ 已强制解锁: {vm}")
    return removed
