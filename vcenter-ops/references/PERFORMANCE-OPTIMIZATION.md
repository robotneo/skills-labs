# P1-P4 性能优化说明

## P1 减少 vCenter 实时 API 调用

新增：`scripts/inventory_cache_index.py`

```bash
python3 scripts/inventory_cache_index.py --action build
python3 scripts/inventory_cache_index.py --action query --name '<vm>'
python3 scripts/inventory_cache_index.py --action query --ip '<ip>'
```

数据：`data/inventory_index.json`

## P2 异步任务化

新增：`scripts/async_runner.py`

```bash
python3 scripts/async_runner.py --action submit --cmd 'python3 scripts/healthcheck.py'
python3 scripts/async_runner.py --action list
python3 scripts/async_runner.py --action status --task-id '<id>' --tail 20
```

数据：`data/async_tasks/`

## P3 交付 pipeline 可恢复状态

新增：`scripts/delivery_state.py`

```bash
python3 scripts/delivery_state.py --action create --vm-name '<vm>' --ip '<ip>' --owner '<owner>'
python3 scripts/delivery_state.py --action advance --delivery-id '<id>' --state prechecked
python3 scripts/delivery_state.py --action get --delivery-id '<id>'
```

数据：`data/deliveries/`

## P4 推荐算法增强

新增：`scripts/recommend_plus.py`

```bash
python3 scripts/recommend_plus.py --cpu 4 --memory 8 --disk 100 --top 3
```

逻辑：调用原 `recommend`，再结合最新 metrics 对高水位 datastore / 高内存 cluster 做扣分。

## 当前边界

- 以上均为非侵入式增强，暂未改 handler.py 主入口。
- 不执行真实 VM 创建/删除。
- recommend_plus 依赖已有 metrics 数据，metrics 过旧时建议先跑 observability_loop。
