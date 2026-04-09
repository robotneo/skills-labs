#!/usr/bin/env python3
"""
Module: scripts.handler
Description: vCenter Ops 技能统一入口分发器。
支持从 config.yaml 自动读取连接信息，也可通过命令行参数覆盖。
Author: xiaofei
Date: 2026-03-19
Updated: 2026-04-08
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
from scripts import audit
from scripts import plan_manager
from scripts import ttl_manager
from scripts import approval_manager

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
    parser.add_argument("--action",
                        choices=[
                            "list_all", "get_vm", "clone_vm", "delete_vm", "power_vm",
                            "snapshot", "reconfigure",
                            "guest_exec", "migrate", "plan", "ttl", "datastore",
                            "template", "batch", "approval", "events", "quota", "export",
                        ],
                        help="执行的操作类型（--audit-query 时可选）")

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

    # --- 快照子操作参数 ---
    parser.add_argument("--snap_action", choices=["create", "list", "revert", "delete"],
                        help="快照子操作类型（create/list/revert/delete）")
    parser.add_argument("--snap_name", help="快照名称")

    # --- Dry-Run 模式 ---
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="Dry-Run 模式：只输出将要执行的操作，不实际执行")

    # --- 审计日志查询 ---
    parser.add_argument("--audit-query", action="store_true", dest="audit_query",
                        help="查询审计日志（配合 --action 和 --hostname 筛选）")

    # --- Guest OS 操作参数 ---
    parser.add_argument("--cmd", help="Guest OS 中要执行的命令")
    parser.add_argument("--guest-user", default="root", help="Guest OS 用户名（默认 root）")
    parser.add_argument("--guest-pwd", default="", help="Guest OS 密码")

    # --- vMotion 参数 ---
    parser.add_argument("--target_host", help="vMotion 目标宿主机名/IP")

    # --- Plan 操作参数 ---
    parser.add_argument("--plan_action", choices=["create", "execute", "rollback", "list", "delete"],
                        help="计划子操作类型")
    parser.add_argument("--plan_id", help="计划 ID")
    parser.add_argument("--plan_steps", help="计划步骤列表（JSON 格式）")
    parser.add_argument("--plan_desc", help="计划描述")

    # --- TTL 参数 ---
    parser.add_argument("--ttl_action", choices=["set", "cancel", "list", "cleanup"],
                        help="TTL 子操作类型")
    parser.add_argument("--ttl_minutes", type=int, help="TTL 分钟数")
    parser.add_argument("--creator", default="agent", help="TTL 设置者")

    # --- 数据存储参数 ---
    parser.add_argument("--ds_name", help="数据存储名称")
    parser.add_argument("--ds_path", default="", help="数据存储子路径")
    parser.add_argument("--ds_scan", action="store_true", help="扫描所有数据存储中的镜像文件")

    # --- 模板管理参数 ---
    parser.add_argument("--tpl_action", choices=["list", "register", "convert"],
                        help="模板子操作类型（list/register/convert）")
    parser.add_argument("--tpl_name", help="模板名称（register 时使用）")

    # --- 批量操作参数 ---
    parser.add_argument("--batch_action", choices=["power"], help="批量子操作类型")
    parser.add_argument("--pattern", help="VM 名称匹配模式（支持 * 和 ? 通配符）")

    # --- 审批参数 ---
    parser.add_argument("--approval_action", choices=["create", "approve", "reject", "list", "cancel"],
                        help="审批子操作类型")
    parser.add_argument("--approval_id", help="审批 ID")
    parser.add_argument("--approval_params", help="审批关联的操作参数（JSON 格式）")
    parser.add_argument("--approval_target_action", help="审批关联的目标操作类型")
    parser.add_argument("--comment", help="审批意见")

    # --- 事件查询参数 ---
    parser.add_argument("--minutes", type=int, help="查询最近 N 分钟的事件（默认 60）")
    parser.add_argument("--event_category", choices=["power", "create_delete", "migration", "snapshot", "alarm"],
                        help="事件类别过滤")

    # --- 资源配额参数 ---
    parser.add_argument("--cpu_threshold", type=float, help="CPU 使用率告警阈值（0-1，默认 0.85）")
    parser.add_argument("--mem_threshold", type=float, help="内存使用率告警阈值（默认 0.85）")
    parser.add_argument("--disk_threshold", type=float, help="磁盘使用率告警阈值（默认 0.9）")

    # --- 导出报表参数 ---
    parser.add_argument("--export_format", choices=["json", "csv", "markdown"],
                        help="导出格式（默认 json）")
    parser.add_argument("--output", help="输出文件路径")

    # --- 通用分页/限制 ---
    parser.add_argument("--top", type=int, default=50, help="返回结果数量限制")

    return parser


def resolve_connection(args, cfg: Dict[str, Any]) -> tuple:
    """
    合并连接参数：命令行 > config.yaml 明文 > .env 环境变量 > password_ref 引用。
    返回 (host, user, pwd, port)。
    """
    vc = cfg.get("vcenter", {})

    host = args.host or vc.get("host", "")
    user = args.user or vc.get("user", "")
    port = args.port or vc.get("port", 443)

    # 密码：命令行 > config.yaml 明文 > .env 环境变量 > password_ref 引用
    pwd = args.pwd or vc.get("password", "")
    if not pwd:
        # 尝试从 .env 文件加载
        env_file = SKILL_DIR / ".env"
        if env_file.exists():
            from dotenv import load_dotenv
            load_dotenv(env_file)
        # 检查 password_ref
        ref = vc.get("password_ref", "")
        if ref:
            pwd = os.environ.get(ref, "")

    missing = []
    if not host:
        missing.append("host")
    if not user:
        missing.append("user")
    if not pwd:
        missing.append("password")

    if missing:
        raise ValueError(
            f"vCenter 连接信息缺失: {', '.join(missing)}。"
            f"请检查 .env 文件或 config.yaml。"
        )

    return host, user, pwd, port


def main():
    parser = create_arg_parser()
    args = parser.parse_args()

    # 读取配置文件
    cfg = load_config()

    # --- 审计日志查询（无需 vCenter 连接） ---
    if args.audit_query:
        results = audit.query(action=args.action or None, target=args.hostname or None)
        print(json.dumps({
            "status": "ok",
            "action": "audit_query",
            "data": results,
            "message": f"共 {len(results)} 条审计记录"
        }, ensure_ascii=False, indent=2))
        return

    # 非 audit_query 时 action 必填
    if not args.action:
        parser.error("--action 为必填参数（或使用 --audit-query 查询审计日志）")

    response: Dict[str, Any] = {
        "status": "success",
        "action": args.action,
        "data": None,
        "message": ""
    }

    # --- Dry-Run 模式（不建立 vCenter 连接） ---
    if args.dry_run:
        params = {}
        if args.hostname:
            params["hostname"] = args.hostname
        if args.template:
            params["template"] = args.template
        if args.dc:
            params["dc"] = args.dc
        if args.cluster:
            params["cluster"] = args.cluster
        if args.ds:
            params["ds"] = args.ds
        if args.network:
            params["network"] = args.network
        if args.host_node:
            params["host_node"] = args.host_node
        if args.cpu:
            params["cpu"] = args.cpu
        if args.memory:
            params["memory_gb"] = args.memory
        if args.disk:
            params["disk_gb"] = args.disk
        if args.ip:
            params["ip"] = args.ip
        if args.mask:
            params["mask"] = args.mask
        if args.gw:
            params["gw"] = args.gw
        if args.state:
            params["state"] = args.state
        if args.power_on:
            params["power_on"] = True
        if args.snap_action:
            params["snap_action"] = args.snap_action
        if args.snap_name:
            params["snap_name"] = args.snap_name
        if args.cmd:
            params["cmd"] = args.cmd
        if args.target_host:
            params["target_host"] = args.target_host
        if args.plan_action:
            params["plan_action"] = args.plan_action
        if args.plan_steps:
            params["plan_steps"] = args.plan_steps
        if args.plan_desc:
            params["plan_desc"] = args.plan_desc
        if args.ttl_action:
            params["ttl_action"] = args.ttl_action
        if args.ttl_minutes:
            params["ttl_minutes"] = args.ttl_minutes
        if args.ds_name:
            params["ds_name"] = args.ds_name
        if args.ds_path:
            params["ds_path"] = args.ds_path
        if args.ds_scan:
            params["ds_scan"] = True

        target = args.hostname or "(无目标)"
        audit.record(args.action, target, "dry_run", details=params)

        print(json.dumps({
            "status": "dry_run",
            "action": args.action,
            "params": params,
            "message": "Dry-Run 模式，未执行任何操作"
        }, ensure_ascii=False, indent=2))
        return

    # ========== 无需 vCenter 连接的操作（提前处理） ==========

    # --- Plan: create / list / delete（无需连接） ---
    if args.action == "plan":
        plan_act = args.plan_action or "list"

        if plan_act == "create":
            if not args.plan_steps:
                raise ValueError("创建计划必须提供 --plan_steps（JSON 格式步骤列表）")
            steps = json.loads(args.plan_steps)
            plan = plan_manager.create_plan(steps, description=args.plan_desc or "")
            response["data"] = plan
            response["message"] = f"计划 [{plan['plan_id']}] 已创建，共 {len(steps)} 步"
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return

        elif plan_act == "list":
            plans = plan_manager.list_plans()
            response["data"] = plans
            response["message"] = f"共 {len(plans)} 个计划"
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return

        elif plan_act == "delete":
            if not args.plan_id:
                raise ValueError("删除计划必须提供 --plan_id")
            plan_manager.delete_plan(args.plan_id)
            response["message"] = f"计划 [{args.plan_id}] 已删除"
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return

        # execute / rollback 需要连接，继续往下

    # --- TTL: set / cancel / list（无需连接） ---
    if args.action == "ttl":
        ttl_act = args.ttl_action or "list"

        if ttl_act == "set":
            if not args.hostname:
                raise ValueError("设置 TTL 必须提供 --hostname")
            if not args.ttl_minutes:
                raise ValueError("设置 TTL 必须提供 --ttl_minutes")
            result = ttl_manager.set_ttl(args.hostname, args.ttl_minutes, args.creator or "agent")
            response["data"] = result
            response["message"] = f"已设置 [{args.hostname}] TTL: {args.ttl_minutes} 分钟"
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return

        elif ttl_act == "cancel":
            if not args.hostname:
                raise ValueError("取消 TTL 必须提供 --hostname")
            if ttl_manager.cancel_ttl(args.hostname):
                response["message"] = f"已取消 [{args.hostname}] 的 TTL"
            else:
                response["status"] = "fail"
                response["message"] = f"[{args.hostname}] 未设置 TTL"
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return

        elif ttl_act == "list":
            ttls = ttl_manager.list_ttls()
            response["data"] = ttls
            response["message"] = f"共 {len(ttls)} 个 TTL 记录"
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return

        # cleanup 需要连接，继续往下

    # --- Approval: create / approve / reject / list / cancel（无需连接） ---
    if args.action == "approval":
        appr_act = args.approval_action or "list"

        if appr_act == "create":
            if not args.hostname:
                raise ValueError("创建审批必须提供 --hostname（操作目标）")
            params = {}
            if args.approval_params:
                params = json.loads(args.approval_params)
            record = approval_manager.create_request(
                action=args.approval_target_action or "approval",
                target=args.hostname,
                params=params,
                requested_by=args.creator or "agent",
            )
            response["data"] = record
            response["message"] = f"审批请求 [{record['approval_id']}] 已创建，等待审批"

        elif appr_act == "approve":
            if not args.approval_id:
                raise ValueError("审批必须提供 --approval_id")
            record = approval_manager.approve(args.approval_id, comment=args.comment or "")
            response["data"] = record
            response["message"] = f"审批 [{args.approval_id}] 已通过"

        elif appr_act == "reject":
            if not args.approval_id:
                raise ValueError("拒绝必须提供 --approval_id")
            record = approval_manager.reject(args.approval_id, comment=args.comment or "")
            response["data"] = record
            response["message"] = f"审批 [{args.approval_id}] 已拒绝"

        elif appr_act == "cancel":
            if not args.approval_id:
                raise ValueError("取消必须提供 --approval_id")
            if approval_manager.cancel_request(args.approval_id):
                response["message"] = f"审批 [{args.approval_id}] 已取消"
            else:
                response["status"] = "fail"
                response["message"] = f"审批 [{args.approval_id}] 取消失败（可能已处理）"

        elif appr_act == "list":
            records = approval_manager.list_requests()
            response["data"] = records
            response["message"] = f"共 {len(records)} 条审批记录"

        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    # ========== 以下操作需要 vCenter 连接 ==========

    try:
        # 解析连接信息
        host, user, pwd, port = resolve_connection(args, cfg)

        with VCenterClient(host, user, pwd, port) as si:
            inventory = VCenterInventory(si)
            executor = VCenterExecutor(si)

            if args.action == "list_all":
                response["data"] = inventory.fetch_all_inventory()
                response["message"] = "全栈资产清单扫描完成"
                audit.record(args.action, "(全量)", "success")

            elif args.action == "get_vm":
                if not args.hostname:
                    raise ValueError("操作 'get_vm' 必须提供 --hostname")
                vm_data = inventory.get_single_vm_detail(args.hostname)
                if not vm_data:
                    response["status"] = "fail"
                    response["message"] = f"未找到该虚拟机: {args.hostname}"
                else:
                    response["data"] = vm_data
                    audit.record(args.action, args.hostname, "success")

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
                audit.record(args.action, args.hostname, "success", details={
                    "template": args.template, "cluster": args.cluster,
                    "ds": args.ds, "ip": args.ip
                })

            elif args.action == "power_vm":
                if not all([args.hostname, args.state]):
                    raise ValueError("电源管理需要 --hostname 和 --state")
                msg = executor.set_vm_power(args.hostname, args.state)
                response["message"] = msg
                audit.record(args.action, args.hostname, "success", details={"state": args.state})

            elif args.action == "delete_vm":
                if not args.hostname:
                    raise ValueError("🚫 安全策略拦截：删除操作必须通过 --hostname 指定精确的虚拟机名称，全量删除被禁止。")

                # 脚本级安全校验（双保险：handler 校验 + executor 校验）
                VCenterExecutor._validate_delete_target(args.hostname)

                msg = executor.remove_vm(args.hostname)
                response["message"] = msg
                audit.record(args.action, args.hostname, "success")

            elif args.action == "snapshot":
                if not args.hostname:
                    raise ValueError("快照操作必须提供 --hostname")
                snap_action = args.snap_action or "create"
                snap_name = args.snap_name or f"snap-{args.hostname}"

                if snap_action == "create":
                    msg = executor.create_snapshot(args.hostname, snap_name)
                    response["message"] = msg
                    audit.record(args.action, args.hostname, "success", details={"snap_action": snap_action, "snap_name": snap_name})
                elif snap_action == "list":
                    snaps = executor.list_snapshots(args.hostname)
                    response["data"] = snaps
                    response["message"] = f"共 {len(snaps)} 个快照"
                    audit.record(args.action, args.hostname, "success", details={"snap_action": snap_action})
                elif snap_action == "revert":
                    msg = executor.revert_snapshot(args.hostname, snap_name)
                    response["message"] = msg
                    audit.record(args.action, args.hostname, "success", details={"snap_action": snap_action, "snap_name": snap_name})
                elif snap_action == "delete":
                    msg = executor.remove_snapshot(args.hostname, snap_name)
                    response["message"] = msg
                    audit.record(args.action, args.hostname, "success", details={"snap_action": snap_action, "snap_name": snap_name})

            elif args.action == "reconfigure":
                if not args.hostname:
                    raise ValueError("reconfigure 操作必须提供 --hostname")
                if not any([args.cpu, args.memory, args.disk]):
                    raise ValueError("reconfigure 操作至少需要一个参数: --cpu / --memory / --disk")
                msg = executor.reconfigure_vm(
                    vm_name=args.hostname,
                    cpus=args.cpu,
                    memory_gb=args.memory,
                    disk_gb=args.disk,
                )
                response["message"] = msg
                audit.record(args.action, args.hostname, "success", details={
                    "cpus": args.cpu, "memory_gb": args.memory, "disk_gb": args.disk
                })

            elif args.action == "guest_exec":
                if not args.hostname:
                    raise ValueError("guest_exec 必须提供 --hostname")
                if not args.cmd:
                    raise ValueError("guest_exec 必须提供 --cmd")
                result = executor.guest_exec(
                    vm_name=args.hostname,
                    cmd=args.cmd,
                    username=args.guest_user or "root",
                    password=args.guest_pwd or "",
                )
                response["data"] = result
                if result.get("exit_code") == 0:
                    response["message"] = f"命令执行成功 (PID: {result.get('pid')})"
                else:
                    response["status"] = "warning"
                    response["message"] = f"命令退出码: {result.get('exit_code')}"
                audit.record(args.action, args.hostname, "success" if result.get("exit_code") == 0 else "warning",
                             details={"cmd": args.cmd, "exit_code": result.get("exit_code")})

            elif args.action == "migrate":
                if not args.hostname:
                    raise ValueError("migrate 必须提供 --hostname")
                if not args.target_host:
                    raise ValueError("migrate 必须提供 --target_host")
                msg = executor.migrate_vm(vm_name=args.hostname, target_host=args.target_host)
                response["message"] = msg
                audit.record(args.action, args.hostname, "success", details={"target_host": args.target_host})

            elif args.action == "plan":
                plan_act = args.plan_action or "list"

                if plan_act == "execute":
                    if not args.plan_id:
                        raise ValueError("执行计划必须提供 --plan_id")
                    plan = plan_manager.execute_plan(args.plan_id, executor)
                    response["data"] = plan
                    response["message"] = f"计划 [{args.plan_id}] 执行完成: {plan['status']}"
                    audit.record(args.action, f"plan:{args.plan_id}", "success" if plan["status"] == "completed" else "failed")

                elif plan_act == "rollback":
                    if not args.plan_id:
                        raise ValueError("回滚计划必须提供 --plan_id")
                    plan = plan_manager.rollback_plan(args.plan_id, executor)
                    response["data"] = plan
                    response["message"] = f"计划 [{args.plan_id}] 回滚完成: {plan['status']}"
                    audit.record(args.action, f"plan:{args.plan_id}", "success")

            elif args.action == "ttl":
                ttl_act = args.ttl_action or "list"

                if ttl_act == "cleanup":
                    results = ttl_manager.cleanup_expired(executor)
                    response["data"] = results
                    response["message"] = f"清理完成: {len(results)} 个过期 VM"
                    audit.record(args.action, "(ttl-cleanup)", "success", details={"count": len(results)})

            elif args.action == "datastore":
                if args.ds_scan:
                    # 扫描所有数据存储镜像
                    images = executor.scan_datastore_images(top_n=args.top or 50)
                    response["data"] = images
                    response["message"] = f"共发现 {len(images)} 个镜像文件"
                else:
                    # 浏览指定数据存储
                    if not args.ds_name:
                        raise ValueError("浏览数据存储必须提供 --ds_name 或 --ds_scan")
                    files = executor.browse_datastore(args.ds_name, path=args.ds_path or "")
                    response["data"] = files
                    response["message"] = f"[{args.ds_name}] {args.ds_path or '/'} 下共 {len(files)} 项"
                audit.record(args.action, args.ds_name or "(scan)", "success")

            elif args.action == "template":
                tpl_act = args.tpl_action or "list"

                if tpl_act == "list":
                    templates = executor.list_templates()
                    response["data"] = templates
                    response["message"] = f"共 {len(templates)} 个模板"
                    audit.record(args.action, "(全部)", "success")

                elif tpl_act == "register":
                    if not args.hostname:
                        raise ValueError("注册模板必须提供 --hostname")
                    msg = executor.register_template(args.hostname, template_name=args.tpl_name or "")
                    response["message"] = msg
                    audit.record(args.action, args.hostname, "success", details={"tpl_action": "register", "tpl_name": args.tpl_name or ""})

                elif tpl_act == "convert":
                    if not args.hostname:
                        raise ValueError("转换模板必须提供 --hostname")
                    msg = executor.convert_to_vm(args.hostname)
                    response["message"] = msg
                    audit.record(args.action, args.hostname, "success", details={"tpl_action": "convert"})

            elif args.action == "batch":
                batch_act = args.batch_action
                if not batch_act:
                    raise ValueError("batch 操作必须提供 --batch_action")

                if batch_act == "power":
                    if not args.pattern:
                        raise ValueError("批量操作必须提供 --pattern（VM 名称匹配模式）")
                    if not args.state:
                        raise ValueError("批量电源操作必须提供 --state")

                    result = executor.batch_power(args.pattern, args.state)
                    response["data"] = result
                    response["message"] = f"批量 {args.state}: {result['success']}/{result['total']} 成功, {result['failed']} 失败"
                    audit.record(args.action, f"pattern:{args.pattern}", "success" if result['failed'] == 0 else "warning",
                                 details={"batch_action": "power", "pattern": args.pattern, "state": args.state,
                                          "success": result['success'], "failed": result['failed']})

            elif args.action == "events":
                events = executor.get_events(
                    minutes=args.minutes or 60,
                    category=args.event_category or "",
                    max_events=args.top or 50,
                )
                response["data"] = events
                response["message"] = f"最近 {args.minutes or 60} 分钟共 {len(events)} 个事件"
                audit.record(args.action, "(events)", "success", details={"minutes": args.minutes or 60, "category": args.event_category or ""})

            elif args.action == "quota":
                result = executor.check_resource_quota(
                    cluster_name=args.cluster or "",
                    ds_name=args.ds or "",
                    cpu_threshold=float(args.cpu_threshold) if args.cpu_threshold else 0.85,
                    mem_threshold=float(args.mem_threshold) if args.mem_threshold else 0.85,
                    disk_threshold=float(args.disk_threshold) if args.disk_threshold else 0.9,
                )
                response["data"] = result
                if result["warnings"]:
                    response["status"] = "warning"
                    response["message"] = f"发现 {len(result['warnings'])} 个告警"
                else:
                    response["message"] = "资源使用正常，无告警"
                audit.record(args.action, args.cluster or "(全部)", "success" if not result["warnings"] else "warning",
                             details={"warnings_count": len(result['warnings'])})

            elif args.action == "export":
                vms = executor.export_vm_inventory(cluster_name=args.cluster or "", max_vms=args.top or 0)
                fmt = args.export_format or "json"

                if fmt == "json":
                    response["data"] = vms
                    response["message"] = f"共 {len(vms)} 台虚拟机"

                elif fmt == "csv":
                    import csv as csv_mod
                    import io
                    if not vms:
                        response["data"] = ""
                        response["message"] = "无数据"
                    else:
                        output = io.StringIO()
                        writer = csv_mod.DictWriter(output, fieldnames=vms[0].keys())
                        writer.writeheader()
                        writer.writerows(vms)
                        csv_content = output.getvalue()

                        if args.output:
                            with open(args.output, "w", encoding="utf-8") as f:
                                f.write(csv_content)
                            response["message"] = f"已导出 {len(vms)} 台 VM 到 {args.output}"
                        else:
                            response["data"] = csv_content
                            response["message"] = f"共 {len(vms)} 台虚拟机"

                elif fmt == "markdown":
                    if not vms:
                        response["data"] = "无数据"
                        response["message"] = "无数据"
                    else:
                        headers = list(vms[0].keys())
                        md = "| " + " | ".join(headers) + " |\n"
                        md += "| " + " | ".join(["---"] * len(headers)) + " |\n"
                        for vm_entry in vms:
                            md += "| " + " | ".join(str(vm_entry.get(h, "")) for h in headers) + " |\n"

                        if args.output:
                            with open(args.output, "w", encoding="utf-8") as f:
                                f.write(md)
                            response["message"] = f"已导出 {len(vms)} 台 VM 到 {args.output}"
                        else:
                            response["data"] = md
                            response["message"] = f"共 {len(vms)} 台虚拟机"

                audit.record(args.action, args.cluster or "(全部)", "success", details={"format": fmt, "count": len(vms)})

    except Exception as e:
        logger.error(f"Handler 执行故障: {str(e)}", exc_info=True)
        response["status"] = "error"
        response["message"] = f"执行异常: {str(e)}"
        target = getattr(args, 'hostname', None) or "(未知)"
        audit.record(args.action, target, "failed", error=str(e))

    print(json.dumps(response, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
