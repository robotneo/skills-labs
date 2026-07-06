# CHANGELOG

## v2.0.0 — 单人管理员精简

> 目标：将 Skill 收敛到单人 IT 管理员实际使用的能力面，砍掉多人协作/企业治理/规模化智能相关的枝叶。

### ❌ 移除

- 审批工作流（approval_manager / approval_policy）与相关 CLI（`approval`, `approval_policy`）
- RBAC（role_manager）与相关 CLI（`rbac`）
- 变更窗口（change_window）与相关 CLI（`change_window`）
- Webhook 订阅（webhook_subscriber / event_bus）与相关 CLI（`webhook`）
- 智能化四件套：metrics_collector / recommender / recommend_plus / anomaly_detector / capacity_forecaster / alarm_poller（`metrics`, `recommend`, `anomaly`, `forecast`）
- 资产监控与 Prometheus SD 集成：asset_registry / monitoring_integrator
- 企业级安全门禁：batch_guard / preflight_gate / danger_token / evidence_collector / secret_audit
- 交付流水线：delivery_pipeline / delivery_state / post_clone_init / batch_clone（`delivery`, `post_init`, `batch_clone`）
- 其它：async_runner / inventory_cache_index / quota_enforcer / observability_loop.sh
- 对应 references 与 tests 一并清理

### ✅ 保留

- 生命周期：`clone_vm` / `power_vm` / `snapshot` / `reconfigure` / `migrate` / `delete_vm` / `guest_exec`
- 巡检：`list_all` / `get_vm` / `events` / `quota` / `export` / `audit_report` / `history` / `preset` / `datastore` / `template` / `ip_pool`
- 编排：`plan` / `batch` / `ttl`
- 安全：`secret` / `danger`

### 🔧 兼容处理

- `executor.py` 内部保留 `bus_publish` no-op 实现，历史事件发布语句无需删除。
- `ttl_manager.py` 已有 event_bus 缺失时的 fallback，无需改动。
- `SKILL.md` 版本更新到 `2.0.0`，权限分级与 action 表同步刷新。


## v1.2.0 — 2026-05-22 — 可观测性增强

> Phase 6：打通全运行期事件、接入 vCenter 原生告警、一键健康自检。

### ✨ 新增

| 模块 | 文件 | 说明 |
|------|------|------|
| Alarm 轮询 | `scripts/alarm_poller.py` | 拉取 vCenter 原生告警，转发到 event_bus，去重持久化 |
| 健康自检 | `scripts/healthcheck.py` | 10 项检查（依赖/配置/缓存/锁/加密/连通性） |

### 🔧 改进

- **executor.py**
  - `set_vm_power` → 发布 `vm.power.on/off/reset`
  - `reconfigure_vm` → 发布 `vm.reconfigured`
  - `migrate_vm` → 发布 `vm.migrated`
  - `remove_vm` → 发布 `vm.deleted`（含快照信息）
- **ttl_manager.cleanup_expired** → 发布 `ttl.expired` / `ttl.cleaned`
- 所有运行期变更现在都能被 Webhook 订阅

### 📊 集成验证记录（真实 vCenter）

```
✅ vCenter 连通 8.0.3
✅ 推荐引擎 Top-3 评分 93.9
✅ 采集 62 条指标（cluster + ds）
✅ 抓到 3 条原生告警
✅ 异常检测 真实检出：43.59-data 使用率 96.1% > 90%
✅ RBAC 拦截 guest 删除 / 放行 list_all
```

### 🧪 pytest 覆盖

24 个单测测试全过（`tests/`），覆盖：

- ip_pool / preset / danger / rbac / change_window / secret / capacity / anomaly

### 📖 文档补全

- `SKILL.md` 补充 v1.1-v1.4 章节
- `references/USER-GUIDE.md` 274 行命令手册
- `references/OPS-RUNBOOK.md` 213 行运维手册（cron/备份/灾难演练）

---

## v1.4.0 — 2026-05-22 — 智能化

> Phase 5：在 v1.3 安全护栏之上，引入资源推荐 / 异常检测 / 容量预测。

### ✨ 新增

| 模块 | 文件 | 说明 |
|------|------|------|
| 指标采集 | `scripts/metrics_collector.py` | 集群 CPU/内存 + DS 容量采集，JSONL 按日切分，支持 dry-run |
| 推荐引擎 | `scripts/recommender.py` | 4 因子加权评分（负载/容量/IP/亲和），Top-N 输出 |
| 异常检测 | `scripts/anomaly_detector.py` | 均值+kσ 动态阈值 + 硬阈值兜底 + 发布 alarm 事件 |
| 容量预测 | `scripts/capacity_forecaster.py` | 线性回归预测剩余天数，发布 quota.breach 事件 |

### 🔧 handler 接入

- `--action metrics`（collect / query / cleanup）
- `--action recommend`（联推 preset + 亲和分析）
- `--action anomaly`（扫描全量指标）
- `--action forecast`（预测趋势）

### 📊 设计要点

- **推荐评分公式**：`0.4 * cluster_load + 0.3 * ds_free + 0.2 * ip_avail + 0.1 * affinity`
- **异常双阈值**：动态阈值主控正常波动，硬阈值拦截极端场景
- **预测 R²**：输出拟合度，R² < 0.5 说明趋势不明显
- **资源水位底座**：独立启动，上层异常/预测可只读

### 🧪 测试覆盖

| 模块 | 验证场景 |
|------|---------|
| `metrics_collector` | dry-run 生成 + 真实 vCenter 集群/DS 采集 |
| `recommender` | 真实 vCenter 5 集群 / 57 DS，返回 Top-5 评分 93.7 |
| `anomaly_detector` | 15 个样本 + 1 个突刺，准确识别 |
| `capacity_forecaster` | 14 天线性增长，R²=1.0，预测 7 天后超限 |

---

## v1.3.0 — 2026-05-22 — 安全合规

> Phase 4：生产准入门槛。密码加密、RBAC、危险词、审批策略、变更窗口。

### ✨ 新增

| 模块 | 文件 | 说明 |
|------|------|------|
| 密码加密 | `scripts/secret_manager.py` | Fernet 对称加密，主密钥三级加载 + 从 .env 迁移 + 密钥轮换 |
| RBAC | `scripts/role_manager.py` | guest/operator/admin 三级内置角色 + 用户绑定 |
| 危险词校验 | `scripts/danger_validator.py` | 25+ 危险模式 + 白名单 + 确认 TTL |
| 审批策略 | `scripts/approval_policy.py` | auto / single / multi 三级路由 + 默认 4 条策略 |
| 变更窗口 | `scripts/change_window.py` | allow / block / blackout 三重规则 + 白名单 |

### 🔧 handler 多重拦截

所有需 vCenter 连接的操作依序经过：

1. **RBAC** 检查用户权限
2. **变更窗口** 检查是否允许变更
3. **危险词** 检查目标是否需二次确认（`--confirmed` 可表示已确认）
4. **审批策略** 检查是否需审批
5. **配额**（v1.1 已有）
6. 原有 VM 并发锁

### 🔑 使用指引

```bash
# 1) 迁移 .env 密码到加密存储
python3 scripts/secret_manager.py migrate --dry-run    # 预览
python3 scripts/secret_manager.py migrate              # 执行

# 2) 启用 RBAC（config.yaml 设 rbac.enabled: true）
python3 scripts/handler.py --action rbac --rbac-action bind --rbac-user alice --rbac-role operator

# 3) 启用变更窗口（仅举例，需在 config.yaml 填 allow/block_windows）
# change_window.enabled: true + block_windows: ...

# 4) 扫描危险操作
python3 scripts/handler.py --action danger --danger-action scan --danger-target prod-mysql-master
```

### 📊 影响面

- **默认全关闭**：仅在 config.yaml 显式启用后生效，不影响现有工作流
- **拦截状态可见**：`blocked` / `confirm_required` / `approval_required`
- **--actor 参数**：标记谁在操作（默认 agent）
- `secrets.json` + `.master_key` 文件 chmod 600

---

## v1.1.0 — 2026-05-22 — 规模化 + 协作能力

> Phase 3：在 Phase 2 的用户体验之上，打通批量场景 / 事件订阅 / 资源护栏。

### ✨ 新增

| 模块 | 文件 | 说明 |
|------|------|------|
| 批量克隆 | `scripts/batch_clone.py` | 多 VM 并行克隆、任务限额、失败不阻断、结果汇总 |
| IP 池 | `scripts/ip_pool.py` | CIDR/范围/单IP 解析 + 预留持久化 + ping 跳过 |
| 事件总线 | `scripts/event_bus.py` | 进程内发布/订阅，支持通配符词（`vm.*`） |
| Webhook 订阅 | `scripts/webhook_subscriber.py` | HTTP / 钉钉机器人（含签名）异步投递，持久化配置 |
| 配额硬限制 | `scripts/quota_enforcer.py` | 克隆前单VM/集群/DS 三重拦截，越限报 `QuotaExceeded` |
| 审计报表 | `scripts/audit.py` 扩展 | summarize() + format_report_markdown() + export_report() |

### 🔧 改进

- **executor.clone_vm_advanced**
  - 克隆前调用 `enforce_clone_quota`，越限直接拒绝
  - 克隆成功/失败发布 `vm.created` / `clone.failed` 事件到总线
  - 错误日志统一使用 `format_error_oneline`

- **preset_manager**
  - 新增 `save_preset()` / `delete_preset()` / `save_from_history()`
  - CLI 子命令：save / save-from-history / delete
  - 预设名校验（字母开头，限定字符集）
  - 仅保存可重用字段（过滤 hostname/ip 等临时参数）

- **handler.py 接入**
  - 新增 action: `batch_clone`、`ip_pool`、`webhook`、`audit_report`
  - `preset` action 增加 `--preset-action save/save-from-last/delete/show`
  - 启动时自动挂载 Webhook 订阅到 event_bus

### 📊 影响面

- **向后兼容**：所有新能力默认启用但可禁
  - `quota_enforce.enabled: false` 可关闭配额拦截
  - 未配置 Webhook 时事件总线仅需加法，无外部投递
  - 批量克隆默认并行度 3，单次上限 50 台
- **新增依赖**：无（仅用 Python 标准库与已有的 PyYAML）
- **新增数据目录**:
  ```
  data/
  ├── ip_reservations.json   # IP 预留池
  └── webhooks.json          # Webhook 订阅配置
  ```

### 🧪 测试覆盖

| 模块 | 自测结果 |
|------|----------|
| `ip_pool` | ✅ parse/available/allocate/release/reservations/cleanup CLI |
| `batch_clone` | ✅ generate_clone_specs dry-run（3 台 IP 自动分配） |
| `event_bus` | ✅ 发布/通配符匹配/历史 |
| `webhook_subscriber` | ✅ add/list/remove/投递重试/钉钉签名 |
| `quota_enforcer` | ✅ per_vm 越限抦截三项 |
| `audit.summarize` | ✅ markdown 报表生成 |
| `handler` 4 个新 action | ✅ 全部联调通过 |

### 📝 使用示例

```bash
# 批量克隆：从 IP 池自动分配 5 台 dev-small
python3 scripts/handler.py --action batch_clone \
  --preset dev-small --count 5 \
  --template Ubuntu20.04-2c4g60g-lvm2 \
  --dc DC --cluster CL --ds DS01 --network VLAN10 \
  --ip-pool "10.0.10.20-10.0.10.50" \
  --name-prefix web- --workers 3

# IP 池查询 + 分配
python3 scripts/handler.py --action ip_pool --ip-action available --ip-spec "10.0.10.0/24"
python3 scripts/handler.py --action ip_pool --ip-action allocate --ip-spec "10.0.10.0/24" --count 3

# Webhook 订阅（钉钉机器人）
python3 scripts/handler.py --action webhook --webhook-action add \
  --webhook-name ops-bot --webhook-url "https://oapi.dingtalk.com/robot/send?access_token=XXX" \
  --webhook-secret SECXXX --webhook-mode dingtalk \
  --webhook-topics "vm.created" "vm.deleted" "clone.failed"

# 从历史记录存为预设
python3 scripts/handler.py --action preset --preset-action save-from-last \
  --preset-name web-standard --from-vm web-test01

# 生成近 30 天审计报表
python3 scripts/handler.py --action audit_report --report-days 30 \
  --export_format markdown --output /tmp/audit-month.md
```

### ⏭️ 下一步（v1.2 预告）

- 批量失败项一键重试（`--retry-failed`）
- 事件发布扩展到广义塬与闲忙变更、告警、TTL 到期
- 预设包市场（跨环境同步）

---

## v1.0.0 — 2026-05-22 — 用户体验 + 关键功能补强

> Phase 2：在 Phase 1 稳定性底座之上，补强用户体验与关键功能。

### ✨ 新增

| 模块 | 文件 | 说明 |
|------|------|------|
| Tools 就绪检测 | `scripts/tools_checker.py` | VMware Tools 状态查询 + 阻塞等待 + 中文修复建议 |
| 错误友好化 | `scripts/error_dictionary.py` | pyVmomi 异常 → 中文描述 + 修复建议，覆盖 25+ 异常类型 |
| 历史复用 | `scripts/history_manager.py` | 复用 data/tasks/ 的克隆参数，支持"按上次配置克隆" |
| 预设包 | `scripts/preset_manager.py` + `presets/*.yaml` | @dev-small / @dev-medium / @prod-large 一键规格 |
| 进度推送 | `scripts/progress_reporter.py` | 统一进度回调 + 去抖 + 多通道（stdout/日志/钉钉） |

### 🔧 改进

- **executor.py**
  - `clone_vm_advanced` 新增 `wait_tools` / `tools_timeout` 参数，克隆且开机后自动等待 Tools 就绪 + IP 分配
  - `clone_vm_advanced` 新增 `on_progress` 参数，克隆进度可实时推送
  - `clone_vm_advanced` 自动将克隆参数写入 task `meta`（供 history_manager 复用）
  - `guest_exec` 使用 `assert_tools_ready` 替换硬编码检查，输出修复建议
  - `_wait_for_task` 新增 `meta` 参数，所有操作可携带元信息
  - 异常日志使用 `format_error_oneline` 输出中文友好提示

- **预设包系统**
  - `presets/dev-small.yaml`: 2C/4G/40G 开发标配
  - `presets/dev-medium.yaml`: 4C/8G/80G 中等规格
  - `presets/prod-large.yaml`: 8C/16G/200G 生产规格（强制二次确认）

### 📊 影响面

- **向后兼容**：所有新参数均有默认值，原有调用无需修改
  - `wait_tools=True` 默认启用，克隆开机 VM 会额外等待 Tools（最多 300s）
  - `wait_tools=False` 可禁用（不影响无 IP 克隆场景）
- **新增依赖**：PyYAML（用于预设包解析，`pip install pyyaml`）

### 🧪 测试覆盖

| 模块 | 自测结果 |
|------|----------|
| `tools_checker` | ✅ 状态枚举 / 中文标签 / self-check |
| `error_dictionary` | ✅ pyVmomi 异常匹配 / 关键词回退 / MRO 链查找 |
| `history_manager` | ✅ 列表/查询/格式化 CLI |
| `preset_manager` | ✅ 加载/合并/apply CLI |
| `progress_reporter` | ✅ 去抖/进度条/milestone 推送 |
| `executor` import | ✅ 全模块 import 联调 |

### ⏭️ 下一步（Phase 3 预告）

- 批量克隆（多 VM 并行 + 限额）
- 自定义预设包（用户可在 UI 中创建/保存）
- Webhook 事件订阅（VM 状态变更自动通知）

---

## v0.9.0 — 2026-05-21 — 稳定性底座

> Phase 1：稳定性优先，所有后续增强都依赖这层。

### ✨ 新增

| 模块 | 文件 | 说明 |
|------|------|------|
| 重试策略 | `scripts/retry_policy.py` | 通用 retry 装饰器 + 错误分类 + 友好错误格式化 |
| 任务管理器 | `scripts/task_manager.py` | vCenter Task 的提交/查询/等待/取消，支持持久化与进度回调 |
| 并发锁 | `scripts/lock_manager.py` | 基于 fcntl 的 VM 级并发锁，支持 TTL 与强制解锁 |
| 自动回滚 | `scripts/rollback_manager.py` | 上下文管理器风格的回滚机制，LIFO 顺序 |

### 🔧 改进

- **client.py**
  - `connect()` 接入 `@retry` 装饰器：网络/超时错误自动指数退避重试（默认 3 次：1s/3s/9s + ±30% 抖动）
  - 认证失败、SSL 错误等不可恢复错误立即抛出，不浪费时间
  - 错误信息使用 `format_friendly_error` 输出中文友好提示
- **executor.py**
  - `_wait_for_task` 改造为 TaskManager 调度，所有任务可查询历史记录（`data/tasks/*.json`）
  - `remove_vm` 接入 `VMLock`，删除前自动创建保留快照（`VC_SKIP_PRE_DELETE_SNAPSHOT=1` 可跳过）
  - `set_vm_power` 接入 `VMLock` + 自动失效缓存
  - `clone_vm_advanced` 包裹 `RollbackContext`：克隆失败自动清理半成品 VM
  - 写操作完成后调用 `cache_mgr.invalidate_after_action()`，自动失效相关 section
- **cache_manager.py**
  - 新增 `CACHE_TTL`（默认 300s，可通过环境变量 `VC_CACHE_TTL` 调整）
  - 新增 `cache_age_seconds()`、`invalidate_cache()`、`invalidate_after_action()`
  - 写操作类型 → 失效 section 映射表（clone/delete/power/reconfigure 等）

### 🛡️ 安全增强

- **删除前自动快照**：所有 `delete_vm` 操作自动打一个 `pre-delete-YYYYMMDD-HHMMSS` 快照，作为最后的回滚兜底
- **并发锁**：同一 VM 同时只能被一个写操作持有，防止删除/电源/克隆冲突
- **锁 TTL 自动清理**：进程崩溃后残留的锁会在 TTL 过期后被自动 GC

### 🧪 测试覆盖

| 模块 | 自测结果 |
|------|---------|
| `retry_policy` | ✅ 重试成功 / 不可重试错误立即抛出 |
| `lock_manager` | ✅ 获取/重复加锁拒绝/自动释放 |
| `rollback_manager` | ✅ 异常回滚 LIFO 顺序 / commit 后跳过 |
| `cache_manager` | ✅ 失效函数与映射表 |
| `task_manager` | ✅ list/持久化 |

### 📊 影响面

- **向后兼容**：原 `_wait_for_task` 用法不变，内部转 TaskManager 调度
- **配置可选**：所有新机制默认启用，可通过环境变量降级
  - `VC_CACHE_TTL=0`：禁用缓存自动过期
  - `VC_SKIP_PRE_DELETE_SNAPSHOT=1`：跳过删除前快照
- **新增依赖**：无（仅使用 Python 标准库）

### 🗂️ 新增数据目录

```
data/
├── tasks/              # 任务执行记录（JSON，自动清理 7 天前）
├── locks/              # 并发锁文件（.lock + .json 元信息）
└── vc_session_cache.json  # 已存在
```

### ⏭️ 下一步（Phase 2 预告）

- VMware Tools Ready 检测
- 错误友好化（pyVmomi 异常 → 人话 + 修复建议）
- 交互简化（参数预设包 `@dev-small`）
- 历史复用（`按上次配置克隆`）
- 进度反馈（克隆百分比实时推送）
