# vcenter-aiops 实机验证清单（b5，execution-beta）

> 生成日期：2026-10-18。真值：`registry.COMMANDS` 112 条（handler 112/112 可解析、0 断链、0 重复；CLI subparser 112/112；源码 0 个 NotImplemented/TODO 占位；离线 785 测试通过、pyflakes 0）。
> **实机状态：vSphere 6.5 / 6.7 / 7.0 / 8.0 = 0/4，全部远端命令仍 `not_lab_verified`。** 离线通过 ≠ 实机验收。
> 用法：在测试环境（独立集群 / 测试 VM、可回收数据存储）执行；每条记录 build、账号权限、结果与失败分类（预期内 fail-closed / 真实缺陷）。

## 0. 数字口径

| 类别 | 数量 | 是否需实机 |
|---|---:|---|
| 远端只读 remote_read | 31 | 是（只读，先做） |
| 远端写 remote_write | 35 | 是（需特权 34、异步 30；高风险 5） |
| **需实机合计** | **66** | |
| 纯本地 local_read/local_write + 编排本地部分 | 46 | 否（本机即可，见第 8 节） |

高风险写（5，二次确认）：`vm delete`、`vm snapshot-revert`、`vm snapshot-delete`、`cluster remove-host`、`cluster delete`。

## 1. 实机前置（每条命令通用）

1. `vcenter-aiops profile test --profile <p>`：验证连接与服务端 instanceUuid，确认未连错同名 vCenter。
2. TLS：默认校验企业 CA；`--insecure` 仅测试环境，预期出现关闭告警。
3. 账号权限：用**最小权限测试账号**核对每个写命令声明的特权（缺特权应明确 exit4，不调用不支持的写 API）。
4. 记录环境：vCenter build、ESXi build、许可证（HA/DRS/DVS/vMotion）、VMware Tools 版本、存储类型（VMFS/vSAN/NFS）。
5. 全程 `--dry-run` 先预览；不可逆写经 `plan apply --confirm <digest>`（销毁类再加 `--confirm-destruction`）。
6. 故障判定：写后结果不明应 exit6 + `task reconcile`，**不得自动重发**；参数/身份问题应 exit4。

## 2. P0 只读冒烟（安全，最先跑，31 条）

连接/IP（3）：`profile test`、`ip check --address --scope`、`ip available`。
资产/事件/容量（4）：`inventory list`（kind=vm/host/cluster/datastore 各一）、`inventory export`、`events list`、`quota check`。
对象查询（10）：`vm list`、`vm inspect`（--id 与 --name 各一，含同名消歧）、`template list/inspect`、`host info`、`cluster list/info`、`datastore list/inspect`、`alarm list`（含 --entity-id 与 --status）。
数据存储搜索（4）：`datastore browse`、`datastore scan`（ISO/OVA/OVF）、`datastore search-status`、`cache refresh`（另验 `cache status` 为本地）。
VM 状态只读（3）：`vm snapshot-list`、`vm tools-status`、`vm wait-tools`。
计划/任务核对（4）：`plan validate`、`plan reconcile`、`task reconcile`、`task wait`。
Guest 只读（3，需 Tools + 来宾凭据）：`vm guest-process-status`、`vm guest-output`、`vm guest-download`。

> 重点核对（历史真机缺陷 D1–D3 同类风险）：64 位 long 标量、DatastoreBrowser `session[]` 任务 id、大分页 PropertyCollector、缺字段返回 unavailable 而非编造。

## 3. 台账优先：14 项高频新增能力（A–E 组）

| 组 | 命令 | 实机要点 |
|---|---|---|
| A1 | `inventory export` | 文件不覆盖/不跟符号链接；CSV/JSON 外部字段转义 |
| A2 | `events list` | 按 vm/host/since/type 过滤；无权限 vs 无事件区分 |
| A3 | `quota check` | CPU/内存/存储预检；缺字段=unavailable |
| B1/B2 | `ip check`、`ip available` | ping 不通**不得**判空闲；无正向证据=inconclusive |
| B3 | `ip expire` | 默认只列；`--apply --lease-id` 才释放 |
| C1/C2 | `deploy ova`、`deploy ovf` | 描述符/磁盘/网络映射/容量校验；NFC 上传；默认关机；中断后 reconcile 不重发；OVA 路径穿越/解压炸弹拒绝 |
| D1 | `vm guest-exec-output` | Linux+Windows；stdout/stderr 各 ≤64KiB；真实退出码；超时不伪造成功 |
| D2 | `vm guest-output` | 凭 run-id 只读，不重执行；缺失/损坏=不确定 |
| D3 | `vm guest-upload` | ≤4MiB；默认拒覆盖；Guest 路径穿越拒绝 |
| D4 | `vm guest-download` | ≤4MiB；本地不覆盖、防穿越 |
| D5 | `vm guest-customize` | hostname/IP/掩码/网关/DNS；不隐式开机；提交成功 ≠ 来宾配置已生效 |
| E1 | `alarm reset` | 仅 6.7+；只能 vm/host + red/yellow 批量；预览展示真实 scope；**6.5 必须写前拒绝** |

## 4. 其余远端写（按域，测试 VM/集群，35 条）

- **告警（2）**：`alarm acknowledge`（确认≠恢复）、`alarm reset`。
- **电源（5）**：`vm power-on`、`shutdown`（优雅，不回退强关）、`power-off`、`reset`、`suspend`。
- **VM 配置（3）**：`vm rename`、`vm reconfigure`（关机态 CPU/内存/磁盘只扩不缩）、`vm delete`（见第 5 节）。
- **快照写（3）**：`vm snapshot-create`（默认非内存快照；名称允许 `/ \ %`）、`snapshot-revert`、`snapshot-delete`（后两者见第 5 节）。
- **模板（2）**：`deploy mark-template`（不改名）、`template convert`（不改名不开机）。
- **介质（2）**：`deploy iso`（须先 browse/scan + 300 秒内 search_id）、`deploy unmount-iso`（不删 ISO）。
- **克隆/部署/迁移（4）**：`vm clone`（关机、不隐式改网/IP）、`deploy template`、`deploy clone-template`（第 6 节专项）、`vm migrate`（见第 5 节）。
- **主机维护（2）**：`host maintenance-enter`（撤离/DRS 影响预览；无容量不强成功）、`host maintenance-exit`。
- **集群（4）**：`cluster create`（HA/DRS 差异+许可）、`cluster configure`（仅改选定字段）、`cluster remove-host`（高风险；移出≠注销；先维护模式）、`cluster delete`（仅精确空集群，不级联）。
- **VM 创建（1）**：`vm create`（关机空白；多等价 VirtualDiskOption 选择；不分配 IP）。
- **Guest 写（4）**：`guest-exec`、`guest-exec-output`、`guest-upload`、`guest-customize`（要求 Guest 自带 Python 3.10+，不自动安装）。
- **链接克隆（1）**：`deploy linked-clone`（精确父 UUID+快照；依赖保护；许可由服务端终判）。
- **OVA/OVF（2）**：见 C1/C2。

## 5. 必须验证“正确拒绝”的命令（验 fail-closed，不是验成功）

| 命令 | 预期实机表现 |
|---|---|
| `vm delete`（**受控通道**，b5 新增） | 四种情形分别验：① 不带 `--allow-shared-datastore`，即便扫描无消费者也应 `dependency_unproven`/exit4 拒绝；② 扫描发现其他 VM/模板/快照引用其磁盘文件应 `dependency_present`/exit4；③ 预览后、提交前若新增消费者，submit 应 `dependency_present`（SubmissionRejected，不发写）；④ 无本地依赖 + 干净扫描 + 旗标 + 两把确认（digest 与 `DESTROY:`）齐全才真正 `Destroy_Task`。另验枚举不可得（权限/读失败）时即使带旗标也拒绝 |
| `vm snapshot-revert` / `vm snapshot-delete` | 无担保通道，应无条件拒绝恢复/清理（`dependency_unproven`） |
| `vm migrate`（带 `--datastore-id`） | 缺 PBM 策略证据/指定存储应拒绝；仅“无磁盘且无 NVDIMM”的纯计算迁移可执行 |
| `alarm reset`（6.5） | 版本门写前 exit4；scope 扩大（集群/数据存储/单告警）拒绝 |
| 任意写，权限不足 | exit4 并说明所缺特权；不得调用不支持的写 API |
| 同名对象仅给 `--name` | 返回消歧信息，不默认操作第一个 |

## 6. `deploy clone-template` 专项（对齐 vcenter-ops 2.0，新增重点）

在 7.0/8.0 优先，逐项验证：精确模板 ID 克隆；host 省略走 DRS、指定 host 走放置；DVPG（network-N）与标准端口组（dvportgroup-N）；静态 IP Linux 定制（给 IP 即开机，子网掩码/网关/域）与不给 IP（关机）；CPU/内存改配与省略保留；**磁盘仅扩容不缩容**；Tools 就绪交 `vm wait-tools`。记录定制后实际网卡/IP/主机名。

## 7. 版本矩阵记录（每系列一行）

| vSphere | build | 账号/许可 | 只读冒烟 | 14 项 A–E | 写抽样 | fail-closed 项 | 结论 |
|---|---|---|---|---|---|---|---|
| 6.5 | | | ☐ | ☐（alarm reset 应拒） | ☐ | ☐ | |
| 6.7 | | | ☐ | ☐ | ☐ | ☐ | |
| 7.0 | | | ☐ | ☐ | ☐ | ☐ | |
| 8.0（含 8.0.3 build-24091160 复测 D1–D3） | | | ☐ | ☐ | ☐ | ☐ | |

GA 还需：四系列通过 + Windows secret 后端 + 隔离安装/打包 + 覆盖率 ≥85% + PRD AC-01–29。

## 8. 不需实机的 46 条本地命令（本机验证即可）

version / doctor（不带 --connect）/ capabilities list·show；profile list·show·add·update·delete；ip reserve·release·list·expire（本地租约）；plan list·show·apply·archive·rollback·create；task list·inspect·cancel；batch power-on·power-off·shutdown·reset（只生成计划）；audit list·export；secret list·set·rotate·delete（Windows 后端除外）；history list·show；preset list·show·save·delete·from-history·from-vm；policy inspect·check；cache status·invalidate；datastore search-inspect·search-list。
