"""
Module: scripts.retry_policy
Description: 通用重试装饰器与错误分类。用于 vCenter 连接、API 调用等场景。
Author: 运枢
Date: 2026-05-21
Version: 0.9.0

设计要点：
- 区分可重试 / 不可重试错误（认证失败立即抛出，网络/超时进行指数退避重试）
- 重试策略可配置：最大次数、退避序列、抖动
- 提供错误分类工具，便于上层做友好提示
"""

import time
import random
import logging
import functools
from enum import Enum
from typing import Callable, Iterable, Optional, Type, Tuple

from pyVmomi import vim, vmodl

logger = logging.getLogger(__name__)


class ErrorCategory(str, Enum):
    """vCenter 错误分类。"""
    NETWORK = "network"        # 网络不通 / 主机不可达 → 重试
    TIMEOUT = "timeout"        # 超时 → 重试
    AUTH = "auth"              # 认证失败 → 不重试
    SSL = "ssl"                # 证书问题 → 不重试
    PERMISSION = "permission"  # 权限不足 → 不重试
    RESOURCE = "resource"      # 资源不存在/冲突 → 不重试
    BUSY = "busy"              # 资源被占用 → 可重试
    UNKNOWN = "unknown"        # 未知 → 默认不重试


# 默认可重试的错误类别
RETRYABLE_CATEGORIES = {ErrorCategory.NETWORK, ErrorCategory.TIMEOUT, ErrorCategory.BUSY}


def classify_error(exc: BaseException) -> ErrorCategory:
    """
    将任意异常归类为 ErrorCategory。
    优先匹配 pyVmomi 特定异常，再 fallback 到字符串关键词匹配。
    """
    # pyVmomi 特定异常
    if isinstance(exc, vim.fault.InvalidLogin):
        return ErrorCategory.AUTH
    if isinstance(exc, vim.fault.NoPermission):
        return ErrorCategory.PERMISSION
    if isinstance(exc, vim.fault.NotFound):
        return ErrorCategory.RESOURCE
    if isinstance(exc, vim.fault.DuplicateName):
        return ErrorCategory.RESOURCE
    if isinstance(exc, vim.fault.ResourceInUse):
        return ErrorCategory.BUSY
    if isinstance(exc, vmodl.fault.RequestCanceled):
        return ErrorCategory.TIMEOUT

    # 通用异常关键词匹配
    msg = str(exc).lower()
    if any(k in msg for k in ["timeout", "timed out", "deadline"]):
        return ErrorCategory.TIMEOUT
    if any(k in msg for k in ["connection refused", "unreachable", "no route", "name or service not known", "network is unreachable"]):
        return ErrorCategory.NETWORK
    if any(k in msg for k in ["ssl", "certificate", "tlsv1"]):
        return ErrorCategory.SSL
    if any(k in msg for k in ["invalid login", "authentication", "unauthorized", "permission denied"]):
        return ErrorCategory.AUTH
    if any(k in msg for k in ["busy", "in use", "locked"]):
        return ErrorCategory.BUSY

    return ErrorCategory.UNKNOWN


def retry(
    max_attempts: int = 3,
    backoff: Iterable[float] = (1, 3, 9),
    jitter: float = 0.3,
    retry_on: Optional[Iterable[ErrorCategory]] = None,
    exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    on_retry: Optional[Callable[[int, BaseException, float], None]] = None,
):
    """
    通用重试装饰器，支持指数退避 + 抖动 + 错误分类。

    :param max_attempts: 最大尝试次数（含首次）
    :param backoff: 每次重试间隔序列（秒），长度建议 = max_attempts - 1
    :param jitter: 抖动比例 [0, 1]，例如 0.3 表示 ±30% 随机抖动
    :param retry_on: 仅当错误分类在此集合内才重试，None=使用默认 RETRYABLE_CATEGORIES
    :param exceptions: 捕获的异常类型
    :param on_retry: 重试钩子 (attempt, exc, wait_seconds) -> None
    """
    backoff_list = list(backoff)
    allowed = set(retry_on) if retry_on else RETRYABLE_CATEGORIES

    def decorator(func: Callable):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: Optional[BaseException] = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    category = classify_error(exc)

                    # 不可重试的错误立即抛出
                    if category not in allowed:
                        logger.error(f"[{func.__name__}] 不可重试错误 ({category.value}): {exc}")
                        raise

                    # 已达最大次数
                    if attempt >= max_attempts:
                        logger.error(f"[{func.__name__}] 重试已达上限 {max_attempts} 次，放弃: {exc}")
                        raise

                    # 计算下一次等待时间
                    base_wait = backoff_list[min(attempt - 1, len(backoff_list) - 1)]
                    wait = base_wait * (1 + random.uniform(-jitter, jitter))
                    wait = max(0.1, wait)

                    logger.warning(
                        f"[{func.__name__}] 第 {attempt}/{max_attempts} 次失败 "
                        f"({category.value}): {exc} → {wait:.1f}s 后重试"
                    )
                    if on_retry:
                        try:
                            on_retry(attempt, exc, wait)
                        except Exception:
                            logger.debug("on_retry 钩子异常，忽略", exc_info=True)
                    time.sleep(wait)

            # 理论上不会到这里
            if last_exc:
                raise last_exc
            raise RuntimeError(f"[{func.__name__}] 重试逻辑异常退出")
        return wrapper
    return decorator


def format_friendly_error(exc: BaseException) -> str:
    """根据错误分类生成中文友好提示（供 UI/日志使用）。"""
    category = classify_error(exc)
    mapping = {
        ErrorCategory.NETWORK: "🌐 网络不通，请检查 vCenter 主机连通性",
        ErrorCategory.TIMEOUT: "⏰ vCenter 响应超时，请稍后重试",
        ErrorCategory.AUTH: "🔐 vCenter 认证失败，请检查用户名/密码",
        ErrorCategory.SSL: "🔒 SSL 证书验证失败",
        ErrorCategory.PERMISSION: "🚫 当前账号权限不足",
        ErrorCategory.RESOURCE: "📦 目标资源不存在或冲突",
        ErrorCategory.BUSY: "⏳ 资源被占用，请稍后重试",
        ErrorCategory.UNKNOWN: "⚠️ 未知错误",
    }
    return f"{mapping.get(category, mapping[ErrorCategory.UNKNOWN])} | 原因: {exc}"
