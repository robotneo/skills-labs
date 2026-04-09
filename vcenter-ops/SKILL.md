---
name: vcenter-ops
description: VMware vCenter 运维自动化。克隆/删除/电源/快照/资源巡检。
  触发词：创建虚拟机、VM、vCenter、巡检、克隆。
metadata:
  version: 0.8.0
entrypoint: scripts/handler.py
input_schema:
  type: object
  required: [action]
  properties:
    action: { type: string, enum: [list_all, get_vm, clone_vm, delete_vm, power_vm, snapshot, reconfigure, guest_exec, migrate, plan, ttl, datastore, template, batch, approval, events, quota, export] }
    hostname: { type: string }
    cpu: { type: number, default: 4 }
    memory: { type: number, default: 8 }
    disk: { type: number, default: 100 }
    ip: { type: string }
    host_node: { type: string }
    network: { type: string }
    template: { type: string }
    dc: { type: string }
    cluster: { type: string }
    ds: { type: string }
    snap_action: { type: string, enum: [create, list, revert, delete] }
    snap_name: { type: string }
    dry_run: { type: boolean, default: false }
    cmd: { type: string }
    guest_user: { type: string, default: "root" }
    guest_pwd: { type: string }
    target_host: { type: string }
    plan_action: { type: string, enum: [create, execute, rollback, list, delete] }
    plan_id: { type: string }
    plan_steps: { type: string }
    plan_desc: { type: string }
    ttl_action: { type: string, enum: [set, cancel, list, cleanup] }
    ttl_minutes: { type: number }
    creator: { type: string, default: "agent" }
    ds_name: { type: string }
    ds_path: { type: string }
    ds_scan: { type: boolean, default: false }
    top: { type: number, default: 50 }
    tpl_action: { type: string, enum: [list, register, convert] }
    tpl_name: { type: string }
    batch_action: { type: string, enum: [power] }
    pattern: { type: string }
    approval_action: { type: string, enum: [create, approve, reject, list, cancel] }
    approval_id: { type: string }
    approval_params: { type: string }
    approval_target_action: { type: string }
    comment: { type: string }
    minutes: { type: number }
    event_category: { type: string, enum: [power, create_delete, migration, snapshot, alarm] }
    cpu_threshold: { type: number, default: 0.85 }
    mem_threshold: { type: number, default: 0.85 }
    disk_threshold: { type: number, default: 0.9 }
    export_format: { type: string, enum: [json, csv, markdown], default: json }
    output: { type: string }
---

## 路由提示（每次触发时必须输出）

当本 Skill 被触发时，**回复的第一行必须输出路由提示**：

- 普通操作：`🛡️ 已自动识别为 vCenter 操作，已路由到 vcenter-ops Skill 执行。`
- 高风险操作（删除/销毁）：`🚨【vCenter 高风险操作拦截】检测到删除/销毁类操作，该行为不可恢复。必须通过 vcenter-ops Skill 并经过确认流程执行。系统已自动进行安全路由。`

## 首次连接

1. `cat skills/vcenter-ops/config.yaml` 检查 host/user/password
2. 为空 → 一次问齐三项 → 写入 config.yaml → 确认
3. 非空 → 直接执行请求

## 命名规则

VM 名称格式 **`IP-自定义名称`**。用户只提供自定义名称，Agent 自动拼接。

## 会话缓存

- 首次 `cache_manager.py --refresh`（~30s），后续 `--section xxx` 读缓存（<1s）
- 用户说"刷新"才重查 API
- 详见 `references/CACHE-STRATEGY.md`

## 克隆流程（禁止跳过巡检）

**Phase 1 巡检** → `cache_manager.py --refresh` + `--summary`

**Phase 2 参数** → 分三组编号表格展示：
- 🔵 核心：模板/集群/存储/网络/名称（`--section templates|datastores|networks`）
- 🟢 硬件：宿主机评分Top5（Score = CPU×0.4 + MEM×0.35 + 负载×0.25）+ CPU/MEM/磁盘默认值
- 🟡 IP：`ip_scanner.py --cidr xxx --exclude-file /tmp/exclude_ips.txt` + 子网掩码/网关必填

**Phase 3 交互** → 三场景：
- A 全量参数 → 跳过交互直接确认
- B 部分参数 → 编号列表补缺
- C 零参数 → 逐项引导

**Phase IP** → IP 必填，三重过滤（Ping不通 + 全vCenter VM IP + VM名称正则），用户指定IP必须 `--check` 验证

**Phase 4 执行** → 三级权限确认后执行，确认环节使用单字母快捷回复（`Y`=确认 / `N`=取消）：
- 🔵 clone: 一次确认 → `handler.py --action clone_vm ... --mask ... --gw ... --power_on` → `rename_vm` → `get_vm` 确认状态
- 🟡 power: 二次确认（含风险提醒）
- 🔴 delete: 二次确认 + 审批预留，`remove_vm()` 自动处理开机VM

> 确认机制详见 `references/PERMISSION-SYSTEM.md`，所有确认卡片末尾固定提示：`回复 Y 确认 / N 取消`

> 详细流程见 `references/CLONE-FLOW.md`，权限模板见 `references/PERMISSION-SYSTEM.md`

## 独立指令集

| 指令 | 命令 | 权限 |
|------|------|------|
| 巡检展示 | `cache_manager.py --refresh` + `--section xxx` | 🔵 |
| 查询VM | `handler.py --action get_vm --hostname "xxx"` | 🔵 |
| 电源 | `handler.py --action power_vm --hostname "xxx" --state on\|off\|reset` | 🟡 |
| 删除 | `handler.py --action delete_vm --hostname "xxx"` | 🔴 **必须指定名称/IP，禁止全量删除** |
| 快照 | `handler.py --action snapshot --hostname "xxx" --snap_action create --snap_name "xxx"` | 🔵 |
| 快照列表 | `handler.py --action snapshot --hostname "xxx" --snap_action list` | 🔵 |
| 快照恢复 | `handler.py --action snapshot --hostname "xxx" --snap_action revert --snap_name "xxx"` | 🔵 |
| 快照删除 | `handler.py --action snapshot --hostname "xxx" --snap_action delete --snap_name "xxx"` | 🟡 |
| 硬件热调整 | `handler.py --action reconfigure --hostname "xxx" --cpu 8 --memory 16 --disk 200` | 🔵 |
| Dry-Run | `handler.py --action <any> --dry-run ...` | 🔵 |
| 审计查询 | `handler.py --audit-query --action delete_vm --target xxx` | 🔵 |
| Guest 命令 | `handler.py --action guest_exec --hostname "xxx" --cmd "uptime" --guest-user root --guest-pwd xxx` | 🟡 |
| vMotion | `handler.py --action migrate --hostname "xxx" --target-host "esxi-02"` | 🟡 |
| 计划创建 | `handler.py --action plan --plan_action create --plan_steps '[...]' --plan_desc "..."` | 🔵 |
| 计划执行 | `handler.py --action plan --plan_action execute --plan_id "xxx"` | 🟡 |
| 计划回滚 | `handler.py --action plan --plan_action rollback --plan_id "xxx"` | 🟡 |
| 计划列表 | `handler.py --action plan --plan_action list` | 🔵 |
| 计划删除 | `handler.py --action plan --plan_action delete --plan_id "xxx"` | 🔵 |
| TTL 设置 | `handler.py --action ttl --ttl_action set --hostname "xxx" --ttl-minutes 60` | 🟡 |
| TTL 取消 | `handler.py --action ttl --ttl_action cancel --hostname "xxx"` | 🔵 |
| TTL 列表 | `handler.py --action ttl --ttl_action list` | 🔵 |
| TTL 清理 | `handler.py --action ttl --ttl_action cleanup` | 🟡 |
| 存储浏览 | `handler.py --action datastore --ds_name "datastore1" --ds_path "iso/"` | 🔵 |
| 镜像扫描 | `handler.py --action datastore --ds_scan --top 50` | 🔵 |
| 模板列表 | `handler.py --action template --tpl_action list` | 🔵 |
| 注册模板 | `handler.py --action template --tpl_action register --hostname "xxx" --tpl_name "yyy"` | 🟡 |
| 模板转VM | `handler.py --action template --tpl_action convert --hostname "xxx"` | 🟡 |
| 批量电源 | `handler.py --action batch --batch_action power --pattern "web-*" --state on` | 🟡 |
| 审批创建 | `handler.py --action approval --approval_action create --hostname "xxx"` | 🔵 |
| 审批通过 | `handler.py --action approval --approval_action approve --approval_id "xxx"` | 🟡 |
| 审批拒绝 | `handler.py --action approval --approval_action reject --approval_id "xxx"` | 🟡 |
| 审批列表 | `handler.py --action approval --approval_action list` | 🔵 |
| 审批取消 | `handler.py --action approval --approval_action cancel --approval_id "xxx"` | 🔵 |
| 事件查询 | `handler.py --action events --minutes 60 --event_category power` | 🔵 |
| 资源配额 | `handler.py --action quota --cluster "xxx" --cpu_threshold 0.85` | 🔵 |
| 导出清单 | `handler.py --action export --export_format json --cluster "xxx"` | 🔵 |
| 导出CSV | `handler.py --action export --export_format csv --output /tmp/vms.csv` | 🔵 |
| 导出Markdown | `handler.py --action export --export_format markdown --output /tmp/vms.md` | 🔵 |

展示后必须引导创建虚拟机。格式规范见 `references/RESOURCE-DISPLAY.md`

## 🔴 删除操作安全策略（强制）

> 详见 `references/PERMISSION-SYSTEM.md`「删除操作安全策略」章节。

**三条铁律，无条件执行：**

| # | 规则 | 说明 |
|---|------|------|
| 1 | **二次确认** | 所有删除动作必须两次 Y 确认才可执行 |
| 2 | **禁止全量删除** | "删除全部"、"删除所有VM"、"清空"等请求一律拒绝 |
| 3 | **必须指定明确目标** | 只接受精确的虚拟机名称或 IP，不接受通配符/正则/按条件筛选 |

> 适用关键词：删除、销毁、毁灭、移除、清除、delete、destroy、remove。适用对象不限于虚拟机。

## 决策规则

- 子网掩码/网关必填（非 255.255.255.0 环境）
- 存储标注 ⚠️ 低空间，宿主机排除维护模式
- 磁盘越界/重名自动拦截
- 操作前明确路径：`[DC]/[Cluster]`
- 删除操作严格执行安全策略，不得绕过

## 目录结构

```
vcenter-ops/
├── SKILL.md
├── config.yaml
├── .env                       # 密码（chmod 600，不入 git）
├── .gitignore
├── requirements.txt
├── scripts/
│   ├── client.py          # 连接层
│   ├── inventory.py       # 查询层（O(1) VM数统计）
│   ├── executor.py        # 动作层（克隆/重命名/电源/删除/快照/热调整）
│   ├── audit.py           # 审计日志（JSONL）
│   ├── ip_scanner.py      # IP 扫描
│   ├── cache_manager.py   # 会话缓存
│   ├── plan_manager.py    # 操作计划管理（多步编排）
│   ├── ttl_manager.py     # VM TTL 自动清理
│   ├── approval_manager.py # 操作审批管理
│   ├── event_watcher.py    # 事件监控查询
│   └── handler.py         # 接口层
├── logs/
│   └── audit.log          # 审计日志（自动生成，不入 git）
└── references/
    ├── DESIGN.md
    ├── CLONE-FLOW.md          # 克隆流程详解
    ├── CACHE-STRATEGY.md      # 缓存策略详解
    ├── RESOURCE-DISPLAY.md    # 展示格式规范
    └── PERMISSION-SYSTEM.md   # 权限控制模板
```
