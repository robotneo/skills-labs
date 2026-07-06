# vcenter-ops 参数 Schema

> 本文件是 CLI 快速参考。权威定义以 `python3 scripts/handler.py --help` 为准。

- Action 数量：22
- 入口：`python3 scripts/handler.py --action <action> [options]`

## Action 枚举

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
events
quota
export
history
preset
ip_pool
audit_report
secret
danger
```

## 参数分组速览

### 连接与全局

| 参数 | 说明 |
|---|---|
| `--host` / `--user` / `--pwd` / `--port` | vCenter 连接参数，默认从 `config.yaml` + `.env` 读取 |
| `--action` | 必填，选择上表中的一个动作 |
| `--dry-run` | 只输出将要执行的操作，不实际调用 vCenter |
| `--audit-query` | 查询审计日志（可配合 `--action` 与 `--hostname`） |
| `--actor` | 当前操作人（用于审计与危险确认） |
| `--confirmed` | 危险操作二次确认标记 |

### 核心业务参数

| 参数 | 说明 |
|---|---|
| `--hostname` | 虚拟机名称 |
| `--template` / `--dc` / `--cluster` / `--ds` / `--network` | 克隆所需资源标识 |
| `--host_node` | 指定物理宿主机节点 |
| `--cpu` / `--memory` / `--disk` | CPU 核数、内存 (GB)、磁盘 (GB) |
| `--ip` / `--mask` / `--gw` | 静态 IP、掩码、网关 |
| `--state` | 电源状态：`on` / `off` / `reset` |
| `--power_on` | clone 完成后自动开机 |

### 快照 / TTL / 事件 / 配额 / 导出

| 参数 | 说明 |
|---|---|
| `--snap_action` | 快照子操作：`create` / `list` / `revert` / `delete` |
| `--snap_name` | 快照名称 |
| `--ttl_action` | TTL 子操作：`set` / `cancel` / `list` / `cleanup` |
| `--ttl_minutes` | TTL 分钟数 |
| `--creator` | TTL 设置者 |
| `--minutes` / `--event_category` | 事件查询窗口与类别 |
| `--cpu_threshold` / `--mem_threshold` / `--disk_threshold` | 配额告警阈值 |
| `--export_format` / `--output` | 报表输出格式与目标文件 |
| `--top` | 通用结果条数限制 |
| `--report-days` | 审计报表覆盖天数 |

### 数据存储 / 模板 / 批量 / Plan

| 参数 | 说明 |
|---|---|
| `--ds_name` / `--ds_path` / `--ds_scan` | 数据存储浏览 |
| `--tpl_action` / `--tpl_name` | 模板子操作：`list` / `register` / `convert` |
| `--batch_action` / `--pattern` | 批量子操作与 VM 通配符匹配 |
| `--plan_action` / `--plan_id` / `--plan_steps` / `--plan_desc` | Plan/Apply 编排 |

### Guest OS / 迁移

| 参数 | 说明 |
|---|---|
| `--cmd` | Guest OS 内要执行的命令 |
| `--guest-user` / `--guest-pwd` | Guest OS 凭据 |
| `--target_host` | vMotion 目标宿主机 |

### 预设 / 历史

| 参数 | 说明 |
|---|---|
| `--preset` | 使用预设包（如 `dev-small`），参数会被同名 CLI 参数覆盖 |
| `--from-last` / `--from-vm` | 复用最近一次克隆参数 / 复用与指定 VM 同名的历史参数 |
| `--no-wait-tools` / `--tools-timeout` | 克隆后是否等待 VMware Tools 就绪 |
| `--preset-action` / `--preset-name` / `--preset-desc` / `--preset-overwrite` | 预设子操作 |

### IP 池 / Secret / Danger

| 参数 | 说明 |
|---|---|
| `--ip-action` | IP 池子操作：`available` / `allocate` / `release` / `reservations` / `cleanup` |
| `--ip-spec` | IP 池声明（CIDR/范围/单 IP） |
| `--ip-target` | 要释放的 IP |
| `--secret-action` / `--secret-key` / `--secret-value` / `--secret-desc` | 加密存储子操作 |
| `--danger-action` / `--danger-target` / `--danger-op` | 危险词扫描/确认/规则查询 |
