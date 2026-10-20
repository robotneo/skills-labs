# 交互式虚拟机创建 / 克隆向导 —— 对话流程设计

> 适用：vcenter-aiops 3.0.0b6。用户表达“克隆虚拟机 / 创建虚拟机 / 新建虚拟机 / 开一台 VM / 部署一台虚拟机 / 加一台机器”等等价意图，**统一引导到“基于模板的自定义克隆”**，逐轮收集 → 二次确认 → 执行（克隆并自动开机）→ 统一清单回传。
> **默认环节是“基于模板的自定义克隆”（`deploy clone-template`）**：进入向导后直接按模板克隆，并在克隆 spec 中一次性完成名称/规格/集群主机/存储/网络的自定义改配；**不会**先造一台默认配置的关机空白机。`vm create`（无模板、无系统的空白机）仅是用户**显式要求**时才走的旁路，不是默认项，也不作为一个对等选项来问。
> 向导是**编排层**：不新增命令，每一步都映射到当前注册的原子命令；所有写仍走“预览计划 → digest 确认 → plan apply”，未知不重发。
> 最后更新：2026-10-19（新增前置凭据门；收集顺序重排为“凭据 → 规格 → 模板 → 网络/IP → 集群/主机/存储 → 命名 → 二次确认”；命名公式改为 `<业务名>-<IP点改连字符>-<Owner>`）。

---

## 0. 先约定硬边界（向导必须据此提问，不能替用户假设）

| 边界 | 事实 | 向导处理 |
|---|---|---|
| 统一入口 | 凡“克隆/创建/新建/开一台/部署一台/加一台虚拟机”等同义意图，都进模板克隆流 | 不问“新建还是克隆”；仅当用户明确“没有模板/要全新空白机”才切 `vm create` 旁路（提示需自装 OS） |
| 前置凭据门 | 任何盘点前必须先有可用 profile（vCenter 地址/用户名/密码）。`profile add` 的 `--password-ref` 只接受引用（`env:VC_PASSWORD` 或 0600 文件），**不接受也不记录明文密码** | 无连接信息 → 先问齐 vCenter IP(+端口)、用户名、密码，引导安全注入后 `profile add` + `profile test`，通过才继续 |
| 收集顺序 | 规格 → 模板 → 网络/IP → 集群/主机/存储 → 命名（严格按序） | 规格先于模板；选定模板后用首盘容量反校磁盘；放置信息盘点后再编号选择 |
| 自动配 IP | 只有 **Linux 单网卡静态 IP** 能在克隆时由 vCenter 定制并开机（给 `--ip-address` 即开机）；**不下发 DNS、不支持 Windows/DHCP/多网卡** | 在“网络/IP”步一并问客户机类型/网卡数，分流“原生开机定制”或“关机克隆→机内配网→vm power-on” |
| 磁盘只扩不缩 | `--disk-gb` 必须 > 模板首盘当前值 | 先收集期望盘，选模板后读首盘容量，自动夹到合法区间 |
| “最小可用 IP” | 工具**不扫描整段网段**，只对单个地址给三路信号；ping 不通 ≠ 空闲（inconclusive 即不可用） | 向导在用户给的可分配范围内从低端逐个 `ip available`，第一个三路全绿者为建议值 |
| 名称规则 | 固定公式 **`<业务名>-<IP点改连字符>-<Owner>`**（如 `web01-10-10-0-21-zhangsan`）；1–80 字符、无路径/百分号/控制符/边缘空白、目标文件夹唯一 | 业务名每台自由输入、Owner 每台问申请人；用所选 IP 拼名后 `inventory list` 查重，重名换 IP 重拼不加序号 |

---

## 1. 状态机总览（S0–S9）

```
START  触发词：克隆/创建/新建/开一台/部署一台/加一台 虚拟机（等价意图统一入口）
  │
  ▼
[S0 统一入口]  一律进入「模板自定义克隆 deploy clone-template」；不问“新建还是克隆”
  │            仅用户明确“无模板、要空白机”才切旁路 vm create（需自装 OS，不在主流程）
  ▼
[S1 凭据门]    是否已有可连通 profile（profile list → profile test 成功）？
  │            否 → 问齐 vCenter IP(+端口)/用户名/密码 → 安全注入 → profile add → profile test
  │            是 → 直接复用（本对话不再重问）
  ▼
[S2 规格]      问 CPU 核数 / 内存 GiB / 硬盘 GiB（默认 standard 4C/8G/100G，可自定义）
  ▼
[S3 选模板]    template list + inspect：列出“模板名 + OS/首盘/规格/网卡”供编号选择
  │            选定后用首盘容量反校：硬盘 GiB 必须 > 模板首盘，否则夹下限/提示换模板
  ▼
[S4 网络与IP]  问 网段 CIDR/掩码/网关/可分配范围/scope + 虚拟机使用的网络(端口组 network_id)
  │            （网段本对话首次问并记住、后续复用）；范围内逐地址 ip available 三路取证
  │            并行问客户机 OS/网卡数/静态·DHCP → 决定开机定制 or 关机克隆
  ▼
[S5 放置]      cluster list 选集群 → host 选“DRS 自动(默认)/指定主机” → datastore 选存储
  │            只给 connected/accessible/容量足够且主机可见的可选项；放置一致性写前强校验
  ▼
[S6 命名]      问 业务名(每台) + Owner 申请人姓名/工号(每台)
  │            自动拼名 <业务名>-<IP点改连字符>-<Owner> → inventory 查重（重名换 IP，不加序号）
  ▼
[S7 预检+占坑] profile test / 模板首盘 / 存储容量 / 同名 / 放置一致性 / IP 三路空闲 → ip reserve 占坑
  ▼
[S8 二次确认]  归纳全部信息出完整配置卡，用户显式“确认”            ── 第 1 次（业务确认）
  │            deploy clone-template 预览出 digest
  ▼
[S9 执行+核对] plan apply --confirm <digest>                      ── 第 2 次（计划密码学确认）
               Linux 带 IP：克隆即开机+定制；其它：克隆关机 → 机内配网 → vm power-on
               vm wait-tools / vm inspect / inventory 复核 → 统一结果卡（IP 租约转已用/失败释放）
END
```

> **S1 是硬前置**：没有 vCenter 连接信息就无法盘点模板/集群/存储，因此把“问齐 IP/用户名/密码并 `profile add`+`profile test`”提到所有业务问题之前。本对话一旦 profile 连通即记住，后续创建不再重问。
>
> **两次确认的含义**：S8 是给人看的“配置卡确认”；S9 的 `--confirm <digest>` 是对不可变计划内容的密码学确认（plan 含 folder/pool/ds/host/规格/IP，任一项变化 digest 就变）。克隆属 change、非销毁，不需要 `DESTROY:`。

---

## 2. 逐轮信息收集（对话脚本，严格按序）

向导一次只问当前必需项；已能从盘点或本对话已记住的参数推出的不重复问；每轮给“推荐项（回车默认）+ 可选项编号 + 自定义”。

### S1 — 凭据门（最先，缺则必问）

进入向导先 `profile list` 看是否已有可连通 profile：

- **已有且 `profile test` 成功** → 记住并复用，直接进 S2，不再问连接信息。
- **没有 / test 失败 / 用户要换环境** → 一次性问齐三件：
  1. **vCenter 地址**：IP 或域名（默认端口 443，非默认再问端口；是否校验 TLS）。
  2. **用户名**：如 `administrator@vsphere.local`。
  3. **密码**：**引导用户安全注入，绝不在对话里明文收发、绝不写进命令行参数或文档。**

安全注入与建档（macOS/Linux；让用户在本机终端执行，密码不回显、不入 shell 历史）：

```bash
umask 077; read -rs -p "VC password: " pw && printf '%s' "$pw" > /tmp/.vcpw && unset pw && chmod 600 /tmp/.vcpw
# 建档（--password-ref 只引用 env，不存明文）：
VC_PASSWORD="$(cat /tmp/.vcpw)" vcenter-aiops profile add <profile名> \
  --host <vCenter-IP> --user <用户名> --password-ref env:VC_PASSWORD --port 443 --insecure
vcenter-aiops --profile <profile名> profile test      # 回报服务端身份即通过
```

- profile 名建议用环境简称（如 `lab`）；已存在同名则改用 `profile update`。
- `profile test` 通过才进 S2；失败据退出码回报（exit3 网络/TLS、exit4 身份），不带着坏连接继续。
- 向导结束（或用户要求）后 `rm -P /tmp/.vcpw` 清密码文件。

### S2 — 规格：CPU / 内存 / 硬盘（先于模板）

| 项 | 默认（standard） | 可选 |
|---|---|---|
| CPU 核数 | **4** | ≥1 整数，受集群许可/EVC 约束 |
| 内存 | **8 GiB** | ≥1 GiB |
| 硬盘（系统盘） | **100 GiB** | ≥ 模板首盘；选模板后自动夹下限 |

档位可参考 `references/wizard/size-presets.yaml`（inherit/compact/standard/large/xlarge）。此时还没选模板，硬盘先记期望值；S3 选到模板后展示“模板盘 X GiB → 目标 Y GiB（扩容）”，若期望盘 ≤ 模板首盘则提示只能选更大值或换模板（**只扩不缩**）。

### S3 — 从哪个模板克隆（列出模板名与信息供选择）

- 先 `cluster list` / `template list` 盘点（环境有多个数据中心/集群时，向导按用户指定范围列模板；默认列当前可见全部真模板）。
- `template list` + 对候选项 `template inspect --id`，用编号表展示，**至少包含：模板名、客户机 OS（guestId）、首盘容量、vCPU/内存、自带网卡/网络、MoRef(vm-N)**。
- 只列 `config.template=true`、connected 的真模板；用户回编号选择，记录模板 `vm-id`（如 `vm-17091`）。
- 选定即做磁盘只扩不缩反校。盘点不到任何模板时**不静默回退空白机**，提示“无可用模板”，由用户显式决定是否切 `vm create` 旁路。

向导据此渲染选择表：

```text
[ vcenter-aiops --profile lab template list --limit 200 ]
编号  模板名                  客户机OS        首盘    规格    MoRef
 1    Centos7.9_2c4g60g       centos7_64Guest 60GiB   2C/4G   vm-17091
 2    Ubuntu22.04_4c8g100g    ubuntu64Guest   100GiB  4C/8G   vm-18022
 …
```

### S4 — 网络与 IP：网段 CIDR + 虚拟机使用的网络

**A. 网段参数（本对话首次问一次并记住，后续创建复用、不再重问；用户显式改才更新）。不内置、不预填、不落盘、不跨对话：**

| 字段 | 当次示例（假设值，非固定网段） |
|---|---|
| 网络地址/CIDR | `10.10.0.0/23` |
| 点分掩码 | `255.255.254.0` |
| 网关 | `10.10.0.1` |
| 可分配范围 | `10.10.0.10 – 10.10.1.253` |
| 保留 | 网络地址、广播、.1 网关、.2–.9 基础设施 |
| scope 标签 | `vlan50:10.10.0.0/23` |

**B. 虚拟机使用的网络（端口组对象）**：问新 VM 网卡接哪个网络。改网卡需 `network_id`（标准 `network-N` 或分布式 `dvportgroup-N`）；当前无 `network list` 命令，该 ID 由用户当次提供/管理员给出，省略则保留模板自带网卡。

**C. 客户机形态（与网络同一步问，决定开机路径）**：Linux/Windows？单网卡/多网卡？静态/DHCP？是否要 DNS？
- **Linux + 单网卡 + 静态 + 无额外 DNS** → 克隆即开机 + 原生定制。
- 其它（Windows/多网卡/DHCP/要 DNS）→ 关机克隆 → 机内配网 → `vm power-on`（仍收集期望 IP 用于占坑与命名，但不承诺 vCenter 自动配网）。

**D. 自动选最小可用 IP（严格）：**

```text
candidate = 可分配范围下界（如 .10）
loop:
  sig = ip available --address candidate --scope <scope>
    内部三路：① inventory_use（vCenter 已有 VM 的 guest.ipAddress/名称占用）
             ② active_lease（本地有效租约）
             ③ ping：reachable=true→占用；探测失败→inconclusive（按不可用处理）
  if sig.available == true:              选 candidate（最小可用，停）
  else if reasons 含 ping_inconclusive:  记“存疑”，继续（绝不选存疑地址）
  else:                                  candidate = candidate + 1（跳过网络/广播/网关/保留）
  到上界仍无 → 报告“网段无可分配地址”，请用户扩范围/换网段
```

- 取到后展示：**“建议 IP 10.10.0.21（ping 不通、清单无占用、无租约）”**，三选一：**回车采用 / 输入自定义 IP（同样三路校验）/ 换一个（candidate+1 重测）**。
- 自定义地址落在网段外、命中网络/广播/网关/保留、或任一信号占用 → 当场拒绝并说明原因。

### S5 — 放置：集群 → 主机（自定义或 DRS）→ 数据存储

1. **集群**：`cluster list --limit 100` 列集群，编号选择（记录 compute/pool，如共享存储 `domain-c12391`/`resgroup-12392`）。
2. **主机**：默认“**集群 DRS 自动放置**”（省略 host_id）；需绑定则 `host info` 列该集群 connected、非维护主机供编号选择（即“自定义主机”）。向导校验指定主机 ∈ 集群、能见所选存储与网络。
3. **数据存储**：`datastore list/inspect` 给可用空间，只列 accessible/normal、空闲 > 目标盘容量者；指定主机时只列该主机可见存储。例：5020-A `datastore-28406`。

### S6 — 命名：业务名 + IP + Owner

依次问两项（**每台都问，不做对话级复用**）：

1. **业务名**：这台机器的用途短名，自由输入、名称词表合法（如 `web01`、`db02`、`jumpbox`）。
2. **Owner（申请人）**：责任人姓名或工号（如 `zhangsan` / `1024`）；同一值用于 `ip reserve --owner`，便于租约追责。

自动拼名（**IP 的点号一律改成连字符**）：

```text
<业务名>-<IP 点改连字符>-<Owner>

例：业务名 web01 + IP 10.10.0.21 + Owner zhangsan
  → web01-10-10-0-21-zhangsan
```

- 拼成后用 `inventory list --kind vm` 查重；**重名说明该 IP/名称已占用，换一个经三路取证空闲的 IP 重新拼名**，不做序号递增、不覆盖、不模糊匹配。
- 整名必须过 1–80 字符与非法字符校验（连字符 `-` 合法；业务名/Owner 内部不要含 `/ \ %`、空白、控制符）。
- **全连字符天然是合法 Linux 主机名**：IP 点改连字符后，克隆即开机走 LinuxPrep `FixedName` 时也不会出现“点号被当 FQDN”的问题；若业务名/Owner 只用字母数字与连字符，则 vCenter 名与客户机主机名可安全保持一致。

---

## 3. 预检与占坑（S7，只读 / 本地，零远端变更）

```bash
profile test                                     # vCenter 身份/连通（S1 已做，此处复核）
template inspect --id <tpl>                      # 模板=true、首盘 < 目标盘
datastore inspect --id <ds>                      # 空闲 > 目标盘
cluster list / host info                         # 放置自洽
inventory list --kind vm --limit 1000            # 名称查重、IP 占用（ip available 内部也用）
ip available --address <选中IP> --scope <scope>  # 三路正向空闲证据
ip reserve --scope <scope> --ip <IP> --owner <Owner> --minutes 60   # 占坑 60 分钟，owner=申请人
```

任一不满足：停在预检，回报具体原因（exit2 参数 / exit4 前置），不进入确认。
占坑成功后若放弃或失败，向导执行 `ip release <lease_id>` 回收，避免地址悬挂。

---

## 4. 二次确认配置卡（S8）

所有信息归纳为一张完整卡片，要求用户显式回复“确认 / yes”：

```text
━━━━━━ 请确认虚拟机创建配置 ━━━━━━
vCenter     : lab（172.17.41.101，administrator@vsphere.local）
创建方式    : 模板克隆（克隆后自动开机）
名称        : web01-10-10-0-21-zhangsan
Owner       : zhangsan
客户机/网络 : Linux 单网卡 / 静态IP / 开机自动定制
规格        : 4 vCPU · 8 GiB 内存 · 100 GiB 系统盘（模板 60→100 扩容）
模板        : Centos7.9_2c4g60g（vm-17091）
网络        : network-1001（VLAN50，scope vlan50:10.10.0.0/23）
IP/掩码/网关: 10.10.0.21 / 255.255.254.0 / 10.10.0.1（域 local）
IP 状态     : ping 不通 + 清单无占用 + 已预留 60 分钟（owner zhangsan）
集群        : 共享存储 domain-c12391（资源池 resgroup-12392）
主机        : DRS 自动放置
数据存储    : 5020-A（datastore-28406）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
回复“确认”执行；回复“改 <项> <值>”修改；其余取消。
```

改任意项 → 回到对应 S 编号，重跑受影响预检（改 IP 要先释放旧租约、重测新 IP、重新拼名占坑）。

---

## 5. 执行（S9，克隆 + 自动开机）

### 5.1 Linux 单网卡静态 IP（原生：克隆即开机 + 定制）

```bash
# 预览（纯只读，出 awaiting_confirmation + plan_id/digest）
vcenter-aiops --profile lab deploy clone-template \
  --vm-id vm-17091 --name web01-10-10-0-21-zhangsan \
  --folder-id group-v1002 --pool-id resgroup-12392 --datastore-id datastore-28406 \
  --network-id network-1001 --cpu 4 --memory-gb 8 --disk-gb 100 \
  --ip-address 10.10.0.21 --subnet-mask 255.255.254.0 --gateway 10.10.0.1 --guest-domain local

# 第 2 次确认：对不可变计划的 digest
vcenter-aiops --profile lab plan apply <plan_id> --confirm <digest> --wait
# powerOn=true，CloneVM 后自动开机并下发 Linux 定制（主机名 = 全连字符 VM 名，合规）
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

> 默认链路全程是“模板自定义克隆”：不带 `--ip-address` 时克隆为 poweredOff（规格/网卡改配同样在克隆 spec 完成），需要联网时再按 5.1（Linux 单网卡，克隆即开机定制）或在来宾系统内配网后 `vm power-on`。**`vm create` 不属于默认环节**，仅在用户明确“没有模板、要全新空白机”时走该旁路，随后自行装系统/配网/开机。

---

## 6. 就绪核对（S9 内）

```bash
vm wait-tools   --id <new-vm-id>     # Linux 开机定制：等 Tools/IP 就绪（任务成功≠就绪）
vm inspect      --id <new-vm-id>     # 电源/主机/池/存储/CPU/内存
inventory list --kind vm            # 复核 guest.ipAddress==所选 IP、名称唯一
```

克隆任务 success 仅代表已创建/已提交定制；必须独立读到 Tools 就绪且实际 IP 正确。失败按退出码处理：exit4 前置/确认问题可修正重试；**exit6 结果未知只用 `task reconcile/task wait` 核对，绝不重发克隆**。

---

## 7. 统一结果清单（S9 末，固定格式回传）

成功后无论走哪条路径，都回传同一张卡片：

```text
✅ 虚拟机创建成功
┌──────────────┬──────────────────────────────────────────┐
│ 名称         │ web01-10-10-0-21-zhangsan                  │
│ Owner        │ zhangsan                                   │
│ IP 地址      │ 10.10.0.21/23（gw 10.10.0.1，VLAN50）       │
│ 规格         │ 4 vCPU / 8 GiB / 100 GiB                   │
│ 模板         │ Centos7.9_2c4g60g（vm-17091）              │
│ 集群         │ 共享存储 domain-c12391（resgroup-12392）    │
│ 主机         │ host-12601（DRS 放置）                     │
│ 数据存储     │ 5020-A（datastore-28406）                  │
│ 运行状态     │ poweredOn · Tools: toolsOkay · IP 已就绪    │
└──────────────┴──────────────────────────────────────────┘
plan_id=<id> · new-vm-id=vm-34624 · 创建耗时 27s
```

**字段口径（固定 9 项 + 追溯）：**

| 字段 | 取值来源 |
|---|---|
| 名称 | S6 拼出并查重后的最终 `--name`（`<业务名>-<IP点改连字符>-<Owner>`） |
| Owner | S6 申请人，同 `ip reserve --owner` |
| IP 地址 | S4 三路取证选中的地址；关机/未配网路线标注“机内配置（预留 10.10.0.21）” |
| 规格 | 实际落盘 numCPU / memoryMB/1024 / 首盘 GiB（`vm inspect` 实测值，不回显请求值） |
| 模板 | 源模板名（vm-id） |
| 集群 | 资源池 owner 计算资源名（domain-c…） |
| 主机 | 实际 runtime.host（DRS 时报告调度结果，而非“自动”） |
| 数据存储 | 实际 datastore 列表中命中的目标 |
| 运行状态 | `runtime.powerState` + Tools 状态 + IP 就绪标志（wait-tools 后读取） |
| 追溯 | plan_id、new-vm-id、耗时；便于 `task inspect/plan show` 审计 |

失败/部分成功时不输出成功卡，改为：状态、失败阶段、退出码与原因、已占 IP 的 lease_id（并提示已/将释放）、若 exit6 给出 `task reconcile` 命令，不自动重发。

---

## 8. 向导顺序速查（可直接当对话脚本）

0. **触发**：克隆/创建/新建/开一台/部署一台/加一台虚拟机 → 一律模板克隆，不问“新建还是克隆”。
1. **S1 凭据门**：`profile list` → 无可用则问 vCenter IP/用户名/密码（安全注入）→ `profile add` + `profile test`；通过后本对话复用。
2. **S2 规格**：CPU 核数 / 内存 GiB / 硬盘 GiB（回车默认 4/8/100）。
3. **S3 模板**：`template list/inspect` 列表（模板名/OS/首盘/规格/网卡/MoRef）→ 编号选择 → 磁盘只扩不缩反校。
4. **S4 网络与 IP**：网段 CIDR/掩码/网关/范围/scope（首次问、对话内复用）+ 虚拟机网络 network_id + 客户机形态；范围内逐地址三路取证建议最小可用 IP（回车/自定义/换一个）。
5. **S5 放置**：选集群 → 主机回车 DRS 或选具体主机 → 选数据存储。
6. **S6 命名**：问业务名（每台）+ Owner 申请人（每台）→ 拼 `<业务名>-<IP点改连字符>-<Owner>` → 查重（重名换 IP，不加序号）。
7. **S7 预检 + 占坑**（只读）→ `ip reserve --owner <Owner>`。
8. **S8** 全量配置卡 → 用户“确认”。
9. **S9** 预览得 digest → `plan apply --confirm`（Linux 带 IP 自动开机；其它关机克隆后机内配网再 `vm power-on`）→ wait-tools/inspect 复核 → 统一结果卡。
10. 收尾：成功转 IPAM 已用 / 失败 `ip release`；向导结束 `rm -P /tmp/.vcpw`。

---

## 9. 异常与安全要点

- **凭据不明文**：密码只经 0600 文件 + `env:VC_PASSWORD` 引用注入，不进对话、命令行参数、文档或提交；`profile add` 存的是 `password_ref` 而非密码本身；结束即 `rm -P`。
- **全程零写直到确认**：S1–S8 只有只读盘点/探测和本地 IP 占坑；远端写唯一入口是确认后的 `plan apply`。
- **ping 不通绝不当空闲**：inconclusive（探测不可用）按不可用跳过；只有“清单无占用 + 无有效租约 + ping 明确不通”才是 `available:true`。
- **占坑 TTL**：默认 `--minutes 60`，覆盖一次克隆窗口；成功转 IPAM 已用，失败/取消 `ip release`；owner 记申请人。
- **最小权限**：克隆需 DeployTemplate/CreateFromExisting/AssignVMToPool/AllocateSpace/Network.Assign；带 IP 开机另需 PowerOn/Customize。
- **未知不重发**：写后超时/结果不明 exit6，只 `task reconcile/task wait`；request_id 绑定精确目标与参数幂等。
- **命名/目标精确**：拒绝通配/零宽字符；目标文件夹同名写前 exit4。
- **Windows 等非原生定制**：向导不假装能下发 IP，明确告知“克隆关机→机内配网→开机”，结果卡 IP 字段据实标注。
- **网络 ID 缺口**：无 `network list`，改网卡所需 `network-N/dvportgroup-N` 由用户当次提供或管理员给出；省略则保留模板网卡。
- **网段不固化、对话内复用**：网段参数首次问一次并记住，后续创建复用、不再重问；不读固定网段池文件、不落盘、不跨对话。复用的是**网段参数**，每台 VM 的具体 IP 仍重新三路取证选最小可用。
- **Owner 与业务名每台问**：不做对话级复用，确保命名与租约归属精确到当次申请人/用途。