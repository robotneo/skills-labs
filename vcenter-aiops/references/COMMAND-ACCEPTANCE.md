# vCenter AIops 运维命令台账（Ops Ledger）

> 口径：只服务 **vCenter / VMware 日常运维高频动作**。
> **已交付命令不再作为待办台账**（仅在末尾"已交付能力速查"列出，无验收勾选）；低频/治理/禁用类整体**搁置**（可恢复，未删除）。
> 完整 150 项 PRD 台账已归档：`docs/archive/COMMAND-ACCEPTANCE-FULL-150-20260929.md`。
> 更新日期：2026-10-10（14 项待做已全部完成注册 + 离线验收，版本进入 3.0.0b1；仅待用户实机验收）。地面真值来自 `vcenter-aiops capabilities list`。

## 对账总览（数字自洽）

| 分类 | 数量 | 说明 |
| --- | --: | --- |
| PRD 必需叶子 | 150 | PRD 1.2 第 6.2–6.4 节 |
| 延期 | 1 | `cluster add-host`（严格指纹策略，用户批准延期） |
| 当前实施范围 | 149 | = 已交付 + 搁置（原 14 项待做已全部转为已交付） |
| ✅ 已交付（含本轮 14 项） | **108** | 注册 + 离线验收通过；实机验收待用户进行 |
| ⏸ 搁置 | **41** | 低频/治理/接口类，见文末，暂不做 |

校验：108 + 41 = 149；+ 延期 1 = 150。

## 状态图例

- **注册**：叶子进入命令注册表。**离线验收**：独立 help/schema + 成功 / 拒绝 / 恢复三类测试与审查证据（本轮完整套件 **456 项通过**）。
- **实机验收**：vSphere 6.5/6.7/7.0/8.0 实测并记录 build/权限/许可证/Tools。**14 项全部未实机实测**，仍标 `not_lab_verified`。
- 模拟通过不等于实机验收；GA 前必须由用户在真实环境完成 14 项的实机勾选。

---

# ✅ 本轮完成的 14 项（注册 ☑ / 离线验收 ☑ / 实机待验收 ☐）

## A. 资产与排障只读（3）

| # | 命令 | 用途与边界 | 关键参数 | 风险/确认 | 注册 | 离线验收 | 实机 |
| --: | --- | --- | --- | --- | :-: | :-: | :-: |
| A1 | `inventory export` | 导出资产清单到文件，复用 list 过滤/分页；json/csv，外部字段转义 | `--file`、`--format` | 只读；不覆盖已有文件/符号链接 | ☑ | ☑ | ☐ |
| A2 | `events list` | 查事件排障，按精确对象/时间/类型过滤；权限不足与无事件区分 | `--vm-id\|--host-id`、`--since`、`--event-type`、`--limit` | 只读；分页 cursor | ☑ | ☑ | ☐ |
| A3 | `quota check` | 变更前容量预检（CPU/内存/存储），只预检不预留；缺字段返回 unavailable | `--cluster-id\|--host-id\|--datastore-id`、请求量 | 只读；不臆测容量 | ☑ | ☑ | ☐ |

## B. IP 地址管理（3）

> ping 不通**只作信号**；探测不可用返回 inconclusive，绝不等于空闲。作用域+地址唯一，跨隔离网络可同址。

| # | 命令 | 用途与边界 | 关键参数 | 风险/确认 | 注册 | 离线验收 | 实机 |
| --: | --- | --- | --- | --- | :-: | :-: | :-: |
| B1 | `ip check` | 汇总资产占用 + 本地租约 + ping 三路信号 | `--address`、`--scope` | 只读；不判空闲 | ☑ | ☑ | ☐ |
| B2 | `ip available` | 仅在有正向空闲证据时返回 true，否则 inconclusive，不自动分配 | `--address`、`--scope` | 只读；保守判定 | ☑ | ☑ | ☐ |
| B3 | `ip expire` | 处理过期且无未知部署关联的租约；默认列出，精确租约 ID 才释放 | `--apply`、`--lease-id` | 释放走确认边界 | ☑ | ☑ | ☐ |

## C. 模板与设备部署（2）

| # | 命令 | 用途与边界 | 关键参数 | 风险/确认 | 注册 | 离线验收 | 实机 |
| --: | --- | --- | --- | --- | :-: | :-: | :-: |
| C1 | `deploy ova` | 本地 OVA 部署；校验描述符/磁盘/网络映射/容量；NFC lease 驱动上传；默认不开机 | `--source`、`--resource-pool-id`、`--host-id`、`--folder-id`、`--datastore-id`、`--network-mapping` | 拒绝路径穿越；中断核对不盲清 | ☑ | ☑ | ☐ |
| C2 | `deploy ovf` | OVF 描述符目录 + 引用磁盘部署；其余同 OVA | `--source-dir`、同上 | 同上 | ☑ | ☑ | ☐ |

## D. Guest 操作系统操作（5）

> 显式区分 Linux/Windows，要求 Guest 自带 Python 3.10+（不自动安装）；输出只作数据，不保存 Guest 密码；结果绑定本次 run-id，不仅凭 PID。

| # | 命令 | 用途与边界 | 关键参数 | 风险/确认 | 注册 | 离线验收 | 实机 |
| --: | --- | --- | --- | --- | :-: | :-: | :-: |
| D1 | `vm guest-exec-output` | 执行并采集 stdout/stderr/exit_code（各 ≤64 KiB base64） | `--vm-id`、program/args | 预览包装器；未知不重发 | ☑ | ☑ | ☐ |
| D2 | `vm guest-output` | 只读已有运行输出，不重新执行；缺失/损坏返回不确定 | `--run-id` | 只读；不冒充成功 | ☑ | ☑ | ☐ |
| D3 | `vm guest-upload` | 上传文件到 Guest，校验路径/覆盖/容量（≤4 MiB） | 本地路径、Guest 路径、覆盖策略 | 拒绝路径穿越 | ☑ | ☑ | ☐ |
| D4 | `vm guest-download` | 从 Guest 下载文件（≤4 MiB），校验路径/容量/端点 | Guest 路径、本地路径 | 拒绝路径穿越 | ☑ | ☑ | ☐ |
| D5 | `vm guest-customize` | 声明式定制 hostname/IP/掩码/网关/DNS；提交与"实际配置完成"分别报告 | `--vm-id`、`--spec-file` | 不隐式开机；可重启 | ☑ | ☑ | ☐ |

## E. 告警（1）

| # | 命令 | 用途与边界 | 关键参数 | 风险/确认 | 注册 | 离线验收 | 实机 |
| --: | --- | --- | --- | --- | :-: | :-: | :-: |
| E1 | `alarm reset` | `ClearTriggeredAlarms` 自 6.7 提供；AlarmFilterSpec 无实体/告警 ID，typeEntity 仅 VM/Host；预览绑定精确告警集合 | `--entity-type vm\|host`、`--statuses` | **6.5 写前拒绝**；范围扩大即 plan_stale；不扩大范围 | ☑ | ☑ | ☐ |

14 项均已注册并通过离线验收（完整套件 456 项通过）。实机列为 ☐：等用户在真实 vCenter 6.5/6.7/7.0/8.0 验收后勾选，再进入正式版（GA）。

---

# ⏸ 搁置清单（41，暂不做，可恢复）

> 以下为 PRD 范围内但非日常运维高频，或属治理/接口/一次性能力。需要时从归档台账恢复，不计入当前完成。

- **TTL（5）**：`vm set-ttl`、`cancel-ttl`、`list-ttl`、`expired-ttl`、`cleanup-ttl`。
- **旧数据迁移（3）**：`migration inspect`、`apply`、`verify`（2.0→3.0 切换前一次性工具，非日常运维；切换时再启用）。
- **扫描（4）**：`scan run`、`status`、`history`、`report`。
- **调查聚合（5）**：`attention`、`summary`、`investigate vm/host/datastore`。
- **调度（9）**：`schedule create/list/show/update/enable/disable/delete`、`scheduler run/status`。
- **通知（10）**：`notify channel-add/list/update/delete`、`enable/disable`、`test`、`send`、`history`、`retry`。
- **MCP（1）**：`mcp serve`（接口能力，非运维动作）。
- **组合编排（4）**：`deploy batch-clone`、`deploy batch`、`vm guest-provision`、`vm clean-slate`（高频时可提前恢复；原子能力已在待做/已交付中覆盖）。

**延期（1，不开放占位）**：`cluster add-host`（严格指纹安全策略，需独立设计与批准）。

---

# ✅ 已交付能力速查（108，非待办，无验收勾选）

> 仅供运维参考"现在能做什么"；不再作为待验收台账。

- **运行环境（4）**：`version`、`doctor`、`capabilities list`、`capabilities show`。
- **连接配置（6）**：`profile list/show/add/update/delete/test`。
- **资产（2）**：`inventory list`、`inventory export`。
- **VM 查询（2）**：`vm list`、`vm inspect`。
- **电源（5）**：`vm power-on`、`shutdown`、`power-off`、`reset`、`suspend`。
- **VM 变更（6）**：`vm create`、`clone`、`rename`、`reconfigure`、`migrate`、`delete`。
- **快照（4）**：`vm snapshot-list/create/revert/delete`。
- **模板（4）**：`template list/inspect`、`deploy mark-template`、`template convert`。
- **部署（6）**：`deploy template`、`linked-clone`、`iso`、`unmount-iso`、`deploy ova`、`deploy ovf`。
- **Guest（9）**：`vm guest-exec`、`guest-exec-output`、`guest-process-status`、`guest-output`、`guest-download`、`guest-upload`、`guest-customize`、`tools-status`、`wait-tools`。
- **集群（6）**：`cluster list/info/create/delete/remove-host/configure`。
- **主机（3）**：`host info`、`maintenance-enter`、`maintenance-exit`。
- **告警（3）**：`alarm list`、`alarm acknowledge`、`alarm reset`。
- **事件与容量（2）**：`events list`、`quota check`。
- **存储（4）**：`datastore list/inspect/browse/scan`。
- **IP（6）**：`ip list`、`reserve`、`release`、`check`、`available`、`expire`。
- **预设（6）**：`preset list/show/save/delete/from-history/from-vm`。
- **缓存（3）**：`cache status/refresh/invalidate`。
- **历史（2）**：`history list/show`。
- **审计（2）**：`audit list/export`。
- **密钥（4）**：`secret list/set/delete/rotate`。
- **策略（2）**：`policy inspect/check`。
- **任务（5）**：`task list/inspect/wait/cancel/reconcile`。
- **编排（12）**：`plan create/show/list/validate/apply/reconcile/rollback/archive`、`batch power-on/shutdown/power-off/reset`。

## 更新规则

- 实机验收：由用户在真实 vCenter 完成 14 项勾选并记录 build/权限/Tools 后，版本由 beta 进入正式版（GA）。
- 搁置/延期项恢复时，从本台账或归档重新列入待做。
- 最终验收仍需覆盖 PRD AC-01–29、覆盖率≥85%、隔离安装与跨平台；命令/测试数量不替代这些门槛。
