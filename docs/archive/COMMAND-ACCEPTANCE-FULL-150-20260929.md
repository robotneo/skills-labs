# vCenter AIops 逐命令验收台账

依据：已批准 PRD 1.2 第 6.2–6.4 节。此表独立于代码注册表保存必需清单，避免“只检查已实现命令”漏掉缺失功能。

注册核对日期：2026-09-29。原始 PRD 共150个必需叶子；其中自动 add-host 经用户选择安全方案A批准延期，当前实施范围149个，注册93个。注册不代表功能验收完成，所有条目的完整需求验收仍待逐项补充测试证据。额外的 datastore 搜索恢复入口不抵扣必需命令；不得把延期项计入完成。

状态分离：注册状态只表示入口存在；离线验收需独立 help/schema、处理器成功/拒绝/恢复证据；实机验收需准确 build、权限和环境记录。候选版不是稳定版。

| 领域 | 必需命令（前缀 vcenter-aiops） | 注册基线 | 完整离线验收 | 6.5 / 6.7 / 7.0 / 8.0 |
| --- | --- | --- | --- | --- |
| 运行环境 | `version` | 已注册 | 待逐项验收 | 均未实测 |
| 运行环境 | `doctor` | 已注册 | 待逐项验收 | 均未实测 |
| 运行环境 | `capabilities list` | 已注册 | 待逐项验收 | 均未实测 |
| 运行环境 | `capabilities show` | 已注册 | 待逐项验收 | 均未实测 |
| 连接配置 | `profile list` | 已注册 | 待逐项验收 | 均未实测 |
| 连接配置 | `profile show` | 已注册 | 待逐项验收 | 均未实测 |
| 连接配置 | `profile add` | 已注册 | 待逐项验收 | 均未实测 |
| 连接配置 | `profile update` | 已注册 | 待逐项验收 | 均未实测 |
| 连接配置 | `profile delete` | 已注册 | 待逐项验收 | 均未实测 |
| 连接配置 | `profile test` | 已注册 | 待逐项验收 | 均未实测 |
| 资产 | `inventory list` | 已注册 | 待逐项验收 | 均未实测 |
| 资产 | `inventory export` | 未注册 | 待逐项验收 | 均未实测 |
| VM 查询 | `vm list` | 已注册 | 待逐项验收 | 均未实测 |
| VM 查询 | `vm inspect` | 已注册 | 待逐项验收 | 均未实测 |
| 电源 | `vm power-on` | 已注册 | 待逐项验收 | 均未实测 |
| 电源 | `vm shutdown` | 已注册 | 待逐项验收 | 均未实测 |
| 电源 | `vm power-off` | 已注册 | 待逐项验收 | 均未实测 |
| 电源 | `vm reset` | 已注册 | 待逐项验收 | 均未实测 |
| 电源 | `vm suspend` | 已注册 | 待逐项验收 | 均未实测 |
| VM 变更 | `vm create` | 已注册 | 模块测试及审查通过；发布验收待完成 | 均未实测 |
| VM 变更 | `vm clone` | 已注册 | 待逐项验收 | 均未实测 |
| VM 变更 | `vm rename` | 已注册 | 待逐项验收 | 均未实测 |
| VM 变更 | `vm reconfigure` | 已注册 | CPU/内存及受限磁盘配置模块测试/审查通过；发布验收待完成 | 均未实测 |
| VM 变更 | `vm migrate` | 已注册 | 待逐项验收 | 均未实测 |
| VM 变更 | `vm delete` | 已注册 | 待逐项验收 | 均未实测 |
| 快照 | `vm snapshot-list` | 已注册 | 待逐项验收 | 均未实测 |
| 快照 | `vm snapshot-create` | 已注册 | 待逐项验收 | 均未实测 |
| 快照 | `vm snapshot-revert` | 已注册 | 待逐项验收 | 均未实测 |
| 快照 | `vm snapshot-delete` | 已注册 | 待逐项验收 | 均未实测 |
| 模板 | `template list` | 已注册 | 模块测试及审查通过；发布验收待完成 | 均未实测 |
| 模板 | `template inspect` | 已注册 | 模块测试及审查通过；发布验收待完成 | 均未实测 |
| 模板 | `deploy mark-template` | 已注册 | 待逐项验收 | 均未实测 |
| 模板 | `template convert` | 已注册 | 模块测试及审查通过；发布验收待完成 | 均未实测 |
| 部署 | `deploy ova` | 未注册 | 待逐项验收 | 均未实测 |
| 部署 | `deploy ovf` | 未注册 | 待逐项验收 | 均未实测 |
| 部署 | `deploy template` | 已注册 | 待逐项验收 | 均未实测 |
| 部署 | `deploy linked-clone` | 未注册 | 待逐项验收 | 均未实测 |
| 部署 | `deploy iso` | 已注册 | 模块测试及审查修复复核通过；发布验收待完成 | 均未实测 |
| 部署 | `deploy unmount-iso` | 已注册 | 模块测试及审查修复复核通过；发布验收待完成 | 均未实测 |
| Guest | `vm guest-exec` | 已注册 | 显式包装协议离线测试/独立审查通过；本阶段输出为DEVNULL | 均未实测 |
| Guest | `vm guest-exec-output` | 未注册 | 待逐项验收 | 均未实测 |
| Guest | `vm guest-upload` | 未注册 | 待逐项验收 | 均未实测 |
| Guest | `vm guest-download` | 未注册 | 待逐项验收 | 均未实测 |
| Guest | `vm guest-process-status` | 已注册 | 精确运行标记核对、丢回执恢复与并发锁测试/审查通过 | 均未实测 |
| Guest | `vm guest-output` | 未注册 | 待逐项验收 | 均未实测 |
| Guest | `vm tools-status` | 已注册 | 待逐项验收 | 均未实测 |
| Guest | `vm wait-tools` | 已注册 | 待逐项验收 | 均未实测 |
| Guest | `vm guest-customize` | 未注册 | 待逐项验收 | 均未实测 |
| 集群 | `cluster list` | 已注册 | 待逐项验收 | 均未实测 |
| 集群 | `cluster info` | 已注册 | 待逐项验收 | 均未实测 |
| 集群 | `cluster create` | 已注册 | 模块测试及审查通过；发布验收待完成 | 均未实测 |
| 集群 | `cluster delete` | 已注册 | 模块测试及审查通过；发布验收待完成 | 均未实测 |
| 集群 | `cluster add-host` | 不开放（用户批准延期） | 严格指纹安全策略；不计入完成 | 均未实测 |
| 集群 | `cluster remove-host` | 已注册 | 模块测试及方案A复核通过；发布验收待完成 | 均未实测 |
| 集群 | `cluster configure` | 已注册 | 模块测试及审查通过；发布验收待完成 | 均未实测 |
| 主机前置操作 | `host info` | 已注册 | 待逐项验收 | 均未实测 |
| 主机前置操作 | `host maintenance-enter` | 已注册 | 模块测试及审查通过；发布验收待完成 | 均未实测 |
| 主机前置操作 | `host maintenance-exit` | 已注册 | 模块测试及审查通过；发布验收待完成 | 均未实测 |
| 告警 | `alarm list` | 已注册 | 待逐项验收 | 均未实测 |
| 告警 | `alarm acknowledge` | 已注册 | 待逐项验收 | 均未实测 |
| 告警 | `alarm reset` | 未注册 | 待逐项验收 | 均未实测 |
| 存储 | `datastore list` | 已注册 | 待逐项验收 | 均未实测 |
| 存储 | `datastore inspect` | 已注册 | 待逐项验收 | 均未实测 |
| 存储 | `datastore browse` | 已注册 | 待逐项验收 | 均未实测 |
| 存储 | `datastore scan` | 已注册 | 待逐项验收 | 均未实测 |
| 事件和配额 | `events list` | 未注册 | 待逐项验收 | 均未实测 |
| 事件和配额 | `quota check` | 未注册 | 待逐项验收 | 均未实测 |
| IP | `ip check` | 未注册 | 待逐项验收 | 均未实测 |
| IP | `ip available` | 未注册 | 待逐项验收 | 均未实测 |
| IP | `ip reserve` | 已注册 | 待逐项验收 | 均未实测 |
| IP | `ip release` | 已注册 | 待逐项验收 | 均未实测 |
| IP | `ip list` | 已注册 | 待逐项验收 | 均未实测 |
| IP | `ip expire` | 未注册 | 待逐项验收 | 均未实测 |
| 预设 | `preset list` | 已注册 | 模块测试/审查通过；发布验收待完成 | 均未实测 |
| 预设 | `preset show` | 已注册 | 模块测试/审查通过；发布验收待完成 | 均未实测 |
| 预设 | `preset save` | 已注册 | 模块测试/审查通过；发布验收待完成 | 均未实测 |
| 预设 | `preset delete` | 已注册 | 模块测试/审查通过；发布验收待完成 | 均未实测 |
| 预设 | `preset from-history` | 已注册 | 模块测试/修复复核通过；发布验收待完成 | 均未实测 |
| 预设 | `preset from-vm` | 已注册 | CPU/内存提取测试/复核通过；发布验收待完成 | 均未实测 |
| 缓存 | `cache status` | 已注册 | 离线测试及独立审查通过；当前服务端身份明确未核实 | 均未实测 |
| 缓存 | `cache refresh` | 已注册 | 离线测试及独立审查通过；实时只读采集、并发代次校验 | 均未实测 |
| 缓存 | `cache invalidate` | 已注册 | 离线测试及独立审查通过；精确 Profile/kind、撤销在途刷新 | 均未实测 |
| 历史 | `history list` | 已注册 | 模块测试/审查通过；发布验收待完成 | 本地功能 |
| 历史 | `history show` | 已注册 | 模块测试/审查通过；发布验收待完成 | 本地功能 |
| 审计 | `audit list` | 已注册 | 待逐项验收 | 均未实测 |
| 审计 | `audit export` | 已注册 | 待逐项验收 | 均未实测 |
| 密钥 | `secret list` | 已注册 | POSIX模块测试/审查通过；Windows后端待实现 | 本地功能；平台验收未完成 |
| 密钥 | `secret set` | 已注册 | POSIX模块测试/审查通过；Windows后端待实现 | 本地功能；平台验收未完成 |
| 密钥 | `secret delete` | 已注册 | POSIX模块测试/审查通过；Windows后端待实现 | 本地功能；平台验收未完成 |
| 密钥 | `secret rotate` | 已注册 | POSIX模块测试/审查通过；Windows后端待实现 | 本地功能；平台验收未完成 |
| 策略 | `policy inspect` | 已注册 | 静态检查测试/审查通过；发布验收待完成 | 不声明远端授权 |
| 策略 | `policy check` | 已注册 | 静态检查测试/审查通过；发布验收待完成 | 不声明远端授权 |
| TTL | `vm set-ttl` | 未注册 | 待逐项验收 | 均未实测 |
| TTL | `vm cancel-ttl` | 未注册 | 待逐项验收 | 均未实测 |
| TTL | `vm list-ttl` | 未注册 | 待逐项验收 | 均未实测 |
| TTL | `vm expired-ttl` | 未注册 | 待逐项验收 | 均未实测 |
| TTL | `vm cleanup-ttl` | 未注册 | 待逐项验收 | 均未实测 |
| 任务 | `task list` | 已注册 | 待逐项验收 | 均未实测 |
| 任务 | `task inspect` | 已注册 | 待逐项验收 | 均未实测 |
| 任务 | `task wait` | 已注册 | 待逐项验收 | 均未实测 |
| 任务 | `task cancel` | 已注册 | 待逐项验收 | 均未实测 |
| 任务 | `task reconcile` | 已注册 | 待逐项验收 | 均未实测 |
| 数据迁移 | `migration inspect` | 未注册 | 待逐项验收 | 均未实测 |
| 数据迁移 | `migration apply` | 未注册 | 待逐项验收 | 均未实测 |
| 数据迁移 | `migration verify` | 未注册 | 待逐项验收 | 均未实测 |
| 扫描 | `scan run` | 未注册 | 待逐项验收 | 均未实测 |
| 扫描 | `scan status` | 未注册 | 待逐项验收 | 均未实测 |
| 扫描 | `scan history` | 未注册 | 待逐项验收 | 均未实测 |
| 扫描 | `scan report` | 未注册 | 待逐项验收 | 均未实测 |
| 调查 | `attention` | 未注册 | 待逐项验收 | 均未实测 |
| 调查 | `summary` | 未注册 | 待逐项验收 | 均未实测 |
| 调查 | `investigate vm` | 未注册 | 待逐项验收 | 均未实测 |
| 调查 | `investigate host` | 未注册 | 待逐项验收 | 均未实测 |
| 调查 | `investigate datastore` | 未注册 | 待逐项验收 | 均未实测 |
| 调度 | `schedule create` | 未注册 | 待逐项验收 | 均未实测 |
| 调度 | `schedule list` | 未注册 | 待逐项验收 | 均未实测 |
| 调度 | `schedule show` | 未注册 | 待逐项验收 | 均未实测 |
| 调度 | `schedule update` | 未注册 | 待逐项验收 | 均未实测 |
| 调度 | `schedule enable` | 未注册 | 待逐项验收 | 均未实测 |
| 调度 | `schedule disable` | 未注册 | 待逐项验收 | 均未实测 |
| 调度 | `schedule delete` | 未注册 | 待逐项验收 | 均未实测 |
| 调度 | `scheduler run` | 未注册 | 待逐项验收 | 均未实测 |
| 调度 | `scheduler status` | 未注册 | 待逐项验收 | 均未实测 |
| 通知 | `notify channel-add` | 未注册 | 待逐项验收 | 均未实测 |
| 通知 | `notify channel-list` | 未注册 | 待逐项验收 | 均未实测 |
| 通知 | `notify channel-update` | 未注册 | 待逐项验收 | 均未实测 |
| 通知 | `notify channel-delete` | 未注册 | 待逐项验收 | 均未实测 |
| 通知 | `notify enable` | 未注册 | 待逐项验收 | 均未实测 |
| 通知 | `notify disable` | 未注册 | 待逐项验收 | 均未实测 |
| 通知 | `notify test` | 未注册 | 待逐项验收 | 均未实测 |
| 通知 | `notify send` | 未注册 | 待逐项验收 | 均未实测 |
| 通知 | `notify history` | 未注册 | 待逐项验收 | 均未实测 |
| 通知 | `notify retry` | 未注册 | 待逐项验收 | 均未实测 |
| MCP | `mcp serve` | 未注册 | 待逐项验收 | 均未实测 |
| 编排 | `plan create` | 已注册 | 待逐项验收 | 均未实测 |
| 编排 | `plan show` | 已注册 | 待逐项验收 | 均未实测 |
| 编排 | `plan list` | 已注册 | 待逐项验收 | 均未实测 |
| 编排 | `plan validate` | 已注册 | 待逐项验收 | 均未实测 |
| 编排 | `plan apply` | 已注册 | 待逐项验收 | 均未实测 |
| 编排 | `plan reconcile` | 已注册 | 待逐项验收 | 均未实测 |
| 编排 | `plan rollback` | 已注册 | 待逐项验收 | 均未实测 |
| 编排 | `plan archive` | 已注册 | 待逐项验收 | 均未实测 |
| 编排 | `batch power-on` | 已注册 | 待逐项验收 | 均未实测 |
| 编排 | `batch shutdown` | 已注册 | 待逐项验收 | 均未实测 |
| 编排 | `batch power-off` | 已注册 | 待逐项验收 | 均未实测 |
| 编排 | `batch reset` | 已注册 | 待逐项验收 | 均未实测 |
| 编排 | `deploy batch-clone` | 未注册 | 待逐项验收 | 均未实测 |
| 编排 | `deploy batch` | 未注册 | 待逐项验收 | 均未实测 |
| 编排 | `vm guest-provision` | 未注册 | 待逐项验收 | 均未实测 |
| 编排 | `vm clean-slate` | 未注册 | 待逐项验收 | 均未实测 |

最终验收还需覆盖 PRD AC-01–29、核心分支覆盖率、隔离安装、发布包内容和跨平台运行；命令数量与测试数量不能替代这些门槛。
