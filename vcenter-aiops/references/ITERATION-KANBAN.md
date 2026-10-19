# vCenter AIops 迭代看板

> 单一事实来源：`references/COMMAND-ACCEPTANCE.md`（台账）、`references/IMPLEMENTATION-STATUS.md`（阶段记录）、`docs/prd/vcenter-ops-3.0-prd.md`（PRD 1.2，已审批）。
> 本看板只做**状态呈现与排期**，不改变 PRD 范围；数字以台账注册核对日期为准。
> **下一大版本任务**：41 项整体搁置 + `cluster add-host` 延期共 **42 条未实施叶子**，已按模块整理为迭代任务清单 `references/ROADMAP-3.1-unimplemented.md`（建议目标 3.1.0；若并入 3.0 完整交付则按 AC-29 收尾），含每模块命令/参数/AC 映射/依赖/P1–P3 顺序/DoD。

| 项目 | 值 |
| --- | --- |
| 产品 / 命令 | vCenter AIops / 唯一公共命令 `vcenter-aiops` |
| 当前版本 | **3.0.0b6**（execution-beta，候选版；在 b5 基础上合入 `vm delete` 受控通道与交互式创建/克隆向导配套件，并统一版本号；非 GA，待真机复测 D08/D15/D16/D25b 及克隆验收） |
| 看板更新 | 2026-10-19（发版 **3.0.0b6**：统一版本号四落点 `__init__.py`/manifest/pyproject/SKILL frontmatter 及各 references 版本头，COMMAND-INTERACTION 按 `__version__` 脚本重生成；本版相对 b5 合入此前未提交的两批工作——①`vm delete` 受控通道替代全局 fail-closed：新增 consumers.py 全 vCenter 磁盘链消费者扫描（运行态+快照树），仅在"无本地依赖+干净扫描+显式 `--allow-shared-datastore` 担保+plan apply 双重确认"齐全时才 Destroy_Task，枚举不可得/发现消费者/预览后新增消费者均写前拒绝（dependency_present/dependency_unproven，exit4），扫描证据入 binding 并 submit 重校验；snapshot revert/delete 与带存储 migrate 仍全局全禁；新增 test_delete_guarded_channel；②"交互式创建/克隆向导"配套件（**零源码、命令仍 112**）：`references/wizard/size-presets.yaml`（默认 standard 4C/8G/100G，磁盘只扩不缩）、`references/wizard/CLONE-RUNBOOK.md`、`references/wizard/LAB-TEST-CHECKLIST.md`（跨对话自包含实机演练手册，密码经 0600 /tmp/.vcpw 注入不入库）；默认环节为 `deploy clone-template` 模板自定义克隆，`vm create` 空白机降为显式旁路；业务网段（CIDR/掩码/网关/可分配范围/scope）**不固化文件**，首次对话提供一次、会话内记住复用，每台具体 IP 仍重新三路取证（曾误建 references/wizard/ip-pools.yaml 固定台账，已删除）；SKILL.md 新增向导节并补 frontmatter 触发意图。816+ 离线测试通过、pyflakes 0，命令特权核权/二次确认/"未知不重发"语义不变）。前次 2026-10-18（b5）：rename/snapshot 名称远端读取前收口、target_busy 退出码统一 4、state.db/audit 导出/debug.log 符号链接加固、datastore 搜索 submit 写前拒绝与写后未知分流（785 测试）。COMMAND-INTERACTION --check 通过 |
| 安装状态 | 已安装用户级 `~/.workbuddy/skills/vcenter-aiops/`（b1 安全审计后）；b4 发布后 rsync 同步，2026-10-16 再同步 M1–M4、S1 分平台 marker 锁与 D1–D3 四 src 修复。**D-1 风险分级核查时标准 skills 目录暂未检出 vcenter-aiops 代码副本**（仅数据 home `~/Library/Application Support/vcenter-aiops`），平台重装后以仓库源码为准；运行经 `VCENTER_AIOPS_PYTHON` 指向隔离 venv |
| PRD 必需叶子 | 150 |
| 当前实施范围 | 149（`cluster add-host` 经用户批准方案 A 延期，不计入完成） |
| 已交付（地面真值） | **108 / 149（72%）**（PRD 必需口径；另额外注册 `deploy clone-template` 对齐 vcenter-ops 克隆模版标准流程，不属原 150 必需叶） |
| 剩余 41 的拆分 | **搁置 41**（原 14 项运维待做已全部转为已交付，待实机验收） |
| 台账口径（2026-10-10 beta） | `COMMAND-ACCEPTANCE.md`：14 项 A–E 组全部注册 ☑ + 离线 ☑，实机列待用户勾选 ☐；41 项低频/治理维持搁置；完整 150 项归档于 `docs/archive/COMMAND-ACCEPTANCE-FULL-150-20260929.md` |
| 离线测试 | **552 项通过**（截至 2026-10-16；风险分级 D-1 净增 27：test_risk_classification 13 + test_risk_gate_cli 14；既有 handler 级 CLI 测试按非 TTY 自动化语义加 `--yes` 适配，不增删方法） |
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
3.0.0b4 ── 迁移 vcenter-ops v2.0「克隆模版」标准流程：新增 `deploy clone-template`（独立 TemplateClone Provider，单次原子 CloneSpec：改网+静态IP Linux定制+CPU/内存+磁盘仅扩容+有IP即开机；host 省略走 DRS；MoRef 精确寻址）/ 112 命令 / 496 离线测试（Provider 级 13 + Engine 流程级 15）；干净构建 verify_wheel 76 模块通过；Tools 就绪交 `vm wait-tools`（不阻塞确认引擎）；MCP 叶子、clean-slate、迁移工具仍未做（属 rc/搁置）
  ▼
b4 安全加固（同版本，2026-10-16）── 只读静态审计（严重0/高危0/中危4/低危4）后修复 M1 ping 地址 ipaddress 收口、M2 已存数据目录权限收紧、M3 写路径补 TLS 关闭告警、M4 新增 requirements.lock（227 sha256，--require-hashes）；命令契约/特权/版本不变 / 509 离线测试（+13 回归）；wheel verify 76 模块、全新 venv 哈希锁安装+冒烟通过、安装副本同步
  ▼
b4 S1 依赖 CVE 修复（同版本，2026-10-16）── 运行时性能/安全深度检查（0/0/中3/低4/健康9）后修唯一可立即修复项：cryptography 48.0.1 命中 CVE-2026-69247/69248/69249（仅 X.509/PKCS#7，项目仅用 Fernet 不可达）；因 49+ 上游停发 Intel-Mac wheel，requirements.lock 改分平台 marker（50.0.2 非Intel-Mac 59 hash / 48.0.1 Intel-Mac 49 hash，正向 De Morgan marker，286 sha256），pyproject 放宽到 <51；OSV 复查 50.0.2=0 公告；Intel-Mac 全新 venv 选中 48.0.1 universal2 wheel 纯二进制安装、Fernet 往返、篡改 hash 被拒、509 测试全过；P1（轮询空转写库）/P2（异常无落盘）/P3–P6 留待 rc
  ▼
b4 真机验收缺陷 D1–D3 修复（同版本，2026-10-16，依据 8.0.3 build-24091160 缺陷单）── 共性根因=离线假桩与真机返回形态不一致；**D1（P0）** vm create 真机 4 个等价 VirtualDiskOption 致"磁盘能力不可确定"，抽共享 `hardware.select_new_disk_option()` 按能力（唯一 FlatVer2 backing+persistent+thin 可判定）选择替代基数断言，0 合格才失败、多等价确定取首，vm create 与 reconfigure 扩容共用；**D2** 悬空 cluster MoRef 首次取数抛 ManagedObjectNotFound → `cluster_not_found/exit4`（`clusters._existing_cluster()`）；**D3** batch/电源悬空 vm 同理 → `vm_not_found/exit4` 带具体 ID（`mutations.vm()`），异对象 fault 不吞、畸形 ID 仍 target_invalid、删除后置 verify 仅 delete 判 True；安全前提（Guest 唯一/控制器基数/支持集/不缩容/二次确认）全保留；命令契约/特权/版本不变 / 112 命令 / 520 离线测试（+11 真机形态回归）；安装副本同步
  ▼  门：真机重跑 D08/D15/D16/D25b，并由用户在真实 vCenter 完成 14 项实机验收（6.5/6.7/7.0/8.0）；clone-template 另需验静态 IP 定制/DVPG/DRS 放置/Linux Guest 引导；D1–D3 需在 8.0.3 真机 dry-run 复测（vm create 任意放置 VMFS/vSAN、cluster delete 悬空 ID、batch 悬空 vm_id）
  ▼
b4 风险分级与分级管控（同版本，2026-10-16，阶段 D-1）── 新增 `domain/risk.py` 集中三级模型，112 命令映射为 **low 54 / medium 43 / high 15**；低直跑、敏感（权限·数据外发·系统配置·对外发送·终止）说明影响范围+确认、不可逆（删除/清空/覆盖/批量/终止）确认前列精确目标（资源·路径·范围·数量）并拒通配/过宽范围。修正两类历史错标：4 个 batch 批量电源（原 read_only，CLI 自动确认门不认 orchestration 致无交互确认入口）与 15 个直接生效本地敏感写（secret/profile/preset/export 等原零确认）。CLI 新增 `direct_effect_gate()` 与全局/叶子 `--yes/-y`（非 TTY 未授权 exit4、目标不精确即使 --yes 也 exit2）；batch 终端走 枚举每台→digest→`BATCH-<n>` 二次确认；引擎型写仍以 digest/DESTROY 为确认值、不建第二套状态机。命令签名/特权核权/未知不重发不变；552 离线测试（+27：分级 13 + CLI 门 14）；SKILL.md 与 COMMAND-INTERACTION.md 同步；MCP 服务面未来须复用同一策略
  ▼
3.0.0b5 (2026-10-18) ── 安全/性能全面扫描后加固 + 去重矩阵收口 + b5 代码体检第二批：**L-6** 降级锁 POSIX 路径补 O_NOFOLLOW+fstat（拒符号链接/非常规/多硬链接，新增 `locking.open_lock`）；**L-9** profile `os.replace` 后 best-effort fsync 父目录（崩溃不丢目录项）；**L-3** 补 `operations.target` 与 `datastore_searches(profile,created desc)` 幂等索引（CREATE INDEX IF NOT EXISTS，claim 忙等/按 profile 历史列表不再随数据量全表）；OVA 解压超限块改为**延迟落盘**（超限额成员不写盘、连空壳都不留）。**去重矩阵①**：六份 currentSession+HasPrivilegeOnEntity 核权（ovf_deploy/hosts/clusters/template_clone/mutations/guest，含 guest 一次性特权缓存）统一委托新增 `mor.check_privileges(content,entity,required,denied,unable,...)`，收敛机制（getattr 防御/callable/等长/严格 `is True`），保留各点领域文案与 clusters 历史"session 缺失误→permission_denied/4"覆盖；**去重矩阵③**：clusters/template_clone/creation/placement 四份名称正则合并为新增 `domain/naming.valid_name`（1–80、禁 `/\\%`+控制符+边缘空白+零宽不可见，内部空格仍合法），placement 顺带收紧到同一词表；快照名是用户标签另设 `valid_snapshot_name`（允许 `/\\%`，仅禁控制符/零宽/边缘空白）。**b5 只读体检第二批（2026-10-18）**：vm rename `new_name`/snapshot-create `snapshot_name` 改为任何远端读取前确定性收口（name_invalid/2）；claim 两处 target_busy 退出码统一显式 4；符号链接加固三处——state.db 已存在文件连接前 O_NOFOLLOW+fstat 校验（`state_db_unsafe/3`，宽松权限 fchmod 收紧 0600 而非拒绝，非常规/他人属主/多硬链接拒绝）、audit export 发布前 lstat 拒符号链接/特殊文件（`export_target_unsafe/3`，普通已存在仍 export_exists/2）、debug.log 追加改 O_NOFOLLOW 私有 fd（写后不再路径 chmod，轮转遇链接放弃）；datastore 搜索 submit 写前四查失败包成 `SubmissionRejected`（确定性 failed/exit4/不重发），写后不可证明仍 reconciliation_required/6，且只有显式 SubmissionRejected 才判确定性失败（裸 OperationError 负向用例仍归未知）。不改命令签名/特权集/二次确认/"未知不重发"；版本四落点（`__init__.py`/manifest/pyproject/SKILL frontmatter）+ 交互文档（脚本按 `__version__` 重生成，`--check` 幂等）一致；785 离线测试通过、pyflakes 0（去重矩阵②datacenter_of、④mor.require，及体检项 #3 计划级超时预算/#4 poll 异常分类，待后续批次）
  ▼
3.0.0b6 (当前，2026-10-19) ── 合入 `vm delete` 受控通道 + 交互式创建/克隆向导配套件（**零新增原子命令，注册表仍 112**），统一发版版本号。**受控删除通道**：新增 `providers/vsphere/consumers.py` 全 vCenter 磁盘链消费者扫描（运行态 VM+模板 + 快照树），替代全局 fail-closed；仅当"无本地依赖 + 干净扫描 + 显式 `--allow-shared-datastore` 担保 + plan apply 双重确认"四条件齐全才下发 Destroy_Task；枚举不可得/发现消费者/预览后新增消费者均写前拒绝（`dependency_present`/`dependency_unproven`，exit4），扫描证据入 binding 并在 submit 时重校验；snapshot revert/delete 与带存储 migrate 维持全局全禁；新增 test_delete_guarded_channel。**向导配套件（编排层，非命令）**：默认环节定为 `deploy clone-template` 模板自定义克隆（克隆 spec 内改名/规格/放置/网络/可选静态 IP 开机定制），`vm create` 空白全必填机降为用户显式要求的旁路；新增 `references/wizard/size-presets.yaml`（inherit/standard 默认 4C/8G/100G/compact/large/xlarge，磁盘只扩不缩）、`CLONE-RUNBOOK.md`（只到预览、人工确认后 plan apply，命令选项脚本比对注册表零偏差，ip release/task id 为位置参数）、`LAB-TEST-CHECKLIST.md`（跨对话自包含实机手册，密码经 0600 `/tmp/.vcpw` 注入不入库，网段首次给、会话内复用，每台 IP 仍三路取证）；业务网段**不固化文件/不跨对话**（曾误建 ip-pools.yaml 已删）；SKILL.md 新增向导节并在 frontmatter 补触发意图。不改命令签名/特权集/二次确认/"未知不重发"；版本四落点 + references 版本头一致，COMMAND-INTERACTION 按 `__version__` 重生成 `--check` 通过；816+ 离线测试通过、pyflakes 0
  ▼
3.0.0rc          ── 门：7.0/8.0 实机核心矩阵通过；Windows 密钥后端；TTL/扫描/通知默认关
  ▼
3.0.0 GA         ── 门：6.5/6.7/7.0/8.0 逐领域矩阵 + PRD AC-01–29 + 覆盖率≥85%
  ▼
3.1.0（建议）    ── 消化 PRD 未实施 42 叶子（41 搁置 + add-host 延期）：MCP 服务面 + 数据迁移（P1）→ 扫描/通知/调度/add-host（P2）→ 调查/TTL/组合编排（P3）；任务清单与 AC 映射见 references/ROADMAP-3.1-unimplemented.md
```

## 更新规则

- 每次注册 / 离线验收 / 实机验收状态变化，先更新 `COMMAND-ACCEPTANCE.md`，再同步本看板数字与日期。
- 不得把"已注册"或"模拟测试通过"写作"已验收"；延期项单列，不计入完成。
- 本看板不授权真实 vCenter 写入；真实操作按具体环境与对象另行授权。
