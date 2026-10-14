# vCenter AIops 3.0 Implementation Plan

> **执行状态：** 未完成项的连续收尾次序已迁至 `2026-09-10-vcenter-aiops-completion.md`。本文件保留历史进度；按新的整体收尾计划执行，不重复派发已完成内容。

**Goal:** 实现已批准的原子 CLI 全领域重构，保留真实状态与兼容证据。

**Architecture:** CLI/MCP 复用命令契约和应用处理器；Provider 隔离 pyVmomi。SQLite 管理计划、操作与租约；独立数据目录存放配置和审计。逐阶段验证，不把未完成能力注册成可执行入口。

**Tech Stack:** Python >=3.10、argparse、SQLite、pyVmomi、PyYAML；MCP/调度/加密依赖按需引入。当前可用 Python 3.12 与 pyVmomi 9.1.0.0 仅作本机开发，不作为 6.5–8.0 兼容结论。

**Spec:** docs/prd/vcenter-ops-3.0-prd.md（1.2，已批准）

## Global Constraints

- 唯一公开命令 vcenter-aiops；新发行包不包含 scripts/handler.py 或 --action 兼容入口。
- 支持目标为 vSphere 6.5、6.7、7.0、8.0；全部实机验证状态初始为未验证。
- 无生产连接与写入，无真实凭据导入。旧目录在新功能完成前保留为迁移来源，最终切换时移除。
- 不导入旧执行器充当新架构；不注册 TODO/NotImplemented 命令作为已完成能力。

## Task 1: 新入口与可验证命令契约

Files: vcenter-aiops/pyproject.toml, src/vcenter_aiops/{__init__,__main__}.py, cli/main.py, domain/models.py, application/registry.py, tests/test_cli.py, SKILL.md, run.sh, run.ps1, run.bat。

Interfaces: CommandSpec(path, handler, category, description); Result(status, data, error, next_action); main(argv)->int。

- [x] 新 CLI version/help/doctor 不导入 pyVmomi、不创建运行目录；未知旧参数返回退出码 2。
- [x] 测试 JSON 单对象结果、独立叶子 help、未实现能力不冒充可用。
- [x] 执行 `PYTHONPATH=src python -m unittest discover -s tests`；当前 23 个离线测试通过。

## Task 2: 本地状态和配置

Files: infrastructure/{paths,store,config}.py, application/local.py, tests/test_state.py。

Interfaces: Store(path).reserve(scope, ip, owner); Store.create_plan(steps); Store.claim(operation_id); ProfileStore(path).get(name)。

- [x] 单 SQLite 事务实现租约唯一性、计划不可变内容摘要、操作 request-id 去重及目标互斥。
- [x] 测试并发争抢 IP 仅一个成功，参数变化 request-id 冲突，未知提交状态不能重复 claim。
- [x] 配置只存凭据引用，验证端口/TLS 与 Profile 名称，写入采用原子替换。
- [x] profile、ip、plan 查询命令真实可运行；无连接操作不加载凭据。

当前交付边界：基础候选版已构建安装；完整参数 schema、Provider 任务观察器及下述业务域仍在待实施清单中。状态库已验证未知状态保锁和匹配远端任务后的终态流转，但这不等于远端写执行器完成。

## Task 3: 连接与只读 Provider

Files: providers/vsphere/{connection,inventory}.py, application/queries.py, tests/test_provider.py。

Interfaces: VsphereSession(profile), Inventory.list(kind, limit), Inventory.resolve(kind, selector)。

- [x] 默认 CA 验证、显式 insecure、环境变量凭据引用；验证 session disconnect 与凭据缺失不连接。
- [ ] 查询返回序列化记录、重名拒绝、属性批量读取及分页，不返回 SDK 对象。
- [ ] capabilities 同时列实现状态、服务端可用性及未验证版本状态。

## Task 4: 原子写入及计划恢复

Files: application/{execution,plans}.py, providers/vsphere/{vm,snapshots,tasks}.py, tests/test_execution.py。

- [ ] 写入前固定身份/摘要、预检、确认及持久化意图；提交后保存 task ID。
- [ ] 模拟提交后崩溃必须返回待核对，不重复写；超时/取消/部分回滚分别测试。
- [ ] 迁移 VM 创建/电源/配置/克隆/迁移/快照/销毁，delete 不隐式关机。

## Task 5: 部署、Guest、集群、告警

Files: providers/vsphere/{deployment,guest,cluster,alarms,datastores}.py；对应 application 处理器及 tests。

- [ ] OVA 路径安全与 NFC lease；Guest 文件传输和 OS 适配；集群维护/许可证；告警实际范围。
- [ ] 每个原子动作独立失败测试，组合计划复用同处理器。

## Task 6: 扫描、调度、通知、TTL

Files: application/{scans,schedules,notifications,ttl}.py；infrastructure/outbox.py；tests。

- [ ] 默认只读扫描、通知关闭、对象级 TTL 授权；多目标 partial 与重启去重。
- [ ] 通知失败有限重试、持久化状态；未知投递不伪报成功。

## Task 7: MCP、旧数据迁移与完整交付

Files: mcp/server.py, migrations/import_v2.py, references/COMMANDS.md, tests/test_migration.py。

- [ ] MCP 逐叶子映射；本地敏感管理能力默认不暴露。
- [ ] 数据迁移预演/备份/校验；旧计划/TTL 不自动执行，旧确认不继承。
- [ ] 原子命令全清单验收后移除旧目录，更新仓库索引，生成无测试/缓存的发行包。

## Task 8: 实验矩阵与发布

- [ ] 四系列服务端按命令记录 build、SDK、证据与限制。
- [ ] Windows/macOS/Linux 安装测试，CLI/MCP 契约测试，PRD AC-01–29 验收。
- [ ] 实机条件缺失时发布候选里程碑，不宣布完整 3.0 兼容完成。

## 2026-09-10 续作记录

- 已推进逐命令 schema、部分生命周期 Provider、多步确认执行、任务核对与有限补偿；完整功能清单仍以 PRD 为验收基准，Task 4–8 尚未全部完成。
- 审查发现并修复跨执行轮次及同轮次的陈旧观察竞争：恢复收尾在文件锁和数据库事务内重读全部步骤状态，不能将正在运行的后续步骤误报为可继续执行。
- 同步 Skill 导航与实施状态，明确候选版边界、恢复确认值以及尚未完成的能力。无真实 vCenter 连接或生产写入。
- 补齐 plan validate 的状态投影与恢复计划校验：仅检查未完成步骤，不消费确认值；运行中计划引导核对原任务，不提供错误的静态验证结论。
- 推进 Task 5 告警查询：新增独立 alarm list 处理器与 Provider，精确范围、过滤、截断、不可读状态均有离线测试。确认及重置仍待实现，不能标记整个告警模块完成。
- 告警确认已接入现有执行引擎，离线覆盖预览不写、精确目标提交、后置核对及不可补偿状态。重置 API 的版本与宽范围限制已确认，尚未开放 reset 命令。
- 新增数据存储单目录 browse/scan 原子入口，覆盖安全路径、镜像扩展名过滤、输出截断、任务超时及失败。递归搜索及只读搜索任务的持久化恢复尚未完成。
- 数据存储续作：显式递归已接入子目录搜索 API；搜索独立表持久化意图、回执与终态，新增 search-status/search-inspect/search-list，验证重启恢复、请求去重、丢响应不重提、跨 Profile 拒绝与并发旧观察保护。上述递归及恢复待办已落实到离线实现，实机验收仍待进行。
- 本地审计续作：新增 audit list/export，固定快照上界分页、主体 HMAC 伪名化、独占发布不覆盖文件、只在本地生成证据。审计全库范围显式返回，拒绝不支持的 Profile 过滤。
- 本轮验证：110 项测试分别在源码与安装包环境通过；新增 wheel 源码一致性校验，隔离了污染安装包的旧 build 缓存。安装包内 26 个 Python 模块与源码匹配。审计导出后置失败返回 partial 的问题已修复并经独立复核。
