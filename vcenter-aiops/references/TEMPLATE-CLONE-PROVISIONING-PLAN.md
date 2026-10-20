# 基于模板克隆创建虚拟机 —— 完整设计与落地方案

> 适用版本：vcenter-aiops 3.0.0b6（execution-beta）。统一入口原子命令 `deploy clone-template`（对齐 vcenter-ops 2.0 克隆模版标准流程）。
> 本文所有命令均以当前注册的 112 条命令真实签名为准；所有远端写都走"预览出固定计划 → 二次确认 → plan apply → task/wait 核对"，不直接生效、不自动重发。
> 最后更新：2026-10-19。

---

## 0. 能力边界（先读，避免误用）

| 事项 | 系统真实行为 | 对方案的影响 |
|---|---|---|
| 创建路径 | **统一走 `deploy clone-template`**（用户既定规则：新建/克隆 VM 不用 `vm clone`/`deploy template`） | 两条路线共用同一条命令，仅参数不同 |
| 开关机 | **给 `ip_address` 即开机并下发 Linux 定制；省略则克隆为关机 VM** | 路线一=省略 IP 的关机定制；路线二可关机可开机 |
| 磁盘 | `disk_gb` **只能大于模板首盘当前值（仅扩容，不能缩容）** | "标准 100GB"要求源模板首盘 ≤100GB；更大的盘无法缩到 100 |
| 客户机定制 | 写死 `LinuxPrep`：单网卡静态 IP/掩码/网关/域(`guest_domain`)；**不下发 DNS、不支持 Windows、不支持 DHCP/多网卡** | Windows 或需 DNS/DHCP/多网卡的场景走"关机克隆 → 开机后手工/配置管理"路线 |
| IP 池 / VLSM | 工具**无内置 CIDR 池与自动子网划分**；`ip` 子系统是"`scope` 字符串 + 单 IP 三路信号 + 本地租约" | VLSM 网段规划在**规划层**完成（本方案第 2 章），工具负责逐 IP 空闲取证与占用登记 |
| 网络对象 | 无 `network list` 命令；`network_id` 接受标准网络 `network-N` 或分布式端口组 `dvportgroup-N` | 改网需已知精确网络 ID；省略 `network_id` 则保留模板网卡 |
| 主机放置 | `host_id` 省略 → 集群 DRS 自动选主机；指定则校验主机∈资源池同一计算资源、已连接、非维护、且能见到所选存储/网络 | 默认推荐省略 host_id 走 DRS |
| 风险级别 | `deploy clone-template` 为 `risk=change`（非销毁类） | `plan apply` 只需 `--confirm <digest>` 一把确认，**不需要** `--confirm-destruction` |
| 成功语义 | 克隆任务 success 仅代表 VM 已创建/已提交定制；IP/Tools 就绪须再用 `vm wait-tools`/`task wait` 核对 | 开机定制路线必须有"就绪核对"步骤，不假定已就绪 |

---

## 1. 两条路线总览与选择逻辑

```
                    ┌─────────────────────────────────────┐
                    │  新建 VM 需求（基于模板克隆）          │
                    └───────────────┬─────────────────────┘
                                    │
                  目标放置/模板/IP 是否已知且确定？
                                    │
              ┌─────────────────────┴──────────────────────┐
             已知                                        不确定 / 新环境
              │                                           │
   ┌──────────▼──────────┐                   ┌────────────▼─────────────┐
   │ 路线一：关机定制创建  │                   │ 路线二：盘点选择后创建      │
   │ （默认 / 幂当首选）   │                   │ （先 inventory 再决策）    │
   ├──────────────────────┤                   ├──────────────────────────┤
   │ 省略 ip_address       │                   │ ① profile test            │
   │ 克隆即 poweredOff     │                   │ ② 盘点 集群/池/主机        │
   │ CPU/内存/盘/网卡       │                   │    模板 / 数据存储 / 网络   │
   │ 在克隆 spec 中改配     │                   │ ③ VLSM 选网段 + 逐 IP 取证 │
   │ 不依赖 Tools/定制      │                   │ ④ 选定后进入路线一或开机定制 │
   │ 最稳、跨 OS 通用       │                   │ ⑤ 确认 → apply → 就绪核对  │
   └──────────┬───────────┘                   └──────────────────────────┘
              │ 后续需要联网/IP
              ▼
   开机后由配置管理 / 手工配网，或单独走"开机静态 IP 定制"（仅 Linux 单网卡）
```

**选择判据（决策表）**

| 条件 | 选路线 |
|---|---|
| 模板/文件夹/资源池/数据存储的精确 ID 已在 CMDB 或既往盘点中确定，且新建为关机交付 | **路线一（默认）** |
| 源模板首盘可能 >100GB，需先确认能否扩到标准盘 | 路线一（但先做一次 `template inspect` 核盘） |
| 新环境、不确定有哪些集群/模板/存储/空闲 IP | **路线二** |
| 需要克隆后自动配静态 IP 并开机，且为 **Linux 单网卡** | 路线二盘点 + 路线一命令**带 IP 参数**（=开机定制变体） |
| Windows / 需 DNS / 需 DHCP / 多网卡 | 路线一关机克隆，**网络在机内另行配置**，不要用内置定制 |

> 两条路线不是两套命令：**路线二是"路线一之前的盘点与决策阶段"**。盘点完成、参数确定后，最终都落到同一条 `deploy clone-template`。

---

## 2. IP 地址池与 VLSM 网络参数规范

### 2.1 工具的 IP 能力（真实语义）

| 命令 | 作用 | 关键字段 |
|---|---|---|
| `ip check --address <ip> --scope <scope>` | 汇总三路信号：资产占用 `inventory_use`、本地有效租约 `active_lease`、ping `reachable` | ping 不通只给 `inconclusive`，**不等于空闲** |
| `ip available --address <ip> --scope <scope>` | 仅在有**正向空闲证据**时 `available:true`（资产无占用、无有效租约、ping 明确不通） | 任一不确定 → `available:false` |
| `ip reserve --scope <scope> --ip <ip> --owner <owner> --minutes <n>` | 事务预留一个 IP（本地租约，带 TTL 与属主） | `minutes` 正整数；过期可释放 |
| `ip list --scope <scope>` | 列出该 scope 租约 | 只记录本工具预留，不扫全网 |
| `ip release <lease_id>` / `ip expire` | 释放精确租约 / 列过期租约（`--apply --lease-id` 才真释放） | 默认只列不改 |

> **`scope` 是字符串标签，不是 CIDR 解析器**。约定把 scope 命名为 `VLAN号:CIDR`（如 `vlan50:10.10.50.0/24`），使租约可按网段聚合，但工具不会按 CIDR 自动枚举/划分子网。**VLSM 划分由下面的规划表完成。**

### 2.2 VLSM 规划方法（规划层，落为一张网段表）

对每个业务网段登记：**VLAN、网络地址、CIDR 前缀、点分掩码、可用主机数、网关、保留段、可分配 IP 范围、scope 标签**。

划分规则：
1. 按"需求主机数"从大到小排序，大块先切（VLSM 最佳实践，减少碎片）。
2. 可用主机数 = `2^(32-前缀) − 2`（再扣除网关与保留地址）。
3. 网关默认取本子网第一个可用地址（`.1`）；网络地址（全 0）、广播地址（全 1）、网关、基础设施保留段不进可分配范围。
4. 掩码必须是**连续的合法 VLSM 掩码**（如 /25=255.255.255.128，/26=255.255.255.192）。

**VLSM 划分示例**：父块 `10.10.0.0/16`，按办公(VLAN50,/23=510 主机)、访客(VLAN51,/24=254)、管理(/26=62)、互联(/30=2) 依次切分：

| 用途 / VLAN | 网络地址/CIDR | 子网掩码 | 可用主机数 | 网关 | 可分配 IP 范围 | 保留 | scope 标签 |
|---|---|---|---:|---|---|---|---|
| 办公 VLAN50 | `10.10.0.0/23` | 255.255.254.0 | 510 | 10.10.0.1 | 10.10.0.10 – 10.10.1.253 | .0/.1(网)/.1(网关)/.2–.9 基础设施/10.10.1.254-255 | `vlan50:10.10.0.0/23` |
| 访客 VLAN51 | `10.10.2.0/24` | 255.255.255.0 | 254 | 10.10.2.1 | 10.10.2.10 – 10.10.2.253 | .0/.1/.2–.9/.254-255 | `vlan51:10.10.2.0/24` |
| 管理 VLAN10 | `10.10.3.0/26` | 255.255.255.192 | 62 | 10.10.3.1 | 10.10.3.10 – 10.10.3.62 | .0/.1/.2–.9/.63 | `vlan10:10.10.3.0/26` |
| 点到点互联 | `10.10.3.64/30` | 255.255.255.252 | 2 | 10.10.3.65 | 10.10.3.65 – 10.10.3.66 | .64/.67 | `p2p:10.10.3.64/30` |

> 上线前应把本表沉淀为团队 IPAM 基线（文件或台账）。工具侧用相同 `scope` 串登记每一次预留，保证资产、租约、ping 三路一致。

### 2.3 单个 IP 的"可分配"判定流程（强制）

```
候选 IP（落在 2.2 可分配范围内，且非网络/广播/网关/保留）
   │
   ▼
ip available --address <ip> --scope <scope>
   │
   ├─ available:true ─────────────► 允许：ip reserve（TTL 预留，owner=新 VM 名）
   ├─ reasons 含 inventory_use/active_lease/ping_reachable ► 换一个 IP
   └─ inconclusive（ping 不可达探测/读不全）──────────────► 视为不可用，换 IP，不得猜空闲
```

---

## 3. 虚拟机规格规范与标准基础模板

### 3.1 规格字段（映射到命令参数）

| 规格项 | 命令参数 | 单位/约束 | 省略时 |
|---|---|---|---|
| CPU 核数 | `--cpu` | 正整数（GiB 无关），最终由服务端 license/兼容性裁决 | 保留模板值 |
| 内存 | `--memory-gb` | 正整数 GiB（落为 memoryMB=GB×1024） | 保留模板值 |
| 系统盘容量 | `--disk-gb` | 正整数 GiB，**只能 > 模板首盘当前值（仅扩容）** | 保留模板盘大小 |
| 网卡/网络 | `--network-id` | `network-N` 或 `dvportgroup-N`；省略保留模板网卡 | 保留模板网卡 |
| 名称 | `--name` | 1–80 字符，无路径/百分号/控制符/边缘空白；目标文件夹内唯一 | 必填 |

### 3.2 标准基础模板规格（基线）：4 vCPU / 8 GiB / 100 GiB

| 项 | 标准值 | 落地参数 |
|---|---|---|
| CPU | **4 核** | `--cpu 4` |
| 内存 | **8 GiB** | `--memory-gb 8` |
| 系统盘 | **100 GiB** | `--disk-gb 100`（要求源模板首盘 ≤ 100 GiB） |

**命名规则（固定公式 `<业务名>-<IP点改连字符>-<Owner>`）**：
- 模板对象由 vCenter 侧维护（如 `tpl-centos7.9-4c8g100g`）；克隆出的 VM 命名 = 业务名（每台自由输入，如 web01）+ IP（点号改连字符）+ Owner（申请人姓名/工号）。
- 例：业务名 web01、地址 10.10.0.21、Owner zhangsan → **`web01-10-10-0-21-zhangsan`**。用所选 IP 拼名后查重，同名即代表该 IP 已被占用，应换空闲 IP 重拼，不加序号。Owner 同值用于 `ip reserve --owner`。全连字符名同时是合规 Linux 主机名。
- 标准规格可存为 preset 复用：`preset save` 保存 `deploy clone-template` 的声明式参数（CPU/内存/盘/网络），创建时 `preset show` 取值，避免每次手填。

**前置校验（盘容量约束）**：
```
template inspect --id <模板 vm-id>      # 确认 config.template=true、首盘容量 ≤ 100GiB
```
- 模板首盘 = 60 GiB → `--disk-gb 100` 扩容成功（已在真机验证扩到 80 GiB 的同款路径）。
- 模板首盘 > 100 GiB（如 120 GiB）→ 传 `--disk-gb 100` 会在写**前**被 `invalid_arguments/exit2` 拒绝（只扩不缩）。需换 ≤100 GiB 的模板，或接受较大盘并在规格表中标注例外。

---

## 4. 路线一：关机状态自定义配置后创建（默认模式）

**特征**：不传 `--ip-address`，克隆出的 VM 为 `poweredOff`；CPU/内存/磁盘扩容/网卡改配全部在一次性 `CloneVM_Task` 的 spec 中完成。不依赖 VMware Tools、不触发客户机定制，最稳、跨操作系统通用。

### 4.1 实施流程

```
① 前置确认（已知精确 ID）
   profile test → template inspect（模板/首盘≤100G）→ 确定 folder/pool/datastore(/host)
② 组装标准规格参数（4C/8G/100G，必要时 --network-id）
③ deploy clone-template（不带 ip）→ 返回 awaiting_confirmation + plan_id/digest
   ※ 此步纯预览，零变更
④ plan validate（可选，提交前再核对前提未漂移）
⑤ plan apply <plan_id> --confirm <digest> [--wait/-y]   → CloneVM_Task
⑥ task wait / 只读核验：非模板、poweredOff、文件夹/池/存储/CPU/内存/盘/网卡
⑦ 交付为关机状态；联网/IP 由后续配置管理或开机内置定制另行完成
```

### 4.2 操作步骤（命令）
```bash
# 0) 连接与身份（确认连的是目标 vCenter，避免同名环境误操作）
vcenter-aiops --profile lab profile test

# 1) 核模板（必须 isTemplate=true，首盘 ≤100GiB 才能扩到标准盘）
vcenter-aiops --profile lab template inspect --id vm-17091

# 2) 预览克隆计划（关机、标准 4C/8G/100G；host 省略走集群 DRS）
#    纯预览，返回 awaiting_confirmation，vCenter 零变更
vcenter-aiops --profile lab deploy clone-template \
  --vm-id vm-17091 \
  --name web01-10-10-0-21-zhangsan \
  --folder-id group-v1002 \
  --pool-id resgroup-12392 \
  --datastore-id datastore-28406 \
  --network-id network-1001 \
  --cpu 4 --memory-gb 8 --disk-gb 100

# 3)（可选）提交前再核对前提
vcenter-aiops --profile lab plan validate <plan_id>

# 4) 确认执行（change 级，只需 digest；--wait 等克隆任务结束）
vcenter-aiops --profile lab plan apply <plan_id> --confirm <digest> --wait
#    非交互/自动化可在命令链中加 -y；交互式终端会提示逐字输入 digest

# 5) 交付核验（只读）
vcenter-aiops --profile lab vm inspect --id <new-vm-id>
```

**预期结果**：新 VM `poweredOff`、`config.template=false`、位于指定文件夹/池/存储，CPU=4、memoryMB=8192、首盘=100GiB（104857600 KB），网卡映射到指定网络。

---

## 5. 路线二：盘点现有环境 → 选择 → 创建（基于现有环境模式）

**特征**：目标环境不确定，先只读盘点"集群/资源池/主机/数据存储/模板/网络"，结合 VLSM 网段选 IP，参数齐备后回到第 4 章的同一条命令创建。

### 5.1 阶段 A：连接与全局盘点

```bash
vcenter-aiops --profile lab profile test

# 计算资源：集群、主机
vcenter-aiops --profile lab cluster list --limit 200
vcenter-aiops --profile lab host info  --name <主机名>     # 或 --id host-12601

# 模板与普通 VM
vcenter-aiops --profile lab template list --limit 200
vcenter-aiops --profile lab template inspect --id <模板 vm-id>

# 数据存储（容量/可用）与已有 VM
vcenter-aiops --profile lab datastore list --limit 200
vcenter-aiops --profile lab datastore inspect --id datastore-28406
vcenter-aiops --profile lab inventory list --kind vm --limit 1000
```

**盘点输出→决策映射表（人工填表）**：

| 要确定的项 | 用哪条命令 | 记录值（精确 ID） |
|---|---|---|
| 目标集群 | `cluster list` | 集群/计算资源 ID，如 `domain-c12391` |
| 资源池 | 集群详情/放置信息 | `pool_id`，如 `resgroup-12392`（集群默认 DRS 池） |
| 放置主机（可选） | `host info` | 省略则 DRS；指定则记 `host_id`，如 `host-12601` |
| VM 文件夹 | 环境约定 / inventory | `folder_id`，如 `group-v1002`（须与计算资源同数据中心） |
| 数据存储 | `datastore list/inspect` | `datastore_id` + 可用空间（需 >100GiB，主机可见） |
| 源模板 | `template list/inspect` | `vm_id`（模板），记录首盘容量判断能否到 100G |
| 网络 | 网络 ID 需从环境/管理员获取（无 network list） | `network_id`：`network-N` 或 `dvportgroup-N`；不改网则省略 |

> **host↔datastore、host↔network 一致性**：命令在写前会强制校验"指定主机能使用该数据存储/网络"、"文件夹与计算资源同数据中心"、"目标文件夹无同名对象"、"存储可用空间足够"。盘点时优先让放置关系自洽（同一集群内主机与共享存储）。

### 5.2 阶段 B：VLSM 网段与 IP 选择（需要联网时）

1. 从第 2.2 节网段表选定用途网段（如办公 VLAN50 → scope `vlan50:10.10.0.0/23`）。
2. 在可分配范围内取候选地址，逐一做三路取证：

```bash
# 正向空闲证据：资产无占用 + 无有效租约 + ping 明确不通
vcenter-aiops --profile lab ip available --address 10.10.0.21 --scope vlan50:10.10.0.0/23
# 想看明细（资产/租约/ping 各自信号）：
vcenter-aiops --profile lab ip check     --address 10.10.0.21 --scope vlan50:10.10.0.0/23
```

3. `available:true` 后立即预留（带 TTL 与属主，防止窗口内被抢）：

```bash
vcenter-aiops --profile lab ip reserve \
  --scope vlan50:10.10.0.0/23 --ip 10.10.0.21 --owner zhangsan --minutes 120
```

### 5.3 阶段 C：选择完成 → 创建

- **关机交付（默认）**：按第 4 章执行，不带 `--ip-address`。
- **开机 + Linux 单网卡静态 IP 定制**：在同一条命令上追加 IP 参数（见第 6 章）。
- 创建成功、Tools/IP 就绪核对通过后，可将预留转固定（续约或在 IPAM 登记为已用）；失败则 `ip release <lease_id>` 释放。

---

## 6. 开机静态 IP 定制变体（仅 Linux 单网卡）

在克隆命令上追加以下参数，即开机并下发 Linux 客户机定制：

| 参数 | 必填 | 说明 |
|---|---|---|
| `--ip-address` | 是（给了才开机） | 点分十进制 IPv4，必须来自第 5.2 已取证+预留的地址 |
| `--subnet-mask` | 否 | 点分掩码，默认 `255.255.255.0`；VLSM 网段务必显式给真实掩码（如 /23 → 255.255.254.0） |
| `--gateway` | 否 | 点分 IPv4；省略则不设默认网关 |
| `--guest-domain` | 否 | Linux 域，默认 `local` |

```bash
vcenter-aiops --profile lab deploy clone-template \
  --vm-id vm-17091 --name web01-10-10-0-21-zhangsan \
  --folder-id group-v1002 --pool-id resgroup-12392 \
  --datastore-id datastore-28406 --network-id network-1001 \
  --cpu 4 --memory-gb 8 --disk-gb 100 \
  --ip-address 10.10.0.21 --subnet-mask 255.255.254.0 \
  --gateway 10.10.0.1 --guest-domain local
# → awaiting_confirmation，再 plan apply <id> --confirm <digest> --wait
# → 克隆任务结束后必须核对 Tools/IP（任务成功 ≠ 来宾已就绪）：
vcenter-aiops --profile lab vm tools-status --id <new-vm-id>
vcenter-aiops --profile lab vm wait-tools   --id <new-vm-id>
```

**强制核对项**：克隆 success 仅代表已创建/已提交定制。用 `vm wait-tools`/`task wait` 等到 Tools 与 IP 就绪，再用 `vm inspect`/`inventory list` 独立核验实际网卡与 IP；定制后主机名取 `--name`（LinuxPrep FixedName）。

**不适用场景（改走关机路线）**：Windows 来宾、需要 DNS/搜索域、DHCP 取址、多网卡分别定制 —— 当前内置定制不支持，需克隆关机后在机内或用配置管理完成。

---

## 7. 参数规范总表（deploy clone-template）

| 参数 | 类型 | 必填 | 默认 | 约束 / 取值 |
|---|---|---|---|---|
| `--vm-id` | string | 是 | — | 精确模板对象 ID `vm-\d+`，且 `config.template=true` |
| `--name` | string | 是 | — | 新 VM 名，1–80 字符，目标文件夹唯一 |
| `--folder-id` | string | 是 | — | `group-v\d+`，VM 文件夹，与计算资源同数据中心 |
| `--pool-id` | string | 是 | — | `resgroup-\d+` |
| `--datastore-id` | string | 是 | — | `datastore-\d+`，可访问/非维护/空间足 |
| `--host-id` | string | 否 | 省略=DRS | `host-\d+`，须∈池同一计算资源、connected、非维护 |
| `--network-id` | string | 否 | 保留模板网卡 | `network-N` 或 `dvportgroup-N`（仅改首块网卡） |
| `--cpu` | integer | 否 | 保留模板 | ≥1；标准值 **4** |
| `--memory-gb` | integer | 否 | 保留模板 | ≥1 GiB；标准值 **8** |
| `--disk-gb` | integer | 否 | 保留模板 | ≥1 且 **>模板首盘当前值**；标准值 **100** |
| `--ip-address` | IPv4 | 否 | 省略=关机 | 给定则开机 + Linux 单网卡定制 |
| `--subnet-mask` | IPv4 mask | 否 | 255.255.255.0 | VLSM 网段显式给真实连续掩码 |
| `--gateway` | IPv4 | 否 | 不设网关 | — |
| `--guest-domain` | string | 否 | local | Linux 定制域 |
| `--dry-run` | bool | 否 | false | （预览即非写，计划机制本身已保证先生后批） |
| `--request-id` | string | 否 | 自动 | 幂等键，绑定精确目标与参数 |
| `--wait` | bool | 否 | true | 是否等待克隆任务终态 |

**所需特权（写）**：`VirtualMachine.Provisioning.DeployTemplate`、`VirtualMachine.Inventory.CreateFromExisting`、`Resource.AssignVMToPool`、`Datastore.AllocateSpace`、`Network.Assign`（改网时）；带 IP 开机定制另需 `VirtualMachine.Interact.PowerOn`、`VirtualMachine.Provisioning.Customize`。

**退出码**：0 成功 · 2 参数错误（如 disk_gb≤模板盘、非法 IP/掩码/名称）· 3 本地配置/存储不安全 · 4 前置/身份/确认失败（模板不存在、放置不一致、容量不足、权限不足、计划过期）· 5 业务失败/部分 · 6 结果未知须 `task reconcile`，**绝不自动重发**。

---

## 8. 注意事项与上线检查清单

**安全/流程**
- [ ] 一律先 `profile test` 确认 vCenter 身份，防同名环境误操作。
- [ ] 所有创建先出 `awaiting_confirmation` 计划，核对 plan 中的 folder/pool/ds/host/规格/IP 后再 `plan apply --confirm <digest>`；change 级无需 DESTROY 令牌。
- [ ] 写后超时/响应丢失 → exit6，用 `task reconcile`/`task wait` 核对原任务，**不要重复提交**（request_id 幂等）。
- [ ] 用最小权限账号；缺特权应在写前 exit4 且不调用写 API。

**规格/磁盘**
- [ ] 标准 100GiB 盘前确认源模板首盘 ≤100GiB（只扩不缩）；更大模板需走例外。
- [ ] 数据存储空闲 > 目标盘标称容量，且目标主机可见该存储（指定 host 时）。
- [ ] CPU/内存最终受 vSphere 许可与集群兼容性约束（写前预检不替代完整兼容性试验）。

**网络/IP**
- [ ] VLSM 网段表（网络/掩码/网关/可用范围/保留/scope）评审入库，作为 IPAM 基线。
- [ ] 每个静态 IP 先 `ip available` 取得**正向空闲证据**再 `ip reserve`；`inconclusive` 一律换地址。
- [ ] VLSM 掩码显式传入（/23、/24、/26…），不要沿用默认 /24。
- [ ] 内置定制仅 Linux 单网卡、不下发 DNS；Windows/DHCP/多网卡/DNS 走关机克隆后配置。
- [ ] 改网确认 `network_id` 类型（标准 `network-N` vs 分布式 `dvportgroup-N`）与主机可达。

**就绪/收尾**
- [ ] 开机定制路线必须 `vm wait-tools` 并独立核验 IP/主机名/网卡，任务 success≠就绪。
- [ ] 交付后在 IPAM 将预留转"已用"；失败 `ip release` 释放，避免地址悬挂。
- [ ] 命名固定为 `<业务名>-<IP点改连字符>-<Owner>`（如 `web01-10-10-0-21-zhangsan`），目标文件夹内不重名；重名=该 IP 已占用，换空闲 IP 重拼不加序号。

**验收（只读核验新 VM，9 项）**
1. 非模板 `config.template=false`；2. 名称==`--name`；3. 所在文件夹==folder_id；4. 资源池==pool_id；5. 主机（指定时）==host_id，否则在集群内；6. 数据存储含 datastore_id；7. CPU/内存==4/8192MB；8. 首盘==100GiB；9. 电源：关机路线 `poweredOff`；开机路线 `poweredOn` 且 Tools/IP 就绪。

---

## 9. 端到端最小示例串讲（路线二 → 标准 4C/8G/100G）

```bash
P=lab
# 盘点
vcenter-aiops --profile $P cluster list
vcenter-aiops --profile $P template inspect --id vm-17091          # 模板/首盘
vcenter-aiops --profile $P datastore inspect --id datastore-28406  # 空间
# 选 IP（需要联网时）
vcenter-aiops --profile $P ip available --address 10.10.0.21 --scope vlan50:10.10.0.0/23
vcenter-aiops --profile $P ip reserve --scope vlan50:10.10.0.0/23 \
  --ip 10.10.0.21 --owner zhangsan --minutes 120
# 关机标准规格创建（默认路线一）；假设业务名 web01 → web01-10-10-0-21-zhangsan
vcenter-aiops --profile $P deploy clone-template --vm-id vm-17091 --name web01-10-10-0-21-zhangsan \
  --folder-id group-v1002 --pool-id resgroup-12392 --datastore-id datastore-28406 \
  --network-id network-1001 --cpu 4 --memory-gb 8 --disk-gb 100
vcenter-aiops --profile $P plan apply <plan_id> --confirm <digest> --wait
vcenter-aiops --profile $P vm inspect --id <new-vm-id>
```

> 路线一与路线二最终都收敛到同一条 `deploy clone-template`；区别只在"参数是否已确定"与"是否先做环境盘点/IP 取证"。
