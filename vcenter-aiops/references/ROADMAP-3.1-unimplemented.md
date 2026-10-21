# 下一大版本（3.1.0）未实施模块迭代任务清单

> 状态：规划待办（backlog），尚未写任何实现代码。版本号 **3.1.0 为建议目标**（3.0.0 GA 之后的首个功能版本）；若决定把这些模块并入 3.0 完整交付，则按 PRD AC-29 作为 3.0 收尾——两种排期共用本清单，命令与验收口径不变。
> 真值来源：PRD 1.2 `docs/prd/vcenter-ops-3.0-prd.md`（6.2–6.4 命令目录、6.7 TTL 授权、第 8 阶段、第 7/10 节 AC）、完整台账 `docs/archive/COMMAND-ACCEPTANCE-FULL-150-20260929.md`、当前注册表 `src/vcenter_aiops/application/registry.py`（b5 实测 112 条）。
> 已用脚本核对：下列 **41 条命令在 b5 注册表中均不存在**（注册表集合差集），另 1 条 `cluster add-host` 为用户批准延期；不含任何已实现命令。

## 0. 范围与数量对账

- PRD 原始 150 叶子 → 实施范围 149（`cluster add-host` 延期 1）。
- 已交付 108（+3 额外 datastore search-* 恢复入口不抵扣 +1 clone-template = 当前注册 112）。
- **本清单待实施 = 41 条整体搁置 + 1 条延期 = 42 条叶子**，另加若干非命令形态 GA 项（第 12 节）。

| 模块（工作流） | 叶子数 | PRD 阶段 | 建议批次 | 关键 AC |
|---|---:|---|---|---|
| M1 TTL 生命周期 | 5 | 阶段6 | P3 | AC-28 |
| M2 2.0→3.0 数据迁移 | 3 | 阶段7 | P1（rc/切换前一次性） | AC-12 |
| M3 扫描 | 4 | 阶段6 | P2 | AC-26 |
| M4 调查 / 洞察 | 5 | 阶段6 | P3 | AC-26/29 |
| M5 调度 | 9 | 阶段6 | P2（依赖 M3） | AC-26 |
| M6 通知 | 10 | 阶段6 | P2（被 M3/M5 消费） | AC-27 |
| M7 MCP 服务面 | 1 | 阶段7 | P1 | AC-13/20/22 |
| M8 组合编排 | 4 | 阶段5/6 | P3 | AC-19/23/28 |
| M9 集群 add-host（延期） | 1 | 阶段5 | P2 | AC-24 |
| **合计命令** | **42**（M1–M8 搁置 41 + M9 延期 1） | | | |

## 1. 全局不可变约束（每个模块必须遵守）

1. 所有写仍走“预览 → 计划 → 确认 → apply → 核对”，复用现有预检、特权核权（`mor.check_privileges`）、任务身份与审计；新模块不得自建第二套确认/状态机。
2. 结果不明的写保持 reconciliation_required/6，凭原任务核对，绝不自动重发。
3. 默认安全：TTL 默认只提醒不删除；通知默认关；调度为**可选**进程（不要求普通 CLI 用户起后台服务）；扫描只读、绝不调用变更 API。
4. 通知仅 Webhook + 适配接口；PRD 明确不自动集成 DWS/飞书/企业微信专有 API。
5. MCP 逐叶子映射（`vm power-on → vm_power_on`），禁止万能 `execute(action, params)`；凭据/安装/迁移等管理命令默认不上 MCP；stdio stdout 仅协议、日志走 stderr。
6. 不恢复 handler.py / `--action`，不注册 vmware-aiops / vcenter-ops 别名。
7. 每条叶子交付同步：注册表条目 + 独立 help/schema + 成功/拒绝/恢复离线测试 + capabilities 状态 + COMMAND-INTERACTION/FEATURE-CATALOG 重生成 + 风险分级与确认门；禁止用 NotImplemented/桩/仅模拟通过冒充完成（AC-29）。

---

## 2. M1 — VM TTL 生命周期（5 叶子，P3，AC-28）

PRD 6.2/6.7：设置、取消、到期清单；默认仅提醒；清理只消费**提前持久化、可撤销的对象级授权**，不是每轮由 Agent 临时确认。

| 待实现命令 | 用途 | 必要参数 / 条件 | 风险·限制 |
|---|---|---|---|
| `vm set-ttl` | 为精确 VM 登记到期时间与策略（默认 remind） | `vm_id`、到期时间/TTL；策略默认 remind；cleanup 需显式对象级授权 | 中；写本地授权 + 只读校验 VM 存在 |
| `vm cancel-ttl` | 撤销 TTL 与对应清理授权 | `vm_id` | 中；撤销后 cleanup 必须不可再执行 |
| `vm list-ttl` | 列出已登记 TTL | profile/状态过滤 | 低；本地只读 |
| `vm expired-ttl` | 列出已到期对象（只报告） | 可选 profile | 低；不清理 |
| `vm cleanup-ttl` | 对已授权且到期对象执行清理计划 | 精确对象范围 + 授权 + 二次确认 | 高不可逆；默认生成固定计划交 plan apply；授权缺失/被撤/基线失效即停 |

要点：新增可撤销、绑定 profile+vm_id+授权版本的对象级授权表，与 operations/计划引擎打通；cleanup 与 `vm delete` 共用严格链接磁盘依赖保护（在“无外部链接磁盘全局证据”解决前同样不得真删）。旧 2.0 TTL 迁移只导入为提醒（见 M2）。

## 3. M2 — 2.0→3.0 数据迁移（3 叶子，P1 / rc 切换前一次性，AC-12）

PRD 6.4/第 9 节：检查、迁移、验证分离；只操作本地数据、不写 vSphere；dry-run→备份→转换→验证→切换。

| 待实现命令 | 用途 | 必要参数 / 条件 | 风险·限制 |
|---|---|---|---|
| `migration inspect` | 预检旧 config/预设/.env/密钥/SQLite/TTL/确认，产出差异报告 | `--source <旧目录>` 必填 | 只读源；不打印密钥值 |
| `migration apply` | 备份后转换写入新结构 | 显式授权 + dry-run 通过 + 备份路径 | 高（本地数据）；幂等、不产生重复记录；失败不破坏源 |
| `migration verify` | 校验迁移结果、计数、抽样比对 | 迁移会话标识 | 只读；缺主密钥不得声称成功 |

映射规则：config/预设严格校验、未知字段入报告；.env/密钥需显式授权且不打包主密钥与密文；TTL 仅导入提醒；缓存重建；旧危险词确认不迁移为新授权；使用中 SQLite 不直接复制单文件；保留源备份直到用户决定清理。

## 4. M3 — 扫描（4 叶子，P2，AC-26）

PRD 6.2：多 Profile 只读采集与结果查询，不自动修复。

| 待实现命令 | 用途 | 必要参数 / 条件 | 风险·限制 |
|---|---|---|---|
| `scan run` | 对选定 profile/范围一次性只读采集 | scope/profile；`request_id` | 只读；多目标部分失败结构化返回 |
| `scan status` | 查看扫描作业状态 | `scan_id` | 只读 |
| `scan history` | 列历史扫描 | profile/分页 | 本地只读 |
| `scan report` | 生成离线 HTML / 结构化报告 | `scan_id`；输出文件 | 落盘不覆盖、字段转义 |

要点：作业可重启、并发重叠去重/串行、部分失败隔离；与调度解耦，可独立手动运行。

## 5. M4 — 调查 / 洞察（5 叶子，P3）

PRD 6.2：基于已采集证据聚合，不驱动写；支持离线 HTML。

| 待实现命令 | 用途 | 必要参数 / 条件 | 风险·限制 |
|---|---|---|---|
| `attention` | 全局需关注项聚合（风险/告警/容量/异常） | profile 范围 | 只读；标注证据来源与时间 |
| `summary` | 环境总体摘要 | profile 范围 | 只读 |
| `investigate vm` | 单 VM 证据聚合 | `vm_id` 或 one-of 选择器 | 无证据标“不确定”，不臆断 |
| `investigate host` | 单主机证据聚合 | `host_id`/name | 只读 |
| `investigate datastore` | 单数据存储证据聚合（容量/挂载/孤儿线索） | `datastore_id`/name | 孤儿仅提示、不自动删 |

依赖 M3 采集结果（也可降级实时只读取数，但须标注来源）。

## 6. M5 — 调度（9 叶子，P2，依赖 M3，AC-26）

PRD 6.2/第 11 节：持久化作业 + 可选调度进程；OS 服务部署单独说明。

| 待实现命令 | 用途 | 必要参数 / 条件 | 风险·限制 |
|---|---|---|---|
| `schedule create` | 创建定时作业（承载 scan/报告） | 名称、cron/间隔、载荷命令与参数 | 中；载荷白名单仅只读/安全叶子 |
| `schedule list` | 列作业 | 分页/profile | 只读 |
| `schedule show` | 查作业定义与状态 | `schedule_id` | 只读 |
| `schedule update` | 修改作业 | `schedule_id` + 字段 | 中 |
| `schedule enable` | 启用 | `schedule_id` | 中 |
| `schedule disable` | 停用 | `schedule_id` | 中 |
| `schedule delete` | 删除作业 | `schedule_id` | 高（本地），精确确认 |
| `scheduler run` | 手动驱动调度循环 / 前台可选进程 | 可选 `--once` | 长时运行非单 JSON 语义 |
| `scheduler status` | 查进程/下次触发/最后结果 | 无 | 只读 |

要点：错过触发 catch-up 策略、并发重叠防重入、崩溃重启可恢复；运行日志写 stderr/JSONL，绝不混入 MCP stdout；载荷默认仅 scan/report 等只读动作，不调度不可逆写。

## 7. M6 — 通知（10 叶子，P2，AC-27）

PRD 6.2：默认关闭；持久化 outbox、限次退避、去重；Webhook + 适配接口；`notify test` 也属性外发。

| 待实现命令 | 用途 | 必要参数 / 条件 | 风险·限制 |
|---|---|---|---|
| `notify channel-add` | 新增通道（Webhook/适配） | 名称、类型、目的地、凭据引用 | 高；默认 enabled=false |
| `notify channel-list` | 列通道（脱敏） | 无 | 只读 |
| `notify channel-update` | 改通道 | `name` + 字段 | 高 |
| `notify channel-delete` | 删通道 | `name` | 高，精确确认 |
| `notify enable` | 启用通知 | 范围/通道 | 中 |
| `notify disable` | 停用通知 | 范围/通道 | 中 |
| `notify test` | 发送授权测试消息 | 通道 | 中；真实外发、默认关、二次确认 |
| `notify send` | 手动发送授权 payload | 通道 + 模板/事件引用 | 高；不泄露凭据 |
| `notify history` | 发送历史 | 分页 | 只读 |
| `notify retry` | 失败记录限次重试 | 精确记录 id | 中；去重/退避 |

安全：默认零外发；仅配置端点收到授权 payload；失败进 outbox 可查可限次重试；URL scheme/重定向 host 校验（复用 OVF/guest HTTP 硬化范式）；不内置 DWS/飞书/企微专有 API。

## 8. M7 — MCP 服务面（1 叶子，P1，AC-13/20/22）

| 待实现命令 | 用途 | 必要参数 / 条件 | 风险·限制 |
|---|---|---|---|
| `mcp serve` | 可选 stdio MCP 服务，逐叶子映射业务工具 | 无（stdio） | 与 CLI 共用同一应用处理器，不经 shell 包装 |

要点：按会话/领域加载工具，避免一次暴露全部；管理命令默认不暴露并在能力表说明；确认与结果契约同 CLI，MCP 调用不自行代表用户授权；复用 `domain/risk.py` 分级门；现有 `mcp=False` 叶子默认不上 MCP，逐条评估。

## 9. M8 — 组合编排（4 叶子，P3，AC-19/23/28）

PRD 6.5：组合命令默认生成固定计划交 plan apply，复用注册原子处理器，不绕开预检/权限/任务/审计。

| 待实现命令 | 用途 | 必要参数 / 条件 | 风险·限制 |
|---|---|---|---|
| `deploy batch-clone` | 按清单批量克隆/部署 | 规格/对象清单 + `request_id` | 高批量；展开多原子步骤逐目标可审阅 |
| `deploy batch` | 通用批量部署组合计划 | 规格文件 | 高；不隐式开机/改网，除非步骤显式声明 |
| `vm guest-provision` | 上传→执行→验证在计划中展开 | VM、来宾凭据引用、规格 | 中/高；不改写用户脚本，返回真实退出码 |
| `vm clean-slate` | 回滚到已存在基线快照 | 唯一 `vm_id` + 基线快照 + 二次确认 | 高不可逆；必须显式基线，不隐式删除重建；受链接磁盘依赖保护 |

## 10. M9 — `cluster add-host`（延期 1 叶子，P2，AC-24）

| 待实现命令 | 用途 | 必要参数 / 条件 | 风险·限制 |
|---|---|---|---|
| `cluster add-host` | 独立主机加入集群 | `cluster_id`、主机地址、主机凭据引用、指纹/目标身份 | 高；采用用户批准的安全方案 A（严格指纹策略）；校验证书与目标身份；凭据走 secret 引用；许可不足不写入 |

## 11. 建议实施顺序与依赖

- **P1（rc/GA 前置，打通协议与切换）**：M7 `mcp serve`（利于自动化验收）；M2 数据迁移（2.0→3.0 切换前一次性）。
- **P2（运维增益，有内部依赖）**：M3 scan（只读采集底座）→ M6 notify（先建通道/outbox，再接事件）→ M5 schedule（消费 scan/notify）；M9 add-host 可并行插入。
- **P3（建立在采集/编排成熟后）**：M4 investigate/attention/summary；M1 TTL（依赖对象级授权与删除证据闭环）；M8 组合编排（clean-slate 依赖链接磁盘证据）。
- 依赖关键路径：M3 → M5；M3/M5 → M6 事件；删除证据/对象级授权 → M1 cleanup、M8 clean-slate。

## 12. 非命令形态的 GA 硬门槛（与上述并行，AC-01–29）

- 实机兼容矩阵（GA 门 2026-10-21 收敛）：只验 **7.0+ / 8.0+ 两条线**，真机**只逐写入动作验证**（remote_write 成功路径 + fail-closed 拒绝；只读以离线契约 + 8.0.3 只读轮次为准、不阻断），记录准确 build。6.5/6.7 无真机环境，不阻断 GA，保留 6.5/6.7/7.0/8.0=`not_lab_verified` 设计声明。
- Windows secret 密钥后端（现仅 POSIX；未完成即在该平台明确拒绝 vault）。
- 隔离安装/打包验收（AC-01/14）、核心分支覆盖率 ≥85%、发布包无缓存/测试/真实环境数据。
- 快照恢复后依赖步骤自动推演；计划补偿扩充（当前仅覆盖改名 + 可表示的 CPU/内存字段）；放置预检升级为完整兼容性试验。
- R-6：vcenter-guard Hook 识别 `vcenter-aiops`；R-7：切换验收后删除旧 vcenter-ops 目录，发布包校验无旧 handler/别名。
- 完成 PRD AC-01–29 全量验收（重点 AC-12 迁移、AC-20 MCP 原子映射、AC-23 部署制备、AC-24 集群六类、AC-26 扫描调度、AC-27 通知、AC-28 TTL/Clean Slate、AC-29 完整范围）。

## 13. 完成定义（每个叶子的 DoD）与对账

单条命令“完成”须同时满足：
1. 注册到 `registry.COMMANDS`（含参数 schema、风险级、特权、MCP/异步标记），`capabilities show` 可见；
2. 独立 help/schema + 成功 / 拒绝 / 恢复三类离线测试，全量 `unittest discover` 绿、pyflakes 0；
3. 复用统一预检 / 特权核权 / 确认门 / 审计 / 任务核对，不引入第二套执行边界；
4. 重生成 `COMMAND-INTERACTION.md`（脚本 `--check` 通过）并更新 `FEATURE-CATALOG.md`；
5. 远端叶子在 6.5/6.7/7.0/8.0 标注真实验证状态（离线通过不等于实机验收）；GA 真机门只要求 7.0+/8.0+ 两条线对写入动作给出真机结论，只读不阻断，6.5/6.7 无真机环境保留 `not_lab_verified`。

**对账方法（防止漏做或虚报）**：以 PRD 150 叶子为全集，用脚本对比 `registry.COMMANDS`；本文件 42 条全部转为已注册且离线验收后，PRD 命令范围即 100% 落地（再叠加第 12 节非命令门槛方可宣告完整版本）。每期迭代结束更新本文件状态列与 `ITERATION-KANBAN.md`，不得把“已注册/模拟通过”写作“已实机验收”。

> 备注：本清单为下一大版本的任务输入，不改变 b5 任何现有命令签名与语义；实际排期（3.1.0 或并入 3.0 收尾）以用户决策为准。
