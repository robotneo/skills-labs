```yaml
name: vcenter-ops
description: 专门用于 VMware vCenter 的运维自动化技能。支持从全栈资源巡检到复杂的虚拟机生命周期管理（克隆、删除、规格更新）。
# license: Proprietary. LICENSE.txt has complete terms
compatibility: Requires Python 3.10+
metadata:
  author: xiaofei
  version: 0.1.0

entrypoint: scripts/handler.py

Permissions:
  create: confirm (需用户确认规格)
  delete: approval (需管理层审批)

input_schema:
  type: object
  required: [hostname, action]
  properties:
    action: { type: string, enum: [list_all, get_vm, clone_vm, delete_vm, power_vm] }
    hostname: { type: string, description: "虚拟机名称" }
    cpu: { type: number, default: 4 }
    memory: { type: number, default: 8, description: "单位 GB" }
    disk: { type: number, default: 100, description: "单位 GB" }
    ip: { type: string, description: "静态 IP 地址" }
    host_node: { type: string, description: "指定物理宿主机" }
    network: { type: string, description: "目标网络名称" }
    template: { type: string, description: "源模板名称" }
```

---

### 📌 功能说明

vCenter Ops 技能：一个用于自动化管理 VMware vSphere 环境的专业技能集。

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

### 🧠 核心工作流 (Workflow)
- 资源感知 (Discovery)：调用 inventory.py 自动识别 vCenter 层级，提取 Datastore 水位与 Host 负载。
- 环境校验 (Validation)：执行克隆前，校验存储剩余空间是否满足 disk 参数，校验 network 是否存在。
- 决策辅助 (Decision)：
  - IP 校验：对比钉钉文档 IP 池状态 + 实时 Ping 检测。
  - 宿主机调度：计算 Score = CPU剩余 * 0.5 + 内存剩余 * 0.4，自动推荐最优 Host。
- 任务执行 (Execution)：调用 executor.py 下发异步 Task，支持硬件规格重配置与 CustomizationSpec 网络注入。
- 异步跟踪 (Tracking)：实时返回 vCenter Task ID，监控进度直至 Success。

### 沟通准则

由于虚拟化运维涉及生产环境安全，沟通时请遵循以下原则：

- 明确资源路径：在操作前，清晰地向用户确认目标：例如“正在数据中心 [DC-01] 的 [Cluster-A] 集群中执行操作”。
- 风险提示：执行“删除（Delete）”或“关机（Power Off）”动作前，必须请求用户二次确认。
- 术语对齐：对于非专业用户，将 "Datastore" 解释为“存储池/硬盘空间”，将 "Inventory" 解释为“资产清单”。

其他术语解释：See [the reference guide](references/REFERENCE.md) for details.

---

### 📋 技能指令集 (Commands)

1. 资源巡检与状态报告

    - 目标: 获取环境画像或定位存储/宿主机。
    - 示例: python scripts/handler.py --action list_all
    - 逻辑: 返回 datastores (含 is_low_space 标记) 和 hosts (含 maintenance_mode)。

2. 虚拟机高级置备 (Provisioning)

    - 目标: 从模板快速部署并初始化系统。
    - 关键逻辑: 整合模板定位 -> 位置选择 -> 规格调整 -> IP 注入。
    - 典型命令:

```bash
python scripts/handler.py --action clone_vm --hostname "SVR-PROD-01" \
  --template "CentOS-7-Temp" --cpu 8 --memory 16 --disk 200 \
  --ip "10.0.x.x" --mask "255.255.255.0" --gw "10.0.x.1" \
  --network "VM-Network" --host_node "esxi-node-05"
```

3. 生命周期管理

    - 更新: 调整现有 VM 的 CPU/内存。
    - 删除: 永久销毁（触发 approval 流程）。
    - 电源: on/off/reset 操作。

---

### 🚦 决策规则与安全准则

📐 IP 分配矩阵

| 钉钉文档状态 | Ping 结果 | 最终决策 | 动作         |
|--------------|-----------|----------|--------------|
| 未使用       | 不通      | ✅ 可用   | 继续克隆     |
| 未使用       | 通        | ❌ 冲突   | 报错并记录日志 |
| 已使用       | 不通      | ⚠️ 异常   | 提示用户二次确认 |
| 已使用       | 通        | ❌ 占用   | 拒绝分配     |

⚙️ 宿主机调度策略

- 策略: 自动选择评分最高的宿主机。
- 人工干预: 用户在对话中手动指定的 host_node 拥有最高优先级。

💬 沟通准则 (Agent Style)

- 透明化: 操作前必须告知路径：“正在 [DC-01]/[Cluster-A] 执行操作”。
- 降维解释: 将 "Datastore" 称为 “存储池”，将 "Snapshot" 称为 “快照点”。
- 原子性: 只有当 IP、宿主机、存储均校验通过时，才下发克隆指令。

---

### 📂 工程目录结构

```markdown
vcenter-ops-skills/
├── main.py                 # 项目逻辑集成与本地测试入口
├── SKILL.md                # OpenClaw 技能描述 (Agent 调用的灵魂)
├── requirements.txt        # 依赖包 (pyvmomi)
├── assets/                 # 存放 JSON 配置或自定义规范模板
├── scripts/
│   ├── client.py           # 连接层
│   ├── inventory.py        # 查询层
│   ├── executor.py         # 动作层
│   └── handler.py          # 接口层 (用于 OpenClaw 命令行对接)
└── references/
    └── REFERENCE.md      # 文档层
```

### 🧪 测试用例 (Test Cases)

- 重名拦截: 若 hostname 已存在，立即返回 status: fail。
- 静默失败: 模拟断网，确保 handler.py 捕获 ConnectionError 并输出 JSON 格式错误。
- 规格越界: 若申请 disk 超过 Datastore 剩余空间，提前拦截。

---

### 🔌 扩展方向

- vCenter API 自动克隆虚拟机
- 钉钉文档 IP 池接入
- 审批流接入
- JumpServer 权限自动化
- 输出模板可自定义
