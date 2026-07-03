# vCenter Ops 用户操作手册

## 1. 快速开始

```bash
# 测试连接
python3 scripts/healthcheck.py

# 全量巡检
python3 scripts/handler.py --action list_all

# 查询单 VM
python3 scripts/handler.py --action get_vm --hostname web-test01
```

## 2. 克隆 VM

### 2.1 单台克隆

```bash
python3 scripts/handler.py --action clone_vm \
  --template Ubuntu20.04-2c4g60g-lvm2 --hostname web01 \
  --dc 数据中心 --cluster MD1200 --ds 43.7-data --network VLAN10 \
  --cpu 2 --memory 4 --disk 60 \
  --ip 10.0.0.10 --mask 255.255.255.0 --gw 10.0.0.1
```

### 2.2 使用预设（推荐）

```bash
# 查看预设
python3 scripts/handler.py --action preset

# 应用预设（CPU/内存/磁盘自动套用）
python3 scripts/handler.py --action clone_vm --preset dev-small \
  --hostname web02 --template Ubuntu20.04-2c4g60g-lvm2 \
  --dc 数据中心 --cluster MD1200 --ds 43.7-data --network VLAN10 \
  --ip 10.0.0.11
```

### 2.3 按上次配置克隆

```bash
# 完全复用上次参数，只换名字+IP
python3 scripts/handler.py --action clone_vm --from-last \
  --hostname web03 --ip 10.0.0.12
```

### 2.4 批量克隆

```bash
python3 scripts/handler.py --action batch_clone \
  --preset dev-small --count 5 \
  --template Ubuntu20.04-2c4g60g-lvm2 \
  --dc 数据中心 --cluster MD1200 --ds 43.7-data --network VLAN10 \
  --ip-pool "10.0.10.20-10.0.10.50" \
  --name-prefix web- --workers 3
```

## 3. 智能化辅助

### 3.1 资源推荐

```bash
# 给出 Top-3 集群/宿主机/DS 推荐
python3 scripts/handler.py --action recommend \
  --cpu 4 --memory 8 --disk 100 \
  --recommend-count 2 --recommend-prefix web- --recommend-top 3
```

### 3.2 异常检测 / 容量预测

```bash
# 异常扫描（自动推送 alarm 事件）
python3 scripts/handler.py --action anomaly --metric-days 7

# 容量预测（按 90% 阈值）
python3 scripts/handler.py --action forecast --forecast-threshold 0.9
```

### 3.3 指标采集（建议 cron 每 5min）

```bash
python3 scripts/handler.py --action metrics    # 单次采集（连 vCenter）
python3 scripts/handler.py --action metrics --metrics-action query --metric-type ds_used --metric-days 7
```

## 4. 安全合规

### 4.1 密码加密

```bash
# 从 .env 迁移到加密存储
python3 scripts/secret_manager.py migrate --dry-run    # 预览
python3 scripts/secret_manager.py migrate              # 执行

# 手动加密
python3 scripts/handler.py --action secret --secret-action set \
  --secret-key VCENTER_PASSWORD --secret-value 'mypass'

# 主密钥轮换
python3 scripts/secret_manager.py rotate
```

### 4.2 RBAC

```yaml
# config.yaml 启用
rbac:
  enabled: true
  default_role: guest
```

```bash
python3 scripts/handler.py --action rbac --rbac-action bind \
  --rbac-user alice --rbac-role operator

# 检查权限
python3 scripts/handler.py --action rbac --rbac-action check \
  --rbac-user alice --rbac-target-action delete_vm
```

### 4.3 危险词与确认

```bash
# 扫描
python3 scripts/handler.py --action danger --danger-action scan \
  --danger-target prod-mysql-master

# 危险目标删除：先报错要求确认，再用 --confirmed 重试
python3 scripts/handler.py --action delete_vm --hostname prod-mysql-master \
  --actor alice                            # 报错 confirm_required
python3 scripts/handler.py --action delete_vm --hostname prod-mysql-master \
  --actor alice --confirmed                # 通过
```

### 4.4 变更窗口

```yaml
# config.yaml 启用
change_window:
  enabled: true
  block_windows:
    - {weekdays: [0,1,2,3,4,5,6], start: "00:00", end: "06:00", reason: "夜间静默期"}
  blackout_dates: ["2026-01-01", "2026-02-15"]
```

### 4.5 审批策略

```yaml
approval_policy:
  enabled: true
  # 默认 4 条策略（生产/会签/删除等），可在此追加
```

## 5. 事件推送

### 5.1 Webhook（钉钉）

```bash
python3 scripts/handler.py --action webhook --webhook-action add \
  --webhook-name ops-bot \
  --webhook-url "https://oapi.dingtalk.com/robot/send?access_token=***" \
  --webhook-secret 'SEC***' \
  --webhook-mode dingtalk \
  --webhook-topics "vm.created" "vm.deleted" "clone.failed" "alarm" "quota.breach"
```

### 5.2 已支持的事件主题

| 主题 | 触发时机 |
|------|----------|
| `vm.created` | 克隆成功 |
| `vm.deleted` | 删除成功 |
| `vm.reconfigured` | 硬件变更 |
| `vm.power.on` / `vm.power.off` | 电源变更 |
| `vm.migrated` | vMotion 完成 |
| `clone.failed` | 克隆失败 |
| `ttl.expired` / `ttl.cleaned` | TTL 到期 |
| `alarm` | 异常检测或 vCenter 原生告警 |
| `quota.breach` | 容量预测预警 |

### 5.3 vCenter 原生告警轮询

```bash
# 立刻拉一次（建议 cron 每 5min）
python3 scripts/alarm_poller.py poll

# 列出当前所有活动告警（不去重）
python3 scripts/alarm_poller.py list
```

## 6. 运维与诊断

### 6.1 健康自检

```bash
python3 scripts/healthcheck.py                # 含 vCenter 连通性
python3 scripts/healthcheck.py --no-vcenter   # 仅本地
python3 scripts/healthcheck.py --json         # JSON 输出
```

### 6.2 审计报表

```bash
# HTML 报表（推荐）
python3 scripts/handler.py --action audit_report --report-days 30 \
  --output /tmp/audit-month.html

# Markdown
python3 scripts/handler.py --action audit_report --report-days 7 \
  --export_format markdown --output /tmp/audit-week.md
```

### 6.3 删除操作（高危）

```bash
# 1) 普通删除（自动打 pre-delete 快照）
python3 scripts/handler.py --action delete_vm --hostname dev-tmp01

# 2) 跳过删除前快照（节省时间）
VC_SKIP_PRE_DELETE_SNAPSHOT=1 \
  python3 scripts/handler.py --action delete_vm --hostname dev-tmp01
```

## 7. 推荐 cron 任务

```cron
# 每 5 分钟采集指标
*/5 * * * * cd /root/.openclaw/workspace-infraops/skills/vcenter-ops && python3 scripts/handler.py --action metrics >> logs/metrics.log 2>&1

# 每 5 分钟轮询 vCenter 告警
*/5 * * * * cd /root/.openclaw/workspace-infraops/skills/vcenter-ops && python3 scripts/alarm_poller.py poll >> logs/alarm.log 2>&1

# 每 30 分钟跑异常检测
*/30 * * * * cd /root/.openclaw/workspace-infraops/skills/vcenter-ops && python3 scripts/handler.py --action anomaly >> logs/anomaly.log 2>&1

# 每天凌晨 2 点容量预测
0 2 * * * cd /root/.openclaw/workspace-infraops/skills/vcenter-ops && python3 scripts/handler.py --action forecast >> logs/forecast.log 2>&1

# 每周一 9 点生成审计周报
0 9 * * 1 cd /root/.openclaw/workspace-infraops/skills/vcenter-ops && python3 scripts/handler.py --action audit_report --report-days 7 --output reports/audit-$(date +\%F).html

# 每日 3 点清理过期任务/指标
0 3 * * * cd /root/.openclaw/workspace-infraops/skills/vcenter-ops && python3 scripts/handler.py --action metrics --metrics-action cleanup --metrics-keep-days 30

# 每日 4 点健康自检（失败发邮件）
0 4 * * * cd /root/.openclaw/workspace-infraops/skills/vcenter-ops && python3 scripts/healthcheck.py >> logs/health.log 2>&1 || mail -s "vcenter-ops health FAIL" admin@example.com < logs/health.log
```

## 8. 主密钥备份（极其重要）

`data/.master_key` 丢失 = 所有加密密码无法解密。

```bash
# 备份到本机另一目录（chmod 600）
cp data/.master_key /root/.master_key.backup
chmod 600 /root/.master_key.backup

# 离线备份到加密 U 盘 / 内网保险柜
# 不要把它放进 git！.gitignore 已默认排除 data/
```

## 9. 故障排查 FAQ

| 现象 | 排查 |
|------|------|
| `secrets.json` 解密失败 | 检查 `data/.master_key` 是否被改 / 是否设了 `VC_MASTER_KEY` 环境变量 |
| `change_window` 拦截 | `--action change_window --window-action status` 查当前状态 |
| `confirm_required` | 加 `--confirmed` 参数重试 |
| `approval_required` | 当前审批未对接外部系统，需在 config.yaml 调整 `approval_policy.enabled: false` 或调整策略 |
| `quota` 拦截 | 检查 `config.yaml.quota_enforce.per_vm` 上限 |
| webhook 投递失败 | `--action webhook --webhook-action list` 看 last_error，检查 URL/签名 |
| Tools 等待超时 | `--no-wait-tools` 跳过；或 `--tools-timeout 600` 加长 |
