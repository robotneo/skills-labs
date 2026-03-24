#!/usr/bin/env python3
"""
Module: scripts.handler
Description: vCenter Ops 技能统一入口分发器。
支持从 config.yaml 自动读取连接信息，也可通过命令行参数覆盖。
Author: xiaofei
Date: 2026-03-19
Updated: 2026-03-20
"""

import sys
import os
import json
import argparse
import logging
from pathlib import Path
from typing import Dict, Any

# 将项目根目录添加到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.client import VCenterClient
from scripts.inventory import VCenterInventory
from scripts.executor import VCenterExecutor

# 技能根目录（SKILL.md 所在目录）
SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_FILE = SKILL_DIR / "config.yaml"

# 日志输出至 stderr，stdout 只输出干净 JSON
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


def load_config() -> Dict[str, Any]:
    """
    从 config.yaml 读取 vCenter 连接信息与环境默认值。
    config.yaml 不存在或格式异常时返回空 dict。
    """
    if not CONFIG_FILE.exists():
        logger.warning(f"配置文件不存在: {CONFIG_FILE}")
        return {}

    try:
        import yaml
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        logger.info(f"已加载配置文件: {CONFIG_FILE}")
        return cfg
    except ImportError:
        logger.warning("缺少 PyYAML 依赖，无法读取 config.yaml，请执行: pip install pyyaml")
        return {}
    except Exception as e:
        logger.warning(f"读取 config.yaml 失败: {e}")
        return {}


def save_config(cfg: Dict[str, Any]) -> bool:
    """
    将配置写回 config.yaml。
    """
    try:
        import yaml
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(cfg, f, default_flow_style=False, allow_unicode=True)
        logger.info(f"配置已保存到: {CONFIG_FILE}")
        return True
    except Exception as e:
        logger.error(f"保存 config.yaml 失败: {e}")
        return False


def create_arg_parser() -> argparse.ArgumentParser:
    """
    命令行参数解析器。
    --host / --user / --pwd 改为可选，未提供时自动从 config.yaml 读取。
    """
    parser = argparse.ArgumentParser(description="vCenter Ops Handler")

    # --- 连接参数（可选，降级读 config.yaml） ---
    parser.add_argument("--host", help="vCenter 主机地址（可选，默认读 config.yaml）")
    parser.add_argument("--user", help="用户名（可选，默认读 config.yaml）")
    parser.add_argument("--pwd", help="密码（可选，默认读 config.yaml）")
    parser.add_argument("--port", type=int, help="端口（可选，默认读 config.yaml）")

    # --- 动作控制 ---
    parser.add_argument("--action", required=True,
                        choices=["list_all", "get_vm", "clone_vm", "delete_vm", "power_vm", "snapshot"],
                        help="执行的操作类型")

    # --- 核心业务参数 ---
    parser.add_argument("--hostname", help="虚拟机名称")
    parser.add_argument("--template", help="克隆源模板名称")
    parser.add_argument("--dc", help="数据中心名称")
    parser.add_argument("--cluster", help="计算集群名称")
    parser.add_argument("--ds", help="存储池名称")
    parser.add_argument("--network", help="目标网络/VLAN 名称")

    # --- 高级调度与硬件参数 ---
    parser.add_argument("--host_node", help="指定物理宿主机节点名称")
    parser.add_argument("--cpu", type=int, help="CPU 核数")
    parser.add_argument("--memory", type=int, help="内存大小 (GB)")
    parser.add_argument("--disk", type=int, help="主磁盘容量 (GB)")

    # --- 网络参数 ---
    parser.add_argument("--ip", help="静态 IP 地址")
    parser.add_argument("--mask", help="子网掩码")
    parser.add_argument("--gw", help="默认网关")

    # --- 辅助控制 ---
    parser.add_argument("--state", choices=["on", "off", "reset"], help="电源操作状态")
    parser.add_argument("--power_on", action="store_true", help="完成后是否开机")

    return parser


def resolve_connection(args, cfg: Dict[str, Any]) -> tuple:
    """
    合并连接参数：命令行 > config.yaml > 报错。
    返回 (host, user, pwd, port)。
    """
    vc = cfg.get("vcenter", {})
    defaults = cfg.get("defaults", {})

    host = args.host or vc.get("host", "")
    user = args.user or vc.get("user", "")
    pwd = args.pwd or vc.get("password", "")
    port = args.port or vc.get("port", 443)

    missing = []
    if not host: missing.append("host")
    if not user: missing.append("user")
    if not pwd: missing.append("password")

    if missing:
        raise ValueError(
            f"vCenter 连接信息缺失: {', '.join(missing)}。"
            f"请通过命令行参数传入或更新 config.yaml。"
        )

    return host, user, pwd, port


def main():
    parser = create_arg_parser()
    args = parser.parse_args()

    # 读取配置文件
    cfg = load_config()

    response: Dict[str, Any] = {
        "status": "success",
        "action": args.action,
        "data": None,
        "message": ""
    }

    try:
        # 解析连接信息
        host, user, pwd, port = resolve_connection(args, cfg)

        with VCenterClient(host, user, pwd, port) as si:
            inventory = VCenterInventory(si)
            executor = VCenterExecutor(si)

            if args.action == "list_all":
                response["data"] = inventory.fetch_all_inventory()
                response["message"] = "全栈资产清单扫描完成"

            elif args.action == "get_vm":
                if not args.hostname:
                    raise ValueError("操作 'get_vm' 必须提供 --hostname")
                vm_data = inventory.get_single_vm_detail(args.hostname)
                if not vm_data:
                    response["status"] = "fail"
                    response["message"] = f"未找到该虚拟机: {args.hostname}"
                else:
                    response["data"] = vm_data

            elif args.action == "clone_vm":
                required = [args.template, args.hostname, args.dc, args.cluster, args.ds, args.network]
                if not all(required):
                    raise ValueError("克隆缺少必填参数 (template/hostname/dc/cluster/ds/network)")

                msg = executor.clone_vm_advanced(
                    template_name=args.template,
                    new_name=args.hostname,
                    dc_name=args.dc,
                    cluster_name=args.cluster,
                    ds_name=args.ds,
                    network_name=args.network,
                    host_name=args.host_node,
                    cpus=args.cpu,
                    memory_gb=args.memory,
                    disk_gb=args.disk,
                    ip_address=args.ip,
                    subnet=args.mask,
                    gateway=args.gw
                )
                response["message"] = msg

            elif args.action == "power_vm":
                if not all([args.hostname, args.state]):
                    raise ValueError("电源管理需要 --hostname 和 --state")
                msg = executor.set_vm_power(args.hostname, args.state)
                response["message"] = msg

            elif args.action == "delete_vm":
                if not args.hostname:
                    raise ValueError("删除操作必须提供 --hostname")
                msg = executor.remove_vm(args.hostname)
                response["message"] = msg

            elif args.action == "snapshot":
                if not args.hostname:
                    raise ValueError("快照操作必须提供 --hostname")
                if not args.state:
                    # 默认创建快照
                    snap_name = args.state or f"snap-{args.hostname}"
                    msg = executor.create_snapshot(args.hostname, snap_name)
                response["message"] = msg

    except Exception as e:
        logger.error(f"Handler 执行故障: {str(e)}", exc_info=True)
        response["status"] = "error"
        response["message"] = f"执行异常: {str(e)}"

    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
