# 3.0 实施状态

当前为 3.0.0b4 执行引擎 Beta 候选版（execution-beta），非 GA 交付。14 项运维聚焦待做台账已全部完成并通过离线测试，等待用户实机验收后再进入正式版。

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
