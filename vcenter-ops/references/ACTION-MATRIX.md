# vcenter-ops Action Matrix

> 精简版（v2.0）单人 IT 管理员场景。风险级别：🔵 查询/低风险，🟡 变更/敏感，🔴 删除/不可逆。

- Action 总数：22
- `export_format` 支持：`json` / `csv` / `markdown` / `html`

## 基础查询

| Action | 风险 | 示例命令 |
|---|---|---|
| `list_all` | 🔵 | `python3 scripts/handler.py --action list_all` |
| `get_vm` | 🔵 | `python3 scripts/handler.py --action get_vm --hostname "xxx"` |
| `events` | 🔵 | `python3 scripts/handler.py --action events --minutes 60 --event_category power` |
| `quota` | 🔵 | `python3 scripts/handler.py --action quota --cluster "xxx" --cpu_threshold 0.85` |
| `export` | 🔵 | `python3 scripts/handler.py --action export --export_format json --output /tmp/vms.json` |
| `audit_report` | 🔵 | `python3 scripts/handler.py --action audit_report --export_format html --output /tmp/vcenter-audit.html` |
| `history` | 🔵 | `python3 scripts/handler.py --action history` |
| `preset` | 🔵 | `python3 scripts/handler.py --action preset --preset-action list` |

## 创建交付

| Action | 风险 | 示例命令 |
|---|---|---|
| `clone_vm` | 🔵 | `python3 scripts/handler.py --action clone_vm --hostname "xxx" --template "tpl" --dc "DC" --cluster "CL" --ds "DS" --network "VLAN" --ip "x.x.x.x" --mask "255.255.255.0" --gw "x.x.x.1"` |

## 变更操作

| Action | 风险 | 示例命令 |
|---|---|---|
| `power_vm` | 🟡 | `python3 scripts/handler.py --action power_vm --hostname "xxx" --state on` |
| `snapshot` | 🔵🟡 | `python3 scripts/handler.py --action snapshot --hostname "xxx" --snap_action create --snap_name "snap"` |
| `reconfigure` | 🟡 | `python3 scripts/handler.py --action reconfigure --hostname "xxx" --cpu 8 --memory 16 --disk 200` |
| `migrate` | 🟡 | `python3 scripts/handler.py --action migrate --hostname "xxx" --target_host "esxi-02"` |
| `guest_exec` | 🟡 | `python3 scripts/handler.py --action guest_exec --hostname "xxx" --cmd "uptime" --guest-user root --guest-pwd "***"` |
| `ttl` | 🟡 | `python3 scripts/handler.py --action ttl --ttl_action set --hostname "xxx" --ttl_minutes 60` |

## 存储 / 模板

| Action | 风险 | 示例命令 |
|---|---|---|
| `datastore` | 🔵 | `python3 scripts/handler.py --action datastore --ds_name "datastore1" --ds_path "iso/"` |
| `template` | 🟡 | `python3 scripts/handler.py --action template --tpl_action list` |

## 批量 / 编排

| Action | 风险 | 示例命令 |
|---|---|---|
| `batch` | 🟡 | `python3 scripts/handler.py --action batch --batch_action power --pattern "web-*" --state on` |
| `plan` | 🔵🟡 | `python3 scripts/handler.py --action plan --plan_action create --plan_steps '[{"op":"power","target":"web-01","state":"off"}]'` |

## 安全 / 合规

| Action | 风险 | 示例命令 |
|---|---|---|
| `secret` | 🟡 | `python3 scripts/handler.py --action secret --secret-action set --secret-key VCENTER_PASSWORD --secret-value '***'` |
| `danger` | 🟡 | `python3 scripts/handler.py --action danger --danger-action scan --danger-target "web-01"` |

## IP 管理

| Action | 风险 | 示例命令 |
|---|---|---|
| `ip_pool` | 🔵 | `python3 scripts/handler.py --action ip_pool --ip-action available --ip-spec 10.0.0.0/24` |

## 删除销毁

| Action | 风险 | 示例命令 |
|---|---|---|
| `delete_vm` | 🔴 | `python3 scripts/handler.py --action delete_vm --hostname "xxx" --confirmed` |

## 强制安全规则

- 删除/销毁类操作必须精确指定 VM 名称或 IP。
- 禁止“删除全部/清空/按通配符删除”。
- 删除操作必须二次确认，通过 `--confirmed` 传递第二次确认。
- 批量、Guest 命令、vMotion、密钥、TTL 均按敏感操作处理。
- 所有变更操作支持 `--dry-run` 预演。
