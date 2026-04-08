# 设计规范

- 格式：标准 `AgentSkills` 形态
- 模式：`SKILL.md` + `Python`

- 结构：

    ✅ SKILL.md = 唯一入口（metadata + 说明）
    
    ✅ Python 全部放入 scripts/

    ✅ 数据和模板归档到 assets/

    ✅ 说明文档沉淀到 references/

    ✅ 后续可直接接 vCenter / 钉钉文档 / JumpServer

目录：

```markdown
vcenter-ops/
├── main.py                 # 项目逻辑集成与本地测试入口
├── SKILL.md                # OpenClaw 技能描述 (Agent 调用的灵魂)
├── requirements.txt        # 依赖包 (pyvmomi)
├── assets/                 # 存放 JSON 配置或自定义规范模板
├── scripts/
│   ├── client.py           # 连接层
│   ├── inventory.py        # 查询层
│   ├── executor.py         # 动作层
│   └── handler.py          # 接口层 (用于 OpenClaw 命令行对接)
└── references/             # 说明文档层
    ├── DESIGN.md         # 设计规范
    └── REFERENCE.md      # 接口参考
```

为何还需要 main.py?

- 解耦与测试：handler.py 是给机器人（OpenClaw）用的，参数非常琐碎；而 main.py 是给你（开发者）用的，可以直接配置参数一键运行。
- 智能置备演示：在 main.py 中，我加入了一段简单的排序逻辑（第 3 步），它能自动选择空间最大的存储。这正是你 DeepNet-Ops 项目中“智能运维”的核心体现。
- 调试闭环：它完整覆盖了从 Connect -> Get -> Action -> Verify -> Disconnect 的生命周期。

### 项目测试

在调试开发时，验证脚本的可行性，可以如下验证：

```bash
# 1. 安装依赖
pip install pyvmomi

# 2. 修改 main.py 中的 VC_CONFIG 信息

# 3. 运行测试
python3 main.py
```