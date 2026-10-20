# 克隆创建虚拟机 —— 实机演练手册（跨对话执行版）

> 用途：把这份手册带到**另一个对话**里做真机测试。那个对话只需按本手册顺序执行、回填实测 ID，不依赖当前对话上下文。
>
> **执行前必读三条铁律**
> 1. 默认只走 **`deploy clone-template` 模板自定义克隆**，不先建关机空白机；`vm create` 仅在用户明确"无模板、要空白机"时才用。
> 2. 进入执行前的盘点/取证全部**只读 + 本地占坑**（对应状态机 S1–S7）；远端写**只生成预览**（`awaiting_confirmation`），**必须用户看到配置卡显式批准后**才 `plan apply`（S8→S9）。
> 3. 写后结果未知（exit6 / `reconciliation_required`）只用 `task reconcile/wait` 核对，**绝不重发克隆**。
>
> 环境事实（已核对）：profile 名 **`lab`**，vCenter `172.17.41.101:443`，user `administrator@vsphere.local`，`password_ref=env:VC_PASSWORD`，`verify_tls=false`。命令经 `./run.sh`（自动 `export PYTHONPATH=src`，可用 `VCENTER_AIOPS_PYTHON` 指解释器）。工作目录：`vcenter-aiops/`。
>
> 命令签名以注册的 112 条为准；位置参数：`plan apply <plan_id>`、`ip release <lease_id>`、`task reconcile|wait|inspect <operation_id>`，不要加 `--xxx-id`。

---

## 0. 给新对话的启动指令（复制给对方）

> 请打开 `vcenter-aiops/references/wizard/LAB-TEST-CHECKLIST.md`，严格按它对 lab 环境做一次"模板克隆创建虚拟机"实机演练。我会在本次对话提供 vCenter 密码和业务网段参数；你只做只读盘点与预览，**任何 `plan apply` 之前都要先把配置卡发我确认**。网段参数本次给一次，后续创建直接复用、不要重复问。

---

## 1. 前置准备（在跑命令的本机终端，由用户执行）

### 1.1 注入密码（不进对话、不入 shell 历史）

密码只放进 0600 临时文件，命令用 `VC_PASSWORD="$(cat /tmp/.vcpw)"` 注入，绝不打印：

```bash
( umask 077; read -rs -p 'VC password: ' p; printf '%s' "$p" > /tmp/.vcpw; echo; echo "written $(wc -c < /tmp/.vcpw) bytes" )
chmod 600 /tmp/.vcpw
```

> 演练结束必须清除（见第 9 步）：`rm -P /tmp/.vcpw`。

### 1.2 解释器（如 run.sh 默认 python3 缺依赖）

```bash
export VCENTER_AIOPS_PYTHON=/Users/hua/.workbuddy/binaries/python/envs/vcenter-aiops/bin/python
```

### 1.3 约定调用前缀

下面用 `RUN` 代表：

```bash
VC_PASSWORD="$(cat /tmp/.vcpw)" ./run.sh --profile lab <命令>
```

---

## 2. 首次提供网段参数（本对话给一次，记住并复用）

在新对话里由用户**一次性**提供（agent 对话内记住，不写文件、不跨对话）：

| 字段 | 本对话取值（待填） |
|---|---|
| 网络 CIDR | `<CIDR>` 例 10.10.0.0/23 |
| 点分掩码 | `<MASK>` 例 255.255.254.0 |
| 网关 | `<GW>` 例 10.10.0.1 |
| 可分配范围 | `<FIRST>` – `<LAST>`（默认排除网络/广播/网关/.2–.9） |
| scope 标签 | `<SCOPE>` 建议 `vlan<号>:<CIDR>` |
| vSphere 端口组 | `<NET_ID>` = `network-N` 或 `dvportgroup-N`（不知道就在第 4 步盘点确认；省略=保留模板网卡） |

agent 收到后做一次纯本地合法性自检（不联网）：CIDR/掩码连续、FIRST/LAST 落在网段内且非网络/广播/网关。**之后再创建直接复用这套参数，不再询问；用户显式说改才更新。** 复用的是网段，每台具体 IP 仍要重新三路取证。

---

## 3. 连通与身份核对（只读；对应状态机 S1 凭据门的 test 环节）

> lab profile 已预配（见文首环境事实），凭据在第 1 步注入；这里只做 `profile test`。若是全新环境/无 profile，先按向导 S1 问齐 vCenter IP/用户名/密码并 `profile add`，再 test。

```bash
RUN profile test
```

- 期望 `status=succeeded`、`target.profile=lab`、返回 server 信息。
- exit2 配置错 / exit3 连不上 / exit4 权限前置：停下排查，不进入后续。

---

## 4. 只读盘点（对应状态机 S3 选模板 / S5 放置的盘点取数；只记录真实存在的对象）

```bash
RUN template list --limit 200
RUN cluster list --limit 100
RUN datastore list --limit 200
RUN inventory list --kind vm --limit 1000
# 需要绑定具体主机时才跑（默认 DRS 可省略）：
RUN host info --id <HOST_ID>
```

对候选模板逐个看首盘容量与客户机 OS（决定磁盘只扩不缩、能否用内置 Linux 定制）：

```bash
RUN template inspect --id <TPL_ID>
RUN datastore inspect --id <DS_ID>
```

盘点判定（回填到第 7 步配置卡）：
- 模板：`config.template=true`、connected；记录**首盘容量** `<TPL_DISK_GB>`、客户机 OS、自带网卡/网络。
- 存储：accessible/normal、`freeSpace` > 目标盘；指定主机时只选该主机可见存储。
- 主机（若指定）：∈ 目标集群、connected、非维护、能见到所选存储/网络；否则省略 `--host-id` 走 DRS。
- 命名查重：用 `inventory list` 确认目标名不存在；**重名=该 IP 已占用，换空闲 IP 重拼，不递增序号**。名称公式 `<BIZ>-<IP 点改连字符>-<OWNER>`（如 `web01-10-10-0-21-zhangsan`）。
- 记录放置事实：`<FOLDER_ID>`（VM 文件夹）、`<POOL_ID>`（资源池/计算资源）。

> 历史环境参考（**必须以本次盘点实测为准，不得照抄**）：曾见模板 vm-17091 `Centos7.9_2c4g60g`（首盘 60GB）、存储 datastore-28406（5020-A）、资源池 resgroup-12392、文件夹 group-v1002、集群 domain-c12391、主机 host-12601。

---

## 5. 逐轮选择（S1–S9，agent 只给盘点可选项，严格按序）

| 轮次 | 问什么 | 默认/规则 |
|---|---|---|
| S1 | vCenter 连接（IP/用户名/密码） | 已有可连通 profile 则复用；否则问齐三件，安全注入后 `profile add`+`profile test`，通过才继续 |
| S2 | 规格：CPU 核数/内存 GiB/硬盘 GiB | 回车=**4 核/8GiB/100GiB**；要求 `disk_gb > <TPL_DISK_GB>`（选模板后反校，只扩不缩） |
| S3 | 克隆模板 | `template list/inspect` 列真模板（名/OS/首盘/规格/网卡/MoRef），编号选 `<TPL_ID>` |
| S4 | 网络与 IP：网段 CIDR/掩码/网关/范围/scope + 虚拟机网络 `<NET_ID>` + 客户机形态 | 网段本对话首次给、后续复用；客户机形态决定 **5A** Linux+单网卡+静态+无 DNS 克隆即开机，其它走 **5B** 关机克隆；在 `<FIRST>..<LAST>` 内自动找最小可用 IP |
| S5 | 放置：集群/主机/数据存储 | 编号选 `<POOL_ID>`；主机回车=DRS（省略 host_id）或选 connected 非维护主机；存储选 freeSpace 足够且主机可见的 `<DS_ID>` |
| S6 | 业务名 `<BIZ>` + 申请人 `<OWNER>`（每台都问） | 拼名 **`<BIZ>-<IP 点改连字符>-<OWNER>`**（如 web01+10.10.0.21+zhangsan → `web01-10-10-0-21-zhangsan`），查重；重名换空闲 IP 重拼不加序号；OWNER 同值用于 `ip reserve --owner` |

### S4 自动选最小可用 IP（严格，含占坑）

从 `<FIRST>` 起逐地址：

```bash
RUN ip available --address <CANDIDATE> --scope "<SCOPE>"
```

- `data.available=true`（清单无占用 + 无有效租约 + ping 明确不通）→ 选中停。
- reasons 含 `ping_inconclusive` → 当不可用，下一个，**绝不猜空闲**。
- 含 `inventory_use`/`active_lease`/`ping_reachable` → 下一个。
- 到 `<LAST>` 仍无 → 报"网段无可分配地址"，请用户扩范围/换网段，不硬选。

选中后占坑（确认前唯一本地写）：

```bash
RUN ip reserve --scope "<SCOPE>" --ip <IP> --owner "<OWNER>" --minutes 60
```

记录返回租约 `<LEASE>`。放弃/改 IP/失败时回收：`RUN ip release <LEASE>`。

---

## 6. S7 预检（只读 + 本地，零远端变更）

- `<TPL_DISK_GB>` < 目标 `disk_gb`（只扩不缩）。
- 数据存储 freeSpace > 目标盘；放置自洽（主机∈集群、可见存储/网络）。
- 名称合法且在目标文件夹唯一（1–80 字符，无 `/ %`、控制符、边缘空白）。
- IP `available=true` 且已 reserve。

任一不满足：停在预检，回报 exit2/exit4 原因，不生成写计划。

---

## 7. S8 配置卡（第一次确认）+ 生成预览

把下面卡片用实测值填好发用户，**等显式"确认"**：

```text
━━━━━━ 请确认虚拟机创建配置 ━━━━━━
创建方式 : 模板克隆（5A=克隆后自动开机+定制 / 5B=关机克隆）
名称     : <NAME>                 # <BIZ>-<IP 点改连字符>-<OWNER>
Owner    : <OWNER>
客户机   : <OS> / <单|多>网卡 / <静态|DHCP>
规格     : <CPU> vCPU · <MEM> GiB · <DISK> GiB（模板 <TPL_DISK_GB>→<DISK> 仅扩容）
模板     : <模板名>（<TPL_ID>）
网络     : <NET_ID 或"保留模板网卡">（scope <SCOPE>）
IP/掩码/网关: <IP>/<MASK>/<GW>（域 local）  [5B 标注"机内配置（预留 <IP>）"]
集群     : <POOL_ID>（<计算资源名>）
主机     : DRS 自动放置 或 <HOST_ID>
数据存储 : <DS_ID>（<存储名>）
IP 状态  : ping 不通 + 清单无占用 + 已预留 60 分钟（owner <OWNER>，lease <LEASE>）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
回"确认"执行；"改 <项> <值>"修改（改 IP 先 release 旧租约再重测重占、重拼名）。
```

### 5A Linux 单网卡静态（克隆即开机 + LinuxPrep 定制，无 DNS）

```bash
RUN deploy clone-template \
  --vm-id <TPL_ID> --name <NAME> \
  --folder-id <FOLDER_ID> --pool-id <POOL_ID> --datastore-id <DS_ID> \
  [--host-id <HOST_ID>] [--network-id <NET_ID>] \
  --cpu 4 --memory-gb 8 --disk-gb 100 \
  --ip-address <IP> --subnet-mask <MASK> --gateway <GW> --guest-domain local
```

### 5B Windows / DHCP / 多网卡 / 需 DNS（关机克隆，不带 ip_*）

```bash
RUN deploy clone-template \
  --vm-id <TPL_ID> --name <NAME> \
  --folder-id <FOLDER_ID> --pool-id <POOL_ID> --datastore-id <DS_ID> \
  [--host-id <HOST_ID>] [--network-id <NET_ID>] \
  --cpu 4 --memory-gb 8 --disk-gb 100
```

> 非交互返回 `awaiting_confirmation`，从 `data.id` 取 `<PLAN_ID>`、`data.confirmation` 取 `<CONFIRM>`（会过期，中断后重签，不沿用旧值）。`clone-template` 是 change 级，apply **只需 digest，不需要 DESTROY**。

---

## 8. S9 用户批准后执行（第二次确认）+ 就绪核对

**仅在用户对配置卡回复"确认"后：**

```bash
RUN plan apply <PLAN_ID> --confirm <CONFIRM> --wait
```

5A 成功后核对就绪（任务成功 ≠ 来宾就绪）：

```bash
RUN vm wait-tools --vm-id <NEWVM>
RUN vm inspect --id <NEWVM>
RUN inventory list --kind vm --limit 1000
```

- 5A：必须读到 Tools 就绪且 guest.ipAddress == `<IP>`。
- 5B：克隆为 poweredOff，机内配网后再单独走开机（同样先预览后确认）：

```bash
RUN vm power-on --vm-id <NEWVM>                       # 先预览
RUN plan apply <PLAN2_ID> --confirm <CONFIRM2> --wait
```

结果未知（exit6 / reconciliation_required）——**不重发克隆**：

```bash
RUN task inspect <OP_ID>
RUN task reconcile <OP_ID>
RUN task wait <OP_ID>
```

---

## 9. 收尾

- 成功：结果卡（下）记录实测值；IP 租约按团队 IPAM 核销或保留对账。
- 取消/失败：`RUN ip release <LEASE>` 回收。
- **清除密码文件**：`rm -P /tmp/.vcpw`。

---

## 10. S9 统一结果卡（取 vm inspect / inventory 实测值，不回显请求值）

```text
✅ 虚拟机创建成功
名称     : <NAME>                 # <BIZ>-<IP 点改连字符>-<OWNER>
Owner    : <OWNER>
IP 地址  : <IP>/<PREFIX>（gw <GW>）        # 5B 写"机内配置（预留 <IP>）"
规格     : <CPU>/<MEM>GiB/<DISK>GiB（实测）
模板     : <模板名>（<TPL_ID>）
集群     : <计算资源名>
主机     : <runtime.host 实测>（DRS 报实际调度结果，不写"自动"）
数据存储 : <存储名>
运行状态 : poweredOn · Tools <toolsStatus> · IP 就绪
plan_id=<PLAN_ID> · new-vm-id=<NEWVM>
```

---

## 11. 验收记录（真机矩阵，演练后回填）

| 项 | 实测 | 备注 |
|---|---|---|
| vCenter/ESXi build | | |
| profile test | | |
| 模板/首盘/OS | | 验证磁盘只扩不缩 |
| 集群/主机(DRS)/存储 | | 放置自洽 |
| 网段/scope/选中 IP | | 三路 available=true |
| 5A 或 5B | | clone 预览 digest / apply |
| Tools/guest.ipAddress | | wait-tools 通过 |
| exit6 恢复路径 | | 如触发：reconcile/wait，无重发 |
| 租约回收/密码清除 | | release + rm -P |
