---
# OpenClaw Skill: vCenter Provisioning Agent
# Author: xiaofei
# Description: 自动化虚拟机创建流程（IP 分配 + 宿主机调度）
---

```yaml
name: vcenter_provision
description: "自动化创建 vCenter 虚拟机。包含 IP 自动分配、宿主机资源评分调度、权限控制以及二次确认流程。"
version: 0.1.0

entrypoint: scripts/main.py

input_schema:
  type: object
  required:
    - hostname
  properties:
    hostname:
      type: string
      description: 虚拟机名称
    cpu:
      type: number
      default: 4
    memory:
      type: number
      default: 8
    disk:
      type: number
      default: 100
    os:
      type: string
      default: ubuntu
    host:
      type: string
      description: 指定宿主机

permissions:
  create: confirm
  delete: approval
```

---

### 📌 功能说明

该 Skill 用于自动化完成 vCenter 虚拟机创建流程：

- 自动分配 IP（文档 + Ping 检测）
- 自动选择宿主机（资源评分）
- 支持用户指定宿主机
- 创建前二次确认
- 输出标准化开通信息

### 🧠 工作流程

1. 用户输入创建请求
2. 自动分配 IP（或用户指定）
3. 自动选择宿主机（或用户指定）
4. 生成创建计划
5. 用户确认
6. 执行创建（当前为模拟）
7. 输出开通信息

### 📐 IP 分配规则

| 文档状态 | Ping结果 | 是否可用  |
| ---- | ------ | ----- |
| 未使用  | 不通     | ✅ 可用  |
| 未使用  | 通      | ❌ 冲突  |
| 已使用  | 不通     | ⚠️ 可疑 |
| 已使用  | 通      | ❌ 已占用 |

### ⚙️ 宿主机调度策略

- score = CPU剩余 * 0.5 + 内存剩余 * 0.4
- 自动选择评分最高的宿主机
- 用户可手动指定宿主机，优先使用用户指定值

### 🔌 扩展方向

- vCenter API 自动克隆虚拟机
- 钉钉文档 IP 池接入
- 审批流接入
- JumpServer 权限自动化
- 输出模板可自定义

### 📂 目录说明

```markdown
skill-vcenter-provision/
├── SKILL.md          # Required: metadata + instructions
├── scripts/          # 执行代码
├── assets/           # 数据 & 模板
├── references/       # 扩展文档
└── requirements.txt  # Python依赖
```

