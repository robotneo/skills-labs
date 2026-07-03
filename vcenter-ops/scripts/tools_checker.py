"""
Module: scripts.tools_checker
Description: VMware Tools 状态检测与等待。用于克隆/开机后阻塞等待 Tools 就绪。
Author: 运枢
Date: 2026-05-22
Version: 1.0.0

设计要点：
- 区分 Tools 安装状态 vs 运行状态
- wait_for_tools_ready：轮询直到 Tools 进入 toolsOk / toolsOld，或超时
- 提供 get_tools_status_friendly 返回中文友好状态
- 支持进度回调（用于钉钉消息推送）
"""

import time
import logging
from enum import Enum
from typing import Optional, Callable, Dict, Any

from pyVmomi import vim

logger = logging.getLogger(__name__)


class ToolsState(str, Enum):
    """VMware Tools 状态。"""
    NOT_INSTALLED = "toolsNotInstalled"   # 未安装
    NOT_RUNNING = "toolsNotRunning"       # 已安装未运行
    OK = "toolsOk"                        # 正常运行（最新）
    OLD = "toolsOld"                      # 正常运行（版本旧）
    UNKNOWN = "unknown"


READY_STATES = {ToolsState.OK.value, ToolsState.OLD.value}


def get_tools_status(vm: vim.VirtualMachine) -> Dict[str, Any]:
    """
    获取 VM 的 Tools 状态详情。

    :return: {"status": str, "version": str, "running": bool, "ready": bool, "ip": str}
    """
    if not vm or not vm.guest:
        return {
            "status": ToolsState.UNKNOWN.value,
            "version": "",
            "running": False,
            "ready": False,
            "ip": "",
        }

    status = str(vm.guest.toolsStatus or ToolsState.UNKNOWN.value)
    running = status in READY_STATES
    return {
        "status": status,
        "version": str(vm.guest.toolsVersion or ""),
        "version_status": str(vm.guest.toolsVersionStatus2 or vm.guest.toolsVersionStatus or ""),
        "running": running,
        "ready": running,
        "ip": vm.guest.ipAddress or "",
        "hostname": vm.guest.hostName or "",
    }


_STATUS_LABELS = {
    "toolsNotInstalled": "❌ 未安装",
    "toolsNotRunning":   "⏸️  已安装未运行",
    "toolsOk":           "✅ 正常",
    "toolsOld":          "⚠️  正常（版本旧）",
    "unknown":           "❓ 未知",
}


def get_tools_status_friendly(vm: vim.VirtualMachine) -> str:
    """中文友好状态描述。"""
    info = get_tools_status(vm)
    label = _STATUS_LABELS.get(info["status"], info["status"])
    parts = [f"Tools {label}"]
    if info["version"]:
        parts.append(f"v{info['version']}")
    if info["ip"]:
        parts.append(f"IP={info['ip']}")
    return " | ".join(parts)


def wait_for_tools_ready(
    vm: vim.VirtualMachine,
    timeout: int = 300,
    interval: int = 5,
    require_ip: bool = False,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """
    等待 VMware Tools 就绪。

    :param vm: VirtualMachine 对象
    :param timeout: 总超时秒数，默认 300s
    :param interval: 轮询间隔，默认 5s
    :param require_ip: 是否要求 IP 也已分配
    :param on_progress: 进度回调（每次轮询触发）
    :return: 最终的 tools_status 字典（含 ready/ip 等）
    :raises TimeoutError: 超时未就绪
    """
    if not vm:
        raise ValueError("vm 参数为空")

    deadline = time.time() + timeout
    last_info: Dict[str, Any] = {}
    elapsed = 0

    while time.time() < deadline:
        info = get_tools_status(vm)
        info["elapsed"] = elapsed
        info["timeout"] = timeout
        last_info = info

        if on_progress:
            try:
                on_progress(info)
            except Exception:
                logger.debug("on_progress hook 异常", exc_info=True)

        ip_ok = (not require_ip) or bool(info["ip"])
        if info["ready"] and ip_ok:
            logger.info(
                f"VM [{vm.name}] Tools 就绪 (elapsed={elapsed}s, "
                f"status={info['status']}, ip={info['ip'] or 'N/A'})"
            )
            return info

        time.sleep(interval)
        elapsed += interval

    raise TimeoutError(
        f"等待 VM [{vm.name}] Tools 就绪超时 {timeout}s "
        f"(最后状态: {last_info.get('status')}, ip={last_info.get('ip') or 'N/A'})"
    )


def assert_tools_ready(vm: vim.VirtualMachine, op_name: str = "操作") -> Dict[str, Any]:
    """
    断言 Tools 必须就绪，否则抛出 ValueError（带中文修复建议）。
    用于 guest_exec / guest_upload 等强依赖 Tools 的场景。
    """
    info = get_tools_status(vm)
    if info["ready"]:
        return info

    suggestions = {
        ToolsState.NOT_INSTALLED.value: "请在虚拟机内安装 VMware Tools / open-vm-tools",
        ToolsState.NOT_RUNNING.value: "请在虚拟机内启动 vmtoolsd 服务（systemctl start vmtoolsd）",
        ToolsState.UNKNOWN.value: "请先开机并等待几分钟再试",
    }
    advice = suggestions.get(info["status"], "请检查虚拟机 Tools 状态")
    raise ValueError(
        f"❌ {op_name}失败：虚拟机 [{vm.name}] VMware Tools 未就绪 "
        f"(状态: {info['status']})。修复建议：{advice}"
    )


if __name__ == "__main__":
    # 自测
    print("ToolsState ready set:", READY_STATES)
    print("Label NOT_INSTALLED:", _STATUS_LABELS["toolsNotInstalled"])
    print("Label OK:", _STATUS_LABELS["toolsOk"])
    print("✅ tools_checker self-check passed")
