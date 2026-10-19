# 交互式虚拟机创建 / 克隆向导 —— 对话流程设计

> 适用：vcenter-aiops 3.0.0b6。用户说“创建虚拟机 / 克隆虚拟机”即进入本向导，逐轮收集 → 二次确认 → 执行（克隆并自动开机）→ 统一清单回传。
> **默认环节是“基于模板的自定义克隆”（`deploy clone-template`）**：进入向导后直接按模板克隆，并在克隆 spec 中一次性完成名称/规格/集群主机/存储/网络的自定义改配；**不会**先造一台默认配置的关机空白机。`vm create`（无模板、无系统的空白机）仅是用户**显式要求**时才走的旁路，不是默认项，也不作为一个对等选项来问。
> 向导是**编排层**：不新增命令，每一步都映射到当前注册的原子命令；所有写仍走“预览计划 → digest 确认 → plan apply”，未知不重发。
> 最后更新：2026-10-19。

---

## 0. 先约定五条硬边界（向导必须据此提问，不能替用户假设）

| 边界 | 事实 | 向导处理 |
|---|---|---|
| 默认创建方式 | **统一走模板自定义克隆 `deploy clone-template`**：`cpu/memory_gb/disk_gb/network_id/host_id/ip_address` 均可选，在克隆 spec 内改配；省略规格=继承模板、省略 IP=关机、给 IP=开机+Linux 定制。`vm create` 需 `guest_id/hardware_version/host_id/network_id/cpu/memory/disk` 全必填，产出无系统空白机 | 进入即按模板克隆收集改配项；**不问“新建还是克隆”**。仅当用户明确“没有模板/要全新空白机”才切到 `vm create` 旁路（并提示需自行装系统） |
| 自动配 IP | 只有 **Linux 单网卡静态 IP** 能在克隆时由 vCenter 定制并开机（给 `--ip-address` 即开机）；**不下发 DNS、不支持 Windows/DHCP/多网卡** | Q0 先问客户机类型/网卡数，分流到“原生开机定制”或“关机克隆→机内配网→vm power-on” |
| “最小可用 IP” | 工具**不扫描整段网段**，只对单个地址给三路信号；ping 不通 ≠ 空闲（inconclusive 即不可用） | 向导从可分配低端逐个调 `ip available`，第一个三路全绿者为最小可用 |
| 磁盘只扩不缩 | `--disk-gb` 必须 > 模板首盘当前值 | 选定模板后读首盘容量，规格建议自动夹到合法区间 |
| 名称规则 | 1–80 字符、无路径/百分号/控制符/边缘空白、目标文件夹内唯一 | 按规则生成候选名（结合 IP 主机号），`inventory list` 查重，重名自动加序号 |

---

## 1. 状态机总览

```
START “创建/克隆虚拟机”
  │
  ▼
[S0 进入即克隆]  默认直接走「模板自定义克隆 deploy clone-template」（克隆 spec 内改名/规格/放置/网络）
  │              不问“新建还是克隆”；仅当用户明确“无模板、要空白机”才切旁路 vm create（需自装 OS）
  ▼
[S1 环境确认]  profile test（确认 vCenter 身份/权限）；本对话是否已给过业务网段？
  │            未给 → 问一次网段(VLSM: 网络/掩码/网关/可用范围/VLAN-scope)并在对话内记住；已给 → 直接复用，不再问
  ▼
[S2 盘点]     template / cluster / datastore list (+host info)；只给可选项
  │
  ▼
[S3 逐轮收集] Q1 业务与命名  Q2 规格(默认4/8/100)  Q3 集群  Q4 主机(默认DRS)
  │            Q5 数据存储  Q6 模板  Q7 网络与IP（网段→自动选最小可用/可自定义）
  ▼
[S4 预检]     模板首盘/存储容量/同名/放置一致性/IP 三路空闲取证 → ip reserve 占坑
  │
  ▼
[S5 二次确认] 展示完整配置卡，用户显式“确认”  ── 第 1 次（业务确认）
  │            deploy clone-template 预览出 digest
  ▼
[S6 执行]     plan apply --confirm <digest>   ── 第 2 次（精确计划密码学确认）
  │            Linux带IP：克隆即开机+定制；其它：克隆关机 → vm power-on（机内已配网时）
  ▼
[S7 就绪核对] vm wait-tools / vm inspect / inventory 复核 名称/IP/电源
  │
  ▼
[S8 统一清单] 输出固定格式结果卡；IP 预留转“已用”或失败释放
END
```

> **默认走克隆而非空白机**：S0 不做“新建空白 VM / 模板克隆”的对等二选一——`deploy clone-template` 本身就能在克隆时完成全部自定义改配（规格/网卡/放置皆可选参数），没有必要先建一台默认配置的关机空白机。`vm create` 是无模板、无客户机 OS 的底层路径（`guest_id`/`hardware_version`/`host_id`/`network_id`/`cpu`/`memory`/`disk` 全必填），只在用户明确拒绝模板时才作为旁路，向导需额外提示“产出为空白机，需自行安装系统与配网”。

> **两次确认的含义**：S5 是给人看的“配置卡确认”；S6 的 `--confirm <digest>` 是对不可变计划内容的密码学确认（plan 含 folder/pool/ds/host/规格/IP，任一项变化 digest 就变）。销毁类才需要第三把 `DESTROY:`，克隆不属于销毁，故不需要。

---

## 2. 逐轮信息收集（对话脚本）

向导一次只问当前必需项；已能从盘点或当次网段参数推出的不重复问；每轮给“推荐项（回车默认）+ 可选项编号 + 自定义”。

### Q0 — 客户机与网络形态（决定开机路径，最先问）

- 客户机 OS：**Linux / Windows / 其它**？
- 网卡数量：**1 块 / 多块**？地址方式：**静态 / DHCP**？是否需要下发 DNS？

分流：
- **Linux + 单网卡 + 静态**（且无需额外 DNS）→ 走“克隆带 IP，自动开机 + 定制”（推荐，原生闭环）。
- 其它任意组合（Windows、多网卡、DHCP、要 DNS）→ 走“**关机克隆** → 系统内配网 → `vm power-on`”。向导仍收集期望 IP 用于占坑与命名，但不承诺 vCenter 自动配网。

### Q1 — 业务用途与名称（结合 IP）

- 问：业务/用途、所属 VLAN 或网段（关联命名前缀）。
- 命名按现有规则生成（沿用团队 `mumian-*` 体系）：
  `mumian-<业务段>-<IP主机号补零>`，例：办公 VLAN50、地址 10.10.0.21 → **`mumian-office-021`**。
- 生成后用 `inventory list --kind vm` 查重；同名则递增序号（`-022`、`-023`…），不覆盖、不模糊匹配。
- 名称最终必须过 1–80 字符与非法字符校验；用户可改名。

### Q2 — 规格（默认标准 4C/8G/100G）

| 项 | 默认（标准） | 可选 |
|---|---|---|
| CPU | **4** | ≥1 整数，受集群许可/EVC 约束 |
| 内存 | **8 GiB** | ≥1 GiB |
| 系统盘 | **100 GiB** | 必须 > 模板首盘；选模板后自动夹下限 |

展示“模板盘 X GiB → 目标 100 GiB（扩容）”；若模板盘 >100 则提示只能选更大值或换模板。

### Q3 — 集群；Q4 — 主机（默认 DRS）

- Q3：`cluster list` 列集群，编号选择（记录 compute/pool，如共享存储 `domain-c12391`/`resgroup-12392`）。
- Q4：默认“**集群 DRS 自动放置**”（省略 host_id）；需绑定时 `host info` 列该集群 connected、非维护主机。
- 向导校验：指定主机 ∈ 集群、能见到所选存储与网络（写前命令也会强校验）。

### Q5 — 数据存储

- `datastore list/inspect` 给可用空间，只列 accessible/normal、空闲 > 目标盘容量者；指定主机时只列该主机可见存储。
- 例：5020-A `datastore-28406`（freeSpace 足）。

### Q6 — 克隆模板

- `template list` + `template inspect --id`：只列 `config.template=true`、connected；展示模板名、客户机 OS、首盘容量、自带网卡/网络。
- 记录模板 vm-id（如 `vm-17091`）。默认向导只接受**真模板**作为克隆源；盘点不到任何模板时，不静默改走空白机，而是提示“无可用模板”，由用户显式决定是否切到 `vm create` 旁路。

### Q7 — 网络与 IP（核心：首次问网段，自动选最小可用，可自定义）

**本对话第一次创建 VM 时问一次网段参数（VLSM），并在整段对话内记住；之后再创建直接复用，不再重问。** 这些参数不内置、不预填、不假设固定的办公/访客网段，也不落盘成文件或跨对话台账——只活在当前对话里；用户在对话中明确修改时才更新：

| 字段 | 当次示例（假设值，非固定网段） |
|---|---|
| 网络地址/CIDR | `10.10.0.0/23` |
| 点分掩码 | `255.255.254.0` |
| 网关 | `10.10.0.1` |
| 可分配范围 | `10.10.0.10 – 10.10.1.253` |
| 保留 | 网络地址、广播、.1 网关、.2–.9 基础设施 |
| scope 标签 | `vlan50:10.10.0.0/23` |

**自动选最小可用 IP（向导算法，严格）：**

```text
candidate = 可分配范围下界（如 .10）
loop:
  sig = ip available --address candidate --scope <scope>
    内部三路：① inventory_use（vCenter 已有 VM 的 guest.ipAddress/名称占用）
             ② active_lease（本地有效租约）
             ③ ping：reachable=true→占用；探测失败→inconclusive（按不可用处理）
  if sig.available == true:            选 candidate（最小可用，停）
  else if reasons 含 ping_inconclusive: 记为“存疑”，继续（绝不选存疑地址）
  else:                                candidate = candidate + 1（跳过网络/广播/网关/保留）
  到上界仍无 → 报告“网段无可分配地址”，请用户扩范围/换网段
```

- 取到后展示：**“建议 IP 10.10.0.21（ping 不通、清单无占用、无租约）”**，给三选一：
  **回车采用 / 输入自定义 IP（仍走同样三路校验）/ 换一个（candidate+1 重测）**。
- 自定义地址若落在网段外、是网络/广播/网关/保留、或任一信号占用 → 当场拒绝并说明原因。
- 网络对象：问改不改网卡；改则要 `network_id`（`network-N` 标准 或 `dvportgroup-N` 分布式），不改保留模板网卡。当前无 `network list` 命令，network_id 由用户当次提供/管理员给出。

---

## 3. 预检与占坑（S4，只读 / 本地，零远端变更）

```bash
profile test                                     # vCenter 身份/连通
template inspect --id <tpl>                      # 模板=true、首盘≤目标盘
datastore inspect --id <ds>                      # 空闲 > 目标盘
cluster list / host info                         # 放置自洽
inventory list --kind vm --limit 1000            # 名称查重、IP 占用（ip available 内部也用）
ip available --address <选中IP> --scope <scope>  # 三路正向空闲证据
ip reserve --scope <scope> --ip <IP> --owner <VM名> --minutes 60   # 占坑 60 分钟
```

任一不满足：停在预检，回报具体原因（exit2 参数 / exit4 前置），不进入确认。
占坑成功后若放弃或失败，向导执行 `ip release <lease_id>` 回收，避免地址悬挂。

---

## 4. 二次确认配置卡（S5）

收集完毕，向用户展示完整卡片，要求显式回复“确认 / yes”：

```text
━━━━━━ 请确认虚拟机创建配置 ━━━━━━
创建方式    : 模板克隆（克隆后自动开机）
名称        : mumian-office-021
客户机/网络 : Linux 单网卡 / 静态IP / 开机自动定制
规格        : 4 vCPU · 8 GiB 内存 · 100 GiB 系统盘（模板 60→100 扩容）
集群        : 共享存储 domain-c12391（资源池 resgroup-12392）
主机        : DRS 自动放置
数据存储    : 5020-A（datastore-28406）
模板        : Centos7.9_2c4g60g（vm-17091）
网络        : network-1001（办公 VLAN50）
IP/掩码/网关: 10.10.0.21 / 255.255.254.0 / 10.10.0.1（域 local）
IP 状态     : ping 不通 + 清单无占用 + 已预留 60 分钟
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
回复“确认”执行；回复“改 <项> <值>”修改；其余取消。
```

改任意项 → 回到对应 Q 编号，重跑受影响预检（改 IP 要先释放旧租约、重测新 IP、重新占坑）。

---

## 5. 执行（S6，克隆 + 自动开机）

### 5.1 Linux 单网卡静态 IP（原生：克隆即开机 + 定制）

```bash
# 预览（纯只读，出 awaiting_confirmation + plan_id/digest）
vcenter-aiops --profile lab deploy clone-template \
  --vm-id vm-17091 --name mumian-office-021 \
  --folder-id group-v1002 --pool-id resgroup-12392 --datastore-id datastore-28406 \
  --network-id network-1001 --cpu 4 --memory-gb 8 --disk-gb 100 \
  --ip-address 10.10.0.21 --subnet-mask 255.255.254.0 --gateway 10.10.0.1 --guest-domain local

# 第 2 次确认：对不可变计划的 digest
vcenter-aiops --profile lab plan apply <plan_id> --confirm <digest> --wait
# powerOn=true，CloneVM 后自动开机并下发 Linux 定制（主机名 = VM 名）
```

### 5.2 Windows / DHCP / 多网卡 / 需 DNS（关机克隆 → 配网 → 开机）

```bash
# 不带 --ip-address：克隆为 poweredOff（规格/网卡改配同样在克隆 spec 完成）
vcenter-aiops --profile lab deploy clone-template --vm-id <tpl> --name <name> \
  --folder-id <f> --pool-id <p> --datastore-id <ds> [--network-id <n>] \
  --cpu 4 --memory-gb 8 --disk-gb 100
vcenter-aiops --profile lab plan apply <plan_id> --confirm <digest> --wait
# → 在来宾系统内完成配网（Windows 定制/静态/DHCP/DNS，由镜像/配置管理保证）后：
vcenter-aiops --profile lab vm power-on --vm-id <new-vm-id>       # 先预览
vcenter-aiops --profile lab plan apply <plan2> --confirm <digest2> --wait
```

> 默认链路全程是“模板自定义克隆”：不带 `--ip-address` 时克隆为 poweredOff（规格/网卡改配同样在克隆 spec 完成），需要联网时再按 5.1（Linux 单网卡，克隆即开机定制）或在来宾系统内配网后 `vm power-on`。**`vm create` 不属于默认环节**——它创建无系统空白机（`guest_id`/`hardware_version`/`host_id`/`network_id`/`cpu`/`memory`/`disk` 全必填），仅在用户明确“没有模板、要全新空白机”时走该旁路，随后自行装系统/配网/开机。

---

## 6. 就绪核对（S7）

```bash
vm wait-tools   --id <new-vm-id>     # Linux 开机定制：等 Tools/IP 就绪（任务成功≠就绪）
vm inspect      --id <new-vm-id>     # 电源/主机/池/存储/CPU/内存
inventory list --kind vm            # 复核 guest.ipAddress==所选 IP、名称唯一
```

克隆任务 success 仅代表已创建/已提交定制；必须独立读到 Tools 就绪且实际 IP 正确。失败按退出码处理：exit4 前置/确认问题可修正重试；**exit6 结果未知只用 `task reconcile/task wait` 核对，绝不重发克隆**。

---

## 7. 统一结果清单（S8，固定格式回传）

成功后无论走哪条路径，都回传同一张卡片：

```text
✅ 虚拟机创建成功
┌──────────────┬───────────────────────────────────────┐
│ 名称         │ mumian-office-021                       │
│ IP 地址      │ 10.10.0.21/23（gw 10.10.0.1，VLAN50）   │
│ 规格         │ 4 vCPU / 8 GiB / 100 GiB                │
│ 集群         │ 共享存储 domain-c12391（resgroup-12392） │
│ 主机         │ host-12601（DRS 放置）                  │
│ 数据存储     │ 5020-A（datastore-28406）               │
│ 模板         │ Centos7.9_2c4g60g（vm-17091）           │
│ 运行状态     │ poweredOn · Tools: toolsOkay · IP 已就绪 │
└──────────────┴───────────────────────────────────────┘
plan_id=<id> · new-vm-id=vm-34624 · 创建耗时 27s
```

**字段口径（固定 8 项 + 追溯）：**

| 字段 | 取值来源 |
|---|---|
| 名称 | Q1 生成并查重后的最终 `--name` |
| IP 地址 | Q7 三路取证选中的地址；关机/未配网路线标注“机内配置（预留 10.10.0.21）” |
| 规格 | 实际落盘的 numCPU / memoryMB/1024 / 首盘 GiB（用 `vm inspect` 实测值，不回显请求值） |
| 集群 | 资源池 owner 计算资源名（domain-c…） |
| 主机 | 实际 runtime.host（DRS 时报告调度结果，而非“自动”） |
| 数据存储 | 实际 datastore 列表中命中的目标 |
| 模板 | 源模板名（vm-id） |
| 运行状态 | `runtime.powerState` + Tools 状态 + IP 就绪标志（wait-tools 后读取） |
| 追溯 | plan_id、new-vm-id、耗时；便于 `task inspect/plan show` 审计 |

失败/部分成功时不输出成功卡，改为：状态、失败阶段、退出码与原因、已占 IP 的 lease_id（并提示已/将释放）、若 exit6 给出 `task reconcile` 命令，不自动重发。

---

## 8. 向导提问顺序速查（可直接当对话脚本）

1. **Q0** Linux/Windows？单网卡/多网卡？静态/DHCP？要 DNS 吗？（决定开机路径）
2. **Q1** 业务用途/VLAN → 生成候选名（结合 IP 主机号）→ 查重确认。
3. **Q2** 规格回车用标准 4C/8G/100G，或自定义（选模板后校验磁盘只能扩）。
4. **Q3** 选集群（盘点编号）。
5. **Q4** 主机：回车=DRS，或选具体主机。
6. **Q5** 选数据存储（按可用空间/主机可见过滤）。
7. **Q6** 选模板（只列真模板，显示 OS/首盘/网卡）。
8. **Q7** 网段在**本对话第一次创建时问一次并记住**（网络/CIDR/掩码/网关/可用范围/VLAN-scope），后续创建直接复用、不再重问（用户显式改才更新）→ 每台新 VM 仍在该网段内自动从最小空闲地址做三路探测，建议最小可用 IP；回车采用 / 自定义 / 换一个；选是否改网卡 network_id。
9. **预检 + 占坑**（只读）。
10. **S5** 配置卡 → 用户“确认”。
11. **S6** 出计划 digest → `plan apply --confirm`（Linux 带 IP 自动开机；其它关机克隆后 `vm power-on`）。
12. **S7** wait-tools/inspect 复核。
13. **S8** 统一结果清单。

---

## 9. 异常与安全要点

- **全程零写直到确认**：S0–S5 只有只读盘点/探测和本地 IP 占坑；远端写唯一入口是确认后的 `plan apply`。
- **ping 不通绝不当空闲**：inconclusive（探测不可用）按不可用跳过；只有“清单无占用 + 无有效租约 + ping 明确不通”才是 `available:true`。
- **占坑 TTL**：默认 `--minutes 60`，覆盖一次克隆窗口；成功转 IPAM 已用，失败/取消 `ip release`。
- **最小权限**：克隆需 DeployTemplate/CreateFromExisting/AssignVMToPool/AllocateSpace/Network.Assign；带 IP 开机另需 PowerOn/Customize。
- **未知不重发**：写后超时/结果不明 exit6，只 `task reconcile/task wait`；request_id 绑定精确目标与参数幂等。
- **命名/目标精确**：拒绝通配/零宽字符；目标文件夹同名写前 exit4。
- **Windows 等非原生定制**：向导不假装能下发 IP，明确告知“克隆关机→机内配网→开机”，结果卡 IP 字段据实标注。
- **网络 ID 缺口**：无 `network list`，改网卡所需 `network-N/dvportgroup-N` 由用户当次提供或管理员给出；省略则保留模板网卡。
- **网段不固化、对话内复用**：业务网段参数（CIDR/掩码/网关/可用范围/scope）在本对话第一次创建时问一次并记住，后续创建直接复用、不再重问；不附带也不读取固定网段池文件、不落盘、不跨对话。注意复用的是**网段参数**，每台 VM 的具体 IP 仍要在该网段内重新做三路取证选最小可用（前序 IP 已被占用/预留）。
