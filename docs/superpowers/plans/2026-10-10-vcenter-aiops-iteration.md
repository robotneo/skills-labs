# vCenter AIops Iteration I — P0 收敛 Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development. Task-by-task，任务之间不请求批准；controller 负责集成与终审，implementer 不再派生 agent。

**Goal:** 把已批准 PRD 1.2 的 P0 缺口（只读契约、链接克隆落地、Guest 输出与传输、告警重置、OVA/OVF）推进到可验证状态，使 3.0.0a1 具备进入 beta 的核心面。

**Ground truth（2026-10-10 实测，优先于台账行）：**
- CLI 实注册 **97 = 必需 94 + 额外 `datastore search-*` 3 个**（search-inspect / search-list / search-status，均不抵扣必需）。
- `deploy linked-clone` **已注册且 Provider 已实现**（`application/registrations/linked.py` + `providers/vsphere/linked.py`），但台账行仍标"未注册"——属行级滞后，Task 0 刷新；这是代码 94 与台账 93 的唯一差异。
- 真实缺失（未注册，**55**）：`inventory export`、`events list`、`quota check`、`ip check`、`ip available`、`ip expire`、`deploy ova/ovf`、Guest 5 个、`alarm reset`、TTL、迁移、扫描、调查、调度、通知、MCP、组合编排。
- 本迭代只做 **P0**：W1 只读 + W2 链接克隆验收 + W3 Guest + W4 alarm reset + W2 的 OVA/OVF。W5–W9 列入后续迭代。

**Architecture:** 保留唯一 `vcenter-aiops` CLI、逐叶子契约与现有确认执行引擎（`application/execution.py` + `providers.py:ProviderRouter`）。新增能力通过注册表 `provider_kind` 元数据路由到受控 Provider；SDK 对象不穿透 Provider 边界，领域结果可序列化。复用现有意图、回执、核对、审计与请求去重。

**Tech Stack:** Python >=3.10、pyVmomi（`>=8.0.3,<10`）、SQLite、PyYAML；加密/MCP 可选，禁止导入期联网安装。

**Spec:** `docs/prd/vcenter-ops-3.0-prd.md`（1.2，已审批）。看板：`vcenter-aiops/references/ITERATION-KANBAN.md`。本计划不改变 PRD 范围。

## Global Constraints

- 唯一公共命令 `vcenter-aiops`，包名 `vcenter_aiops`；不恢复 `handler.py --action`，不提供旧别名/转发层。
- 兼容目标 6.5/6.7/7.0/8.0；模拟通过不替代实机，未验证标 `not_lab_verified`，禁止宣称兼容。
- **本迭代不安装 Skill 到 WorkBuddy**，不写入 `~/.workbuddy/skills/`；仅在仓库内改代码与文档。
- 不连接真实 vCenter、不外发通知、不迁移真实凭据；只写代码 + 离线测试。
- 每项 TDD：先写失败测试 → 实现 → 跑定向 → 跑全量离线并记录证据；不注册占位命令、不写 NotImplemented。
- Result 统一契约不泄露凭据；未知写结果保持 `reconciliation_required`，先核对不重发；`--dry-run` 不提交远端。
- 危险写（delete / 链接父磁盘破坏 / alarm reset）沿用二次确认；确认值一次性、绑定计划、默认 10 分钟有效。

**测试命令基线：**
```bash
cd vcenter-aiops
PYTHONPATH=src /Users/hua/.workbuddy/binaries/python/versions/3.13.12/bin/python3 -m unittest discover -s tests -q
```

**Iteration I 出口指标（Definition of Done）：**
- 必需叶子注册数 94 → **108（≥ 108）**（新增 inventory export/events/quota = 3，ip check/available/expire = 3，ova/ovf = 2，Guest exec-output/output/upload/download = 4，guest-customize = 1，alarm reset = 1，合计 +14）。
- 全量离线测试通过且新增覆盖成功/拒绝/恢复三类；无实机宣称，vSphere 字段仍 `not_lab_verified`。
- `COMMAND-ACCEPTANCE.md` 与看板数字、日期同步刷新。

---

## Task 0: 台账收敛（已完成 ✅，2026-10-10）

> 本任务已被"台账运维聚焦化"取代并完成，不再执行原刷新动作。
- 台账 `COMMAND-ACCEPTANCE.md` 已重写：14 项运维待做为主体、94 项已交付移出待办、41 项搁置；完整150项归档 `docs/archive/COMMAND-ACCEPTANCE-FULL-150-20260929.md`。
- 看板与状态文档已同步；对账 94 + 14 + 41 = 149（+延期1=150）自洽。
- 下游 Task 1–7 的命令范围与新台账 14 项一一对应；linked-clone 已属已交付，见 Task 4a 说明。

---

## Task 1: 只读叶子补齐 — inventory export / events / quota

**Files:**
- 修改 `providers/vsphere/inventory.py`（或 `reads.py`）：新增 export 序列化与事件/配额读取。
- 新增处理器：可在 `application/commands/queries.py` 扩展 `inventory_export`、`events_list`、`quota_check`。
- 新增/修改注册：`application/registrations/` 对应只读领域文件，主注册表聚合。
- 新增 `tests/test_read_extensions.py`。

**Interfaces:**
- `inventory export`：复用 `inventory list` 的过滤/分页口径，输出到 `--file`（不覆盖已有文件/符号链接），支持 json/csv；HTML/CSV 对外部字段转义，属 `local_read`，不需要 vCenter 写权限。
- `events list`：参数 `--vm-id|--host-id`（可选，精确对象范围）、`--since`（ISO8601）、`--event-type`（可选）、`--limit`（默认100，最大1000）、分页 cursor；走 EventManager `QueryEvents`（PropertyCollector 风格只读）。权限不足与无事件分别返回，不把缺失解释为空。
- `quota check`：输入目标 `cluster_id`/`host_id`/`datastore_id` 与请求量（cpu/memory_gb/storage_gb），返回可用量、已用量、是否满足及来源采集时间；只读，不预留。无法取得容量字段时返回 `unavailable` + 原因，不臆测。

- [ ] 失败测试：export 不覆盖已有文件、CSV 对 `= + - @` 前缀加引号；events 分页 cursor 稳定、时间边界；quota 对缺失字段返回 unavailable；help/version 不联网。
- [ ] 实现最小只读路径并注册（`category` 为 `local_read`/`read_only`），接 ProviderRouter 时只读不进入确认。
- [ ] 跑定向 + 全量离线，记录证据。

---

## Task 2: IP 只读信号 — ip check / available / expire

**Files:** 修改 `application/commands/`（IP 现有逻辑所在）、`providers/vsphere`（如需网络只读探测）、注册文件；新增 `tests/test_ip_signals.py`。

**Interfaces（严格区分"信号"与"预留"）：**
- `ip check --address A --scope <network-scope>`：返回资产占用（VM IP/名称正则）、本地租约、ping 探测三路信号；ping 不通**只作信号**，探测不可用返回 `inconclusive`，绝不等于空闲。
- `ip available`：综合三路仅在有正向空闲证据时返回 `true`；任一不确定返回 `inconclusive`，不自动分配。
- `ip expire`：只处理**已过期且无部署关联未知结果**的本地租约；默认仅列出，`--apply` 才释放且须精确租约 ID。作用域 + 地址为唯一键，不同隔离网络可同址。
- 复用现有事务 IP 池唯一约束；不覆盖已有预留。

- [ ] 失败测试：ping 不可用不判空闲；同作用域同地址并发只允许一个租约；expire 不释放结果未知的部署关联租约；跨作用域同地址允许。
- [ ] 实现并注册为只读/本地命令，确认 `ip expire` 的释放动作走现有确认边界。
- [ ] 跑定向 + 全量离线。

---

## Task 3: 类型化步骤引用基础（跨 Provider 编排前置）

**Files:** 修改 `domain/contracts.py`、`application/execution.py`、`providers.py:bind_steps`；新增 `tests/test_typed_references.py`。

**Why now:** W2/W3 的部署计划（reserve → deploy → guest-customize → power-on → wait-tools）需要把前一步输出以类型化引用传递，禁止拼 Shell，也禁止不安全的跨 Provider 现状投影。

**Interfaces:**
- 在步骤模型增加可选 `output_ref`（`{from_step, field, value_type}`）与注册表声明的 `outputs` schema；计划绑定在事务内解析引用并类型校验。
- `bind_steps` 对跨 Provider 计划：仅在引用可解析且类型匹配时放行；否则仍返回 `plan_dependency_unsupported`，不退回逐现状预检。
- 引用值只来自已核对的本地执行结果，不来自远端名称/不可信字段。

- [ ] 失败测试：类型不匹配/引用缺失被拒；合法跨域引用绑定成功；篡改 from_step 不执行写；计划变化使旧确认失效。
- [ ] 最小实现，不提前实现后续业务命令。
- [ ] 全量离线，确保现有同 Provider 计划投影不回归。

---

## Task 4: 链接克隆离线验收闭环 + OVA/OVF

**4a. 链接克隆（已注册/已实现，补齐验收证据）：**
**Files:** 核对 `providers/vsphere/linked.py`、`application/commands/linked.py`；扩展 `tests/test_templates_linked.py`/`test_linked_clone_strict.py`。
- [ ] 补齐成功路径（关机克隆、child backing 为新 delta、放置/网卡/父链 verify）的断言对齐 `linked.verify`。
- [ ] 补齐拒绝路径：父 UUID/快照不匹配、当前与快照磁盘或网卡不一致、源/目标 delta 能力缺失、非 FlatVer2/加密/RDM/共享盘 → `capability_unsupported`。
- [ ] 补齐严格保护：对父对象的 delete / snapshot-delete / snapshot-revert / 跨存储 migrate，在无法排除外部链接依赖时一律 `dependency_unproven`，确认本地无记录不构成放行（无 bypass）。
- [ ] 丢回执恢复：未知结果不重发，走 reconcile；`--dry-run` 零写入。
- [ ] 不新造第二写路径，复用 `createNewChildDiskBacking` 的现有 clone。

**4b. OVA / OVF（新注册）：**
**Files:** 新增 `providers/vsphere/ovf.py`、`application/commands/` 对应处理器、注册文件、`tests/test_ovf_deploy.py`。
**Interfaces:**
- `deploy ova --source <local.ova> --resource-pool-id --host-id --folder-id --datastore-id [--disk-provisioning] [--network-mapping k=net-id ...]`；`deploy ovf` 接受描述符目录 + 引用磁盘。
- 校验 OVF 描述符、引用磁盘存在性、网络映射完整、目标容量、硬件兼容；本地 OVA 解包**拒绝路径穿越**（`../`、绝对路径、符号链接逃逸）。
- NFC lease 传输：保活、进度、超时与取消；中断后核对已创建对象，清理仅限本次产生且有授权的资源。
- 默认不开机、不隐式 Guest 定制；`powerOn=false`。能力/许可证不足在写前返回 `capability_unsupported`。

- [ ] 失败测试：路径穿越被拒；网络映射缺失拒绝；容量不足拒绝；NFC 中断后状态可核对、不盲清；dry-run 零远端。
- [ ] 实现并注册，跑定向 + 全量离线。

---

## Task 5: Guest 输出捕获与文件传输

**Why:** 当前 `vm guest-exec` 输出为 DEVNULL，不满足 PRD 完整验收；本任务替换为真实输出，并交付传输。

**Files:** 修改 `providers/vsphere/guest.py`、`guest_protocol.py`、`guest_wrapper.py`、`application/commands/guest.py`、`application/registrations/guest.py`；新增 `tests/test_guest_output.py`、`tests/test_guest_transfer.py`。

**Interfaces:**
- `vm guest-exec-output`：在已批准"显式包装器方案 A"上，执行并把 stdout/stderr/exit_code 写入 Guest 侧有界结果文件，本地通过严格有界 SDK 文件查询读取；完成判定绑定本次 run-id，不仅凭 PID/Tools 短期记录。展示包装源码、参数、目录、保留策略。
- `vm guest-output --run-id`：仅读已有运行输出，不重新执行；结果缺失/损坏/身份不符返回不确定，不冒充成功。
- `vm guest-upload` / `guest-download`：校验本地与 Guest 路径、覆盖策略、容量、传输端点；拒绝路径穿越；返回真实进度与结果；临时文件清理有记录。
- OS 显式：Windows/Linux 分别适配，要求 Guest 已有 Python 3.10+（不自动安装）；日志不保存 Guest 密码；命令输出只作数据。
- 未知启动响应不自动重发；取消不猜目标。

- [ ] 失败测试：输出文件绑定 run-id、损坏返回不确定；上传/下载路径穿越拒绝、覆盖策略生效；超时不伪报成功；OS 不匹配拒绝；dry-run 零写。
- [ ] 实现并注册 4 个叶子，跑定向 + 全量离线。

---

## Task 6: Guest 定制

**Files:** 修改 `providers/vsphere/guest.py`（或新增 customize 适配器）、`application/commands/guest.py`、注册文件；新增 `tests/test_guest_customize.py`。

**Interfaces:**
- `vm guest-customize --vm-id --spec-file <declarative.yaml|json>`：显式声明 hostname/IP/掩码/网关/DNS 等，固定 VM 身份与目标网络；生成自定义预览，提交与"来宾实际配置完成"分别报告（依赖 Tools/可能重启）。
- 复用 Task 3 类型化引用接入部署链；不隐式开机；不把定制提交成功当完成。
- 保留 `IP-自定义名称` 规则；未取得 IP 不编造前缀。

- [ ] 失败测试：spec 字段校验、网络身份固定、提交成功但配置未完成的分离报告、重启后状态可核对、dry-run 零写。
- [ ] 实现并注册，全量离线。

---

## Task 7: alarm reset 差异化交付

**Files:** 修改 `providers/vsphere/alarms.py`、`application/commands/`（告警处理器）、注册文件；扩展 `tests/test_alarms.py`。

**Interfaces（硬约束：不静默扩大范围）：**
- 官方 `AlarmManager.ClearTriggeredAlarms(AlarmFilterSpec)` 自 **6.7** 提供；`AlarmFilterSpec` **无实体 ID/告警 ID**，仅 status/type/time/对象根过滤。
- 6.5：叶子注册但在写前返回 `capability_unsupported`（不伪造、不换扩大范围接口）。
- 6.7+：仅接受能映射到过滤器的条件，预览明确展示实际 scope（实体根及其后代、状态、类型）与预计数量级；无等价精确能力时返回不支持。
- 危险操作二次确认；reset 不等于故障修复；目标不存在时拒绝宽范围清除。

- [ ] 失败测试：6.5 拒绝；过滤器无法表达精确对象时拒绝；scope 与实际过滤一致；确认前零写；丢回执不重发。
- [ ] 实现并注册，跑定向 + 全量离线。

---

## 集成与收尾（controller）

- [ ] 从干净构建目录构建 wheel 并运行 `scripts/verify_wheel.py`，确认无旧 handler/别名、模块集合匹配。
- [ ] 全量离线测试通过；登记实际测试数与新增覆盖三类（成功/拒绝/恢复）。
- [ ] 刷新 `COMMAND-ACCEPTANCE.md`（Task 0 起持续）与看板数字/日期；`IMPLEMENTATION-STATUS.md` 增加本迭代条目。
- [ ] 复核 Iteration I 出口指标：必需注册 108，无实机/兼容宣称，仍为 3.0.0a1（是否升 b1 由 controller 依质量门决定，不在本迭代自动升版）。

## 后续迭代（不在本计划展开）

- **Iteration II（P1）：** `mcp serve` 叶子逐工具映射、`vm clean-slate`、`migration inspect/apply/verify`；发布包去旧 handler，beta → rc。
- **Iteration III（P2）：** TTL（5）、扫描/调查/调度（18）、通知（10），默认关闭。
- **跨迭代持续项：** vSphere 6.5–8.0 实机兼容矩阵（优先 7.0/8.0 一套跑核心）、Windows 密钥后端、vcenter-guard 识别新入口、切换后删除旧 vcenter-ops 目录。