# vcenter-aiops 功能清单（按功能模块）

> 版本：**3.0.0rc1**（release-candidate，发布候选；功能冻结，真机矩阵待验收）。真值来源：`src/vcenter_aiops/application/registry.py` 的 `COMMANDS`（运行时实测 **112 条**）与各 `registrations/*` 子模块；本文据运行时注册表导出，已脚本校验 20 个模块并集 = 112 条，**无遗漏 / 无重复 / 无未注册命令**。
> 实机兼容：所有远端命令对 vSphere **6.5 / 6.7 / 7.0 / 8.0 的兼容状态均为 `not_lab_verified`**（离线测试 ≠ 实机验收）。**GA 真机门（2026-10-21 收敛）只要求 7.0+ 与 8.0+ 两条线逐「写入动作」验证**（成功路径 + fail-closed 拒绝；只读不阻断）；6.5/6.7 无真机环境、不作为 GA 阻断项，但保留 `not_lab_verified` 设计声明，不宣称已验证。命令签名、特权核权、二次确认与“未知不重发”为不可变核心语义。

## 0. 总览

- **命令总数 112**，按类别：本地只读 23 · 本地写 15 · 远端只读 31 · 远端写 35 · 编排 orchestration 8。
- **CLI 风险分级**（真值 `domain/risk.py`）：低 54 · 中 43 · 高 15。
  - 低：只读 / 预览，直接执行。
  - 中：敏感但可逆 / 增量（凭据、导出、系统配置、来宾执行、终止等），交互须确认值，非 TTY 须 `--yes/-y`。
  - 高：不可逆（删除 / 清空 / 覆盖 / 批量 / 终止），先列精确目标再二次确认（DELETE/CLEAR/OVERWRITE/TERMINATION）；`--yes` 不放宽精确目标校验。
- **MCP 暴露**：73 条（未特别标注者默认暴露；标注“仅 CLI”的不暴露）。**异步任务**：32 条（远端 Task，带回执 + 核对）。**声明所需特权**：39 条。
- **Provider 分布**：vm 95 · guest 7 · cluster 3 · host 2 · ovf 2 · membership / creation / template_clone 各 1。

### 0.1 全局通用选项（适用所有命令，表内不重复列出）

| 选项 | 说明 |
|---|---|
| `--profile <名>` | 选择连接配置；远端命令及按 Profile 隔离的本地数据（cache/preset 等）需要 |
| `--timeout <1–3600>` | 等待预算秒数；超时后远端写走“核对 / 未知”，不重发 |
| `--json` | 输出 JSON；exit 5 时附 `category`（business_failure / internal_error） |
| `--yes` / `-y` | 非交互跳过中 / 高风险确认提示；**不替代**精确目标与 digest/DESTROY 校验 |
| `--debug-log` / `VCENTER_AIOPS_DEBUG_LOG=1` | exit 5 时落 0600 脱敏诊断日志（默认关） |

远端写命令（`change(...)` 注册族）统一携带三个写选项：`--dry-run`（默认 false，仅预览）、`--request-id`（幂等键，绑定目标与参数）、`--wait`（默认 true）。表内记作“**+写选项**”。

### 0.2 退出码

`0` 成功 · `2` 参数错误 · `3` 依赖/配置/连接/本地存储不安全 · `4` 前置/身份/确认/写前被拒 · `5` 失败或部分成功 · `6` 需人工核对（结果未知，绝不自动重发）。远端写不直接提交：先返回 `awaiting_confirmation`，再用 `plan apply <id> --confirm <digest>`（不可逆另加 `--confirm-destruction DESTROY:<digest>`）执行。

### 0.3 “已注册但当前不可执行 / 受限”的命令（重点）

| 命令 | 状态 | 原因 |
|---|---|---|
| `vm delete` | **受控放行（仍高风险）** | 已开受控通道：全 vCenter 清单扫描证明本 vCenter 内无其他 VM/模板/快照引用其磁盘链，且显式 `--allow-shared-datastore` 担保（跨 vCenter/独立 ESXi 不可见），再经 `plan apply` 双重确认才销毁；任一证据缺失或发现消费者仍 fail-closed（`dependency_present`/`dependency_unproven`） |
| `vm snapshot-revert` | **注册但当前拒绝执行** | 无有界清单谓词可证明安全，全局 fail-closed，无担保通道 |
| `vm snapshot-delete` | **注册但当前拒绝执行** | 同上，拒绝清理快照 |
| `vm migrate`（带 `datastore_id`） | **受限** | 仅允许明确“无磁盘且无 NVDIMM”的计算迁移（省略 datastore_id）；带磁盘缺 PBM 策略证据、指定存储均拒绝 |
| `alarm reset` | **能力受限** | vSphere 6.7+；只能按类型(vm/host)+状态(red/yellow)批量清除，不能定位单告警/单实体/集群/数据存储 |
| `batch power-on/off`、`batch shutdown`、`batch reset` | **只构建计划，不直接变更** | 生成固定对象计划，须再经 `plan apply` 确认执行 |
| 全部远端命令 | **未实机验收** | 6.5/6.7/7.0/8.0 为 not_lab_verified；GA 真机门只要求 7.0+/8.0+ 逐写入动作验证（只读不阻断）；OVA/OVF、Guest 三命令、alarm reset 已离线验收、待真机写入验收 |

---

## 1. 系统自检与版本（4）

本地、不联网（doctor 默认）、不建状态，用于确认版本、依赖与命令契约。

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `version` | 查看开发版本与产品名 | 无 | 低风险；不联网不建状态 |
| `doctor` | 检查本机依赖（pyVmomi、cryptography 等） | `--connect` 默认 false | 默认只做本机检查；显式 `--connect` 才验证连接 |
| `capabilities list` | 列出全部命令实现与版本验证状态 | 无 | 输出 112 条 describe；含 remaining_domains 与限制 |
| `capabilities show <command_path>` | 查看单条叶子参数 schema 与风险 | `command_path` 必填（位置） | 机器契约查询，不执行动作 |

## 2. 连接 Profile 管理（6）

本地连接配置（host / 凭据引用 / TLS），密码以 `password_ref` 引用、不回显。

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `profile list` | 列出全部连接配置 | 无 | 不显示密码 |
| `profile show <name>` | 查看指定配置 | `name` 必填 | 不显示密码 |
| `profile add` | 新增连接配置 | `name` `host` `user` `password_ref` 必填 | `--port`(默认443,1–65535)、`--ca-file`、`--insecure`(默认false)；中风险 |
| `profile update` | 只更新显式给出的字段 | `name` 必填；`host/user/password_ref/port/ca_file/insecure` 任选 | 未给字段不变；中风险 |
| `profile delete <name>` | 删除本地配置 | `name` 必填 | 高风险，需精确确认；仅删本地，不触碰远端 |
| `profile test` | 验证连接与服务端身份（instanceUuid） | 需 `--profile` | 远端只读；防同名 vCenter 误连 |

## 3. IP 租约与空闲探测（6）

本地事务租约 + 远端资产/ping 三路信号。**预留 ≠ 网络空闲证明**，过期也不自动判空闲。

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `ip reserve` | 作用域内事务预留一个 IP | `scope` `ip` `owner` 必填 | `--minutes` 可选正整数（不给不过期）；中风险 |
| `ip release <lease_id>` | 释放精确租约 | `lease_id` 必填（位置，32 位 token） | 高风险；只能按租约 ID 释放，不按 IP 批量 |
| `ip list` | 列出租约 | `--scope` 可选 | 本地只读 |
| `ip check` | 汇总资产占用 + 本地租约 + ping 三路信号 | `address` `scope` 必填 | 远端只读；**ping 不通不判空闲** |
| `ip available` | 仅有正向空闲证据时返回“可用” | `address` `scope` 必填 | 证据不足返回“不确定”，不自动分配 |
| `ip expire` | 列出过期租约 | `--apply` 默认 false | 真正释放须 `--apply --lease-id <精确ID>` |

## 4. 资产只读查询（14）

批量清单 / 精确对象 / 事件 / 容量预检，全部只读不变更。

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `inventory list` | 批量读取资产 | `--kind {vm/host/cluster/datastore}` 默认 vm；`--limit` 默认100 | PropertyCollector 分页 |
| `inventory export` | 导出资产到新文件 | `--file` 必填；`--kind`；`--format {json/csv}` 默认 json；`--limit` 默认100(≤1000) | 不覆盖已有文件；外部字段转义；中风险（外发）；仅 CLI |
| `events list` | 按对象/时间/类型查事件 | `--vm-id/--host-id/--since/--event-type` 可选；`--limit` 默认100 | 只读不变更 |
| `quota check` | 变更前容量预检 | `cluster_id/host_id/datastore_id/cpu/memory_gb/storage_gb` 均可选 | 只预检不预留；缺字段返回“不可用” |
| `vm list` | 查看 VM 清单 | `--limit` 默认100 | — |
| `vm inspect` | 精确查看单个 VM | **二选一**：`--id` 或 `--name` | one-of，须且仅一个选择器 |
| `template list` | 仅查询模板 | `--limit` 默认100 | 排除普通 VM |
| `template inspect` | 精确查询模板 | **二选一**：`--id` 或 `--name` | 排除普通 VM |
| `host info` | 精确查看主机 | **二选一**：`--id` 或 `--name` | — |
| `cluster list` | 查看集群清单 | `--limit` 默认100 | — |
| `cluster info` | 精确查看集群 | **二选一**：`--id` 或 `--name` | — |
| `datastore list` | 查看数据存储清单 | `--limit` 默认100 | — |
| `datastore inspect` | 精确查看数据存储 | **二选一**：`--id` 或 `--name` | — |
| `alarm list` | 读取对象及后代的可见触发告警 | `--entity-id` 可选（省略查根及后代）；`--status {red/yellow/green/gray}`；`--limit` | 只读取，不确认/不重置 |

## 5. 数据存储搜索与缓存（8）

持久化 DatastoreBrowser 搜索任务（ISO/OVA/OVF 发现）+ 资产只读缓存（TTL 300 秒）。

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `datastore browse` | 浏览数据存储目录 | `--datastore-id` 必填；`--path` 默认空；`--recursive` 默认 false；`--limit` 默认100；`--request-id`；`--wait` 默认true | 异步；需 `Datastore.Browse`；显式 recursive 才含子目录 |
| `datastore scan` | 发现 ISO/OVA/OVF，持久化搜索任务 | 同 browse | 异步；需 `Datastore.Browse`；**只发现不部署** |
| `datastore search-status <search_id>` | 核对原搜索任务 | `search_id` 必填（位置）；`--wait` 默认false | 不重新搜索；丢响应后凭回执核对 |
| `datastore search-inspect <search_id>` | 查看本地搜索记录与已存结果 | `search_id` 必填 | 本地只读；仅 CLI |
| `datastore search-list` | 列出当前 Profile 搜索记录 | `--limit` 默认100 | 本地只读；仅 CLI |
| `cache status` | 离线查看缓存年龄/来源/服务端身份 | `--kind {vm/host/cluster/datastore}` 必填 | 本地只读；TTL 300；仅 CLI |
| `cache refresh` | 从远端只读刷新缓存 | `--kind` 必填 | 远端只读；最多 1000 项并限制快照字节 |
| `cache invalidate` | 删除指定 Profile+类型的服务端缓存 | `--kind` 必填 | 本地写、高风险（清空该类缓存）；令牌绑定 profile+kind；仅 CLI |

## 6. 告警处置（2）

对已触发告警的确认与批量重置。

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `alarm acknowledge` | 确认精确实体上的告警 | `--entity-id` `--alarm-id` 必填 +写选项 | 中风险；只表知悉，不代表故障恢复；非异步 |
| `alarm reset` | 按类型+状态批量清除触发告警 | `--entity-type {vm/host}` 必填；`--statuses` 数组（默认 red+yellow，只允许 red/yellow）+写选项 | 需 `Alarm.SetStatus`；**6.7+**；不能定位单告警/单实体/集群/数据存储；预览绑定精确告警集合 |

## 7. VM 电源 / 快照 / 配置（14）

单台 VM 生命周期写操作与只读状态查询。写命令均先预览、异步、携带写选项。

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `vm snapshot-list` | 读取带精确快照 ID 的快照树 | `--vm-id` 必填；`--limit` | 只读 |
| `vm tools-status` | 读取 VMware Tools 状态 | `--vm-id` 必填 | 缺失字段不编造 |
| `vm wait-tools` | 限时等待 Tools 就绪 | `--vm-id` 必填 | 只读等待，不修改 VM |
| `vm power-on` | 预览并开机 | `--vm-id` +写选项 | `VirtualMachine.Interact.PowerOn` |
| `vm shutdown` | 优雅关机（Guest 关机） | `--vm-id` +写选项 | `…PowerOff`；**不回退**强制关机 |
| `vm power-off` | 强制关机 | `--vm-id` +写选项 | `…PowerOff`；可能丢未保存数据 |
| `vm reset` | 硬重置 | `--vm-id` +写选项 | `…Reset` |
| `vm suspend` | 挂起 | `--vm-id` +写选项 | `…Suspend` |
| `vm rename` | 仅改 VM 名称 | `--vm-id` `--new-name`（1–80 合法名）+写选项 | `…Rename`；远端读取前做名称白名单校验 |
| `vm reconfigure` | 关机态改 CPU/内存/显式磁盘列表 | `--vm-id`；`--cpu`(≥1)、`--memory-gb`(≥1)、`--disks` 数组任选 | 单位 GiB；磁盘只扩不缩、不可补偿；需 CPUCount/Memory/DiskExtend/AddNewDisk |
| `vm delete` | 删除 VM | `--vm-id` `--allow-shared-datastore` +写选项 | 高风险不可逆；受控通道：全 vCenter 扫描无消费者 + 显式担保旗标 + `plan apply` 双重确认；证据不足仍拒绝 |
| `vm snapshot-create` | 创建快照 | `--vm-id` `--snapshot-name`；`--description`、`--memory` 默认false、`--quiesce` 默认false +写选项 | 默认非内存快照；快照名允许 `/ \ %`，禁控制符/零宽/边缘空白 |
| `vm snapshot-revert` | 恢复到快照 | `--vm-id` `--snapshot-id` +写选项 | 高风险不可逆；**当前拒绝执行**（外部链接磁盘依赖不能排除） |
| `vm snapshot-delete` | 删除快照 | `--vm-id` `--snapshot-id` +写选项 | 高风险不可逆；**当前拒绝执行**（同上） |

## 8. VM 部署 / 克隆 / 模板 / 介质 / 迁移（8）

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `deploy mark-template` | 把 VM 转换为模板 | `--vm-id` +写选项 | 需 `…MarkAsTemplate`；只转换不重命名 |
| `template convert` | 把精确模板转换回 VM | `--vm-id` `--pool-id` `--host-id` +写选项 | 需 `…MarkAsVM`+`Resource.AssignVMToPool`；不改名不开机；非异步 |
| `deploy iso` | 编辑已有光驱装载 ISO | `--vm-id` `--cdrom-key`(≥0 整数) `--datastore-id` `--path` `--search-id` +写选项 | 须先 browse/scan + search-status，且 search_id 创建 ≤300 秒；需 EditDevice/SetCDMedia/DeviceConnection/Datastore.Browse |
| `deploy unmount-iso` | 断开并清除光驱介质 | `--vm-id` `--cdrom-key`(≥0) +写选项 | 不删除 ISO 文件 |
| `vm clone` | 克隆为关机 VM | `--vm-id` `--pool-id` `--datastore-id` `--host-id` `--folder-id` `--name` +写选项 | 需 `…Provisioning.Clone`；不隐式预留 IP 或改网 |
| `deploy template` | 从模板部署关机 VM | `--vm-id` `--pool-id` `--datastore-id` `--host-id` `--folder-id` `--name` +写选项 | 需 `…DeployTemplate` |
| `deploy clone-template` | 对齐 vcenter-ops 克隆模版标准流程的一次性克隆 | `--vm-id`(模板) `--name` `--folder-id` `--pool-id` `--datastore-id` 必填；`--host-id`(省略走 DRS)、`--network-id`、`--cpu`、`--memory-gb`、`--disk-gb`(仅扩容)、`--ip-address`、`--subnet-mask`(默认255.255.255.0)、`--gateway`、`--guest-domain`(默认local) 可选 +写选项 | 独立 template_clone Provider；给静态 IP 即开机 + Linux 定制，不给则关机；磁盘仅扩容；需 DeployTemplate/CreateFromExisting/AssignVMToPool/AllocateSpace/Network.Assign/PowerOn/Customize |
| `vm migrate` | 迁移（默认仅计算） | `--vm-id` `--pool-id` `--host-id` 必填；`--datastore-id` 可选 +写选项 | 需 `Resource.ColdMigrate`；省略 datastore_id 仅在明确无磁盘且无 NVDIMM 时做计算迁移；带磁盘 / 指定存储当前拒绝 |

## 9. OVA / OVF 导入（2）

本地解包 + 描述符 / 网络 / 磁盘校验后 OvfManager + NFC 上传，默认关机、不隐式定制。

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `deploy ova` | 从本地单文件 OVA 导入关机 VM/vApp | `--source` `--work-dir` `--name` `--resource-pool-id` `--host-id` `--folder-id` `--datastore-id` 必填；`--network-mapping` 对象；+写选项 | ovf Provider；安全解包拒路径穿越 + OVA 解压炸弹延迟落盘；需 VApp.Import/AllocateSpace/Datastore.Browse/Network.Assign/AssignVMToPool；中断须核对不重发 |
| `deploy ovf` | 从本地 OVF 目录（descriptor.ovf + 引用磁盘）导入 | 同 `deploy ova` | 同上；校验映射后 NFC 上传；默认不开机 |

## 10. 链接克隆（1）

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `deploy linked-clone` | 从精确父 UUID + 快照创建关机链接克隆 | `--vm-id` `--parent-uuid` `--snapshot-id` `--name` `--folder-id` `--pool-id` `--host-id` `--datastore-id` +写选项 | 依赖长期保留，不能排除依赖时拒绝父磁盘清理；许可最终由服务端校验；需 Clone/CreateFromExisting/AssignVMToPool/AllocateSpace/Datastore.Browse/Network.Assign；实机接受度待验收 |

## 11. Guest 来宾操作（7）

经 VMware Tools 的来宾内执行 / 文件传输 / 定制；显式 Python 包装器、有界输出与文件大小，run-id 可信绑定。

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `vm guest-exec` | 来宾内执行程序（输出丢弃） | `--vm-id` `--guest-username` `--credential-ref` `--os-family {linux/windows}` `--python-path` `--program` 必填；`--argv` 数组、`--working-directory`、`--run-parent` 可选 +写选项 | guest Provider；需 GuestOperations.Execute/Query；完成由独立运行标识核对，不凭 PID |
| `vm guest-exec-output` | 执行并有界捕获 stdout/stderr | 同 guest-exec（`--argv` 默认空数组）+写选项 | 各 ≤64KiB；完成绑定本次 run-id |
| `vm guest-process-status` | 只核对已有 Guest 操作的运行标识与原子结果 | `--operation-id` 必填；`--wait` 默认false | 远端只读；需 GuestOperations.Query；不重发 |
| `vm guest-output` | 凭可信 run-id 读已有运行的有界输出 | `--vm-id` `--guest-username` `--credential-ref` `--os-family` `--python-path` `--program` `--run-id`；`--wait` | 只读；不重新执行；缺失/损坏/身份不符返回不确定 |
| `vm guest-download` | 从来宾下载单个有界文件到本地新文件 | `--vm-id` `--guest-username` `--credential-ref` `--os-family` `--guest-path` `--file` | 文件 ≤4MiB；拒绝覆盖与路径穿越；中风险（外发） |
| `vm guest-upload` | 上传本地文件到来宾精确路径 | `--vm-id` `--guest-username` `--credential-ref` `--os-family` `--file` `--guest-path`；`--overwrite` 默认false | 文件 ≤4MiB；默认拒覆盖，显式 overwrite 才覆盖；非异步 |
| `vm guest-customize` | 按声明式规格（hostname/IP/掩码/网关/DNS）经固定包装器定制已开机 VM | `--vm-id` `--guest-username` `--credential-ref` `--os-family` `--python-path` `--spec-file` 必填；`--run-parent` +写选项 | 不隐式开机；提交成功 ≠ 来宾配置完成；需 Execute/Query |

## 12. 主机维护（2）

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `host maintenance-enter` | 显式预览 VM/DRS 影响后让精确主机进入维护模式 | `--host-id` 必填；`--task-timeout` 默认300；`--evacuate-powered-off-vms` 默认false；`--allow-drs-migration` 默认false +写选项 | host Provider；需 `Host.Config.Maintenance` |
| `host maintenance-exit` | 让精确主机退出维护模式 | `--host-id`；`--task-timeout` 默认300 +写选项 | 不创建额外撤离操作 |

## 13. 集群与成员（4）

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `cluster create` | 在精确 host folder 创建集群 | `--folder-id` `--name` 必填；`--ha-enabled` 默认false；`--drs-automation {manual/partiallyAutomated/fullyAutomated}` 默认 manual +写选项 | cluster Provider；需 `Host.Inventory.CreateCluster`；非异步 |
| `cluster configure` | 只增量修改明确选择的 HA/DRS 字段 | `--cluster-id` 必填；`--ha-enabled`、`--drs-enabled`、`--drs-automation`、`--drs-vmotion-rate`(整数) 任选 +写选项 | 需 `Host.Inventory.EditCluster` |
| `cluster delete` | 删除精确空集群 | `--cluster-id` +写选项 | 高风险不可逆，二次确认；需 `Host.Inventory.DeleteCluster` |
| `cluster remove-host` | 把主机移出集群、转为独立主机（保留在 vCenter） | `--cluster-id` `--host-id` `--folder-id` +写选项 | membership Provider；高风险，二次确认；需 EditCluster/MoveHost/AddStandaloneHost |

## 14. VM 创建（1）

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `vm create` | 创建关机空白 VM | `--name` `--folder-id` `--pool-id` `--host-id` `--datastore-id` `--network-id` `--guest-id` `--hardware-version` `--cpu`(整数) `--memory-gb`(整数) `--disk-gb`(整数) +写选项 | creation Provider；单位 GiB；**不分配 IP**；需 Inventory.Create/AddNewDisk/AssignVMToPool/AllocateSpace/Network.Assign |

## 15. 计划引擎（8）

声明式固定计划：从文件预览 → 校验前提 → digest/DESTROY 确认 → 执行 → 核对 / 补偿 / 归档。

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `plan create` | 从声明式文件预览固定计划 | `--file` 必填；`--request-id` 可选 | 编排；只生成计划不执行 |
| `plan validate <plan_id>` | 只核对前提，不执行 | `plan_id` 必填（位置） | 远端只读校验 |
| `plan list` | 列出计划 | 无 | 本地只读 |
| `plan show <plan_id>` | 查看计划及不可变摘要 | `plan_id` 必填 | 只读 |
| `plan apply <plan_id>` | 确认并执行固定计划 | `plan_id` 必填；`--confirm <digest>`；不可逆加 `--confirm-destruction`；`--wait` 默认true | 编排、中风险、仅 CLI；写前被拒 exit4，写后未知 exit6 不重发 |
| `plan reconcile <plan_id>` | 核对原任务 | `plan_id` 必填；`--wait` 默认false | 远端只读；不重复提交 |
| `plan archive <plan_id>` | 归档已结束计划，保留证据 | `plan_id` 必填 | 本地写、中风险 |
| `plan rollback <plan_id>` | 预览可执行补偿，明确不能恢复的步骤 | `plan_id` 必填 | 编排预览；当前补偿覆盖改名与可表示的 CPU/内存字段 |

## 16. 任务核对与批量编排（9）

持久化操作记录的只读核对 / 等待 / 取消，以及只构建计划的批量电源操作。

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `task list` | 查询本地操作记录 | `--limit` 默认100 | 本地只读 |
| `task inspect <operation_id>` | 查看持久化操作与任务身份 | `operation_id` 必填 | 本地只读 |
| `task reconcile <operation_id>` | 只核对已提交任务 | `operation_id` 必填 | 远端只读，不重发 |
| `task wait <operation_id>` | 限时等待已提交任务 | `operation_id` 必填 | 远端只读，不重发 |
| `task cancel <operation_id>` | 请求取消原任务 | `operation_id` 必填；`--confirm` | 编排、中风险、仅 CLI；请求 ≠ 已取消 |
| `batch power-on` | 为多台 VM 构建开机固定对象计划 | `--vm-ids` JSON 数组（如 `["vm-1","vm-2"]`）必填；`--request-id` | 高风险批量；**只构建计划不直接变更**，须再 plan apply |
| `batch power-off` | 构建强制关机计划 | 同上 | 同上 |
| `batch shutdown` | 构建优雅关机计划 | 同上 | 同上 |
| `batch reset` | 构建硬重置计划 | 同上 | 同上 |

## 17. 审计取证（2）

本地脱敏证据视图：不含载荷、凭据或原始主体标识（主体以 HMAC-SHA256 假名）。

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `audit list` | 分页查询脱敏审计事件 | `--limit` 默认100(1–10000)；`--after-id` 默认0；`--snapshot-max-id` 可选非负整数 | 本地只读，不连远端 |
| `audit export` | 导出脱敏 JSON 证据 | `--file` 必填；`--limit` 默认10000；`--after-id`；`--snapshot-max-id` | 本地写、中风险；**拒绝覆盖已有文件**，发布前 lstat 拒符号链接/特殊文件 |

## 18. 凭据 / 秘密（4）

全局秘密（凭据引用值），Fernet 加密静态存储；只存名称 / 修订号 / 时间元数据。

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `secret list` | 列出秘密名称、修订号与 UTC 时间 | 无 | 拒绝按 Profile 过滤（秘密是全局的）；不显示值 |
| `secret set` | 创建全局秘密 | `--name` 必填；`--stdin` 默认false（从标准输入读值） | 不覆盖已有项；值 ≤4096 UTF-8 字节；中风险 |
| `secret rotate` | 替换精确秘密值并递增修订号 | `--name`；`--stdin` | 高风险；这是值轮换，不是主密钥轮换 |
| `secret delete <name>` | 删除精确名称秘密 | `name` 必填 | 高风险，精确确认 |

## 19. 历史与参数预设（8）

本地计划历史查看 + 可复用的声明式参数预设（按 Profile 隔离）。

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `history list` | 分页查看本地计划历史 | `--limit` 默认100；`--after-id` 默认0；`--snapshot-max-id` | 无 `--profile` 时明确查全局 |
| `history show <plan_id>` | 精确查看计划与操作状态 | `plan_id` 必填 | 不输出确认值、绑定或回执 |
| `preset list` | 分页列出指定 Profile 的预设 | `--profile` 必填；`--limit`；`--after-name` | 本地只读 |
| `preset show <name>` | 查看并重新校验指定预设 | `name` 必填；`--profile` | 只读 |
| `preset save` | 保存已注册远端原子命令的声明式参数 | `--name` `--command-path` `--params`(对象) 必填；`--profile` | 中风险；只保存参数，不预览/部署 |
| `preset delete <name>` | 删除 Profile 内精确名称预设 | `name` 必填；`--profile` | 高风险 |
| `preset from-history` | 从同 Profile 历史计划选一个步骤新建预设 | `--name` `--plan-id` `--position`(整数) 必填 | 中风险；不复用确认或操作 |
| `preset from-vm` | 只读来源 VM，保存目标 VM 的 CPU/整 GiB 内存配置预设 | `--name` `--source-vm-id` `--target-vm-id` 必填 | 中风险；非部署/克隆；**遗漏磁盘、网卡、控制器、存储及 UUID** |

## 20. 静态策略预检（2）

不连远端、不消耗确认、不提交任务的纯静态 schema / 风险 / 参数检查。

| 可用命令 | 命令用途 | 必要参数 / 使用条件 | 备注·限制 |
|---|---|---|---|
| `policy inspect <command_path>` | 查看静态 schema、风险与声明权限 | `command_path` 必填 | 本地只读；不查询远端实际权限、不授权执行 |
| `policy check` | 仅检查静态命令参数 | `--command-path` `--params`(对象) 必填 | 不签发确认、不消耗确认、不提交任务；④仅契约基线测试覆盖 |

---

## 附：核对口径与未实现边界

- **一一对应**：20 个模块 × 表行数合计 = 112，与 `registry.COMMANDS` 完全一致（脚本断言无 missing / extra / duplicate）。每条命令对应唯一一个处理器（`handler_ref`），无"注册但无处理器"的空命令（`implemented=true` 全量成立）。
- **"可用"的两层含义**：
  1. *已注册并离线可用*：112 条全部满足（有处理器、有离线测试，全量 816 项通过）。
  2. *当前真正能在真机执行写动作*：`vm delete` 已开**受控通道**——全 vCenter 清单扫描证明本 vCenter 内无其他 VM/模板/快照引用其磁盘链 + 显式 `--allow-shared-datastore` 担保 + `plan apply` 双重确认才销毁（证据不足/发现消费者/无担保仍 fail-closed）；`vm snapshot-revert`、`vm snapshot-delete` 仍因外部依赖不可证而**一律拒绝**；`vm migrate` 仅放开纯计算迁移；这些在第 0.3 节与各表备注中已逐条标注。
- **未实机验收 ≠ 未实现**：所有远端命令在 6.5/6.7/7.0/8.0 均为 `not_lab_verified`；GA 真机门只要求 7.0+/8.0+ 两条线逐写入动作验证（只读以离线契约 + 8.0.3 只读轮次为准），6.5/6.7 无真机环境不阻断；其中 OVA/OVF、Guest 输出/传输/定制、`alarm reset` 已离线验收，等待真机写入验收。
- **`remaining_domains`（capabilities 声明的后续领域，当前无对应命令）**：linked_clone 实机验收、typed_plan_output_references、scans（定时扫描）、schedules（调度）、notifications（通知）、ttl（缓存/记录 TTL 自动清理）、mcp（MCP 服务面复用分级门）、migration（存储迁移策略证据）。这些方向目前**没有注册命令**，不属于上表 112 条。
- **参数速记**：表中"必填"指无默认且 required；未标必填者均可选并给默认值或 None。`--id/--name` 标注"二选一"的为 oneOf，须且只能提供一个。
- **更新方式**：命令或参数有增改后重跑 `PYTHONPATH=src python scripts/generate_command_interaction.py`；本清单依据同一份注册表真值整理，模块分组为人工归类（已用脚本校验并集完整）。

