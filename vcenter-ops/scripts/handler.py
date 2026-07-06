"""
Module: scripts.handler
Description: vCenter Ops Skill entry-point dispatcher.

职责
----
- 组装 CLI 参数（委托给 :mod:`scripts.cli.arguments`）。
- 加载并解析 vCenter 连接信息（委托给 :mod:`scripts.config_loader`）。
- 根据 ``--action`` 分发到相应处理逻辑，落盘审计并输出统一 JSON 信封。

CLI 契约
--------
- ``python3 scripts/handler.py --help`` 中 22 个 action 与参数名保持稳定。
- 输出结构默认 ``{status, action, data, message}``，Dry-Run 特例为
  ``{status, action, params, message}``（由 :class:`Response` 保证）。
"""

import sys
import os
import json
import logging
from typing import Dict, Any

# 将项目根目录添加到 sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.client import VCenterClient
from scripts.inventory import VCenterInventory
from scripts.executor import VCenterExecutor
from scripts import audit
from scripts import plan_manager
from scripts import ttl_manager
from scripts.history_manager import last_clone_params, list_history, format_history_summary, format_clone_params
from scripts.preset_manager import (
    apply_preset, list_presets, format_preset_list, parse_preset_from_text,
    save_preset, save_from_history, delete_preset, get_preset,
)
from scripts.progress_reporter import ProgressReporter, stdout_sink
from scripts.error_dictionary import format_error_oneline
from scripts import ip_pool
# 安全底座
from scripts import secret_manager
from scripts import danger_validator

# 新的公共基础设施
from scripts.cli.arguments import build_parser
from scripts.cli.dry_run import build_dry_run_params, DRY_RUN_SKIP_ACTIONS
from scripts.cli.response import Response, Status
from scripts.config_loader import load_config, save_config, resolve_connection
from scripts.logging_setup import configure_logging
from scripts.paths import SKILL_DIR, CONFIG_FILE  # 兼容旧引用

# 日志统一走 stderr，stdout 只输出干净 JSON。
configure_logging()
logger = logging.getLogger(__name__)



def main():
    parser = build_parser()
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
    # 声明式白名单在 :mod:`scripts.cli.dry_run` 中维护，此处只做分发。
    if args.dry_run and args.action not in DRY_RUN_SKIP_ACTIONS:
        params = build_dry_run_params(args)
        audit.record(args.action, args.hostname or "(无目标)",
                     "dry_run", details=params)
        Response.dry_run(args.action, params=params).emit()
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
        ip_op = args.ip_action or "reservations"
        if ip_op == "available":
            if not args.ip_spec: raise ValueError("--ip-action available 需 --ip-spec")
            pool = ip_pool.IPPool(args.ip_spec, skip_alive=True)
            ips = pool.available(limit=args.top or 20)
            response["data"] = ips
            response["message"] = f"可用 IP {len(ips)} 个"
        elif ip_op == "allocate":
            if not args.ip_spec: raise ValueError("--ip-action allocate 需 --ip-spec")
            pool = ip_pool.IPPool(args.ip_spec, skip_alive=True)
            recs = pool.allocate(args.count or 1, vm_name_prefix=args.name_prefix or "vm-")
            response["data"] = recs
            response["message"] = f"已分配 {len(recs)} 个 IP"
        elif ip_op == "release":
            if not args.ip_target: raise ValueError("--ip-action release 需 --ip-target")
            ok = ip_pool.release_ip(args.ip_target)
            response["message"] = f"{'✅ 已释放' if ok else '⚠️ 未找到'}: {args.ip_target}"
        elif ip_op == "reservations":
            recs = ip_pool.list_reservations()
            response["data"] = recs
            response["message"] = f"共 {len(recs)} 条预留"
        elif ip_op == "cleanup":
            n = ip_pool.cleanup_expired()
            response["message"] = f"清理过期预留 {n} 个"
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
        secret_op = args.secret_action or "list"
        if secret_op == "list":
            response["data"] = secret_manager.list_secret_keys()
            response["message"] = f"共 {len(response['data'])} 个加密存储项"
        elif secret_op == "set":
            if not args.secret_key or not args.secret_value:
                raise ValueError("--secret-action set 需 --secret-key 和 --secret-value")
            secret_manager.set_secret(args.secret_key, args.secret_value, description=args.secret_desc)
            response["message"] = f"✅ 已加密存储: {args.secret_key}"
        elif secret_op == "get":
            if not args.secret_key: raise ValueError("--secret-action get 需 --secret-key")
            v = secret_manager.get_secret(args.secret_key)
            response["data"] = {"key": args.secret_key, "found": v is not None,
                                "value": v if v else None}
            response["message"] = "⚠️ 明文返回请谨慎使用" if v else "未找到"
        elif secret_op == "delete":
            if not args.secret_key: raise ValueError("--secret-action delete 需 --secret-key")
            ok = secret_manager.delete_secret(args.secret_key)
            response["message"] = f"{'✅ 已删除' if ok else '⚠️ 未找到'}: {args.secret_key}"
        elif secret_op == "migrate":
            result = secret_manager.migrate_from_env(dry_run=args.dry_run)
            response["data"] = result
            response["message"] = result.get("message", "")
        elif secret_op == "rotate":
            result = secret_manager.rotate_key()
            response["data"] = result
            response["message"] = result.get("message", "")
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    if args.action == "danger":
        danger_op_kind = args.danger_action or "scan"
        if danger_op_kind == "scan":
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
        elif danger_op_kind == "confirm":
            if not args.danger_target: raise ValueError("--danger-action confirm 需 --danger-target")
            danger_validator.confirm_danger(args.danger_target, args.danger_op, user=args.acting_user)
            response["message"] = f"✅ 已确认危险操作: {args.danger_op} → {args.danger_target}"
        elif danger_op_kind == "patterns":
            response["data"] = danger_validator.load_danger_config().get("patterns", [])
            response["message"] = f"共 {len(response['data'])} 个危险词模式"
        elif danger_op_kind == "config":
            response["data"] = danger_validator.load_danger_config()
            response["message"] = "当前危险词配置"
        print(json.dumps(response, ensure_ascii=False, indent=2))
        return

    # ========== 以下操作需要 vCenter 连接 ==========

    try:
        # 解析连接信息
        conn = resolve_connection(args, cfg)
        host, user, pwd, port = conn.as_tuple()

        # ============ 安全门：危险词校验（单人管理员场景仅保留此项）============
        if args.hostname:
            try:
                if args.confirmed:
                    danger_validator.confirm_danger(args.hostname, args.action,
                                                    user=args.acting_user or "agent")
                danger_validator.validate_danger(
                    args.hostname, args.action, user=args.acting_user or "agent"
                )
            except danger_validator.DangerConfirmRequired as error:
                response["status"] = "confirm_required"
                response["message"] = (
                    str(error) + " 请重新执行并传 --confirmed 确认"
                )
                audit.record(args.action, args.hostname, "awaiting_confirm",
                             operator=args.acting_user or "agent",
                             details={"matched": error.matched})
                print(json.dumps(response, ensure_ascii=False, indent=2))
                return

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
