# 资产/监控接入

目标：VM 生命周期形成 `创建 → 登记资产 → 生成监控目标 → 验证 → 删除/退役` 闭环。

## 1. 资产台账

数据文件：`data/assets.json`

登记/更新资产：

```bash
python3 scripts/asset_registry.py --action upsert \
  --vm-name "172.17.40.100-test-web01" \
  --ip "172.17.40.100" \
  --owner "yanghua" \
  --env "dev" \
  --app "web" \
  --cluster "MD1200" \
  --datastore "43.7-data" \
  --network "VLAN40" \
  --cpu 2 --memory-gb 4 --disk-gb 40 \
  --monitoring-status pending
```

查询：

```bash
python3 scripts/asset_registry.py --action list
python3 scripts/asset_registry.py --action get --vm-name "172.17.40.100-test-web01"
```

退役：

```bash
python3 scripts/asset_registry.py --action retire --vm-name "172.17.40.100-test-web01" --notes "deleted by change-xxx"
```

导出：

```bash
python3 scripts/asset_registry.py --action export --format markdown --output reports/assets.md
python3 scripts/asset_registry.py --action export --format csv --output reports/assets.csv
```

## 2. Prometheus file_sd

生成 file_sd：

```bash
python3 scripts/monitoring_integrator.py --action prometheus_sd --port 9100
```

输出：

```text
monitoring/vcenter-vms.file_sd.json
```

Prometheus 配置示例：

```yaml
scrape_configs:
  - job_name: vcenter-vms
    file_sd_configs:
      - files:
          - /root/.openclaw/workspace-infraops/skills/vcenter-ops/monitoring/vcenter-vms.file_sd.json
```

## 3. 监控状态

标记已接入：

```bash
python3 scripts/monitoring_integrator.py --action mark --vm-name "172.17.40.100-test-web01" --status enabled
```

检查未接入监控的资产：

```bash
python3 scripts/monitoring_integrator.py --action verify
```

## 4. VM 生命周期建议

### 克隆成功后

```bash
python3 scripts/asset_registry.py --action upsert ... --monitoring-status pending
python3 scripts/monitoring_integrator.py --action prometheus_sd
python3 scripts/monitoring_integrator.py --action verify
```

### 删除前

```bash
python3 scripts/asset_registry.py --action get --vm-name "<vm>"
python3 scripts/monitoring_integrator.py --action mark --vm-name "<vm>" --status disabled
python3 scripts/monitoring_integrator.py --action prometheus_sd
```

### 删除后

```bash
python3 scripts/asset_registry.py --action retire --vm-name "<vm>" --notes "deleted"
python3 scripts/monitoring_integrator.py --action prometheus_sd
```

## 5. 当前边界

- 当前只做本地资产台账和 Prometheus file_sd。
- 不直接写入夜莺、Categraf、CMDB、Prometheus 服务端。
- 外部系统接入需要后续提供 API 地址、Token、字段映射和审批确认。
