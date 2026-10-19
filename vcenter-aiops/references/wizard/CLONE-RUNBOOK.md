# 克隆创建虚拟机 Runbook —— 默认模板自定义克隆（默认关机、零自动写）

> 配套文件：
> - 规格档位：[`size-presets.yaml`](size-presets.yaml)（默认 standard = 4C/8G/100G）
> - 对话流程：[`../INTERACTIVE-VM-CREATION-WIZARD.md`](../INTERACTIVE-VM-CREATION-WIZARD.md)
> - 真机执行（含 lab 密码注入与验收表，适合带到另一个对话跑）：[`LAB-TEST-CHECKLIST.md`](LAB-TEST-CHECKLIST.md)
>
> **网段参数不是预置台账**：业务网段（CIDR/掩码/网关/可分配范围/scope）在**本对话第一次创建时由用户提供一次，向导在整段对话内记住，后续创建直接复用、不再重问**；不写死成文件、不假设办公/访客等固定网段、不跨对话保留（用户显式改才更新）。下例 `<cidr>/<mask>/<gw>/<first>/<last>/<scope>` 为该网段占位。注意复用的是网段参数，每台新 VM 的具体 IP 仍在该网段内重新三路取证选取。
>
> **铁律**
> 1. 默认只走 **`deploy clone-template` 模板自定义克隆**；不先建关机空白机。`vm create` 仅在用户明确"无模板、要空白机"时才用（需自装 OS），本 runbook 不含该旁路命令。
> 2. 盘点阶段**全部只读**；唯一在确认前发生的本地变更是 `ip reserve`（本地租约，可 `ip release` 回收）。
> 3. 远端写**只生成预览**（返回 `awaiting_confirmation` + `plan_id`/`confirmation`），**不自动 apply**；apply 必须由用户在看到配置卡后显式批准才执行。
> 4. 写后结果未知（exit6/`reconciliation_required`）只用 `task reconcile`/`task wait` 核对，**绝不重发克隆**。
>
> 命令签名以 `capabilities show "领域 动词"` 为准；全局 `--profile <P>` 写在领域命令之前。下例 profile 名记为 `<P>`。

---

## 0. 变量表（执行前由向导收集填齐）

| 占位符 | 含义 | 取值来源 |
|---|---|---|
| `<P>` | profile 名 | 已配置的 vCenter profile |
| `<tpl>` | 源模板 vm-id | `template list`（只取 `config.template=true`） |
| `<name>` | 新 VM 名 | Q1 命名规则生成 + 查重 |
| `<folder>` | 目标 VM 文件夹 MoRef | 盘点（如 group-v1002） |
| `<pool>` | 目标资源池/计算资源 | 盘点（如 resgroup-12392） |
| `<host>` | 目标主机（可空） | `host info`；**省略=集群 DRS 自动放置** |
| `<ds>` | 数据存储 MoRef | `datastore list/inspect` |
| `<net>` | 网络/端口组（可空） | 外部已知 network-N / dvportgroup-N；**省略=保留模板网卡** |
| `<size>` | 规格参数串 | `size-presets.yaml`，默认 `--cpu 4 --memory-gb 8 --disk-gb 100` |
| `<cidr>/<mask>/<gw>` | 业务网段 CIDR/掩码/网关 | **本对话首次创建时用户提供一次、对话内记住**，后续创建复用；不读固定台账 |
| `<first>`/`<last>` | 可分配 IP 下界/上界 | 由该网段参数推出（排除网络/广播/网关/保留）；网段在对话内复用，区间随之复用 |
| `<scope>` | IP scope 标签 | 该网段约定的字符串，常用 `vlan<号>:<cidr>`（如 `vlan50:10.10.0.0/23`），仅标签不解析 CIDR |
| `<ip>`/`<dom>` | 选中 IP / 来宾域 | Q7 三路取证选中；域默认 `local` |
| `<plan_id>` / `<confirm>` | 计划 ID / 本轮确认值 | 预览返回 `data.id` / `data.confirmation` |
| `<lease>` | IP 租约 ID | `ip reserve` 返回 |
| `<newvm>` | 新 VM 的 vm-id | 克隆成功后从结果/`inventory list` 取 |

---

## 1. 连通与权限（只读）

```text
vcenter-aiops --profile <P> profile test
```

失败即停（exit2 配置 / exit3 连接 / exit4 权限前置），不进入后续。

---

## 2. 盘点可选项（只读，只给真实存在的对象）

```text
vcenter-aiops --profile <P> template list --limit 200
vcenter-aiops --profile <P> template inspect --id <tpl>
vcenter-aiops --profile <P> cluster list --limit 100
vcenter-aiops --profile <P> host info --id <host>            # 仅当需要绑定主机；否则省略走 DRS
vcenter-aiops --profile <P> datastore list --limit 200
vcenter-aiops --profile <P> datastore inspect --id <ds>
vcenter-aiops --profile <P> inventory list --kind vm --limit 1000
```

盘点判定（向导据此过滤，不向用户给无效选项）：
- 模板：`config.template=true`、connected；读**首盘容量**用于磁盘只扩不缩校验。
- 存储：accessible/normal、`freeSpace > 目标盘容量`；指定主机时只列该主机可见存储。
- 主机：∈ 目标集群、connected、非维护、能见到所选存储与网络。
- 名称：用 `inventory list` 查重；同名递增序号，不覆盖、不模糊匹配。
- 无可用模板：**不静默回退空白机**，提示用户显式决定是否走 `vm create` 旁路。

---

## 3. 选 IP（网段对话内复用；每台仍三路取证选最小可用；本地占坑）

本对话第一次创建时，先向用户问清并在对话内记住：网络 CIDR、点分掩码、网关、可分配范围（首尾）、保留段、scope 标签。**之后再创建直接复用这套网段参数，不再重问**（用户显式改才更新）。向导不内置、不假设任何固定网段，也不落盘、不跨对话保留。

每台新 VM 的**具体 IP 不跨机复用**：始终在该网段可分配下界 `<first>` 起逐地址探测（前序机器已占用/预留的地址会被三路信号挡掉）：

```text
vcenter-aiops --profile <P> ip available --address <candidate> --scope "<scope>"
```

- `data.available == true`（清单无占用 + 无有效租约 + ping 明确不通）→ 选中，停。
- reasons 含 `ping_inconclusive` → 当不可用，下一个，**绝不猜空闲**。
- reasons 含 `inventory_use` / `active_lease` / ping 可达 → 下一个。
- 到 `allocatable.last` 仍无 → 报"网段无可分配地址"，请用户扩范围/换网段。

选中后**占坑**（这是确认前唯一的本地写，可回收）：

```text
vcenter-aiops --profile <P> ip reserve --scope "<scope>" --ip <ip> --owner "<name>" --minutes 60
```

记录返回的 `<lease>`。用户放弃、改 IP 或后续失败时回收：

```text
vcenter-aiops --profile <P> ip release <lease>
```

> 改 IP：先 release 旧 `<lease>`，再对新地址重跑 `ip available` + `ip reserve`。

---

## 4. 预检（只读 + 本地，零远端变更）

- 模板首盘 < 目标 `disk_gb`（只扩不缩；standard 要求模板首盘 ≤ 100GB）。
- 数据存储空闲 > 目标盘容量；放置自洽（主机∈集群、可见存储/网络）。
- 名称在目标文件夹内唯一、合法（1–80 字符，无路径/百分号/控制符/边缘空白）。
- IP 已 `available:true` 且已 reserve。

任一不满足：停在预检，回报 exit2/exit4 具体原因，不生成写计划。

---

## 5. 生成克隆预览（不提交）

### 5A. Linux + 单网卡 + 静态 IP（克隆即开机 + 来宾定制）

> 仅此组合能用内置 `LinuxPrep`（ip/掩码/网关/域，**无 DNS**）。给 `--ip-address` 即 `powerOn=true`。

```text
vcenter-aiops --profile <P> deploy clone-template \
  --vm-id <tpl> --name <name> \
  --folder-id <folder> --pool-id <pool> --datastore-id <ds> \
  [--host-id <host>] [--network-id <net>] \
  <size> \
  --ip-address <ip> --subnet-mask <mask> --gateway <gw> [--guest-domain <dom>]
```

### 5B. Windows / DHCP / 多网卡 / 需 DNS（关机克隆，机内配网后再开机）

> 不带 `--ip-address`：克隆为 poweredOff；规格/网卡改配同样在克隆 spec 完成。

```text
vcenter-aiops --profile <P> deploy clone-template \
  --vm-id <tpl> --name <name> \
  --folder-id <folder> --pool-id <pool> --datastore-id <ds> \
  [--host-id <host>] [--network-id <net>] \
  <size>
```

以上两条**默认即只产出预览**：非交互返回 `awaiting_confirmation`，交互终端可看预览但不替用户确认。从返回取 `data.id`→`<plan_id>`、`data.confirmation`→`<confirm>`（过期或中断后会重签，不能沿用旧 digest）。

`deploy clone-template` 为 `risk=change`（非销毁），apply **只需** `--confirm <confirm>`，不需要 `--confirm-destruction`。

---

## 6. 二次确认（人工）—— 配置卡通过后才执行

向用户展示配置卡（向导 S5），用户显式"确认"后，才运行：

```text
vcenter-aiops --profile <P> plan apply <plan_id> --confirm <confirm> --wait
```

- 配置卡任一项被修改 → 回到对应 Q，重跑受影响预检，**重新预览**（digest 会变，旧 confirm 作废）。
- 未获用户明确批准：不要 apply；预览计划保留，IP 租约到期或主动 `ip release` 回收。

5B 关机克隆在 apply 成功、且来宾系统内已完成配网后，再单独走开机（同样先预览后确认）：

```text
vcenter-aiops --profile <P> vm power-on --vm-id <newvm>          # 先预览
vcenter-aiops --profile <P> plan apply <plan2_id> --confirm <confirm2> --wait
```

---

## 7. 就绪核对（只读，任务成功 ≠ 来宾就绪）

```text
vcenter-aiops --profile <P> vm wait-tools --vm-id <newvm>
vcenter-aiops --profile <P> vm inspect --id <newvm>
vcenter-aiops --profile <P> inventory list --kind vm --limit 1000
```

- 5A：必须独立读到 Tools 就绪且 guest.ipAddress == `<ip>`。
- 5B：以 `vm inspect` 电源状态 + 机内配网结果为准。
- 超时/结果不明（exit6/`reconciliation_required`）：

```text
vcenter-aiops --profile <P> task reconcile <operation_id>
vcenter-aiops --profile <P> task wait <operation_id>
```

**不重发克隆**；响应全丢失先 `task list`，按 request_id/服务端/对象身份定位，不猜测匹配。

---

## 8. 收尾：IP 租约

- 成功：预留地址转为已用事实（结果卡记录），保留租约便于对账，或按团队 IPAM 流程核销。
- 取消/失败：`ip release <lease>` 回收，避免地址悬挂。

---

## 9. 统一结果卡（S8，取实测值，不回显请求值）

```text
✅ 虚拟机创建成功
名称       : <name>
IP 地址    : <ip>/<prefix>（gw <gw>，VLAN）        # 5B 标注"机内配置（预留 <ip>）"
规格       : <cpu> vCPU / <mem> GiB / <disk> GiB   # vm inspect 实测
集群       : <compute-resource 名>
主机       : <runtime.host 实测>（DRS 报告调度结果，不写"自动"）
数据存储   : <datastore 名>
模板       : <模板名>（<tpl>）
运行状态   : poweredOn · Tools: <toolsStatus> · IP 就绪
plan_id=<plan_id> · new-vm-id=<newvm>
```

失败/部分成功不出成功卡：给状态、失败阶段、退出码与原因、`<lease>`（及是否已释放）；exit6 附 `task reconcile` 命令。

---

## 附：完整示例（仅算例；网段/IP 为假设值，实际取本对话首次提供并记住的网段，仅演示到预览）

> 下例 `10.10.0.0/23`、`vlan50:...`、`10.10.0.21` 等**只是占位算例**，不是预置网段；真实运行时网段参数在本对话第一次创建时由用户提供一次、后续直接复用。

```text
# 1) 连通
vcenter-aiops --profile lab profile test

# 2) 盘点（只读，省略 host 走 DRS）
vcenter-aiops --profile lab template inspect --id vm-17091
vcenter-aiops --profile lab datastore inspect --id datastore-28406
vcenter-aiops --profile lab inventory list --kind vm --limit 1000

# 3) 本对话已记住的网段（示例 10.10.0.0/23，可分配从 10.10.0.10 起）：逐地址探测最小可用，通过后占坑
vcenter-aiops --profile lab ip available --address 10.10.0.21 --scope "vlan50:10.10.0.0/23"
vcenter-aiops --profile lab ip reserve --scope "vlan50:10.10.0.0/23" --ip 10.10.0.21 \
  --owner mumian-office-021 --minutes 60

# 4) 克隆预览（Linux 带 IP，克隆即开机+定制）——到此为止，等待人工确认
vcenter-aiops --profile lab deploy clone-template \
  --vm-id vm-17091 --name mumian-office-021 \
  --folder-id group-v1002 --pool-id resgroup-12392 --datastore-id datastore-28406 \
  --cpu 4 --memory-gb 8 --disk-gb 100 \
  --ip-address 10.10.0.21 --subnet-mask 255.255.254.0 --gateway 10.10.0.1 --guest-domain local

# 5) 用户确认配置卡后才执行（值来自上一步返回，勿手抄旧 digest）
# vcenter-aiops --profile lab plan apply <plan_id> --confirm <confirm> --wait

# 6) 就绪核对
# vcenter-aiops --profile lab vm wait-tools --vm-id <newvm>
```
