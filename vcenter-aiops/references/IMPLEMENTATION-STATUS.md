# 3.0 实施状态

当前为 3.0.0rc1 发布候选版（release-candidate，功能冻结），非 GA 交付。14 项运维聚焦待做台账已全部完成并通过离线测试，等待 6.5/6.7/7.0/8.0 逐版本实机矩阵验收（GA 硬门槛）后再进入正式版。

完整交付按 [逐命令验收台账](COMMAND-ACCEPTANCE.md) 跟踪：PRD 必需 150 个叶子。台账将注册、离线完整验收与四系列实机验证分开，已注册不等于通过验收。

- 已实现：统一 CLI 与逐命令参数 schema、Profile 引用配置、事务 IP 租约、只读查询、虚拟机电源/重命名/离线 CPU 与内存配置/快照/删除、完整克隆、模板部署、迁移、标记模板、Tools 状态查询。
- 已实现的执行机制：固定目标的多步计划与批量电源操作、摘要确认、危险操作二次确认、请求去重、原任务核对与取消、有限补偿预览（重命名及 CPU/内存配置）、恢复时重新确认。未知结果不会自动重提。
- 已实现（Beta 新增）：OVA/OVF 部署（OvfManager 导入规范 + HttpNfcLease 驱动，`deploy ova`/`deploy ovf`）、Guest 执行输出捕获/输出读取/文件上传下载/声明式定制（`vm guest-exec-output`/`guest-output`/`guest-download`/`guest-upload`/`guest-customize`）、资产导出/事件/配额（`inventory export`/`events list`/`quota check`）、IP 信号（`ip check`/`ip available`/`ip expire`）、告警批量重置（`alarm reset`，6.7+ ClearTriggeredAlarms，仅 VM/Host 类型 + red/yellow 状态过滤）。
- 未完成：链接克隆验收闭环、类型化步骤输出引用、扫描、调度、通知、TTL、MCP、完整本地管理与旧数据迁移（41 项搁置清单保持不变）。模板查询/转换、VM 空白创建、受限磁盘配置、ISO 装卸、主机维护、集群生命周期与移出主机已通过模块审查；自动加入主机按用户批准的严格安全策略延期。
- 限制：当前补偿不是通用回滚；删除等不可逆步骤不能恢复。快照还原后的状态无法静态投影，后续依赖步骤仍受限。命令具体参数以 capabilities show 输出为准。
- 实机验证：6.5、6.7、7.0、8.0 均未验证；开发 SDK 版本不能替代兼容矩阵。
- 旧 vcenter-ops 目录暂为迁移来源，最终切换后删除；新包没有旧 handler 入口。
- PRD/实施计划位于仓库 docs 中。不得将本候选版描述为 PRD AC-01–29 全部通过。

## 2026-09-09 验证记录

- Python 3.12：23 项离线测试通过，涵盖 CLI、配置、IP 并发、操作去重、任务身份校验、未知状态保持目标锁、TLS 和只读分页清理。
- 临时隔离环境已构建并安装 3.0.0a1，入口 version 和 vm inspect --help 可运行。
- 上述 23 项为基础阶段历史记录，不代表当前测试总数。现已接入 vSphere 任务观察器代码并通过离线替身测试，尚未完成真实服务端验证；不提供手工宣告成功的 CLI。
- 未连接任何真实 vCenter，未执行生产写操作；Windows/Linux 安装及四系列服务端兼容仍待验证。

## 2026-09-10 计划校验补齐

- `plan validate` 复用预览的逐步骤状态投影，避免连续操作同一 VM 时误报后续步骤状态变化。
- 待恢复计划仅校验未完成步骤；执行中或结果未知的计划要求先核对任务。校验不消费确认值、不修改计划摘要、不提交远端操作。
- 并发恢复收尾在锁与事务内重新读取步骤状态，避免旧观察结果覆盖后续运行状态。

## 告警查询阶段

- 新增 `alarm list`，支持精确对象范围、状态过滤、结果数量限制及截断提示；读取 PropertyCollector 当前告警属性，不依赖变更通知缓存。
- 输出告警 ID、触发实体 ID、确认状态和采集时间；缺失属性返回不可读取，不伪报无告警。查询范围包括指定对象及其后代，且受当前账号可见权限限制。
- `alarm acknowledge` 已接入独立预览、明确确认、提交前状态复查和提交后确认状态核对；限定精确实体与告警 ID，当前要求独立计划，不提供虚假的撤销确认补偿。四系列服务端仍未实机验证。
- `alarm reset` 尚未开放：官方 ClearTriggeredAlarms 从 6.7 提供，AlarmFilterSpec 不包含实体 ID 或告警 ID，仅有状态与类型过滤，不能代替精确对象重置。禁止静默扩大范围；告警模块整体仍未完成。

## 数据存储查询阶段

- `datastore browse --datastore-id datastore-N [--path 相对目录]` 与 `datastore scan` 默认单层，显式 `--recursive` 包含子目录。scan 按扩展名发现 ISO/OVA/OVF，不下载、不部署；省略 path 查询根目录。
- 拒绝路径穿越、跨数据存储路径和编码转义。返回文件元信息、采集时间及截断标记；错误与结果缺失不解释为空目录。
- 搜索意图、Profile、服务端身份、原 task ID 及完成结果持久化存储。同一 `--request-id` 不会重复搜索；搜索超时返回 running 及恢复入口。提交响应丢失且没有回执时必须人工核对，不猜测 task ID。
- `datastore search-status <search_id> [--wait]` 核对原任务；`datastore search-inspect` 查看本地记录；`datastore search-list` 列出当前 Profile 搜索。这里的 search_id 是返回的 operation_id，不是服务端 task ID，也不走 VM 写入的 task reconcile。
- 恢复命令必须使用原 `--profile`；原 vCenter 身份不一致时拒绝查询。已保存终态不会被过时查询覆盖，服务端任务过期也不会删除已保存结果。
- 结果限制仅约束输出数量，不是服务端扫描工作量限制。尚无真实数据存储兼容性验收记录。

## 本地审计阶段

- `audit list --after-id 0 --limit 100` 分页读取事件；返回 next_cursor 与 snapshot_max_id，后续页可传相同 `--snapshot-max-id` 保持快照上界。
- `audit export --file 新文件.json` 导出至本地，不外发。默认最多 10000 条，截断明确显示，继续导出须选择新文件名与游标；已有文件和符号链接均不覆盖。
- 审计主体使用本地受保护密钥生成 HMAC 关联代号，不导出原始主体、操作参数或凭据；这是伪名化，不是完全匿名，也不构成防篡改签名。
- 当前审计库未按 Profile 划分，范围明确为全部本地 Profile。传 `--profile` 时拒绝执行，不静默忽略过滤条件。Windows 文件发布行为仍待实机验证，不支持安全发布的文件系统会明确失败。
- 文件发布成功后，若审计记录或临时文件清理失败，返回 partial 并保留路径与 SHA256，不把已经存在的文件误报为未生成。

## 2026-09-10 本轮验证

- 110 项离线测试在源码环境及已安装 wheel 环境中分别通过；包含搜索真实双连接并发去重、旧观察终态保护、丢响应恢复、审计导出部分完成等回归。
- wheel 构建与独立目录命令入口验证通过。构建检查曾检出旧 build 缓存带入已移除模块，隔离旧缓存后重新构建；新增 `scripts/verify_wheel.py` 校验安装包的 Python 模块集合与内容，当前 26 个模块逐一匹配。
- 后续每次发布须从干净构建目录构建并运行：`python scripts/verify_wheel.py <wheel路径>`。此校验不替代 Skill ZIP 打包、全量 PRD 验收或四系列服务端实机测试。
- 本轮未连接真实 vCenter，未进行生产变更或外发通知；仍为 3.0.0a1 开发候选版。

## 2026-09-11 领域路由

- 远端命令通过注册表的 `provider_kind` 路由，同一执行引擎继续负责确认、意图、任务和核对；领域归属被固定到计划摘要中。
- 篡改、缺失或未知路由不提交远端写入；混合领域计划在类型化引用完成前明确拒绝。同领域计划保留现有状态投影。
- 新路由接入后完整离线测试 126 项通过；独立审查发现混合计划错误优先级问题，修复后 17 项路由定向测试通过并完成复核。后续完整测试将包含新增的第 127 项回归用例。
- 此次路由格式变更不会自动迁移开发阶段旧计划：缺少领域绑定的计划被拒绝。存在未核对旧操作时须先保存和核对原执行证据，不应重复生成变更来代替恢复。
- 主机维护及其他剩余业务领域仍按逐命令台账推进，不能据此宣称完整 PRD 已交付。

## 2026-09-26 主机维护审查阶段

- 已接入 `host maintenance-enter` 与 `host maintenance-exit`，预览固定主机身份、维护状态、受影响 VM 和显式撤离授权；通过统一执行引擎提交及核对原任务。
- 2026-09-25 源码完整离线测试 150 项通过，其中主机维护 23 项。该记录对应首次审查前版本，不代表后续修复已验证。
- 独立审查发现的 DRS 功能许可和当前服务端身份检查缺口已修复并通过限定复审；修复后完整离线测试 160 项通过。许可格式不明确（包括无法判定有效期的永久许可）时拒绝相关迁移，不冒充过期或已授权；无撤离维护不额外要求 DRS 许可。
- 挂起或身份/电源状态不明的 VM、启用或无法判断的 vSAN 均保守拒绝进入维护；不会隐式关机。四系列服务端仍未实机验证。

## 2026-09-26 集群生命周期

- `cluster create/configure/delete` 已接入统一执行引擎并通过模块审查。创建默认为 HA 关闭、DRS manual；仅修改用户指定配置字段；删除要求空集群及二次确认。
- 创建保存返回对象的回执，不伪造 task ID；响应丢失不会按名称认领或重发。删除只接受精确对象不存在的证据，不将权限/网络错误解释为删除成功。
- 首次完整离线测试 178 项通过。审查发现并修复真实服务端的裸 `ComputeResource` 目录类型兼容问题，修复后 19 项集群定向测试通过；此时尚未重跑新增回归后的完整套件。
- 共享许可解析只接受明确、可解释的有效期与功能证据。含相对到期时间、起始时间、服务端时钟等尚未适配元数据时保守拒绝；这也收紧了主机迁移的接受范围。不能将模拟许可证据当作商业许可或四版本互操作性验收。
- 主机加入/移出仍在实施，整个集群领域及完整 PRD 尚未完成。未连接真实服务端，未提交或推送 Git。

## 主机加入安全审查与用户决策

- 成员管理候选实现完整离线测试198项通过，但独立审查发现：HostConnectSpec.sslThumbprint 允许指纹不匹配时改用受信 CA 验证；本地强制指纹探测不能约束 vCenter 后续发起的连接。
- 用户已选择 A：坚持严格策略，自动 `cluster add-host` 延期。公开命令、处理器、凭据转发路径及无其他用途的本地探测模块已撤下；旧计划和直接 Provider 尝试也会拒绝，不增加 CA 回退开关。
- 撤下后完整离线测试191项通过（保留移出测试，替换自动加入的正向测试为不可调用/无副作用测试），独立限定复核通过。移出主机模块保留并通过审查；自动加入不计入完成，其他模块继续推进。
- 未连接任何真实 ESXi/vCenter，未使用真实凭据。VM创建及后续任务仍未实施，不代表完整重构交付。

## 2026-09-26 空白虚拟机创建

- `vm create` 已接入独立创建 Provider 和共享确认执行引擎，精确指定目录、资源池、主机、存储、网络、Guest ID、硬件版本及容量；不自动开机或分配 IP。
- 从目标主机返回的能力检查 CPU 允许列表、Guest/硬件上限及设备支持，不套用最新产品的硬编码上限。创建限定一个厚置备 FlatVer2 磁盘、受支持的推荐 SCSI 控制器和网卡；不包含高级导入。
- 核对原任务与新 VM 身份、配置和放置；响应丢失不重发，不自动删除作为回滚。存储检查只证明名义磁盘容量，不预留容量或保证并发资源可用。
- 13 项定向及204项完整离线测试通过，独立审查无阻断或次要问题。四系列实机验证和整体发布验收仍未完成。

## 2026-09-27 磁盘配置与 ISO

- `vm reconfigure` 支持显式磁盘新增和扩容，严格校验设备、容量、控制器和存储，拒绝隐式删除/缩容；当前仅支持关机、无快照/加密/链接依赖的受限 SCSI/FlatVer2 组合。字节与 KB 同时初始化，创建模块也补齐字节容量字段。
- 磁盘操作不可补偿；混合 CPU/内存与磁盘步骤只恢复可恢复字段，结果保持部分补偿。设备状态不可推演的后续依赖步骤要求独立重新预览。
- `deploy iso` 与 `deploy unmount-iso` 只编辑已有光驱，不自动开机、下载或删除 ISO。装载需显式 `search_id`，先通过 datastore browse/scan 与 search-status 完成查询。查询创建时间须在300秒内（比完成时间保守），只读取已持久证据与原任务，不暗中重新搜索。
- ISO 证据固定最近观察的路径元数据，不保证外部文件不可被替换，也不证明内容完整性或启动成功。过期禁止新提交，但不阻止核对已提交的原任务。
- 独立审查发现并修复目录名空格匹配及提交前过期的错误状态分类。已知未提交返回持久、可操作的错误并允许新的预览；实际提交可能开始或回执保存失败仍保持未知且不重发。
- 修复后233项完整离线测试通过，限定复核无遗留问题。未连接真实环境、未提交 Git；四版本及整体发布验收仍待完成。

## 2026-09-27 模板查询与转换

- `template list/inspect` 只返回可见模板；不可读取模板标记时明确失败，不伪报空结果。精确查询拒绝截断与名称歧义。
- `template convert` 固定模板身份及目标资源池/主机，检查存储与网络可达性，仅执行同步转换，不改名、不开机、不隐式迁移存储；响应丢失不重发，成功仍须核对原对象及放置。
- 13项定向、246项完整离线测试通过，独立审查无阻断问题；一个错误提示中的旧命令措辞记入最终收尾清单。
- 链接克隆及其依赖保护仍未实现，安全范围选择待确认；模板模块通过不能视为整个部署领域或完整PRD完成。四版本实机及发布验收仍待完成。

## 2026-09-28 本地密钥库（POSIX）

- 已实现 `secret list/set/delete/rotate` 与共享 `env:`/`secret:` 引用；Profile和连接入口接入。无明文get、无CLI明文value，值仅隐藏输入或显式stdin。全局命名空间拒绝Profile过滤。
- 使用Fernet认证加密，主密钥仅通过独立环境变量提供，不落盘、不自动生成用户主密钥；错误主密钥和损坏密文不会覆盖原库。文件/锁检查、防符号链接与目录fd、并发读改写和原子替换均已覆盖。
- 30项新增及276项完整离线测试通过，独立POSIX安全复核无发现。测试使用临时密钥/目录，未读取或迁移真实凭据。
- Windows安全存储后端仍待实现，当前明确拒绝vault操作；这不是“已实现但未验证”。env凭据和基础help仍可用。后续Guest与通知需继续接入共享解析器；整个密钥功能尚不能宣称全平台完成。

## 2026-09-28 历史、预设与静态策略

- 历史查询现有本地证据，支持Profile过滤及有界分页；无Profile时明确全局范围，不输出旧确认值、binding或回执内容。
- 预设按Profile事务保存并验证当前命令schema，不复制执行授权。从历史提取必须显式选择步骤；从VM提取明确来源和未来目标，仅保存CPU/整GiB内存，不是部署/克隆模板，不隐式复制其他硬件或放置。
- policy仅检查静态schema与声明的风险/权限，明确authorization和remote_capability均未检查，不签发确认，也不连接远端。
- 293项完整离线测试通过；独立审查发现的隐式步骤选择及SDK对象越过Provider边界均修复并通过复核。遗漏项提示需补充“放置”的次要措辞保留至最终收尾。无真实环境或Git提交动作。

### 2026-09-28：显式缓存管理

- 新增 cache status/refresh/invalidate，按 Profile、观测服务端 UUID 和资源类型隔离；TTL 300秒，最多1000项和1,000,000字节，展示来源、过期与截断状态。
- 普通查询及写操作预检不读取缓存；失效只清理明确范围的缓存行，并撤销在途刷新代次。发布响应绑定自身数据，后续覆盖返回 partial 和检查时点。
- 修复真实 SDK 枚举归一化及发布后失效竞态，经独立复核通过。完整离线测试308项通过；不代表四版本实机验证，也不代表整个PRD完成。

### 2026-09-29：Guest执行与状态（Task5a）

- 按用户批准方案A增加显式包装协议；独立run标识与启动摘要绑定，预览展示实际源码、参数、目录、DEVNULL和保留策略。要求Guest已有显式Python3.10+，不自动安装。
- 通过严格有界SDK文件查询核对原子完成标记，不把PID当唯一完成证据；未知响应只读恢复、不重发。无回执恢复与提交共用计划锁，防止晚到响应覆盖终态。取消/自动清理不支持，不猜测Kill。
- 完整离线测试340项通过，独立审查发现的并发问题已修复并复核。Windows原生行为与四个vSphere版本均未实机验证；软件升级改变wrapper摘要后旧运行记录需原版本继续核对。
- 文件传输、输出捕获及定制（5b/5c）尚未完成；本阶段DEVNULL不是完整Guest输出功能。

## 2026-10-10 迭代看板与 Iteration I

- 新增迭代看板：`references/ITERATION-KANBAN.md`（指标、按领域看板列、56 未注册 Backlog、P0/P1/P2 排期、风险登记、通往 beta/rc/GA 路线图）。
- 新增 P0 实施计划：`docs/superpowers/plans/2026-10-10-vcenter-aiops-iteration.md`（Task 0–7 + 集成收尾）。
- 地面真值核对：CLI 实注册 97 = 必需 94 + 额外 datastore search-* 3（search-inspect/list/status）；`deploy linked-clone` 已注册且 Provider 已实现，台账行原标"未注册"属行级滞后（台账 93/56 待刷新为 94/55），Iteration I Task 0 处理。
- Iteration I 范围（P0）：只读补齐 inventory export/events/quota、ip check/available/expire、类型化步骤引用、链接克隆验收闭环、OVA/OVF、Guest 输出捕获/传输/定制、alarm reset 差异化。出口目标必需注册 ≥105。
- 明确：**Skill 暂不安装到 WorkBuddy**，仍为 3.0.0a1；不连接真实 vCenter，模拟通过不替代实机验收。

## 2026-10-10 台账收敛为运维聚焦

- `references/COMMAND-ACCEPTANCE.md` 重写为**运维命令台账**：主体只保留 **14 项 vCenter/VMware 日常高频且待做**的命令（A 资产排障3 / B IP3 / C OVA·OVF2 / D Guest5 / E 告警1），带注册/离线/实机勾选。
- **94 项已交付命令从待办删除**，仅在文末"已交付能力速查"列出，不再占验收行。
- **41 项低频/治理/接口类搁置**（TTL、扫描、调查、调度、通知、MCP、组合编排、旧数据迁移），暂不做、可恢复；`cluster add-host` 维持延期。
- 原 150 项完整台账已归档：`docs/archive/COMMAND-ACCEPTANCE-FULL-150-20260929.md`，PRD 全量范围可追溯，搁置项不丢失。
- 对账自洽：94 + 14 + 41 = 149（+延期1=150）。看板已同步说明；Iteration I 实施计划的任务范围与 14 项一致（Task0 台账刷新动作随本次收敛完成）。
- 完成 14 项后已交付 94 → 108，具备 beta 核心面。

## 2026-10-10 14 项待做台账完成，进入 3.0.0b1

- **A 资产排障（3）**：`inventory export`、`events list`、`quota check` 已注册并离线验收。
- **B IP 管理（3）**：`ip check`、`ip available`、`ip expire` 已注册并离线验收（IP 预留不等于网络空闲验证；释放须精确租约 ID）。
- **C 部署（2）**：`deploy ova`/`deploy ovf` 走 OvfManager.CreateImportSpec + ResourcePool.ImportVApp（HttpNfcLease 而非 Task）；新增纯逻辑租约状态机 `ovf_lease.py`、零三方 HTTP 边界 `ovf_http.py`、注入式 SDK 编排 `ovf_deploy.py`（provider_kind=ovf，TLS 客户端配置只注入不持久化）。
- **D Guest（5）**：`guest-exec-output`（Guest 侧 PIPE 有界捕获 stdout/stderr 各 ≤64 KiB base64）、`guest-output`（凭 run-id 经 `store.guest_run` 反查只读，不重跑）、`guest-download`/`guest-upload`（一次性 HTTPS URL，标准库 http.client，单文件 ≤4 MiB，拒绝覆盖/穿越）、`guest-customize`（声明式规格 hostname/适配器[mac|name 二选一]/ipv4[static|dhcp]/dns，纯逻辑 `guest_customize.py` 校验；提交成功不等同来宾配置完成）。capture/mode 标志只属于 run 描述、不进 schema 校验的 params；`_binding` 按 run.mode 分派选项校验。
- **E 告警（1）**：`alarm reset` 用 6.7+ 的 `AlarmManager.ClearTriggeredAlarms`（特权 Alarm.SetStatus）。地面真值：AlarmFilterSpec 的 typeEntity 仅 `entityTypeVm/entityTypeHost/entityTypeAll`，无集群/数据存储，也不能精确定位单告警/实体，因此命令只暴露 vm/host + red/yellow；预览绑定精确告警状态集合，提交前范围扩大即 `plan_stale` 拒绝；6.5 返回 capability_unsupported。
- **修复**：ProviderRouter 中 OvfDeploy 由"每次写都立即构造"改为按需懒加载，避免与 Guest 无关的写路径（及离线 CLI 测试）触发其 RetrieveContent。
- **测试**：完整离线测试 **456 项全部通过**（新增 ovf_lease 11、ovf_deploy 7、guest_transfer 11、guest_customize 12、guest_customize_flow 8、alarm_reset 12，以及 A/B 组定向用例）。真机 NFC/TLS、Guest 内 Python、Windows 行为与四系列 vSphere 均未实机验证，describe 中仍标记 `not_lab_verified`。
- **版本**：pyproject / manifest / SKILL 同步为 `3.0.0b1`（stage=execution-beta）。41 项搁置清单与 cluster add-host 延期保持不变；不安装到 WorkBuddy，不连接真实 vCenter。等用户实机验收通过后再进入正式版。
- **收尾补漏（干净 venv 冒烟发现）**：`vcenter version` 命令仍报 `3.0.0a1`，根因是版本串第四处硬编码在 `src/vcenter_aiops/__init__.py:__version__`（`application/commands/local.py` 的 version 从此取值），前三处（pyproject/manifest/SKILL）升级时漏同步。已改为 `3.0.0b1`，全量离线 **456 项仍全部通过**，随后重新干净构建 wheel 并 `verify_wheel`（verified=true，75 模块），在全新临时 venv 安装复跑冒烟确认：`version=3.0.0b1`、`release_stage=execution_beta`、`capabilities show "alarm reset"` 含特权 Alarm.SetStatus 与 `not_lab_verified`。

## 2026-10-13 安装前安全审计与 WorkBuddy 安装

安装 3.0.0b1 到 WorkBuddy 前完成静态安全审计（本环境无 skills-security-check，按等效检查面手工执行）：
- **危险原语**：无 eval/exec（业务 wrapper 自举除外，见下）/compile/__import__（仅固定模块 handler 动态加载）/pickle/marshal/shell=True/os.system；YAML 全部 safe_load。所有外部进程走 subprocess argv 列表 + shell=False（ping 探测、Guest 固定包装器 `_run`）。
- **Guest wrapper 自举**：`guest_protocol.build_run` 生成 `exec(base64(...))` 启动串，但执行的是包内固定 wrapper 源码（带 sha256 自校验 + payload digest 绑定），用户参数仅作 JSON 数据 base64 传入，绝不拼进代码/shell；非自由代码执行。
- **外联**：源码零硬编码 URL；网络出口仅 (1) 用户 profile 指定的 vCenter（SmartConnect），(2) vCenter 下发的 NFC/Guest 一次性传输 URL（目标 ESXi/Guest）。无遥测、自动更新、分析上报、curl|sh 远程下载。NFC/Guest HTTP 用标准库、有重定向次数与字节上限。
- **凭据**：只接受 `env:VAR`/`secret:NAME` 引用；secret 保险库 Fernet 加密、主密钥必须外部提供（不自动生成/保存）、0700 目录 + O_NOFOLLOW + owner/group 校验 + 原子写，Windows fail-closed；Guest auth 用后 `password=""`；profile 白名单字段禁止明文密码；preset/history 拒绝 password/secret/token 字段；连接异常统一脱敏。
- **文件系统**：密钥/配置/导出/租约普遍 0600 + 0700 目录 + O_EXCL/O_NOFOLLOW；inventory 导出有 CSV 公式注入防护（=+-@ 前缀加引号）。
- **供应链**：无 setup.py/构建钩子/远程安装；依赖仅 pyvmomi(VMware 官方)/PyYAML/cryptography，均有版本上下限；启动脚本 run.sh/ps1/bat 只做版本检查后 `-m vcenter_aiops`。
- **审计发现并修复 1 处 P2**：`guest_download` 本地落盘原为 exists()+open("wb")（TOCTOU/符号链接跟随/默认 umask 可读），已加固为 `O_CREAT|O_EXCL`（POSIX 加 O_NOFOLLOW）+ 0600 + is_symlink 预检，与其他写路径一致。全量 456 项离线测试仍通过，wheel 重建 verify 通过（75 模块）。
- **结论**：无 P0/P1，仅上述已修复 P2，判定可安装。
- **安装**：已装入用户级 `~/.workbuddy/skills/vcenter-aiops/`（排除 tests/__pycache__/build/egg-info），与源逐模块一致；通过 `VCENTER_AIOPS_PYTHON` 指向隔离 venv（Python 3.13.12 + pyVmomi/PyYAML/cryptography，不污染系统 Python）。安装目录 run.sh 验证：version=3.0.0b1、doctor 依赖齐全 connected=false、capabilities release_stage=execution_beta、14 项新命令 show 全部 succeeded（alarm reset 特权 Alarm.SetStatus，四系列 not_lab_verified）。
- 仍未连接真实 vCenter；等待用户在 6.5/6.7/7.0/8.0 实机验收。

## 2026-10-13 命令交互清单与随版同步机制

- 新增受版本控制交付物 `references/COMMAND-INTERACTION.md`（约 2400 行）：覆盖注册表全部 **111 条命令**（remote_write 34 / remote_read 31 / local_read 23 / local_write 15 / orchestration 8），逐条给出 path、operation_id、handler、provider_kind、风险/异步/MCP/特权标记、参数表（类型/必填/位置/默认/枚举/说明）、CLI 占位示例、预期结果、离线测试分级与覆盖文件。
- 离线测试覆盖四级口径：①行为级 73（CLI 词元/命令字面量/operation_id/精确 handler 名直接断言）、②逻辑级 34（底层纯函数/Provider 有单测，叶子为薄包装）、③共享执行轨 3（`vm reset`/`vm suspend`/`deploy mark-template`，走已测 Engine+Mutations，专属 SDK 分支无离线用例，实机优先验收）、④仅契约基线 1（`policy inspect`，仅全量 schema/--help 覆盖）。
- 生成器固化为 `scripts/generate_command_interaction.py`：自包含，直接 import 注册表 `COMMANDS` 与 `__version__`（文档标题自动带版本），含符号级人工修正表 `TIER_FIX`；支持 `--check`（文档过期退出码 1，供发布前/CI），在无 `tests/` 的安装环境拒绝运行（仅在源码树生成）。
- 维护约定已写入 `SKILL.md`：该文档**禁止手工编辑正文**；增删命令或修改命令契约（参数/operation_id/handler/标记）后必须重跑 `PYTHONPATH=src python scripts/generate_command_interaction.py` 并随版本提交；脚本与生成文档随包分发供溯源。
- 生成器与文档已同步到安装副本 `~/.workbuddy/skills/vcenter-aiops/`，两端一致。

## 2026-10-13 真机 8.0.3 只读验证缺陷修复（b1 → b2）

依据《只读验证报告 2026-10-13》（真实 vCenter 8.0.3 / build 24091160，50 用例：46 符合、10 负面用例正确拒绝、远端零副作用）修复 3 个真实缺陷。共同根因是**离线假 SOAP 桩的标量/任务 id/参数形态与真机不一致**，CI 全绿但真机必现：

- **缺陷 1（严重，datastore 读取整族失败 `query_incomplete`）**：真机把 `summary.capacity`/`summary.freeSpace` 等 64 位字段返回为 `pyVmomi.VmomiSupport.long`（int **子类**，`type(v) is int` 为 False），而读取/缓存用严格 `type()` 匹配而拒绝。
  - `providers/vsphere/inventory.py:_scalar` 改为先 bool、后 `isinstance(int/float/str)`，枚举字符串仍扁平化为纯 str。
  - `infrastructure/cache.py:_primitives` 同步改为 isinstance（datastore 快照含 long，否则刷新/读缓存也会失败）。
  - 同类严格判定在**写路径**一并修复（真机这些 xsd:long 字段同样是 long 子类）：`providers/vsphere/devices.py` 新增 `is_integer()`（接受 long/byte/short 子类、排除 bool/None/float），替换磁盘 `capacityInKB`、控制器 `scsiCtlrUnitNumber`、`maxVirtualDiskCapacity`、`summary.freeSpace` 四处；`providers/vsphere/media.py` ISO `fileSize` 复用同一 helper。影响 `inventory list/inspect/export --kind datastore`、磁盘扩容/加盘、ISO 挂载证据复核。
- **缺陷 2（严重，`datastore browse/scan` 真机 `task_identity_mismatch`）**：真机 DatastoreBrowser 任务 `_moId` 为会话形态 `session[uuid]…`，旧正则只接受 `task-\d+`，在任务成功提交后的观测阶段误拒。
  - `providers/vsphere/datastores.py` 新增导出 `valid_task_id()`，保守白名单正则同时接受 `task-N` 与 `session[…]后缀`（限定安全字符集 + 长度上界，拒绝空白/引号/路径/shell 元字符）；`observe()` 改用它。
  - `providers/vsphere/media.py` ISO 证据复核的同一过窄正则改为复用 `valid_task_id`（并移除多余 `import re`）。
  - **安全身份绑定不放松**：`about.instanceUuid` 跨 vCenter 校验 + `task.info.key == 登记 task_id` 仍在，新增回归用例证明换 server/换任务仍被拒。
- **缺陷 3（机器解析，export 失败 JSON 混入 table 抬头）**：根因是 argparse 全局 `--format`(json/table) 与 `inventory export` 叶子 `--format`(json/csv) **dest 同名冲突**——叶子 `--format csv` 把控制台渲染也冲成非 json，失败 JSON 前被加 `状态 | failed`；且全局 `--format table` 会被叶子 choices 误拒为 invalid_arguments。`cli/main.py` 全局参数改用独立 dest `output_format`，与叶子文件格式解耦；现叶子 csv 失败输出为纯 JSON，全局 table 与叶子 csv 可并存。
- **回归测试**：新增 `tests/test_real_type_contracts.py`（12 例）用真实 `VmomiSupport.long` + 真实 pyVmomi FilterSpec/ContainerView + 会话形态任务 id 锁住三缺陷，含"换 server/换任务仍拒绝"的安全反例。全量离线 **468 项全部通过**（原 456 + 新 12）。
- 报告第五节另一条建议（未预期异常统一吞成 `internal_error`、真机 sqlite disk I/O 难排障）本轮**未改**：异常类别可能泄露内部细节，是否在错误信封附带脱敏类别名单独评估。环境产物（首轮沙箱写坏本地 state.db，4 条 internal_error）非 Skill 缺陷，按报告建议由用户手工处理真实 `~/Library/Application Support/vcenter-aiops/state.db`（先备份）。
- 版本：四处版本串（pyproject / manifest / SKILL / `__init__.__version__`）同步 `3.0.0b2`，干净重建 wheel 并 verify，rsync 同步安装副本。仍**未连接**真实 vCenter；缺陷 1/2 修复待真机重跑 D08/D15/D16/D25b 确认。

## 2026-10-13 工程治理：代码复查 + 性能优化 + 清理（b2 → b3）

不改变命令契约与功能，聚焦健壮性与热路径冗余。全量离线 **468 项保持全部通过**。

**代码复查发现并修复（逐模块扫描动作链路）**：
- **P1 OVF 导入可能无限等待**：`ovf_deploy` 的 submit 原先以 `deadline=None` 驱动 lease，vCenter 若长期不把 HttpNfcLease 置 ready/done，命令会永久挂起。改为给 `drive()` 传有界等待：新增 `NFC_LEASE_WAIT_SECONDS=1800`（等 ready 窗口）；`ovf_lease.drive()` 拆成两个窗口——`deadline` 只约束"等 ready"，字节上传在 ready 分支内同步完成（不计入窗口，大文件不被误杀），`HttpNfcLeaseComplete` 后再以 `POST_COMPLETE_WAIT_SECONDS=300` 约束 vCenter finalize；任何路径都不再永久阻塞。
- **P2 HTTP 连接/socket 泄漏**：`guest_http.get_url/put_url` 与 `ovf_http` 重定向循环在非 200、超限、异常等路径未关闭 http.client 连接。统一用 `contextlib.closing(connection)` 包裹，成功/重定向/错误路径均释放。
- **P3 Guest 上传内存放大**：`guest_upload` 原先先 `read_bytes()` 读全文件、再由传输层拒超 4MiB，超大文件会先被整块读入内存。改为读入前先 `stat().st_size` 预检，超限立即 `guest_file_too_large`（传输层 4MiB 上界保留作第二道约束）。
- **误报排除**：审查曾怀疑 host 维护态硬编码 connected，核实为误报——vSphere 维护模式是独立布尔 `inMaintenanceMode`，维护中主机连接态仍为 connected，两者不互斥。
- **设计项维持现状（有意决策，记录不改）**：①`vm guest-upload/download` 虽是 remote_write/risk=change 但不经 plan/confirm 引擎——Guest 文件传输是同步、无服务端 Task、默认拒绝覆盖（幂等）、凭据受限的操作，不产生需对账的远端任务，强套状态机会失真契约；guest-exec/customize 等真正异步动作仍走引擎。②`Parameter("argv", default=[])` 可变默认值当前无害（Parameter 不原地改写 default、注册表进程内只读），保留。

**性能优化（不改功能/稳定性）**：
- 消除只读命令的重复 SOAP：`RetrieveContent()` 在 pyVmomi 是真实往返且不缓存。`connection.server_info(si, content=None)` 增加可选 content；各只读命令把 provider 在 `__init__` 已缓存的 content 透传复用，覆盖 inventory read/export、alarms、events、quota、ip check/available、vm snapshot-list/tools-status/wait-tools。每条只读命令因此少一次 `RetrieveContent` 往返。
- `datastores` provider 改为惰性缓存 content（`@property content/server_uuid`）供 prepare 复用；**刻意保留** observe 阶段一次实时 `RetrieveContent()` 做跨服务器新鲜身份校验（安全防护，有回归测试锁定，不缓存）。
- 其余热路径复核后确认无需改：PropertyCollector 批量取属性无 N+1、事件 collector 单页读取、Engine 轮询指数退避（封顶 2s、随 deadline 收敛）、Store 每命令 `CREATE TABLE IF NOT EXISTS` 为本地亚毫秒幂等保障、懒加载使 version/doctor 不 import pyVmomi（冷启动约 0.4s）。

**无用文件清理**：仅删除可由构建工具再生、且被 `.gitignore` 覆盖的中间产物——`build/`（75 个陈旧 `build/lib` 拷贝，576K）、`src/vcenter_aiops.egg-info/`（28K）、9 个 `__pycache__/`（约 1.5M）。无源码/资源/配置删除；AST 死代码分析确认 75 个源码模块全部可达、111 个 handler 无悬空；references 四份与 scripts 两个均被引用，属受版本控制交付物，不删；本目录无 `docs/`（历史台账中的 docs 引用为仓库上层路径），无会议产物/临时附件/`.bak/.orig/.DS_Store` 残留。

- 版本：五处版本串（pyproject / manifest / SKILL frontmatter+正文 / `__init__.__version__`）同步 `3.0.0b3`，重生成 COMMAND-INTERACTION.md（标题/version 自动 b3，111 条，`--check` 幂等），干净重建 wheel 并 verify（verified=true，75 模块），全新临时 venv 安装冒烟，rsync 同步安装副本。仍**未连接**真实 vCenter。

## 2026-10-14 克隆模版标准流程迁移（b3 → b4）

以 **vcenter-ops v2.0「克隆模版」内部标准流程**为参照，把等价能力以独立 Provider + 独立命令 `deploy clone-template` 接入 aiops 确认执行引擎。**不收窄、不改动**既有 `deploy template`（模板部署）、`vm clone`（普通 VM 克隆安全原语）；不修改无关功能。

**命令契约（operation_id=`deploy.clone_template`，risk=change，asynchronous，provider_kind=`template_clone`，7 项特权）**：
- 必填：`--vm-id`（源**模板** MoRef `vm-N`，强制为模板）、`--name`（1–80 字符）、`--folder-id group-vN`、`--pool-id resgroup-N`、`--datastore-id datastore-N`。
- 可选：`--host-id host-N`（**省略走集群 DRS**，经 cluster.resourcePool 放置）、`--network-id`（标准 `network-N` 或分布式 `dvportgroup-N`，省略保留模板网卡）、`--cpu`/`--memory-gb`（整数 ≥1，克隆时改配）、`--disk-gb`（首盘目标 GiB，**仅允许大于模板当前容量的扩容**）、`--ip-address`（给定静态 IPv4 即**开机 + Linux 定制**，省略则克隆为**关机** VM）、`--subnet-mask`（默认 `255.255.255.0`）、`--gateway`（省略不设网关）、`--guest-domain`（默认 `local`）。

**与 vcenter-ops 流程的核心映射（交互/字段语义/默认值/去重/结果保持等价）**：
| 维度 | vcenter-ops v2.0 | vcenter-aiops |
| --- | --- | --- |
| 触发入口 | `handler.py --action clone_vm` 单次直执行 | `deploy clone-template` 走 preview→plan→confirm→apply→observe/verify/reconcile |
| 参数来源/优先级 | CLI > history(`--from-last/--from-vm`) > preset(`--preset`) | aiops 无 preset/history 合并，参数一次性显式传入，由 schema 校验 |
| 资源寻址 | 名称经 `_get_obj` 定位（同名歧义需消歧） | **MoRef 精确 ID**（`vm-/group-v/resgroup-/host-/datastore-/network-/dvportgroup-`），沿用全栈强身份模型 |
| 克隆提交 | `CloneVM_Task` + 克隆**后二次** `ReconfigVM_Task` 扩盘/改网卡 | **单次原子** `CloneVM_Task`：把 NIC edit + disk edit 并入 `CloneSpec.config.deviceChange`（`VirtualDeviceSpec(operation=edit)`），结果等价、无中间半成品 |
| 放置 | host 缺省走 `cluster.resourcePool`（DRS） | 相同：host 省略时 `RelocateSpec.pool=pool`、不设 host |
| 固定 IP/开机 | 给 `ip_address` → powerOn + `LinuxPrep`/`FixedIp`；不给关机；`--mask` 默认 /24、`--gw` | 相同语义：`--ip-address` 触发 powerOn + `CustomizationSpec(LinuxPrep + FixedIp + GlobalIPSettings)`；`--subnet-mask` 默认 /24、`--gateway`、`--guest-domain` 默认 local；不给 IP 关机 |
| 重复提交 | TaskManager `vct-` 任务，命令级重跑 | 确认引擎 **request_id 绑定 profile+steps 幂等**；同 plan 返回同一 operation，写后异常按"结果未知不重发"处理 |
| 权限 | executor 调用方权限 | 按实体分别核对：模板 DeployTemplate/CreateFromExisting、池 AssignVMToPool、DS AllocateSpace、网络 Network.Assign、PowerOn、Provisioning.Customize（`HasPrivilegeOnEntity`） |
| 返回/异常 | 信封 `{status,action,data,message}`，外层 except「执行异常: …」 | 统一信封；前置/参数失败分类 `invalid_arguments`/`precondition_failed`/`target_exists`/`placement_invalid`/`unauthorized`/`capacity_unavailable`，提交后失败经 task observe/verify 呈现 |

**有意的架构适配偏差（结果展示一处差异，须知悉）**：vcenter-ops 在命令内 `wait_for_tools_ready`（默认 300s，`--no-wait-tools` 跳过，超时仅告警）；aiops **不把长 Guest 引导/Tools 等待塞进确认引擎**——静态 IP 克隆提交成功只证明 VM 已创建（有 IP 时 vCenter 已开始开机+定制），Tools/IP 就绪交给既有 `vm wait-tools` / `task wait`，并在 binding warning `TOOLS_HINT` 明确引导核对。其余交互与字段语义一致。

**实现**：新增 `providers/vsphere/template_clone.py`（`TemplateClone`：preflight 全量校验 + 按实体核权 + 同 DC/同名拒绝/DS 容量/仅扩容/IPv4 校验；submit 提交前重跑 preflight 比对，异常包成 `SubmissionRejected`；`_clone_spec` 单次原子构造；observe/verify 校验新 VM 身份、name/folder/pool/电源态（有 IP=poweredOn）/DS/host/CPU/内存/磁盘容量/网卡 backing（标准网络或 DVPG portgroupKey+switchUuid）；自实现 cancel 仅允许单步骤、校验 cancelable+queued/running）；注册到 `registry.py`（命令 111→112）、`commands/changes.py`（薄 preview）、`providers.py`（懒加载）。设备对象改配前 `copy.copy`，不原地污染模板。

**测试**：新增 `tests/test_template_clone.py`（13 例，真实 pyVmomi 对象图 + SOAP Stub）：最小关机克隆单任务、DRS 省略 host、完整 spec（改网+CPU4/内存8192MiB+扩盘100GiB+固定IP/默认掩码域/powerOn）、DVPG backing、非模板拒绝、坏 IP/掩码拒绝、磁盘缩容/等容拒绝、同名拒绝、容量不足、权限不足、缺必填、Engine request_id 去重、失败任务 observe=error/verify=False。另新增 `tests/test_template_clone_flow.py`（15 例，Engine 级桩件，`ProviderRouter(None, providers={...})` 注入 + 临时 Store）：完整 preview/confirm/apply 成功、非模板预检拒绝零写、apply 前漂移抛 `target_exists` 零写、submit 包 `SubmissionRejected`、远端 error→failed 不重试、同 request_id 同 plan 仅提交一次、同 request_id 改参→`request_conflict`、**提交响应丢失→`reconciliation_required` 且 reconcile/重放都不二次提交**、running 可取消一次（再取消失效）、取消需精确 `server:task`、clone 无补偿→`compensation_unavailable`、多步骤计划 `plan_dependency_unsupported`、receipt/observation JSON 持久化、`RequestCanceled`→cancelled、running 经 reconcile 达 succeeded。全量离线 **496 项全部通过**（468+13+15）。桩件修复记录：共享夹具 TaskInfo 初版缺 `cancelable` 字段致取消测试误报，补齐后通过——属夹具缺口非产品缺陷。该命令在 COMMAND-INTERACTION 分级为**②逻辑级**（Provider/Engine 方法被直接断言、叶子为薄包装，已登记 `TIER_FIX` 覆盖 `test_template_clone.py`+`test_template_clone_flow.py`）。

- 验证：版本五处升 `3.0.0b4`，重生成 COMMAND-INTERACTION.md（112 条，覆盖汇总 ①73 + ②35 + ③3 + ④1，`--check` 幂等）；干净重建 wheel 并 verify（**verified=true，76 模块**=75+template_clone）；全新临时 venv 安装冒烟（version=3.0.0b4、doctor 依赖齐全 connected=false、capabilities=112、`deploy clone-template --help` 与 capabilities show 契约正确、缺必填/越界整数退出码 2）；rsync 同步安装副本并逐模块 diff 一致（排除 tests/build/dist/egg-info/pycache）。仍**未连接**真实 vCenter；静态 IP 定制、DVPG、DRS 放置、Linux Guest 引导与四系列（6.5/6.7/7.0/8.0）兼容性待实机验收。

- 克隆一致性核对与清理（2026-10-14，同 b4）：逐项比对 vcenter-ops 2.0 `clone_vm_advanced` 后，确认 CloneSpec/RelocateSpec/ConfigSpec 结构、datastore+pool(+host) 放置、numCPUs、memoryMB=gb×1024、首盘 capacityInKB=gb×1024²、网卡 edit（标准/DVPG portgroupKey+switchUuid）、有 IP 才 powerOn+LinuxPrep(FixedName=新名)+FixedIp+AdapterMapping+GlobalIPSettings、掩码默认 /24、template=False 均一致；aiops 侧差异均为**有意架构适配**（MoRef 寻址、单次原子 CloneSpec 合并 NIC+disk、Tools 不阻塞、request_id 幂等/未知不重发、强制源为模板、7 项按实体 HasPrivilege、缩容即拒、guest_domain 可配），vcenter-ops 的 preset/history 合并、cache invalidate、event bus、命令内 Tools 等待在 aiops 架构中无对应（由确认引擎/显式 cache invalidate/`vm wait-tools` 等价承担）。死代码清理 8 处（经 Grep/pyflakes 双重确认零引用）：`ovf.py` 去 `import io`、`guest_http.py` 去未用 `ssl_context` 导入、`clusters.py`/`guest_transfer.py`/`ovf_lease.py` 去未用 `OperationError`、`history.py` 去 `import time`、`commands/cache.py` 去未用局部 `config`、`template_clone.py` 去未用常量 `SUPPORTED_VERSION`（版本校验仍由复用的 `Hosts._server` 承担）。删除全部 `__pycache__`/`dist/`/`build/`/egg-info 可再生产物。清理后回归：**src 全量 pyflakes 零告警、496 测试全过（16.3s）、干净 wheel verify 76 模块、全新 venv 冒烟通过**；76 个源码模块经静态可达性分析无孤立/无重复。

## 2026-10-16 静态安全审计与 M1–M4 中危加固（b4 同版本，不改命令契约）

对全部 76 个源码模块做严格只读静态安全扫描（注入/越权/敏感信息泄露/不安全依赖/硬编码凭证/权限控制），结论：**严重 0、高危 0、中危 4（M1–M4，本次全部修复）、低危 4（L1–L4，记录为设计取舍或残余面）**；报告见仓库上层 `.workbuddy/reports/vcenter-aiops-security-audit-2026-10-16.html`。四项中危均为输入/配置/供应链加固，**不改变任何命令签名、特权或确认流程**，版本维持 `3.0.0b4`。

| 编号 | 风险 | 位置 | 修复 |
| --- | --- | --- | --- |
| M1 | `ip check/available` 的 address 虽以 argv 列表传 ping（无 shell 注入），但以 `-` 开头会被 ping 解释为选项（参数注入） | `application/ipsignals.py` | 新增 `require_ip_address()`，用标准库 `ipaddress.ip_address()` 收口，仅接受字面 IPv4/IPv6，拒绝主机名/网段/选项/非字符串；在 `ping_probe`、`IpSignals.check`、`IpSignals.available` 三入口调用 |
| M2 | `paths.ensure_private()` 的 `mkdir(mode=0o700)` 仅对新建叶子目录生效；已存在的宽松权限目录不被收紧 | `infrastructure/paths.py` | posix 下建目录后 `lstat` 复检：拒绝符号链接/非目录（`data_directory_invalid`），属主非本人或 `st_mode & 0o077` 非零时 `chmod 0700` 收紧；只收紧叶子目录，不改写父级 |
| M3 | Profile 设 `verify_tls=false` 时切 `CERT_NONE`（默认安全），读路径有 warning，但 remote_write/plan apply 写路径缺告警 | `cli/main.py` | 汇聚层新增 `append_tls_warning()`：remote_write 类及 `plan apply`/`plan reconcile` 成功且该 profile 关闭 TLS 校验时，结果附加固定中文告警，去重、error 结果不装饰 |
| M4 | 运行时依赖仅区间约束、无哈希锁，存在依赖混淆/篡改面 | `requirements/requirements.lock`（新增） | 产出 `pip install --require-hashes` 锁文件：pyvmomi 9.1.1.0 / PyYAML 6.0.3 / cryptography 48.0.1（标 optional [secrets]）/ cffi 2.1.1 / pycparser 3.11 / typing-extensions 4.16.0，227 个 sha256 覆盖锁定版本全部平台 wheel+sdist，含环境标记；全新 venv 正向安装通过、篡改首哈希即被 pip 以 DO NOT MATCH THE HASHES 拒绝 |

**测试**：新增 13 例回归——`tests/test_ip_signals.py` +2（合法 v4/v6 放行；`-c10`/`-D`/`--adaptive`/主机名/网段/带空格/整数全拒且 pinger 零调用，共 11 例）、新建 `tests/test_paths.py` 5（新建即 0700、已存 0777 收紧、0750 去组位、符号链接拒绝、父目录 0755 不被改写）、新建 `tests/test_tls_warning.py` 6（remote_write 关闭告警/开启静默/只加一次/error 不装饰/plan apply 覆盖/CLI 端到端 preview 携带）。全量离线 **509 项全部通过（14.9s）**（496 + 13）。低危 L1–L4（run.ps1/run.bat Bypass 执行策略、Guest wrapper base64+exec 的设计取舍、guard hook 仅审计不阻断、异常脱敏残余面）维持记录、未改代码。

- 验证：src 与三个新/改测试文件 pyflakes 零告警；干净重建 wheel 并 verify（**verified=true，76 模块**，requirements/ 不打包入 wheel）；全新 3.13 venv 先按哈希锁装依赖再 `--no-deps` 装 wheel 冒烟（缺参/`--cpu 0` 退出码 2，pyVmomi/yaml/cryptography/cffi/pycparser 与 M1/M2 新符号导入正常）；清理 build/dist/egg-info/pycache；rsync 同步安装副本 `~/.workbuddy/skills/vcenter-aiops/`（src 逐字节 diff 一致、新增 requirements/requirements.lock，另顺带同步了 b4 已提交但副本缺失的 `guest_http.ssl_context` 再导出）。仍**未连接**真实 vCenter，版本仍为 `3.0.0b4`，改动未提交 git。

## 2026-10-16 运行时性能与安全深度检查：S1 cryptography CVE 分平台修复（b4 同版本）

对"项目/运行中的应用"做运行时性能 + 安全深度检查（响应延迟/CPU/内存/泄漏/DB/缓存/并发/异常日志；注入/认证授权/泄露/不安全配置/依赖风险）。结论：**严重 0、高危 0、中危 3（S1 依赖 CVE、P1 轮询空转写库、P2 异常无落盘）、低危 4（P3–P6）、健康项 9**；报告见仓库上层 `.workbuddy/reports/vcenter-aiops-runtime-perf-security-2026-10-16.html`。架构本质是一次性调用即退出的单机 CLI（无 ThreadPool/常驻进程/全局可变缓存，实测峰值 RSS≈25 MB），无传统泄漏/线程竞争面。本轮按推荐落地**唯一可立即修复项 S1**；P1–P6 为 rc/真机阶段的长期优化，未改代码。

**S1 — cryptography 已知 CVE（依赖风险）**：
- OSV.dev 2026-10-16 查询：`cryptography==48.0.1` 命中 3 个唯一 CVE——CVE-2026-69247（PKCS#7 EnvelopedData Bleichenbacher 预言机，fixed 50.0.0）、CVE-2026-69249（重复自签中间证书路径构建指数级 DoS，fixed 49.0.0）、CVE-2026-69248（通配 DNS 名绕过 nameConstraints，fixed 49.0.0）；OSV 另以 3 条 PYSEC 镜像呈现，共 6 条记录。本项目仅使用 `cryptography.fernet.Fernet`（`infrastructure/secrets.py`），**不触及 X.509/PKCS#7 路径（漏洞功能不可达）**，且唯一 profile `lab` 凭据走 `env:` 引用、本机运行根本不 import cryptography（optional `[secrets]` extra），故定中危。
- **上游 wheel 断层（关键约束）**：48.0.1 是最后一个提供 macOS universal2/x86_64 wheel 的版本；49.0.0 起 macOS wheel 只剩 arm64（Linux manylinux/musllinux 与 Windows wheel 仍齐全）。本机为 Intel Mac（x86_64），强锁 50 会回退 sdist、需要新版 Rust（本机 1.73 过旧，Cargo.lock 解析失败）。经用户决策采用**分平台环境标记（marker）**方案：同一锁文件内 50.0.2 配"非 Intel-Mac"marker、48.0.1 配"Intel-Mac"marker，两分支严格互斥；两版本传递依赖完全一致（cffi>=2.0.0 非 PyPy、typing-extensions>=4.13.2 仅 py<3.11、bcrypt 仅 ssh extra），现有 pin 共用。
- **改动**：`pyproject.toml` 的 `secrets` extra 由 `cryptography>=48.0.1,<49` 放宽为 `cryptography>=48.0.1,<51`；`requirements/requirements.lock` 拆为两段——`cryptography==50.0.2`（非 Intel-Mac，59 个 sha256）+ `cryptography==48.0.1`（仅 Intel-Mac，49 个 sha256，注释标明携带 CVE 但仅 Fernet 使用、env: 路径不加载）。锁文件现 317 行、286 个 sha256、7 个 pin。
- **marker 写法坑（实测）**：初版 50 分支用 `not (sys_platform=='darwin' and (...))`，pip（含 26.2.1，vendored packaging）解析即报 `Invalid marker: Expected a marker variable or quoted string`——该版本 marker 语法不接受顶层 `not (...)`。按 **De Morgan 改为正向** `sys_platform != 'darwin' or (platform_machine != 'x86_64' and platform_machine != 'i386')`，与 48 分支 `sys_platform == 'darwin' and (platform_machine == 'x86_64' or ...)` 经真值表验证在 darwin/linux/win × x86_64/i386/arm64 六组合上**严格互补**。

**验证（系统原生 CPython 3.13.12，`env -u PYTHONPATH` 去 WorkBuddy shim，全新 /tmp/s1_venv）**：
- 锁文件结构自校验：317 行 / 286 hash / 7 pin，无悬空或缺失续行符，两 marker 互为否定。
- 全新 `pip install --require-hashes -r requirements.lock` 在 Intel Mac **正确忽略 50 分支、选中 `cryptography-48.0.1-cp311-abi3-macosx_10_9_universal2.whl` 纯二进制安装成功**（pyvmomi 9.1.1.0 / PyYAML 6.0.3 / cffi 2.1.1 / pycparser 3.11），无 Rust/sdist 回退；Fernet encrypt/decrypt 往返通过。
- 50.0.2 三目标平台二进制 wheel 可解析性（`pip download --only-binary :all:` 跨平台）：manylinux2014_x86_64、win_amd64、macosx_11_0_arm64 均取到 `cp311-abi3` wheel。
- 哈希负向测试：将候选 hash 集合整体伪造（最小锁只列一个 `deadbeef…`）时 pip 以 **THESE PACKAGES DO NOT MATCH THE HASHES** 拒绝（Expected 伪造值 / Got 锁内真实值）。注：仅改多工件段中单个 hash 不会触发拒绝——pip 只需下载到的 wheel 命中该版本列出的任一合法 hash，这是多平台全工件列哈希的预期语义；有效负向测试须使全部候选 hash 失效。
- Fernet 跨版本兼容证据：token 为标准 Fernet（版本字节 0x80 + 8B 时间戳 + 16B IV + 密文 + 32B HMAC），解密契约独立于本次 CVE 涉及的 X.509/PKCS#7 代码，48↔50 互通；本机两侧均解析为 48.0.1，arm64/Linux/Win 侧 50.0.2 的真机互通留待 CI/实机（如实记录边界）。
- OSV 复查：`cryptography==50.0.2` **0 公告**；`48.0.1` 仍 3 个唯一 CVE（仅 Intel-Mac 兜底、路径不可达、env: 不加载）。
- 全量离线 **509 项保持全部通过（16.0s）**（S1 不动 src）；安装副本 `~/.workbuddy/skills/vcenter-aiops/` 的 `requirements.lock` 与 `pyproject.toml` 已同步并 `cmp` 逐字节一致（副本 pyproject 由 `<49` 更新到 `<51`）。仍**未连接**真实 vCenter，版本仍 `3.0.0b4`，改动未提交 git。

## 2026-10-16 b4 真机验收缺陷 D1–D3 修复（8.0.3 build-24091160，b4 同版本）

依据真机验收产出的《vcenter-aiops-缺陷修复-b4-20261016》修复三项缺陷。共性根因：**离线假桩与真机返回形态不一致 → CI 全绿但真机必现**。三处均为 fail-closed 边界对真机形态过严或漏捕，本轮按"能力选择替代基数断言""悬空 MoRef 归一化"做最小修复，**不放松任何既有安全前提**，不改命令签名/确认语义，版本维持 `3.0.0b4`。

| 编号 | 级别 | 现象 / 复现 | 根因 | 修复 |
| --- | --- | --- | --- | --- |
| D1 | P0（阻断 GA） | `vm create` 真机任意放置（VMFS/vSAN）dry-run 必报 `capability_unsupported: 磁盘能力不可确定` | 代码假设非废弃 `VirtualDiskOption` **恰为 1 个**；8.0.3 真机 `QueryConfigOption(key, host)` 返回 **4 个按总线区分但 backing 能力等价**的磁盘选项（backingOption 同为 FlatVer2/SparseVer2/SeSparse/RawDiskMappingVer1/LocalPMem）。同源两处：`hardware.py`（vm create）与 `devices.py`（vm reconfigure 扩容预检） | 新增共享 helper `hardware.select_new_disk_option()`：遍历非废弃磁盘候选，**按能力选出恰有 1 个 FlatVer2BackingOption（type=FlatVer2BackingInfo）+ diskMode 含 persistent + thinProvisioned 可判定**的选项；0 个合格才 `capability_unsupported(exit4)`，多个等价时确定性取服务序首个，evidence 记 `disk_option_candidates`/`disk_option_qualified`。`hardware.capability()` 与 `devices.preflight()` 共用 |
| D2 | P2（可诊断性） | `cluster delete --cluster-id domain-c99999999 --dry-run` 返回 `internal_error/exit5` | 形态合法但悬空的 MoRef 裸构造不触发取数，首次属性读取（`_state()` 读 parent/resourcePool/host）才抛 `vmodl.fault.ManagedObjectNotFound`，未捕获 | `clusters.py` 新增 `_existing_cluster()`：非 create 预检统一经此解析；仅当 `fault.obj._moId` 为请求 ID（或缺失）时归一化为结构化 `cluster_not_found(exit4)` 且消息含用户自填 ID，**命名其他对象的 fault 原样上抛**（防误吞） |
| D3 | P2 | `batch power-on/power-off/shutdown/reset --vm-ids '["vm-99999999"]'` 原子预览返回 `internal_error/exit5`；应指出具体 vm_id | 同源：`mutations.vm()` 读 `vm.config` 时悬空 MoRef 抛 `ManagedObjectNotFound` 未捕获 | `mutations.vm()` 捕获后仅在 `fault.obj._moId == 请求 vm_id` 时归一化为 `vm_not_found(exit4)` 并带具体 ID，否则 re-raise；畸形 ID 仍走 `target_invalid(exit2)`（不混淆）。batch 的 read_only/orchestration 语义、原子性不变，仅修错误码。`verify()` 同时把删除后置条件（对象已消失）判 True——仅 `vm delete` 遇 `vm_not_found`/该 fault 为成功，其他命令为 False |

**保持不变的安全前提（未放松）**：Guest OS 唯一命中（`len(guests)==1` + supportedForCreate + supportedMaxCPUs/内存 bounds）、控制器类型唯一基数断言（真机控制器唯一，`len(controller_options)==1` 保留）与控制器 supportedDevice/noSharing、网卡支持集、FlatVer2+persistent+thick(thin=False) 唯一 backing、`bounds()` 容量范围、扩容仅编辑现存磁盘且**不缩容/不隐式删除/字节容量一致**、链接磁盘 `dependency_unproven` fail-closed、危险操作二次确认。

**测试（新增 11 例对齐真机形态）**：
- `tests/test_vm_creation.py` +3：4 个等价磁盘选项确定性取其一不失败（evidence candidates/qualified==4，submit 后单盘 FlatVer2 persistent thin=False）；0 个合格 FlatVer2 backing → capability_unsupported；4 个全 deprecated → 仍失败（证明不回退废弃选项）。夹具 helper 深拷贝原地替换磁盘索引，保留控制器/网卡固定索引（[2]/[0] 约束不重排）。
- `tests/test_vm_devices.py` +2：4 等价选项允许扩容（after_kb=16GiB、calls 空）；清空 backing 阻断扩容。
- `tests/test_cluster_lifecycle.py` +2：悬空 domain-c999999 的 delete/configure → cluster_not_found/exit4/含 ID/calls 空；fault 命名其他对象（domain-c777）时原样抛 ManagedObjectNotFound 不被吞。
- `tests/test_vm_provider.py` +4：四电源命令悬空 vm → vm_not_found/exit4/含 ID；batch bind_steps 第二步悬空报首个缺失 vm_id；"not-a-mor" → target_invalid/exit2；power-on 建合法 binding 后切悬空 resolver，`vm delete` verify=True、`vm power-on` verify=False（删除后置语义）。fault.obj 用真实 `vim.VirtualMachine` 构造（DataObject 校验拒绝 SimpleNamespace）。

- 验证：8 个改动文件 **pyflakes 零告警**（修复过程中曾自检发现 verify() 误删局部 `from pyVmomi import vmodl` 致 re-raise 分支 NameError，已补回——该路径被"fault 始终匹配请求 ID"的既有测试漏网）；定向四模块 **69 例通过**；全量离线 **520 项全部通过（14.9s）**（509 + 11）。安装副本 `~/.workbuddy/skills/vcenter-aiops/` 的 4 个 src 文件已同步并 `cmp` 逐字节一致（副本为无 tests 的发布子集）。仍**未连接**真实 vCenter，版本仍 `3.0.0b4`，改动未提交 git。

**后续项（本轮按"最小修复"未扩展，需在 rc 前统一收口）**：修复单建议的更广悬空 MoRef 覆盖点——host/datastore/folder/task 等其他对象类型的首次属性读取，以及 `task inspect/wait/reconcile/cancel`、`plan` 系列对 ManagedObjectNotFound 的统一归一化，本轮未改；真机 dry-run 复测（vm create 任意放置 VMFS/vSAN、cluster delete、batch 悬空 ID）需用户在 8.0.3 实机执行确认。

## 2026-10-16 b4 风险分级与分级管控机制（阶段 D-1）

为全部 112 条已注册命令建立三级风险分级与执行前管控门，满足"低风险只读直跑 / 敏感操作先说明影响范围并二次确认 / 不可逆操作确认前列出精确目标（资源·路径·范围·数量），禁止模糊匹配与过宽通配"的要求。**不改命令签名、特权核权、计划引擎 digest/DESTROY 确认与"未知不重发"语义；门挂在 CLI 层，520 个程序化 handler 单测不受影响。**

### 三级模型（真值来源 `src/vcenter_aiops/domain/risk.py`，纯数据/纯函数、零 SDK）

| 级别 | 数量 | 范围 | CLI 管控 |
| --- | --- | --- | --- |
| low | 54 | 只读/预览（local_read/remote_read，不含导出/传输） | 直接执行，无确认 |
| medium | 43 | 敏感但可逆/增量：经引擎的 change 类（电源/克隆/部署/改配/来宾执行）+ 直接生效的 secret set、profile add/update、ip reserve、preset save/from-*、plan archive、audit/inventory export、guest download/upload、task cancel | 执行前打印敏感类别+影响范围+精确目标；终端逐字键入目标确认，非交互须 `--yes/-y` |
| high | 15 | 5 条 destructive（vm delete、snapshot revert/delete、cluster remove-host/delete）+ 4 条 batch 批量电源 + secret rotate/delete、profile delete、ip release、cache invalidate、preset delete；`guest-upload --overwrite`、`ip expire --apply` 按参数动态升级 | 确认前逐条列精确目标（资源/路径/范围/数量），拒绝通配/模糊；终端先逐字输入精确目标、再输入动作关键字 DELETE/CLEAR/OVERWRITE/TERMINATE（批量为 `BATCH-<数量>`）二次确认；`--yes` 仅跳过交互、不放宽精确校验 |

### 关键实现

- `domain/contracts.py`：`describe()` 新增 `risk_level`/`sensitive_categories`/`irreversible_categories`（`capabilities show` 可读，兼容旧 `risk`/`category`）。
- `domain/risk.py`（新增）：`risk_level/risk_tags/is_direct_effect/precise_targets/validate_exact_targets/confirmation_token/is_wildcard`；集中 `_OVERRIDES` 修正了两类历史错标——①4 个 `batch power-*`（原 risk=read_only，实为批量写）；②15 个直接生效本地写（原 risk=read_only、零确认）。通配判定拒绝 `* ? [ ] { } %` 与 `.*`/`.+`，但允许文件路径中的空格（值从不进 shell）。
- `cli/main.py`：新增 `direct_effect_gate()`（直接生效命令的统一门，非 TTY 未授权 exit4 `confirmation_required`，目标不精确即使 `--yes` 也 exit2 `target_not_exact`）；`interactive_apply()` 扩展覆盖 batch（枚举每台序号+总数→digest→`BATCH-<n>`）；新增全局与叶子两级 `--yes/-y`（动词前后均可）。参数/配置错误（exit2/3）先于确认门返回。
- 经计划引擎的远端写继续以 sha256 计划 digest（destructive 再加 `DESTROY:<digest>`）为确认值，CLI 门只在其上补人类可读横幅，不新建第二套确认状态机。

### 测试与验证

- 新增 `tests/test_risk_classification.py`（**13** 例：112 命令分级完备且无未知级、destructive 必 high、5 条 destructive 集合精确、batch high+bulk、override 指向真实命令、本地写必直接生效、只读必 low、批量枚举/数量、通配/重复/空/超 100 拒绝、路径允许空格、guest-overwrite 与 ip expire --apply 动态升级）。
- 新增 `tests/test_risk_gate_cli.py`（14 例：低直跑；中风险非 TTY 拦截/`--yes` 授权/动词后 `--yes`/TTY 精确确认/错误取消；高风险非 TTY 拦截/TTY 错误目标取消/正确目标错误关键字取消/正确目标+DELETE 放行/带 `--yes` 通配仍 exit2；inventory export 门先于联网；批量枚举+digest+`BATCH-2` 放行、`BATCH-3` 取消不提交）。
- 既有 handler 级 CLI 测试（test_secrets/test_foundation/test_audit/test_history_presets_policy）在非 TTY 下显式 `--yes` 表达"自动化已授权"，handler 内 scope/输入/profile 等校验仍在门后照常生效（前置拒绝仍 exit2/3）。
- 全量 **552 项全部通过**（D-1 前基线 525 + 两新文件净增 27：分级 13 + CLI 门 14；既有 handler 级 CLI 测试仅按非 TTY 自动化语义补 `--yes`，未增删测试方法，16–27s）；src pyflakes 零告警（test_ovf/test_placement 的 3 条 unused 为历史遗留、本次未触碰）；冷启动 import 仍不加载 pyVmomi；`scripts/generate_command_interaction.py` 已纳入三级风险并重新生成 `COMMAND-INTERACTION.md`（`--check` 通过）。

### 边界与未做

- 仅 CLI 交互面加门；MCP 服务面尚未交付（remaining domains），未来落地时须复用 `domain/risk.py` 同一策略。
- 仍**未连接**真实 vCenter，版本维持 `3.0.0b4`，改动未提交 git。标准 `~/.workbuddy/skills/` 下当前无 vcenter-aiops 代码副本（仅数据 home `~/Library/Application Support/vcenter-aiops`），故本轮无物理副本可同步；平台重装后以仓库源码为准。

## 2026-10-16 体检问题全量修复（H/M/L，b4 同版本，不改命令契约）

依据 `vcenter-aiops-healthcheck-2026-10-16.html` 逐项修复并各配离线测试。**核心写路径（preview→plan→confirm→apply→observe/verify/reconcile）、命令签名、特权核权、二次确认、"未知不重发"与 fail-closed 全部保持不变；仍未连真机、版本仍为 3.0.0b4、未提交 git。**

### 高危（H）

- **H-1 悬空 host MoRef**：新增 `Hosts._existing_host()`，resolve+首次受控取数同 try，MONF 且 `fault.obj._moId==host_id`（或 None）归一 `host_not_found/4`，命名他对象 re-raise；写后 observe/verify/cancel 遇 MONF 为"证据过期"→`unknown/6`（`_task()` MONF→`task_state_unknown/6`，verify 增 MONF 分支返回 False），不再冒泡 internal_error/5。
- **H-2 克隆 RelocateSpec 偷换资源池**：`RelocateSpec(datastore=ds, pool=传入pool)`，仅当显式 host 时再 `location.host=host`，不再用 `host.parent.resourcePool` 覆盖用户传入池。
- **H-3 folder 严格 `_id` 误判**：新增 `_is_vm_child()`（`_wsdlName/type==VirtualMachine` 且 `vm-\d+`）与 `_vm_child_ids()`；folder `childEntity` 仅对 VM 子项判同名/计入 before，子文件夹/vApp 不再恒抛 target_unavailable；compute/host 的 `.vm` 清单保持严格（成员必为 VM）。
- **H-4 悬空 MOR 统一收口**：新增公共 `providers/vsphere/mor.py::existing(probe, object_id, code, message)`，接入 datastore browse/scan、devices datastore、placement pool/ds/host/folder、linked mount、ops events entity / quota target、media task、snapshot 枚举边缘；clusters 与 hosts 沿用已验证的内联收口。规则统一：**仅 fault 指向请求对象（或 None）才 `*_not_found/4`，否则 re-raise，畸形 ID 仍 exit2，写后取数 MONF→unknown/6**。
- **H-6 许可适配器放宽（保持 fail-closed）**：`licenses.require()` 接受 0..N 行、同作用域多行 granted 并集、忽略未知 properties 键、无 expirationDate 视为永久；但 0 行→`license_unverifiable/4`，外域/过期/坏 expiry/诊断标记/缺 feature 仍拒。**永久许可在 8.0.3 上的精确官方键名待用户提供脱敏 `QueryAssignedLicenses` 样本后再最终校准。**
- **H-7 64 位整数判定**：`reads.py` 用 `_is_int()`（`isinstance(int) and not bool`）替代 `type() is int`，接受 vmodl long 子类，bool/None/非整仍 `preset_hardware_unsupported/4`。

### 中危（M）

- **M-1 轮询写合并**：`execution.py` 同一事务先 SELECT 当前 state/observation，仅当状态或 canonical(observation) 真正变化才执行 UPDATE/audit，避免每轮 fsync，也不产生 `-wal/-shm` 旁路（方案 A，不引入 WAL）。
- **M-2 observe 权限缓存**：仅缓存按 (run_id, server_uuid, object_id, instance_uuid, digest, 权限集合) 绑定的 HasPrivilege SOAP；**execute 授权永不缓存**，VM/vCenter/tools/session 实时身份每轮读取（缓存整个绑定会破坏 fail-closed，已实测纠正）；ListFilesInGuest 每轮实时；guest wrapper 源按 (path, mtime_ns, size) 模块级缓存，首次防篡改 digest 仍计算。
- **M-3 datastore browse 性能**：prepare/submit 共享每会话 ServiceContent 缓存（`server_uuid` property），submit 把"整段重跑 prepare + 再 resolve 一次"收窄为只复核存在性/`summary.accessible`/datastore 名/server 身份（resolve 一次），消除重复往返；轮询改指数退避 0.2s→cap 2s（与引擎一致）。**observe 的 server 身份门保持实时 `RetrieveContent()` 不缓存**——observe 是跨会话恢复入口，会话若被重连到另一台 vCenter，必须在读同名任务前实时拒绝 `server_mismatch`（与 M-2"实时身份不缓存"同一边界；全量回归曾因初版缓存此门而暴露回归，已纠正并加实时重连用例）。
- **M-4 guest 悬空 VM 预检**：`Guest._identity()` resolve+`vm.config` 取数包同一 try，MONF 匹配→`vm_not_found/4`（预检语义），不再误归 guest_sdk_failed/6。
- **M-5 内部错误脱敏日志**：新增 `infrastructure/diagnostics.py` 与全局 `--debug-log`（或 `VCENTER_AIOPS_DEBUG_LOG=1`，默认关）。仅在 catch-all(exit5) 时把 **fault 类型名 + 本地代码帧(文件/函数/行) + operation_id** 追加到 0700 数据目录 `logs/debug.log`(0600, append, fsync)；**绝不记录 argv/参数/凭据/端点/异常消息原文**；日志失败本身被吞掉，绝不改变 exit5 结果；正常路径不产生日志。
- **M-6 OVF/OVA 预检远端放置取证**：`ovf_deploy.preflight()` 在零 ImportVapp/零 CreateImportSpec/零 HttpNfcLease 前提下，只读取证 pool/host/folder/datastore/全部映射 network 的存在性（陈旧 ID→`*_not_found/4`）、host↔pool 同计算资源、host 已连接非维护、folder 为同 DC 的 VM 文件夹、ds 可访问/非维护且 host 可见、每个 network 在 host 可见，并按实体 HasPrivilege（Resource.AssignVMToPool / Datastore.AllocateSpace / vApp.Import / Network.Assign）；放置快照并入 scope，submit 重跑预检，漂移→`plan_stale`。

### 低危/加固（L）

- **L-1 cluster create 名称白名单**：远端取数前先本地校验 1–80 字符、不含 `/ \ %` 与控制符、无边缘空白（`name_invalid/2`，与 clone 同词汇）。
- **L-2 datastore limit**：`isinstance(int) and not bool and 1<=limit<=1000`。
- **L-3 pyflakes 清零**：删除 `test_ovf.py` 未用 `os`、`test_placement.py` 三个未用局部变量，并清理本轮新增文件的未用导入；`python -m pyflakes src tests` 归零。
- **L-5 hosts 写后 MONF→unknown/6**（随 H-1 完成）。
- **L-6 template_clone 同名检查**只对 VM 子项生效（随 H-3 完成）。
- **L-4 磁盘 / TTL 治理**：见下节。

### L-4 磁盘治理与 TTL 策略（当前**不做**自动删除）

数据 home 默认 `~/Library/Application Support/vcenter-aiops`（可用 `VCENTER_AIOPS_HOME` 覆盖）。落地产物与保留职责：

| 产物 | 位置 | 增长来源 | 策略 |
| --- | --- | --- | --- |
| 状态库 | `state.db`（+ 事务期临时 `-wal/-shm`，正常关闭即回收） | operations / execution_steps 计划与观察、租约、去重账本 | **不自动清理**：reconcile 与幂等去重依赖历史 operation；建议运维侧按保留期（如 ≥180 天）冷归档后 `VACUUM`，删除前须确认无 `running/reconciliation_required` 记录 |
| 审计视图 | `state.db` 内 `audit` 表（HMAC 化名，无载荷） | 每次状态流转一条 | 合规证据，默认永久；如需收敛由外部按 `id`/时间归档，工具不提供删除命令 |
| 审计/inventory 导出 | **用户指定路径**（`audit/inventory export`），禁止覆盖 | 人工每次导出 | 一次性文件，归使用者管理；同目录 `.audit-export-*` 临时文件在 `finally` 即 unlink，异常残留可手动删除 |
| OVA 解包 | **用户指定** `work_dir/unpacked/`（不在数据 home） | 每次 `deploy ova` | 工具不回收用户目录；部署核对完成后由调用方删除该 work_dir |
| 内部错误日志 | `<home>/logs/debug.log`（0700 目录 / 0600 文件，append-only） | 仅 `--debug-log` 或 `VCENTER_AIOPS_DEBUG_LOG=1` 开启时的 exit5 | 默认关闭、零增长；开启后建议随排障轮次轮转（如保留最近 1–5 MB / 7 天），可安全 `truncate` 或删除，不影响 reconcile |
| Profile / 密钥 | 配置文件 + 系统密钥链（`env:`/`secret:` 引用，密钥不落盘） | 人工增删 | 长期保留，仅经 `profile delete` / `secret delete`（均为 high，二次确认）移除 |

原则：**工具不主动删除任何状态/审计/导出数据**——自动回收可能在网络分区后的 reconcile 窗口里抹掉"未知不重发"所需证据。TTL 以运维侧外部归档/轮转承担，文档在此固化职责边界；HTTP/Guest 传输本身已流式有界（单文件 ≤4 MiB、Guest 输出各 ≤64 KiB），不产生无界临时缓冲。

### 测试

- 新增离线测试：`test_reads_preset_hardware`(8)、`test_template_clone_hardening`(7)、`test_host_dangling_mor`(7)、`test_dangling_mor_matrix`(19)、`test_license_entitlements` 扩充、`test_poll_write_coalescing`(2)、`test_guest_observe_cache`(5)、`test_datastore_m3`(6)、`test_diagnostics_m5`(8)、`test_ovf_placement_m6`(16)、`test_cluster_lifecycle` 名称白名单(2)；既有 OVF/cluster/datastore 夹具升级为放置一致的健康拓扑。
- 全部 fail-closed 放宽点均保留"无肯定证据即拒绝"负向用例（许可 0 行/外域/过期、权限缺失、跨 DC、网络/DS 不可达、MONF 命名他对象 re-raise、畸形 ID exit2）。
- 测试命令固定 `env -u PYTHONPATH PYTHONPATH=src:tests <py> -m unittest discover -s tests < /dev/null`；`python -m pyflakes src tests` 归零。

