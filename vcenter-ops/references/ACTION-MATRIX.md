# vcenter-ops Action Matrix

> 从 `scripts/handler.py --help` 和运维规则整理。风险级别：🔵 查询/低风险，🟡 变更/敏感，🔴 删除/不可逆。

- action 总数：33
- `export_format` 支持：`json` / `csv` / `markdown` / `html`

## 基础查询

| Action | 风险 | 示例命令 |
|---|---|---|
| `list_all` | 🔵 | `python3 scripts/handler.py --action list_all` |
| `get_vm` | 🔵 | `python3 scripts/handler.py --action get_vm --hostname "xxx"` |
| `events` | 🔵 | `python3 scripts/handler.py --action events --minutes 60 --event_category power` |
| `quota` | 🔵 | `python3 scripts/handler.py --action quota --cluster "xxx" --cpu_threshold 0.85` |
| `export` | 🔵 | `python3 scripts/handler.py --action export --export_format json|csv|markdown|html --output /tmp/vms.out` |
| `audit_report` | 🔵 | `python3 scripts/handler.py --action audit_report --export_format html --output /tmp/vcenter-audit.html` |
| `history` | 🔵 | `python3 scripts/handler.py --action history` |
| `preset` | 🔵 | `python3 scripts/handler.py --action preset --preset-action list|show|save|delete` |

## 创建交付

| Action | 风险 | 示例命令 |
|---|---|---|
| `clone_vm` | 🔵 | `python3 scripts/handler.py --action clone_vm --hostname "xxx" --template "tpl" --dc "DC" --cluster "CL" --ds "DS" --network "VLAN" --ip "x.x.x.x" --mask "255.255.255.0" --gw "x.x.x.1"` |
| `batch_clone` | 🟡 | `python3 scripts/handler.py --action batch_clone --count 3 --name-prefix web- --ip-pool 10.0.0.0/24` |
| `recommend` | 🔵 | `python3 scripts/handler.py --action recommend --cpu 4 --memory 8 --disk 100 --recommend-top 3` |

## 变更操作

| Action | 风险 | 示例命令 |
|---|---|---|
| `power_vm` | 🟡 | `python3 scripts/handler.py --action power_vm --hostname "xxx" --state on|off|reset` |
| `snapshot` | 🔵 | `python3 scripts/handler.py --action snapshot --hostname "xxx" --snap_action create|list|revert|delete --snap_name "snap"` |
| `reconfigure` | 🔵 | `python3 scripts/handler.py --action reconfigure --hostname "xxx" --cpu 8 --memory 16 --disk 200` |
| `migrate` | 🟡 | `python3 scripts/handler.py --action migrate --hostname "xxx" --target_host "esxi-02"` |
| `guest_exec` | 🟡 | `python3 scripts/handler.py --action guest_exec --hostname "xxx" --cmd "uptime" --guest-user root --guest-pwd "***"` |
| `ttl` | 🟡 | `python3 scripts/handler.py --action ttl --ttl_action set|cancel|list|cleanup` |

## 存储模板

| Action | 风险 | 示例命令 |
|---|---|---|
| `datastore` | 🔵 | `python3 scripts/handler.py --action datastore --ds_name "datastore1" --ds_path "iso/"` |
| `template` | 🟡 | `python3 scripts/handler.py --action template --tpl_action list|register|convert` |

## 批量编排

| Action | 风险 | 示例命令 |
|---|---|---|
| `batch` | 🟡 | `python3 scripts/handler.py --action batch --batch_action power --pattern "web-*" --state on` |
| `plan` | 🔵 | `python3 scripts/handler.py --action plan --plan_action create|execute|rollback|list|delete` |

## 协作审批

| Action | 风险 | 示例命令 |
|---|---|---|
| `approval` | 🟡 | `python3 scripts/handler.py --action approval --approval_action create|approve|reject|list|cancel` |
| `approval_policy` | 🟡 | `python3 scripts/handler.py --action approval_policy --policy-action list|route|config` |
| `webhook` | 🟡 | `python3 scripts/handler.py --action webhook --webhook-action list|add|remove|toggle` |

## 安全合规

| Action | 风险 | 示例命令 |
|---|---|---|
| `secret` | 🟡 | `python3 scripts/handler.py --action secret --secret-action list|set|get|delete|migrate|rotate` |
| `rbac` | 🟡 | `python3 scripts/handler.py --action rbac --rbac-action roles|users|bind|unbind|check|config` |
| `danger` | 🟡 | `python3 scripts/handler.py --action danger --danger-action scan|confirm|patterns|config` |
| `change_window` | 🟡 | `python3 scripts/handler.py --action change_window --window-action status|check|config` |

## 可观测智能

| Action | 风险 | 示例命令 |
|---|---|---|
| `metrics` | 🟡 | `python3 scripts/handler.py --action metrics --metrics-action collect|query|cleanup` |
| `anomaly` | 🔵 | `python3 scripts/handler.py --action anomaly --metric-days 7` |
| `forecast` | 🔵 | `python3 scripts/handler.py --action forecast --forecast-threshold 0.9` |

## IP 管理

| Action | 风险 | 示例命令 |
|---|---|---|
| `ip_pool` | 🔵 | `python3 scripts/handler.py --action ip_pool --ip-action available|allocate|release|reservations|cleanup --ip-spec 10.0.0.0/24` |

## 删除销毁

| Action | 风险 | 示例命令 |
|---|---|---|
| `delete_vm` | 🔴 | `python3 scripts/handler.py --action delete_vm --hostname "xxx"` |

## 强制安全规则

- 删除/销毁类操作必须精确指定 VM 名称或 IP。
- 禁止“删除全部/清空/按通配符删除”。
- 删除操作必须二次确认；启用审批策略时必须走审批。
- 批量、Guest 命令、vMotion、Webhook、密钥、RBAC、变更窗口均按敏感操作处理。

## 标准交付 / 初始化

| Action | 风险 | 示例命令 |
|---|---|---|
| `delivery` | 🟡 | `python3 scripts/handler.py --action delivery --delivery-action plan --name web01 --ip 10.0.0.10 --owner user --template tpl --dc DC --cluster CL --datastore DS --network VLAN --gateway 10.0.0.1` |
| `post_init` | 🔵 | `python3 scripts/handler.py --action post_init --hostname 10.0.0.10-web01 --ip 10.0.0.10 --ssh-check` |
