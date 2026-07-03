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
from scripts.history_manager import last_clone_params, list_history, format_history_summary, format_clone_params
from scripts.preset_manager import (
    apply_preset, list_presets, format_preset_list, parse_preset_from_text,
    save_preset, save_from_history, delete_preset, get_preset,
)
from scripts.progress_reporter import ProgressReporter, stdout_sink
from scripts.error_dictionary import format_error_oneline
from scripts import ip_pool
from scripts import batch_clone as batch_clone_mod
from scripts import webhook_subscriber
# v1.3 安全合规
from scripts import secret_manager
from scripts import role_manager
from scripts import danger_validator
from scripts import approval_policy
from scripts import change_window
# v1.4 智能化
from scripts import metrics_collector
from scripts import recommender
from scripts import anomaly_detector
from scripts import capacity_forecaster
# v1.5 标准交付 / 克隆后初始化
from scripts import delivery_pipeline
from scripts import post_clone_init

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
                            "history", "preset",
                            "batch_clone", "ip_pool", "webhook", "audit_report",
                            "secret", "rbac", "danger", "approval_policy", "change_window",
                            "metrics", "recommend", "anomaly", "forecast", "delivery", "post_init",
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
    parser.add_argument("--export_format", choices=["json", "csv", "markdown", "html"],
                        help="导出格式（默认 json）")
    parser.add_argument("--output", help="输出文件路径")

    # --- 通用分页/限制 ---
    parser.add_argument("--top", type=int, default=50, help="返回结果数量限制")

    # --- v1.0 预设 / 历史复用 ---
    parser.add_argument("--preset", help="使用预设包（如 @dev-small / dev-small），参数会被同名 CLI 参数覆盖")
    parser.add_argument("--from-last", action="store_true", dest="from_last",
                        help="克隆时复用最近一次克隆参数（仅覆盖未指定的项）")
    parser.add_argument("--from-vm", dest="from_vm",
                        help="克隆时复用与指定 VM 同名的历史克隆参数")
    parser.add_argument("--no-wait-tools", action="store_true", dest="no_wait_tools",
                        help="克隆后不等待 VMware Tools 就绪")
    parser.add_argument("--tools-timeout", type=int, dest="tools_timeout", default=300,
                        help="等待 Tools 就绪超时（默认 300s）")

    # --- v1.1 批量克隆 / IP 池 / Webhook / 审计报表 ---
    parser.add_argument("--count", type=int, help="批量克隆数量")
    parser.add_argument("--name-prefix", dest="name_prefix", default="vm-", help="批量克隆 VM 名前缀")
    parser.add_argument("--name-start", type=int, dest="name_start", default=1, help="批量克隆编号起始")
    parser.add_argument("--ip-pool", dest="ip_pool_spec", help="IP 池声明（CIDR/范围/单IP，逗号隔）")
    parser.add_argument("--workers", type=int, default=3, help="批量并行度")

    parser.add_argument("--preset-action", dest="preset_action",
                        choices=["list", "save", "save-from-last", "delete", "show"],
                        help="预设子操作")
    parser.add_argument("--preset-name", dest="preset_name", help="预设名")
    parser.add_argument("--preset-desc", dest="preset_desc", default="")
    parser.add_argument("--preset-overwrite", action="store_true", dest="preset_overwrite")

    parser.add_argument("--ip-action", dest="ip_action",
                        choices=["available", "allocate", "release", "reservations", "cleanup"])
    parser.add_argument("--ip-spec", dest="ip_spec", help="IP 池声明")
    parser.add_argument("--ip-target", dest="ip_target", help="要释放的 IP")

    parser.add_argument("--webhook-action", dest="webhook_action",
                        choices=["list", "add", "remove", "toggle"])
    parser.add_argument("--webhook-name", dest="webhook_name")
    parser.add_argument("--webhook-url", dest="webhook_url")
    parser.add_argument("--webhook-secret", dest="webhook_secret", default="")
    parser.add_argument("--webhook-topics", nargs="+", dest="webhook_topics", default=["*"])
    parser.add_argument("--webhook-mode", dest="webhook_mode", choices=["http", "dingtalk"], default="http")
    parser.add_argument("--webhook-id", dest="webhook_id")
    parser.add_argument("--webhook-enable", action="store_true")
    parser.add_argument("--webhook-disable", action="store_true")

    parser.add_argument("--report-days", type=int, dest="report_days", default=7,
                        help="审计报表覆盖天数")

    # --- v1.3 安全合规 ---
    parser.add_argument("--actor", default="agent", dest="acting_user",
                        help="当前操作人（用于 RBAC/审批/危险确认）")
    parser.add_argument("--confirmed", action="store_true",
                        help="危险操作二次确认标记")

    parser.add_argument("--secret-action", dest="secret_action",
                        choices=["list", "set", "get", "delete", "migrate", "rotate"])
    parser.add_argument("--secret-key", dest="secret_key")
    parser.add_argument("--secret-value", dest="secret_value")
    parser.add_argument("--secret-desc", dest="secret_desc", default="")

    parser.add_argument("--rbac-action", dest="rbac_action",
                        choices=["roles", "users", "bind", "unbind", "check", "config"])
    parser.add_argument("--rbac-user", dest="rbac_user")
    parser.add_argument("--rbac-role", dest="rbac_role")
    parser.add_argument("--rbac-target-action", dest="rbac_target_action")

    parser.add_argument("--danger-action", dest="danger_action",
                        choices=["scan", "confirm", "patterns", "config"])
    parser.add_argument("--danger-target", dest="danger_target")
    parser.add_argument("--danger-op", dest="danger_op", default="delete_vm")

    parser.add_argument("--policy-action", dest="policy_action",
                        choices=["list", "route", "config"])
    parser.add_argument("--policy-target-action", dest="policy_target_action")
    parser.add_argument("--policy-target", dest="policy_target", default="")

    parser.add_argument("--window-action", dest="window_action",
                        choices=["status", "check", "config"])
    parser.add_argument("--window-op", dest="window_op")

    # --- v1.4 智能化 ---
    parser.add_argument("--metrics-action", dest="metrics_action",
                        choices=["collect", "query", "cleanup"])
    parser.add_argument("--metric-type", dest="metric_type")
    parser.add_argument("--metric-target", dest="metric_target")
    parser.add_argument("--metric-days", type=int, dest="metric_days", default=7)
    parser.add_argument("--metrics-keep-days", type=int, dest="metrics_keep_days", default=30)
    parser.add_argument("--metrics-dry-run", action="store_true", dest="metrics_dry_run")

    parser.add_argument("--recommend-top", type=int, dest="recommend_top", default=3)
    parser.add_argument("--recommend-count", type=int, dest="recommend_count", default=1)
    parser.add_argument("--recommend-prefix", dest="recommend_prefix", default="")

    parser.add_argument("--forecast-threshold", type=float, dest="forecast_threshold",
                        default=0.9)

    # --- v1.5 标准交付 / 克隆后初始化 ---
    parser.add_argument("--delivery-action", dest="delivery_action",
                        choices=["plan", "execute", "verify"], help="标准交付子操作")
    parser.add_argument("--delivery-confirm", action="store_true", dest="delivery_confirm",
                        help="确认执行 delivery execute")
    parser.add_argument("--skip-clone", action="store_true", dest="skip_clone",
                        help="delivery execute 时跳过真实 clone，仅验证资产/监控流程")
    parser.add_argument("--name", dest="delivery_name", help="交付名称/自定义 VM 名")
    parser.add_argument("--owner", dest="owner", help="负责人")
    parser.add_argument("--env", dest="env", default="dev", help="环境 dev/test/prod")
    parser.add_argument("--app", dest="app", default="app", help="应用名")
    parser.add_argument("--gateway", dest="gateway", help="网关，delivery 使用")
    parser.add_argument("--datastore", dest="datastore", help="datastore，delivery 别名")
    parser.add_argument("--expected-hostname", dest="expected_hostname", help="post_init 期望主机名")
    parser.add_argument("--ssh-check", action="store_true", dest="ssh_check", help="post_init 检查 SSH 端口")
    parser.add_argument("--ssh-port", type=int, dest="ssh_port", default=22, help="post_init SSH 端口")
    parser.add_argument("--init-timeout", type=int, dest="init_timeout", default=3, help="post_init 检查超时")

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

    # 密码：v1.3 优先从 secret_manager（加密存储）取 → 命令行 → config.yaml 明文 → .env 环境变量 → password_ref 引用
    pwd = args.pwd or vc.get("password", "")
    if not pwd:
        # 尝试从 .env 文件加载
        env_file = SKILL_DIR / ".env"
        if env_file.exists():
            from dotenv import load_dotenv
            load_dotenv(env_file)
        ref = vc.get("password_ref", "")
        if ref:
            # 优先加密存储
            try:
                enc_val = secret_manager.resolve_password(ref)
                if enc_val:
                    pwd = enc_val
                    logger.debug(f"密码从 secret_manager 加载 ({ref})")
            except Exception as _e:
                logger.debug(f"secret_manager 读取失败，回退环境变量: {_e}")
            if not pwd:
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
    # 不应需 vCenter 的查询类 action 可跳过 dry-run
    _DRY_SKIP = {"history", "preset", "secret", "rbac", "danger", "approval_policy",
                  "change_window", "metrics", "anomaly", "forecast",
                  "ip_pool", "webhook", "audit_report"}
    if args.dry_run and args.action not in _DRY_SKIP:
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

    # --- v1.5 Delivery / Post-init（通过独立脚本编排，默认安全） ---
    if args.action == "delivery":
        d_action = args.delivery_action or "plan"
        d_name = args.delivery_name or args.hostname
        ds_value = args.datastore or args.ds
        gw_value = args.gateway or args.gw
        missing = []
        for key, val in {
            "--name/--hostname": d_name,
            "--ip": args.ip,
            "--owner": args.owner,
            "--template": args.template,
            "--dc": args.dc,
            "--cluster": args.cluster,
            "--datastore/--ds": ds_value,
            "--network": args.network,
            "--gateway/--gw": gw_value,
        }.items():
            if not val:
                missing.append(key)
        if missing:
            raise ValueError("delivery 缺少参数: " + ", ".join(missing))
        dp_args = argparse.Namespace(
            action=d_action,
            confirm=args.delivery_confirm,
            skip_clone=args.skip_clone,
            name=d_name,
            vm_name=args.hostname if args.hostname and args.hostname.startswith(str(args.ip)) else None,
            ip=args.ip,
            owner=args.owner,
            env=args.env or "dev",
            app=args.app or "app",
            preset=args.preset or "dev-small",
            template=args.template,
            dc=args.dc,
            cluster=args.cluster,
            datastore=ds_value,
            network=args.network,
            gateway=gw_value,
            mask=args.mask or "255.255.255.0",
            cpu=str(args.cpu or 2),
            memory=str(args.memory or 4),
            disk=str(args.disk or 40),
        )
        if d_action == "plan":
            result = delivery_pipeline.do_plan(dp_args)
        elif d_action == "execute":
            result = delivery_pipeline.do_execute(dp_args)
        else:
            result = delivery_pipeline.do_verify(dp_args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if args.action == "post_init":
        vm = args.hostname or (f"{args.ip}-{args.delivery_name}" if args.ip and args.delivery_name else None)
        if not vm or not args.ip:
            raise ValueError("post_init 必须提供 --hostname 或 --name，并提供 --ip")
        pi_args = argparse.Namespace(
            vm_name=vm,
            ip=args.ip,
            expected_hostname=args.expected_hostname,
            ssh_check=args.ssh_check,
            ssh_user=args.guest_user or "root",
            ssh_port=args.ssh_port or 22,
            timeout=args.init_timeout or 3,
        )
        result = post_clone_init.run(pi_args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

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

    # --- v1.0 预设 / 历史 查询（无需连接 vCenter） ---
    if args.action == "preset":
        presets = list_presets()
        response["data"] = presets
        response["message"] = format_preset_list(presets)
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    if args.action == "history":
        # 查询：--from-vm 看该 VM 最近一次 / 否则最近克隆列表
        if args.from_vm or args.from_last:
            info = last_clone_params(args.from_vm)
            response["data"] = info
            response["message"] = format_clone_params(info or {})
        else:
            recs = list_history(limit=args.top or 10)
            response["data"] = recs
            response["message"] = format_history_summary(recs)
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    # ============ v1.1 离线 action：预设 CRUD / IP 池 / Webhook / 审计报表 ============

    if args.action == "preset" and args.preset_action and args.preset_action != "list":
        # 预设写操作
        if args.preset_action == "save":
            if not args.preset_name:
                raise ValueError("--preset-action save 需 --preset-name")
            params = {}
            for k_cli, k_dst in [("template","template_name"),("dc","dc_name"),
                                  ("cluster","cluster_name"),("ds","ds_name"),
                                  ("network","network_name"),("host_node","host_name"),
                                  ("cpu","cpus"),("memory","memory_gb"),
                                  ("disk","disk_gb"),("gw","gateway")]:
                v = getattr(args, k_cli, None)
                if v is not None:
                    params[k_dst] = v
            data = save_preset(args.preset_name, params,
                               description=args.preset_desc,
                               overwrite=args.preset_overwrite)
            response["data"] = data
            response["message"] = f"✅ 预设 [{args.preset_name}] 已保存"
        elif args.preset_action == "save-from-last":
            if not args.preset_name:
                raise ValueError("--preset-action save-from-last 需 --preset-name")
            info = last_clone_params(args.from_vm)
            if not info:
                raise ValueError("未找到可使用的历史记录")
            data = save_from_history(args.preset_name, info,
                                     description=args.preset_desc,
                                     overwrite=args.preset_overwrite)
            response["data"] = data
            response["message"] = f"✅ 预设 [{args.preset_name}] 已从历史保存"
        elif args.preset_action == "delete":
            if not args.preset_name:
                raise ValueError("--preset-action delete 需 --preset-name")
            ok = delete_preset(args.preset_name)
            response["message"] = f"{'✅ 已删除' if ok else '⚠️ 未找到'}: {args.preset_name}"
        elif args.preset_action == "show":
            if not args.preset_name:
                raise ValueError("--preset-action show 需 --preset-name")
            response["data"] = get_preset(args.preset_name)
            response["message"] = f"预设 [{args.preset_name}]" if response["data"] else "未找到预设"
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    if args.action == "ip_pool":
        ipa = args.ip_action or "reservations"
        if ipa == "available":
            if not args.ip_spec: raise ValueError("--ip-action available 需 --ip-spec")
            pool = ip_pool.IPPool(args.ip_spec, skip_alive=True)
            ips = pool.available(limit=args.top or 20)
            response["data"] = ips
            response["message"] = f"可用 IP {len(ips)} 个"
        elif ipa == "allocate":
            if not args.ip_spec: raise ValueError("--ip-action allocate 需 --ip-spec")
            pool = ip_pool.IPPool(args.ip_spec, skip_alive=True)
            recs = pool.allocate(args.count or 1, vm_name_prefix=args.name_prefix or "vm-")
            response["data"] = recs
            response["message"] = f"已分配 {len(recs)} 个 IP"
        elif ipa == "release":
            if not args.ip_target: raise ValueError("--ip-action release 需 --ip-target")
            ok = ip_pool.release_ip(args.ip_target)
            response["message"] = f"{'✅ 已释放' if ok else '⚠️ 未找到'}: {args.ip_target}"
        elif ipa == "reservations":
            recs = ip_pool.list_reservations()
            response["data"] = recs
            response["message"] = f"共 {len(recs)} 条预留"
        elif ipa == "cleanup":
            n = ip_pool.cleanup_expired()
            response["message"] = f"清理过期预留 {n} 个"
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    if args.action == "webhook":
        wa = args.webhook_action or "list"
        if wa == "list":
            whs = webhook_subscriber.list_webhooks()
            response["data"] = whs
            response["message"] = webhook_subscriber.format_webhook_list(whs)
        elif wa == "add":
            if not (args.webhook_name and args.webhook_url):
                raise ValueError("--webhook-action add 需 --webhook-name 和 --webhook-url")
            wh = webhook_subscriber.add_webhook(
                args.webhook_name, args.webhook_url,
                secret=args.webhook_secret, topics=args.webhook_topics,
                mode=args.webhook_mode,
            )
            response["data"] = wh
            response["message"] = f"✅ Webhook [{args.webhook_name}] 已添加"
        elif wa == "remove":
            if not args.webhook_id: raise ValueError("--webhook-action remove 需 --webhook-id")
            ok = webhook_subscriber.remove_webhook(args.webhook_id)
            response["message"] = f"{'✅ 已删除' if ok else '⚠️ 未找到'}: {args.webhook_id}"
        elif wa == "toggle":
            if not args.webhook_id: raise ValueError("--webhook-action toggle 需 --webhook-id")
            enabled = bool(args.webhook_enable) and not args.webhook_disable
            ok = webhook_subscriber.toggle_webhook(args.webhook_id, enabled)
            response["message"] = f"{'✅ 已' + ('启用' if enabled else '禁用') if ok else '⚠️ 未找到'}: {args.webhook_id}"
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    if args.action == "audit_report":
        summary = audit.summarize(since_days=args.report_days or 7)
        fmt = args.export_format or "html"
        text = audit.export_report(
            since_days=args.report_days or 7,
            fmt=fmt,
            output=args.output,
        )
        response["data"] = summary
        response["message"] = (
            f"报表已导出到 {args.output}" if args.output
            else (text[:500] + "\u2026" if fmt == "html" and len(text) > 500 else text)
        )
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    # ============ v1.3 安全合规离线 action ============

    if args.action == "secret":
        sa = args.secret_action or "list"
        if sa == "list":
            response["data"] = secret_manager.list_secret_keys()
            response["message"] = f"共 {len(response['data'])} 个加密存储项"
        elif sa == "set":
            if not args.secret_key or not args.secret_value:
                raise ValueError("--secret-action set 需 --secret-key 和 --secret-value")
            secret_manager.set_secret(args.secret_key, args.secret_value, description=args.secret_desc)
            response["message"] = f"✅ 已加密存储: {args.secret_key}"
        elif sa == "get":
            if not args.secret_key: raise ValueError("--secret-action get 需 --secret-key")
            v = secret_manager.get_secret(args.secret_key)
            response["data"] = {"key": args.secret_key, "found": v is not None,
                                "value": v if v else None}
            response["message"] = "⚠️ 明文返回请谨慎使用" if v else "未找到"
        elif sa == "delete":
            if not args.secret_key: raise ValueError("--secret-action delete 需 --secret-key")
            ok = secret_manager.delete_secret(args.secret_key)
            response["message"] = f"{'✅ 已删除' if ok else '⚠️ 未找到'}: {args.secret_key}"
        elif sa == "migrate":
            result = secret_manager.migrate_from_env(dry_run=args.dry_run)
            response["data"] = result
            response["message"] = result.get("message", "")
        elif sa == "rotate":
            result = secret_manager.rotate_key()
            response["data"] = result
            response["message"] = result.get("message", "")
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    if args.action == "rbac":
        ra = args.rbac_action or "roles"
        if ra == "roles":
            response["data"] = role_manager.list_roles()
            response["message"] = role_manager.format_roles_table()
        elif ra == "users":
            response["data"] = role_manager.list_users()
            response["message"] = role_manager.format_users_table()
        elif ra == "bind":
            if not args.rbac_user or not args.rbac_role:
                raise ValueError("--rbac-action bind 需 --rbac-user 和 --rbac-role")
            d = role_manager.bind_user(args.rbac_user, args.rbac_role)
            response["data"] = d
            response["message"] = f"✅ {args.rbac_user} → {args.rbac_role}"
        elif ra == "unbind":
            if not args.rbac_user: raise ValueError("--rbac-action unbind 需 --rbac-user")
            ok = role_manager.unbind_user(args.rbac_user)
            response["message"] = f"{'✅ 已解绑' if ok else '⚠️ 未找到'}: {args.rbac_user}"
        elif ra == "check":
            if not args.rbac_user or not args.rbac_target_action:
                raise ValueError("--rbac-action check 需 --rbac-user 和 --rbac-target-action")
            try:
                role_manager.check_permission(args.rbac_user, args.rbac_target_action)
                role = role_manager.get_user_role(args.rbac_user)
                response["message"] = f"✅ 通过：{args.rbac_user} (role={role}) 可执行 {args.rbac_target_action}"
            except role_manager.PermissionDenied as e:
                response["status"] = "denied"
                response["message"] = str(e)
        elif ra == "config":
            response["data"] = role_manager.load_rbac_config()
            response["message"] = "当前 RBAC 配置"
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    if args.action == "danger":
        da = args.danger_action or "scan"
        if da == "scan":
            if not args.danger_target: raise ValueError("--danger-action scan 需 --danger-target")
            matched = danger_validator.scan_danger(args.danger_target, args.danger_op)
            response["data"] = matched
            if not matched:
                response["message"] = f"✅ [{args.danger_target}] 未命中危险词"
            else:
                response["status"] = "warning"
                response["message"] = (
                    f"⚠️ [{args.danger_target}] 命中 {len(matched)} 个危险词: "
                    + ", ".join(m["pattern"] for m in matched)
                )
        elif da == "confirm":
            if not args.danger_target: raise ValueError("--danger-action confirm 需 --danger-target")
            danger_validator.confirm_danger(args.danger_target, args.danger_op, user=args.acting_user)
            response["message"] = f"✅ 已确认危险操作: {args.danger_op} → {args.danger_target}"
        elif da == "patterns":
            response["data"] = danger_validator.load_danger_config().get("patterns", [])
            response["message"] = f"共 {len(response['data'])} 个危险词模式"
        elif da == "config":
            response["data"] = danger_validator.load_danger_config()
            response["message"] = "当前危险词配置"
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    if args.action == "approval_policy":
        pa = args.policy_action or "list"
        if pa == "list":
            response["data"] = approval_policy.load_policies().get("policies", [])
            response["message"] = approval_policy.format_policies_table()
        elif pa == "route":
            if not args.policy_target_action:
                raise ValueError("--policy-action route 需 --policy-target-action")
            result = approval_policy.route_approval(args.policy_target_action, args.policy_target)
            response["data"] = result
            response["message"] = json.dumps(result, ensure_ascii=False)
        elif pa == "config":
            response["data"] = approval_policy.load_policies()
            response["message"] = "当前审批策略配置"
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    if args.action == "change_window":
        wa = args.window_action or "status"
        if wa == "status":
            response["data"] = change_window.load_window_config()
            response["message"] = change_window.format_status()
        elif wa == "check":
            if not args.window_op: raise ValueError("--window-action check 需 --window-op")
            allowed, reason, nxt = change_window.is_change_allowed(
                args.window_op, target=args.hostname or "", user=args.acting_user
            )
            response["data"] = {"allowed": allowed, "reason": reason, "next_allowed": nxt}
            response["message"] = f"{'✅' if allowed else '⛔'} {reason}"
        elif wa == "config":
            response["data"] = change_window.load_window_config()
            response["message"] = "当前变更窗口配置"
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    # ============ v1.4 智能化 离线 action（metrics query / anomaly / forecast）============

    if args.action == "metrics" and (args.metrics_action or "query") != "collect":
        ma = args.metrics_action or "query"
        if ma == "query":
            recs = metrics_collector.query_history(
                metric_type=args.metric_type,
                target=args.metric_target,
                since_days=args.metric_days or 7,
            )
            response["data"] = recs
            response["message"] = f"查询到 {len(recs)} 条指标"
        elif ma == "cleanup":
            n = metrics_collector.cleanup_old(keep_days=args.metrics_keep_days or 30)
            response["message"] = f"清理 {n} 个过期文件"
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    if args.action == "anomaly":
        anomalies = anomaly_detector.detect_all(
            since_days=args.metric_days or 7,
            publish_events=True,
        )
        response["data"] = anomalies
        response["message"] = anomaly_detector.format_anomalies(anomalies)
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    if args.action == "forecast":
        results = capacity_forecaster.forecast_all(
            since_days=args.metric_days or 30,
            publish_events=True,
            config={
                "threshold": args.forecast_threshold or 0.9,
                "min_samples": 10,
                "warning_days": 30,
                "critical_days": 7,
            },
        )
        response["data"] = results
        response["message"] = capacity_forecaster.format_forecasts(results)
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    # ========== 以下操作需要 vCenter 连接 ==========

    try:
        # 解析连接信息
        host, user, pwd, port = resolve_connection(args, cfg)

        # ============ v1.3 四重安全门（RBAC → 变更窗口 → 危险词 → 审批策略）============
        try:
            role_manager.check_permission(args.acting_user or "agent", args.action)
        except role_manager.PermissionDenied as _e:
            response["status"] = "denied"
            response["message"] = str(_e)
            audit.record(args.action, args.hostname or "", "rejected",
                         operator=args.acting_user or "agent", error=str(_e))
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return

        try:
            change_window.validate_change_window(
                args.action, target=args.hostname or "", user=args.acting_user or "agent"
            )
        except change_window.ChangeWindowBlocked as _e:
            response["status"] = "blocked"
            response["message"] = str(_e)
            audit.record(args.action, args.hostname or "", "rejected",
                         operator=args.acting_user or "agent", error=str(_e))
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return

        if args.hostname:
            try:
                if args.confirmed:
                    danger_validator.confirm_danger(args.hostname, args.action,
                                                    user=args.acting_user or "agent")
                danger_validator.validate_danger(
                    args.hostname, args.action, user=args.acting_user or "agent"
                )
            except danger_validator.DangerConfirmRequired as _e:
                response["status"] = "confirm_required"
                response["message"] = (
                    str(_e) + " 请重新执行并传 --confirmed 确认"
                )
                audit.record(args.action, args.hostname, "awaiting_confirm",
                             operator=args.acting_user or "agent",
                             details={"matched": _e.matched})
                print(json.dumps(response, ensure_ascii=False, indent=2))
                return

        try:
            approval_policy.validate_approval(args.action, target=args.hostname or "")
        except approval_policy.ApprovalRequired as _e:
            response["status"] = "approval_required"
            response["message"] = str(_e)
            audit.record(args.action, args.hostname or "", "awaiting_approval",
                         operator=args.acting_user or "agent",
                         details={"level": _e.level, "approvers": _e.approvers})
            print(json.dumps(response, ensure_ascii=False, indent=2))
            return

        # 启动时挂载 Webhook 订阅到事件总线（幂等，只启动一次）
        try:
            webhook_subscriber.register_all_to_bus()
        except Exception as _wh_e:
            logger.debug(f"webhook 挂载跳过: {_wh_e}")

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
                # v1.0: 支持 --preset / --from-last / --from-vm 参数合并
                # 合并优先级（高 → 低）：CLI 参数 > history > preset > config.defaults
                merged: Dict[str, Any] = {}

                # 1) preset
                if args.preset:
                    try:
                        ps = apply_preset(args.preset, user_params=None)
                        # 换算为源字段名
                        for k_src, k_dst in {
                            "template_name": "template", "new_name": "hostname",
                            "dc_name": "dc", "cluster_name": "cluster",
                            "ds_name": "ds", "network_name": "network",
                            "host_name": "host_node", "cpus": "cpu",
                            "memory_gb": "memory", "disk_gb": "disk",
                            "ip_address": "ip", "subnet": "mask", "gateway": "gw",
                        }.items():
                            if k_src in ps and ps[k_src] is not None:
                                merged[k_dst] = ps[k_src]
                        merged["_preset"] = ps.get("_preset")
                        merged["_preset_desc"] = ps.get("_preset_desc", "")
                    except ValueError as ve:
                        raise ValueError(f"预设加载失败: {ve}")

                # 2) history (优先级高于 preset)
                if args.from_last or args.from_vm:
                    info = last_clone_params(args.from_vm)
                    if not info:
                        raise ValueError(
                            f"未找到可复用的历史克隆记录 "
                            f"(--from-vm={args.from_vm or '(无)'})"
                        )
                    for k_src, k_dst in {
                        "template_name": "template", "dc_name": "dc",
                        "cluster_name": "cluster", "ds_name": "ds",
                        "network_name": "network", "host_name": "host_node",
                        "cpus": "cpu", "memory_gb": "memory", "disk_gb": "disk",
                        "subnet": "mask", "gateway": "gw",
                    }.items():
                        v = (info.get("params") or {}).get(k_src)
                        if v is not None:
                            merged[k_dst] = v
                    merged["_history_source"] = info.get("source_task_id")

                # 3) CLI 显式参数 最高优先级
                cli_overrides = {
                    "template": args.template, "hostname": args.hostname,
                    "dc": args.dc, "cluster": args.cluster, "ds": args.ds,
                    "network": args.network, "host_node": args.host_node,
                    "cpu": args.cpu, "memory": args.memory, "disk": args.disk,
                    "ip": args.ip, "mask": args.mask, "gw": args.gw,
                }
                for k, v in cli_overrides.items():
                    if v is not None:
                        merged[k] = v

                required = [merged.get("template"), merged.get("hostname"), merged.get("dc"),
                            merged.get("cluster"), merged.get("ds"), merged.get("network")]
                if not all(required):
                    missing = [n for n,v in zip(
                        ["template","hostname","dc","cluster","ds","network"], required) if not v]
                    raise ValueError(
                        f"克隆缺少必填参数: {','.join(missing)} "
                        f"(可通过 --preset / --from-last / --from-vm 补齐)"
                    )

                # 进度接口：默认 stdout
                rpt = ProgressReporter(
                    op_name=f"克隆 {merged['hostname']}",
                    sinks=[stdout_sink],
                )

                msg = executor.clone_vm_advanced(
                    template_name=merged["template"],
                    new_name=merged["hostname"],
                    dc_name=merged["dc"],
                    cluster_name=merged["cluster"],
                    ds_name=merged["ds"],
                    network_name=merged["network"],
                    host_name=merged.get("host_node"),
                    cpus=merged.get("cpu"),
                    memory_gb=merged.get("memory"),
                    disk_gb=merged.get("disk"),
                    ip_address=merged.get("ip"),
                    subnet=merged.get("mask") or "255.255.255.0",
                    gateway=merged.get("gw"),
                    wait_tools=not args.no_wait_tools,
                    tools_timeout=args.tools_timeout or 300,
                    on_progress=rpt.on_update,
                )
                rpt.on_done({"state": "success", "progress": 100})
                response["message"] = msg
                response["data"] = {
                    "merged_params": merged,
                    "used_preset": merged.get("_preset"),
                    "used_history": merged.get("_history_source"),
                }
                audit.record(args.action, merged["hostname"], "success", details={
                    "template": merged.get("template"), "cluster": merged.get("cluster"),
                    "ds": merged.get("ds"), "ip": merged.get("ip"),
                    "preset": merged.get("_preset"),
                    "history": merged.get("_history_source"),
                })

            elif args.action == "metrics":
                # v1.4: 采集一轮指标到 data/metrics/
                out = metrics_collector.collect_from_vcenter(executor)
                response["data"] = out
                response["message"] = f"采集 {len(out)} 条指标已落盘"
                audit.record(args.action, "(metrics)", "success",
                             operator=args.acting_user or "agent",
                             details={"count": len(out)})

            elif args.action == "recommend":
                # v1.4: 资源推荐
                cpus = args.cpu or 2
                memory = args.memory or 4
                disk = args.disk or 40
                if args.preset:
                    try:
                        ps = apply_preset(args.preset, user_params=None)
                        cpus = cpus if args.cpu else (ps.get("cpus") or cpus)
                        memory = memory if args.memory else (ps.get("memory_gb") or memory)
                        disk = disk if args.disk else (ps.get("disk_gb") or disk)
                    except Exception:
                        pass
                recs = recommender.recommend(
                    executor=executor,
                    cpus=cpus, memory_gb=memory, disk_gb=disk,
                    name_prefix=args.recommend_prefix or "",
                    target_count=args.recommend_count or 1,
                    top_n=args.recommend_top or 3,
                )
                response["data"] = recs
                response["message"] = recommender.format_recommendations(recs)
                audit.record(args.action, f"top{args.recommend_top}", "success",
                             operator=args.acting_user or "agent",
                             details={"cpus": cpus, "memory": memory, "disk": disk,
                                      "count": args.recommend_count})

            elif args.action == "batch_clone":
                # v1.1: 批量克隆
                if not args.count or args.count <= 0:
                    raise ValueError("--count 必填且 > 0")
                required = [args.template, args.dc, args.cluster, args.ds, args.network]
                if not all(required):
                    raise ValueError("批量克隆需 --template/--dc/--cluster/--ds/--network")
                # 应用 preset
                cpus, memory, disk, gw = args.cpu, args.memory, args.disk, args.gw
                if args.preset:
                    ps = apply_preset(args.preset, user_params=None)
                    cpus = cpus or ps.get("cpus")
                    memory = memory or ps.get("memory_gb")
                    disk = disk or ps.get("disk_gb")
                    gw = gw or ps.get("gateway")

                specs = batch_clone_mod.generate_clone_specs(
                    template_name=args.template, dc_name=args.dc,
                    cluster_name=args.cluster, ds_name=args.ds,
                    network_name=args.network, host_name=args.host_node,
                    cpus=cpus, memory_gb=memory, disk_gb=disk,
                    subnet=args.mask or "255.255.255.0", gateway=gw,
                    count=args.count, name_prefix=args.name_prefix or "vm-",
                    name_start=args.name_start or 1,
                    ip_pool_spec=args.ip_pool_spec,
                )
                summary = batch_clone_mod.batch_clone(
                    executor, specs,
                    max_workers=args.workers or 3,
                    wait_tools=not args.no_wait_tools,
                    tools_timeout=args.tools_timeout or 300,
                )
                response["data"] = summary
                response["message"] = batch_clone_mod.format_batch_summary(summary)
                audit.record(args.action, f"{args.name_prefix}*({args.count})",
                             "success" if summary["failed"] == 0 else "warning",
                             details={"total": summary["total"], "success": summary["success"],
                                      "failed": summary["failed"], "preset": args.preset})

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
