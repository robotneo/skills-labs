# vcenter-ops Observability Loop

> 目标：保证 `metrics → healthcheck → anomaly → forecast → report` 闭环可持续运行。

## 手动执行

```bash
cd /root/.openclaw/workspace-infraops/skills/vcenter-ops
./scripts/observability_loop.sh
```

## 单步命令

```bash
# 采集 vCenter 指标
python3 scripts/handler.py --action metrics --metrics-action collect

# 健康自检，目标 10/10
python3 scripts/healthcheck.py

# 查询近 1 天指标
python3 scripts/handler.py --action metrics --metrics-action query --metric-days 1

# 异常检测
python3 scripts/handler.py --action anomaly --metric-days 7

# 容量预测，建议至少 10 个样本以上
python3 scripts/handler.py --action forecast --metric-days 60 --forecast-threshold 0.9

# 资源推荐
python3 scripts/handler.py --action recommend --cpu 4 --memory 8 --disk 100 --recommend-top 3
```

## 推荐 crontab

```cron
# vcenter-ops observability loop
*/5 * * * * cd /root/.openclaw/workspace-infraops/skills/vcenter-ops && ./scripts/observability_loop.sh
```

## 输出文件

```text
logs/observability_loop-YYYY-MM-DD.log
reports/healthcheck-latest.md
reports/anomaly-latest.json
reports/forecast-latest.json
data/metrics/YYYY-MM-DD.jsonl
```

## 验收标准

```text
healthcheck: 10/10
metrics: 当天 jsonl 存在且行数 > 0
anomaly: 可输出异常或空列表
forecast: 可执行；样本不足时返回 insufficient_data，不视为执行失败
recommend: 可输出 Top-N 推荐
```

## 当前注意事项

容量预测至少需要 10 个样本。刚恢复采集后，真实生产 datastore 可能只有 1-2 个样本，会返回：

```text
样本不足 (N/10)，无法预测
```

这表示预测模型可用，但历史数据不足。连续采集后会自动恢复有效预测。
