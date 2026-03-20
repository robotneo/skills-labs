```yaml
name: vcenter-ops
description: VMware vCenter 运维自动化技能。支持全栈资源巡检、虚拟机生命周期管理（克隆/删除/规格更新/快照）。
  触发关键词：创建虚拟机、VM、VMWare vCenter、vCenter。
compatibility: Requires Python 3.10+
metadata:
  author: xiaofei
  version: 0.4.0

entrypoint: scripts/handler.py

input_schema:
  type: object
  required: [action]
  properties:
    action: { type: string, enum: [list_all, get_vm, clone_vm, delete_vm, power_vm] }
    hostname: { type: string, description: "虚拟机名称" }
    cpu: { type: number, default: 4 }
    memory: { type: number, default: 8, description: "单位 GB" }
    disk: { type: number, default: 100, description: "单位 GB" }
    ip: { type: string, description: "静态 IP 地址" }
    host_node: { type: string, description: "指定物理宿主机" }
    network: { type: string, description: "目标网络名称" }
    template: { type: string, description: "源模板名称" }
    dc: { type: string, description: "数据中心名称" }
    cluster: { type: string, description: "计算集群名称" }
    ds: { type: string, description: "存储池名称" }
```

---

## 📌 首次连接流程（必须遵守）

当用户首次触发本技能，先检查 `config.yaml` 是否已保存连接信息：

### Step 1: 检查 config.yaml

```bash
cat skills/vcenter-ops/config.yaml
```

检查 `vcenter.host` / `vcenter.user` / `vcenter.password` 是否非空。

### Step 2: 判断

- **任一为空** → 执行 Step 3
- **三项均非空** → 跳过，直接执行用户请求

### Step 3: 收集连接信息

一次性向用户询问：

```
请提供 vCenter 连接信息：
1. vCenter 地址（IP 或域名）
2. 用户名（如 administrator@vsphere.local）
3. 密码
```

### Step 4: 持久化到 config.yaml

收到回复后立即写入：

```yaml
vcenter:
  host: "用户提供的地址"
  user: "用户提供的用户名"
  password: "用户提供的密码"
  port: 443
```

### Step 5: 确认

```
✅ vCenter 连接信息已保存，后续操作将自动使用。
```

---

## 📛 命名规则

**VM 名称格式必须为 `IP-自定义名称`**，这是 vCenter 环境的统一命名规范。

- ✅ 正确：`172.17.40.2-TEST-VM-02`、`172.17.41.10-web-nginx-01`
- ❌ 错误：`TEST-VM-02`、`nginx01`（缺少 IP 前缀）

**Agent 处理流程：**
1. 收集参数时，用户只需提供"自定义名称"部分（如 `TEST-VM-02`）
2. IP 确定后，Agent 自动拼接为 `IP-名称` 格式
3. 在 Phase 4 确认阶段展示**最终名称**（含 IP 前缀）
4. 克隆执行时使用用户输入的原始名称（handler.py `--hostname`）
5. 克隆完成后调用 `executor.rename_vm()` 重命名为 `IP-名称` 格式

```python
# 重命名命令（克隆完成后执行）
executor.rename_vm("TEST-VM-02", "172.17.40.2-TEST-VM-02")
```

---

## 📋 克隆虚拟机前置流程（核心交互）

**用户请求克隆虚拟机时，必须按以下流程执行，禁止跳过巡检直接克隆。**

## ⚡ 会话缓存策略（核心优化）

**问题**：vCenter API 查询全量资源需 ~30 秒，且返回 250KB+ JSON，直接喂给模型消耗大量 token。

**解决方案**：首次查询时将全量数据保存到本地 JSON 文件，后续按需从缓存中提取指定字段。

### 缓存规则

| 场景 | 操作 | 耗时 | Token 消耗 |
|------|------|------|-----------|
| **首次查询**（会话内第一次） | 调用 API + 保存缓存 | ~30s | 仅摘要 |
| **后续查询**（读缓存） | 读取本地 JSON + 按需提取 | <1s | 仅提取字段 |
| **用户说"刷新"** | 重新调用 API + 更新缓存 | ~30s | 仅摘要 |
| **克隆/删除等写操作** | 直接调用 handler.py | 正常 | 正常 |

### Agent 执行流程

#### Step 1: 检查缓存

每次需要 vCenter 资源信息时，先检查缓存：

```bash
cd skills/vcenter-ops && python3 scripts/cache_manager.py --status
```

#### Step 2: 判断

- **缓存存在** → 跳到 Step 3 按需读取
- **缓存不存在** → 执行 Step 2a 刷新

#### Step 2a: 首次刷新（仅会话内第一次）

```bash
cd skills/vcenter-ops && python3 scripts/cache_manager.py --refresh
```

> 耗时约 30 秒，告诉用户"正在巡检 vCenter 环境，请稍候..."。

刷新完成后，**仅输出摘要信息**（不输出全量数据）：

```bash
cd skills/vcenter-ops && python3 scripts/cache_manager.py --summary
```

摘要输出示例（极低 token）：
```json
{"status":"ok","datacenters":["Datacenter"],"clusters":["MD1200","SC4020","共享存储","GPU","vSAN-A"],
"templates":8,"datastores":55,"networks":8,"hosts":{"total":45,"available":30,"maintenance":14},"vms":{"total":360}}
```

Agent 向用户展示：
```
✅ vCenter 巡检完成（缓存已保存）
  数据中心: 1 | 集群: 5 | 模板: 8 | 存储: 55 | 网络: 8
  宿主机: 30 可用 / 14 维护 | 虚拟机: 360 台
  缓存时间: 2026-03-20 18:30
```

#### Step 3: 按需读取（从缓存提取）

**按类别提取**（不查 API，直接读本地 JSON）：

```bash
# 模板列表
python3 scripts/cache_manager.py --section templates

# 存储列表（Top 10）
python3 scripts/cache_manager.py --section datastores --top 10

# 指定集群的宿主机
python3 scripts/cache_manager.py --section hosts --cluster "共享存储"

# 网络列表
python3 scripts/cache_manager.py --section networks

# VM IP（用于 IP 扫描排除）
python3 scripts/cache_manager.py --section vm_ips
```

**搜索 VM**（按名称/IP）：

```bash
python3 scripts/cache_manager.py --search "nginx"
```

### 关键规则

1. **会话级缓存**：缓存文件 `/tmp/vc_session_cache.json` 在会话内有效，`/new` 新会话不保留
2. **不自动过期**：缓存不会自动失效，只有用户明确说"刷新"才重新查 API
3. **写操作不受影响**：克隆/删除/电源管理等写操作仍直接调用 handler.py
4. **数据一致性**：如果会话内执行了克隆/删除操作，建议提示用户"数据已变更，建议刷新缓存"
5. **按需提取减少 token**：Agent 只读取需要的字段，不加载全量 250KB JSON 到上下文

### 缓存文件

| 文件 | 路径 | 用途 |
|------|------|------|
| 全量数据 | `/tmp/vc_session_cache.json` | 250KB，包含全部 VM/宿主机/存储等 |
| 元信息 | `/tmp/vc_session_meta.json` | 缓存时间、统计摘要 |

---

### Phase 1: 资源巡检（使用会话缓存）

按「会话缓存策略」章节执行：
1. 检查缓存（`cache_manager.py --status`）
2. 无缓存 → `--refresh` 刷新 → 输出摘要
3. 有缓存 → `--summary` 输出摘要

> 不再直接调用 `handler.py --action list_all`，改用 `cache_manager.py` 缓存机制。

后续 Phase 2 展示资源时，按需调用 `cache_manager.py --section xxx` 从缓存读取。

### Phase 2: 整理参数清单

从巡检结果中提取以下信息，**分三组展示给用户**：

#### 🔵 第一组：核心业务参数（必选）

```
🔵 核心业务参数
┌──────────┬─────────────────────────────────────┐
│ 参数     │ 可选项                               │
├──────────┼─────────────────────────────────────┤
│ 数据中心 │ [DC-01]                              │
│ 集群     │ [Cluster-A, Cluster-B]              │
│ 模板     │ [CentOS-7-Temp, Ubuntu-22-Temp]     │
│ 存储池   │ [DS-NAS-01 ⚠️空间不足, DS-SSD-01]   │
│ 网络     │ [VM-Network, VM-DB-Network]         │
│ VM名称   │ （必填，请指定）                      │
└──────────┴─────────────────────────────────────┘
```

**说明**：
- 存储池需标注 `is_low_space` 告警
- 模板从巡检结果的 `templates` 列表中提取
- 网络从 `networks` 列表中提取

#### 🟢 第二组：硬件与宿主机调度参数

**在展示此组之前，必须先基于巡检结果计算宿主机评分：**

从 `list_all` 返回的 `hosts` 列表中筛选可用宿主机，调用评分模型：

```
评分模型: Score = CPU空闲率 × 0.40 + 内存空闲率 × 0.35 + 负载均衡因子 × 0.25

负载均衡因子 = (最大VM数 - 当前VM数) / 最大VM数 × 100

排除规则:
  ❌ 维护模式 (maintenance_mode=true)
  ❌ 未开机 (power_state≠poweredOn)
  ❌ 状态异常 (status≠green)
```

**展示 Top5 推荐列表：**

```
🟢 宿主机调度（自动评分推荐 Top5）
┌────┬──────────────┬────────┬──────────┬────────┬──────┬─────────┐
│ #  │ 宿主机       │ 集群   │ CPU空闲% │ MEM空闲%│ VM数  │ Score   │
├────┼──────────────┼────────┼──────────┼────────┼──────┼─────────┤
│ ⭐1│ esxi-02      │ Cls-A  │ 80%      │ 70%     │ 12    │ 76.50   │
│  2 │ esxi-05      │ Cls-A  │ 65%      │ 75%     │ 15    │ 70.75   │
│  3 │ esxi-01      │ Cls-A  │ 60%      │ 55%     │ 18    │ 58.75   │
│  4 │ esxi-03      │ Cls-B  │ 50%      │ 80%     │ 20    │ 56.00   │
│  5 │ esxi-04      │ Cls-B  │ 45%      │ 60%     │ 25    │ 51.25   │
└────┴──────────────┴────────┴──────────┴────────┴──────┴─────────┘
❌ 排除: esxi-06 (维护模式), esxi-07 (未开机)

请选择:
  1. 输入编号（如"1"）选择推荐宿主机
  2. 直接指定其他宿主机名称
  3. 输入"自动"使用第1名（⭐最优）
  4. 不选 → 由集群 DRS 自动调度
```

**硬件参数（可选，使用 config.yaml 默认模板值）：**

```
┌──────────┬────────────────┐
│ 参数     │ 默认值          │
├──────────┼────────────────┤
│ CPU      │ 默认: 4 核      │
│ 内存     │ 默认: 8 GB      │
│ 磁盘     │ 默认: 100 GB    │
└──────────┴────────────────┘
```

**宿主机展示规则：**
- 默认展示 **用户选择的集群** 下的宿主机列表（含评分和 VM 数）
- 用户回复"全部"或"其他集群"时，展示全量 Top10（跨集群）
- 宿主机列表必须包含 VM 数（通过 `_moId` 匹配，而非 Python `id()`）

**优先级规则：**
- 用户直接指定宿主机名称 → 最高优先级
- 用户选择推荐列表编号 → 使用对应宿主机
- 用户选择"自动" → 不指定 host_node，由集群 DRS 自动调度
- 用户不选 → 同"自动"

> ⚠️ **VM 数统计说明**：`inventory.py` 通过预构建 `_moId` 字典实现 O(1) 查找，
> 一次遍历缓存所有对象引用，避免 ContainerView 多次遍历导致 Python 对象 id 失效。

#### 🟡 第三组：IP 地址选择（可选）

**在展示此组之前，必须先执行 IP 网段扫描：**

```bash
cd skills/vcenter-ops && python3 scripts/ip_scanner.py --cidr 172.17.40.0/23 --use-cache
```

**参数说明：**
- `--cidr`：扫描网段（默认 `172.17.40.0/23`，可更换）
- `--exclude-file`：排除 IP 文件路径（每行一个 IP）
- `--exclude-ips`：排除 IP 逗号分隔列表
- `--check IP`：快速检测单个 IP 是否可用
- `--use-cache`：优先使用 30 分钟内缓存

**从扫描结果中提取可用 IP 列表展示：**

```
🟡 IP 地址（来自 172.17.40.0/23 扫描）
┌──────────────┬────────┬─────────────┐
│ IP 地址      │ 状态   │ 延迟        │
├──────────────┼────────┼─────────────┤
│ 172.17.40.3  │ ✅ 可用│ 0.4ms       │
│ 172.17.40.5  │ ✅ 可用│ 0.4ms       │
│ 172.17.40.7  │ ✅ 可用│ 0.5ms       │
│ ...          │        │             │
└──────────────┴────────┴─────────────┘
可用: 256 个 | 已占用: 256 个 | 扫描时间: 2026-03-20 14:22
```

**网络自定义参数：**
```
┌──────────┬────────────────────┐
│ 参数     │ 说明               │
├──────────┼────────────────────┤
│ IP 地址  │ 从上方列表选择或直接指定 │
│ 子网掩码 │ 必须指定（如 255.255.254.0）│
│ 网关     │ 必须指定（如 172.17.40.1）│
│ 扫描网段 │ 默认: 172.17.40.0/23（可更换）│
└──────────┴────────────────────┘
```

**说明**：
- 不填 IP 则跳过网络注入，VM 开机后需手动配置
- 用户直接指定 IP 时，必须先用 `--check` 验证该 IP 是否可用
- 更换网段：执行 `python3 scripts/ip_scanner.py --cidr 10.0.0.0/24` 即可
- 后续将对接独立的钉钉文档 IP 管理 SKILL 替代本扫描模块

### Phase 3: 参数确认与交互选择

**核心原则：用户提供了多少参数就用多少，缺什么交互问什么，全程用编号列表供用户选择。**

#### 三种场景判断

**场景 A — 全量参数（直接创建）**

触发条件：用户一句话包含所有关键信息。

示例："名称 TEST-01，集群 vSAN-A，模板 3(CentOS)，存储 vsanDatastore，网络 yewu，4C8G100G，IP 172.17.40.10"

处理：提取全部参数 → Phase IP 验证 IP → Phase 4 列出最终确认 → 执行。**跳过交互选择。**

**场景 B — 部分参数（只问缺失项）**

触发条件：用户提供了名称 + 规格 + IP，但缺少集群/模板/存储/网络。

示例："创建 TEST-01，4C8G，IP 用 172.17.40.10"

处理：先确认已提取的参数，再对每个缺失项展示编号列表让用户选择：

```
已确认：
  ✅ VM名称: TEST-01
  ✅ CPU: 4核  内存: 8GB  磁盘: 100GB
  ✅ IP: 172.17.40.10（待验证）

请选择以下参数（可一次回复，如"集群5，模板3，存储4，网络1"）：

🏗️ 集群
  1. MD1200
  2. SC4020
  3. 共享存储
  4. GPU
  5. vSAN-A

📦 模板
  1. Ubuntu20.04-2c4g60g-lvm2 | Ubuntu 2C/4G/60G
  2. SC5020U24042c4g30g   | Ubuntu 2C/4G/30G
  3. Centos7.9_2c4g60glvm  | CentOS 7 2C/4G/60G
  4. win10ent4c8g60g       | Windows 10 4C/8G/60G
  ...

💾 存储
  1. vsanDatastore  | 29.8TB 可用 14.4TB (48.3%) ✅
  2. 5020-A         | 30TB 可用 17.5TB (56.8%) ✅
  ...

🌐 网络
  1. yewu
  2. VM Network
  3. 虚拟机网络
  ...
```

用户回复编号后，汇总所有参数进入 Phase 4 确认。

**场景 C — 零参数（逐项引导）**

触发条件：用户只说"创建虚拟机"或"克隆虚拟机"，没有具体信息。

处理：巡检后，逐项展示编号列表引导用户选择：

```
收到！我来帮你创建虚拟机，请逐项选择或一次回复多个编号。

📦 先选模板（克隆的基础）：
  1. Ubuntu20.04-2c4g60g-lvm2 | Ubuntu 2C/4G/60G
  2. SC5020U24042c4g30g   | Ubuntu 2C/4G/30G
  3. Centos7.9_2c4g60glvm  | CentOS 7 2C/4G/60G
  4. win10ent4c8g60g       | Windows 10 4C/8G/60G
  5. win11ent4c8g60g       | Windows 11 4C/8G/60G
  ...

请回复模板编号（如 3）：
```

用户选模板后，继续选集群 → 存储 → 网络 → 名称 → 规格 → IP，每一步都展示编号列表。

#### 交互规则

1. **编号选择优先**：每个可选项必须带编号，用户回复编号即可
2. **支持批量回复**：用户可以一次回复多个编号，如"集群5，模板3，存储4，网络1"
3. **自动填充**：当某类资源仅 1 个时自动选中，不展示
4. **存储空间标注**：低空间存储标注 ⚠️
5. **参数汇总确认**：所有参数确定后，列出完整清单请用户最终确认

#### 智能匹配规则

| 用户说法 | 匹配结果 |
|---------|---------|
| "CentOS 模板" / "用 CentOS" | 模糊匹配模板名称 |
| "8核16G" / "8C16G" | CPU=8, 内存=16GB |
| "200G硬盘" / "磁盘200" | 磁盘=200GB |
| "放到 vSAN-A" / "在A集群" | 集群=vSAN-A |
| "用 SSD 存储" | 模糊匹配存储名称 |
| "分配 IP 172.17.40.10" | IP=172.17.40.10 |
| "放到 172.17.43.35 上" | 宿主机=172.17.43.35 |
| "全部默认" / "快速创建" | 仅 VM名称必填，其余用默认值 |

### Phase IP: 网络配置（IP 必填）

**克隆虚拟机时，IP 地址和网络注入为必填项，不可跳过。**

#### IP 可用性判断规则

**可用 IP = Ping 不通 + 非 vCenter 任何 VM 使用（含关机 VM）**

三重过滤逻辑：
1. 对指定网段执行 Ping 扫描，筛选出 **Ping 不通**的 IP（ping 通 = 已占用）
2. 收集 **vCenter 全部 VM 的 IP 地址**（不区分集群），来源包括：
   - `guest.ipAddress`：VMware Tools 正常运行的 VM（包括开关机状态）
   - `_extract_vm_ips()`：从 `guest.net` 网卡信息提取（兼容 Tools 未正常上报的情况）
   - **VM 名称提取**：从 VM 命名规则 `IP-名称` 中提取 IP（如 `172.17.40.12-uat-srm` → `172.17.40.12`）
3. 从 Ping 不通的 IP 中 **排除全部 VM IP**（跨集群排除，因为不同集群可能共用网段）
4. 剩余 IP 按 **从小到大排序**，作为可分配列表

> **为什么排除全 vCenter 而非单个集群？** 不同集群的 VM 可能使用同一网段，仅排除目标集群会遗漏其他集群已占用的 IP。
> **为什么从 VM 名称提取 IP？** 关机 VM 的 `guest.ipAddress` 和 `guest.net` 均可能为空，但 IP 已记录在 VM 名称中（命名规范 `IP-名称`）。

#### Step 1: 收集 vCenter 全部 VM 的 IP

从 Phase 1 巡检结果中，提取 **整个 vCenter 下所有 VM 的 IP 地址**（不区分集群），三个来源：

Agent 在内存中过滤：
```python
import re

vm_ips = set()
ip_pattern = re.compile(r"^(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")

for vm in inventory["vms"]:
    # 来源 1: guest.ipAddress（inventory.py 已通过 _extract_vm_ips 增强）
    ip = vm["runtime"]["ip_address"]
    if ip and ip != "N/A":
        vm_ips.add(ip)

    # 来源 2: 从 VM 名称提取 IP（兼容关机 VM，如 172.17.40.12-uat-srm）
    name = vm["metadata"]["name"]
    m = ip_pattern.match(name)
    if m:
        vm_ips.add(m.group(1))

# 写入临时文件，通过 --exclude-file 传入（避免命令行参数过长）
with open("/tmp/exclude_ips.txt", "w") as f:
    for ip in sorted(vm_ips):
        f.write(ip + "\n")

print(f"收集到 {len(vm_ips)} 个 vCenter VM IP（含关机 VM）")
```

> - 排除全 vCenter VM IP 而非单个集群，因为不同集群的 VM 可能共用同一网段。
> - 关机 VM 通过 VM 名称提取 IP（命名规范 `IP-名称`），确保已分配但未运行的 IP 不会被误分配。

#### Step 2: 扫描网段并排除已有 IP

```bash
cd skills/vcenter-ops && python3 scripts/ip_scanner.py --cidr 172.17.40.0/23 --exclude-file /tmp/exclude_ips.txt
```

**参数说明：**
- `--cidr`：扫描网段（默认 `172.17.40.0/23`，可更换）
- `--exclude-file`：排除 IP 文件路径（每行一个 IP，避免命令行参数过长）
- `--exclude-ips`：排除 IP 逗号分隔列表（少量 IP 时可用）
- `--check IP`：快速检测单个 IP 是否可用

#### Step 2: 展示可用 IP 列表

从扫描结果的 `available` 列表中提取，按 IP 末位排序展示：

```
📡 网络配置（必填）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
网段: 172.17.40.0/23
扫描时间: 2026-03-20 14:22

可用 IP 列表:
┌──────────────┬────────┐
│ 172.17.40.3  │ ✅ 0.4ms│
│ 172.17.40.5  │ ✅ 0.4ms│
│ 172.17.40.7  │ ✅ 0.5ms│
│ 172.17.40.9  │ ✅ 0.4ms│
│ 172.17.40.10 │ ✅ 0.4ms│
│ ...          │        │
│ 共 256 个可用 IP                    │
└──────────────┴────────┘

子网掩码: 255.255.255.0（默认，可改）
网关: （建议填写，如 172.17.40.1）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

#### Step 3: 用户选择 IP（三种方式）

**方式 1 — 自动推荐（最快）**

Agent 从可用列表中选取**前 3 个最小 IP**，推荐用户确认：

```
💡 自动推荐（从小到大 Top3）:
  1. 172.17.40.2  ⭐推荐
  2. 172.17.40.3
  3. 172.17.40.4

回复"1"使用推荐 IP，或指定其他。
```

**方式 2 — 从列表选择**

用户从展示的可用 IP 列表中指定一个。

```
用户: "用 172.17.40.10"
Agent: ✅ 已选择 172.17.40.10（可用，延迟 0.4ms）
```

**方式 3 — 用户直接指定 IP**

用户指定一个不在列表中的 IP，Agent **必须**先执行检测：

```bash
cd skills/vcenter-ops && python3 scripts/ip_scanner.py --check 172.17.40.200
```

检测结果处理：

| Ping 结果 | 集群 VM 是否使用 | 最终决策 |
|-----------|-----------------|---------|
| 不通 | 未使用 | ✅ 可分配 |
| 不通 | 已被 VM 使用 | ❌ 排除，提示换一个 |
| 通 | — | ❌ 已占用，拒绝分配 |

```
用户: "IP 用 172.17.40.200"
Agent: 正在检测 172.17.40.200...
       ❌ 该 IP 已被占用（延迟 0.5ms），请选择其他 IP 或从可用列表中选取。
```

#### Step 4: 确认网关（可选但建议）

```
IP: 172.17.40.3 ✅
子网掩码: 255.255.255.0
网关: 请提供网关地址（如 172.17.40.1），或不填跳过
```

#### Step 5: IP 确认完成

```
✅ 网络配置完成
  IP: 172.17.40.3
  掩码: 255.255.255.0
  网关: 172.17.40.1

进入最终确认...
```

### Phase 4: 根据权限级别确认与执行

**根据操作类型匹配权限级别（读取 `config.yaml` 中 `permission.action_map`）：**

| 级别 | 操作 | 流程 |
|------|------|------|
| **confirm** | clone_vm / get_vm / list_all / snapshot | 列出参数 → 一次确认 → 执行 |
| **double_confirm** | power_vm | 列出参数 → 一次确认 → 风险提醒 → 二次确认 → 执行 |
| **approval** | delete_vm | 列出参数 → 一次确认 → 风险提醒 → 二次确认 → 执行（预留审批接口） |

#### 🔵 Level: confirm（普通操作）

适用于：克隆/创建虚拟机、查询、巡检、快照

```
📋 克隆计划确认
━━━━━━━━━━━━━━━━━━━━
名称: 172.17.40.5-PROD-WEB-05
模板: CentOS-7-Temp
位置: DC-01 / Cluster-A / DS-SSD-01
网络: VM-Network
规格: 4C / 8GB / 100GB
宿主机: esxi-02 (Score: 69.5)
IP: 172.17.40.5 / 255.255.254.0 / 172.17.40.1
━━━━━━━━━━━━━━━━━━━━
权限级别: 🔵 普通操作（确认即可）
确认执行？（回复"确认"开始克隆）
```

用户回复"确认"后执行克隆：

1. 调用 `handler.py --action clone_vm --hostname "原始名称"` 执行克隆
2. 克隆成功后调用 `executor.rename_vm("原始名称", "IP-原始名称")` 重命名
3. 输出最终结果，包含重命名后的名称

#### 🟡 Level: double_confirm（敏感操作）

适用于：电源管理（开/关/重启）

```
📋 电源操作确认
━━━━━━━━━━━━━━━━━━━━
目标: PROD-DB-01
当前状态: poweredOn
操作: 关机 (off)
━━━━━━━━━━━━━━━━━━━━
权限级别: 🟡 敏感操作（需二次确认）

第一次确认: 确认要对 PROD-DB-01 执行关机？（回复"确认"）
```

用户第一次确认后，**必须**输出风险提醒：

```
⚠️ 风险提醒
━━━━━━━━━━━━━━━━━━━━
操作: 关闭 PROD-DB-01
风险: 该虚拟机上的所有业务将中断，请确认已通知相关方
影响: 连接该 VM 的用户将断开连接
回滚: 可通过 power_vm --state on 重新开机
━━━━━━━━━━━━━━━━━━━━

第二次确认: 了解风险，确定执行？（回复"确认执行"）
```

用户第二次确认后才执行。

#### 🔴 Level: approval（高风险操作）

适用于：删除虚拟机

```
📋 删除操作确认
━━━━━━━━━━━━━━━━━━━━
目标: PROD-OLD-01
位置: DC-01 / Cluster-A / esxi-01
规格: 4C / 8GB / 100GB
━━━━━━━━━━━━━━━━━━━━
权限级别: 🔴 高风险操作（需二次确认 + 审批）

第一次确认: 确认要永久删除 PROD-OLD-01？（回复"确认"）
```

用户第一次确认后，输出风险提醒：

```
⚠️ 风险提醒
━━━━━━━━━━━━━━━━━━━━
操作: 永久删除 PROD-OLD-01（不可恢复）
风险: 所有数据将永久丢失，包括磁盘、快照、配置
影响: 该虚拟机将从 vCenter 清单中完全移除
回滚: ❌ 不可回滚（除非有外部备份）
━━━━━━━━━━━━━━━━━━━━

📌 当前审批状态: 审批接口待接入（自动跳过）
后续将对接审批系统，届时需等待审批通过后方可执行。

第二次确认: 了解以上风险，确定删除？（回复"确认删除"）
```

用户第二次确认后执行：
1. Agent 调用 `handler.py --action delete_vm --hostname "VM名称"`
2. `remove_vm()` 自动检测 VM 电源状态：
   - **开机** → 自动先关机（PowerOff）→ 再删除（Destroy）
   - **关机** → 直接删除
3. 独立的电源管理操作（`power_vm`）不受影响，用户仍可单独执行开/关/重启

> **审批接口预留**：config.yaml 中 `approval` 级别的操作已预留审批钩子。
> 后续接入 JumpServer / 钉钉审批 / 自建审批系统时，在第二次确认前插入审批流程即可。
> 当前版本 Agent 需在输出中明确标注"审批接口待接入"。

---

## 📋 独立指令集

### 资源巡检与展示（实时查询）

**触发条件：** 用户要求展示/查看 vCenter 下的资源信息（模板、存储、网络、集群等）。

**Agent 必须：实时调用脚本查询，禁止使用历史缓存数据。**

#### Step 1: 检查缓存并巡检

```bash
# 先检查缓存
cd skills/vcenter-ops && python3 scripts/cache_manager.py --status
```

- **有缓存** → 直接从缓存读取（跳到 Step 2）
- **无缓存** → 执行刷新：

```bash
cd skills/vcenter-ops && python3 scripts/cache_manager.py --refresh
```

> 首次巡检耗时约 30 秒，请先告知用户"正在巡检 vCenter 环境，请稍候..."。
> 后续查询从缓存读取，<1 秒完成。

**用户说"刷新"时**，强制重新查询 API 更新缓存。

#### #### Step 2: 识别用户意图，按需展示

从缓存中提取，**按用户要求选择性展示**（不查 API，<1s）：

| 用户说 | 展示内容 | JSON 路径 |
|--------|---------|----------|
| "展示全部" / "巡检" / "列出信息" | 全部资源 | 完整 data |
| "模板" / "克隆模板" | 仅模板 | `data.templates[]` |
| "存储" / "存储池" | 仅存储 | `data.datastores[]` |
| "网络" | 仅网络 | `data.networks[]` |
| "集群" / "计算集群" | 仅集群 | `data.clusters[]` |
| "数据中心" | 仅数据中心 | `data.datacenters[]` |
| "宿主机" | 宿主机评分 | `data.hosts[]` |

**未指定类别时，默认展示全部资源信息。**

#### Step 3: 格式化输出规范

##### 全部展示格式

```
📁 数据中心
  - Datacenter

🏗️ 计算集群
  - MD1200
  - SC4020
  - vSAN-A

📦 克隆模板
| # | 名称 | 系统 | 规格 |
|---|------|------|------|
| 1 | Ubuntu20.04-2c4g60g-lvm2 | Ubuntu 64-bit | 2C/4G/60G |
| 2 | Centos7.9_2c4g60glvm | CentOS 7 64-bit | 2C/4G/60G |
...

💾 存储池（主要）
| # | 名称 | 总容量 | 可用 | 可用率 |
|---|------|-------|------|-------|
| 1 | vsanDatastore | 29.8TB | 14.4TB | 48.3% ✅ |
| 2 | 5020-A | 30TB | 17.5TB | 56.8% ✅ |
...
> 共 N 个存储池，其余多为各宿主机本地数据盘。

🌐 网络
| # | 名称 |
|---|------|
| 1 | yewu |
| 2 | VM Network |
...
```

##### 单类展示格式

用户只问某一类时，**只输出该类别，不加其他区块**。同样使用表格格式。

示例 — 用户说"看看模板"：
```
📦 克隆模板
| # | 名称 | 系统 | 规格 |
|---|------|------|------|
| 1 | Ubuntu20.04-2c4g60g-lvm2 | Ubuntu 64-bit | 2C/4G/60G |
| 2 | Centos7.9_2c4g60glvm | CentOS 7 64-bit | 2C/4G/60G |
...
```

示例 — 用户说"存储池有哪些"：
```
💾 存储池
| # | 名称 | 总容量 | 可用 | 可用率 |
|---|------|-------|------|-------|
| 1 | vsanDatastore | 29.8TB | 14.4TB | 48.3% ✅ |
...
```

#### Step 4: 展示后引导创建虚拟机

资源信息展示完毕后，Agent **必须**追加以下提示引导用户进入克隆流程：

```
---

需要创建虚拟机？请提供以下信息：

  名称: TEST-VM-01（自定义）
  集群: vSAN-A / MD1200 / SC4020 / GPU / 共享存储
  模板: 编号或名称（如 3 = Centos7.9）
  存储: vsanDatastore / 5020-A / ...
  网络: yewu / VM Network / ...
  硬件: CPU/内存/磁盘（默认 4C/8G/100G，可改）

示例回复：
  "名称 TEST-VM-01，集群 vSAN-A，模板 3，存储 vsanDatastore，网络 yewu"
```

#### 关键规则

- 存储池 `is_low_space=true` 必须标注 ⚠️
- 宿主机必须按评分模型排序，展示 Top5
- 本地数据盘（500GB 级别、以 IP 开头如 43.x-data）合并为"其余为各宿主机本地数据盘，空间充足"
- 展示完毕后必须引导创建虚拟机
- 模板、存储、网络必须使用编号表格，方便用户用编号回复

---

### 查询单个虚拟机

```bash
python3 scripts/handler.py --action get_vm --hostname "VM名称"
```

### 电源管理（🟡 敏感 - 二次确认）

```bash
python3 scripts/handler.py --action power_vm --hostname "VM名称" --state on|off|reset
```

### 删除虚拟机（🔴 高风险 - 二次确认 + 预留审批）

```bash
python3 scripts/handler.py --action delete_vm --hostname "VM名称"
```

---

## 🛡️ 权限控制体系

### 三级权限模型

| 级别 | 标识 | 操作 | 确认次数 | 审批 |
|------|------|------|---------|------|
| **confirm** | 🔵 普通 | clone_vm, get_vm, list_all, snapshot | 1 次 | 无 |
| **double_confirm** | 🟡 敏感 | power_vm | 2 次 | 无 |
| **approval** | 🔴 高风险 | delete_vm | 2 次 | 预留接口 |

### 权限配置来源

权限定义存储在 `config.yaml` 的 `permission` 节点，Agent 读取后按级别执行对应确认流程。

### 审批接口预留

`approval` 级别操作预留审批钩子，后续可接入：
- JumpServer 工单系统
- 钉钉 OA 审批
- 自建审批 API

接入方式：在二次确认后、执行前调用审批接口，等待审批通过后执行。当前版本自动跳过。

## 🚦 决策规则

📐 IP 分配矩阵（三重过滤）

| Ping 结果 | vCenter VM 使用 | 最终决策 | 动作 |
|-----------|----------------|----------|------|
| 不通 | 未使用 | ✅ 可分配 | 推荐给用户 |
| 不通 | 已被 VM 使用 | ❌ 排除 | 从可用列表移除 |
| 通 | — | ❌ 已占用 | 拒绝分配 |

> IP 注入为克隆必填项，Agent 必须在 Phase IP 中完成 IP 选择和检测。
> 后续将对接独立的钉钉文档 IP 管理 SKILL，实现文档状态 + Ping 双重校验。

- 🔵 普通操作：一次确认即可执行
- 🟡 敏感操作：必须二次确认，第一次确认后必须输出风险提醒
- 🔴 高风险操作：二次确认 + 风险提醒 + 明确标注"不可回滚"
- 📏 磁盘越界、重名等场景自动拦截
- 🔒 config.yaml 明文密码，注意文件权限
- ✅ 克隆前必须经过 Phase 1~4 完整流程
- 📐 用户指定 IP 时必须先 `--check` 验证可用性


## 💬 沟通准则

- 操作前明确路径：`正在 [DC-01]/[Cluster-A] 执行操作`
- 降维解释：Datastore → 存储池，Snapshot → 快照点
- 原子性：所有参数校验通过后才下发指令

---

## 📂 目录结构

```
vcenter-ops/
├── SKILL.md                # 技能描述（本文件）
├── config.yaml             # vCenter 连接信息 + 默认参数
├── requirements.txt        # Python 依赖（pyvmomi）
├── assets/                 # 配置模板
├── scripts/
│   ├── client.py           # 连接层
│   ├── inventory.py        # 查询层
│   ├── executor.py         # 动作层（克隆/重命名/电源/删除/快照）
│   ├── ip_scanner.py       # IP 网段扫描与 Ping 检测
│   └── handler.py          # 接口层
└── references/
    ├── DESIGN.md           # 设计规范
    └── REFERENCE.md        # 术语解释
```
