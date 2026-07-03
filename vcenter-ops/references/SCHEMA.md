# vcenter-ops 参数 Schema

> 本文件由 `scripts/handler.py` 的 argparse 定义整理而来，用于替代旧版 `SKILL.md` 中的长 `input_schema`。

- action 数量：35
- 参数数量：110
- 入口：`python3 scripts/handler.py --action <action> [options]`

## Action Enum

```text
list_all
get_vm
clone_vm
delete_vm
power_vm
snapshot
reconfigure
guest_exec
migrate
plan
ttl
datastore
template
batch
approval
events
quota
export
history
preset
batch_clone
ip_pool
webhook
audit_report
secret
rbac
danger
approval_policy
change_window
metrics
recommend
anomaly
forecast
delivery
post_init
```

## JSON Schema

```json
{
  "type": "object",
  "required": [
    "action"
  ],
  "properties": {
    "host": {
      "type": "string",
      "description": "vCenter 主机地址（可选，默认读 config.yaml）"
    },
    "user": {
      "type": "string",
      "description": "用户名（可选，默认读 config.yaml）"
    },
    "pwd": {
      "type": "string",
      "description": "密码（可选，默认读 config.yaml）"
    },
    "port": {
      "type": "integer",
      "description": "端口（可选，默认读 config.yaml）"
    },
    "action": {
      "type": "string",
      "enum": [
        "list_all",
        "get_vm",
        "clone_vm",
        "delete_vm",
        "power_vm",
        "snapshot",
        "reconfigure",
        "guest_exec",
        "migrate",
        "plan",
        "ttl",
        "datastore",
        "template",
        "batch",
        "approval",
        "events",
        "quota",
        "export",
        "history",
        "preset",
        "batch_clone",
        "ip_pool",
        "webhook",
        "audit_report",
        "secret",
        "rbac",
        "danger",
        "approval_policy",
        "change_window",
        "metrics",
        "recommend",
        "anomaly",
        "forecast",
        "delivery",
        "post_init"
      ],
      "description": "执行的操作类型"
    },
    "hostname": {
      "type": "string",
      "description": "虚拟机名称"
    },
    "template": {
      "type": "string",
      "description": "克隆源模板名称"
    },
    "dc": {
      "type": "string",
      "description": "数据中心名称"
    },
    "cluster": {
      "type": "string",
      "description": "计算集群名称"
    },
    "ds": {
      "type": "string",
      "description": "存储池名称"
    },
    "network": {
      "type": "string",
      "description": "目标网络/VLAN 名称"
    },
    "host_node": {
      "type": "string",
      "description": "指定物理宿主机节点名称"
    },
    "cpu": {
      "type": "integer",
      "description": "CPU 核数"
    },
    "memory": {
      "type": "integer",
      "description": "内存大小 (GB)"
    },
    "disk": {
      "type": "integer",
      "description": "主磁盘容量 (GB)"
    },
    "ip": {
      "type": "string",
      "description": "静态 IP 地址"
    },
    "mask": {
      "type": "string",
      "description": "子网掩码"
    },
    "gw": {
      "type": "string",
      "description": "默认网关"
    },
    "state": {
      "type": "string",
      "enum": [
        "on",
        "off",
        "reset"
      ],
      "description": "电源操作状态"
    },
    "power_on": {
      "type": "boolean",
      "description": "完成后是否开机"
    },
    "snap_action": {
      "type": "string",
      "enum": [
        "create",
        "list",
        "revert",
        "delete"
      ],
      "description": "快照子操作类型（create/list/revert/delete）"
    },
    "snap_name": {
      "type": "string",
      "description": "快照名称"
    },
    "dry_run": {
      "type": "boolean",
      "description": "Dry-Run 模式：只输出将要执行的操作，不实际执行"
    },
    "audit_query": {
      "type": "boolean",
      "description": "查询审计日志（配合 --action 和 --hostname 筛选）"
    },
    "cmd": {
      "type": "string",
      "description": "Guest OS 中要执行的命令"
    },
    "guest_user": {
      "type": "string",
      "default": "root",
      "description": "Guest OS 用户名（默认 root）"
    },
    "guest_pwd": {
      "type": "string",
      "default": "",
      "description": "Guest OS 密码"
    },
    "target_host": {
      "type": "string",
      "description": "vMotion 目标宿主机名/IP"
    },
    "plan_action": {
      "type": "string",
      "enum": [
        "create",
        "execute",
        "rollback",
        "list",
        "delete"
      ],
      "description": "计划子操作类型"
    },
    "plan_id": {
      "type": "string",
      "description": "计划 ID"
    },
    "plan_steps": {
      "type": "string",
      "description": "计划步骤列表（JSON 格式）"
    },
    "plan_desc": {
      "type": "string",
      "description": "计划描述"
    },
    "ttl_action": {
      "type": "string",
      "enum": [
        "set",
        "cancel",
        "list",
        "cleanup"
      ],
      "description": "TTL 子操作类型"
    },
    "ttl_minutes": {
      "type": "integer",
      "description": "TTL 分钟数"
    },
    "creator": {
      "type": "string",
      "default": "agent",
      "description": "TTL 设置者"
    },
    "ds_name": {
      "type": "string",
      "description": "数据存储名称"
    },
    "ds_path": {
      "type": "string",
      "default": "",
      "description": "数据存储子路径"
    },
    "ds_scan": {
      "type": "boolean",
      "description": "扫描所有数据存储中的镜像文件"
    },
    "tpl_action": {
      "type": "string",
      "enum": [
        "list",
        "register",
        "convert"
      ],
      "description": "模板子操作类型（list/register/convert）"
    },
    "tpl_name": {
      "type": "string",
      "description": "模板名称（register 时使用）"
    },
    "batch_action": {
      "type": "string",
      "enum": [
        "power"
      ],
      "description": "批量子操作类型"
    },
    "pattern": {
      "type": "string",
      "description": "VM 名称匹配模式（支持 * 和 ? 通配符）"
    },
    "approval_action": {
      "type": "string",
      "enum": [
        "create",
        "approve",
        "reject",
        "list",
        "cancel"
      ],
      "description": "审批子操作类型"
    },
    "approval_id": {
      "type": "string",
      "description": "审批 ID"
    },
    "approval_params": {
      "type": "string",
      "description": "审批关联的操作参数（JSON 格式）"
    },
    "approval_target_action": {
      "type": "string",
      "description": "审批关联的目标操作类型"
    },
    "comment": {
      "type": "string",
      "description": "审批意见"
    },
    "minutes": {
      "type": "integer",
      "description": "查询最近 N 分钟的事件（默认 60）"
    },
    "event_category": {
      "type": "string",
      "enum": [
        "power",
        "create_delete",
        "migration",
        "snapshot",
        "alarm"
      ],
      "description": "事件类别过滤"
    },
    "cpu_threshold": {
      "type": "number",
      "description": "CPU 使用率告警阈值（0-1，默认 0.85）"
    },
    "mem_threshold": {
      "type": "number",
      "description": "内存使用率告警阈值（默认 0.85）"
    },
    "disk_threshold": {
      "type": "number",
      "description": "磁盘使用率告警阈值（默认 0.9）"
    },
    "export_format": {
      "type": "string",
      "enum": [
        "json",
        "csv",
        "markdown",
        "html"
      ],
      "description": "导出格式（默认 json）"
    },
    "output": {
      "type": "string",
      "description": "输出文件路径"
    },
    "top": {
      "type": "integer",
      "default": "50",
      "description": "返回结果数量限制"
    },
    "preset": {
      "type": "string",
      "description": "使用预设包（如 @dev-small / dev-small），参数会被同名 CLI 参数覆盖"
    },
    "from_last": {
      "type": "boolean",
      "description": "克隆时复用最近一次克隆参数（仅覆盖未指定的项）"
    },
    "from_vm": {
      "type": "string",
      "description": "克隆时复用与指定 VM 同名的历史克隆参数"
    },
    "no_wait_tools": {
      "type": "boolean",
      "description": "克隆后不等待 VMware Tools 就绪"
    },
    "tools_timeout": {
      "type": "integer",
      "default": "300",
      "description": "等待 Tools 就绪超时（默认 300s）"
    },
    "count": {
      "type": "integer",
      "description": "批量克隆数量"
    },
    "name_prefix": {
      "type": "string",
      "default": "vm-",
      "description": "批量克隆 VM 名前缀"
    },
    "name_start": {
      "type": "integer",
      "default": "1",
      "description": "批量克隆编号起始"
    },
    "ip_pool": {
      "type": "string",
      "description": "IP 池声明（CIDR/范围/单IP，逗号隔）"
    },
    "workers": {
      "type": "integer",
      "default": "3",
      "description": "批量并行度"
    },
    "preset_action": {
      "type": "string",
      "enum": [
        "list",
        "save",
        "save-from-last",
        "delete",
        "show"
      ],
      "description": "预设子操作"
    },
    "preset_name": {
      "type": "string",
      "description": "预设名"
    },
    "preset_desc": {
      "type": "string",
      "default": ""
    },
    "preset_overwrite": {
      "type": "boolean"
    },
    "ip_action": {
      "type": "string",
      "enum": [
        "available",
        "allocate",
        "release",
        "reservations",
        "cleanup"
      ]
    },
    "ip_spec": {
      "type": "string",
      "description": "IP 池声明"
    },
    "ip_target": {
      "type": "string",
      "description": "要释放的 IP"
    },
    "webhook_action": {
      "type": "string",
      "enum": [
        "list",
        "add",
        "remove",
        "toggle"
      ]
    },
    "webhook_name": {
      "type": "string"
    },
    "webhook_url": {
      "type": "string"
    },
    "webhook_secret": {
      "type": "string",
      "default": ""
    },
    "webhook_topics": {
      "type": "string",
      "default": "[\"*\"]"
    },
    "webhook_mode": {
      "type": "string",
      "enum": [
        "http",
        "dingtalk"
      ],
      "default": "http"
    },
    "webhook_id": {
      "type": "string"
    },
    "webhook_enable": {
      "type": "boolean"
    },
    "webhook_disable": {
      "type": "boolean"
    },
    "report_days": {
      "type": "integer",
      "default": "7",
      "description": "审计报表覆盖天数"
    },
    "actor": {
      "type": "string",
      "default": "agent",
      "description": "当前操作人（用于 RBAC/审批/危险确认）"
    },
    "confirmed": {
      "type": "boolean",
      "description": "危险操作二次确认标记"
    },
    "secret_action": {
      "type": "string",
      "enum": [
        "list",
        "set",
        "get",
        "delete",
        "migrate",
        "rotate"
      ]
    },
    "secret_key": {
      "type": "string"
    },
    "secret_value": {
      "type": "string"
    },
    "secret_desc": {
      "type": "string",
      "default": ""
    },
    "rbac_action": {
      "type": "string",
      "enum": [
        "roles",
        "users",
        "bind",
        "unbind",
        "check",
        "config"
      ]
    },
    "rbac_user": {
      "type": "string"
    },
    "rbac_role": {
      "type": "string"
    },
    "rbac_target_action": {
      "type": "string"
    },
    "danger_action": {
      "type": "string",
      "enum": [
        "scan",
        "confirm",
        "patterns",
        "config"
      ]
    },
    "danger_target": {
      "type": "string"
    },
    "danger_op": {
      "type": "string",
      "default": "delete_vm"
    },
    "policy_action": {
      "type": "string",
      "enum": [
        "list",
        "route",
        "config"
      ]
    },
    "policy_target_action": {
      "type": "string"
    },
    "policy_target": {
      "type": "string",
      "default": ""
    },
    "window_action": {
      "type": "string",
      "enum": [
        "status",
        "check",
        "config"
      ]
    },
    "window_op": {
      "type": "string"
    },
    "metrics_action": {
      "type": "string",
      "enum": [
        "collect",
        "query",
        "cleanup"
      ]
    },
    "metric_type": {
      "type": "string"
    },
    "metric_target": {
      "type": "string"
    },
    "metric_days": {
      "type": "integer",
      "default": "7"
    },
    "metrics_keep_days": {
      "type": "integer",
      "default": "30"
    },
    "metrics_dry_run": {
      "type": "boolean"
    },
    "recommend_top": {
      "type": "integer",
      "default": "3"
    },
    "recommend_count": {
      "type": "integer",
      "default": "1"
    },
    "recommend_prefix": {
      "type": "string",
      "default": ""
    },
    "forecast_threshold": {
      "type": "number",
      "default": "0.9"
    },
    "delivery_action": {
      "type": "string",
      "enum": [
        "plan",
        "execute",
        "verify"
      ],
      "description": "标准交付子操作"
    },
    "delivery_confirm": {
      "type": "boolean",
      "description": "确认执行 delivery execute"
    },
    "skip_clone": {
      "type": "boolean",
      "description": "跳过真实 clone"
    },
    "delivery_name": {
      "type": "string"
    },
    "owner": {
      "type": "string"
    },
    "env": {
      "type": "string"
    },
    "app": {
      "type": "string"
    },
    "gateway": {
      "type": "string"
    },
    "datastore": {
      "type": "string"
    },
    "expected_hostname": {
      "type": "string"
    },
    "ssh_check": {
      "type": "boolean",
      "description": "检查 SSH 端口"
    },
    "ssh_port": {
      "type": "integer",
      "default": "22"
    },
    "init_timeout": {
      "type": "integer",
      "default": "3"
    }
  }
}
```
