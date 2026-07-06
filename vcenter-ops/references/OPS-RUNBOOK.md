# vcenter-ops 运维 Runbook（v2.0 精简版）

> 单人 IT 管理员场景，涵盖日常巡检、备份、故障处理与灾难演练。

## 1. 目录结构

| 路径 | 作用 | 建议策略 |
|---|---|---|
| `config.yaml` | 连接 + 权限映射 | 提交 Git，敏感字段仅保留 `password_ref` |
| `.env` | 密码/密钥引用 | 严禁提交 Git，权限 chmod 600 |
| `data/audit/*.jsonl` | 审计日志 | 归档保留 ≥ 180 天 |
| `data/cache/` | 库存缓存 | 长期占位，异常时可清空重建 |
| `data/tasks/*.json` | 任务/历史 | 供 `history` action 使用 |
| `data/locks/` | VM 锁 | 异常残留可手工清理 |
| `data/secrets/` | 加密存储 | 与 `.master.key` 一起备份 |
| `logs/` | 运行日志 / cron 输出 | 定期切割 |

## 2. 风险分级

| 级别 | Action | 处理策略 |
|---|---|---|
| 🔴 高危 | `delete_vm` | 精确名称/IP + `--confirmed` + 审计留痕 |
| 🟡 中危 | `power_vm`、`migrate`、`reconfigure`、`guest_exec`、`batch`、`ttl`、`secret set/delete`、`plan execute/rollback`、`template register/convert` | 建议先 `--dry-run` |
| 🔵 低危 | `list_all`、`get_vm`、`quota`、`events`、`export`、`snapshot list`、`history`、`preset`、`ip_pool available`、`datastore`、`audit_report`、`plan list` | 可随意执行 |

## 3. 日常巡检

```bash
python3 scripts/healthcheck.py           # 环境自检：依赖 / 配置 / 缓存 / 锁 / 加密 / vCenter 连通性
python3 scripts/handler.py --action list_all
python3 scripts/handler.py --action quota --cluster CL01
python3 scripts/handler.py --action events --minutes 60
```

## 4. 备份

至少每周把以下内容备份到独立位置：

- `.env`（密码环境变量）
- `data/secrets/` + `data/.master.key`（加密存储和主密钥；缺一不可）
- `config.yaml`
- `presets/`
- `data/audit/`

推荐一条 tar 备份：

```bash
tar czf /var/backups/vcenter-ops-$(date +%F).tgz \
  .env config.yaml presets \
  data/secrets data/.master.key data/audit
```

## 5. 灾难演练

1. 在测试机上把备份还原到新的 Skill 目录。
2. `python3 scripts/healthcheck.py --no-vcenter` 确认加密存储/依赖 OK。
3. 打开 `.env`，把密码替换为演练账号。
4. `python3 scripts/handler.py --action list_all` 确认可以正常读到清单。
5. `python3 scripts/handler.py --action audit-query` 抽查审计日志完整性。

## 6. 常见故障

| 现象 | 排查 | 处理 |
|---|---|---|
| `handler.py` 报连接失败 | `healthcheck.py` 显示 vCenter 项 ❌ | 核对 host/user/`password_ref`；检查 `.env` 权限 |
| 密码解密失败 | `data/.master.key` 丢失 | 从备份还原；否则用 `secret --secret-action rotate` 重建 |
| VM 锁残留 | `data/locks/` 有过期文件 | 确认没有进程后手工删除锁文件 |
| 删除被危险词拦截 | 提示 "confirm_required" | 精确指定 `--hostname`，重跑并加 `--confirmed` |
| 缓存脏 | 库存显示与真实 vCenter 不一致 | `python3 scripts/cache_manager.py --refresh` |

## 7. 推荐 cron

```cron
# TTL 到期清理（每小时）
0 * * * * cd /path/to/vcenter-ops && python3 scripts/handler.py --action ttl --ttl_action cleanup >> logs/ttl.log 2>&1

# 每日审计报表
0 3 * * * cd /path/to/vcenter-ops && python3 scripts/handler.py --action audit_report --export_format html --output logs/audit-$(date +\%F).html >> logs/audit-cron.log 2>&1

# 每 30 分钟刷新一次库存缓存
*/30 * * * * cd /path/to/vcenter-ops && python3 scripts/cache_manager.py --refresh >> logs/cache.log 2>&1
```

## 8. 密钥轮换

```bash
# 备份主密钥
cp data/.master.key /var/backups/master.key.$(date +%F)

# 轮换主密钥（自动重新加密所有 secret）
python3 scripts/handler.py --action secret --secret-action rotate

# 再次备份
cp data/.master.key /var/backups/master.key.$(date +%F).new
```
