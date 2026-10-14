# vCenter AIops 迭代看板

> 单一事实来源：`references/COMMAND-ACCEPTANCE.md`（台账）、`references/IMPLEMENTATION-STATUS.md`（阶段记录）、`docs/prd/vcenter-ops-3.0-prd.md`（PRD 1.2，已审批）。
> 本看板只做**状态呈现与排期**，不改变 PRD 范围；数字以台账注册核对日期为准。

| 项目 | 值 |
| --- | --- |
| 产品 / 命令 | vCenter AIops / 唯一公共命令 `vcenter-aiops` |
| 当前版本 | **3.0.0b4**（execution-beta，候选版；新增克隆模版标准流程 `deploy clone-template`，待真机复测 D08/D15/D16/D25b 及克隆验收，非 GA） |
| 看板更新 | 2026-10-14（迁移 vcenter-ops v2.0 克隆模版流程为 `deploy clone-template`；新增 15 项 Engine 级克隆流程桩测试并清理死代码/构建产物；496 离线测试通过） |
| 安装状态 | 已安装用户级 `~/.workbuddy/skills/vcenter-aiops/`（b1 安全审计后）；b4 发布后 rsync 同步，经 `VCENTER_AIOPS_PYTHON` 指向隔离 venv 运行 |
| PRD 必需叶子 | 150 |
| 当前实施范围 | 149（`cluster add-host` 经用户批准方案 A 延期，不计入完成） |
| 已交付（地面真值） | **108 / 149（72%）**（PRD 必需口径；另额外注册 `deploy clone-template` 对齐 vcenter-ops 克隆模版标准流程，不属原 150 必需叶） |
| 剩余 41 的拆分 | **搁置 41**（原 14 项运维待做已全部转为已交付，待实机验收） |
| 台账口径（2026-10-10 beta） | `COMMAND-ACCEPTANCE.md`：14 项 A–E 组全部注册 ☑ + 离线 ☑，实机列待用户勾选 ☐；41 项低频/治理维持搁置；完整 150 项归档于 `docs/archive/COMMAND-ACCEPTANCE-FULL-150-20260929.md` |
| 离线测试 | **496 项通过**（截至 2026-10-14；481 + 15 项克隆流程 Engine 桩测试） |
| 实机验收 | 6.5 / 6.7 / 7.0 / 8.0 → **0 / 4**（14 项新增能力全部 `not_lab_verified`） |

> 数字口径：`capabilities list` 实注册 **112** = 必需 108 + 额外 `datastore search-*` 3（search-inspect / list / status，不抵扣必需）+ `deploy clone-template` 1（对齐 vcenter-ops v2.0 克隆模版标准流程）。
> 对账：108 已交付 + 41 搁置 = 149，+延期 add-host = 150。
> 本看板按领域全量列保留作全景参考；**当前已完成 beta 核心面，下一步是用户实机验收**。

## 状态图例

- **已注册**：CLI 叶子入口存在于命令注册表。不代表功能完成。
- **离线验收**：具备独立 help/schema，且有处理器成功 / 拒绝 / 恢复测试与独立审查证据。
- **实机验收**：在对应 vSphere 系列上实测，记录 vCenter/ESXi build、账号权限、许可证、Tools、硬件版本。
- **延期**：`cluster add-host`，严格指纹安全策略，需独立设计与批准，不开放占位入口。
- 三个状态严格分离：**已注册 → 离线验收 → 实机验收**，不得跳级宣称。

## 看板列：按领域汇总

> R=已注册，U=未注册，D=延期；括号为命令数。进度 = R / 实施数。

| 领域 | R | U | D | 进度 | 备注 |
| --- | --: | --: | --: | --- | --- |
| 运行环境 version/doctor/capabilities | 4 | 0 | 0 | 100% | 离线逐项验收待补 |
| 连接配置 profile | 6 | 0 | 0 | 100% | show 不显示凭据 |
| 资产 inventory | 2 | 0 | 0 | 100% | `inventory export` 已注册离线过审，实机待验收 |
| VM 查询 list/inspect | 2 | 0 | 0 | 100% | |
| 电源 power | 5 | 0 | 0 | 100% | 不自动降级为强制操作 |
| VM 变更 create/clone/rename/reconfigure/migrate/delete | 6 | 0 | 0 | 100% | create/reconfigure 离线过审，发布验收待补 |
| 快照 snapshot | 4 | 0 | 0 | 100% | revert 后状态不可静态投影 |
| 模板 template / mark-template | 4 | 0 | 0 | 100% | convert 离线过审 |
| 部署 deploy | 6 | 0 | 0 | 100% | linked-clone 已注册；`ova`/`ovf` 已注册离线过审，NFC/TLS 实机待验收 |
| Guest | 9 | 0 | 0 | 100% | exec-output/output/upload/download/customize 已注册离线过审，Guest 内 Python/Windows 实机待验收 |
| 集群 cluster | 6 | 0 | 1 | 86% | add-host 延期；其余发布验收待补 |
| 主机前置 host | 3 | 0 | 0 | 100% | maintenance 离线过审 |
| 告警 alarm | 3 | 0 | 0 | 100% | `alarm reset` 已实现：6.7+ ClearTriggeredAlarms，仅 VM/Host 类型过滤，6.5 拒绝；实机待验收 |
| 存储 datastore | 4 | 0 | 0 | 100% | 另有搜索恢复入口（不抵扣必需） |
| 事件与配额 events/quota | 2 | 0 | 0 | 100% | `events list`/`quota check` 已注册离线过审 |
| IP | 6 | 0 | 0 | 100% | `check`/`available`/`expire` 已注册离线过审 |
| 预设 preset | 6 | 0 | 0 | 100% | |
| 缓存 cache | 3 | 0 | 0 | 100% | 服务端身份未核实 |
| 历史 history | 2 | 0 | 0 | 100% | 本地功能 |
| 审计 audit | 2 | 0 | 0 | 100% | 未按 Profile 划分，范围为全部本地 |
| 密钥 secret | 4 | 0 | 0 | 100% | 仅 POSIX，Windows 后端待实现 |
| 策略 policy | 2 | 0 | 0 | 100% | 不声明远端授权 |
| TTL | 0 | 5 | 0 | 0% | 整列未注册 |
| 任务 task | 5 | 0 | 0 | 100% | |
| 数据迁移 migration | 0 | 3 | 0 | 0% | 整列未注册 |
| 扫描 scan | 0 | 4 | 0 | 0% | 整列未注册 |
| 调查 investigate/attention/summary | 0 | 5 | 0 | 0% | 整列未注册 |
| 调度 schedule/scheduler | 0 | 9 | 0 | 0% | 整列未注册 |
| 通知 notify | 0 | 10 | 0 | 0% | 整列未注册 |
| MCP | 0 | 1 | 0 | 0% | `mcp serve` 未注册 |
| 编排 plan/batch | 12 | 4 | 0 | 75% | 缺 batch-clone/batch/guest-provision/clean-slate |
| **合计（地面真值）** | **108** | **41** | **1** | **72%** | R+U=149 实施范围；14 项 A–E 已全部注册+离线验收，待实机；41 项搁置 |

## Backlog：55 个未注册叶子（全景归档视角）

> ⚠️ 2026-10-10 起，这 55 项已分流：**仅 14 项运维高频动作进入当前工作台账**（W1 的 6 + W2 的 ova/ovf 2 + W3 的 5 + W4 的 1），其余 **41 项（W5–W9 + 组合编排）整体搁置**。下列全量分组仅作全景参考，实际推进顺序以 `COMMAND-ACCEPTANCE.md` 的 14 项为准。

### W1 只读与契约补齐（6 + 1 前置能力）→ 全部进入待做（A/B 组）
`inventory export`、`events list`、`quota check`、`ip check`、`ip available`、`ip expire`、类型化步骤输出引用（跨计划前置能力，非独立叶子，作为编排依赖）。

### W2 部署（2 叶子 + 1 待验收）
未注册：`deploy ova`、`deploy ovf`。另有 `deploy linked-clone` 已注册、Provider 已实现，本迭代只补离线验收闭环（含父磁盘严格依赖保护）。

### W3 Guest 能力（5）
`vm guest-exec-output`、`vm guest-output`、`vm guest-upload`、`vm guest-download`、`vm guest-customize`；含真实输出捕获（替换当前 DEVNULL）。

### W4 告警（1）
`alarm reset`：`ClearTriggeredAlarms` 自 6.7 提供，`AlarmFilterSpec` 无实体/告警 ID，仅支持状态与类型过滤，必须按版本差异化、展示真实 scope，禁止静默扩大范围。

### W5 TTL（5）
`vm set-ttl`、`cancel-ttl`、`list-ttl`、`expired-ttl`、`cleanup-ttl`；默认仅提醒，清理消费持久化对象级授权。

### W6 数据迁移（3）
`migration inspect`、`migration apply`、`migration verify`；dry-run → 备份 → 转换 → 验证 → 切换，源数据不破坏。

### W7 扫描 / 调查 / 调度（18）
- 扫描 4：`scan run/status/history/report`
- 调查 5：`attention`、`summary`、`investigate vm/host/datastore`
- 调度 9：`schedule create/list/show/update/enable/disable/delete`、`scheduler run/status`

### W8 通知（10）
`notify channel-add/list/update/delete`、`enable/disable`、`test`、`send`、`history`、`retry`；默认关闭，持久化 outbox，限次退避与去重。

### W9 MCP 与组合编排（5）
`mcp serve`、`deploy batch-clone`、`deploy batch`、`vm guest-provision`、`vm clean-slate`。

## 优先级与排期

| 优先级 | 工作流 | 2026-10-10 状态 | 里程碑出口 |
| --- | --- | --- | --- |
| **下一步（阻塞 GA）** | 14 项的实机验收（W1 + ova/ovf + W3 Guest + W4 reset） | 注册+离线已完成，**等用户在真实 vCenter 验收勾选** | GA 前置 |
| 搁置 | W5 TTL、W7 扫描/调查/调度、W8 通知、mcp、4 组合编排 | 41 项，暂不做，可恢复 | 按需 |
| 切换时 | W6 数据迁移 | 一次性，2.0→3.0 切换前启用 | rc |
| 持续 | 实机兼容矩阵 + Windows 密钥后端 | 四系列与跨平台是 GA 硬门槛 | GA |

> 详细任务拆分、文件清单、接口契约、TDD 顺序见
> `docs/superpowers/plans/2026-10-10-vcenter-aiops-iteration.md`（Iteration I 覆盖 P0）。

## 风险与依赖登记

| ID | 风险 / 依赖 | 影响 | 缓解 |
| --- | --- | --- | --- |
| R-1 | 四系列实机验收 0/4 | 无法发稳定版，兼容声明无证据 | 优先争取 7.0/8.0 一套实验环境跑核心矩阵 |
| R-2 | 链接克隆 / 父磁盘依赖保护未定 | 误删父对象、存储迁移事故 | 无法排除依赖即拒绝 delete/快照清理/迁移 |
| R-3 | Guest 输出当前 DEVNULL | guest-exec 不满足完整验收 | 独立运行标记 + 有界文件查询，补齐输出捕获 |
| R-4 | alarm reset API 无法精确定位 | 可能扩大清除范围 | 版本差异化 + scope 展示，6.5 明确不支持 |
| R-5 | 密钥库仅 POSIX | 跨平台不完整 | 实现 Windows 安全后端，未完成即明确拒绝 vault |
| R-6 | vcenter-guard 仍指向 vcenter-ops | 新入口路由错配 | 后续让 Hook 识别 `vcenter-aiops`（独立改动） |
| R-7 | 旧 vcenter-ops 目录仍在 | 发布包含旧入口风险 | 切换验收后删除，发布包校验无 handler/别名 |
| R-8 | 结果不明写请求 | 重复提交风险 | 保持 reconciliation_required，先核对不重发 |

## 里程碑路线图（质量门，非时间承诺）

```text
3.0.0a1  ── execution-alpha：94 注册 / 340 离线测试 / 0 实机
  ▼
Iteration I (P0)  ── W1–W4 完成：inventory/events/quota、ip 3、ova/ovf、Guest 5、alarm reset
  ▼
3.0.0b1 ── execution-beta：必需 108 / 实注册 111 / 456 离线测试 / 真机 8.0.3 首轮只读验证（381 VM / 47 主机 / 5 集群）
  ▼
3.0.0b2 ── 修复真机只读 3 缺陷（VmomiSupport.long 标量、DatastoreBrowser session[] 任务 id、CLI format dest 冲突）/ 111 命令 / 468 离线测试；干净构建 verify_wheel 通过
  ▼
3.0.0b3 ── 工程治理：只读复用 RetrieveContent 缓存、OVF lease 有界等待、HTTP 泄漏修复、清理 build/egg-info/pycache；命令契约不变 / 111 命令 / 468 离线测试
  ▼
3.0.0b4 (当前) ── 迁移 vcenter-ops v2.0「克隆模版」标准流程：新增 `deploy clone-template`（独立 TemplateClone Provider，单次原子 CloneSpec：改网+静态IP Linux定制+CPU/内存+磁盘仅扩容+有IP即开机；host 省略走 DRS；MoRef 精确寻址）/ 112 命令 / 496 离线测试（Provider 级 13 + Engine 流程级 15）；干净构建 verify_wheel 76 模块通过；Tools 就绪交 `vm wait-tools`（不阻塞确认引擎）；MCP 叶子、clean-slate、迁移工具仍未做（属 rc/搁置）
  ▼  门：真机重跑 D08/D15/D16/D25b，并由用户在真实 vCenter 完成 14 项实机验收（6.5/6.7/7.0/8.0）；clone-template 另需验静态 IP 定制/DVPG/DRS 放置/Linux Guest 引导
3.0.0rc          ── 门：7.0/8.0 实机核心矩阵通过；Windows 密钥后端；TTL/扫描/通知默认关
  ▼
3.0.0 GA         ── 门：6.5/6.7/7.0/8.0 逐领域矩阵 + PRD AC-01–29 + 覆盖率≥85%
```

## 更新规则

- 每次注册 / 离线验收 / 实机验收状态变化，先更新 `COMMAND-ACCEPTANCE.md`，再同步本看板数字与日期。
- 不得把"已注册"或"模拟测试通过"写作"已验收"；延期项单列，不计入完成。
- 本看板不授权真实 vCenter 写入；真实操作按具体环境与对象另行授权。
