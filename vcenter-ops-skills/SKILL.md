---
name: vcenter-ops-skills
description: 专门用于 VMware vCenter 的运维自动化技能。该技能支持从基础的资源巡检（Datacenter、Cluster、Host、Virtual Machine、Folder、Resource Pool、Template、Datastore Cluster、Datastore、vSphere Distributed Switch、vSwitch）到复杂的虚拟机生命周期管理（克隆、删除、更新）。当用户需要查看虚拟化环境状态、批量创建开发/测试环境、或者通过模板快速部署虚拟机时，请务必触发此技能。即使客户只是模糊地提到“检查一下服务器空间”或“给我弄台新的 Linux 机器”，也应优先考虑使用此技能来检查 vCenter 资源。
license: 完整条款请参阅 LICENSE.txt 文件。
---


```yaml
name: vcenter-ops-skills
description: 专门用于 VMware vCenter 的运维自动化技能。该技能支持从基础的资源巡检（Datacenter、Cluster、Host、Virtual Machine、Folder、Resource Pool、Template、Datastore Cluster、Datastore、vSphere Distributed Switch、vSwitch）到复杂的虚拟机生命周期管理（克隆、删除、更新）。
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
    ip: 
      type: string
      description: 指定 IP 地址
    host:
      type: string
      description: 指定宿主机

permissions:
  create: confirm
  delete: approval
```

---

### 📌 功能说明

vCenter Ops Skills
一个用于自动化管理 VMware vSphere 环境的专业技能集。

本技能的核心逻辑是：“先感知，后执行”。在进行任何变更动作（如克隆或删除）之前，技能会优先确认物理环境的边界和资源余量，以确保操作的原子性和安全性。

- **vCenterClient**：
    - 支持 Datacenter / Cluster / Datastore / Network / Template 查询
    - 宿主机查询（CPU/内存使用率、VM 数量、连接状态）
    - 集群资源概览（CPU/内存总量及已用量）
    - 按 CPU/内存空闲率自动排序宿主机
- **IP 分配**：
    - 集成钉钉文档状态查询 + 实时 Ping 检测（双重检查）
- **宿主机选择**：
    - 自动根据资源评分选择最优宿主机
    - 支持对话式引导用户手动选择
- **Planner**：
    - 整合 IP、宿主机、vCenter 资源信息，生成完整开通计划
    - 结构清晰，易于扩展
- **VM 克隆**：
    - 支持自定义 CPU/内存/硬盘规格
    - 支持指定宿主机、存储、网络和模板
    - 克隆完成后自动开机
- **Skill 交互**：
    - 智能对话引导用户逐步完成参数选择
    - 支持用户通过对话覆盖默认参数
    - 提交任务后实时返回 vCenter Task ID

### 🧠 工作流程
- 资源感知 (Discovery)：自动识别 vCenter 中的层级结构。
- 环境校验 (Validation)：在执行克隆等动作前，校验目标存储空间（Datastore）和网络（Network）的可用性。
- 任务执行 (Execution)：调用 pyvmomi 执行具体的增删改查动作。
- 异步跟踪 (Task Tracking)：针对克隆等耗时操作，持续监控 vCenter Task 进度，直到返回明确的成功或失败状态。

### 沟通准则

由于虚拟化运维涉及生产环境安全，沟通时请遵循以下原则：

- 明确资源路径：在操作前，清晰地向用户确认目标：例如“正在数据中心 [DC-01] 的 [Cluster-A] 集群中执行操作”。
- 风险提示：执行“删除（Delete）”或“关机（Power Off）”动作前，必须请求用户二次确认。
- 术语对齐：对于非专业用户，将 "Datastore" 解释为“存储池/硬盘空间”，将 "Inventory" 解释为“资产清单”。

---

### 技能指令集

#### 1. 资源巡检 (Inventory & Inspection)

用于获取 vCenter 的实时状态。

示例：

 - 输入：“查看目前有哪些虚拟机模板？”
 - 输出：返回 templates 列表及其分布的 datacenter。
 - 输入：“帮我找一个空间最足的存储。”
  - 输出：对比所有 datastores 的 freeSpace 并推荐最优项。

####2. 虚拟机置备 (Provisioning)

通过模板克隆新机器。这是本技能最复杂的原子动作。

置备逻辑：
- 模板定位：确认 template_name 存在且配置正确。
- 位置选择：确定目标 folder（文件夹）和 resource_pool（资源池）。
- 克隆配置 (RelocateSpec)：定义目标存储和主机。
- 自定义配置 (Customization)：处理 IP 分配、主机名修改等 OS 层面的初始化。

#### 3. 生命周期管理 (Lifecycle)

包含虚拟机的电源管理、配置更新和销毁。

- Update: 调整 CPU/内存配额。
- Delete: 从磁盘永久删除虚拟机（需谨慎）。

---

## 编写与测试规范

### 结构定义

技能代码应严格按照以下结构组织：

```markdown
vcenter-ops-skills/
├── main.py                 # 项目逻辑集成与本地测试入口
├── SKILL.md                # Required: metadata + instructions
├── assets/                 # 数据模板目录
├── scripts/
│   ├── client.py           # 封装连接逻辑 - 负责处理 SSL 验证、连接建立与断开。
│   ├── inventory.py        # 资源查询逻辑 - 利用 ContainerView 批量抓取资源，避免递归导致的 OOM 或超时。
│   ├── executor.py         # 动作处理逻辑 - 处理耗时的异步任务，如克隆和删除。
│   └── handler.py          # 分发请求逻辑 - 作为外部调用的统一入口。
└── references/             # 扩展文档目录
    └── terminology.md      # 术语解释
```

### 测试用例 (Test Cases)

在发布新版本技能前，请至少验证以下场景：

- 空结果处理：当指定的数据中心下没有任何集群时，不应报错，而应返回空列表。
- 重名校验：克隆时如果目标名称已存在，应提前拦截并提示。
- 连接超时：模拟 vCenter 登录失败的情况，确保有优雅的错误捕获。

### 写入样式建议

- 使用祈使句：例如“获取所有 Datacenter 列表”而非“如果你能的话请帮我拿一下列表”。
- 解释“为什么”：在代码注释中说明为何使用 CreateContainerView（为了在大规模环境下保持性能）。
- JSON 优先：所有内部技能通信均采用结构化 JSON，避免自然语言解析带来的歧义。

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

