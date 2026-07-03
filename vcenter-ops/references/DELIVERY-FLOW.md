# 标准交付流程

目标：一句话创建 VM 后，形成标准闭环：

```text
需求参数 → 巡检 → 推荐 → IP 检查 → 克隆 → 验证 → 登记资产 → 生成监控 file_sd → 交付报告
```

## 1. 安全模式

默认只生成计划，不执行克隆：

```bash
python3 scripts/delivery_pipeline.py --action plan \
  --name demo-web01 \
  --ip 172.17.40.100 \
  --owner yanghua \
  --env dev \
  --app web \
  --template Ubuntu20.04-template \
  --dc DC \
  --cluster MD1200 \
  --datastore 43.7-data \
  --network VLAN40 \
  --gateway 172.17.40.1
```

输出：

```text
reports/delivery-<vm>-<timestamp>.md
reports/delivery-<vm>-<timestamp>.json
```

## 2. 执行模式

真实执行需要显式确认：

```bash
python3 scripts/delivery_pipeline.py --action execute --confirm ...
```

如果只想验证资产/监控闭环，不执行克隆：

```bash
python3 scripts/delivery_pipeline.py --action execute --confirm --skip-clone ...
```

## 3. 验证模式

```bash
python3 scripts/delivery_pipeline.py --action verify \
  --name demo-web01 \
  --ip 172.17.40.100 \
  --owner yanghua \
  --template Ubuntu20.04-template \
  --dc DC \
  --cluster MD1200 \
  --datastore 43.7-data \
  --network VLAN40 \
  --gateway 172.17.40.1
```

## 4. 交付验收标准

```text
healthcheck 10/10
VM 查询成功
资产已写入 data/assets.json
monitoring/vcenter-vms.file_sd.json 已生成
monitoring verify missing_monitoring = 0
交付报告已生成
审计日志有关键操作记录
```

## 5. 当前边界

- 默认不接入外部 CMDB/夜莺/Categraf。
- Prometheus 只生成 file_sd 文件，不改服务端配置。
- 删除流程仍走 `references/OPS-RUNBOOK.md` 的删除标准流程。

## 6. handler 统一入口

计划：

```bash
python3 scripts/handler.py --action delivery --delivery-action plan \
  --name demo-web01 --ip 172.17.40.100 --owner yanghua \
  --template Ubuntu20.04-template --dc DC --cluster MD1200 \
  --datastore 43.7-data --network VLAN40 --gateway 172.17.40.1
```

执行需要确认：

```bash
python3 scripts/handler.py --action delivery --delivery-action execute --delivery-confirm ...
```

克隆后初始化：

```bash
python3 scripts/handler.py --action post_init --hostname 172.17.40.100-demo-web01 --ip 172.17.40.100 --ssh-check
```
