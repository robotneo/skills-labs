# vCenter AIops 3.0 产品需求文档（PRD）

| 项目 | 内容 |
| --- | --- |
| 文档版本 | 1.2（完整运维范围，统一 vcenter-aiops 命令） |
| 目标产品版本 | 3.0.0 |
| 编写日期 | 2026-09-09 |
| 状态 | 用户已审批通过，进入实施；不代表已完成兼容验证或已授权真实环境写入 |
| 现有代码基线 | skills-labs / vcenter-ops 2.0.0；仓库提交 27e16df |
| 用户 | 单人 IT 管理员、通过 AI Agent 执行操作的技术支持人员 |

### 已审批范围修订（2026-09-26）

用户选择安全方案 A：坚持凭据连接的严格指纹策略，暂不开放 `cluster add-host`，继续其他模块。vSphere 6.5–8.0 的 HostConnectSpec.sslThumbprint 允许指纹不匹配后使用受信 CA，本地探测不能约束 vCenter 委托连接，因此自动加入不得以“全程固定指纹”名义交付。该叶子保留在原始需求清单，标为用户批准延期；当前实施范围不注册占位入口或 CA 回退开关。`cluster remove-host` 及其他需求不变。后续开放自动加入需要独立设计与批准，不能把延期项计入已完成或宣称原始150叶子全部交付。

## 1. 已确定的约束

产品名为 **vCenter AIops**，唯一公共命令为 `vcenter-aiops`，新 Skill/发行目录为 `vcenter-aiops/`，Python 包为 `vcenter_aiops`。模块入口 `python -m vcenter_aiops` 与启动器进入同一 CLI。MCP 使用 `vcenter-aiops mcp serve`。不注册 vmware-aiops 或旧 vcenter-ops 命令别名。公开包名可用性在发布前验证；本文路径保留用于追踪历次 PRD，旧名称仅表示迁移来源。

1. 参考 VMware-AIops 的模块组织、CLI/MCP 双入口和现代 Python 包结构，独立重构 vcenter-ops。
2. 兼容目标为 vSphere 6.5、6.7、7.0、8.0；不能只支持 7/8，也不能将 SDK 可连接等同于全部操作可用。
3. 所有产品功能均提供独立的原子化 CLI 叶子命令，采用 VMware-AIops 风格的“领域 + 明确动词”组织方式。CLI 为默认接口，MCP 为可选安装能力，两者共用命令契约和执行核心。
4. 不保留 `scripts/handler.py --action ...`，不提供旧命令别名或转发兼容层；允许保留旧数据迁移工具。
5. 先审批 PRD，再编写详细技术设计和实施计划、执行代码重构。
6. 本 PRD 不授权连接生产 vCenter 或执行真实虚拟机写操作。

## 2. 背景、问题与目标

现有项目具备 VM 生命周期、快照、克隆、计划、IP 池和审计等基础，但业务主要集中在 handler.py（747 行）和 executor.py（1121 行）。静态扫描发现 4 个测试文件、13 个测试函数，未覆盖大部分远端变更流程。文档 ACTION-MATRIX 宣称 22 个 action，实际参数列表有 23 个，说明能力文档需要由可验证契约维护。

重构必须解决以下已观察到的问题：

- 连接默认忽略证书验证；对象按名称查找后返回首个匹配项。
- 确认主要在 handler 危险词流程中，计划、TTL 与直接调用缺少统一执行边界。
- 失败计划重试重置已有结果；回滚异常后仍可能标记完全回滚。
- 任务取消无法定位远端任务时仍设置本地 cancelled；等待超时不能证明远端失败。
- IP 预留可覆盖已有记录，JSON 读写缺少事务保护。
- 运行数据放在安装目录，部分模块导入即创建目录。
- Guest 执行固定使用 Linux shell，输出为空；上传下载是未实现占位。
- 删除前快照不能作为销毁 VM 后的独立恢复保障。

目标是让管理员能明确知道：操作哪个环境和对象、实际将改变什么、是否已执行、执行到哪里，以及失败后下一步如何处理。架构优化以可测试、可恢复和行为一致为标准，不以目录数量为标准。

## 3. 范围与非目标

### 3.1 3.0 基础必需范围

- 多 vCenter 配置、显式目标选择、连接自检、版本和能力查询。
- 资产清单与详情、事件、配额预检、分页和导出。
- 模板克隆、现有 VM 克隆、电源操作、重配置、迁移、快照、模板转换、精确 VM 删除。
- Guest 命令执行：Linux/Windows 显式适配、退出码及输出采集、超时状态。
- IP 池、预设、历史、密钥引用、审计与缓存。
- 批量电源操作、计划执行与补偿、任务查询及远端结果核对。
- TTL 设置、取消、到期清单；默认不自动删除。
- CLI、可选 stdio MCP、中文 Skill、跨平台启动器、ZIP/wheel 交付。
- 2.0 数据检查与迁移工具，但不兼容旧命令和旧 JSON 输出格式。

以上功能以第 6 节原子命令目录为交付单位；每个叶子必须独立可用，不以一个大命令覆盖整个流程作为完成依据。

### 3.2 本次新增必需范围

VM 创建、挂起和 Clean Slate；OVA/OVF 部署、链接克隆、ISO 挂载、Guest 上传下载及批量制备；集群创建/删除、HA/DRS、主机加入/移除；告警查询/确认/重置；单次与定时扫描、日志分析、聚合调查报告、Webhook 通知；显式授权的 TTL 到期清理，全部纳入 3.0 完整交付。各模块分阶段实现，但不得继续列为未实施的后续功能而宣称本次重构完成。

独立 ESXi 正式实机支持仍作为后续范围；本次兼容验收针对 vCenter 管理环境。

### 3.3 本轮非目标

主机网络重构、vSAN 管理、Kubernetes、预测分析、多租户审批平台仍不在范围。扫描调度为可选组件，不要求普通 CLI 用户启动后台服务。通知提供 Webhook 和适配接口，不自动集成 DWS/飞书/企业微信专有 API。现有 Wi-Fi 和通知项目不在重构范围。

## 4. vSphere 兼容需求

| 服务端系列 | 首版目标 | 当前验证状态 | 放行条件 |
| --- | --- | --- | --- |
| 6.5 | 本文全部领域的适用命令 | 未验证 | 逐命令验证，缺少版本/许可能力时明确拒绝 |
| 6.7 | 同上 | 未验证 | 同上 |
| 7.0 | 同上 | 未验证 | 同上 |
| 8.0 | 同上 | 未验证 | 同上 |

“支持系列”不自动表示测试过所有 Update/补丁组合。兼容清单必须记录实际 vCenter/ESXi build、客户端 Python、pyVmomi、VMware Tools、虚拟硬件和许可证条件；未测补丁明确标记，不得冒称全量验证。

- 首版主目标是 vCenter 管理的环境；独立 ESXi 不作为首版验收门槛。vCenter 与 ESXi 的搭配仍须遵循厂商互操作要求。
- 能力判断结合服务端 API 版本、对象能力、许可证、权限、VM 硬件和电源状态；不能只判断版本字符串。
- 低版本缺少字段时返回 unavailable 及原因；缺少方法或前提条件时在写入前返回 capability_unsupported。
- 兼容分支集中在 vSphere Provider；业务层不散布版本判断。
- 新旧快照 API 的选择依据官方接口文档和运行能力，在技术设计阶段建立方法矩阵；不得捕获所有异常后改用另一写接口重复提交。
- 首选统一 SDK 版本。先通过 6.5/6.7 连接和核心任务兼容试验选型；若确需不同 SDK，采用隔离依赖配置和相同契约，不能运行中自动降级安装。
- 建议 Python 3.10+；正式发布只声明完成测试的解释器版本。SDK、TLS、Python 和 MCP 依赖组合在实现前的兼容试验中确定并锁定。
- TLS 默认验证证书，支持企业 CA；显式 insecure 配置应在连接结果中可见。不得自动降低 TLS 安全级别以连接旧环境。
- 四个系列没有全部通过核心验收前，不得发布“6.5–8.0 全面验证通过”的稳定版；可发布明确列出缺口的候选版本。

## 5. 核心用户流程

### 5.1 首次接入

安装 Skill → 检查本机运行依赖 → 设置命名连接 Profile 和凭据引用 → 验证 TLS/身份 → 查询版本和能力 → 只读资产查询。多 Profile 时必须显式选择；切换环境不能沿用之前对象身份。

### 5.2 查询与排障

选择 Profile → 按名称、IP 或对象 ID 查询 → 遇到多匹配返回候选列表 → 返回带采集时间和数据来源的结果。缓存必须标明时间；用户可要求刷新。权限不足与对象不存在必须区分。

### 5.3 单次或批量变更

解析并固定对象身份 → 实时预检 → 生成计划及差异 → 用户确认 → 应用计划 → 跟踪远端任务 → 验证后置条件 → 返回结果并写审计。

批量范围在预览时展开为固定对象集合；执行时不重新按通配符扩大范围。单步命令是第一等入口，可独立预检、确认、执行和查询结果，不要求用户先手工创建计划。多步骤才使用显式 Plan/Apply，调用同一套原子处理器。

### 5.4 克隆

完整交付流程由独立命令组合：资源查询 → IP 检查与预留 → 模板部署或 VM 克隆 → Guest 定制 → 开机 → Tools/IP 核对。源对象和目的资源的只读预检属于对应命令内部职责；开机、额外重配置等独立变更不得隐藏在 clone 命令中。保留 `IP-自定义名称` 规则；未获得 IP 时不得编造前缀。

Ping 不通只能作为信号，不能证明 IP 空闲；结合资产、预留和网络探测。探测不可用返回不确定，不能当作空闲自动分配。IP 预留以网络作用域及地址作为唯一键，允许不同隔离网络使用同一地址。

### 5.5 中断与恢复

超时或进程重启 → 读取任务和执行记录 → 查询原 vCenter 任务/后置状态 → 更新结果。远端状态无法确认时进入 reconciliation_required，不自动重复提交变更。

## 6. 原子化 CLI 产品模型

### 6.1 原子命令的定义

原子命令指一个可独立调用、验证和测试的业务动作，不是分布式事务承诺，也不强制等于一次 SOAP 请求。允许内部执行必要的读取、校验、任务等待和结果核对；不得隐式串联多个独立业务变更。

- 使用 `vcenter-aiops <领域> <动词>`，每个叶子具有独立 help、输入模型、结果模型、风险和能力要求。
- 禁止 `--action`、`--state on/off`、`--snap-action` 这类通过参数切换业务的万能入口。动作拆成 `vm power-on`、`vm shutdown`、`vm power-off`、`vm reset` 等。
- `vm delete` 不先强制关机或创建快照；状态不满足时返回前置条件失败，由用户或计划显式组合动作。
- `vm clone` 不自动开机、不隐式申请 IP；`deploy mark-template` 不附带重命名；关闭 Guest 失败不自动升级为强制关机。
- 一份 VM 配置规格内的 CPU/内存/磁盘修改可以作为 `vm reconfigure` 单一动作，输出完整差异；不同 VM 不得合并成一个原子写动作。
- 所有首版产品能力必须在 CLI 中可达；不能只存在于 Python 函数、MCP 或自然语言文档中。

### 6.2 3.0 完整叶子命令目录

每个反引号标注项均为独立叶子命令，不是同一命令的模式参数。下列为本项目范围，不宣称与上游功能数量或命令拼写完全相同。

| 领域 | 独立 CLI 叶子命令 | 职责与边界 |
| --- | --- | --- |
| 运行环境 | `version`、`doctor`、`capabilities list`、`capabilities show` | 本地自检、版本与远端能力；doctor 默认不连接，显式 --connect 才探测 |
| 连接配置 | `profile list`、`profile show`、`profile add`、`profile update`、`profile delete`、`profile test` | 只改配置或测试连接，不修改 vSphere 资源；show 不显示凭据 |
| 资产 | `inventory list`、`inventory export` | 跨类型资源查询和导出，支持分页和过滤 |
| VM 查询 | `vm list`、`vm inspect` | 返回唯一身份、状态和配置 |
| 电源 | `vm power-on`、`vm shutdown`、`vm power-off`、`vm reset`、`vm suspend` | 开机、优雅关机、强制关机、硬重置和挂起；不自动降级为更强操作 |
| VM 变更 | `vm create`、`vm clone`、`vm rename`、`vm reconfigure`、`vm migrate`、`vm delete` | 创建空 VM 与克隆分开；单源/单目标业务操作，均独立预检 |
| 快照 | `vm snapshot-list`、`vm snapshot-create`、`vm snapshot-revert`、`vm snapshot-delete` | 单 VM/精确快照对象，不通过 snap-action 分派 |
| 模板 | `template list`、`template inspect`、`deploy mark-template`、`template convert` | 模板与 VM 转换只做转换，不顺带重命名或开机 |
| 部署 | `deploy ova`、`deploy ovf`、`deploy template`、`deploy linked-clone`、`deploy iso`、`deploy unmount-iso` | 部署、链接克隆与介质挂载各自独立，不隐藏额外开机 |
| Guest | `vm guest-exec`、`vm guest-exec-output`、`vm guest-upload`、`vm guest-download`、`vm guest-process-status`、`vm guest-output`、`vm tools-status`、`vm wait-tools`、`vm guest-customize` | 对齐参考项目 vm guest-* 风格；exec-output 执行并采集，guest-output 仅读已有输出；均检查 OS/Tools 能力 |
| 集群 | `cluster list`、`cluster info`、`cluster create`、`cluster delete`、`cluster add-host`、`cluster remove-host`、`cluster configure` | vCenter 专有；HA/DRS 配置，不隐式清空或撤离资源 |
| 主机前置操作 | `host info`、`host maintenance-enter`、`host maintenance-exit` | 显式进入/退出维护，不将 VM 撤离隐藏在集群移除操作中 |
| 告警 | `alarm list`、`alarm acknowledge`、`alarm reset` | 确认与重置分离，实际重置范围必须展示 |
| 存储 | `datastore list`、`datastore inspect`、`datastore browse`、`datastore scan` | 只读，scan 表示发现镜像，不执行部署 |
| 事件和配额 | `events list`、`quota check` | 时间窗口查询和资源约束检查 |
| IP | `ip check`、`ip available`、`ip reserve`、`ip release`、`ip list`、`ip expire` | 检测不等于预留；expire 仅处理过期本地租约，结果未知的部署关联租约不得自动释放 |
| 预设 | `preset list`、`preset show`、`preset save`、`preset delete`、`preset from-history`、`preset from-vm` | 显式复用参数；创建预设不执行部署 |
| 缓存 | `cache status`、`cache refresh`、`cache invalidate` | 可观察并显式管理缓存；刷新只读访问远端 |
| 历史 | `history list`、`history show` | 查询既往记录，不自动重复执行 |
| 审计 | `audit list`、`audit export` | 查询与导出脱敏证据 |
| 密钥 | `secret list`、`secret set`、`secret delete`、`secret rotate` | 安全输入；无明文 get 命令 |
| 策略 | `policy inspect`、`policy check` | 查询风险与限制，不生成可绕过确认的通用标志 |
| TTL | `vm set-ttl`、`vm cancel-ttl`、`vm list-ttl`、`vm expired-ttl`、`vm cleanup-ttl` | 默认提醒；清理走明确授权的精确对象计划，不扩大范围 |
| 任务 | `task list`、`task inspect`、`task wait`、`task cancel`、`task reconcile` | cancel 请求远端取消，不等同确认已取消 |
| 数据迁移 | `migration inspect`、`migration apply`、`migration verify` | 检查、迁移、验证分离；操作本地数据，不写 vSphere |
| 扫描 | `scan run`、`scan status`、`scan history`、`scan report` | 多 Profile 只读采集及结果查询，不自动修复 |
| 调查 | `attention`、`summary`、`investigate vm`、`investigate host`、`investigate datastore` | 基于采集证据聚合，支持离线 HTML |
| 调度 | `schedule create`、`schedule list`、`schedule show`、`schedule update`、`schedule enable`、`schedule disable`、`schedule delete`、`scheduler run`、`scheduler status` | 持久化作业与可选调度进程；操作系统服务部署单独说明 |
| 通知 | `notify channel-add`、`notify channel-list`、`notify channel-update`、`notify channel-delete`、`notify enable`、`notify disable`、`notify test`、`notify send`、`notify history`、`notify retry` | 默认关闭；测试也属于外发，仅向配置目的地发送授权内容 |
| MCP | `mcp serve` | 可选 stdio 服务，仍使用统一主命令 |

### 6.3 编排命令：组合原子动作

Plan/Apply 是上层编排能力，不把多步骤伪装为单个原子 VM 操作。编排自身也提供职责明确的叶子入口：`plan create`、`plan show`、`plan list`、`plan validate`、`plan apply`、`plan reconcile`、`plan rollback`、`plan archive`。

`batch power-on`、`batch shutdown`、`batch power-off`、`batch reset` 是批量计划构建入口，仅生成固定目标集合的计划，不直接进行循环写入；实际执行统一通过 plan apply。不提供批量删除入口。

plan create 接受声明式步骤文件；每步引用已注册原子操作 ID（如 vm.power_on）及强类型参数。plan validate 只预检；plan apply 执行已确认的计划。计划不可嵌套任意 Shell 或未注册 Python 方法，不另建一套底层调用路径。

典型部署计划由 `ip reserve → deploy template → vm guest-customize → vm power-on → vm wait-tools → vm inspect` 组成，各步骤可单独运行。Guest 定制可能依赖后续重启应用，其提交成功与来宾实际配置完成必须分别报告。前一步输出通过类型化引用传给后一步，不拼接 Shell 字符串。

### 6.4 每条叶子的统一契约

`deploy batch-clone`、`deploy batch`、`vm guest-provision`、`vm clean-slate` 为明确的组合命令，默认生成计划，由 `plan apply` 执行。clean-slate 必须指定唯一 VM 和已存在的基线快照，不隐式变成删除重建。`vm cleanup-ttl` 只消费提前登记的精确对象授权，详见第 6.7 节。

命令注册表是帮助、CLI schema、MCP、操作矩阵和测试覆盖清单的共同来源。每项包含：operation_id、命令路径、类别（查询/本地变更/远端变更/编排）、参数与单位、结果 schema、所需权限和版本能力、前后置条件、风险、幂等语义、超时行为、补偿能力及是否支持异步任务。

统一公共参数为 `--profile`、`--format json|table`、`--timeout`；远端写叶子提供 `--dry-run` 和 `--request-id`，任务型操作提供 `--wait/--no-wait`。不支持的参数不得静默忽略。只读查询不产生确认流程；本地配置命令也不要求可用 vCenter 连接。

同 request-id、同目标和同参数重复提交返回已有操作；参数变化返回冲突。这个契约不承诺跨 vCenter 的 exactly-once。查询现有任务不再执行原始命令。

单步 CLI 可交互显示预览并完成确认后执行；非交互缺少适用授权时返回 awaiting_confirmation 和固定的单步计划引用，通过 plan apply 完成。--dry-run 不提交远端变更，也不视为已确认。单步用户无需预先手写计划文件。

示例：

```text
vcenter-aiops --profile lab --format json vm list --limit 100
vcenter-aiops --profile lab capabilities list
vcenter-aiops --profile lab vm power-on --vm-id vm-123 --dry-run
vcenter-aiops --profile lab vm shutdown --vm-id vm-123
vcenter-aiops --profile lab vm snapshot-list --vm-id vm-123
vcenter-aiops --profile lab vm reconfigure --vm-id vm-123 --cpu 4 --memory-gb 8 --dry-run
vcenter-aiops --profile lab plan create --file deployment.yaml
vcenter-aiops --profile lab plan apply <plan-id>
vcenter-aiops --profile lab task inspect <operation-id>
vcenter-aiops migration inspect --source <旧版目录>
```

### 6.5 MCP 对齐

MCP 通过可选 `vcenter-aiops mcp serve` stdio 入口启动。每个开放的业务叶子映射独立工具，如 `vm power-on → vm_power_on`、`vm snapshot-create → vm_snapshot_create`；禁止万能 execute(action, params) 工具。CLI 必须覆盖全部能力，MCP 可按会话仅加载相关领域，避免一次暴露所有工具。

MCP 与 CLI 直接调用相同应用处理器，不通过 Shell 包装 CLI。凭据管理、安装、数据迁移等本机管理命令默认不暴露到 MCP；未开放项在能力表中明确列出，不影响业务叶子对应原则。stdio stdout 仅用于协议，日志写 stderr。确认和结果契约与 CLI 一致，MCP 调用不能自行代表用户授权。

### 6.6 参考项目功能对照与本项目差异

已读取用户指定的 [VMware-AIops 中文 README](https://github.com/vmware-skills/VMware-AIops/blob/main/README-CN.md) 中生命周期、Plan/Apply、部署、集群、告警、存储、扫描及安全章节。其为社区项目，本文借鉴命令风格与功能组织，不宣称 VMware 官方产品或上游逐命令兼容。README 中部分扫描与监控功能已委托配套项目；实现阶段须核对实际源码/注册表，不能凭 README 假定所有命令仍在同一包。

| 参考领域 | 本项目命令示例（统一前缀） | 实施决策 |
| --- | --- | --- |
| 生命周期 | `vcenter-aiops vm create`、`vm suspend`、`vm delete` | 覆盖创建到销毁；删除不隐式关机 |
| 关机 | `vcenter-aiops vm shutdown`、`vm power-off` | 上游 power-off 默认优雅、--force 强制；本项目采用两个独立动词，不支持 --force 混合语义 |
| 快照与基线 | `vcenter-aiops vm snapshot-create`、`vm clean-slate` | 快照为原子操作，基线恢复为显式组合计划 |
| 多步计划 | `vcenter-aiops plan create`、`plan apply`、`plan rollback` | 已完成计划保留审计并归档，不立即删除证据 |
| 部署制备 | `vcenter-aiops deploy ova`、`deploy template`、`deploy linked-clone`、`deploy batch` | 全部纳入，批量展开成单 VM 步骤 |
| Guest | `vcenter-aiops vm guest-exec-output`、`vm guest-upload`、`vm guest-download` | 对齐 vm guest-*；客户机账户是独立授权边界 |
| 集群 | `vcenter-aiops cluster create`、`cluster configure`、`cluster remove-host` | 能力/许可证/维护前置条件校验 |
| 告警 | `vcenter-aiops alarm list`、`alarm acknowledge`、`alarm reset` | 不把确认等同故障修复；重置展示真实范围 |
| 数据存储 | `vcenter-aiops datastore browse`、`datastore scan` | 只读浏览和镜像发现，与 deploy 分开 |
| 扫描与通知 | `vcenter-aiops scan run`、`schedule create`、`notify send` | 本项目定义稳定 CLI；上游章节没有给出的具体命令不冒充逐字兼容 |
| 安全机制 | 各写叶子的 `--dry-run`、`policy check`、`audit export` | CLI/MCP 共用规则，真实权限由服务端账户限制 |

### 6.7 新增领域的行为要求

**VM 生命周期与 TTL。** vm create 校验 CPU、内存、磁盘、Guest 类型、网络和硬件版本，不硬编码仅适用于最新 vSphere 的上限。vm suspend 返回远端任务与实际状态。set-ttl 默认仅提醒；启用删除模式必须保存 vCenter/VM 唯一身份、到期时间、授权范围及电源处理策略，不能继承普通 10 分钟确认作为未来授权。执行前重验对象与前提，授权撤销、身份变化或结果未知时停止。旧 TTL 仍只迁移为提醒。cleanup-ttl 不接受任意全量或通配符删除授权。

**OVA/OVF 与链接克隆。** 校验描述文件、引用磁盘、网络映射、目标容量及硬件兼容性；本地 OVA 解包拒绝路径穿越。传输处理 NFC lease 保活、进度、超时和取消；中断后核对已创建对象，清理仅针对本次产生并有授权的资源。链接克隆记录父 VM/快照依赖，不允许把删除父对象当作安全清理。ISO 挂载验证数据存储路径和光驱条件，不附带启动。

**2026-09-29 用户批准的依赖保护边界。** 采用严格保护：无法排除相关链接磁盘依赖时，拒绝 VM 删除、快照清理及存储迁移。不能因为本地状态库未记录依赖就宣称安全，也不以仅保护本工具创建的子对象代替外部依赖检查；能力不足必须明确拒绝，不隐式绕过。

**Guest 与制备。** 明确 program/arguments 和 OS，不任意改写用户脚本。上传/下载校验本地及 Guest 路径、覆盖策略、容量和传输端点；每个步骤返回真实输出/退出码，临时输出文件清理有记录。日志不保存 Guest 密码，不能将收到的命令输出当作新指令。guest-provision 的上传、执行、验证步骤均在计划中展开。

**2026-09-29 用户批准的 Guest 方案 A 补充。** 允许显式执行包装器，完整包装动作、实际启动参数、独立运行标识、结果/输出文件及保留策略必须进入预览和确认；不隐藏改写用户程序。可靠完成判定使用绑定本次运行的结果证据，不仅依赖可复用的 PID 或短期 Tools 退出记录。结果缺失、损坏或身份不符不冒充成功，启动响应未知不得自动重发；取消与清理不能猜测目标或隐式执行。输出捕获仍属完整验收要求，未实现阶段不得伪造输出。此方案批准不包含真实 Guest 执行授权。

**集群。** create/configure 展示 HA/DRS 差异并检查许可证。delete 只允许精确的空集群，不能级联销毁 VM 或自动移除主机。remove-host 要求维护模式及资源检查，说明移出集群与注销主机不同；不隐式删除存储或 VM。add-host 校验证书和目标身份，主机凭据使用引用。maintenance-enter 的撤离/迁移影响需显式预览；不能保证无容量时可成功维护。

**告警。** acknowledge 只改变确认状态，不代表故障恢复。reset 在技术设计阶段核对各版本 API 及实际过滤范围；若底层接口影响多个匹配对象，必须在预览与结果返回 scope 和数量。不能在匹配目标不存在时执行宽范围重置；没有等价能力的版本返回不支持，不静默替换成扩大范围的调用。

**定时扫描。** scan run 为只读；采集资产、容量、告警、事件及允许获取的日志，日志正则命中仅作为线索。单 Profile 失败不终止其他 Profile，返回 partial 和逐目标状态。schedule 默认建议 15 分钟、显式时区，支持启停和更新。调度进程使用持久化作业、单实例锁、重叠抑制；重启后合并错过的扫描，不突发补跑全部任务。无进程运行时显示未运行，不声称已持续监控。macOS/Linux/Windows 提供各自服务运行指南；安装 Skill 不自动安装或启用服务。

**通知。** 与扫描分别启用，默认无外发。Webhook URL/认证材料使用受保护引用；发送前明确目的地及内容策略。支持通用 JSON、Slack/Discord 消息格式适配；不以“任意 HTTP”承诺所有企业平台协议兼容。默认只发脱敏摘要，完整资产/日志需显式授权；测试命令发送明确的测试消息。持久化通知 outbox，限次退避重试、去重、冷却、恢复通知和投递状态查询；平台无幂等能力时明确存在重复风险。调度重启不得重复创建同一扫描事件；结果不明的发送不伪报成功。扫描本身不修复、不关机、不删 VM。

**安全共性。** 输入和输出 schema、字段单位、路径、证书、最小权限、危险变更预览、拒绝记录、审计及敏感数据过滤纳入全部新增命令。事件、HTML、日志和 Guest 输出转义/截断并标记为不可信数据。MCP 不复制上游缺少确认的写路径；本地控制仍不宣称能抵抗拥有全部本机凭据的 Agent。

## 7. 统一执行、授权与恢复

### 7.1 目标和计划

每个计划包含 schema_version、Profile 身份、服务端 instance UUID、对象 ID、参数、前置条件、风险、补偿策略和内容摘要。MoRef 必须限定在对应服务端范围；名称/IP 用于检索，不能作为最终执行身份。

确认后若目标、参数、范围或关键前置条件变化，计划失效并重新展示。确认记录与计划绑定、一次性消费、有限有效期；默认建议 10 分钟。不得用全局 confirmed 布尔值或危险词豁免替代精确计划。

普通变更一次明确确认；VM/集群销毁、主机移除、快照恢复/删除、Clean Slate 和告警重置采用两次明确确认，并展示精确对象或实际影响范围。CLI 与 MCP 展示同一计划及风险信息。未来 TTL 自动清理使用单独持久化、可撤销的对象级授权；不是每轮由 Agent 自动回答确认。不引入组织级审批系统。

本地确认记录是防误操作机制，不是对有 Shell 权限 Agent 的安全隔离。实际权限边界是最小权限 vCenter 账户；只读场景必须支持使用只读账户。

### 7.2 状态机

计划：draft → ready → awaiting_confirmation → executing → succeeded / failed / partial / reconciliation_required。

补偿：compensating → compensated / compensation_partial / compensation_failed。

远端任务另外记录 queued、running、succeeded、failed、cancel_requested、cancelled、unknown；只有远端确认取消后才记 cancelled。客户端等待超时不自动等于任务失败。

- 提交前写入操作意图，提交后保存远端任务 ID，后置验证完成才报告成功。
- 如果提交后、本地保存任务 ID 前崩溃，必须通过对象和关联证据核对；证据不足时要求人工核对，不能盲目补发。
- 网络重试默认只覆盖确定可重试的读取；写请求结果不明时先核对。
- 计划失败保留已完成步骤和执行前状态；恢复不从零执行。
- 回滚只运行可执行的补偿步骤，逐步保存结果；不可逆/无法恢复的步骤明确展示。
- VM 快照不是销毁后的备份；磁盘扩容等不可逆变化不得标成可完全回滚。
- 同一对象变更串行化；批量默认并发不超过 5，可配置，并在失败时停止提交新步骤、核对已提交步骤。

## 8. 架构边界

```text
vcenter-aiops/
  SKILL.md
  manifest.json
  pyproject.toml
  run.sh / run.ps1 / run.bat
  config.example.yaml
  src/vcenter_aiops/
    cli/                   参数、交互和格式化
    mcp/                   可选协议接口
    application/
      commands/            每个原子操作的独立处理器
      registry/            命令描述、schema、能力与风险注册
      workflows/           计划及批量编排，复用 commands
    domain/                目标、操作、结果和能力模型
    services/              inventory、VM、snapshot、guest 等
    providers/vsphere/     pyVmomi 与版本能力适配
    infrastructure/        配置、状态库、审计、密钥、缓存
  migrations/
  presets/
  references/
  tests/unit/ integration/ contracts/
```

接口层只能调用应用层。每个叶子有独立处理器和输入输出模型，共享连接、授权、任务、审计及存储组件；不得将旧 handler 的巨大条件分支搬入新目录。领域 CLI 模块负责注册叶子，不强制一条命令对应一个文件。pyVmomi 对象不穿透 Provider 边界，领域结果必须可序列化。Provider 使用明确的方法契约，测试替身可替换真实连接。无强制微服务或消息队列；scheduler 是显式启动的可选长期进程。新增 deploy、guest、cluster、alarm、scan、notify 服务，schedule 状态和通知 outbox 存入独立数据库表，避免扫描日志挤占任务记录。

核心依赖与 MCP 可选依赖分离；构建发布时记录准确版本和许可证。若复用上游代码，先确认具体文件的许可、来源和兼容性，保留必要归属。参考架构不等于建立对整个上游的强依赖。

## 9. 配置、数据与迁移

使用系统用户数据目录，支持 `VCENTER_AIOPS_HOME` 覆盖。默认路径：macOS 为 `~/Library/Application Support/vcenter-aiops`，Windows 为 `%LOCALAPPDATA%/vcenter-aiops`，Linux 为 `${XDG_DATA_HOME:-~/.local/share}/vcenter-aiops`。配置及凭据引用可显式指定；运行文件不得写入只读 Skill 安装目录。

SQLite 保存计划、任务、IP 租约和审计索引，使用事务、唯一约束和数据库 schema 迁移；限制为本机文件系统，网络共享和多机器协调不在首版范围。数据库备份必须考虑事务日志，不能直接复制使用中的单个数据库文件。

凭据使用受保护输入或已有 secret 引用，不通过明文 CLI 参数传递，不写入报告、计划或命令历史。加密存储和主密钥分开管理；缺少主密钥时不能声称迁移成功。审计存储不可用时，在提交远端变更前阻止执行；提交后审计落盘失败应返回审计异常及可核对任务标识，不能重试远端写入。

| 旧数据 | 迁移策略 |
| --- | --- |
| config.yaml / 预设 | 严格校验并映射新结构；未知字段列入迁移报告 |
| .env / 加密密钥 | 显式迁移授权；不打印值，不将主密钥和密文打包发布 |
| IP 预留 | 转换作用域；作用域无法确定时保留待处理，不自动释放或覆盖 |
| 历史 / 审计 | 导入历史记录并注明来源，不冒充 3.0 执行证据 |
| 未完成计划 / 任务 | 只导入为待核对记录，不自动继续或回滚 |
| TTL | 导入为到期提醒，不自动恢复删除行为 |
| 缓存 / 危险词确认 | 缓存重建；旧确认不迁移为新授权 |

迁移先 dry-run，再备份、转换、验证和切换；重复迁移不得产生重复记录。失败不破坏源数据，新版写入后的数据不能承诺无损降级回 2.0。保留源备份直到用户决定清理。

3.0 发布包不包含旧 handler、旧参数别名或旧执行逻辑。历史文档可说明命令变化，但所有当前操作示例只能使用新入口。

## 10. 输出和非功能要求

- 新响应统一包含 schema_version、operation_id、status、target、data、warnings、error、next_action。错误包含稳定 code 与 retryable，不泄露凭据。
- JSON 模式 stdout 只输出一个有效 JSON 结果；日志/进度写 stderr。MCP 复用同一结果语义。
- 长期运行的 scheduler 不遵循单次命令单 JSON 结束语义：运行日志写 stderr/JSONL 文件，状态通过 scheduler status 查询；不得混入 MCP 协议 stdout。
- 建议退出码：0 成功，2 参数错误，3 配置/连接/认证失败，4 需确认或能力不足，5 执行失败/部分完成，6 结果待核对。
- 默认中文展示；机器字段和错误码稳定，不翻译。HTML/CSV 导出转义不可信内容，事件和 Guest 输出只作为数据，不作为 Agent 指令。
- 查询默认每页 100 条，最大 1000；大环境优先批量属性读取，避免逐对象重复 API 请求。所有外部请求具有超时，任务轮询退避且有上限。
- `--help`、本地版本查询和无需连接的 doctor 不访问 vCenter；普通查询和变更预览不会意外触发写入。
- 依赖未安装时给出可执行提示；不在模块导入或日常查询时自动联网安装。
- 发布 ZIP 包含单一中文 SKILL.md、运行代码、必要文档和元数据，排除 tests、缓存、真实配置、密钥、运行记录；wheel/离线依赖包按平台分别验证。

## 11. 验收标准

| 编号 | 场景 | 必须满足 |
| --- | --- | --- |
| AC-01 | 全新安装 | macOS、Windows、Linux 的指定 Python 基线可运行 help/doctor；基础 CLI 不要求 MCP |
| AC-02 | 旧入口移除 | 发布包无 handler.py 旧入口，新 CLI 拒绝 --action，当前文档无旧命令示例 |
| AC-03 | 四个 vSphere 系列 | 每个系列实测连接、清单、核心 VM/快照/克隆操作及任务查询；保留准确 build 和能力记录 |
| AC-04 | 缺少权限/功能 | 预检返回明确原因，不调用不支持的写 API；缺失查询字段标不可用 |
| AC-05 | TLS | 默认拒绝不可信证书；配置企业 CA 后成功；不自动降级 |
| AC-06 | 重名/跨环境 | 返回消歧信息；不能操作第一个同名 VM 或沿用其他 vCenter 对象 |
| AC-07 | 确认与批量 | CLI/MCP 共用规则，计划变化使旧确认失效；禁止通配符删除 |
| AC-08 | 进程崩溃/超时 | 不重复提交结果不明的写请求；可依据原任务恢复查询 |
| AC-09 | 计划/回滚失败 | 已完成步骤不重跑；补偿失败显示部分/失败，保留每步证据 |
| AC-10 | IP 并发 | 同作用域同 IP 的并发申请只允许一个有效租约，不覆盖他人预留 |
| AC-11 | Guest | Linux/Windows 支持矩阵内命令可返回真实退出码和输出；超时不伪造成功 |
| AC-12 | 数据迁移 | 可预演、可重复，源数据不破坏；历史 TTL/确认不触发新写操作 |
| AC-13 | CLI/MCP 契约 | 成功、失败、需确认和待核对状态一致，协议输出不混入日志 |
| AC-14 | 打包 | 独立安装可运行，版本一致，无缓存、测试或真实环境数据 |
| AC-15 | 不可逆语义 | 不以删除前快照承诺销毁恢复；扩容等不可逆项在计划中可见 |
| AC-16 | 原子 CLI 完整性 | 第 6 节每个叶子有独立 help/schema/处理器/结果测试；无 --action、--state、--snap-action 分派入口 |
| AC-17 | 无隐藏变更 | clone 不自动开机，delete 不自动关机或创建快照，shutdown 不自动回退强制关机，deploy mark-template 不重命名 |
| AC-18 | 独立调用 | 单步写叶子无需用户手工建 plan 即可交互执行；无交互授权返回固定待确认对象且未提交写入 |
| AC-19 | 编排复用 | batch 只生成固定计划；plan 引用注册原子处理器，不绕开相同预检、权限、任务和审计 |
| AC-20 | MCP 原子映射 | 业务工具逐叶子映射，无 execute(action, params)；CLI 独有管理命令列出原因 |
| AC-21 | 命令与能力矩阵 | 每个远端叶子均关联 6.5/6.7/7.0/8.0 验证条目；按能力拒绝不支持项，不伪造成功 |
| AC-22 | 统一前缀 | 安装后所有功能使用 vcenter-aiops；mcp serve 也在同一入口，无旧 handler 或旧命令别名 |
| AC-23 | 部署与制备 | OVA/OVF、模板、链接克隆、ISO、Guest 上传下载及批量计划有成功/失败测试，NFC 中断不遗失操作状态 |
| AC-24 | 集群 | 六类上游对应操作覆盖；非空集群删除拒绝；移除主机前验证维护和影响范围；许可不足无写入 |
| AC-25 | 告警 | list/acknowledge/reset 均独立；重置范围与实际 API 一致，错误对象不会扩大清除范围 |
| AC-26 | 扫描调度 | 多目标部分失败、作业重启、并发重叠和错过触发均测试；scan 不调用变更 API |
| AC-27 | 通知 | 默认无外发；启用后仅配置端点收到授权 payload，去重、限次重试、失败历史可验证 |
| AC-28 | TTL/Clean Slate | 未授权到期不删除，取消后不清理；精确授权和基线失效时停止，所有组合步骤可审阅 |
| AC-29 | 完整范围 | 第 3.2 节新增领域全部有交付记录；不得以 TODO、占位 NotImplemented 或仅模拟通过宣布完整版本完成 |

测试分为无网络单元测试、模拟 Provider 契约测试、隔离安装测试和显式授权的实验 vCenter 测试。模拟通过不能代替实机验证。核心应用/状态/策略模块分支覆盖率目标至少 85%，同时必须覆盖上表故障场景，不能仅用覆盖率替代行为验收。

当前尚未具备四个版本实验环境的已验证证据。这是稳定版兼容声明的验收依赖，不阻止先实现架构和离线测试。

## 12. 交付阶段

1. PRD 审批：冻结原子叶子目录、编排边界、取消旧入口和四系列兼容目标。
2. 技术设计与兼容试验：逐叶子确定参数/结果/权限/版本能力/幂等契约；确定 SDK/Python 组合及 API 差异，发现无法满足 6.5 的条件时反馈，不静默缩小范围。
3. 核心与只读迁移：命令注册表、新包、配置、Provider、数据目录、结果协议、独立查询叶子及测试。
4. 写操作与可靠性：逐项实现独立写叶子，完成后再由它们组合计划/批量，覆盖任务恢复、补偿和事务 IP 池。
5. 扩展领域：OVA/OVF/链接克隆/ISO、Guest 传输与制备、集群和告警，逐命令完成能力与失败场景验证。
6. 扫描与通知：单次扫描、调查报告、持久化调度、Webhook、TTL 对象授权；测试默认关闭和恢复行为。
7. MCP 与数据迁移：叶子工具映射、迁移工具、命令文档、中文 Skill、新命名发布目录，移除旧实现。
8. 验收与发布：四系列逐领域矩阵、故障测试、ZIP/wheel、变更说明、已知限制；完整范围未交付时只发布候选里程碑。

每阶段以可运行交付和验收结果推进，不以目录移动量作为完成标准。代码重构完成不等同于四系列实机验收完成。

## 13. 审批与待确定事项

用户已批准的具体范围：vCenter AIops 3.0 命名及唯一 vcenter-aiops 入口、第 6 节完整原子与编排命令目录、生命周期/部署/集群/告警/存储/定时扫描/通知/安全全部领域、无旧入口、CLI 默认/MCP 可选、四系列兼容门槛和状态数据迁移。本次 1.2 取代 1.1 的有限首版范围，分八阶段交付。

实施阶段需要补齐但不阻止 PRD 审批的信息：各系列可用实验环境/build、企业 CA、测试服务账户权限、克隆模板/网络/存储及可销毁测试资源。真实写入另按用户明确授权的环境与对象执行。

PRD 已获批，允许代码重构与离线验证。不得据此迁移本机真实凭据或提交真实 vCenter 写任务；这些操作按具体环境和范围另行授权。

## 14. 参考依据

- [VMware-AIops 中文说明](https://github.com/vmware-skills/VMware-AIops/blob/main/README-CN.md)：参考 CLI/MCP、领域拆分和操作编排思路；其兼容声明不替代本项目测试。
- [VMware-AIops 构建配置](https://github.com/vmware-skills/VMware-AIops/blob/main/pyproject.toml)：参考现代构建、命令入口和依赖组织，不直接继承其全部依赖。
- [pyVmomi 项目](https://github.com/vmware/pyvmomi)：SDK 选型与兼容资料入口，实施时核对具体版本和官方 API 文档。
- 本仓库 vcenter-ops/SKILL.md、scripts/cli/arguments.py、client.py、executor.py、plan_manager.py、task_manager.py、ip_pool.py、ttl_manager.py：现状及迁移范围依据。

以上外部资料于 2026-09-09 查阅，main 分支可能变化；进入实现阶段应固定参考提交和依赖版本。
