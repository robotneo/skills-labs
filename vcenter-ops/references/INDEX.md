# vCenter Ops 文档索引

## 入口文档

- `../SKILL.md`：Skill 触发规则、入口命令、关键安全约束。
- `ACTION-MATRIX.md`：action 风险等级与命令示例。
- `SCHEMA.md`：完整 CLI 参数说明。
- `USER-GUIDE.md`：面向日常使用的操作手册。
- `OPS-RUNBOOK.md`：生产运维 Runbook、备份、恢复、故障处理。

## 专题流程

- `CLONE-FLOW.md`：克隆 VM 标准流程与预检查。
- `DELIVERY-FLOW.md`：标准交付与初始化流程。
- `CACHE-STRATEGY.md`：库存缓存刷新与复用策略。
- `PERMISSION-SYSTEM.md`：权限、审批、危险操作分级。
- `SAFETY-GATE.md`：安全门禁与高风险操作拦截。

## 能力说明

- `ASSET-MONITORING.md`：资产监控集成。
- `OBSERVABILITY-LOOP.md`：可观测闭环。
- `PERFORMANCE-OPTIMIZATION.md`：性能优化说明。
- `RESOURCE-DISPLAY.md`：资源展示格式。
- `DESIGN.md`：设计说明。
- `REFERENCE.md`：补充参考。

## 版本治理

- `VERSION-MATRIX.md`：版本能力矩阵。
- `CHANGELOG.md`：变更记录。
- `ROADMAP.md`：后续路线。

## 整理原则

- `SKILL.md` 保持精简，只放触发、入口、硬性安全规则。
- 长示例、Runbook、版本记录统一放入 `references/`。
- `scripts/` 只放可执行脚本；`tests/` 只放测试；`assets/` 只放模板资源。
- 不提交 `.env`、运行数据、缓存、pycache、pytest 缓存。
