"""
Module: scripts.preset_manager
Description: 参数预设包管理器。加载 presets/*.yaml，支持 @preset-name 引用与合并。
Author: 运枢
Date: 2026-05-22
Version: 1.0.0

设计要点：
- 预设位于 presets/*.yaml，文件名 = 预设名
- 优先级：用户传入参数 > preset params > preset defaults
- @dev-small 在 CLI/handler 中可作为快捷引用
- 支持 list_presets / get_preset / apply_preset 三个核心 API
"""

import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).resolve().parent.parent
PRESET_DIR = SKILL_DIR / "presets"

try:
    import yaml  # PyYAML
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not HAS_YAML:
        raise RuntimeError("PyYAML 未安装，请先 pip install pyyaml")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def list_presets() -> List[Dict[str, Any]]:
    """列出所有可用预设。"""
    if not PRESET_DIR.exists():
        return []
    presets = []
    for f in sorted(PRESET_DIR.glob("*.yaml")):
        try:
            data = _load_yaml(f)
            data["_file"] = f.name
            data.setdefault("name", f.stem)
            presets.append(data)
        except Exception as e:
            logger.warning(f"加载预设 {f.name} 失败: {e}")
    return presets


def get_preset(name: str) -> Optional[Dict[str, Any]]:
    """按名称获取预设。支持 @dev-small / dev-small 两种写法。"""
    if not name:
        return None
    n = name.lstrip("@").strip()
    candidate = PRESET_DIR / f"{n}.yaml"
    if not candidate.exists():
        return None
    data = _load_yaml(candidate)
    data["_file"] = candidate.name
    data.setdefault("name", n)
    return data


def apply_preset(
    preset_name: str,
    user_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    将预设应用到用户参数上。

    合并优先级（高 → 低）：
        user_params > preset.params > preset.defaults

    :raises ValueError: 预设不存在
    :return: 合并后的参数字典
    """
    preset = get_preset(preset_name)
    if not preset:
        available = ", ".join(p.get("name", "?") for p in list_presets()) or "(无)"
        raise ValueError(
            f"❌ 预设 [{preset_name}] 不存在。可用预设: {available}"
        )

    merged: Dict[str, Any] = {}
    merged.update(preset.get("defaults") or {})
    merged.update(preset.get("params") or {})
    if user_params:
        # 仅覆盖 user 显式提供的非空字段
        for k, v in user_params.items():
            if v is not None:
                merged[k] = v

    # 元信息（供 handler / 日志使用）
    merged["_preset"] = preset.get("name")
    merged["_preset_desc"] = preset.get("description", "")
    merged["_require_confirm"] = bool(preset.get("require_confirm"))
    return merged


# ============================================================
# 创建 / 删除 / 从历史保存
# ============================================================

def save_preset(
    name: str,
    params: Dict[str, Any],
    description: str = "",
    tags: Optional[List[str]] = None,
    require_confirm: bool = False,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """
    创建或更新预设。

    :param name: 预设名（不含 @）
    :param params: 参数字典（如 {cpus: 4, memory_gb: 8}）
    :param description: 预设说明
    :param tags: 标签列表
    :param require_confirm: 使用时是否强制二次确认
    :param overwrite: 同名是否覆盖
    :raises ValueError: 预设名不合法 / 已存在且未允许覆盖
    """
    if not HAS_YAML:
        raise RuntimeError("PyYAML 未安装，请先 pip install pyyaml")

    import re
    n = name.lstrip("@").strip()
    if not re.match(r"^[a-zA-Z][a-zA-Z0-9_-]{0,30}$", n):
        raise ValueError(
            f"预设名 [{n}] 不合法。要求：以字母开头，仅含字母/数字/_/-，长度≤1 31"
        )

    PRESET_DIR.mkdir(parents=True, exist_ok=True)
    target = PRESET_DIR / f"{n}.yaml"
    if target.exists() and not overwrite:
        raise ValueError(f"预设 [{n}] 已存在，需明示传 overwrite=True 覆盖")

    # 过滤在预设中不合适的字段（如 hostname/ip，应由调用者提供）
    clean_params: Dict[str, Any] = {}
    safe_keys = {
        "template_name", "dc_name", "cluster_name", "host_name",
        "ds_name", "network_name",
        "cpus", "memory_gb", "disk_gb", "subnet", "gateway",
    }
    for k, v in (params or {}).items():
        if k in safe_keys and v is not None:
            clean_params[k] = v

    data = {
        "name": n,
        "description": description or f"用户自定义预设 ({n})",
        "op": "clone_vm",
        "params": clean_params,
        "defaults": {"subnet": "255.255.255.0"},
        "tags": tags or ["custom"],
    }
    if require_confirm:
        data["require_confirm"] = True

    target.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    logger.info(f"✅ 预设 [{n}] 已保存: {target}")
    return data


def delete_preset(name: str) -> bool:
    """删除预设。返回 True 表示删除成功，False 表示不存在。"""
    n = name.lstrip("@").strip()
    target = PRESET_DIR / f"{n}.yaml"
    if target.exists():
        target.unlink()
        logger.info(f"🗑️ 预设 [{n}] 已删除")
        return True
    return False


def save_from_history(
    name: str,
    history_record: Dict[str, Any],
    description: str = "",
    overwrite: bool = False,
) -> Dict[str, Any]:
    """
    从一条 history_manager 返回的 last_clone_params 结果保存为预设。

    :param name: 新预设名
    :param history_record: history_manager.last_clone_params() 的返回值
    """
    if not history_record or not history_record.get("params"):
        raise ValueError("history_record 为空或不含 params")

    params = dict(history_record["params"])
    desc = description or (
        f"从历史记录 {history_record.get('source_task_id', '?')} 存为预设"
    )
    return save_preset(name, params, description=desc, overwrite=overwrite, tags=["custom", "from-history"])


def parse_preset_from_text(text: str) -> Optional[str]:
    """
    从用户输入中识别 @preset-name 引用。

    示例：
        "克隆 web01 @dev-small"  → "dev-small"
        "@prod-large 克隆 db01"  → "prod-large"
    """
    import re
    m = re.search(r"@([a-zA-Z][a-zA-Z0-9_-]+)", text or "")
    return m.group(1) if m else None


def format_preset_list(presets: List[Dict[str, Any]]) -> str:
    if not presets:
        return "📭 暂无预设包"
    lines = ["| 预设名 | 说明 | 规格 | 标签 |", "|--------|------|------|------|"]
    for p in presets:
        params = p.get("params") or {}
        spec = []
        if params.get("cpus"): spec.append(f"{params['cpus']}C")
        if params.get("memory_gb"): spec.append(f"{params['memory_gb']}G")
        if params.get("disk_gb"): spec.append(f"{params['disk_gb']}GB")
        tags = ", ".join(p.get("tags") or [])
        lines.append(
            f"| @{p.get('name','?')} | {p.get('description','-')} | "
            f"{'/'.join(spec) or '-'} | {tags or '-'} |"
        )
    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

def _cli():
    import argparse
    parser = argparse.ArgumentParser(description="vCenter 参数预设管理")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="列出所有预设")

    p_show = sub.add_parser("show", help="查看预设详情")
    p_show.add_argument("name")

    p_apply = sub.add_parser("apply", help="模拟应用预设（合并 user 参数）")
    p_apply.add_argument("name")
    p_apply.add_argument("--vm", default=None)
    p_apply.add_argument("--ip", default=None)

    p_save = sub.add_parser("save", help="创建/保存预设")
    p_save.add_argument("name")
    p_save.add_argument("--desc", default="")
    p_save.add_argument("--cpus", type=int)
    p_save.add_argument("--memory", type=int, dest="memory_gb")
    p_save.add_argument("--disk", type=int, dest="disk_gb")
    p_save.add_argument("--template", dest="template_name")
    p_save.add_argument("--dc", dest="dc_name")
    p_save.add_argument("--cluster", dest="cluster_name")
    p_save.add_argument("--ds", dest="ds_name")
    p_save.add_argument("--network", dest="network_name")
    p_save.add_argument("--host", dest="host_name")
    p_save.add_argument("--gw", dest="gateway")
    p_save.add_argument("--tag", action="append", default=[], dest="tags")
    p_save.add_argument("--require-confirm", action="store_true")
    p_save.add_argument("--overwrite", action="store_true")

    p_sfh = sub.add_parser("save-from-history", help="从历史记录保存为预设")
    p_sfh.add_argument("name")
    p_sfh.add_argument("--from-vm", dest="from_vm", help="以该 VM 的最近一次克隆为源")
    p_sfh.add_argument("--desc", default="")
    p_sfh.add_argument("--overwrite", action="store_true")

    p_del = sub.add_parser("delete", help="删除预设")
    p_del.add_argument("name")

    args = parser.parse_args()

    if args.cmd == "list":
        print(format_preset_list(list_presets()))
    elif args.cmd == "show":
        p = get_preset(args.name)
        if not p:
            print(f"❌ 预设 {args.name} 不存在"); return
        import json
        print(json.dumps(p, ensure_ascii=False, indent=2))
    elif args.cmd == "apply":
        user = {}
        if args.vm: user["new_name"] = args.vm
        if args.ip: user["ip_address"] = args.ip
        merged = apply_preset(args.name, user)
        import json
        print(json.dumps(merged, ensure_ascii=False, indent=2))
    elif args.cmd == "save":
        params = {}
        for k in ("cpus","memory_gb","disk_gb","template_name","dc_name",
                  "cluster_name","ds_name","network_name","host_name","gateway"):
            v = getattr(args, k, None)
            if v is not None:
                params[k] = v
        data = save_preset(
            args.name, params,
            description=args.desc,
            tags=args.tags or None,
            require_confirm=args.require_confirm,
            overwrite=args.overwrite,
        )
        import json
        print("✅ 保存成功。预设内容:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.cmd == "save-from-history":
        try:
            from .history_manager import last_clone_params
        except ImportError:
            from history_manager import last_clone_params
        info = last_clone_params(args.from_vm)
        if not info:
            print("❌ 未找到历史记录"); return
        data = save_from_history(args.name, info, description=args.desc, overwrite=args.overwrite)
        import json
        print("✅ 已从历史保存为预设:")
        print(json.dumps(data, ensure_ascii=False, indent=2))
    elif args.cmd == "delete":
        ok = delete_preset(args.name)
        print(f"{'✅ 已删除' if ok else '⚠️ 未找到预设'}: {args.name}")
    else:
        parser.print_help()


if __name__ == "__main__":
    _cli()
