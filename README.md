# skills-labs

这里存放了我日常使用的效率提升与运维开发相关的 Codex Skills 与 Hooks。仓库定位是「个人 Skills 实验室」——面向单人 IT 管理员场景，包含长期迭代的运维自动化 Skill、零依赖的桌面小工具，以及围绕 Skill 的安全/路由 Hook。

## 目录一览

| 类型 | 名称 | 作用 |
| --- | --- | --- |
| Skill | `vcenter-ops` | VMware vCenter 单人管理员运维自动化 |
| Skill | `wifi-health-detector` | macOS / Windows Wi-Fi 健康度检测 |
| Hook | `hooks/vcenter-guard` | vCenter 操作前置管控与安全路由 |

---

## Skills

### vcenter-ops

- **Skill 名称**：`vcenter-ops`
- **当前版本**：v2.0（solo-admin edition）
- **入口**：`scripts/handler.py`
- **核心定位**：把单人 IT 管理员每天的 vCenter 常规操作（查询 / 交付 / 电源 / 快照 / 迁移 / 批量）折叠成一条对话指令，可 Dry-Run、可回滚、可审计。

**能力矩阵**

- 生命周期：清单查询、克隆交付、电源控制、快照管理、硬件热调整、删除销毁
- 高级操作：vMotion 跨宿主机热迁移、Guest OS 命令执行、模板 / VM 互转、数据存储浏览
- 编排与批量：Plan / Apply 多步事务 + 回滚、通配符批量操作、TTL 自动清理、预设 / 历史复用
- 安全底座：Dry-Run 预演、危险词二次确认、删除三层校验、审计日志、加密密钥（Fernet）
- 观测与运营：资源配额检查、事件查询、库存导出（JSON / CSV / Markdown / HTML）、IP 池管理

**安全特性**

- 删除类操作强制走 `_validate_delete_target()` 三层校验（禁止通配 / 保留名单 / 显式命名）
- 危险词二次确认：命中黑名单的操作必须携带 `--confirmed` 才能落地
- 密码通过 `--pwd` → `config.yaml` 明文 → `secret_manager` 加密存储 → `.env` / 环境变量四级回退加载
- 所有变更操作支持 `--dry-run` 预演，且 Dry-Run 与实际执行走同一套参数解析

**常用示例**

```bash
# 全量清单
python3 vcenter-ops/scripts/handler.py --action list_all

# 克隆虚拟机（先 Dry-Run，再实际交付）
python3 vcenter-ops/scripts/handler.py --action clone_vm --dry-run \
  --hostname web-01 --template ubuntu22-tmpl --dc DC1 --cluster C1 \
  --ds DS1 --network VLAN10 --ip 10.0.0.11 --mask 255.255.255.0 --gw 10.0.0.1

# 批量开机（支持 * / ? 通配符）
python3 vcenter-ops/scripts/handler.py --action batch \
  --batch-action power --pattern 'web-*' --state on
```

### wifi-health-detector

- **Skill 名称**：`wifi-health-detector`
- **入口**：`main.py`
- **平台支持**：macOS / Windows
- **依赖**：零第三方依赖，Python 3.7+
- **核心定位**：一键采集当前 Wi-Fi 硬件参数与本地网络质量，输出健康评分与优化建议

**输出内容**

1. `📶 无线网络核心参数`（Markdown 表格）：IP、网关、SSID、频段、信号强度、协商速率、信道宽度、信道、同频干扰、MAC、时延、丢包、加密类型
2. `🌐 当前网络状态`：健康评分、稳定性评估、主要问题、优化建议

**使用示例**

```bash
python3 wifi-health-detector/main.py
python3 wifi-health-detector/main.py --interface en0
```

建议本地或提权执行；沙箱内运行会影响时延、丢包与 Wi-Fi 扫描等指标的准确性。

## Hooks

### vcenter-guard

- **Hook 名称**：`vcenter-guard`
- **入口**：`hooks/vcenter-guard/handler.ts`
- **触发时机**：`message:preprocessed`（消息进入 Agent 之前）
- **核心定位**：企业级 vCenter 操作管控 Hook，统一入口 + 高风险操作拦截

**策略分级**

- 高风险操作（如删除虚拟机）：推送安全警告，强制走标准审批流程
- 普通操作（开关机、快照、查询等）：自动推送路由提示，引导使用 `vcenter-ops` Skill

**设计目标**

- 统一 vCenter 操作入口，防止绕过 Skill 直接执行底层命令
- 提供操作前风险提示与流程引导
- 为后续审计与安全策略提供基础
