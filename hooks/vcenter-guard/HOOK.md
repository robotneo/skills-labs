---
name: vcenter-guard
description: "企业级 vCenter 操作管控 Hook：自动路由到 vcenter-ops Skill，并管控高风险操作"
metadata:
  openclaw:
    emoji: "🛡️"
    events: ["message:preprocessed"]
---

# vcenter-guard

该 Hook 用于在消息进入 Agent 前进行统一的策略控制与安全管控。

它会拦截所有进入系统的消息，识别是否包含 vCenter / VMware 相关操作意图，并根据操作风险等级执行不同策略：

- **高风险操作**（如删除虚拟机）：推送安全警告，并引导用户必须通过标准流程执行  
- **普通操作**（如开关机、快照、查询）：自动推送路由提示，引导使用 vcenter-ops Skill  

---

## 🎯 设计目标

- 统一 vCenter 操作入口
- 防止绕过 Skill 直接执行底层命令
- 提供操作前风险提示与引导
- 为后续审计与安全策略提供基础

---

## ⏱ 触发时机

- `message:preprocessed`  
  在消息预处理完成后、发送给 Agent 之前触发，是进行输入侧策略控制的关键节点。

---

## ⚙️ 核心功能

### 1. 意图识别（Intent Detection）

- 自动识别 vCenter 相关操作
- 支持中英文关键词（如：vm / 虚拟机 / snapshot / 删除 等）

---

### 2. 风险分级控制（Risk Classification）

- **高风险操作**
  - 删除 / 销毁虚拟机等不可恢复操作
  - 推送安全警告
  - 强制引导走标准流程（vcenter-ops Skill）

- **普通操作**
  - 开机 / 关机 / 快照 / 查询等
  - 自动提示使用规范 Skill 执行

---

### 3. 路由提示（Routing Hint）

- 自动向 Agent 注入策略提示
- 引导 LLM 优先选择 `vcenter-ops` Skill
- 避免直接使用 system.run 等底层能力

---

### 4. 审计日志（Audit Logging）

- 记录用户输入内容
- 标记是否命中 vCenter 操作
- 为安全审计与行为分析提供数据支持

---

## 🧠 架构定位

该 Hook 属于：

> **输入策略层（Input Policy Layer）**

在整个系统中的作用：

```text
User Input
   ↓
message:received
   ↓
message:preprocessed   ← 🛡️ vcenter-guard（本 Hook）
   ↓
Agent（LLM）
   ↓
Skill / Tool 执行