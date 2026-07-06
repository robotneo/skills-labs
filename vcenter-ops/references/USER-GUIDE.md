# vcenter-ops 使用手册（v2.0 精简版）

> 单人 IT 管理员日常操作手册。所有命令均以 `python3 scripts/handler.py` 为入口，运行前请 `cd` 到 Skill 根目录。

## 1. 快速开始

```bash
# 环境检查（依赖 / 配置 / 缓存 / vCenter 连通性）
python3 scripts/healthcheck.py

# 全量清单
python3 scripts/handler.py --action list_all

# 查询单台 VM
python3 scripts/handler.py --action get_vm --hostname 10.0.0.11-web01
```

首次运行前把 `.env` 文件的 `chmod 600`，并在 `config.yaml` 里通过 `password_ref` 引用密码环境变量名，避免明文落盘。

## 2. 克隆 VM

### 2.1 手工指定完整参数

```bash
python3 scripts/handler.py --action clone_vm \
  --hostname 10.0.0.20-web02 \
  --template centos7-tpl \
  --dc DC01 --cluster CL01 --ds ds-ssd-01 --network VLAN10 \
  --cpu 4 --memory 8 --disk 100 \
  --ip 10.0.0.20 --mask 255.255.255.0 --gw 10.0.0.1 \
  --power_on
```

### 2.2 使用预设

```bash
# 查看预设
python3 scripts/handler.py --action preset --preset-action list

# 使用预设 dev-small，仅指定必要的差异项
python3 scripts/handler.py --action clone_vm \
  --preset dev-small \
  --hostname 10.0.0.30-app01 \
  --ip 10.0.0.30
```

### 2.3 复用上次参数

```bash
python3 scripts/handler.py --action clone_vm --from-last --hostname 10.0.0.31-app02 --ip 10.0.0.31
```

## 3. 变更操作

```bash
# 电源
python3 scripts/handler.py --action power_vm --hostname web02 --state off

# 快照
python3 scripts/handler.py --action snapshot --hostname web02 --snap_action create --snap_name pre-upgrade
python3 scripts/handler.py --action snapshot --hostname web02 --snap_action list

# 硬件热调整
python3 scripts/handler.py --action reconfigure --hostname web02 --cpu 8 --memory 16

# vMotion
python3 scripts/handler.py --action migrate --hostname web02 --target_host esxi-03

# Guest OS 命令
python3 scripts/handler.py --action guest_exec --hostname web02 \
  --cmd 'uptime' --guest-user root --guest-pwd '***'
```

## 4. 批量与编排

```bash
# 批量电源：通配符匹配 + 并发
python3 scripts/handler.py --action batch --batch_action power --pattern 'web-*' --state on

# Plan/Apply：多步事务 + 回滚
python3 scripts/handler.py --action plan --plan_action create \
  --plan_steps '[{"op":"power","target":"web-01","state":"off"},{"op":"snapshot","target":"web-01","name":"pre-patch"}]' \
  --plan_desc "patch pre-check"
python3 scripts/handler.py --action plan --plan_action execute --plan_id <id>
python3 scripts/handler.py --action plan --plan_action rollback --plan_id <id>
```

## 5. IP 池

```bash
# 查看某网段可用 IP
python3 scripts/handler.py --action ip_pool --ip-action available --ip-spec 10.0.0.0/24

# 分配一个 IP（会写入本地占用表）
python3 scripts/handler.py --action ip_pool --ip-action allocate --ip-spec 10.0.0.0/24

# 释放已分配 IP
python3 scripts/handler.py --action ip_pool --ip-action release --ip-target 10.0.0.20
```

## 6. TTL 自动清理

```bash
# 给某台 VM 设置 60 分钟 TTL
python3 scripts/handler.py --action ttl --ttl_action set --hostname test-vm --ttl_minutes 60

# 查看 TTL 列表
python3 scripts/handler.py --action ttl --ttl_action list

# 手动触发一次到期清理（推荐挂 cron）
python3 scripts/handler.py --action ttl --ttl_action cleanup
```

## 7. 巡检 / 审计

```bash
# 事件（最近 60 分钟内的电源/迁移/快照/告警）
python3 scripts/handler.py --action events --minutes 60 --event_category power

# 资源配额展示
python3 scripts/handler.py --action quota --cluster CL01 --cpu_threshold 0.85

# 导出全量 VM 报表
python3 scripts/handler.py --action export --export_format html --output /tmp/vms.html

# 审计报表（HTML）
python3 scripts/handler.py --action audit_report --export_format html --output /tmp/vcenter-audit.html

# 审计日志查询
python3 scripts/handler.py --audit-query --action delete_vm --hostname web02
```

## 8. 密码与密钥

```bash
# 迁移 .env 中的密码到加密存储（推荐首次运行）
python3 scripts/handler.py --action secret --secret-action migrate

# 查看加密存储中已保存的键
python3 scripts/handler.py --action secret --secret-action list

# 设置一个新密钥
python3 scripts/handler.py --action secret --secret-action set \
  --secret-key VCENTER_PASSWORD --secret-value '***'

# 轮换主密钥（会重新加密所有 secret）
python3 scripts/handler.py --action secret --secret-action rotate
```

## 9. 删除操作（高危）

```bash
# 第 1 步：先扫描一下危险词（可选）
python3 scripts/handler.py --action danger --danger-action scan --danger-target web02

# 第 2 步：Dry-run 预演
python3 scripts/handler.py --dry-run --action delete_vm --hostname web02

# 第 3 步：正式删除（必须带 --confirmed）
python3 scripts/handler.py --action delete_vm --hostname web02 --confirmed
```

删除会自动打预删除快照，出错后可通过快照回滚。

## 10. 推荐 cron 任务

```cron
# 每小时清一次 TTL 到期 VM
0 * * * * cd /path/to/vcenter-ops && python3 scripts/handler.py --action ttl --ttl_action cleanup >> logs/ttl.log 2>&1

# 每天 03:00 导出审计报表
0 3 * * * cd /path/to/vcenter-ops && python3 scripts/handler.py --action audit_report --export_format html --output logs/audit-$(date +\%F).html >> logs/audit-cron.log 2>&1
```

## 11. 常见问题

- **连不上 vCenter**：先跑 `python3 scripts/healthcheck.py`，再核对 `config.yaml` 与 `.env` 里的 host / password_ref。
- **密码泄漏担忧**：改用 `secret_manager` 加密存储，不要把密码写进 `config.yaml`。
- **批量误操作**：先 `--dry-run`，再看输出的 `params` 是否符合预期，再去掉 `--dry-run` 正式执行。
- **删除不了 VM**：确认没有触发危险词校验，如果是有意为之请补 `--confirmed`；仍失败请查 `logs/audit.log`。
