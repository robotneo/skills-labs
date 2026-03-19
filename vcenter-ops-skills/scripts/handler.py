"""
Module: scripts.handler
Description: OpenClaw 技能包统一入口分发器 (增强版)。
支持高级克隆参数解析（规格、网络自定义、物理宿主机定向调度），并输出标准 JSON。
Author: xiaofei
Date: 2026-03-19
"""

import sys
import json
import argparse
import logging
from typing import Dict, Any

# 导入自定义模块
from client import VCenterClient
from inventory import VCenterInventory
from executor import VCenterExecutor

# 配置基础日志格式：必须输出至 stderr，确保 stdout 只有干净的 JSON 数据供 LLM 解析
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

def create_arg_parser() -> argparse.ArgumentParser:
    """
    构造增强型命令行参数解析器。
    涵盖了从基础资产查询到复杂克隆所需的所有维度。
    """
    parser = argparse.ArgumentParser(description="vCenter Ops Skills Advanced Handler")
    
    # --- 基础连接参数 ---
    parser.add_argument("--host", required=True, help="vCenter 主机地址")
    parser.add_argument("--user", required=True, help="用户名")
    parser.add_argument("--pwd", required=True, help="密码")
    parser.add_argument("--port", type=int, default=443, help="端口")

    # --- 动作控制 ---
    parser.add_argument("--action", required=True, 
                        choices=["list_all", "get_vm", "clone_vm", "delete_vm", "power_vm"],
                        help="执行的操作类型")

    # --- 核心业务参数 ---
    parser.add_argument("--vm_name", help="虚拟机名称")
    parser.add_argument("--template", help="克隆源模板名称")
    parser.add_argument("--dc", help="数据中心名称")
    parser.add_argument("--cluster", help="计算集群名称")
    parser.add_argument("--ds", help="存储池名称")
    parser.add_argument("--network", help="目标网络/VLAN名称")

    # --- 高级调度与硬件重配置参数 ---
    parser.add_argument("--host_node", help="（可选）指定目标物理宿主机节点名称")
    parser.add_argument("--cpus", type=int, help="自定义 CPU 核数")
    parser.add_argument("--memory", type=int, help="自定义内存大小 (MB)")
    parser.add_argument("--disk", type=int, help="自定义主磁盘容量 (GB)")

    # --- 网络自定义参数 (CustomizationSpec) ---
    parser.add_argument("--ip", help="（可选）静态 IP 地址")
    parser.add_argument("--mask", default="255.255.255.0", help="子网掩码")
    parser.add_argument("--gw", help="默认网关")

    # --- 辅助控制 ---
    parser.add_argument("--state", choices=["on", "off", "reset"], help="电源操作状态")
    parser.add_argument("--power_on", action="store_true", help="操作完成后是否尝试开机")

    return parser

def main():
    """
    主分发逻辑。
    """
    parser = create_arg_parser()
    args = parser.parse_args()

    # 预定义标准返回结构
    response: Dict[str, Any] = {
        "status": "success",
        "action": args.action,
        "data": None,
        "message": ""
    }

    try:
        # 使用上下文管理器维持 vCenter 会话
        with VCenterClient(args.host, args.user, args.pwd, args.port) as si:
            
            inventory = VCenterInventory(si)
            executor = VCenterExecutor(si)

            # --- [1] 资产深度发现 ---
            if args.action == "list_all":
                # 包含物理机、虚拟机、模板、存储、网络的完整画像
                response["data"] = inventory.fetch_all_inventory()
                response["message"] = "全栈资产清单扫描完成"

            # --- [2] 虚拟机状态确认 ---
            elif args.action == "get_vm":
                if not args.vm_name:
                    raise ValueError("操作 'get_vm' 必须提供 --vm_name")
                vm_data = inventory.get_single_vm_detail(args.vm_name)
                if not vm_data:
                    response["status"] = "fail"
                    response["message"] = f"未找到该虚拟机: {args.vm_name}"
                else:
                    response["data"] = vm_data

            # --- [3] 深度自定义克隆 (核心逻辑) ---
            elif args.action == "clone_vm":
                # 基础必填项校验
                required_fields = [args.template, args.vm_name, args.dc, args.cluster, args.ds, args.network]
                if not all(required_fields):
                    raise ValueError("克隆操作缺少必填资源定位参数 (template/vm_name/dc/cluster/ds/network)")
                
                # 调用 executor 的高级克隆函数
                msg = executor.clone_vm_advanced(
                    template_name=args.template,
                    new_name=args.vm_name,
                    dc_name=args.dc,
                    cluster_name=args.cluster,
                    ds_name=args.ds,
                    network_name=args.network,
                    host_name=args.host_node,   # 定向调度物理机
                    cpus=args.cpus,             # 规格调整
                    memory_mb=args.memory,      # 规格调整
                    disk_gb=args.disk,          # 磁盘调整
                    ip_address=args.ip,         # 网络注入
                    subnet=args.mask,           # 网络注入
                    gateway=args.gw             # 网络注入
                )
                response["message"] = msg

            # --- [4] 电源管理 ---
            elif args.action == "power_vm":
                if not all([args.vm_name, args.state]):
                    raise ValueError("电源管理需要 --vm_name 和 --state")
                msg = executor.set_vm_power(args.vm_name, args.state)
                response["message"] = msg

            # --- [5] 删除虚拟机 ---
            elif args.action == "delete_vm":
                if not args.vm_name:
                    raise ValueError("删除操作必须提供 --vm_name")
                msg = executor.remove_vm(args.vm_name)
                response["message"] = msg

    except Exception as e:
        logger.error(f"Handler 执行故障: {str(e)}", exc_info=True)
        response["status"] = "error"
        response["message"] = f"执行异常: {str(e)}"

    # 最终结果输出给 OpenClaw / LLM
    # ensure_ascii=False 保证中文 message 不会被转码
    print(json.dumps(response, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()