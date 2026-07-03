# vCenter Ops Roadmap

## 已发布

| 版本 | 日期 | 主题 | 模块数 |
|------|------|------|--------|
| v0.9 | 2026-05-21 | 稳定性底座 | 4 |
| v1.0 | 2026-05-22 | 用户体验 | 5 |
| v1.1 | 2026-05-22 | 规模化协作 | 5 |
| v1.2 | 2026-05-22 | 可观测增强 | 2（+executor改造） |
| v1.3 | 2026-05-22 | 安全合规 | 5 |
| v1.4 | 2026-05-22 | 智能化 | 4 |

**累计 35 个 Python 模块 / 约 400 KB / 24 单测 / 真实 vCenter 验证通过**

## v1.5 候选（待用户决策）

### 主题 A：多 vCenter 统管（约 5 天）
- `vcenter_registry.py`: 多个 vCenter 实例注册/切换
- `cross_vc_search.py`: 全局 VM 搜索
- handler `--vcenter <name>` 参数支持

### 主题 B：灾备 / DR（约 7 天）
- `replication.py`: 跨集群 VM 复制（基于克隆+vMotion）
- `snapshot_export.py`: 模板/快照外送（OVA/OVF）
- `dr_drill.py`: 灾备演练编排（拉起备机+网络切换）

### 主题 C：资源回收（约 3 天）
- `idle_detector.py`: 闲置 VM 识别（30 天 CPU < 5%）
- `resource_reclaim.py`: 自动 TTL 提议 + 通知到拥有者

### 主题 D：Cost 视图（约 4 天）
- `cost_calculator.py`: 按 VM 规格/运行时长打分
- `cost_report.py`: 按 cluster/项目/owner 维度报表
- 集成到 HTML 审计报表

### 主题 E：审批工作流（约 5 天）
- `approval_dingtalk.py`: 钉钉审批集成
- `approval_wecom.py`: 企微审批集成
- 替换当前占位实现

### 主题 F：自助门户（约 10 天）
- FastAPI Web UI 包装 handler
- Vue 前端：克隆向导/批量/历史/审批/告警面板
- 单点登录集成

## 决策建议

| 优先级 | 主题 | 理由 |
|--------|------|------|
| 🔥 高 | C 资源回收 | 立即省钱 + 低风险 |
| 🔥 高 | E 审批集成 | v1.3 安全门最后一块拼图 |
| 中 | A 多 vCenter | 适合中大型组织 |
| 中 | D Cost 视图 | 财务/管理层喜欢看 |
| 低 | B 灾备 | 工程量大，需配套基础设施 |
| 低 | F 自助门户 | 工程量大，但用户体验提升明显 |

## 推荐 v1.5 范围

**方案 1**：C + E（约 8 天）— 闭环安全+成本，最务实
**方案 2**：A + D（约 9 天）— 多 vCenter + 成本看板
**方案 3**：完整 F（约 10 天）— 一步到位上 Web 界面

待用户决策。
