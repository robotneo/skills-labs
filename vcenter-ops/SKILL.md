---
name: vcenter-ops
description: VMware vCenter 运维自动化。克隆/删除/电源/快照/资源巡检。
  触发词：创建虚拟机、VM、vCenter、巡检、克隆。
metadata:
  version: 0.5.0
entrypoint: scripts/handler.py
input_schema:
  type: object
  required: [action]
  properties:
    action: { type: string, enum: [list_all, get_vm, clone_vm, delete_vm, power_vm, snapshot] }
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
---

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

**Phase 4 执行** → 三级权限确认后执行：
- 🔵 clone: 一次确认 → `handler.py --action clone_vm ... --mask ... --gw ... --power_on` → `rename_vm` → `get_vm` 确认状态
- 🟡 power: 二次确认（含风险提醒）
- 🔴 delete: 二次确认 + 审批预留，`remove_vm()` 自动处理开机VM

> 详细流程见 `references/CLONE-FLOW.md`，权限模板见 `references/PERMISSION-SYSTEM.md`

## 独立指令集

| 指令 | 命令 | 权限 |
|------|------|------|
| 巡检展示 | `cache_manager.py --refresh` + `--section xxx` | 🔵 |
| 查询VM | `handler.py --action get_vm --hostname "xxx"` | 🔵 |
| 电源 | `handler.py --action power_vm --hostname "xxx" --state on\|off\|reset` | 🟡 |
| 删除 | `handler.py --action delete_vm --hostname "xxx"` | 🔴 |
| 快照 | `handler.py --action snapshot --hostname "xxx"` | 🔵 |

展示后必须引导创建虚拟机。格式规范见 `references/RESOURCE-DISPLAY.md`

## 决策规则

- 子网掩码/网关必填（非 255.255.255.0 环境）
- 存储标注 ⚠️ 低空间，宿主机排除维护模式
- 磁盘越界/重名自动拦截
- 操作前明确路径：`[DC]/[Cluster]`

## 目录结构

```
vcenter-ops/
├── SKILL.md
├── config.yaml
├── requirements.txt
├── scripts/
│   ├── client.py          # 连接层
│   ├── inventory.py       # 查询层（O(1) VM数统计）
│   ├── executor.py        # 动作层（克隆/重命名/电源/删除/快照）
│   ├── ip_scanner.py      # IP 扫描
│   ├── cache_manager.py   # 会话缓存
│   └── handler.py         # 接口层
└── references/
    ├── DESIGN.md
    ├── CLONE-FLOW.md          # 克隆流程详解
    ├── CACHE-STRATEGY.md      # 缓存策略详解
    ├── RESOURCE-DISPLAY.md    # 展示格式规范
    └── PERMISSION-SYSTEM.md   # 权限控制模板
```
