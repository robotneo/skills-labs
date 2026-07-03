# vCenter Ops 生产 Runbook

路径：`/root/.openclaw/workspace-infraops/skills/vcenter-ops`

原则：先巡检、再变更；高风险必确认；所有操作可审计、可回滚、可验证。

## 1. 快速检查

```bash
cd /root/.openclaw/workspace-infraops/skills/vcenter-ops
python3 scripts/healthcheck.py
pytest -q
./scripts/observability_loop.sh
```

验收：

```text
healthcheck 10/10
pytest 全部通过
observability_loop success
```

## 2. 关键文件

| 路径 | 作用 | 要求 |
|---|---|---|
| `config.yaml` | 主配置 | 变更前备份 |
| `.env` | 密码环境变量 | `chmod 600` |
| `data/.master_key` | 加密主密钥 | 必须离线备份 |
| `data/secrets.json` | 加密密钥库 | 与主密钥一起备份 |
| `logs/audit.log` | 审计日志 | 长期保留 |
| `data/metrics/*.jsonl` | 指标数据 | 定期清理/归档 |
| `reports/` | 报告 | 归档 |

权限修复：

```bash
chmod 600 .env data/.master_key data/secrets.json 2>/dev/null || true
chmod 700 data logs reports 2>/dev/null || true
```

## 3. 操作分级

| 级别 | 操作 | 要求 |
|---|---|---|
| 🔵 查询 | `list_all/get_vm/events/quota/export/history/preset` | 可直接执行 |
| 🟡 变更 | `clone_vm/power_vm/snapshot/reconfigure/migrate/ttl/batch` | 至少一次确认 |
| 🔴 高危 | `delete_vm/secret/rbac/approval_policy/change_window` | 二次确认 + 审批/审计 |

## 4. 创建 VM 标准流程

### 4.1 巡检

```bash
python3 scripts/cache_manager.py --refresh
python3 scripts/cache_manager.py --summary
python3 scripts/handler.py --action recommend --cpu 4 --memory 8 --disk 100 --recommend-top 3
```

### 4.2 查看模板/预设

```bash
python3 scripts/handler.py --action preset
python3 scripts/handler.py --action template --tpl_action list
```

### 4.3 IP 检查

```bash
python3 scripts/ip_scanner.py --check <IP>
```

### 4.4 克隆

```bash
python3 scripts/handler.py --action clone_vm \
  --preset dev-small \
  --hostname "<IP>-<name>" \
  --template "<template>" \
  --dc "<dc>" \
  --cluster "<cluster>" \
  --ds "<datastore>" \
  --network "<network>" \
  --ip "<IP>" \
  --mask "255.255.255.0" \
  --gw "<gateway>" \
  --power_on
```

### 4.5 验证

```bash
python3 scripts/handler.py --action get_vm --hostname "<IP>-<name>"
ping -c 3 <IP>
grep "clone_vm" logs/audit.log | tail -5
```

## 5. 删除 VM 标准流程

删除铁律：

```text
禁止删除全部/清空/通配符删除。
必须指定精确 VM 名称或 IP。
必须二次确认。
生产环境必须审批。
删除前必须留证据。
```

### 5.1 删除前取证

```bash
VM="<vm-name>"
TS="$(date +%F-%H%M%S)"
python3 scripts/handler.py --action get_vm --hostname "$VM" > "reports/predelete-${VM}-${TS}.json"
python3 scripts/handler.py --action snapshot --hostname "$VM" --snap_action list > "reports/predelete-${VM}-${TS}-snapshots.json"
python3 scripts/handler.py --action events --minutes 1440 > "reports/predelete-${VM}-${TS}-events.json"
```

### 5.2 执行删除

```bash
python3 scripts/handler.py --action delete_vm --hostname "$VM"
```

### 5.3 删除后验证

```bash
python3 scripts/handler.py --action get_vm --hostname "$VM"
grep "delete_vm" logs/audit.log | tail -10
```

## 6. 常用变更命令

### 电源

```bash
python3 scripts/handler.py --action power_vm --hostname "<vm>" --state on
python3 scripts/handler.py --action power_vm --hostname "<vm>" --state off
python3 scripts/handler.py --action power_vm --hostname "<vm>" --state reset
```

### 快照

```bash
python3 scripts/handler.py --action snapshot --hostname "<vm>" --snap_action create --snap_name "before-change-$(date +%F-%H%M)"
python3 scripts/handler.py --action snapshot --hostname "<vm>" --snap_action list
python3 scripts/handler.py --action snapshot --hostname "<vm>" --snap_action revert --snap_name "<snap>"
python3 scripts/handler.py --action snapshot --hostname "<vm>" --snap_action delete --snap_name "<snap>"
```

### 规格调整

```bash
python3 scripts/handler.py --action reconfigure --hostname "<vm>" --cpu 8 --memory 16 --disk 200
```

注意：磁盘扩容通常不可缩小。

### 迁移

```bash
python3 scripts/handler.py --action migrate --hostname "<vm>" --target_host "<esxi-host>"
```

## 7. TTL 生命周期

```bash
python3 scripts/handler.py --action ttl --ttl_action set --hostname "<vm>" --ttl_minutes 1440 --creator "<owner>"
python3 scripts/handler.py --action ttl --ttl_action list
python3 scripts/handler.py --action ttl --ttl_action cancel --hostname "<vm>"
python3 scripts/handler.py --action ttl --ttl_action cleanup
```

建议：临时测试 VM 必须设置 TTL；生产 VM 不建议自动删除。

## 8. 可观测闭环

```bash
./scripts/observability_loop.sh
python3 scripts/handler.py --action metrics --metrics-action collect
python3 scripts/handler.py --action anomaly --metric-days 7
python3 scripts/handler.py --action forecast --metric-days 60 --forecast-threshold 0.9
python3 scripts/handler.py --action recommend --cpu 4 --memory 8 --disk 100 --recommend-top 3
```

推荐 cron：

```cron
*/5 * * * * cd /root/.openclaw/workspace-infraops/skills/vcenter-ops && ./scripts/observability_loop.sh
0 3 * * * cd /root/.openclaw/workspace-infraops/skills/vcenter-ops && python3 scripts/handler.py --action metrics --metrics-action cleanup --metrics-keep-days 30 >> logs/cron-cleanup.log 2>&1
0 9 * * 1 cd /root/.openclaw/workspace-infraops/skills/vcenter-ops && python3 scripts/handler.py --action audit_report --report-days 7 --export_format html --output reports/audit-week-$(date +\%F).html >> logs/cron-audit.log 2>&1
```

验收：

```text
reports/healthcheck-latest.md 存在且 10/10
reports/anomaly-latest.json 存在
reports/forecast-latest.json 存在
data/metrics/当天日期.jsonl 行数 > 0
```

## 9. 审计和报表

```bash
grep "success" logs/audit.log | tail -20
grep "delete_vm" logs/audit.log | tail -20
python3 scripts/handler.py --action audit_report --report-days 7 --export_format html --output "reports/audit-week-$(date +%F).html"
```

保留建议：

| 数据 | 保留周期 |
|---|---|
| `logs/audit.log` | ≥180 天 |
| `reports/audit-*.html` | ≥1 年 |
| `reports/predelete-*` | ≥1 年 |
| `data/metrics/*.jsonl` | 30-180 天 |

## 10. 备份恢复

### 备份

```bash
mkdir -p /backup/vcenter-ops
TS="$(date +%F-%H%M%S)"
tar -czf "/backup/vcenter-ops/vcops-${TS}.tgz" data/ config.yaml .env logs/audit.log reports/
chmod 600 "/backup/vcenter-ops/vcops-${TS}.tgz"
```

### 恢复

```bash
tar -xzf /backup/vcenter-ops/vcops-YYYY-MM-DD-HHMMSS.tgz -C /tmp/vcops-restore
cp -a /tmp/vcops-restore/data ./
cp -a /tmp/vcops-restore/config.yaml ./
cp -a /tmp/vcops-restore/.env ./
chmod 600 .env data/.master_key data/secrets.json
python3 scripts/healthcheck.py
```

主密钥丢失：

```text
如果 data/.master_key 和备份都丢失，secrets.json 无法解密，只能重录 secret。
```

## 11. 升级流程

```bash
python3 scripts/healthcheck.py
pytest -q
TS="$(date +%F-%H%M%S)"
tar -czf "/backup/vcenter-ops/pre-upgrade-${TS}.tgz" data/ config.yaml .env SKILL.md references/OPS-RUNBOOK.md references/ scripts/ tests/

# 升级后验证
python3 -m py_compile scripts/*.py
pytest -q
python3 scripts/handler.py --help >/tmp/vcenter-ops-help.txt
python3 scripts/healthcheck.py
./scripts/observability_loop.sh
```

## 12. 故障处置

| 故障 | 命令 | 处理 |
|---|---|---|
| vCenter 不通 | `python3 scripts/healthcheck.py` | 查地址、账号、网络、443 端口 |
| 指标过期 | `python3 scripts/handler.py --action metrics --metrics-action collect` | 修复采集/cron |
| 锁残留 | `find data/locks -type f -print -exec cat {} \;` | 确认无任务后清理过期锁 |
| 审计日志大 | `tail -n 20000 logs/audit.log > /tmp/audit.log.new` | 归档后截断 |
| Webhook 失败 | `python3 scripts/handler.py --action webhook --webhook-action list` | 查 URL/secret/网络 |
| 误关机 | `power_vm --state on` | 立即恢复并通知业务 |
| 误扩容 | 记录原规格反向调整 | 磁盘不可直接缩小 |
| 误删除 | 停止后续清理 | 查备份、快照、审计、存储残留 |

## 13. 安全上线清单

- [ ] `.env`、`.master_key`、`secrets.json` 权限 600
- [ ] 主密钥已离线备份
- [ ] healthcheck 10/10
- [ ] pytest 通过
- [ ] RBAC 至少一个 admin
- [ ] 删除操作二次确认可用
- [ ] 审批策略已验证
- [ ] 变更窗口已验证
- [ ] observability_loop 已跑通
- [ ] audit_report 可生成

## 14. 日常巡检

### 每日

```bash
python3 scripts/healthcheck.py
python3 scripts/handler.py --action anomaly --metric-days 7
python3 scripts/handler.py --action events --minutes 1440
```

### 每周

```bash
python3 scripts/handler.py --action audit_report --report-days 7 --export_format html --output reports/audit-week-$(date +%F).html
python3 scripts/handler.py --action forecast --metric-days 60 --forecast-threshold 0.9
python3 scripts/handler.py --action ttl --ttl_action list
python3 scripts/handler.py --action ip_pool --ip-action reservations
```

### 每月

```bash
python3 scripts/handler.py --action audit_report --report-days 30 --export_format html --output reports/audit-month-$(date +%Y%m).html
python3 scripts/handler.py --action metrics --metrics-action cleanup --metrics-keep-days 90
pytest -q
```

## 15. 当前已知状态

```text
healthcheck: 10/10
pytest: 24 passed
metrics collect: 正常
observability_loop: 正常
已知告警：43.59-data 使用率约 96.12%，超过 90% 阈值
```
