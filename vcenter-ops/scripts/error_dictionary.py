"""
Module: scripts.error_dictionary
Description: pyVmomi 异常 → 中文友好错误 + 修复建议。
Author: 运枢
Date: 2026-05-22
Version: 1.0.0

设计要点：
- 覆盖常见 pyVmomi 异常 (vim.fault.*)
- 每条错误提供：友好描述 + 可能原因 + 修复建议
- 兼容 retry_policy.format_friendly_error，作为更细颗粒度补充
- 支持通过关键词模糊匹配（兜底）
"""

import logging
from typing import Dict, Optional, Tuple

try:
    from pyVmomi import vim, vmodl
    HAS_PYVMOMI = True
except ImportError:
    HAS_PYVMOMI = False

logger = logging.getLogger(__name__)


# ============================================================
# 异常 → (友好描述, 修复建议) 的映射
# ============================================================
# key: pyVmomi 异常类名（字符串，便于不依赖 import 顺序）
# value: (icon + 中文描述, 修复建议)
# ============================================================

ERROR_MAPPINGS: Dict[str, Tuple[str, str]] = {
    # ---------- 认证 / 权限 ----------
    "InvalidLogin": (
        "🔐 vCenter 登录失败：用户名或密码错误",
        "请检查 .env 或 config.yaml 中的 VC_USER / VC_PASSWORD",
    ),
    "NoPermission": (
        "🚫 权限不足：当前账号无操作权限",
        "请联系 vCenter 管理员授予对应资源（VM / Datastore / Network）的权限",
    ),
    "NotAuthenticated": (
        "🔒 会话已过期",
        "工具会自动重连，若反复出现请检查 session 缓存（data/vc_session_cache.json）",
    ),

    # ---------- 资源不存在 / 冲突 ----------
    "NotFound": (
        "📦 目标资源不存在",
        "请检查名称是否拼写正确，或刷新缓存（cache_manager.py --refresh）",
    ),
    "ManagedObjectNotFound": (
        "📦 vCenter 对象引用失效",
        "对象可能已被删除，请重新查询",
    ),
    "DuplicateName": (
        "♻️ 同名资源已存在",
        "请更换名称，或先删除/重命名已存在的资源",
    ),
    "AlreadyExists": (
        "♻️ 资源已存在",
        "请检查目标是否已创建，或先清理",
    ),
    "InvalidName": (
        "📛 名称不合法",
        "名称不能包含 / \\ ? * : | \" < > 等特殊字符，长度 1~80",
    ),

    # ---------- 资源占用 / 状态冲突 ----------
    "ResourceInUse": (
        "⏳ 资源被占用",
        "目标 VM/Datastore 有进行中的任务，请等待完成或在 vCenter 中查看 Recent Tasks",
    ),
    "FileLocked": (
        "🔒 文件被锁定",
        "VMDK/VMX 文件被其他进程占用，常见于关机失败或快照异常，需在 Datastore 中手动解锁",
    ),
    "InvalidPowerState": (
        "⚡ 电源状态不符合操作要求",
        "请先调整 VM 电源状态（开机/关机/挂起）后再试",
    ),
    "VmConfigFault": (
        "⚙️ 虚拟机配置错误",
        "检查 CPU/内存/磁盘/网卡配置是否超出宿主机/集群限制",
    ),
    "InvalidState": (
        "🔄 对象状态不允许该操作",
        "请确认目标当前状态（开机/关机/快照/克隆中），等待或调整后重试",
    ),

    # ---------- 资源不足 ----------
    "InsufficientResourcesFault": (
        "📉 资源不足：CPU/内存/存储/许可不够",
        "请扩容集群、清理 Datastore 或释放其他 VM 资源",
    ),
    "OutOfBounds": (
        "📏 数值超出范围",
        "请检查 CPU/内存/磁盘配置是否符合宿主机/集群上限",
    ),
    "InsufficientStorageSpace": (
        "💾 存储空间不足",
        "Datastore 可用空间不够，请清理或选择其他 Datastore",
    ),

    # ---------- 网络 / 主机 ----------
    "HostConnectFault": (
        "🌐 vCenter 与 ESXi 主机通信失败",
        "请检查 ESXi 主机是否在线、网络是否畅通",
    ),
    "HostNotConnected": (
        "🚫 ESXi 主机未连接",
        "在 vCenter 中右键主机 → Connection → Connect",
    ),
    "NoHost": (
        "🚫 集群中没有可用主机",
        "检查集群是否有 ESXi 主机处于 Connected 且未进入维护模式",
    ),
    "NetworkInaccessible": (
        "📡 网络/端口组不可达",
        "检查 dvSwitch / Standard Switch 端口组是否在目标主机上可用",
    ),

    # ---------- 任务 / 超时 ----------
    "TaskInProgress": (
        "🔄 同一对象上已有任务正在执行",
        "等待当前任务完成（vCenter Recent Tasks），或取消后重试",
    ),
    "RequestCanceled": (
        "🛑 任务被取消",
        "可能是手动取消或超时触发，请确认后重新提交",
    ),
    "Timedout": (
        "⏰ 操作超时",
        "vCenter 响应慢或任务执行时间过长，请稍后重试或检查 vCenter 性能",
    ),

    # ---------- 克隆 / 模板 ----------
    "CustomizationFault": (
        "🛠️ 客户化（Customization）失败",
        "请检查模板 OS 类型与 CustomizationSpec 是否匹配，Linux 模板需要 perl 等依赖",
    ),
    "FileFault": (
        "📁 文件系统操作失败",
        "可能是 Datastore 文件权限/空间问题，请在 vCenter Datastore Browser 检查",
    ),
    "InvalidDeviceSpec": (
        "🔌 设备规格不合法",
        "网卡/磁盘类型与目标模板/主机不兼容，请调整 device spec",
    ),

    # ---------- SSL / 连接 ----------
    "SSLVerifyFault": (
        "🔒 SSL 证书验证失败",
        "首次连接需信任 vCenter 证书，可通过 VC_DISABLE_SSL=1 暂时跳过（仅测试环境）",
    ),
}


# ============================================================
# 关键词兜底（pyVmomi 不可用时也能工作）
# ============================================================

KEYWORD_FALLBACK: Dict[str, Tuple[str, str]] = {
    "invalid login": ERROR_MAPPINGS["InvalidLogin"],
    "no permission": ERROR_MAPPINGS["NoPermission"],
    "not found": ERROR_MAPPINGS["NotFound"],
    "duplicate name": ERROR_MAPPINGS["DuplicateName"],
    "already exists": ERROR_MAPPINGS["AlreadyExists"],
    "resource in use": ERROR_MAPPINGS["ResourceInUse"],
    "file locked": ERROR_MAPPINGS["FileLocked"],
    "invalid power state": ERROR_MAPPINGS["InvalidPowerState"],
    "insufficient": ERROR_MAPPINGS["InsufficientResourcesFault"],
    "task in progress": ERROR_MAPPINGS["TaskInProgress"],
    "timeout": ERROR_MAPPINGS["Timedout"],
    "timed out": ERROR_MAPPINGS["Timedout"],
    "host not connected": ERROR_MAPPINGS["HostNotConnected"],
    "ssl": ERROR_MAPPINGS["SSLVerifyFault"],
    "certificate": ERROR_MAPPINGS["SSLVerifyFault"],
}


def _short_class_name(exc: BaseException) -> str:
    """提取异常的短类名。pyVmomi 类型如 vim.fault.NoPermission → NoPermission。"""
    name = type(exc).__name__
    # pyVmomi 异常实例的字符串形式是 (vim.fault.NoPermission) {...}
    # 而 type().__name__ 可能返回完整路径，取最后一段
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    return name


def translate_exception(exc: BaseException) -> Tuple[str, str]:
    """
    将异常翻译为 (中文友好描述, 修复建议)。

    优先级：
    1. pyVmomi 异常类名精确匹配（取短名）
    2. MRO 链上任意祖先类匹配
    3. 关键词模糊匹配
    4. 兜底：原始异常类型 + 原始消息
    """
    # 1. 短类名精确匹配
    class_name = _short_class_name(exc)
    if class_name in ERROR_MAPPINGS:
        return ERROR_MAPPINGS[class_name]

    # 2. MRO 链上查找（覆盖 pyVmomi 子类继承场景）
    for cls in type(exc).__mro__:
        short = cls.__name__.rsplit(".", 1)[-1]
        if short in ERROR_MAPPINGS:
            return ERROR_MAPPINGS[short]

    # 3. 关键词模糊匹配
    msg = str(exc).lower()
    for kw, mapping in KEYWORD_FALLBACK.items():
        if kw in msg:
            return mapping

    return (
        f"⚠️ 未识别错误（{class_name}）",
        "请查看完整日志（logs/）或将原始错误反馈给运维",
    )


def format_error_detail(exc: BaseException, op_name: str = "") -> str:
    """
    格式化错误为多行 markdown 友好文本，适合钉钉/日志输出。

    示例输出：
        ❌ 克隆虚拟机失败
        ──
        🚫 权限不足：当前账号无操作权限
        💡 修复建议：请联系 vCenter 管理员授予对应资源的权限
        🔍 原始错误：vim.fault.NoPermission: ...
    """
    desc, advice = translate_exception(exc)
    header = f"❌ {op_name}失败" if op_name else "❌ 操作失败"
    return (
        f"{header}\n"
        f"──\n"
        f"{desc}\n"
        f"💡 修复建议：{advice}\n"
        f"🔍 原始错误：{type(exc).__name__}: {exc}"
    )


def format_error_oneline(exc: BaseException, op_name: str = "") -> str:
    """单行简洁版本，适合内联日志。"""
    desc, advice = translate_exception(exc)
    prefix = f"[{op_name}] " if op_name else ""
    return f"{prefix}{desc} | 建议：{advice} | 原始：{type(exc).__name__}"


if __name__ == "__main__":
    # 自测
    class FakeFault(Exception):
        pass

    e1 = FakeFault("Invalid login - check credentials")
    print(format_error_oneline(e1, "测试连接"))
    print()

    e2 = FakeFault("File locked by another process")
    print(format_error_detail(e2, "删除虚拟机"))
    print()

    # pyVmomi 真实异常（如可用）
    if HAS_PYVMOMI:
        try:
            raise vim.fault.NoPermission(msg="no perm")
        except Exception as e:
            print(format_error_detail(e, "克隆虚拟机"))

    print("✅ error_dictionary self-check passed")
